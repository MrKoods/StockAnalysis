"""analyst-initiation-buy -- TRAIN/HOLDOUT test (data ONLY via research_data as rd).

Hypothesis: a bullish sell-side coverage INITIATION creates new, gated institutional demand that
diffuses over the next few sessions. For each bullish initiation (ratings Action == 'init' with a
Buy/Outperform/Overweight/Positive/Accumulate ToGrade), go LONG at the OPEN of the first session
strictly AFTER the rating's GradeDate (leak-free: GradeDate is date-only, so we never trade same
day), and exit at the CLOSE H sessions later. Returns are SPY-hedged GROSS bps (stock open->close
minus SPY open->close over the same window); the harness subtracts cost_bps.

Variants (6): universe in {sp600, sp46 (sp400+sp600)} x hold H in {1, 3, 5}. `chosen` is
PRE-REGISTERED = 'sp600_h3' (smallest caps = strongest mechanism; 3-day hold = idea horizon /
post-announcement drift -- see PLAN.md). The other 5 are a robustness map for the Skeptic only and
are never carried to the holdout.
"""
from __future__ import annotations

import math

import pandas as pd

import research_data as rd

COST_BPS = 25.0                       # MUST equal plan.json cost_bps (ranks variants in train only)
HOLD_GRID = (1, 3, 5)
UNIV_GRID = ("sp600", "sp46")
PREREGISTERED = "sp600_h3"
MAX_MOVE = 0.50                       # drop bars with |stock move| > 50% (bad-bar / unadjusted guard)
BULLISH = ("buy", "outperform", "overweight", "positive", "accumulate", "conviction")


def _name(univ: str, h: int) -> str:
    return f"{univ}_h{h}"


def _members() -> dict[str, set]:
    sp600 = set(rd.universe("sp600"))
    sp400 = set(rd.universe("sp400"))
    return {"sp600": sp600, "sp46": sp600 | sp400}


def _is_bullish(grade: str) -> bool:
    g = grade.lower()
    return any(tok in g for tok in BULLISH)


def _events(tickers) -> pd.DataFrame:
    """Bullish coverage initiations, one row per (ticker, signal_date).
    signal_date = GradeDate normalized to a date (entry is the first session strictly after it).
    Columns: ticker, signal_date (Timestamp)."""
    rats = rd.ratings(sorted(tickers))
    rows = []
    for t, df in rats.items():
        if "Action" not in df or "GradeDate" not in df:
            continue
        tg = df.get("ToGrade")
        if tg is None:
            continue
        act = df["Action"].astype(str).str.lower()
        grade = tg.astype(str)
        m = (act == "init") & grade.map(_is_bullish)
        sub = df[m]
        if len(sub) == 0:
            continue
        gd = pd.to_datetime(sub["GradeDate"], errors="coerce")
        if getattr(gd.dt, "tz", None) is not None:
            gd = gd.dt.tz_convert("America/New_York").dt.tz_localize(None)
        gd = gd.dropna().dt.normalize()
        for d in gd:
            rows.append({"ticker": t, "signal_date": d})
    if not rows:
        return pd.DataFrame(columns=["ticker", "signal_date"])
    ev = pd.DataFrame(rows).drop_duplicates(["ticker", "signal_date"])
    return ev[["ticker", "signal_date"]]


def _trades(ev: pd.DataFrame, members: set, prices: dict, spy: pd.DataFrame, hold: int) -> list[dict]:
    spy_idx = pd.DatetimeIndex(spy.index).normalize()
    spy_open = spy["open"].to_numpy()
    spy_close = spy["close"].to_numpy()
    out = []
    for tkr, sig in ev.itertuples(index=False):
        if tkr not in members:
            continue
        df = prices.get(tkr)
        if df is None:
            continue
        idx = pd.DatetimeIndex(df.index).normalize()
        pos = int(idx.searchsorted(sig, side="right"))    # first bar strictly AFTER the grade date
        if pos >= len(idx):
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
        if abs(c / o - 1) > MAX_MOVE:                      # bad-bar guard
            continue
        gross = (c / o - 1) * 1e4 - (sc / so - 1) * 1e4    # SPY-hedged, long
        out.append({"date": exit_day, "gross_bps": gross})
    return out


def _rank_t(trades) -> float:
    """Week-clustered net t, used only to report which variant looked best in train (Skeptic info)."""
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
    members = _members()
    ev = _events(members["sp46"])
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
