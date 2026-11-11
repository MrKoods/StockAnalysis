"""issuer-self-tender-long -- TRAIN/HOLDOUT test (data ONLY via research_data as rd).

Hypothesis: when an S&P 1500 company launches a self-tender offer (repurchase its OWN shares at a premium) it
files SEC Form SC TO-I. This is a hard, time-limited undervaluation signal with a near-term price floor (no
holder tenders below the offer price). Peyer-Vermaelen (2009) measure ~+200 bps CAR over 3-5 days; Lie (2005)
finds tender repurchases react more strongly than open-market buybacks. We go LONG at the CLOSE of the session
AFTER the first tradable session (= the earliest a once-daily after-close dispatch can actually fill -- one
session after the first reaction) and exit at the CLOSE H sessions later. Returns are SPY-hedged GROSS bps on
the LONG side (stock_ret - spy_ret, close->close); the harness subtracts cost_bps. This matches paper_runner's
long-hedged defn (real_bps - sgn*spy_bps, sgn=+1 for long).

For SC TO-I the FILER is the issuer, so rd.filings(tickers=sp1500) returns the right names directly. We keep raw
form == "SC TO-I" only (dropping SC TO-I/A amendments -- the initial launch is the event).

Variants (7): universe in {sp1500 (sp500+sp400+sp600), sp500} x hold H in {1, 3, 5} (6) plus one
momentum-conditioned variant `sp1500_h3_momneg` (base sp1500, H=3, kept only when the prior-20-session stock
return as of first_session < 0 -- the "deeper undervaluation" read). `chosen` is PRE-REGISTERED = `sp1500_h3`
(the idea card's primary rule: all S&P 1500, the ~3-day academic horizon -- see PLAN.md). The other 6 are a
robustness map for the Skeptic only and are never carried to holdout. Central robustness read (NOT a switch of
chosen): hold-1 vs hold-3/5 maps the post-entry decay -- if the edge is gone by H=3 the one-session-late entry
has eaten it. sp1500 vs sp500 reads small/mid-cap concentration. momneg reads undervaluation vs momentum.
"""
from __future__ import annotations

import math

import pandas as pd

import research_data as rd

COST_BPS = 25.0                       # MUST equal plan.json cost_bps (ranks variants in train only)
MOM_LOOKBACK = 20                     # sessions of prior stock return for the momneg filter
PREREGISTERED = "sp1500_h3"
MAX_MOVE = 0.50                       # drop bars with |stock move| > 50% (bad-bar / unadjusted guard)

# name -> (universe key, hold H, momneg filter?)
CONFIGS = {
    "sp1500_h1": ("sp1500", 1, False),
    "sp1500_h3": ("sp1500", 3, False),
    "sp1500_h5": ("sp1500", 5, False),
    "sp500_h1": ("sp500", 1, False),
    "sp500_h3": ("sp500", 3, False),
    "sp500_h5": ("sp500", 5, False),
    "sp1500_h3_momneg": ("sp1500", 3, True),
}


def _members() -> dict[str, set]:
    sp500 = set(rd.universe("sp500"))
    sp400 = set(rd.universe("sp400"))
    sp600 = set(rd.universe("sp600"))
    return {"sp1500": sp500 | sp400 | sp600, "sp500": sp500}


def _events(tickers) -> pd.DataFrame:
    """Every INITIAL SC TO-I with a known first tradable session, one row per (ticker, first_session).
    Columns: ticker, first_session (Timestamp)."""
    f = rd.filings(forms=["SC TO-I"], tickers=sorted(tickers))
    if f.empty:
        return f
    f = f[f["form"].astype(str).str.strip() == "SC TO-I"]        # initial only, drop SC TO-I/A amendments
    f = f[f["first_session"].notna()].copy()
    if f.empty:
        return f
    f["first_session"] = pd.to_datetime(f["first_session"]).dt.normalize()
    f = f.drop_duplicates(["ticker", "first_session"])
    return f[["ticker", "first_session"]]


def _trades(ev: pd.DataFrame, members: set, prices: dict, spy: pd.DataFrame, hold: int,
            momneg: bool) -> list[dict]:
    spy_idx = pd.DatetimeIndex(spy.index).normalize()
    spy_close = spy["close"].to_numpy()
    out = []
    for tkr, fs in ev[["ticker", "first_session"]].itertuples(index=False):
        if tkr not in members:
            continue
        df = prices.get(tkr)
        if df is None:
            continue
        idx = pd.DatetimeIndex(df.index).normalize()
        pos = int(idx.searchsorted(fs, side="left"))
        if pos >= len(idx) or idx[pos] != fs:          # first_session must be a real bar for this ticker
            continue
        if momneg:                                     # prior-20-session stock return as of first_session < 0
            if pos < MOM_LOOKBACK:
                continue
            c0, cp = float(df["close"].iloc[pos]), float(df["close"].iloc[pos - MOM_LOOKBACK])
            if not (c0 > 0 and cp > 0) or (c0 / cp - 1) >= 0:
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
        gross = (cx / ce - 1) * 1e4 - (sc_x / sc_e - 1) * 1e4   # SPY-hedged, LONG, close->close
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


def _config(name: str, ev, members, prices, spy):
    univ, hold, momneg = CONFIGS[name]
    return _trades(ev, members[univ], prices, spy, hold, momneg)


def run(start: str, end: str, phase: str, chosen: str | None) -> dict:
    members = _members()
    all_syms = members["sp1500"]
    ev = _events(all_syms)
    syms = sorted(ev["ticker"].astype(str).unique()) if len(ev) else []
    prices = rd.daily(syms + ["SPY"])
    spy = prices.get("SPY")
    if spy is None:
        raise RuntimeError("SPY daily bars missing from the archive -- required for the hedge")

    if phase == "holdout":
        return {"variants": 1, "chosen": chosen,
                "trades": {chosen: _config(chosen, ev, members, prices, spy)}}

    trades = {n: _config(n, ev, members, prices, spy) for n in CONFIGS}
    best = max(trades, key=lambda k: _rank_t(trades[k]))     # reported for the Skeptic only
    print(f"train: {len(trades)} variants; best-looking (NOT chosen) = {best}; "
          f"pre-registered chosen = {PREREGISTERED}")
    return {"variants": len(trades), "chosen": PREREGISTERED, "trades": trades}
