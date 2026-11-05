"""early-10q-drift -- TRAIN/HOLDOUT test (data ONLY via research_data as rd).

Hypothesis: a company that files its 10-Q earlier (by calendar date) than it filed the SAME fiscal
quarter's 10-Q one year earlier is sending a voluntary "good news" signal (Begley & Fischer 1998: 10-Q
timeliness predicts the sign of the next earnings surprise). Because a 10-Q filing is lower-profile than
an earnings press release the timestamp is under-noticed, so the early filer DRIFTS UP over the next few
sessions. We go LONG at the OPEN of the first tradable session after SEC acceptance (= first_session) and
exit at the OPEN H=3 sessions later. Returns are SPY-hedged GROSS bps (stock open->open minus SPY
open->open over the same window); the harness subtracts cost_bps.

"Days early" (calendar): for each 10-Q accepted at date Di we find this ticker's prior 10-Q accepted at
Dj with (Di - Dj) in [300, 430] days and closest to 365 (= the same fiscal quarter one year prior, the
~91/182/273-day neighbours excluded), then days_early = (Dj + 1 year) - Di (>0 = filed earlier than a year
ago). 5 trading days ~= 7 calendar days, 10 ~= 14.

Variants (6): universe in {sp1500, sp46 (sp400+sp600, small/mid only)} x early threshold in {7, 14}
calendar days (LONG early filers), plus a late-filer SHORT (days_early <= -7) for {sp1500, sp46}. Hold is
fixed at H=3 sessions (the card's horizon). `chosen` is PRE-REGISTERED = 'sp1500_t7_long' (the broad
universe the academic result is measured on, base 7-day threshold, long). The other five configs are a
robustness map for the Skeptic only and are never carried to the holdout.
"""
from __future__ import annotations

import math

import pandas as pd

import research_data as rd

COST_BPS = 20.0                       # MUST equal plan.json cost_bps (ranks variants in train only)
HOLD = 3                              # sessions, open -> open
GAP_LO, GAP_HI = 300, 430             # calendar-day window isolating the same quarter one year prior
THRESHOLDS = (7, 14)                  # calendar days "early" (~5 / ~10 trading days)
UNIVERSES = ("sp1500", "sp46")
PREREGISTERED = "sp1500_t7_long"
MAX_MOVE = 0.50                       # drop bars with |stock move| > 50% (bad-bar / unadjusted guard)


def _members() -> dict[str, set]:
    sp500 = set(rd.universe("sp500"))
    sp400 = set(rd.universe("sp400"))
    sp600 = set(rd.universe("sp600"))
    return {"sp1500": sp500 | sp400 | sp600, "sp46": sp400 | sp600}


def _events(tickers) -> pd.DataFrame:
    """All original 10-Q filings for the universe, one row per (ticker, acceptance day), with the
    prior-year same-quarter delta. Columns: ticker, first_session (Timestamp), days_early (int)."""
    f = rd.filings(forms=["10-Q"], tickers=sorted(tickers))
    if f.empty:
        return f
    f = f[(f["form"].astype(str) == "10-Q") & f["first_session"].notna() & f["accepted"].notna()].copy()
    f["acc_day"] = pd.to_datetime(f["accepted"]).dt.normalize()
    f["first_session"] = pd.to_datetime(f["first_session"]).dt.normalize()
    f = f.drop_duplicates(["ticker", "acc_day"]).sort_values(["ticker", "acc_day"])
    rows = []
    for tkr, g in f.groupby("ticker"):
        acc = list(g["acc_day"])
        fs = list(g["first_session"])
        for i in range(len(acc)):
            di = acc[i]
            best_j, best_err = None, None
            for j in range(i - 1, -1, -1):           # scan backwards; gap grows as j falls
                gap = (di - acc[j]).days
                if gap > GAP_HI:
                    break
                if gap < GAP_LO:
                    continue
                err = abs(gap - 365)
                if best_err is None or err < best_err:
                    best_err, best_j = err, j
            if best_j is None:
                continue
            days_early = ((acc[best_j] + pd.DateOffset(years=1)) - di).days
            rows.append({"ticker": tkr, "first_session": fs[i], "days_early": int(days_early)})
    return pd.DataFrame(rows)


def _select(ev: pd.DataFrame, members: set, thr: int, side: str) -> pd.DataFrame:
    m = ev["ticker"].isin(members)
    m &= (ev["days_early"] >= thr) if side == "long" else (ev["days_early"] <= -thr)
    return ev[m]


def _trades(sel: pd.DataFrame, prices: dict, spy: pd.DataFrame, side: str) -> list[dict]:
    spy_idx = pd.DatetimeIndex(spy.index).normalize()
    spy_open = spy["open"].to_numpy()
    out = []
    for tkr, fs in sel[["ticker", "first_session"]].itertuples(index=False):
        df = prices.get(tkr)
        if df is None:
            continue
        idx = pd.DatetimeIndex(df.index).normalize()
        pos = int(idx.searchsorted(fs, side="left"))
        if pos >= len(idx) or idx[pos] != fs:          # first_session must be a real bar for this ticker
            continue
        exit_pos = pos + HOLD
        if exit_pos >= len(idx):
            continue
        entry_day, exit_day = idx[pos], idx[exit_pos]
        se = int(spy_idx.searchsorted(entry_day, side="left"))
        sx = int(spy_idx.searchsorted(exit_day, side="left"))
        if (se >= len(spy_idx) or sx >= len(spy_idx)
                or spy_idx[se] != entry_day or spy_idx[sx] != exit_day):
            continue
        o, c = float(df["open"].iloc[pos]), float(df["open"].iloc[exit_pos])     # open->open hold
        so, sc = float(spy_open[se]), float(spy_open[sx])
        if not (o > 0 and c > 0 and so > 0 and sc > 0):
            continue
        if abs(c / o - 1) > MAX_MOVE:                  # bad-bar guard
            continue
        hedged = (c / o - 1) * 1e4 - (sc / so - 1) * 1e4   # SPY-hedged long, open->open
        gross = hedged if side == "long" else -hedged      # short = mirror of the hedged long
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


def _build(name: str, ev: pd.DataFrame, members: dict, prices: dict, spy: pd.DataFrame) -> list[dict]:
    univ, ttag, dtag = name.split("_")             # e.g. "sp1500_t7_long"
    thr = int(ttag[1:])
    side = "long" if dtag == "long" else "short"
    sel = _select(ev, members[univ], thr, side)
    return _trades(sel, prices, spy, side)


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
                "trades": {chosen: _build(chosen, ev, members, prices, spy)}}

    names = [f"{u}_t{thr}_long" for u in UNIVERSES for thr in THRESHOLDS]
    names += [f"{u}_t7_short" for u in UNIVERSES]
    trades = {n: _build(n, ev, members, prices, spy) for n in names}
    best = max(trades, key=lambda k: _rank_t(trades[k]))     # reported for the Skeptic only
    print(f"train: {len(trades)} variants; best-looking (NOT chosen) = {best}; "
          f"pre-registered chosen = {PREREGISTERED}")
    return {"variants": len(trades), "chosen": PREREGISTERED, "trades": trades}
