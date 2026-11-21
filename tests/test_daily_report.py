import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import daily_report  # noqa: E402


def test_epre_breakdown_counts_exit_days_and_splits_by_index():
    import pandas as pd
    led = pd.DataFrame({"exit_day": ["2026-11-02", "2026-11-02", "2026-11-03", "2026-11-03"],
                        "index": ["sp600", "sp500", "sp600", "sp400"], "hedged_bps": [-50.0, 60.0, -30.0, None],
                        "void": [None, None, None, None]})
    s = daily_report.epre_breakdown(led)
    assert s.startswith("2 exit days") and "sp600 -40 (2)" in s and "sp500 +60 (1)" in s and "sp400" not in s
    assert daily_report.epre_breakdown(led.iloc[:0]) == ""
