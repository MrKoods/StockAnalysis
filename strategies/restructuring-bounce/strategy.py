"""restructuring-bounce -- FROZEN paper rule = pre-registered `chosen` = sp600_h3:
LONG an S&P 600 (small-cap) stock after it files an 8-K with item 2.05 (exit/restructuring costs).
Enter at the OPEN of the session AFTER the first tradable session (= open+2 from the event -- one
session after the initial reaction), exit at the OPEN 3 sessions later (= open+5 from the event).
SPY-hedged, judged at real Webull quotes (real_hedged_bps).

Promotability: 2.05 8-Ks are public the same day and the team's data/edgar/filings.parquet (rebuilt by
tools/edgar.py every dispatcher run) carries SEC's exact acceptance time -- so this CAN be traded live.
2.05 is RARE in the S&P 600, so a 20-40 trading-day paper window may take many months to fill.

Signal timing (matches the research entry = open+2): the runner enters at the OPEN of the session AFTER
the signal and exits hold_sessions sessions later at the open (spec hold_sessions=3, exit_at=open). So we
emit a signal on the day the event's FIRST tradable session is TODAY (asof): the runner then enters the
next open (= open+2 from the event) and exits 3 sessions later (= open+5). A 2.05 whose first tradable
session is not today is skipped (the once-daily after-close runner never back-fills -- that would be a
backtest). Universe is CURRENT S&P 600 membership (survivorship caveat in PLAN.md).
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

FILINGS = Path(__file__).resolve().parents[2] / "data" / "edgar" / "filings.parquet"
SP600_CSV = Path(r"C:\Users\user\Documents\Git\StockAnalysis-V3") / "daytrade" / "sp600.csv"


def _sp600() -> set:
    try:
        df = pd.read_csv(SP600_CSV)
    except Exception:
        return set()
    return set(df.iloc[:, 0].astype(str).str.upper().str.strip())


def _load() -> pd.DataFrame:
    try:
        return pd.read_parquet(FILINGS)
    except Exception:
        return pd.DataFrame()


def universe() -> list[str]:
    return sorted(_sp600())


def signals(asof: date, bars: dict) -> list[dict]:
    members = _sp600()
    df = _load()
    if df.empty or not members or "accepted" not in df.columns or "items" not in df.columns:
        return []
    form = df["form"].astype(str).str.replace("/A", "", regex=False)
    has_205 = df["items"].fillna("").str.split(",").apply(lambda c: any(x.strip() == "2.05" for x in c))
    tkr = df["ticker"].astype(str).str.upper().str.strip()
    df = df[(form == "8-K") & has_205 & tkr.isin(members)].copy()
    if df.empty:
        return []
    acc = pd.to_datetime(df["accepted"], errors="coerce")
    df = df[acc.notna()]
    acc = acc[acc.notna()]
    df = df[acc >= pd.Timestamp(asof) - pd.Timedelta(days=10)]   # recent filings only
    if df.empty:
        return []
    spy = bars.get("SPY")
    if spy is None:
        return []
    sessions = sorted(d for d in spy.index if d <= asof)          # bars are indexed by date
    if not sessions:
        return []
    last = sessions[-1]
    out, seen = [], set()
    for t, a in zip(df["ticker"].astype(str).str.upper().str.strip(), pd.to_datetime(df["accepted"])):
        day = a.normalize()
        secs = (a - day).total_seconds()
        same_day = 0 < secs < 9.5 * 3600                          # accepted premarket -> that day's open
        target = day.date() if same_day else day.date() + timedelta(days=1)
        later = [s for s in sessions if s >= target]
        first_sess = later[0] if later else None                  # first tradable session <= asof
        if first_sess == last and t not in seen:                  # first tradable session is TODAY
            seen.add(t)
            out.append({"ticker": t, "side": "long"})
    return out
