import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import scan_ops  # noqa: E402

SCHED = {"StockAnalysis_X": {"model": "V3", "what": "x signals", "at": "12:40", "days": "Mon-Fri",
                             "retry_until": "12:48", "frozen": True, "log": None}}


def task(last="2026-11-02T12:40:01", result=0, at="12:40", days=62, state="Ready"):
    return [{"Name": "StockAnalysis_X", "State": state, "LastRun": last, "LastResult": result,
             "Triggers": [{"Kind": "MSFT_TaskWeeklyTrigger", "Start": f"2026-10-01T{at}:00", "Days": days}]}]


def test_ok_run_is_silent():
    assert scan_ops.check(datetime(2026, 11, 2, 12, 50), task(), SCHED, {}, dry_run=True) == []


def test_failed_run_is_retried_inside_window_then_given_up():
    st = {}
    ev = scan_ops.check(datetime(2026, 11, 2, 12, 42), task(result=1), SCHED, st, dry_run=True)
    assert len(ev) == 1 and "re-running" in ev[0]
    ev = scan_ops.check(datetime(2026, 11, 2, 12, 50), task(result=1), SCHED, st, dry_run=True)   # window closed
    assert len(ev) == 1 and "can't be fixed" in ev[0] and "gap" in ev[0]
    assert scan_ops.check(datetime(2026, 11, 2, 13, 0), task(result=1), SCHED, st, dry_run=True) == []  # said once


def test_missed_run_and_recovery():
    st = {}
    ev = scan_ops.check(datetime(2026, 11, 2, 12, 46), task(last="2026-10-30T12:40:00"), SCHED, st, dry_run=True)
    assert "missed" in ev[0]
    ev = scan_ops.check(datetime(2026, 11, 2, 12, 47), task(last="2026-11-02T12:46:30"), SCHED, st, dry_run=True)
    assert ev and "recovered" in ev[0]


def test_drift_and_disabled():
    ev = scan_ops.check(datetime(2026, 11, 2, 9, 0), task(at="11:40"), SCHED, {}, dry_run=True)
    assert any("master schedule says 12:40" in e for e in ev)
    ev = scan_ops.check(datetime(2026, 11, 2, 9, 0), task(state="Disabled"), SCHED, {}, dry_run=True)
    assert any("DISABLED" in e for e in ev)


def test_traceback_in_log_counts_as_failure(tmp_path, monkeypatch):
    log = tmp_path / "x.log"
    log.write_text("old Traceback from last week\n")
    monkeypatch.setattr(scan_ops, "GIT", tmp_path)
    sched = {"StockAnalysis_X": {**SCHED["StockAnalysis_X"], "log": "x.log"}}
    st = {}
    assert scan_ops.check(datetime(2026, 11, 2, 12, 41), task(), sched, st, dry_run=True) == []   # old errors ignored
    log.write_text(log.read_text() + "Traceback (most recent call last):\n  boom\n")
    ev = scan_ops.check(datetime(2026, 11, 2, 12, 42), task(), sched, st, dry_run=True)
    assert ev and "Traceback" in ev[0] and "re-running" in ev[0]
