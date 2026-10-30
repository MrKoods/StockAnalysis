"""Scan Operator - keeps every scan in team/schedule.json running (plain Python, zero Claude tokens).

    python tools/scan_ops.py              # one check (StockAnalysis_Team_ScanOps, every 10 min 05:00-18:50)
    python tools/scan_ops.py --dry-run    # print what it would do; no re-runs, no posts
    python tools/scan_ops.py status       # the schedule with today's state of each job

Each check, for every job due today:
  - verify it really worked: it ran (not missed), exit code OK, and no Traceback written to its log since the
    last check (a crash can still exit 0 when the shell swallows it);
  - if not, and the job's `retry_until` hasn't passed, re-run it (Start-ScheduledTask - the same task, nothing
    changed) up to 2 times, and say so in #agent-ops; report recovery;
  - if it can't be re-run validly any more, post one clear alert saying which results are missing today.
  - schedule drift: a task missing, disabled, or firing at a different time than the master schedule -> alert.
It never changes a task or the schedule: timing changes are proposed by the team and made by the user.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from common import STATE, TEAM, load_json, log, now_pt, post, save_json
from ops_monitor import OK_RESULTS, last_due, scheduled_tasks

SCHEDULE = TEAM / "team" / "schedule.json"
STATEF = STATE / "scan_ops.json"
GIT = TEAM.parent
DAYS = {"Mon-Fri": 62, "Mon-Sat": 126, "Sat": 64, "Sun": 1}
MAX_RETRIES = 2
USER = "Team - Scan Operator"


def _hm(s: str | None, day) -> datetime | None:
    return datetime.combine(day, datetime.strptime(s, "%H:%M").time()) if s else None


def _new_log_text(path: str | None, st: dict) -> str:
    """Bytes appended to a log since the last check (first sight: none - old errors aren't re-reported)."""
    if not path:
        return ""
    p = GIT / path
    if not p.exists():
        return ""
    size, key = p.stat().st_size, f"log:{path}"
    start = st.get(key)
    st[key] = size
    if start is None or start > size:            # first sight, or the log was rotated/truncated
        return ""
    with open(p, "rb") as fh:
        fh.seek(start)
        return fh.read(size - start).decode("utf-8", "replace")


def check(now: datetime, tasks: list[dict], sched: dict, st: dict, dry_run: bool) -> list[str]:
    today = now.date().isoformat()
    day = st.setdefault(today, {})
    by_name = {t["Name"]: t for t in tasks}
    events: list[str] = []

    def once(key: str, text: str) -> None:       # each message at most once a day
        if not day.get(key):
            day[key] = True
            events.append(text)

    # Tracebacks per log, attributed to the job sharing that log that ran most recently.
    crashed: set[str] = set()
    logs: dict[str, list[str]] = {}
    for name, j in sched.items():
        if j.get("log"):
            logs.setdefault(j["log"], []).append(name)
    for path, names in logs.items():
        if "Traceback" in _new_log_text(path, st):
            ran = [(by_name[n].get("LastRun") or "", n) for n in names if n in by_name]
            if ran:
                crashed.add(max(ran)[1])

    for name, j in sched.items():
        t = by_name.get(name)
        short = name.removeprefix("StockAnalysis_")
        if t is None:
            once(f"missing:{name}", f"⚠️ **{short}** ({j['what']}) is in the master schedule but has no Windows task.")
            continue
        if t["State"] == "Disabled":
            once(f"disabled:{name}", f"⚠️ **{short}** ({j['what']}) is DISABLED but the master schedule expects it.")
            continue
        weekly = [tr for tr in t.get("Triggers") or [] if tr.get("Kind") == "MSFT_TaskWeeklyTrigger"]
        times = {(tr.get("Start") or "")[11:16] for tr in weekly}
        if j["at"] not in times or not any(int(tr.get("Days") or 0) == DAYS[j["days"]] for tr in weekly):
            once(f"drift:{name}", f"⚠️ **{short}** fires at {sorted(times) or '?'} but the master schedule says "
                                  f"{j['at']} {j['days']} - someone changed it?")
        due = last_due(t.get("Triggers"), now)
        if due is None or due.date() != now.date() or t["State"] == "Running":
            continue
        last = datetime.fromisoformat(t["LastRun"]) if t.get("LastRun") else None
        missed = (last is None or last < due - timedelta(minutes=2)) and now > due + timedelta(minutes=5)
        failed = not missed and last is not None and last >= due - timedelta(minutes=2) and \
            int(t.get("LastResult") or 0) not in OK_RESULTS
        problem = "missed its run" if missed else "exited with an error" if failed else \
            "wrote a Traceback to its log" if name in crashed else None
        retries = day.get(f"retries:{name}", 0)
        if problem is None:
            if retries and not day.get(f"recovered:{name}"):
                day[f"recovered:{name}"] = True
                events.append(f"✅ **{short}** recovered after {retries} automatic re-run(s).")
            continue
        until = _hm(j.get("retry_until"), now.date())
        if until and now <= until and retries < MAX_RETRIES:
            day[f"retries:{name}"] = retries + 1
            events.append(f"🔁 **{short}** ({j['what']}) {problem} - re-running it automatically "
                          f"(attempt {retries + 1}/{MAX_RETRIES}; valid until {j['retry_until']}).")
            if not dry_run:
                subprocess.run(["powershell", "-NoProfile", "-Command", f"Start-ScheduledTask -TaskName '{name}'"],
                               capture_output=True, text=True)
        else:
            why = (f"its valid window closed at {j['retry_until']}" if until and now > until else
                   f"{retries} re-runs didn't fix it" if until else "it is never re-run automatically")
            frozen = " Its timing is part of a running test, so today is a gap in that test." if j.get("frozen") else ""
            once(f"gave_up:{name}", f"🛑 **{short}** ({j['what']}) {problem} and can't be fixed automatically - "
                                    f"{why}. Today's {j['model']} results from it are missing.{frozen} "
                                    f"The Scorekeeper will diagnose it at 2:50 PM.")
            st.setdefault("issues", []).append({"date": today, "job": name, "problem": problem})
    return events


def run(dry_run: bool = False) -> list[str]:
    now = now_pt()
    sched = load_json(SCHEDULE, {}).get("jobs", {})
    st = load_json(STATEF, {})
    for k in [k for k in st if k[:2] == "20" and k < (now.date() - timedelta(days=7)).isoformat()]:
        st.pop(k)                                 # keep a week of per-day state
    st["issues"] = [i for i in st.get("issues", []) if i["date"] >= (now.date() - timedelta(days=7)).isoformat()]
    events = check(now, scheduled_tasks(), sched, st, dry_run)
    if dry_run:
        print("\n".join(events) or "nothing to do")
        return events
    save_json(STATEF, st)
    if events:
        post("ops", "\n".join(events), USER)
    log(f"scan_ops: {len(events)} event(s)" + (": " + " | ".join(e[:80] for e in events) if events else ""), "scan_ops")
    return events


def status() -> str:
    sched = load_json(SCHEDULE, {}).get("jobs", {})
    tasks = {t["Name"]: t for t in scheduled_tasks()}
    lines = []
    for name, j in sorted(sched.items(), key=lambda kv: kv[1]["at"]):
        t = tasks.get(name, {})
        lines.append(f"{j['at']} {j['days']:<8} {name.removeprefix('StockAnalysis_'):<28} {t.get('State', 'MISSING'):<9} "
                     f"last {str(t.get('LastRun') or '-')[:16]:<16} result {t.get('LastResult', '-')}"
                     f"{'  [frozen]' if j.get('frozen') else ''}")
    return "\n".join(lines)


if __name__ == "__main__":
    if sys.argv[1:2] == ["status"]:
        print(status())
    else:
        run(dry_run="--dry-run" in sys.argv)
