"""scan_ops must never file a failure ticket against its OWN task.

Regression: on 2026-11-10 the machine was asleep from ~10:00 to ~15:30 PT. On wake, Task Scheduler fired the
missed StockAnalysis_Team_ScanOps catch-up (two overlapping instances logged 15:30:35 / 15:30:39). The pre-sleep
run had been terminated by the system, leaving a non-OK LastResult; a post-wake snapshot caught the task with that
stale result and a State no longer "Running", so scan_ops evaluated its own row, saw `failed`, and - because
ScanOps has retry_until=null, so it is never re-run automatically - recorded a give-up issue. That became a false
"ScanOps exited with an error" Engineer ticket, even though every scan_ops run that day completed cleanly (no
traceback, ran every 10 min before 10:00 and after 15:30).

The `t["State"] == "Running"` guard can't prevent this: the false flag happens precisely when the snapshot shows
a stale non-Running state. A real ScanOps failure is still caught by ops_monitor.check_tasks (once per dispatch,
machine awake). So scan_ops must skip its own run-outcome evaluation outright.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import scan_ops  # noqa: E402

# ScanOps itself (retry_until null -> any failure goes straight to give-up) plus a normal job to prove real
# failures are still recorded.
SCHED = {
    scan_ops.OWN_TASK: {"model": "team", "what": "Scan Operator", "at": "15:40", "days": "Mon-Sat",
                        "retry_until": None, "frozen": False, "log": None},
    "StockAnalysis_X": {"model": "V3", "what": "x signals", "at": "12:40", "days": "Mon-Fri",
                        "retry_until": "12:48", "frozen": True, "log": None},
}


def trig(start, days):
    return [{"Kind": "MSFT_TaskWeeklyTrigger", "Start": start, "Days": days}]


def tasks():
    # ScanOps: a stale terminated result (post-sleep snapshot) - recent LastRun, non-OK result, not "Running".
    # X: a genuine failure well past its re-run window.
    return [
        {"Name": scan_ops.OWN_TASK, "State": "Ready", "LastRun": "2026-11-10T15:40:01", "LastResult": 1,
         "Triggers": trig("2026-10-01T15:40:00", 126)},
        {"Name": "StockAnalysis_X", "State": "Ready", "LastRun": "2026-11-10T12:40:01", "LastResult": 1,
         "Triggers": trig("2026-10-01T12:40:00", 62)},
    ]


def test_scan_ops_never_flags_itself():
    st = {}
    scan_ops.check(datetime(2026, 11, 10, 15, 40), tasks(), SCHED, st, dry_run=True)
    issues = st.get("issues", [])
    assert all(i["job"] != scan_ops.OWN_TASK for i in issues), f"scan_ops filed a ticket against itself: {issues}"
    # A real failure of another job is still recorded, so the self-skip didn't blunt the monitor.
    assert any(i["job"] == "StockAnalysis_X" for i in issues), f"real failure not recorded: {issues}"


def test_prune_drops_stale_own_task_issue(tmp_path, monkeypatch):
    """A ScanOps issue written before the self-flag fix (2026-11-10) must be purged on the next prune, so
    engineer.py stops replaying it as a phantom ticket. A real recent failure of another job is kept."""
    statef = tmp_path / "scan_ops.json"
    today = "2026-11-12"
    seed = {"issues": [{"date": "2026-11-10", "job": scan_ops.OWN_TASK, "problem": "exited with an error"},
                       {"date": today, "job": "StockAnalysis_X", "problem": "exited with an error"}],
            "ticks": [], "gaps": []}
    statef.write_text(json.dumps(seed), encoding="utf-8")
    monkeypatch.setattr(scan_ops, "STATEF", statef)
    monkeypatch.setattr(scan_ops, "now_pt", lambda: datetime(2026, 11, 12, 15, 40))
    monkeypatch.setattr(scan_ops, "scheduled_tasks", lambda: [])
    monkeypatch.setattr(scan_ops, "SCHEDULE", tmp_path / "no_sched.json")
    monkeypatch.setattr(scan_ops, "post", lambda *a, **k: None)
    monkeypatch.setattr(scan_ops, "log", lambda *a, **k: None)
    scan_ops.run(dry_run=False)
    issues = json.loads(statef.read_text(encoding="utf-8")).get("issues", [])
    assert all(i["job"] != scan_ops.OWN_TASK for i in issues), f"stale ScanOps issue not purged: {issues}"
    assert any(i["job"] == "StockAnalysis_X" for i in issues), f"real failure wrongly dropped: {issues}"
