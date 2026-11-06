"""turn-of-month -- TRAIN/HOLDOUT test (data ONLY via research_data as rd).

Hypothesis: US large-caps earn an abnormal return in the turn-of-the-month window. Go LONG the whole
S&P 500 (equal weight) at the CLOSE of the last NYSE trading day of each calendar month (day T) and exit
at the CLOSE of the H-th session of the new month. Returns are RAW (unhedged) close-to-close bps: TOM is
a market-level seasonal, so SPY-hedging would cancel it. The harness subtracts cost_bps and clusters by week.

Variants (4): tom_h1 / tom_h2 / tom_h3 (exit the 1st/2nd/3rd new-month session) + mid_h3, a mid-month
placebo (enter the middle session of the month, hold 3) that earns the same beta but carries no TOM signal,
so the Skeptic can read the TOM premium as tom_h3 minus mid_h3. `chosen` is PRE-REGISTERED = 'tom_h3'
(the canonical McConnell-Xu window, the idea's stated rule) -- NOT best-of-train. The other three configs
are reported only as a robustness/placebo map and never carried to the holdout.

Knowing which calendar day is month-end is not look-ahead (it is the session calendar, fixed in advance);
every entry uses only prices at/through its own close and exits strictly later.
"""
from __future__ import annotations

import math
from collections import defaultdict

import pandas as pd

import research_data as rd

COST_BPS = 10.0                 # MUST equal plan.json cost_bps (ranks variants only; harness re-charges)
HOLD_GRID = (1, 2, 3)           # new-month sessions held; exit = close of the H-th new-month session
MID_HOLD = 3                    # placebo horizon
MIN_SESSIONS_FOR_MID = 13       # only take a mid-month placebo in months long enough to keep it off both turns
PREREGISTERED = "tom_h3"
UNIVERSE = "sp500"


def _closes_and_sessions():
    """Per-ticker close Series (indexed by normalised date) + the NYSE session calendar (from SPY)."""
    syms = rd.universe(UNIVERSE)
    prices = rd.daily(syms + ["SPY"])
    spy = prices.get("SPY")
    if spy is None:
        raise RuntimeError("SPY daily bars missing from the archive -- needed for the NYSE session calendar")
    sess = pd.DatetimeIndex(pd.to_datetime(spy.index)).normalize().unique().sort_values()
    closes = {}
    for t, df in prices.items():
        if t == "SPY":
            continue
        idx = pd.DatetimeIndex(pd.to_datetime(df.index)).normalize()
        s = pd.Series(df["close"].to_numpy(dtype=float), index=idx)
        closes[t] = s[~s.index.duplicated(keep="last")]
    return closes, sess


def _entry_positions(sess: pd.DatetimeIndex, kind: str) -> list[int]:
    """kind 'tom' -> the last session index of each month; 'mid' -> the middle session of long-enough months."""
    groups: dict[tuple, list[int]] = defaultdict(list)
    for i, d in enumerate(sess):
        groups[(d.year, d.month)].append(i)
    if kind == "tom":
        return [v[-1] for v in groups.values()]
    return [v[len(v) // 2] for v in groups.values() if len(v) >= MIN_SESSIONS_FOR_MID]


def _trades(closes: dict, sess: pd.DatetimeIndex, entry_pos: list[int], hold: int) -> list[dict]:
    out = []
    n = len(sess)
    for p in entry_pos:
        xp = p + hold
        if xp >= n:
            continue
        entry_day, exit_day = sess[p], sess[xp]
        for s in closes.values():
            ce = s.get(entry_day)
            cx = s.get(exit_day)
            if ce is None or cx is None or not (ce > 0 and cx > 0):
                continue
            out.append({"date": exit_day, "gross_bps": (cx / ce - 1) * 1e4})
    return out


def _trades_for(name: str, closes: dict, sess: pd.DatetimeIndex) -> list[dict]:
    if name == "mid_h3":
        return _trades(closes, sess, _entry_positions(sess, "mid"), MID_HOLD)
    return _trades(closes, sess, _entry_positions(sess, "tom"), int(name.split("_h")[1]))


def _rank_t(trades) -> float:
    """Week-clustered net t, reported only to say which variant looked best in train."""
    if not trades:
        return float("-inf")
    df = pd.DataFrame(trades)
    net = df["gross_bps"].astype(float) - COST_BPS
    per = net.groupby(pd.to_datetime(df["date"]).dt.to_period("W")).mean()
    if len(per) < 2:
        return float("-inf")
    sd = per.std(ddof=1)
    return float(per.mean() / (sd / math.sqrt(len(per)))) if sd > 0 else 0.0


def run(start: str, end: str, phase: str, chosen: str | None) -> dict:
    closes, sess = _closes_and_sessions()

    if phase == "holdout":
        return {"variants": 1, "chosen": chosen,
                "trades": {chosen: _trades_for(chosen, closes, sess)}}

    names = [f"tom_h{h}" for h in HOLD_GRID] + ["mid_h3"]
    trades = {n: _trades_for(n, closes, sess) for n in names}
    best = max(trades, key=lambda k: _rank_t(trades[k]))     # reported for the Skeptic only
    print(f"train: {len(names)} variants; best-looking (NOT chosen) = {best}; "
          f"pre-registered chosen = {PREREGISTERED}")
    return {"variants": len(names), "chosen": PREREGISTERED, "trades": trades}
