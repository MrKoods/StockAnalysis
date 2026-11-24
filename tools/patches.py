"""Ready-to-apply patches for files the Engineer may not edit itself (user's decision 2026-11-21).

    python tools/patches.py list               - every patch and its status
    python tools/patches.py check [<id>]       - validate new patches (the dispatcher runs this after the Engineer)
    python tools/patches.py show <id>          - the full diff
    python tools/patches.py apply <id>         - USER ONLY: apply, re-run that repo's tests, commit (or roll back)
    python tools/patches.py reject <id> [why]  - USER: drop it (the Engineer reads why)

Why: the Engineer diagnosed the 2026-11-19 V4 EPRE crash on day one but couldn't touch V4, and the code that
scores the live tests (quotes.py, V4 epre/) must never change without the user. So the Engineer writes the fix as
exact find-and-replace edits in state/patches/<id>.json:

    {"title": "...", "why": "root cause + evidence", "ticket": "the ticket text it fixes",
     "edits": [{"file": "V4/epre/paper.py", "old": "exact text, once in the file", "new": "replacement"},
               {"file": "V4/tests/test_x.py", "old": "", "new": "whole new file"}]}

`check` proves it: every file is patchable, every `old` matches exactly once, then the patch is applied to a
SCRATCH COPY of that repo and its whole test suite runs there. Only then is it posted to #agent-ops as ready. The
live files are touched only by `apply`, which the user runs - and which checks again first.

Auto-apply (user 2026-11-24, "runs a month without me"): a patch that touches ONLY machinery (AUTO_FILES - data
collection, reports, scan operations; never scoring, rules, V3/V4 or the runner) applies itself AUTO_WAIT_H hours
after it became ready, unless the user rejected it. Same path as the user's apply (live re-check, full tests, roll
back on failure), committed as team-runner and logged in registry/engineer_log.csv. A WATCH pattern (network,
processes, ...) in an added line keeps it for the user unless that file already used the same thing.
"""
from __future__ import annotations

import difflib
import fnmatch
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from common import LIVE_V3, LIVE_V4, STATE, TEAM, load_json, now_pt, post, save_json

DIR = STATE / "patches"
ROOTS = {"team": TEAM, "V4": LIVE_V4, "V3": LIVE_V3}
PATCHABLE = {"team": ["tools/*.py", "tests/*.py", "prompts/*.md"],
             "V4": ["epre/*.py", "tests/*.py"],
             "V3": ["daytrade/*.py", "daytrade/*/*.py", "tests/*.py"]}
# The hard limits and the overseers stay out even with the user's yes - a one-word approval must never be able to
# remove a limit (holdout wall, gate, budget, the guard itself, settings, schedule, frozen rules).
BLOCKED = {"team": ["tools/gate.py", "tools/budget.py", "tools/engineer.py", "tools/patches.py", "tools/ideas.py",
                    "tools/jobs.py", "tools/research_data.py", "tools/plan_limit.py", "prompts/auditor.md",
                    "prompts/engineer.md", "tools/playbook.py", "prompts/strategist.md"],
           "V4": [], "V3": []}
BIG_DIRS = ("data",)            # linked, not copied, into the scratch copy (team 640 MB, V3 1.4 GB)
SKIP = {".git", "__pycache__", ".pytest_cache", "output", "research_results"}
MAX_ADDED = 200
# Not blocked (the user decides) but called out in the post so a yes is an informed one.
WATCH = [r"\bsubprocess\b", r"\brequests\b|\burllib\b|\bsocket\b", r"ScheduledTask|schtasks", r"\.env\b",
         r"\bholdout\b", r"registry\.json|ideas\.csv|trials\.csv", r"real_price_rules|RULES\.md", r"\brmtree\b|\.unlink\("]
AUTO_FILES = ["team/tools/" + n + ".py" for n in (
    "catalog", "cboe_history", "daily_bars", "daily_report", "edgar", "edgar_live", "edgar_text", "evening_check",
    "fomc_dates", "ops_monitor", "option_chains", "scan_ops", "screen")] + ["team/tests/test_eng_*.py"]
AUTO_WAIT_H = 24
ENG_LOG = TEAM / "registry" / "engineer_log.csv"


def _split(file: str) -> tuple[str, str]:
    repo, _, rel = file.replace("\\", "/").partition("/")
    return repo, rel


def allowed(file: str) -> str | None:
    """None if the file may be patched, else why not."""
    repo, rel = _split(file)
    if repo not in ROOTS:
        return f"{file}: must start with one of {sorted(ROOTS)}/"
    if ".." in rel.split("/") or not rel:
        return f"{file}: bad path"
    if any(fnmatch.fnmatch(rel, p) for p in BLOCKED[repo]):
        return f"{file}: a hard-limit file - never patchable, even with the user's approval"
    if not any(fnmatch.fnmatch(rel, p) for p in PATCHABLE[repo]):
        return f"{file}: not patchable ({repo} allows {PATCHABLE[repo]})"
    return None


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""


