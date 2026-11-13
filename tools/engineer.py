"""Engineer's guard - the script half of the self-fixing loop. Plain Python, zero Claude tokens.

    python tools/engineer.py tickets    # what the Engineer has been asked to look at
    python tools/engineer.py check      # guard + full test suite on the working tree (changes nothing)

The loop: prepare() turns what went wrong (failed roles, failed data refreshes, scans that could not be re-run,
Scorekeeper diagnoses, the Auditor's report) into state/engineer_tickets.md and wakes the Engineer. The Engineer
edits code. finish() - never the Engineer - then decides whether the edit stays: every changed file must be on the
EDITABLE list, added lines must pass the static checks, and the whole test suite must pass. Otherwise every code
change of that run is rolled back. The dispatcher commits what survives; registry/engineer_log.csv is the record.

Why static checks as well as permission files: tools/*.py run from Task Scheduler with no permission file around
them, so an edit to one could otherwise reach anything the permissions forbid. The Engineer also can't run the
code it edits: its only way to execute anything is `check`, which runs the guard first.
"""
from __future__ import annotations

import csv
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, timedelta

from common import STATE, TEAM, load_json, log, post, save_json

STATEF = STATE / "engineer.json"
TICKETS = STATE / "engineer_tickets.md"
RECORD = TEAM / "registry" / "engineer_log.csv"
USER = "Team - Engineer"
MAX_FILES, MAX_ADDED = 6, 250
MAX_ATTEMPTS = 2       # the same problem twice unfixed goes to the user instead of burning more runs

# Machinery only. NOT here, on purpose: gate, budget, jobs, ideas, paper_runner, research_data, quotes, fill_costs,
# integrity, outlook (they decide or score results); dispatch, common, plan_limit, this file (they run the agents).
EDITABLE = ["tools/catalog.py", "tools/daily_bars.py", "tools/daily_report.py", "tools/edgar.py",
            "tools/evening_check.py", "tools/ops_monitor.py", "tools/scan_ops.py", "tools/screen.py",
            "prompts/scorekeeper.md", "prompts/scout.md", "tests/test_eng_*.py"]
GUARDED = ("tools/", "prompts/", "tests/", "team/", "TEAM.md")

# Added lines of Python may not reach outside the job: processes, network, secrets, schedules, rules, results.
FORBIDDEN_PY = [r"\bsubprocess\b", r"\bos\.(system|popen|exec|spawn|remove|unlink|environ)", r"\b(eval|exec|compile)\(",
                r"__import__", r"\bimportlib\b", r"\bsocket\b", r"\burllib\b", r"\brequests\b", r"\bhttpx\b",
                r"\brmtree\b", r"\.unlink\(", r"ScheduledTask", r"schtasks", r"\.env\b", r"registry\.json",
                r"\bshutil\b", r"\bos\.(replace|rename|makedirs|chmod)", r"\bctypes\b", r"\bbuiltins\b",
                r"\bglobals\(",
                r"ideas\.csv", r"trials\.csv", r"decisions\.csv", r"schedule\.json", r"real_price_rules",
                r"fill_costs\.json", r"settings", r"place_\w*instruction", r"\bholdout\b", r"\bSTOP\b",
                r"\bLIVE_V[234]\b", r"\bgit\b", r"\bclaude\b"]
# tools/ code only (2026-11-13): new ways to write or move files. Not tests - they build fixtures in tmp_path with
# exactly these calls, and anything a test writes inside the repo is caught by finish()'s after-test check.
# (A regex list is a speed bump, not a sandbox - e.g. a file name built from pieces gets past it. The real limits
# are the editable list, the after-test check, every change being a visible commit, and the Auditor's review.)
FORBIDDEN_TOOL_PY = [r"\.(symlink_to|chmod)\(", r"\bopen\([^)]*['\"](w|a|x|r\+)"]
# A prompt edit may add guidance, not remove a limit.
LIMIT_WORDS = re.compile(r"\b(never|frozen|must|hard rule|don't|do not|not allowed|forbid\w*|only)\b", re.I)


@dataclass
class Change:
    path: str
    status: str           # git porcelain XY: " M", "??", " D"...


def _run_git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=TEAM, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout       # not stripped: the leading space of a porcelain status is meaningful


def code_changes() -> list[Change]:
    out = []
    for entry in _run_git("status", "--porcelain=v1", "-z", "--untracked-files=all").split("\0"):
        if len(entry) > 3 and entry[3:].startswith(GUARDED):
            out.append(Change(entry[3:], entry[:2]))
    return out


def _status_all() -> dict[str, str]:
    """Every changed or new file in the repo (not just GUARDED ones): path -> porcelain status + size."""
    out = {}
    for entry in _run_git("status", "--porcelain=v1", "-z", "--untracked-files=all").split("\0"):
        if len(entry) > 3:
            f = TEAM / entry[3:]
            out[entry[3:]] = entry[:2] + (f":{f.stat().st_size}" if f.is_file() else "")
    return out


def editable(path: str) -> bool:
    return any(fnmatch.fnmatch(path, p) for p in EDITABLE)


