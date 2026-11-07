"""pipe-short -- TRAIN/HOLDOUT test (data ONLY via research_data as rd).

Hypothesis: an 8-K item 3.02 (sale of unregistered equity = a completed PIPE) marks a discounted, dilutive
placement whose agents/investors hedge by short-selling the target, creating a persistent negative drift
after the filing (Brophy-Ouimet-Sialm 2009; Chaplinsky-Haushalter 2010). We SHORT at the CLOSE of the
session AFTER the first tradable session (= one session after the first reaction -- the earliest a live
after-close dispatch can fill; the open round trip costs more than the whole edge), and cover at the CLOSE
H sessions later. Returns are SPY-hedged GROSS bps, SHORT side (spy_ret - stock_ret, close->close); the
harness subtracts cost_bps. This matches paper_runner's short hedged defn (real_bps - sgn*spy_bps).

Variants (7): universe in {sp1500 (sp500+sp400+sp600), sp46 (sp400+sp600)} x hold H in {1, 3, 5}, plus
`sp1500_h3_ex` = sp1500_h3 with any 3.02 within +/-2 calendar days of an 8-K item 2.02 (earnings release) OR
item 1.01 (material agreement) EXCLUDED -- a robustness check that the drift is the dilution, not a priced
co-incident event. `chosen` is PRE-REGISTERED = 'sp1500_h3' (the idea card's primary rule: full S&P 1500,
the ~3-day screen horizon -- see PLAN.md). The other six configs are a robustness map for the Skeptic only
and are never carried to the holdout.
"""
from __future__ import annotations

import math

import pandas as pd

import research_data as rd

COST_BPS = 25.0                       # MUST equal plan.json cost_bps (ranks variants in train only)
HOLD_GRID = (1, 3, 5)
UNIV_GRID = ("sp1500", "sp46")
PREREGISTERED = "sp1500_h3"
MAX_MOVE = 0.50                       # drop bars with |stock move| > 50% (bad-bar / unadjusted guard)
EX_DAYS = 2                           # exclude a 3.02 within +/- this many calendar days of a 2.02 or 1.01
EX_ITEMS = ["2.02", "1.01"]           # earnings release / material agreement


def _members() -> dict[str, set]:
    sp500 = set(rd.universe("sp500"))
    sp400 = set(rd.universe("sp400"))
    sp600 = set(rd.universe("sp600"))
    return {"sp1500": sp500 | sp400 | sp600, "sp46": sp400 | sp600}


def _events(tickers) -> pd.DataFrame:
    """3.02 8-K filings with a known first tradable session, one row per (ticker, first_session).
    Columns: ticker, first_session (Timestamp), accepted (normalized Timestamp)."""
    f = rd.filings(forms=["8-K"], items=["3.02"], tickers=sorted(tickers))
    if f.empty:
        return f
    f = f[f["first_session"].notna()].copy()
    f["first_session"] = pd.to_datetime(f["first_session"]).dt.normalize()
    f["accepted"] = pd.to_datetime(f["accepted"]).dt.normalize()
    f = f.drop_duplicates(["ticker", "first_session"])
    return f[["ticker", "first_session", "accepted"]]


def _ex_map(tickers) -> dict[str, "pd.DatetimeIndex"]:
    """ticker -> sorted accepted dates of its 8-K item 2.02 / 1.01 filings (the events we exclude near)."""
    f = rd.filings(forms=["8-K"], items=EX_ITEMS, tickers=sorted(tickers))
    out: dict[str, pd.DatetimeIndex] = {}
    if f.empty:
        return out
    acc = pd.to_datetime(f["accepted"]).dt.normalize()
    for t, g in acc.groupby(f["ticker"].astype(str)):
        out[t] = pd.DatetimeIndex(sorted(g.unique()))
    return out


def _has_ex_near(ex_idx: "pd.DatetimeIndex | None", when: pd.Timestamp) -> bool:
    if ex_idx is None or len(ex_idx) == 0:
        return False
    i = int(ex_idx.searchsorted(when, side="left"))
    for j in (i - 1, i):                                  # nearest excluded event on either side
        if 0 <= j < len(ex_idx) and abs((ex_idx[j] - when).days) <= EX_DAYS:
            return True
    return False


def _trades(ev: pd.DataFrame, members: set, prices: dict, spy: pd.DataFrame, hold: int,
            ex_map: dict | None = None) -> list[dict]:
    spy_idx = pd.DatetimeIndex(spy.index).normalize()
    spy_close = spy["close"].to_numpy()
    out = []
    for tkr, fs, acc in ev.itertuples(index=False):
        if tkr not in members:
            continue
        if ex_map is not None and _has_ex_near(ex_map.get(str(tkr)), acc):
            continue
        df = prices.get(tkr)
        if df is None:
            continue
        idx = pd.DatetimeIndex(df.index).normalize()
        pos = int(idx.searchsorted(fs, side="left"))
        if pos >= len(idx) or idx[pos] != fs:          # first_session must be a real bar for this ticker
            continue
        entry_pos = pos + 1                             # CLOSE of the session AFTER first_session
        exit_pos = entry_pos + hold
        if exit_pos >= len(idx):
            continue
        entry_day, exit_day = idx[entry_pos], idx[exit_pos]
        se = int(spy_idx.searchsorted(entry_day, side="left"))
        sx = int(spy_idx.searchsorted(exit_day, side="left"))
        if (se >= len(spy_idx) or sx >= len(spy_idx)
                or spy_idx[se] != entry_day or spy_idx[sx] != exit_day):
            continue
        ce, cx = float(df["close"].iloc[entry_pos]), float(df["close"].iloc[exit_pos])   # close->close hold
        sc_e, sc_x = float(spy_close[se]), float(spy_close[sx])
        if not (ce > 0 and cx > 0 and sc_e > 0 and sc_x > 0):
            continue
        if abs(cx / ce - 1) > MAX_MOVE:                # bad-bar guard
            continue
        gross = (sc_x / sc_e - 1) * 1e4 - (cx / ce - 1) * 1e4   # SPY-hedged, SHORT, close->close
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


def _config(name: str, ev, members, prices, spy, ex_map):
    univ, htag = name.split("_")[0], name.split("_")[1]
    h = int(htag[1:])
    use_ex = name.endswith("_ex")
    return _trades(ev, members[univ], prices, spy, h, ex_map if use_ex else None)


def run(start: str, end: str, phase: str, chosen: str | None) -> dict:
    members = _members()
    all_syms = members["sp1500"]
    ev = _events(all_syms)
    syms = sorted(ev["ticker"].astype(str).unique()) if len(ev) else []
    prices = rd.daily(syms + ["SPY"])
    spy = prices.get("SPY")
    if spy is None:
        raise RuntimeError("SPY daily bars missing from the archive -- required for the hedge")
    ex_map = _ex_map(syms) if syms else {}

    if phase == "holdout":
        return {"variants": 1, "chosen": chosen,
                "trades": {chosen: _config(chosen, ev, members, prices, spy, ex_map)}}

    names = [f"{u}_h{h}" for u in UNIV_GRID for h in HOLD_GRID] + ["sp1500_h3_ex"]
    trades = {n: _config(n, ev, members, prices, spy, ex_map) for n in names}
    best = max(trades, key=lambda k: _rank_t(trades[k]))     # reported for the Skeptic only
    print(f"train: {len(trades)} variants; best-looking (NOT chosen) = {best}; "
          f"pre-registered chosen = {PREREGISTERED}")
    return {"variants": len(trades), "chosen": PREREGISTERED, "trades": trades}
