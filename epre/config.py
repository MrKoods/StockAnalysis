"""Paths and fixed rules for the EPRE paper test (see RULES.md - do not change after the first trade)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UNIVERSE_DIR = DATA / "universe"
CALENDAR = DATA / "calendar" / "earnings_calendar.csv"
LEDGER = DATA / "paper" / "epre_ledger.csv"
TZ = "America/New_York"

INDEXES = ("sp500", "sp400", "sp600")
ETFS = {"SPY", "QQQ", "IWM", "DIA", "SMH", "XLF", "XLE", "XLK", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB",
        "TLT", "GLD"}
COST_BPS = {"sp500": 3.0, "sp400": 5.0, "sp600": 8.0}   # per side, same tiers as the research (PROTOCOL12)
HEDGE = ("SPY", "IJH", "IJR")                           # equal-weight S&P 500 / 400 / 600 proxy
BMO_CUTOFF_MIN = 9 * 60 + 30                            # report before 09:30 ET -> that session's open reacts
UNCONFIRMED_TIMES = {0, 15 * 60}                        # Yahoo placeholders for an unknown time of day
# Yahoo's placeholder for an UPCOMING report moves with US daylight saving: 15:00/00:00 ET in summer time, 16:00/01:00
# ET in standard time (seen 2026-11-02: CG, ITT, NAVI - BMO for years - suddenly "16:00"). Only for upcoming events:
# past reports at 16:00 are real after-close reports and must keep counting toward a company's habit.
UPCOMING_PLACEHOLDER_TIMES = UNCONFIRMED_TIMES | {1 * 60, 16 * 60}
N_POSTED = 20                                           # trades shown on Discord per day (all are scored)