def _apply_edits(edits: list[dict], root_of: dict[str, Path]) -> tuple[dict[str, str], list[str]]:
    """New text per file (not written). Problems if any edit doesn't match exactly once."""
    texts, problems = {}, []
    for e in edits:
        repo, rel = _split(e["file"])
        p = root_of[repo] / rel
        cur = texts.get(e["file"])
        if cur is None:
            cur = p.read_text(encoding="utf-8") if p.exists() else None
        if e.get("old", "") == "":
            if cur is not None:
                problems.append(f"{e['file']}: old is empty (= new file) but the file exists")
                continue
            texts[e["file"]] = e["new"]
            continue
        if cur is None:
            problems.append(f"{e['file']}: file does not exist")
            continue
        n = cur.count(e["old"])
        if n != 1:
            problems.append(f"{e['file']}: `old` text found {n} times (must be exactly 1)")
            continue
        texts[e["file"]] = cur.replace(e["old"], e["new"])
    return texts, problems


def diff(texts: dict[str, str], root_of: dict[str, Path] = ROOTS) -> str:
    out = []
    for f, new in texts.items():
        repo, rel = _split(f)
        p = root_of[repo] / rel
        old = p.read_text(encoding="utf-8").splitlines(keepends=True) if p.exists() else []
        out += difflib.unified_diff(old, new.splitlines(keepends=True), f"a/{f}", f"b/{f}")
    return "".join(out)


def _scratch(repo: str, into: Path) -> Path:
    src, dst = ROOTS[repo], into / repo
    dst.mkdir(parents=True)
    for item in src.iterdir():
        if item.name in SKIP:
            continue
        if item.is_dir() and item.name in BIG_DIRS:
            # directory junction: no admin rights needed on Windows, read-through to the real data
            subprocess.run(["cmd", "/c", "mklink", "/J", str(dst / item.name), str(item)], capture_output=True)
        elif item.is_dir():
            shutil.copytree(item, dst / item.name, ignore=shutil.ignore_patterns(*SKIP))
        else:
            shutil.copy2(item, dst / item.name)
    return dst


def _unjunction(into: Path) -> None:
    """Remove junctions BEFORE deleting the scratch copy, so nothing ever deletes through them into real data."""
    for d in into.glob("*/*"):
        if d.name in BIG_DIRS and d.is_dir():
            subprocess.run(["cmd", "/c", "rmdir", str(d)], capture_output=True)   # rmdir on a junction = unlink only


def run_tests(root: Path) -> tuple[bool, str]:
    if not (root / "tests").is_dir():
        return True, "(no tests in this repo)"
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "--tb=short", "-p", "no:cacheprovider"],
                           cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
                           env={**__import__("os").environ, "TEAM_DRY_RUN": "1"})
    except subprocess.TimeoutExpired:
        return False, "tests timed out after 15 minutes"
    return r.returncode == 0, (r.stdout + r.stderr)[-1200:]


def validate(p: dict) -> tuple[list[str], dict[str, str]]:
    """Static checks against the LIVE files: (problems, new texts)."""
    edits = p.get("edits") or []
    problems = [] if edits else ["no edits"]
    problems += [why for e in edits if (why := allowed(e.get("file", "")))]
    problems += [f"edit {i}: needs file/old/new" for i, e in enumerate(edits)
                 if not all(isinstance(e.get(k), str) for k in ("file", "old", "new"))]
    if problems:
        return problems, {}
    texts, more = _apply_edits(edits, ROOTS)
    added = sum(1 for l in diff(texts).splitlines() if l.startswith("+") and not l.startswith("+++"))
    if added > MAX_ADDED:
        more.append(f"{added} lines added (max {MAX_ADDED}) - split it")
    return problems + more, texts


