"""split-announcement-drift -- TRAIN/HOLDOUT test (data ONLY via research_data as rd).

Hypothesis: a FORWARD stock-split announcement is a positive signal; the stock drifts up over the
next few sessions (management-confidence signal, retail-accessibility demand, analyst attention).
Go LONG at the OPEN of `first_session` (rd's leak-free first tradable session after the announcement
became public) and exit at the CLOSE H sessions later. Returns are SPY-hedged GROSS bps
(stock open->close minus SPY open->close over the same window); the harness subtracts cost_bps.

Variants (6): hold H in {2,4} sessions x ratio tier in {r1: all forward (>1), r2: >=2:1, r3: >=3:1}.
`chosen` is PRE-REGISTERED = 'h4_r2' (hold 4 sessions, forward splits >= 2:1 -- the idea's stated
rule). The other 5 configs are reported only as a robustness map and never carried to the holdout.
"""
from __future__ import annotations

import math

import pandas as pd

import research_data as rd

COST_BPS = 20.0                                  # MUST equal plan.json cost_bps (ranks variants only)
HOLD_GRID = (2, 4)
RATIO_GRID = {"r1": 1.0, "r2": 2.0, "r3": 3.0}   # minimum forward ratio per tier
PREREGISTERED = "h4_r2"


def _name(h: int, rtag: str) -> str:
    return f"h{h}_{rtag}"


def _events() -> pd.DataFrame:
    """Forward-split announcements with a known first tradable session, one row per
    (ticker, first_session). Columns: ticker, first_session (Timestamp), ratio."""
    sp = rd.splits(None)
    if sp.empty:
        return sp
    sp = sp[(sp["ratio"] > 1.0) & sp["first_session"].notna()].copy()
    sp["first_session"] = pd.to_datetime(sp["first_session"]).dt.normalize()
    sp = sp.drop_duplicates(["ticker", "first_session"])
    return sp[["ticker", "first_session", "ratio"]]


def _trades(ev: pd.DataFrame, prices: dict, spy: pd.DataFrame, hold: int, min_ratio: float) -> list[dict]:
    spy_idx = pd.DatetimeIndex(spy.index).normalize()
    spy_open = spy["open"].to_numpy()
    spy_close = spy["close"].to_numpy()
    out = []
    for tkr, fs, ratio in ev.itertuples(index=False):
        if ratio < min_ratio:
            continue
        df = prices.get(tkr)
        if df is None:
            continue
        idx = pd.DatetimeIndex(df.index).normalize()
        pos = int(idx.searchsorted(fs, side="left"))
        if pos >= len(idx) or idx[pos] != fs:         # first_session must be a real bar for this ticker
            continue
        exit_pos = pos + hold
        if exit_pos >= len(idx):
            continue
        entry_day, exit_day = idx[pos], idx[exit_pos]
        se = int(spy_idx.searchsorted(entry_day, side="left"))
        sx = int(spy_idx.searchsorted(exit_day, side="left"))
        if (se >= len(spy_idx) or sx >= len(spy_idx)
                or spy_idx[se] != entry_day or spy_idx[sx] != exit_day):
            continue
        o, c = float(df["open"].iloc[pos]), float(df["close"].iloc[exit_pos])
        so, sc = float(spy_open[se]), float(spy_close[sx])
        if not (o > 0 and c > 0 and so > 0 and sc > 0):
            continue
        gross = (c / o - 1) * 1e4 - (sc / so - 1) * 1e4   # SPY-hedged, long
        out.append({"date": exit_day, "gross_bps": gross})
    return out


def _rank_t(trades) -> float:
    """Week-clustered net t, used only to report which variant looked best in train."""
    if not trades:
        return float("-inf")
    df = pd.DataFrame(trades)
    net = df["gross_bps"].astype(float) - COST_BPS
    per = net.groupby(pd.to_datetime(df["date"]).dt.to_period("W")).mean()
    n = len(per)
    if n < 2:
        return float("-inf")
    sd = per.std(ddof=1)
    return float(per.mean() / (sd / math.sqrt(n))) if sd > 0 else 0.0


def run(start: str, end: str, phase: str, chosen: str | None) -> dict:
    ev = _events()
    syms = sorted(ev["ticker"].astype(str).unique()) if len(ev) else []
    prices = rd.daily(syms + ["SPY"])
    spy = prices.get("SPY")
    if spy is None:
        raise RuntimeError("SPY daily bars missing from the archive -- required for the hedge")

    if phase == "holdout":
        h = int(chosen.split("_")[0][1:])
        rtag = chosen.split("_")[1]
        return {"variants": 1, "chosen": chosen,
                "trades": {chosen: _trades(ev, prices, spy, h, RATIO_GRID[rtag])}}

    trades: dict[str, list] = {}
    for h in HOLD_GRID:
        for rtag, mr in RATIO_GRID.items():
            trades[_name(h, rtag)] = _trades(ev, prices, spy, h, mr)
    best = max(trades, key=lambda k: _rank_t(trades[k]))   # reported for the Skeptic only
    print(f"train: {len(trades)} variants; best-looking (NOT chosen) = {best}; "
          f"pre-registered chosen = {PREREGISTERED}")
    return {"variants": len(trades), "chosen": PREREGISTERED, "trades": trades}
