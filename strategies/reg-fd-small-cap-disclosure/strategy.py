"""reg-fd-small-cap-disclosure -- FROZEN paper rule = pre-registered `chosen` = sp600_h1:
LONG an S&P 600 (small-cap) stock the session its 8-K item 7.01 (Regulation FD disclosure) first
becomes tradable; enter at that session's OPEN (the runner enters at the session after the signal),
exit at the CLOSE 1 session later (spec hold_sessions=1). SPY-hedged, judged at real Webull quotes
(real_hedged_bps).

Promotability: 7.01 8-Ks are public the same day and the team's data/edgar/filings.parquet (rebuilt by
tools/edgar.py every dispatcher run) carries SEC's exact acceptance time -- so this CAN be traded live,
and small caps file 7.01 often enough to fill a 20-40 day paper window.

Signal timing (matches the research entry = first_session open): on `asof` we emit a signal when the
first tradable session after SEC acceptance is the NEXT session (so the runner, which enters at the
session after the signal, enters exactly at first_session's open). A 7.01 accepted premarket (before
09:30, tradable at that same day's open) is skipped -- the once-daily after-close runner would enter a
day late, which is not the rule. Universe is CURRENT S&P 600 membership (survivorship caveat in PLAN.md).
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
    has_701 = df["items"].fillna("").str.split(",").apply(lambda c: any(x.strip() == "7.01" for x in c))
    tkr = df["ticker"].astype(str).str.upper().str.strip()
    df = df[(form == "8-K") & has_701 & tkr.isin(members)].copy()
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
        if target > last and t not in seen:                       # first tradable session is the NEXT one
            seen.add(t)
            out.append({"ticker": t, "side": "long"})
    return out
