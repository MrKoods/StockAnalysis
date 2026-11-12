"""Ops Monitor - script only, never calls Claude. Checks everything; posts to #agent-ops only when it finds a problem.

    python tools/ops_monitor.py [--dry-run]

Checks: every enabled StockAnalysis_* scheduled task fired at its last scheduled time and succeeded;
snapshot.py ACTION NEEDED and "!!" lines (V2/V3/V4); ledger integrity (tools/integrity.py); the team's own last
role runs (logged out / failed). A problem is posted straight away (🛑); the full end-of-day report is posted by
tools/daily_report.py at the end of the dispatch. Returns the findings so the dispatcher can decide whether a
Claude role is worth waking.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import integrity
import outlook
from common import PYTHON, SNAPSHOT, STATE, TEAM, LIVE_V2, load_json, log, now_pt, post, save_json

# 0 = success, 267009 = still running, 267011 = never run (new task)
OK_RESULTS = {0, 267009, 267011}

PS_TASKS = r"""
Get-ScheduledTask -TaskName 'StockAnalysis_*' | ForEach-Object {
  $i = $_ | Get-ScheduledTaskInfo
  [pscustomobject]@{
    Name = $_.TaskName; State = "$($_.State)"
    LastRun = if ($i.LastRunTime) { $i.LastRunTime.ToString('s') } else { $null }
    LastResult = $i.LastTaskResult
    Triggers = @($_.Triggers | ForEach-Object { [pscustomobject]@{
      Kind = $_.CimClass.CimClassName; Start = $_.StartBoundary; Days = $_.DaysOfWeek } })
  }
} | ConvertTo-Json -Depth 4
"""


@dataclass
class Findings:
    alerts: list[str] = field(default_factory=list)      # needs the user (computer off, task failed)
    diagnose: list[str] = field(default_factory=list)    # worth a Claude look (crash, traceback)
    notes: list[str] = field(default_factory=list)       # context for the user, not a problem (loss cluster)
    snapshot: str = ""
    tasks_checked: int = 0


def scheduled_tasks() -> list[dict]:
    r = subprocess.run(["powershell", "-NoProfile", "-Command", PS_TASKS], capture_output=True, text=True)
    data = json.loads(r.stdout or "[]")
    return data if isinstance(data, list) else [data]


def last_due(triggers: list[dict], now: datetime) -> datetime | None:
    """Most recent scheduled fire time at or before now, across daily/weekly triggers."""
    due = None
    for tr in triggers or []:
        kind = tr.get("Kind")
        if kind not in ("MSFT_TaskWeeklyTrigger", "MSFT_TaskDailyTrigger") or not tr.get("Start"):
            continue
        start = datetime.fromisoformat(tr["Start"][:19])
        for back in range(9):
            when = datetime.combine(now.date() - timedelta(days=back), start.time())
            if when > now:
                continue
            if when < start:  # before the task existed (e.g. registered today) - nothing was due
                break
            # DaysOfWeek bitmask: Sunday = 1 ... Saturday = 64; Python weekday(): Monday = 0
            if kind == "MSFT_TaskWeeklyTrigger" and not (int(tr.get("Days") or 0) >> ((when.weekday() + 1) % 7)) & 1:
                continue
            if due is None or when > due:
                due = when
            break
    return due


OFF_GAP = timedelta(minutes=25)   # Scan Operator ticks every 10 min; a longer silence = the PC was off or asleep


def offline(start: datetime, end: datetime, ticks: list[str], now: datetime | None = None) -> tuple | None:
    """(last tick before `start`, first tick after `end`) when the Scan Operator saw nothing in between for longer
    than OFF_GAP - i.e. the machine was off/asleep through the whole [start, end] window. None otherwise,
    including when there is no tick history to judge by. `now` counts as a tick (the current check)."""
    ts = sorted(datetime.fromisoformat(x) for x in ticks)
    before = [x for x in ts if x < start]
    after = [x for x in ts if x > end] + ([now] if now and now > end else [])
    if not before or not after or any(start <= x <= end for x in ts):
        return None
    prev, nxt = before[-1], min(after)
    return (prev, nxt) if nxt - prev > OFF_GAP else None


def window_gap(name: str, due: datetime, now: datetime, sched: dict, ticks: list[str]) -> str | None:
    """A note when a window-bound job (has `retry_until`) could not run because the PC was off through its
    whole valid window - an expected one-day gap, not a failure for the user or the Engineer to fix."""
    j = sched.get(name) or {}
    if not j.get("retry_until"):
        return None
    until = datetime.combine(due.date(), datetime.strptime(j["retry_until"], "%H:%M").time())
    if now <= until or not (off := offline(due, until, ticks, now)):
        return None
    test = f" ({j.get('model')} test)" if j.get("frozen") else ""
    return (f"{name.removeprefix('StockAnalysis_')} could not run in its {j['at']}-{j['retry_until']} window - "
            f"the PC was off or asleep {off[0]:%H:%M}-{off[1]:%H:%M}. One-day gap in {j['what']}{test}; "
            f"nothing to fix.")


def check_tasks(tasks: list[dict], now: datetime, f: Findings, sched: dict | None = None,
                ticks: list[str] | None = None) -> None:
    if sched is None:
        sched = load_json(TEAM / "team" / "schedule.json", {}).get("jobs", {})
    if ticks is None:
        ticks = load_json(STATE / "scan_ops.json", {}).get("ticks", [])
    for t in tasks:
        if t["State"] == "Disabled":
            continue
        due = last_due(t.get("Triggers"), now)
        if due is None:
            continue
        f.tasks_checked += 1
        name = t["Name"].removeprefix("StockAnalysis_")
        last = datetime.fromisoformat(t["LastRun"]) if t.get("LastRun") else None
        bad = last is None or last < due - timedelta(minutes=2) or int(t["LastResult"]) not in OK_RESULTS
        if bad and (note := window_gap(t["Name"], due, now, sched, ticks)):
            f.notes.append(note)
            continue
        if last is None or last < due - timedelta(minutes=2):
            ran = f"last ran {last:%m-%d %H:%M}" if last else "never ran"
            f.alerts.append(f"{name} did NOT run at {due:%a %m-%d %H:%M} ({ran}) - computer off or asleep?")
        elif int(t["LastResult"]) not in OK_RESULTS:
            msg = f"{name} ran {last:%a %m-%d %H:%M} but FAILED (result {t['LastResult']})"
            f.alerts.append(msg + " - check its log.")
            f.diagnose.append(msg)


def check_snapshot(f: Findings) -> None:
    r = subprocess.run([PYTHON, str(SNAPSHOT)], cwd=LIVE_V2, capture_output=True, text=True, timeout=600)
    f.snapshot = r.stdout + (("\n[stderr]\n" + r.stderr[-2000:]) if r.returncode else "")
    if r.returncode:
        f.alerts.append(f"snapshot.py crashed (exit {r.returncode}) - numbers unavailable today")
        f.diagnose.append("snapshot.py crashed:\n" + r.stderr[-1500:])
    for line in r.stdout.splitlines():
        if "ACTION NEEDED" in line:
            f.alerts.append(line.strip().replace("ACTION NEEDED: ", ""))
        elif "error lines" in line:
            # snapshot.py counts a provider's own outage apart: a note for the user, nothing to diagnose
            if not re.search(r", 0 error lines\b", line):
                f.diagnose.append(re.sub(r" \| outside outage: .*", "", line.strip()))
            for label in re.findall(r"outside outage: ([^|]+?) x\d+", line):
                note = (f"{now_pt():%Y-%m-%d}: {label} - outside outage, the scans carry on with their other "
                        f"sources (not our bug)")
                if note not in f.notes:
                    f.notes.append(note)
        elif "!! loss cluster" in line:
            f.notes.append(line.strip().removeprefix("!! "))
        elif line.strip().startswith("!!"):
            f.diagnose.append(line.strip().removeprefix("!! "))
    f.notes = only_new(f.notes, STATE / "notes_seen.json")  # a cluster stays in the 7-day window; say it once


def only_new(items: list[str], path) -> list[str]:
    seen = set(load_json(path, []))
    save_json(path, sorted(seen | set(items))[-200:])
    return [x for x in items if x not in seen]


def check_integrity(f: Findings) -> None:
    new, _known = integrity.check()
    for x in new:
        f.alerts.append(f"data problem: {x}")
        f.diagnose.append(f"integrity: {x}")


def check_team(f: Findings) -> None:
    runs = load_json(STATE / "role_runs.json", {})
    for role, r in runs.items():
        if r.get("status") == "logged_out":
            f.alerts.append(f"Claude is LOGGED OUT ({role} run {r.get('date')}). Open Claude Code and log in.")
        elif r.get("status") == "failed" and r.get("date") == f"{now_pt():%Y-%m-%d}":
            f.alerts.append(f"team role {role} failed today: {r.get('note', '')[:150]}")


def run(dry_run: bool = False, post_it: bool = True) -> Findings:
    now = now_pt()
    f = Findings()
    try:
        check_tasks(scheduled_tasks(), now, f)
    except Exception as e:  # noqa: BLE001
        f.alerts.append(f"could not read scheduled tasks: {e}")
    try:
        check_snapshot(f)
    except Exception as e:  # noqa: BLE001
        f.alerts.append(f"snapshot.py did not finish: {e}")
    try:
        f.snapshot += ("\n=== Outlook: what each next decision still needs (tools/outlook.py) ===\n"
                       + "\n".join("  " + x for x in outlook.lines(f.snapshot)) + "\n")
    except Exception as e:  # noqa: BLE001
        log(f"outlook failed: {e}", "ops")
    try:
        check_integrity(f)
    except Exception as e:  # noqa: BLE001
        f.alerts.append(f"integrity check did not finish: {e}")
    check_team(f)
    (STATE / "snapshot.txt").write_text(f.snapshot, encoding="utf-8")
    if post_it and f.alerts:
        post("ops", f"🛑 **Problem found {now:%a %m-%d %H:%M}** - {len(f.alerts)} (the daily report follows)\n"
             + "\n".join(f"• {x}" for x in f.alerts), "Team - Ops Monitor", dry_run)
    log(f"ops: {len(f.alerts)} alerts, {len(f.diagnose)} to diagnose, {len(f.notes)} notes, "
        f"{f.tasks_checked} tasks", "ops")
    return f


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv)