def _lines(c: Change) -> tuple[list[str], list[str]]:
    """(added, removed) lines of one changed file."""
    if c.status == "??":
        return (TEAM / c.path).read_text(encoding="utf-8", errors="replace").splitlines(), []
    diff = _run_git("diff", "HEAD", "--", c.path).splitlines()
    return ([l[1:] for l in diff if l.startswith("+") and not l.startswith("+++")],
            [l[1:] for l in diff if l.startswith("-") and not l.startswith("---")])


def review(changes: list[Change]) -> list[str]:
    """Why these changes may not stay. Empty = the guard accepts them (the tests still have to pass)."""
    problems = [f"{c.path}: not on the Engineer's editable list" for c in changes if not editable(c.path)]
    problems += [f"{c.path}: deleted (the Engineer never deletes files)" for c in changes if "D" in c.status]
    if len(changes) > MAX_FILES:
        problems.append(f"{len(changes)} files changed (max {MAX_FILES}) - too big for an unattended fix")
    total = 0
    for c in changes:
        if not (TEAM / c.path).is_file():
            continue
        added, removed = _lines(c)
        total += len(added)
        if c.path.endswith(".py"):
            rules = FORBIDDEN_PY + (FORBIDDEN_TOOL_PY if c.path.startswith("tools/") else [])
            for line in added:
                if hit := next((rx for rx in rules if re.search(rx, line)), None):
                    problems.append(f"{c.path}: added line matches forbidden pattern {hit}: {line.strip()[:100]}")
        elif c.path.endswith(".md"):
            problems += [f"{c.path}: removes a limit: {l.strip()[:100]}" for l in removed if LIMIT_WORDS.search(l)]
    if total > MAX_ADDED:
        problems.append(f"{total} lines added (max {MAX_ADDED}) - too big for an unattended fix")
    return problems


def run_tests() -> tuple[bool, str]:
    env = dict(os.environ, TEAM_DRY_RUN="1")
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "--tb=short"], cwd=TEAM, env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
    except subprocess.TimeoutExpired:
        return False, "tests timed out after 10 minutes"
    return r.returncode == 0, (r.stdout + r.stderr)[-1500:]


def revert(changes: list[Change]) -> None:
    """Undo exactly the listed files: restore tracked ones, remove ones this run created."""
    for c in changes:
        if c.status == "??":
            (TEAM / c.path).unlink(missing_ok=True)
        else:
            _run_git("checkout", "HEAD", "--", c.path)


def _record(today: date, result: str, changes: list[Change], why: str) -> None:
    new = not RECORD.exists()
    with open(RECORD, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["date", "result", "files", "why"])
        w.writerow([str(today), result, " ".join(c.path for c in changes), why[:500]])


def mark_handled(status: str) -> None:
    """A finished Engineer run has looked at every ticket it was given: don't hand those occurrences over again
    (fixed, or turned into a proposal - either way re-reading them is wasted Opus time). Kept for 3 weeks."""
    if status != "ok":
        return
    st = load_json(STATEF, {})
    handled = st.get("handled", []) + [u for u in st.get("pending", []) if u not in st.get("handled", [])]
    save_json(STATEF, {**st, "handled": handled[-300:], "pending": []})


def finish(today: date, status: str) -> str:
    """After an Engineer run, before the dispatcher commits: keep the code changes or roll all of them back."""
    mark_handled(status)
    changes = code_changes()
    if not changes:
        return "no code changes"
    problems = [] if status == "ok" else [f"the run ended with status {status}"]
    before = _status_all()
    try:
        problems += review(changes)
        if not problems:
            ok, output = run_tests()
            if not ok:
                problems.append("tests failed: " + output[-400:])
            # Anything that appeared or changed WHILE the tests ran was written by test code: it is never reviewed
            # and would be swept into the next commit (git add -A). Name it, undo it, and refuse the run.
            during = [Change(path, st[:2]) for path, st in _status_all().items() if before.get(path) != st]
            if during:
                problems.append("tests wrote outside the job: " + ", ".join(c.path for c in during)[:300])
                revert(during)
    except Exception as e:  # noqa: BLE001 - when the guard itself breaks, nothing stays
        problems.append(f"guard error: {e}")
    names = ", ".join(c.path for c in changes)
    if problems:
        revert(changes)
        _record(today, "rolled_back", changes, "; ".join(problems))
        post("ops", f"↩️ Engineer's changes were rolled back ({names}). Why: {'; '.join(problems)[:900]}", USER)
        log(f"engineer: rolled back {names}: {problems}", "dispatch")
        return "rolled back"
    _record(today, "applied", changes, "guard and tests passed")
    post("ops", f"🛠️ Engineer's fix is in, guard and all tests passed: {names}. "
                f"Details: reports/{today}-engineer.md", USER)
    log(f"engineer: applied {names}", "dispatch")
    return "applied"


# ---------- what needs fixing ----------

def _days(since: str, today: date) -> list[str]:
    start = date.fromisoformat(since) + timedelta(days=1)
    return [str(start + timedelta(days=i)) for i in range((today - start).days + 1)]


