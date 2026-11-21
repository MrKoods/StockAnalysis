"""A Webull-connector give-up on a Quote task is a known external blocker (user reconnects), not an Engineer bug.

Regression: 2026-11-16..20 the Webull connector (a user-managed login) was signed out; quotes.py exited 1 with
its `(webull_auth)` status.
ops_monitor already named the user-only fix in the alert, but still appended the failure to `f.diagnose`, which
wakes the Engineer every day to re-diagnose something the team structurally cannot fix (auditor 2026-11-21 rec #1).
A webull_auth Quote give-up must alert the user but NOT diagnose; a Quote failure from any OTHER cause must still
diagnose; and a non-Quote failure is unaffected.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import ops_monitor  # noqa: E402
from common import WEBULL_HELP  # noqa: E402

NOW = datetime(2026, 11, 20, 13, 30)
# PC on through the Quote window, so window_gap() returns None and we reach the result check.
TICKS = ["2026-11-20T12:40:00", "2026-11-20T12:50:00", "2026-11-20T13:00:00", "2026-11-20T13:20:00"]


def task(name, last="2026-11-20T12:56:00", result=1):
    return [{"Name": name, "State": "Ready", "LastRun": last, "LastResult": result,
             "Triggers": [{"Kind": "MSFT_TaskWeeklyTrigger", "Start": "2026-10-30T12:56:00", "Days": 62}]}]


def run(name, signed_out, monkeypatch):
    monkeypatch.setattr(ops_monitor, "webull_signed_out", lambda day: signed_out)
    f = ops_monitor.Findings()
    ops_monitor.check_tasks(task(name), NOW, f, sched={}, ticks=TICKS)
    return f


def test_webull_auth_quote_give_up_alerts_but_does_not_diagnose(monkeypatch):
    f = run("StockAnalysis_Team_QuoteClose", True, monkeypatch)
    assert len(f.alerts) == 1 and WEBULL_HELP in f.alerts[0]
    assert not f.diagnose          # the Engineer is NOT woken for a known user-only blocker


def test_other_quote_failure_still_diagnoses(monkeypatch):
    f = run("StockAnalysis_Team_QuoteClose", False, monkeypatch)
    assert len(f.alerts) == 1 and "check its log" in f.alerts[0]
    assert len(f.diagnose) == 1    # a Quote failure from any other cause must still wake the Engineer


def test_non_quote_failure_unaffected(monkeypatch):
    f = run("StockAnalysis_Team_Dispatch", False, monkeypatch)
    assert len(f.alerts) == 1 and len(f.diagnose) == 1
