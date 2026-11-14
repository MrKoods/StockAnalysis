"""material-impairment-short -- paper rule for the record (see PLAN.md "Promotability").

The pre-registered research `chosen` (e0_sp1500_h3) SHORTs at the DAY-0 close (`entry_session`): an S&P 1500
stock that files an 8-K item 2.06 (material impairment / goodwill writedown), shorted at the close of the first
session whose close is still reachable after SEC accepted the filing, covered at the CLOSE 3 sessions later,
hedged with its own index fund (judged real_hedged_bps).

DO NOT PROMOTE AS-IS. A once-daily AFTER-close dispatch only sees a 2.06 after it reaches SEC's daily index
(next weekday), by which time the day-0 close has passed -- so this runner can only enter the NEXT close (= the
research `e1` timing), which is NOT the chosen edge. Trading the day-0 close needs an intraday EDGAR check
(~12:45 PT) that is NOT built yet; the Director requests it on a holdout pass. This file emits the e1 best-effort
short for the record (and so an `e1` paper test can be stood up if the Director pre-registers it separately).

NOTE: real_hedged_bps prices the bid/ask spread but NOT short borrow -- impairment names can be beaten-down
mid/small-caps, some hard-to-borrow. The Director must confirm borrow before any real-money step (pass_mean_bps
is sized to leave room).
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

FILINGS = Path(__file__).resolve().parents[2] / "data" / "edgar" / "filings.parquet"
V3 = Path(r"C:\Users\user\Documents\Git\StockAnalysis-V3") / "daytrade"
ITEM = "2.06"


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
    form = df["form"].astype(str).str.replace("/A", "", regex=False).str.strip()
    items = df["items"].fillna("").astype(str)
    has_206 = items.apply(lambda s: ITEM in [x.strip() for x in s.split(",")])
    tkr = df["ticker"].astype(str).str.upper().str.strip()
    df = df[(form == "8-K") & has_206 & tkr.isin(members)].copy()
    if df.empty:
        return []
    acc = pd.to_datetime(df["accepted"], errors="coerce")
    df = df[acc.notna()]
    acc = acc[acc.notna()]
    df = df[acc >= pd.Timestamp(asof) - pd.Timedelta(days=10)]        # recent filings only
    if df.empty:
        return []
    spy = bars.get("SPY")
    if spy is None:
        return []
    sessions = sorted(d for d in spy.index if d <= asof)              # bars are indexed by date
    if not sessions:
        return []
    last = sessions[-1]
    out, seen = [], set()
    for t, a in zip(df["ticker"].astype(str).str.upper().str.strip(), pd.to_datetime(df["accepted"])):
        day = a.normalize()
        secs = (a - day).total_seconds()
        same_day = 0 < secs < 9.5 * 3600                              # accepted premarket -> that day's open
        target = day.date() if same_day else day.date() + timedelta(days=1)
        later = [s for s in sessions if s >= target]
        first_sess = later[0] if later else None                     # first tradable session <= asof
        if first_sess == last and t not in seen:                     # first tradable session is TODAY
            seen.add(t)
            out.append({"ticker": t, "side": "short"})
    return out