def collect(today: date, since: str) -> tuple[list[str], list[str]]:
    """(urgent, weekly) problems newer than `since`. Urgent ones wake the Engineer on any dispatch day."""
    days, urgent, weekly = _days(since, today), [], []
    usage = STATE / "usage.csv"
    if usage.exists():
        for line in usage.read_text(encoding="utf-8").splitlines()[1:]:
            p = line.split(",")
            if p[0] in days and p[-1] == "failed" and p[1] != "engineer":
                urgent.append(f"Role {p[1]} failed on {p[0]} - see state/logs/{p[0]}-{p[1]}.json")
    for i in load_json(STATE / "scan_ops.json", {}).get("issues", []):
        if i["date"] in days:
            urgent.append(f"Scan {i['job']} {i['problem']} on {i['date']} and could not be re-run validly")
    for d in days:
        f = STATE / "logs" / f"{d}-dispatch.log"
        if f.exists():
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                # SEC answers 403 for a daily index it hasn't published yet - normal
                if " failed: " in line and not ("edgar update failed" in line and "403" in line):
                    urgent.append(f"Dispatch on {d}: {line[20:300]}")
        if (TEAM / "reports" / f"{d}-diagnosis.md").exists():
            urgent.append(f"Scorekeeper diagnosis to act on: reports/{d}-diagnosis.md")
        if (TEAM / "reports" / f"{d}-auditor.md").exists():
            weekly.append(f"Auditor report: reports/{d}-auditor.md - act on the recommendations addressed to you "
                          "and any machinery CONCERN")
        for log_file in (STATE / "logs").glob(f"{d}-*.json"):
            try:
                denied = json.loads(log_file.read_text(encoding="utf-8")).get("permission_denials") or []
            except (json.JSONDecodeError, OSError):
                continue
            for x in denied[:5]:
                cmd = (x.get("tool_input") or {}).get("command", x.get("tool_name", "?"))
                weekly.append(f"Refused for {log_file.stem}: {str(cmd)[:160]}")
    return urgent, weekly


def _key(text: str) -> str:
    return hashlib.sha1(re.sub(r"\d+", "#", text).encode()).hexdigest()[:12]


def prepare(today: date, weekly_day: bool, dry_run: bool = False, diagnose: list[str] | None = None) -> str | None:
    """Write the ticket file and say why the Engineer should run; None = nothing to do today. `diagnose` = the Ops
    Monitor's "worth a look" items (crashed task, traceback): the Engineer diagnoses them since the Scorekeeper was
    retired (2026-11-13) - one role, so two can't disagree about the same failure (as on 2026-11-10)."""
    st = load_json(STATEF, {})
    since = st.get("last_run") or str(today - timedelta(days=7))
    urgent, weekly = collect(today, since)
    urgent += [f"Ops Monitor ({today}): {d[:300]}" for d in diagnose or []]
    # The exact text of an item names its date, so "handled" means THAT occurrence only: a new failure of the same
    # job on another day is a new ticket. (2026-11-10..12: one power cut re-ticketed for three Engineer runs.)
    handled = set(st.get("handled", []))
    urgent = [u for u in urgent if u not in handled]
    attempts: dict = st.get("attempts", {})
    fresh = [u for u in urgent if attempts.get(_key(u), 0) < MAX_ATTEMPTS]
    stuck = [u for u in urgent if u not in fresh]
    if stuck and not dry_run:
        post("ops", f"🧯 The Engineer tried {MAX_ATTEMPTS} times and could not fix these - they need you:\n"
                    + "\n".join(f"• {s[:200]}" for s in stuck[:8]), USER)
    if not fresh and not (weekly_day and weekly):
        if not dry_run:
            save_json(STATEF, {**st, "last_run": str(today)})
        return None
    body = ["# Engineer tickets", "", f"Problems since {since}. Newest evidence is in the files named.", "",
            "## Must fix (something failed)"] + [f"- {u}" for u in fresh or ["none"]] + [
            "", "## Weekly review items"] + [f"- {w}" for w in (weekly if weekly_day else []) or ["none"]]
    if dry_run:
        print("\n".join(body))
    else:
        TICKETS.write_text("\n".join(body), encoding="utf-8")
        for u in fresh:
            attempts[_key(u)] = attempts.get(_key(u), 0) + 1
        save_json(STATEF, {**st, "last_run": str(today), "attempts": attempts, "pending": fresh})
    kind = "weekly review of the team's machinery" if weekly_day else "something failed"
    return f"{kind}: {len(fresh)} failure ticket(s) - read state/engineer_tickets.md"


def main(argv: list[str]) -> int:
    if argv[:1] == ["tickets"]:
        print(TICKETS.read_text(encoding="utf-8") if TICKETS.exists() else "no tickets")
        return 0
    if argv[:1] == ["check"]:
        changes = code_changes()
        problems = review(changes)
        print("files changed:", ", ".join(c.path for c in changes) or "none")
        if problems:
            print("GUARD REFUSES (tests not run):\n" + "\n".join(problems))
            return 1
        ok, output = run_tests()
        print("guard OK;", "tests PASS" if ok else "tests FAIL")
        print(output)
        return 0 if ok else 1
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
