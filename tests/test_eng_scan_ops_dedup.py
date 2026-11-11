"""A failed scan that can't be re-run must record ONE issue per job per day, not one per 10-min tick.

Regression: a single QuoteClose failure (2026-11-10, ran late at 15:30 past its 12:56 window) produced 5
identical entries in scan_ops.json `issues`, because the append ran on every tick while `once()` only gated
the Discord alert. Those duplicates became 5 identical Engineer tickets and inflated engineer.py's attempt
counter toward the "tried too many times, needs you" cutoff.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import scan_ops  # noqa: E402

SCHED = {"StockAnalysis_X": {"model": "V3", "what": "x signals", "at": "12:40", "days": "Mon-Fri",
                             "retry_until": "12:48", "frozen": True, "log": None}}


def task(last="2026-11-02T12:40:01", result=1):
    return [{"Name": "StockAnalysis_X", "State": "Ready", "LastRun": last, "LastResult": result,
             "Triggers": [{"Kind": "MSFT_TaskWeeklyTrigger", "Start": "2026-10-01T12:40:00", "Days": 62}]}]


def test_gave_up_records_one_issue_across_many_ticks():
    st = {}
    # Many ticks after the valid window has closed, all still seeing the failed run.
    for minute in (50, 0 + 60, 10 + 60, 20 + 60, 30 + 60):   # 12:50, 13:00, 13:10, 13:20, 13:30
        h, m = 12 + minute // 60, minute % 60
        scan_ops.check(datetime(2026, 11, 2, h, m), task(), SCHED, st, dry_run=True)
    issues = [i for i in st.get("issues", []) if i["job"] == "StockAnalysis_X"]
    assert len(issues) == 1, f"expected exactly one issue, got {len(issues)}: {issues}"
    assert issues[0] == {"date": "2026-11-02", "job": "StockAnalysis_X", "problem": "exited with an error"}
