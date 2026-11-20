"""buyback-announcement-long -- TRAIN/HOLDOUT test (data ONLY via research_data as rd).

Hypothesis: an 8-K item 8.01 that announces an OPEN-MARKET SHARE REPURCHASE AUTHORIZATION is a credible
(non-binding) undervaluation signal; investors underreact to the soft commitment and the stock drifts up
over the following weeks as the firm buys into a shrinking float (Ikenberry-Lakonishok-Vermaelen 1995 JFE
~12%/4y, front-loaded to 1-3 months; Peyer-Vermaelen 2009 JFQA ~2.4% first-month alpha, persists
post-publication). We go LONG the filer at the DAY-0 close (entry_session) and hold ~20 sessions.

Signal = an 8.01 filing whose text (body + attached press release) matches a FROZEN, pre-registered
share-repurchase regex, AFTER stripping any "repurchase agreement(s)" phrase (repo/financing contracts,
not an equity buyback). The regex is NOT tuned on results (a tuned keyword list would be a variant and
raise the luck bar) and is deliberately tighter than a bare "repurchase" (which also matches debt/note
repurchases). Rows with no downloaded text (has_text False) are skipped. We dedup only on (ticker,
entry_session) -- no cross-filing dedup, so research and the paper strategy stay identical; a later
reminder / completion 8-K entered weeks late dilutes the mean (conservative).

Return = hedged LONG, close->close GROSS bps = stock_ret - hedge_ret, each trade hedged with ITS OWN
index fund (SPY/IJH/IJR via rd.index_of + rd.hedge_ticker). The harness subtracts cost_bps and clusters
by MONTH (20-session holds overlap across weeks).

Variants (5), explicit CONFIGS dict (no name parsing): name -> (entry_mode, universe, hold).
  entry_mode e0 = entry_session close (DAY 0, the chosen family); e1 = the CLOSE after first_session (a
             session late -- the direct test of how much the day-0 entry matters).
  universe   sp1500 = sp500+sp400+sp600 (current members); midsmall = sp400+sp600; sp500 = point-in-time
             members (rd.pit_filter, required for an sp500-only cut).
`chosen` is PRE-REGISTERED = 'all_sp1500_h20'. The other 4 are a robustness map for the Skeptic and are
NEVER carried to the holdout.
"""
from __future__ import annotations

import math

import pandas as pd

import research_data as rd

COST_BPS = 25.0                       # MUST equal plan.json cost_bps (ranks variants in train only)
MAX_MOVE = 0.60                       # drop bars with |stock move| > 60% over the hold (bad-bar guard)
PREREGISTERED = "all_sp1500_h20"
# FROZEN pre-registered filter (case-insensitive). Not tuned on results. Strip repo/financing contracts
# first ("repurchase agreement(s)"), then require the word repurchase/buyback in a share/program/
# authorization context (a bare "repurchase" also matches debt/note repurchases).
REPO_RE = r"repurchase\s+agreements?"
BUYBACK_RE = (
    r"share\s+repurchase"
    r"|stock\s+repurchase"
    r"|repurchase\s+program"
    r"|repurchase\s+plan"
    r"|repurchase\s+authoriz"
    r"|authoriz\w*\s+(?:the\s+)?(?:repurchase|buy[-\s]?back)"
    r"|buy[-\s]?back"
    r"|repurchase\s+of\s+(?:its\s+)?(?:common\s+)?(?:stock|shares)"
)

# name -> (entry_mode, universe, hold)
CONFIGS = {
    "all_sp1500_h20": ("e0", "sp1500",   20),   # CHOSEN -- card primary rule
    "all_sp1500_h10": ("e0", "sp1500",   10),   # horizon: front-loaded or full-month drift?
    "midsmall_h20":   ("e0", "midsmall", 20),   # sp400+sp600 (less-arbitraged smaller names)
    "all_sp500_h20":  ("e0", "sp500",    20),   # large-cap only (point-in-time membership)
    "e1_sp1500_h20":  ("e1", "sp1500",   20),   # a session late -- how much day-0 entry matters
}


def _universes():
    sp500 = set(rd.universe("sp500"))
    sp400 = set(rd.universe("sp400"))
    sp600 = set(rd.universe("sp600"))
    return sp500, sp400, sp600, (sp500 | sp400 | sp600)


def _events(tickers) -> pd.DataFrame:
    """8-K item 8.01 filings whose text matches the frozen repurchase regex (after the repo strip), with
    both session dates known. The filer is the company (8-Ks are filer-indexed), so a universe ticker
    here is the one that announced the repurchase."""
    f = rd.filings(items=["8.01"], tickers=sorted(tickers))
    if f.empty:
        return f
    f = rd.filing_text(f)
    f = f[f["has_text"].fillna(False)].copy()
    if f.empty:
        return f
    blob = (f["text"].fillna("") + " " + f["exhibit"].fillna(""))
    blob = blob.str.replace(REPO_RE, " ", case=False, regex=True)   # drop repo/financing contracts first
    f = f[blob.str.contains(BUYBACK_RE, case=False, regex=True, na=False)]
    f = f[f["first_session"].notna() & f["entry_session"].notna()].copy()
    if f.empty:
        return f
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
            entry_pos = pos + 1                   # CLOSE of the session AFTER first_session (a day late)
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
    """Month-clustered net t, used only to report which variant looked best in train (NOT a switch)."""
    if not trades:
        return float("-inf")
    df = pd.DataFrame(trades)
    net = df["gross_bps"].astype(float) - COST_BPS
    per = net.groupby(pd.to_datetime(df["date"]).dt.to_period("M")).mean()
    n = len(per)
    if n < 2:
        return float("-inf")
    sd = per.std(ddof=1)
    return float(per.mean() / (sd / math.sqrt(n))) if sd > 0 else 0.0


def run(start: str, end: str, phase: str, chosen: str | None) -> dict:
    sp500, sp400, sp600, sp1500 = _universes()
    midsmall = sp400 | sp600
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
        if univ == "midsmall":
            return ev_all[ev_all["ticker"].isin(midsmall)]
        return ev_all                                       # sp1500

    def _build(name) -> list[dict]:
        em, univ, hold = CONFIGS[name]
        return _trades(_subset(univ), prices, hedges, index_map, hold, em)

    if phase == "holdout":
        return {"variants": 1, "chosen": chosen, "trades": {chosen: _build(chosen)}}

    trades = {n: _build(n) for n in CONFIGS}
    best = max(trades, key=lambda k: _rank_t(trades[k]))      # reported for the Skeptic only
    print(f"train: {len(trades)} variants; best-looking (NOT chosen) = {best}; pre-registered chosen = {PREREGISTERED}")
    return {"variants": len(CONFIGS), "chosen": PREREGISTERED, "trades": trades}
