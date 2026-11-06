"""nt-filing-short -- TRAIN/HOLDOUT test (data ONLY via research_data as rd).

Hypothesis: a Notification of Late Filing (Form NT 10-K / NT 10-Q) is a public admission that management
cannot certify the financials on time; NT filers then report worse earnings and draw downward revisions
(Ettredge-Lee-Scholz 2000). The market underreacts at the NT date, leaving a short-side drift. We SHORT at
the CLOSE of the session AFTER the first tradable session (= one session after the first reaction -- the
earliest retail-affordable fill; the open round trip costs more than the whole edge), and cover at the
CLOSE H sessions later. Returns are SPY-hedged GROSS bps, SHORT side (spy_ret - stock_ret, close->close);
the harness subtracts cost_bps. This matches paper_runner's short hedged defn (real_bps - sgn*spy_bps).

Variants (5): universe in {sp500, sp54 (sp500+sp400)} x hold H in {2, 3}, plus `sp54_h3_ex202` = sp54_h3
with NT filings that are concurrent (+/-2 cal days) with an 8-K item 2.02 (earnings release) EXCLUDED --
a robustness check that the signal is the NT, not a priced earnings event. `chosen` is PRE-REGISTERED =
'sp54_h3' (broadest tradable universe, the evidence's ~3-day drift horizon -- see PLAN.md). The other four
configs are a robustness map for the Skeptic only and are never carried to the holdout.
"""
from __future__ import annotations

import math

import pandas as pd

import research_data as rd

COST_BPS = 30.0                       # MUST equal plan.json cost_bps (ranks variants in train only)
HOLD_GRID = (2, 3)
UNIV_GRID = ("sp500", "sp54")
PREREGISTERED = "sp54_h3"
NT_FORMS = ["NT 10-K", "NT 10-Q"]
MAX_MOVE = 0.50                       # drop bars with |stock move| > 50% (bad-bar / unadjusted guard)
EX202_DAYS = 2                        # exclude an NT within +/- this many calendar days of an 8-K 2.02


def _members() -> dict[str, set]:
    sp500 = set(rd.universe("sp500"))
    sp400 = set(rd.universe("sp400"))
    return {"sp500": sp500, "sp54": sp500 | sp400}


def _nt_events(tickers) -> pd.DataFrame:
    """NT 10-K / NT 10-Q filings with a known first tradable session.
    Columns: ticker, first_session (Timestamp), accepted (normalized Timestamp)."""
    f = rd.filings(forms=NT_FORMS, tickers=sorted(tickers))
    if f.empty:
        return f
    f = f[f["first_session"].notna()].copy()
    f["first_session"] = pd.to_datetime(f["first_session"]).dt.normalize()
    f["accepted"] = pd.to_datetime(f["accepted"]).dt.normalize()
    f = f.drop_duplicates(["ticker", "first_session"])
    return f[["ticker", "first_session", "accepted"]]


def _ex202_map(tickers) -> dict[str, "pd.DatetimeIndex"]:
    """ticker -> sorted accepted dates of its 8-K item 2.02 (earnings release) filings."""
    f = rd.filings(forms=["8-K"], items=["2.02"], tickers=sorted(tickers))
    out: dict[str, pd.DatetimeIndex] = {}
    if f.empty:
        return out
    acc = pd.to_datetime(f["accepted"]).dt.normalize()
    for t, g in acc.groupby(f["ticker"].astype(str)):
        out[t] = pd.DatetimeIndex(sorted(g.unique()))
    return out


def _has_202_near(ex_idx: "pd.DatetimeIndex | None", when: pd.Timestamp) -> bool:
    if ex_idx is None or len(ex_idx) == 0:
        return False
    i = int(ex_idx.searchsorted(when, side="left"))
    for j in (i - 1, i):                                  # nearest 2.02 on either side
        if 0 <= j < len(ex_idx) and abs((ex_idx[j] - when).days) <= EX202_DAYS:
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
        if ex_map is not None and _has_202_near(ex_map.get(str(tkr)), acc):
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
    use_ex = name.endswith("_ex202")
    return _trades(ev, members[univ], prices, spy, h, ex_map if use_ex else None)


def run(start: str, end: str, phase: str, chosen: str | None) -> dict:
    members = _members()
    all_syms = members["sp54"]
    ev = _nt_events(all_syms)
    syms = sorted(ev["ticker"].astype(str).unique()) if len(ev) else []
    prices = rd.daily(syms + ["SPY"])
    spy = prices.get("SPY")
    if spy is None:
        raise RuntimeError("SPY daily bars missing from the archive -- required for the hedge")
    ex_map = _ex202_map(syms) if syms else {}

    if phase == "holdout":
        return {"variants": 1, "chosen": chosen,
                "trades": {chosen: _config(chosen, ev, members, prices, spy, ex_map)}}

    names = [f"{u}_h{h}" for u in UNIV_GRID for h in HOLD_GRID] + ["sp54_h3_ex202"]
    trades = {n: _config(n, ev, members, prices, spy, ex_map) for n in names}
    best = max(trades, key=lambda k: _rank_t(trades[k]))     # reported for the Skeptic only
    print(f"train: {len(trades)} variants; best-looking (NOT chosen) = {best}; "
          f"pre-registered chosen = {PREREGISTERED}")
    return {"variants": len(trades), "chosen": PREREGISTERED, "trades": trades}
