"""pre-earnings-premium -- FROZEN paper rule = pre-registered chosen = h1_sp500:
LONG an S&P 500 stock at the CLOSE of the session 2 sessions before its scheduled earnings
announcement (A-2); EXIT at the CLOSE of the session before the announcement (A-1). Hold 1 session,
close->close, SPY-hedged, judged at real Webull quotes (real_hedged_bps). We capture ONLY the
pre-announcement risk premium (Laarits 2020; Ai-Bansal-Han 2021) and take ZERO earnings-surprise
risk -- we are flat before the release, BMO or AMC.

Timing (matches the research entry = close A-2): the once-daily after-close runner enters at the
CLOSE of the session AFTER the signal day and exits hold_sessions=1 later at the close. So on `asof`
we emit a LONG when a stock's next earnings session A is exactly the 3rd NYSE session after `asof`:
the runner then enters close(asof+1) = A-2 and exits close(asof+2) = A-1. Upcoming earnings dates come
from V4 EPRE's nightly Yahoo calendar (data/calendar/earnings_calendar.csv -- the same live feed EPRE
trades on); future sessions are counted on a self-contained NYSE holiday calendar, not from bars.

PROMOTABILITY: earnings dates are scheduled and public (Yahoo calendar refreshed nightly by V4), so
this trades live. ~2000 S&P 500 reports/yr clustered into earnings weeks -> a 20-40 trading-day window
fills in a few months. CAVEAT: a report's date can be 'estimated' and shift; a 2-session lead is short
enough that it is almost always confirmed, but the Director should note any report whose date moved
after entry. max_signals_per_day caps the busiest earnings days (a few peak days under-sampled).
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

V4 = Path(r"C:\Users\user\Documents\Git\StockAnalysis-V4")
CALENDAR = V4 / "data" / "calendar" / "earnings_calendar.csv"
SP500_CSV = Path(r"C:\Users\user\Documents\Git\StockAnalysis-V3") / "daytrade" / "sp500_new.csv"


def universe() -> list[str]:
    try:
        df = pd.read_csv(SP500_CSV)
    except Exception:
        return []
    return sorted(df.iloc[:, 0].astype(str).str.upper().str.strip().unique())


# ---------- self-contained NYSE holiday calendar (counts FUTURE sessions, not from bars) ----------

def _easter(y: int) -> date:
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
    d = date(y, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(days=7 * (n - 1))


def _last_weekday(y: int, month: int, weekday: int) -> date:
    d = date(y, month, 28)
    while d.month == month:
        d += timedelta(days=1)
    d -= timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def _nyse_holidays(y: int) -> set:
    hol = {
        _observed(date(y, 1, 1)),                 # New Year's Day
        _nth_weekday(y, 1, 0, 3),                 # MLK (3rd Mon Jan)
        _nth_weekday(y, 2, 0, 3),                 # Washington (3rd Mon Feb)
        _easter(y) - timedelta(days=2),           # Good Friday
        _last_weekday(y, 5, 0),                    # Memorial Day (last Mon May)
        _observed(date(y, 7, 4)),                 # Independence Day
        _nth_weekday(y, 9, 0, 1),                 # Labor Day (1st Mon Sep)
        _nth_weekday(y, 11, 3, 4),                # Thanksgiving (4th Thu Nov)
        _observed(date(y, 12, 25)),               # Christmas
    }
    if y >= 2022:
        hol.add(_observed(date(y, 6, 19)))        # Juneteenth
    return hol


def _is_session(d: date) -> bool:
    return d.weekday() < 5 and d not in _nyse_holidays(d.year)


def _next_session(d: date) -> date:
    """First session strictly after d."""
    d += timedelta(days=1)
    while not _is_session(d):
        d += timedelta(days=1)
    return d


def signals(asof: date, bars: dict) -> list[dict]:
    if not _is_session(asof):
        return []
    try:
        cal = pd.read_csv(CALENDAR)
    except Exception:
        return []
    if cal.empty or "report_day" not in cal.columns or "index" not in cal.columns:
        return []
    # 3rd NYSE session after asof = the announcement session A; entry = asof+1 close = A-2.
    s3 = _next_session(_next_session(_next_session(asof)))
    members = set(universe())
    cal = cal[cal["index"].astype(str).str.strip() == "sp500"].copy()
    rpt = pd.to_datetime(cal["report_day"], errors="coerce").dt.date
    tkr = cal["ticker"].astype(str).str.upper().str.strip()
    out, seen = [], set()
    for t, a in zip(tkr, rpt):
        if a == s3 and t in members and t not in seen:
            seen.add(t)
            out.append({"ticker": t, "side": "long"})
    return out
