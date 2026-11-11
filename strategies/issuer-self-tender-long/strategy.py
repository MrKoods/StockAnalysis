"""issuer-self-tender-long -- FROZEN paper rule = pre-registered `chosen` = sp1500_h3:
LONG an S&P 1500 stock after it files an initial SC TO-I (Issuer Tender Offer Statement = the company offers to
repurchase its OWN shares at a premium to market). Enter at the CLOSE of the session AFTER the first tradable
session (= one session after the first reaction), exit at the CLOSE 3 sessions later. SPY-hedged, judged at real
Webull quotes (real_hedged_bps).
NOTE: this is a LONG, so there is NO short-borrow concern. The only standing caveat is survivorship -- the
universe is CURRENT S&P 1500 membership (no point-in-time index), which biases a long signal UP; a pass is not
fully conservative on that axis (see PLAN.md).

Promotability: SC TO-I is public the same day and the team's data/edgar/filings.parquet (rebuilt by
tools/edgar.py every dispatcher run) carries SEC's exact acceptance time -- so this CAN be traded live. For
SC TO-I the FILER is the issuer, so a filing under our ticker is the right name directly. Self-tenders in the
S&P 1500 are uncommon (~20-50/yr across the whole universe), so a 20-40 trading-day paper window may take months.

Signal timing (matches the research entry = close of first_session+1): the runner enters at the CLOSE of the
session AFTER the signal day and exits hold_sessions sessions later at the close (spec entry_at=close,
hold_sessions=3, exit_at=close). So we emit a signal on the day an initial SC TO-I's FIRST tradable session is
TODAY (asof): the runner then enters the next session's close (= first_session+1 close) and exits 3 sessions
later. An SC TO-I whose first tradable session is not today is skipped (the once-daily after-close runner never
back-fills -- that would be a backtest). We keep raw form == "SC TO-I" (dropping SC TO-I/A amendments). Universe
is CURRENT S&P 500 + S&P 400 + S&P 600 (survivorship caveat in PLAN.md).
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
    if df.empty or not members or "accepted" not in df.columns or "form" not in df.columns:
        return []
    form = df["form"].astype(str).str.strip()
    tkr = df["ticker"].astype(str).str.upper().str.strip()
    df = df[(form == "SC TO-I") & tkr.isin(members)].copy()     # initial only, drop SC TO-I/A
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
