"""reg-fd-small-cap-disclosure -- TRAIN/HOLDOUT test (data ONLY via research_data as rd).

Hypothesis: a voluntary Regulation FD disclosure (8-K item 7.01) by a small-cap company is NEW
information that diffuses slowly to under-attentive holders; the stock drifts up over the next
session. Go LONG at the OPEN of `first_session` (rd's leak-free first tradable session after SEC
acceptance) and exit at the CLOSE H sessions later. Returns are SPY-hedged GROSS bps
(stock open->close minus SPY open->close over the same window); the harness subtracts cost_bps.

Variants (6): universe in {sp600, sp400, sp46 (400+600)} x hold H in {1, 3}. `chosen` is
PRE-REGISTERED = 'sp600_h1' (smallest caps = strongest form of the mechanism; hold 1 = screen's
best-t horizon -- see PLAN.md). The other 5 configs are a robustness map for the Skeptic only and
are never carried to the holdout.
"""
from __future__ import annotations

import math

import pandas as pd

import research_data as rd

COST_BPS = 30.0                       # MUST equal plan.json cost_bps (ranks variants in train only)
HOLD_GRID = (1, 3)
UNIV_GRID = ("sp600", "sp400", "sp46")
PREREGISTERED = "sp600_h1"
MAX_MOVE = 0.50                       # drop bars with |stock move| > 50% (bad-bar / unadjusted guard)


def _name(univ: str, h: int) -> str:
    return f"{univ}_h{h}"


def _members() -> dict[str, set]:
    sp600 = set(rd.universe("sp600"))
    sp400 = set(rd.universe("sp400"))
    return {"sp600": sp600, "sp400": sp400, "sp46": sp600 | sp400}


def _events(tickers) -> pd.DataFrame:
    """7.01 filings with a known first tradable session, one row per (ticker, first_session).
    Columns: ticker, first_session (Timestamp)."""
    f = rd.filings(forms=["8-K"], items=["7.01"], tickers=sorted(tickers))
    if f.empty:
        return f
    f = f[f["first_session"].notna()].copy()
    f["first_session"] = pd.to_datetime(f["first_session"]).dt.normalize()
    f = f.drop_duplicates(["ticker", "first_session"])
    return f[["ticker", "first_session"]]


def _trades(ev: pd.DataFrame, members: set, prices: dict, spy: pd.DataFrame, hold: int) -> list[dict]:
    spy_idx = pd.DatetimeIndex(spy.index).normalize()
    spy_open = spy["open"].to_numpy()
    spy_close = spy["close"].to_numpy()
    out = []
    for tkr, fs in ev.itertuples(index=False):
        if tkr not in members:
            continue
        df = prices.get(tkr)
        if df is None:
            continue
        idx = pd.DatetimeIndex(df.index).normalize()
        pos = int(idx.searchsorted(fs, side="left"))
        if pos >= len(idx) or idx[pos] != fs:          # first_session must be a real bar for this ticker
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
        if abs(c / o - 1) > MAX_MOVE:                  # bad-bar guard
            continue
        gross = (c / o - 1) * 1e4 - (sc / so - 1) * 1e4   # SPY-hedged, long
        out.append({"date": exit_day, "gross_bps": gross})
    return out


def _rank_t(trades) -> float:
    """Day-clustered net t, used only to report which variant looked best in train."""
    if not trades:
        return float("-inf")
    df = pd.DataFrame(trades)
    net = df["gross_bps"].astype(float) - COST_BPS
    per = net.groupby(pd.to_datetime(df["date"]).dt.normalize()).mean()
    n = len(per)
    if n < 2:
        return float("-inf")
    sd = per.std(ddof=1)
    return float(per.mean() / (sd / math.sqrt(n))) if sd > 0 else 0.0


def run(start: str, end: str, phase: str, chosen: str | None) -> dict:
    members = _members()
    all_syms = members["sp46"]
    ev = _events(all_syms)
    syms = sorted(ev["ticker"].astype(str).unique()) if len(ev) else []
    prices = rd.daily(syms + ["SPY"])
    spy = prices.get("SPY")
    if spy is None:
        raise RuntimeError("SPY daily bars missing from the archive -- required for the hedge")

    if phase == "holdout":
        univ, htag = chosen.rsplit("_", 1)
        h = int(htag[1:])
        return {"variants": 1, "chosen": chosen,
                "trades": {chosen: _trades(ev, members[univ], prices, spy, h)}}

    trades: dict[str, list] = {}
    for univ in UNIV_GRID:
        for h in HOLD_GRID:
            trades[_name(univ, h)] = _trades(ev, members[univ], prices, spy, h)
    best = max(trades, key=lambda k: _rank_t(trades[k]))     # reported for the Skeptic only
    print(f"train: {len(trades)} variants; best-looking (NOT chosen) = {best}; "
          f"pre-registered chosen = {PREREGISTERED}")
    return {"variants": len(trades), "chosen": PREREGISTERED, "trades": trades}