def check(pid: str) -> dict:
    """Validate one patch end to end and record its status. Posts once when it becomes ready."""
    f = DIR / f"{pid}.json"
    p = load_json(f, {})
    problems, texts = validate(p)
    res = {"status": "invalid", "checked": f"{now_pt():%Y-%m-%d %H:%M}", "problems": problems}
    if not problems:
        repos = sorted({_split(x)[0] for x in texts})
        tmp = Path(tempfile.mkdtemp(prefix="team-patch-"))
        try:
            roots = {r: _scratch(r, tmp) for r in repos}
            for x, t in texts.items():
                repo, rel = _split(x)
                (roots[repo] / rel).parent.mkdir(parents=True, exist_ok=True)
                (roots[repo] / rel).write_text(t, encoding="utf-8")
            outs = {r: run_tests(roots[r]) for r in repos}
        finally:
            _unjunction(tmp)
            shutil.rmtree(tmp, ignore_errors=True)
        ok = all(o for o, _ in outs.values())
        d = diff(texts)
        (DIR / f"{pid}.diff").write_text(d, encoding="utf-8")
        res.update(status="ready" if ok else "tests_failed", repos=repos,
                   tests={r: o[1][-400:] for r, o in outs.items()},
                   sha={x: _sha(ROOTS[_split(x)[0]] / _split(x)[1]) for x in texts},
                   watch=sorted({rx for l in d.splitlines() if l.startswith("+") for rx in WATCH if re.search(rx, l)}))
    prev = p.get("_status", {})
    first_ready = res["status"] == "ready" and prev.get("status") != "ready"
    if res["status"] == "ready":
        res["ready_since"] = prev.get("ready_since") if not first_ready else res["checked"]
        res["ready_since"] = res["ready_since"] or res["checked"]
        if prev.get("auto"):
            res["auto"] = prev["auto"]
    p["_status"] = res
    save_json(f, p)
    if first_ready:
        d = (DIR / f"{pid}.diff").read_text(encoding="utf-8")
        files = ", ".join(sorted({e["file"] for e in p["edits"]}))
        warn = f"\n⚠️ touches: {', '.join(res['watch'])} - read it before saying yes." if res["watch"] else ""
        if (why_not := auto_blocker(p)) is None:
            warn += (f"\n⏱️ Machinery only - it applies ITSELF in {AUTO_WAIT_H} h unless you reject it "
                     f"(`python tools/patches.py reject {pid} <why>`).")
        else:
            warn += f"\n🙋 Waits for your yes: {why_not}."
        post("ops", f"🩹 **Engineer patch ready: {p.get('title', pid)}** ({files}) - tests pass on a scratch copy.\n"
                    f"{p.get('why', '')[:400]}{warn}\n```diff\n{d[:900]}{' ...' if len(d) > 900 else ''}\n```"
                    f"Apply: `python tools/patches.py apply {pid}` · full diff: `python tools/patches.py show {pid}` · "
                    f"no: `python tools/patches.py reject {pid} <why>`", "Team - Engineer")
    return res


def pending() -> list[str]:
    return sorted(f.stem for f in DIR.glob("*.json")
                  if load_json(f, {}).get("_status", {}).get("status") not in ("applied", "rejected"))


def ready() -> list[tuple[str, str]]:
    return [(f.stem, load_json(f, {}).get("title", f.stem)) for f in sorted(DIR.glob("*.json"))
            if load_json(f, {}).get("_status", {}).get("status") == "ready"]


def check_new() -> list[str]:
    """Dispatcher hook: (re)check every patch not yet applied/rejected. One line per patch for the dispatch log."""
    out = []
    for pid in pending():
        try:
            out.append(f"{pid}: {check(pid)['status']}")
        except Exception as e:                       # a broken patch file never breaks the dispatch
            out.append(f"{pid}: check crashed - {e}")
    return out


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def auto_blocker(p: dict) -> str | None:
    """None if this patch may apply itself; else why it waits for the user."""
    files = sorted({e.get("file", "") for e in p.get("edits") or []})
    off = [x for x in files if not any(fnmatch.fnmatch(x, a) for a in AUTO_FILES)]
    if not files or off:
        return f"touches {', '.join(off) or 'nothing'} (scoring, rules, V3/V4 or the runner - user only)"
    for e in p["edits"]:
        repo, rel = _split(e["file"])
        cur = (ROOTS[repo] / rel).read_text(encoding="utf-8") if (ROOTS[repo] / rel).exists() else ""
        old_lines = set(e.get("old", "").splitlines())
        added = [l for l in e.get("new", "").splitlines() if l not in old_lines]
        for rx in WATCH:
            if any(re.search(rx, l) for l in added) and not re.search(rx, cur):
                return f"adds {rx} to {e['file']}, which never used it"
    return None


def auto_apply_due(now=None) -> list[str]:
    """Dispatcher hook: apply each machinery-only patch that has been ready AUTO_WAIT_H hours without a reject."""
    from datetime import datetime, timedelta
    now, out = now or now_pt(), []
    for pid, title in ready():
        f = DIR / f"{pid}.json"
        p = load_json(f, {})
        st = p.get("_status", {})
        since = st.get("ready_since")
        if st.get("auto") or not since or auto_blocker(p) is not None:
            continue
        if now - datetime.strptime(since, "%Y-%m-%d %H:%M") < timedelta(hours=AUTO_WAIT_H):
            continue
        rc = apply(pid, auto=True)
        p = load_json(f, {})
        if rc != 0:                       # never retried automatically; the user can still apply it
            p["_status"]["auto"] = "failed"
            save_json(f, p)
        _log_fix(now, "applied" if rc == 0 else "rolled_back", p,
                 "patch auto-applied: machinery only, ready 24 h, tests pass" if rc == 0 else
                 "auto-apply refused or tests failed on the live files - waits for the user")
        post("ops", (f"🛠️ Engineer patch applied itself: {title} - tests pass on the live files." if rc == 0 else
                     f"↩️ Engineer patch {title} could NOT apply itself (live files moved or tests failed) - rolled "
                     f"back; it waits for you: `python tools/patches.py show {pid}`"), "Team - Engineer")
        out.append(f"{pid}: auto {'applied' if rc == 0 else 'failed'}")
    return out


