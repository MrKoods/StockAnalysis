"""activist-13d-long-day0 -- TRAIN/HOLDOUT test (data ONLY via research_data as rd).

Hypothesis: when an activist crosses 5% ownership with intent to influence, it must file a Schedule 13D
(renamed 'SCHEDULE 13D' by SEC in late 2024). Brav-Jiang-Thomas-Partnoy (2008) document a large positive
abnormal return around the INITIAL 13D with drift continuing ~20 days. We go LONG the TARGET company (EDGAR
indexes schedule filings under the SUBJECT company, so rd.filings(tickers=universe) returns the target).

WHY THIS IS A NEW IDEA (same family). The prior `activist-13d-long` (DEAD, train t 0.17, +2.4 bps) entered one
session too late -- at the CLOSE AFTER first_session. The 2026-11-13 audit decomposed event returns and found
the 13D day-0 move is +51 bps t 5.6, with ~nothing left after; entering a session late skipped it. This re-test
changes ONE thing: it enters at the CLOSE of `entry_session` (the first session whose close is still buyable
after SEC accepted the filing, i.e. day 0), so the first held session IS the day-0 drift the late entry missed.
Everything else (windows, cost, week cluster, universe) mirrors the dead idea so the comparison is clean, and the
family's prior 6 variants count in the luck bar automatically. The holdout 2016-2026 was never spent.

Return = hedged LONG, close->close GROSS bps = stock_ret - hedge_ret, each trade hedged with ITS OWN index fund
(SPY/IJH/IJR via rd.index_of + rd.hedge_ticker -- SPY-hedged small caps otherwise carry the small-vs-large swing
as noise). The harness subtracts cost_bps.

Variants (5), explicit CONFIGS dict (no name parsing): name -> (entry_mode, universe, hold).
  entry_mode e0 = entry_session close (DAY 0, the chosen family); e1 = session after first_session close (exactly
             what the DEAD idea did + what a once-daily after-close runner could fill WITHOUT the live EDGAR feed).
  universe   sp1500 = sp500+sp400+sp600 (current members); sp500 = point-in-time members (rd.pit_filter).
`chosen` is PRE-REGISTERED = 'e0_sp1500_h3' (the card's primary rule with the audit's day-0 entry). The other 4
are a robustness map for the Skeptic and are NEVER carried to the holdout.
Robustness reads (verdicts, NOT a switch of chosen): e0 vs e1 = how much the late entry cost (the audit's whole
claim; e1 should reproduce the dead idea's ~0); h1 vs h3 vs h5 = is the drift one day (front-loaded) or several;
sp500 vs sp1500 = large- vs small/mid-cap.
"""
from __future__ import annotations

import math

import pandas as pd

import research_data as rd

COST_BPS = 25.0                       # MUST equal plan.json cost_bps (ranks variants in train only)
MAX_MOVE = 0.50                       # drop bars with |stock move| > 50% (bad-bar / unadjusted guard)
PREREGISTERED = "e0_sp1500_h3"

# name -> (entry_mode, universe, hold)
CONFIGS = {
    "e0_sp1500_h3": ("e0", "sp1500", 3),   # CHOSEN -- card primary horizon, day-0 entry
    "e0_sp1500_h1": ("e0", "sp1500", 1),   # pure day-0 drift (the single first held session)
    "e0_sp1500_h5": ("e0", "sp1500", 5),   # horizon
    "e0_sp500_h3":  ("e0", "sp500",  3),   # large-cap only (point-in-time membership)
    "e1_sp1500_h3": ("e1", "sp1500", 3),   # late entry = reproduces the DEAD idea (should be ~0)
}


def _universes():
    sp500 = set(rd.universe("sp500"))
    sp400 = set(rd.universe("sp400"))
    sp600 = set(rd.universe("sp600"))
    return sp500, (sp500 | sp400 | sp600)


def _events(tickers) -> pd.DataFrame:
    """INITIAL Schedule 13D filings (amendments excluded) with both session dates known. EDGAR indexes a 13D
    under its SUBJECT company, so a universe ticker here is the TARGET of the activist. rd.form_std maps the
    post-2024 'SCHEDULE 13D' back to 'SC 13D' (and '.../A' to 'SC 13D/A'), so keeping form_std == 'SC 13D' keeps
    initial filings across the 2024 rename and drops /A amendments -- the DEAD idea filtered the raw form and so
    missed every post-2024 initial 13D (TEAM.md)."""
    f = rd.filings(forms=["SC 13D"], tickers=sorted(tickers))
    if f.empty:
        return f
    f = f[f["form"].map(rd.form_std) == "SC 13D"]                 # INITIAL only, across the rename
    f = f[f["first_session"].notna() & f["entry_session"].notna()].copy()
    f["first_session"] = pd.to_datetime(f["first_session"]).dt.normalize()
    f["entry_session"] = pd.to_datetime(f["entry_session"]).dt.normalize()
    return f.drop_duplicates(["ticker", "entry_session"])[["ticker", "first_session", "entry_session"]]


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


def _trades(ev, prices, hedges, index_map, hold, entry_mode) -> list[dict]:
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
            entry_pos = pos + 1                   # CLOSE of the session AFTER first_session (the DEAD idea)
        exit_pos = entry_pos + hold
        if exit_pos >= len(idx):
            continue
        ce, cx = float(close[entry_pos]), float(close[exit_pos])   # close->close hold
        if not (ce > 0 and cx > 0):
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
        gross = ((cx / ce - 1) - (hx / he - 1)) * 1e4   # hedged LONG, close->close: stock_ret - hedge_ret
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
    sp500, sp1500 = _universes()
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
        return ev_all

    def _build(name) -> list[dict]:
        em, univ, hold = CONFIGS[name]
        return _trades(_subset(univ), prices, hedges, index_map, hold, em)

    if phase == "holdout":
        return {"variants": 1, "chosen": chosen, "trades": {chosen: _build(chosen)}}

    trades = {n: _build(n) for n in CONFIGS}
    best = max(trades, key=lambda k: _rank_t(trades[k]))      # reported for the Skeptic only
    print(f"train: {len(trades)} variants; best-looking (NOT chosen) = {best}; pre-registered chosen = {PREREGISTERED}")
    return {"variants": len(CONFIGS), "chosen": PREREGISTERED, "trades": trades}
