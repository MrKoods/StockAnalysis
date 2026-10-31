"""split-announcement-drift -- FROZEN paper rule = pre-registered `chosen` = h4_r2:
LONG a stock the session its forward stock-split announcement (ratio >= 2:1) first becomes tradable;
enter at that session's OPEN (the runner enters at the session after the signal), exit at the CLOSE
4 sessions later (spec hold_sessions=4). SPY-hedged, judged at real Webull quotes (real_hedged_bps).

Promotability: forward-split 8-K / press-release announcements are public the same day, and the
team's data/edgar/splits.parquet (rebuilt by tools/edgar.py each dispatcher run) carries the
`announced` timestamp -- so UNLIKE insider-cluster-buys this CAN be traded live. BUT forward splits
are rare (~30/yr across the S&P 1500), so a 20-40 trading-day paper window accumulates only a handful
of signals; reaching min_days=20 distinct exit dates will take many months. Fine to promote, but the
Director should expect a long paper test.

Signal timing (matches the research entry = first_session open): on `asof` we emit a signal when the
first tradable session after the announcement is the NEXT session (so the runner, which enters at the
session after the signal, enters exactly at first_session's open). An announcement made premarket
(before 09:30, so tradable at that same day's open) is skipped -- the once-daily after-close runner
would enter a day late, which is not the rule.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

SPLITS = Path(__file__).resolve().parents[2] / "data" / "edgar" / "splits.parquet"
MIN_RATIO = 2.0          # chosen tier r2 (>= 2:1)
HOLD = 4                 # chosen hold; must equal spec.json hold_sessions


def _load() -> pd.DataFrame:
    try:
        df = pd.read_parquet(SPLITS)
    except Exception:
        return pd.DataFrame()
    return df


def universe() -> list[str]:
    df = _load()
    if df.empty or "ratio" not in df.columns:
        return []
    df = df[df["ratio"] > 1.0]
    return sorted(df["ticker"].astype(str).str.upper().str.strip().unique())


def signals(asof: date, bars: dict) -> list[dict]:
    df = _load()
    if df.empty or "announced" not in df.columns:
        return []
    df = df[(df["ratio"] >= MIN_RATIO) & df["announced"].notna()].copy()
    if df.empty:
        return []
    ann = pd.to_datetime(df["announced"])
    df = df[ann >= pd.Timestamp(asof) - pd.Timedelta(days=10)]   # recent announcements only
    if df.empty:
        return []
    spy = bars.get("SPY")
    if spy is None:
        return []
    sessions = sorted(d for d in spy.index if d <= asof)          # bars are indexed by date
    if not sessions:
        return []
    last = sessions[-1]
    out = []
    for tkr, a in zip(df["ticker"].astype(str).str.upper().str.strip(), pd.to_datetime(df["announced"])):
        day = a.normalize()
        secs = (a - day).total_seconds()
        same_day = 0 < secs < 9.5 * 3600                         # announced premarket -> that day's open
        target = day.date() if same_day else day.date() + timedelta(days=1)
        if target > last:                                        # first tradable session is the NEXT one
            out.append({"ticker": tkr, "side": "long"})
    return out