def _log_fix(now, result: str, p: dict, why: str) -> None:
    import csv
    new = not ENG_LOG.exists()
    ENG_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(ENG_LOG, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["date", "result", "files", "why"])
        w.writerow([f"{now:%Y-%m-%d}", result, " ".join(sorted({e["file"] for e in p.get("edits", [])})), why])


def apply(pid: str, auto: bool = False) -> int:
    f = DIR / f"{pid}.json"
    p = load_json(f, {})
    st = p.get("_status", {})
    if st.get("status") != "ready":
        print(f"{pid} is not ready ({st.get('status', 'never checked')}) - run `check {pid}` first")
        return 1
    problems, texts = validate(p)
    changed = [x for x, h in st.get("sha", {}).items() if _sha(ROOTS[_split(x)[0]] / _split(x)[1]) != h]
    if problems or changed:
        print("NOT applied - the live files moved since the check:", problems or changed, f"\nRe-run: check {pid}")
        return 1
    before = {x: (ROOTS[_split(x)[0]] / _split(x)[1]) for x in texts}
    saved = {x: (q.read_text(encoding="utf-8") if q.exists() else None) for x, q in before.items()}
    for x, t in texts.items():
        before[x].parent.mkdir(parents=True, exist_ok=True)
        before[x].write_text(t, encoding="utf-8")
    repos = sorted({_split(x)[0] for x in texts})
    results = {r: run_tests(ROOTS[r]) for r in repos}
    if not all(o for o, _ in results.values()):
        for x, old in saved.items():
            if old is None:
                before[x].unlink(missing_ok=True)
            else:
                before[x].write_text(old, encoding="utf-8")
        print("Tests FAILED on the live files - rolled back.\n" + "\n".join(o for _, o in results.values()))
        return 1
    for r in repos:
        rels = [_split(x)[1] for x in texts if _split(x)[0] == r]
        _git(ROOTS[r], "add", "--", *rels)
        msg = (f"team-runner: auto-applied Engineer patch {pid}: {p.get('title', '')}\n\n{p.get('why', '')}\n\n"
               f"Machinery only, ready {AUTO_WAIT_H} h without a reject (tools/patches.py auto_apply_due)." if auto else
               f"Engineer patch {pid}: {p.get('title', '')}\n\n{p.get('why', '')}\n\n"
               f"Approved and applied by the user (tools/patches.py apply).")
        _git(ROOTS[r], "commit", "-m", msg, "--", *rels)
    st.update(status="applied", applied=f"{now_pt():%Y-%m-%d %H:%M}", by="auto" if auto else "user")
    save_json(f, p)
    print(f"APPLIED {pid} and committed in {', '.join(repos)}; tests pass.")
    return 0


def reject(pid: str, why: str) -> int:
    f = DIR / f"{pid}.json"
    p = load_json(f, {})
    if not p:
        print(f"no patch {pid}")
        return 1
    p.setdefault("_status", {}).update(status="rejected", rejected=f"{now_pt():%Y-%m-%d %H:%M}", why=why)
    save_json(f, p)
    print(f"rejected {pid}")
    return 0


def main(argv: list[str]) -> int:
    DIR.mkdir(parents=True, exist_ok=True)
    cmd, rest = (argv[0] if argv else "list"), argv[1:]
    if cmd == "list":
        for f in sorted(DIR.glob("*.json")):
            q = load_json(f, {})
            s = q.get("_status", {})
            print(f"{f.stem:30s} {s.get('status', 'new'):13s} {q.get('title', '')}"
                  + (f"  <- {'; '.join(s['problems'])}" if s.get("problems") else ""))
        return 0
    if cmd == "check":
        for line in ([f"{rest[0]}: {check(rest[0])}"] if rest else check_new()):
            print(line)
        return 0
    if cmd == "show" and rest:
        print((DIR / f"{rest[0]}.diff").read_text(encoding="utf-8") if (DIR / f"{rest[0]}.diff").exists() else "no diff")
        return 0
    if cmd == "apply" and rest:
        return apply(rest[0])
    if cmd == "reject" and rest:
        return reject(rest[0], " ".join(rest[1:]) or "no reason given")
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
