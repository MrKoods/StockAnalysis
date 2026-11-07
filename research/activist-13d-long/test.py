"""activist-13d-long -- TRAIN/HOLDOUT test (data ONLY via research_data as rd).

Hypothesis: when an activist crosses 5% ownership with intent to influence, it must file a Schedule 13D.
Brav-Jiang-Thomas-Partnoy (2008) document a large positive abnormal return around the initial 13D with drift
continuing ~20 days. We go LONG the TARGET company (the S&P-1500 name the 13D is filed AGAINST -- EDGAR indexes
schedule filings under the subject company, so rd.filings(tickers=universe) returns them) and hold a few days.

Entry timing is paper-matchable and leak-free: enter at the CLOSE of the session AFTER the first tradable
session (first_session+1). The once-daily runner fires after the close, and the SEC daily index reaches our
archive the next weekday, so the earliest close we could actually fill is first_session+1 -- one session after
the first public reaction. Exit at the CLOSE H sessions later. Returns are SPY-hedged GROSS bps, LONG side
(stock_ret - spy_ret, close->close); the harness subtracts cost_bps. This matches paper_runner's long hedged
definition (real_bps - sgn*spy_bps with sgn=+1).

Variants (6): universe in {sp1500 (sp500+sp400+sp600), sp500} x hold H in {1, 3, 5}. INITIAL SC 13D only --
SC 13D/A amendments are dropped (we keep the raw form == "SC 13D"). `chosen` is PRE-REGISTERED = 'sp1500_h3'
(full activist universe, the evidence's few-day drift horizon -- see PLAN.md). The other five configs are a
robustness map for the Skeptic only and are never carried to the holdout. NOTE: the shared cost floor is the
most-expensive index in the universe (sp600 close->close), so the sp500-only variant is over-charged -- a
conservative bias documented in PLAN.md.
"""
from __future__ import annotations

import math

import pandas as pd

import research_data as rd

COST_BPS = 25.0                       # MUST equal plan.json cost_bps (ranks variants in train only)
HOLD_GRID = (1, 3, 5)
UNIV_GRID = ("sp1500", "sp500")
PREREGISTERED = "sp1500_h3"
MAX_MOVE = 0.50                       # drop bars with |stock move| > 50% (bad-bar / unadjusted guard)


def _members() -> dict[str, set]:
    sp500 = set(rd.universe("sp500"))
    sp400 = set(rd.universe("sp400"))
    sp600 = set(rd.universe("sp600"))
    return {"sp500": sp500, "sp1500": sp500 | sp400 | sp600}


def _events(tickers) -> pd.DataFrame:
    """Initial SC 13D filings (amendments excluded) with a known first tradable session.
    Columns: ticker, first_session (Timestamp). EDGAR indexes a 13D under its SUBJECT company, so a
    universe ticker here is the TARGET of the activist."""
    f = rd.filings(forms=["SC 13D"], tickers=sorted(tickers))
    if f.empty:
        return f
    f = f[f["form"].astype(str).str.strip() == "SC 13D"]          # INITIAL only -- drop SC 13D/A amendments
    f = f[f["first_session"].notna()].copy()
    f["first_session"] = pd.to_datetime(f["first_session"]).dt.normalize()
    f = f.drop_duplicates(["ticker", "first_session"])
    return f[["ticker", "first_session"]]


def _trades(ev: pd.DataFrame, members: set, prices: dict, spy: pd.DataFrame, hold: int) -> list[dict]:
    spy_idx = pd.DatetimeIndex(spy.index).normalize()
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
    univ, htag = name.split("_")[0], name.split("_")[1]
    h = int(htag[1:])
    return _trades(ev, members[univ], prices, spy, h)


def run(start: str, end: str, phase: str, chosen: str | None) -> dict:
    members = _members()
    ev = _events(members["sp1500"])
    syms = sorted(ev["ticker"].astype(str).unique()) if len(ev) else []
    prices = rd.daily(syms + ["SPY"])
    spy = prices.get("SPY")
    if spy is None:
        raise RuntimeError("SPY daily bars missing from the archive -- required for the hedge")

    if phase == "holdout":
        return {"variants": 1, "chosen": chosen,
                "trades": {chosen: _config(chosen, ev, members, prices, spy)}}

    names = [f"{u}_h{h}" for u in UNIV_GRID for h in HOLD_GRID]
    trades = {n: _config(n, ev, members, prices, spy) for n in names}
    best = max(trades, key=lambda k: _rank_t(trades[k]))     # reported for the Skeptic only
    print(f"train: {len(trades)} variants; best-looking (NOT chosen) = {best}; "
          f"pre-registered chosen = {PREREGISTERED}")
    return {"variants": len(trades), "chosen": PREREGISTERED, "trades": trades}
