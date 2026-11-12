"""PC off/asleep through a job's whole valid window = an expected gap (a note), not a failure (alert/ticket).

Regression: 2026-11-10 the PC lost power 09:52-15:23 PT. Team_QuoteClose (12:56, valid to 12:59) could not run;
Windows stamped it 15:30 with result 0x800710E0. Scan Operator + Ops Monitor reported "exited with an error",
the Scorekeeper was launched to diagnose it, the Engineer got 5 tickets and the user was told to check the log -
for something nothing could fix. A real failure while the PC was on must still alert.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import ops_monitor  # noqa: E402
import quotes  # noqa: E402
import scan_ops  # noqa: E402

NAME = "StockAnalysis_Team_QuoteClose"
SCHED = {NAME: {"model": "team", "what": "Quote Clerk: bid/ask before the close", "at": "12:56", "days": "Mon-Fri",
                "retry_until": "12:59", "frozen": True, "log": None}}
NOW = datetime(2026, 11, 10, 15, 30)


def task(last="2026-11-10T15:30:00", result=2147946720):
    return [{"Name": NAME, "State": "Ready", "LastRun": last, "LastResult": result,
             "Triggers": [{"Kind": "MSFT_TaskWeeklyTrigger", "Start": "2026-10-30T12:56:00", "Days": 62}]}]


OFF_TICKS = ["2026-11-10T09:40:00", "2026-11-10T09:50:00"]                     # then nothing until 15:30
ON_TICKS = ["2026-11-10T12:40:00", "2026-11-10T12:50:00", "2026-11-10T13:00:00", "2026-11-10T15:20:00"]


def test_offline_needs_a_long_silence_around_the_window():
    s, e = datetime(2026, 11, 10, 12, 56), datetime(2026, 11, 10, 12, 59)
    assert ops_monitor.offline(s, e, OFF_TICKS, NOW) is not None
    assert ops_monitor.offline(s, e, ON_TICKS, NOW) is None          # 12:50 -> 13:00 is a normal 10-min step
    assert ops_monitor.offline(s, e, [], NOW) is None                # no history: never assume the PC was off


def test_scan_ops_records_a_gap_not_an_issue_when_pc_was_off():
    st = {"ticks": OFF_TICKS}
    for minute in (30, 40, 50):                                       # several ticks after waking
        ev = scan_ops.check(datetime(2026, 11, 10, 15, minute), task(), SCHED, st, dry_run=True)
        assert ev == []
    assert not st.get("issues") and len(st["gaps"]) == 1 and "off or asleep 09:50-15:30" in st["gaps"][0]["note"]


def test_scan_ops_still_gives_up_on_a_real_failure():
    st = {"ticks": ON_TICKS}
    ev = scan_ops.check(datetime(2026, 11, 10, 15, 30), task(last="2026-11-10T12:56:00", result=1), SCHED, st,
                        dry_run=True)
    assert len(ev) == 1 and "can't be fixed" in ev[0] and len(st["issues"]) == 1 and not st.get("gaps")


def test_ops_monitor_note_instead_of_alert_and_diagnosis():
    f = ops_monitor.Findings()
    ops_monitor.check_tasks(task(), NOW, f, sched=SCHED, ticks=OFF_TICKS)
    assert not f.alerts and not f.diagnose and len(f.notes) == 1 and "nothing to fix" in f.notes[0]
    f = ops_monitor.Findings()
    ops_monitor.check_tasks(task(), NOW, f, sched=SCHED, ticks=ON_TICKS)    # PC was on: still a real failure
    assert len(f.alerts) == 1 and len(f.diagnose) == 1 and not f.notes


def test_quotes_capture_refuses_after_its_window():
    assert quotes.too_late("close", datetime(2026, 11, 10, 12, 57)) is None
    assert quotes.too_late("close", datetime(2026, 11, 10, 13, 1)) is None      # 2-min grace after 12:59
    assert "skipped" in quotes.too_late("close", datetime(2026, 11, 10, 15, 30))
    assert "skipped" in quotes.too_late("open", datetime(2026, 11, 10, 9, 0))
