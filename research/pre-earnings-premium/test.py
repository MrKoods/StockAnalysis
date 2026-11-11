"""pre-earnings-premium -- TRAIN/HOLDOUT test (data ONLY via research_data as rd).

Hypothesis: a stock earns a RISK PREMIUM in the 1-2 sessions BEFORE a scheduled earnings
announcement -- investors who dislike holding through the release pay the holders who absorb that
uncertainty (Laarits 2020 "Pre-Announcement Risk"; Ai, Bansal & Han 2021 find 72% of the
earnings-period excess return accrues BEFORE the release). We LONG at the CLOSE of session A-2 (two
sessions before the announcement session A) and EXIT at the CLOSE of session A-1 (one session before
A), so we hold ZERO earnings-surprise risk -- distinct from V4 EPRE, which holds THROUGH the
announcement. Returns are SPY-hedged GROSS bps on the LONG side (stock_ret - spy_ret, close->close);
the harness subtracts cost_bps. Hedging isolates the firm-specific pre-announcement drift from market
beta (firms announce on staggered days, so the market leg is noise).

Universe is S&P 500 ONLY: at a ~1-session hold the premium (tens of bps at most) cannot survive the
12-22 bps round-trip close spreads of S&P 400/600, and a plan carries ONE cost floor -- mixing in
sp600 would over-charge every sp500 trade. Scoping to the cheapest close fills gives the premium its
only tradable shot (see PLAN.md "Why sp500 only").

Variants (4):
  h1_sp500      hold 1 (enter close A-2, exit close A-1), HEDGED      <- PRE-REGISTERED chosen
  h2_sp500      hold 2 (enter close A-3, exit close A-1), HEDGED      (does a 2-session window help?)
  h1_mom_sp500  h1 + prior-5-session return > 0 at entry, HEDGED      (buy pre-announcement winners)
  h1_raw_sp500  h1 but RAW (unhedged)                                 (market-level vs firm-specific?)
`chosen` is PRE-REGISTERED = 'h1_sp500' (the idea card's primary rule: the cleanest single
pre-announcement session of Laarits; NOT best-train-t). The other 3 are a robustness map for the
Skeptic and are never carried to the holdout. Reads (NOT a switch of chosen): h1_raw >> h1_sp500 =>
market beta during earnings season, not a firm-specific premium; h2 >> h1 => edge not in the final
24h; h1_mom >> h1 => a momentum effect, not an uncertainty premium.
"""
from __future__ import annotations

import math

import pandas as pd

import research_data as rd

COST_BPS = 8.0               # MUST equal plan.json cost_bps (ranks variants in train only)
MAX_MOVE = 0.50              # drop bars with |move| > 50% (bad-bar / unadjusted guard)
PREREGISTERED = "h1_sp500"
# name -> (hold sessions, hedged?, prior-5-session momentum filter?)
CONFIGS = {
    "h1_sp500":     (1, True,  False),
    "h2_sp500":     (2, True,  False),
    "h1_mom_sp500": (1, True,  True),
    "h1_raw_sp500": (1, False, False),
}


def _events(tickers, sess_set) -> dict:
    """ticker -> sorted list of announcement sessions (normalized Timestamps) that are real SPY
    sessions. One entry per (ticker, session)."""
    out = {}
    edf = rd.earnings(sorted(tickers))
    for t, df in edf.items():
        if "Earnings Date" not in df.columns:
            continue
        d = pd.to_datetime(df["Earnings Date"], utc=True, errors="coerce")
        d = d.dt.tz_convert("America/New_York").dt.tz_localize(None).dt.normalize()
        days = sorted({ts for ts in pd.DatetimeIndex(d.dropna().unique()) if ts in sess_set})
        if days:
            out[t] = days
    return out


def _trades(events, members, prices, spy_sessions, spy_close_by_sess, hold, hedged, mom) -> list[dict]:
    pos_of = {s: i for i, s in enumerate(spy_sessions)}      # SPY calendar session -> index
    out = []
    for tkr, days in events.items():
        if tkr not in members:
            continue
        df = prices.get(tkr)
        if df is None or len(df) < 7:
            continue
        idx = pd.DatetimeIndex(df.index).normalize()
        close = df["close"].to_numpy()
        tpos = {s: i for i, s in enumerate(idx)}
        for a in days:
            p = pos_of.get(a)
            if p is None or p - 1 - hold < 0:
                continue
            entry_sess = spy_sessions[p - 1 - hold]          # close A-2 (h1) / A-3 (h2)
            exit_sess = spy_sessions[p - 1]                  # close A-1 (always)
            ei, xi = tpos.get(entry_sess), tpos.get(exit_sess)
            if ei is None or xi is None:
                continue
            ce, cx = float(close[ei]), float(close[xi])
            if not (ce > 0 and cx > 0) or abs(cx / ce - 1) > MAX_MOVE:
                continue
            if mom:
                if ei < 5:
                    continue
                c5 = float(close[ei - 5])
                if not (c5 > 0) or (ce / c5 - 1) <= 0:       # prior 5-session return must be positive
                    continue
            stock = (cx / ce - 1) * 1e4
            if hedged:
                se, sx = spy_close_by_sess.get(entry_sess), spy_close_by_sess.get(exit_sess)
                if se is None or sx is None or se <= 0 or sx <= 0:
                    continue
                gross = stock - (sx / se - 1) * 1e4           # SPY-hedged LONG, close->close
            else:
                gross = stock
            out.append({"date": exit_sess, "gross_bps": gross})
    return out


def _rank_t(trades) -> float:
    """Day-clustered net t, reported only for which variant looked best in train (cluster='day')."""
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
    members = set(rd.universe("sp500"))
    spy = rd.daily(["SPY"]).get("SPY")
    if spy is None:
        raise RuntimeError("SPY daily bars missing -- required for the session calendar and the hedge")
    spy_sessions = list(pd.DatetimeIndex(spy.index).normalize())
    spy_close_by_sess = {s: float(c) for s, c in zip(spy_sessions, spy["close"].to_numpy())}
    events = _events(members, set(spy_sessions))
    prices = rd.daily(sorted(events.keys()))

    def build(name):
        hold, hedged, mom = CONFIGS[name]
        return _trades(events, members, prices, spy_sessions, spy_close_by_sess, hold, hedged, mom)

    if phase == "holdout":
        return {"variants": 1, "chosen": chosen, "trades": {chosen: build(chosen)}}

    trades = {n: build(n) for n in CONFIGS}
    best = max(trades, key=lambda k: _rank_t(trades[k]))     # reported for the Skeptic only
    print(f"train: {len(trades)} variants; best-looking (NOT chosen) = {best}; "
          f"pre-registered chosen = {PREREGISTERED}")
    return {"variants": len(trades), "chosen": PREREGISTERED, "trades": trades}
