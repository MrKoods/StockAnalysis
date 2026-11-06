"""turn-of-month -- FROZEN paper rule = pre-registered `chosen` = tom_h3:
LONG the whole S&P 500 (equal weight) at the CLOSE of the last NYSE trading day of each calendar month;
exit at the CLOSE of the 3rd session of the new month (spec hold_sessions=3, entry_at/exit_at = close).
Judged RAW at real Webull quotes (metric real_bps) -- TOM is a market-level seasonal, so it is NOT hedged.

Timing (matches the research entry = month-end close): the once-daily after-close runner enters at the NEXT
session's close, so on `asof` we emit signals when the next NYSE session is the LAST trading day of its month
-- i.e. `asof` is the second-to-last session of the month. Month-end is read from a self-contained NYSE
holiday calendar (below), not from future bars.

PROMOTABILITY CAVEAT (see PLAN.md): TOM fires once a month and every name shares one exit date, so the paper
runner accrues ~one clustered day per month -- reaching min_days=20 takes ~20 months, max_days=40 ~3+ years.
This is effectively a research-only verdict; the Director should decide on the train+holdout result and not
expect a timely paper test.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

SP500_CSV = Path(r"C:\Users\user\Documents\Git\StockAnalysis-V3\daytrade\sp500_new.csv")


def universe() -> list[str]:
    try:
        df = pd.read_csv(SP500_CSV)
    except Exception:
        return []
    return sorted(df.iloc[:, 0].astype(str).str.upper().str.strip().unique())


# ---------- self-contained NYSE holiday calendar ----------

def _easter(y: int) -> date:
    """Anonymous Gregorian algorithm -> Easter Sunday (for Good Friday)."""
    a = y % 19
    b, c = divmod(y, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    day = ((h + m - 7 * n + 114) % 31) + 1
    return date(y, month, day)


def _nth_weekday(y: int, month: int, weekday: int, n: int) -> date:
    """n-th `weekday` (Mon=0) of a month."""
    d = date(y, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(days=7 * (n - 1))


def _last_weekday(y: int, month: int, weekday: int) -> date:
    d = date(y, month, 28)
    while d.month == month:
        d += timedelta(days=1)
    d -= timedelta(days=1)                       # last day of month
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    """NYSE weekend observance for fixed-date holidays: Sat->Fri, Sun->Mon."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _nyse_holidays(y: int) -> set[date]:
    hol = {
        _observed(date(y, 1, 1)),                 # New Year's Day
        _nth_weekday(y, 1, 0, 3),                 # MLK (3rd Mon Jan)
        _nth_weekday(y, 2, 0, 3),                 # Washington (3rd Mon Feb)
        _easter(y) - timedelta(days=2),           # Good Friday
        _last_weekday(y, 5, 0),                   # Memorial Day (last Mon May) -- can be May 31
        _observed(date(y, 7, 4)),                 # Independence Day
        _nth_weekday(y, 9, 0, 1),                 # Labor Day (1st Mon Sep)
        _nth_weekday(y, 11, 3, 4),                # Thanksgiving (4th Thu Nov)
        _observed(date(y, 12, 25)),               # Christmas
    }
    if y >= 2022:
        hol.add(_observed(date(y, 6, 19)))        # Juneteenth
    # NYSE rule: when New Year's Day falls on a Saturday the market does NOT close the prior Friday, so
    # Dec 31 is never a holiday -- nothing to add; _observed above already keeps Jan 1 only when it is a weekday.
    return hol


def _is_session(d: date) -> bool:
    return d.weekday() < 5 and d not in _nyse_holidays(d.year)


def _last_session_of_month(y: int, month: int) -> date:
    d = date(y, month, 28)
    while d.month == month:                       # advance to last calendar day
        d += timedelta(days=1)
    d -= timedelta(days=1)
    while not _is_session(d):                      # step back to the last real trading day
        d -= timedelta(days=1)
    return d


def _prev_session(d: date) -> date:
    d -= timedelta(days=1)
    while not _is_session(d):
        d -= timedelta(days=1)
    return d


def signals(asof: date, bars: dict) -> list[dict]:
    if not _is_session(asof):
        return []
    me = _last_session_of_month(asof.year, asof.month)
    if asof >= me:                                 # at/after this month's last session -> too late to signal
        return []
    if _prev_session(me) != asof:                  # emit only on the second-to-last session of the month
        return []
    return [{"ticker": t, "side": "long"} for t in universe()]
