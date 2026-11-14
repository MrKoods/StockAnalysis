"""material-impairment-short -- TRAIN/HOLDOUT test (data ONLY via research_data as rd).

Hypothesis: when an S&P 1500 company announces a MATERIAL IMPAIRMENT (goodwill / long-lived-asset writedown)
it files an 8-K item 2.06. The writedown says a past acquisition/investment was overvalued and management has
cut its expectations. The negative reaction is not fully priced on the announcement open: impairment magnitude
is uncertain until sell-side re-models (1-2 day analyst lag), 2.06 often co-arrives with an earnings miss, and
retail/momentum holders react late (Li-Shroff-Venkataraman-Zhang 2011; Hirschey-Richardson 2003; Jarva 2009 -
CARs ~-100..-180 bps extending beyond day 0). We SHORT to capture the 2-3 day CONTINUATION.

Entry = day-0 close. Per the 2026-11-13 audit (event tests that entered the close AFTER first_session bought a
day late and lost the day-0 move), the pre-registered `chosen` enters at the CLOSE of `entry_session` (the first
session whose close can still be shorted after SEC accepted the 8-K: before 15:30 ET that day, else the next
session). The drift the hypothesis predicts is days +1..+3 AFTER that close. `e1` variants enter one session
after first_session (= what a once-daily AFTER-close paper runner can actually fill) and measure how much the
mandatory late entry costs (see PLAN.md "Promotability").

Return = hedged SHORT, close->close GROSS bps = hedge_ret - stock_ret, each trade hedged with ITS OWN index
fund (SPY/IJH/IJR via rd.index_of + rd.hedge_ticker, added 2026-11-13 - SPY-hedged small caps carried the
small-vs-large swing as noise). The harness subtracts cost_bps.

Variants (9), explicit CONFIGS dict (no name parsing): name -> (entry_mode, universe, hold, flag).
  entry_mode e0 = entry_session close (chosen family); e1 = session after first_session close (paper-reachable).
  universe   sp1500 = sp500+sp400+sp600 (current members); sp500 = point-in-time members (rd.pit_filter);
             sp46 = sp400+sp600 (current members, no PIT list exists).
  flag       drop = short only if the day-0 reaction (entry close vs prior close) < 0 (materiality proxy, the
             card's "is the signal only large impairments?"); noearn = drop 2.06 filings co-filed with item
             2.02 (earnings release) - isolates the pure impairment from the earnings-miss confound (card risk #1).
`chosen` is PRE-REGISTERED = 'e0_sp1500_h3' (the card's primary rule with the audit's day-0 entry). The other 8
are a robustness map for the Skeptic and are NEVER carried to the holdout.
Robustness reads (verdicts, NOT a switch of chosen): e0 vs e1 = how much the late entry costs (if e1 ~= 0 the
edge is untradeable until the intraday EDGAR feed is built); drop/noearn vs base = is the edge only large or
only earnings-driven impairments; sp500 vs sp46 = is it a large- or small-cap effect; h2/h3/h5 = the horizon.
"""
from __future__ import annotations

import math

import pandas as pd

import research_data as rd

COST_BPS = 25.0                       # MUST equal plan.json cost_bps (ranks variants in train only)
MAX_MOVE = 0.60                       # drop bars with |stock move| > 60% (bad-bar / unadjusted guard)
PREREGISTERED = "e0_sp1500_h3"

# name -> (entry_mode, universe, hold, flag)
CONFIGS = {
    "e0_sp1500_h3":        ("e0", "sp1500", 3, None),      # CHOSEN
    "e0_sp1500_h5":        ("e0", "sp1500", 5, None),      # horizon
    "e0_sp1500_h2":        ("e0", "sp1500", 2, None),      # horizon (immediate?)
    "e0_sp500_h3":         ("e0", "sp500",  3, None),      # large-cap (impairments skew big acquirers)
    "e0_sp46_h3":          ("e0", "sp46",   3, None),      # small/mid-cap
    "e1_sp1500_h3":        ("e1", "sp1500", 3, None),      # late entry = paper-reachable today
    "e1_sp500_h3":         ("e1", "sp500",  3, None),      # late entry, large-cap
    "e0_sp1500_h3_drop":   ("e0", "sp1500", 3, "drop"),    # materiality (day-0 reaction < 0)
    "e0_sp1500_h3_noearn": ("e0", "sp1500", 3, "noearn"),  # exclude co-filed earnings (item 2.02)
}


def _universes():
    sp500 = set(rd.universe("sp500"))
    sp400 = set(rd.universe("sp400"))
    sp600 = set(rd.universe("sp600"))
    return sp500, sp400, sp600, (sp500 | sp400 | sp600), (sp400 | sp600)


