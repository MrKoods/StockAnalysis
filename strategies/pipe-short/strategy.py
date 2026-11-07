"""pipe-short -- FROZEN paper rule = pre-registered `chosen` = sp1500_h3:
SHORT an S&P 1500 stock after it files an 8-K with item 3.02 (sale of unregistered equity = a completed
PIPE). Enter at the CLOSE of the session AFTER the first tradable session (= one session after the first
reaction), cover at the CLOSE 3 sessions later. SPY-hedged, judged at real Webull quotes (real_hedged_bps).
NOTE: real_hedged_bps prices the bid/ask spread but NOT short borrow -- 3.02 filers skew small/distressed and
can be hard-to-borrow, so the Director must confirm borrow availability/cost before any real-money step
(pass_mean_bps is sized to leave room for it).

Promotability: 3.02 8-Ks are public the same day and the team's data/edgar/filings.parquet (rebuilt by
tools/edgar.py every dispatcher run) carries SEC's exact acceptance time -- so this CAN be traded live. 3.02
in the S&P 1500 is uncommon, so a 20-40 trading-day paper window may take many months.

Signal timing (matches the research entry = close of first_session+1): the runner enters at the CLOSE of the
session AFTER the signal day and exits hold_sessions sessions later at the close (spec entry_at=close,
hold_sessions=3, exit_at=close). So we emit a signal on the day a 3.02's FIRST tradable session is TODAY
(asof): the runner then enters the next session's close (= first_session+1 close) and covers 3 sessions
later. A 3.02 whose first tradable session is not today is skipped (the once-daily after-close runner never
back-fills -- that would be a backtest). Universe is CURRENT S&P 500 + S&P 400 + S&P 600 (survivorship caveat
in PLAN.md).
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

FILINGS = Path(__file__).resolve().parents[2] / "data" / "edgar" / "filings.parquet"
V3 = Path(r"C:\Users\user\Documents\Git\StockAnalysis-V3") / "daytrade"


def _members() -> set:
    out: set = set()
    for name in ("sp500_new.csv", "sp400.csv", "sp600.csv"):
        try:
            df = pd.read_csv(V3 / name)
        except Exception:
            continue
        out |= set(df.iloc[:, 0].astype(str).str.upper().str.strip())
    return out


def _load() -> pd.DataFrame:
    try:
        return pd.read_parquet(FILINGS)
    except Exception:
        return pd.DataFrame()


def universe() -> list[str]:
    return sorted(_members())


def signals(asof: date, bars: dict) -> list[dict]:
    members = _members()
    df = _load()
    if df.empty or not members or "accepted" not in df.columns or "items" not in df.columns:
        return []
    form = df["form"].astype(str).str.replace("/A", "", regex=False).str.strip()
    has_302 = df["items"].fillna("").str.split(",").apply(lambda c: any(x.strip() == "3.02" for x in c))
    tkr = df["ticker"].astype(str).str.upper().str.strip()
    df = df[(form == "8-K") & has_302 & tkr.isin(members)].copy()
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
            out.append({"ticker": t, "side": "short"})
    return out
