"""analyst-initiation-buy -- FROZEN paper rule = pre-registered `chosen` = sp600_h3:
LONG an S&P 600 (small-cap) stock the session AFTER a bullish sell-side coverage INITIATION
(ratings Action == 'init' with a Buy/Outperform/Overweight/Positive/Accumulate rating); enter at
that session's OPEN (the runner enters at the session after the signal), exit at the CLOSE 3
sessions later (spec hold_sessions=3). SPY-hedged, judged at real Webull quotes (real_hedged_bps).

Signal timing (matches the research entry = first session strictly after GradeDate): GradeDate is a
date only (no intraday time), so we emit a signal on `asof` when a bullish initiation is dated on
the current session -- the runner then enters at the next session's open, i.e. the first session
after GradeDate. Universe is CURRENT S&P 600 membership (survivorship caveat in PLAN.md).

PROMOTABILITY -- DO NOT PROMOTE YET. The ratings archive is a one-time yfinance snapshot (not a
near-real-time, point-in-time rating feed), so this rule cannot be traded live as the data stands.
This file encodes the frozen rule for the record and will run if a fresh feed is wired in; until
then the Director should not promote it to a paper test (same blocker as the insider family).
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

RATINGS_DIR = Path(r"C:\Users\user\Documents\Git\StockAnalysis-V3") / "data" / "events" / "ratings"
SP600_CSV = Path(r"C:\Users\user\Documents\Git\StockAnalysis-V3") / "daytrade" / "sp600.csv"
BULLISH = ("buy", "outperform", "overweight", "positive", "accumulate", "conviction")


def _sp600() -> set:
    try:
        df = pd.read_csv(SP600_CSV)
    except Exception:
        return set()
    return set(df.iloc[:, 0].astype(str).str.upper().str.strip())


def _is_bullish(grade: str) -> bool:
    g = str(grade).lower()
    return any(tok in g for tok in BULLISH)


def universe() -> list[str]:
    return sorted(_sp600())


def signals(asof: date, bars: dict) -> list[dict]:
    members = _sp600()
    if not members:
        return []
    spy = bars.get("SPY")
    if spy is None:
        return []
    sessions = sorted(d for d in spy.index if d <= asof)      # bars are indexed by date
    if not sessions:
        return []
    last = sessions[-1]
    lo = pd.Timestamp(asof) - pd.Timedelta(days=10)           # recent initiations only
    out, seen = [], set()
    for t in sorted(members):
        f = RATINGS_DIR / f"{t}.parquet"
        if not f.exists():
            continue
        try:
            df = pd.read_parquet(f)
        except Exception:
            continue
        if df.empty or "GradeDate" not in df.columns or "Action" not in df.columns:
            continue
        tg = df.get("ToGrade")
        if tg is None:
            continue
        gd = pd.to_datetime(df["GradeDate"], errors="coerce")
        if getattr(gd.dt, "tz", None) is not None:
            gd = gd.dt.tz_convert("America/New_York").dt.tz_localize(None)
        gd = gd.dt.normalize()
        act = df["Action"].astype(str).str.lower()
        m = (act == "init") & tg.map(_is_bullish) & gd.notna() & (gd >= lo) & (gd <= pd.Timestamp(asof))
        for g in gd[m]:
            target = g.date() + timedelta(days=1)             # first session after the grade date
            if target > last and t not in seen:               # that session is the NEXT one -> runner enters it
                seen.add(t)
                out.append({"ticker": t, "side": "long"})
    return out
