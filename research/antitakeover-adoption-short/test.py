"""antitakeover-adoption-short -- TRAIN/HOLDOUT test (data ONLY via research_data as rd).

Hypothesis: when a board ADOPTS a stockholder rights plan ("poison pill") it files an 8-K item 5.03
(charter/bylaw amendment). The pill entrenches management and removes acquisition-premium optionality;
the reaction is negative (Ryngaert 1988 JFE ~-150 bps CAR) and, per the entrenchment literature
(Bebchuk-Coates-Subramanian 2002; Gompers-Ishii-Metrick 2003), the market UNDERREACTS so the stock
drifts down over the following weeks. We SHORT the filer at the DAY-0 close (entry_session) and hold
~15 sessions to capture the post-announcement drift (the big intraday move on day 0 is already priced
by the close we short at; we want the residual +1..+15 drift).

Signal = an 8-K item 5.03 that both (a) mentions a rights plan / agreement / poison pill AND (b) carries
a FROZEN ADOPTION indicator -- one of the two canonical ways a new pill is announced: "adopt[ed/ion of]"
or "enter[ed] into" the instrument, OR "declar[ed] a ... dividend" (of one preferred-share-purchase
right per share -- the formal pill-distribution mechanism). This is NOT tuned on results (smoke shows
counts only). The indicator set deliberately EXCLUDES "terminat"/"redeem"/"expir"/"amend" both as
triggers and as a negative filter: in an item-5.03 universe those words appear in genuine adoptions too
(an adoption 8-K describes the plan's expiration, termination and redemption provisions, and 5.03 itself
means "charter/bylaw amendment"), so a negative keyword list would reject real adoptions. Instead,
requiring a positive adoption indicator naturally keeps out terminations ("terminated"/"redeemed", which
do not adopt / enter into / declare a dividend of rights). Residual contamination by amendments or the
rare mis-caught termination DILUTES a SHORT edge (amendments ~ neutral, terminations are bullish) -- so a
holdout pass despite it is conservative. Item 5.03 scoping also keeps out financing "registration rights
agreements" (those are item-1.01 events). Rows with no downloaded text (has_text False) are skipped. We
dedup only on (ticker, entry_session) -- no cross-filing dedup -- so research and the paper strategy stay
byte-for-byte identical; a later reminder 8-K entered weeks late dilutes the mean (conservative).

Return = hedged SHORT, close->close GROSS bps = hedge_ret - stock_ret, each trade hedged with ITS OWN
index fund (SPY/IJH/IJR via rd.index_of + rd.hedge_ticker -- SPY-hedged small caps otherwise carry the
small-vs-large swing as noise, 2026-11-13). The harness subtracts cost_bps and clusters by MONTH
(15-session holds overlap across weeks).

Variants (6), explicit CONFIGS dict (no name parsing): name -> (entry_mode, universe, hold).
  entry_mode e0 = entry_session close (DAY 0, the chosen family); e1 = the CLOSE after first_session
             (a session late -- the direct test of how much the day-0 entry matters / paper-reachable).
  universe   sp1500 = sp500+sp400+sp600 (current members); midsmall = sp400+sp600 (entrenchment/G-index
             underperformance is stronger in smaller, less-covered names); sp500 = point-in-time members
             (rd.pit_filter, required for an sp500-only cut).
`chosen` is PRE-REGISTERED = 'e0_sp1500_h15' (the card's primary rule). The other 5 are a robustness map
for the Skeptic and are NEVER carried to the holdout.
"""
from __future__ import annotations

import math

import pandas as pd

import research_data as rd

COST_BPS = 25.0                       # MUST equal plan.json cost_bps (ranks variants in train only)
MAX_MOVE = 0.60                       # drop bars with |stock move| > 60% over the hold (bad-bar guard)
PREREGISTERED = "e0_sp1500_h15"

# FROZEN pre-registered rights-plan ADOPTION filter (case-insensitive). Not tuned on results.
# Require BOTH: the instrument is present (PILL_RE) AND a positive adoption indicator (ADOPT_RE).
PILL_RE = r"(?:rights\s+(?:plan|agreement)|poison\s+pill)"
ADOPT_RE = (r"\badopt"                                              # "adopted / adoption of a ... rights plan"
            r"|enter(?:ed|ing|s)?\s+into"                          # "entered into a Rights Agreement"
            r"|declar\w*\s+(?:a\s+)?(?:[a-z-]+\s+){0,3}dividend")   # "declared a dividend of one ... right"

# name -> (entry_mode, universe, hold)
CONFIGS = {
    "e0_sp1500_h15":   ("e0", "sp1500",   15),   # CHOSEN -- card primary rule
    "e0_sp1500_h10":   ("e0", "sp1500",   10),   # horizon: is the drift front-loaded?
    "e0_sp1500_h5":    ("e0", "sp1500",    5),   # horizon: immediate continuation only?
    "e0_midsmall_h15": ("e0", "midsmall", 15),   # sp400+sp600 (entrenchment effect stronger in smaller)
    "e0_sp500_h15":    ("e0", "sp500",    15),   # large-cap only (point-in-time membership)
    "e1_sp1500_h15":   ("e1", "sp1500",   15),   # a session late -- how much day-0 entry matters
}


def _universes():
    sp500 = set(rd.universe("sp500"))
    sp400 = set(rd.universe("sp400"))
    sp600 = set(rd.universe("sp600"))
    return sp500, sp400, sp600, (sp500 | sp400 | sp600), (sp400 | sp600)


def _events(tickers) -> pd.DataFrame:
    """8-K item 5.03 filings whose text matches the frozen rights-plan ADOPTION regex, with both session
    dates known. 8-Ks are filer-indexed, so a universe ticker here is the company that adopted the pill."""
    f = rd.filings(forms=["8-K"], items=["5.03"], tickers=sorted(tickers))
    if f.empty:
        return f
    f = rd.filing_text(f)
    f = f[f["has_text"].fillna(False)].copy()
    if f.empty:
        return f
    blob = f["text"].fillna("") + " " + f["exhibit"].fillna("")
    f = f[blob.str.contains(PILL_RE, case=False, regex=True, na=False)
          & blob.str.contains(ADOPT_RE, case=False, regex=True, na=False)]
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
        gross = ((hx / he - 1) - (cx / ce - 1)) * 1e4   # hedged SHORT, close->close: hedge_ret - stock_ret
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
    sp500, sp400, sp600, sp1500, midsmall = _universes()
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