def _events(tickers) -> pd.DataFrame:
    """One row per (ticker, first_session, entry_session) for 8-K item 2.06, with co_earn = any filing in the
    group also carried item 2.02 (earnings release). Rows need both session dates known."""
    f = rd.filings(forms=["8-K"], items=["2.06"], tickers=sorted(tickers))
    if f.empty:
        return f
    f = f[f["first_session"].notna() & f["entry_session"].notna()].copy()
    f["first_session"] = pd.to_datetime(f["first_session"]).dt.normalize()
    f["entry_session"] = pd.to_datetime(f["entry_session"]).dt.normalize()
    items = f["items"].fillna("").astype(str)
    f["co_earn"] = items.apply(lambda s: "2.02" in [x.strip() for x in s.split(",")])
    return f.groupby(["ticker", "first_session", "entry_session"], as_index=False).agg(co_earn=("co_earn", "max"))


def _series(df):
    if df is None or not len(df):
        return None
    return pd.DatetimeIndex(df.index).normalize(), df["close"].to_numpy()


def _close_on(series, day):
    idx, c = series
    p = int(idx.searchsorted(day, side="left"))
    if p >= len(idx) or idx[p] != day:
        return None
    v = float(c[p])
    return v if v > 0 else None


def _trades(ev, prices, hedges, index_map, hold, entry_mode, flag) -> list[dict]:
    out = []
    for r in ev.itertuples(index=False):
        tkr = r.ticker
        df = prices.get(tkr)
        if df is None:
            continue
        idx = pd.DatetimeIndex(df.index).normalize()
        close = df["close"].to_numpy()
        if entry_mode == "e0":
            sig = r.entry_session
            pos = int(idx.searchsorted(sig, side="left"))
            if pos >= len(idx) or idx[pos] != sig:
                continue
            entry_pos = pos                       # CLOSE of entry_session (day 0)
        else:
            sig = r.first_session
            pos = int(idx.searchsorted(sig, side="left"))
            if pos >= len(idx) or idx[pos] != sig:
                continue
            entry_pos = pos + 1                   # CLOSE of the session AFTER first_session (paper-reachable)
        exit_pos = entry_pos + hold
        if entry_pos - 1 < 0 or exit_pos >= len(idx):
            continue
        ce, cx = float(close[entry_pos]), float(close[exit_pos])   # close->close hold
        if not (ce > 0 and cx > 0):
            continue
        if flag == "drop":                        # materiality: only short a negative day-0 reaction
            cp = float(close[entry_pos - 1])
            if not (cp > 0) or (ce / cp - 1) >= 0:
                continue
        if abs(cx / ce - 1) > MAX_MOVE:           # bad-bar guard
            continue
        hs = hedges.get(index_map.get(tkr))
        if hs is None:
            continue
        he = _close_on(hs, idx[entry_pos])
        hx = _close_on(hs, idx[exit_pos])
        if he is None or hx is None:
            continue
        gross = ((hx / he - 1) - (cx / ce - 1)) * 1e4   # hedged SHORT, close->close: hedge_ret - stock_ret
        out.append({"date": idx[exit_pos], "gross_bps": gross})
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
    sp500, sp400, sp600, sp1500, sp46 = _universes()
    ev_all = _events(sorted(sp1500))
    index_map = rd.index_of(sorted(sp1500))
    syms = sorted(ev_all["ticker"].astype(str).unique()) if len(ev_all) else []
    prices = rd.daily(syms + ["SPY", "IJH", "IJR"])
    hedges = {}
    for ix in ("sp500", "sp400", "sp600"):
        s = _series(prices.get(rd.hedge_ticker(ix)))
        if s is None:
            raise RuntimeError(f"hedge fund {rd.hedge_ticker(ix)} missing from the archive - required for the hedge")
        hedges[ix] = s

    def _subset(univ) -> pd.DataFrame:
        if len(ev_all) == 0:
            return ev_all
        if univ == "sp500":
            return rd.pit_filter(ev_all, "entry_session")   # point-in-time S&P 500 membership (required)
        if univ == "sp46":
            return ev_all[ev_all["ticker"].isin(sp46)]
        return ev_all[ev_all["ticker"].isin(sp1500)]

    def _build(name) -> list[dict]:
        em, univ, hold, flag = CONFIGS[name]
        sub = _subset(univ)
        if flag == "noearn" and len(sub):
            sub = sub[~sub["co_earn"].astype(bool)]
        return _trades(sub, prices, hedges, index_map, hold, em, flag)

    if phase == "holdout":
        return {"variants": 1, "chosen": chosen, "trades": {chosen: _build(chosen)}}

    trades = {n: _build(n) for n in CONFIGS}
    best = max(trades, key=lambda k: _rank_t(trades[k]))      # reported for the Skeptic only
    print(f"train: {len(trades)} variants; best-looking (NOT chosen) = {best}; pre-registered chosen = {PREREGISTERED}")
    return {"variants": len(CONFIGS), "chosen": PREREGISTERED, "trades": trades}
