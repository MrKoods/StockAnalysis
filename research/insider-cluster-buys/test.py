"""insider-cluster-buys -- TRAIN/HOLDOUT test (data ONLY via research_data as rd).

Signal: >= N distinct corporate insiders (by RPTOWNERCIK), each filing an open-market Form-4
purchase (TRANS_CODE 'P') of >= $25k on the same S&P 500/400 ticker within a rolling 5-CALENDAR-DAY
window measured by FILING_DATE (filings must be public to be tradable -> no look-ahead), with the
qualifying cluster total >= MIN_TOTAL. Long at the next session's OPEN after the triggering filing
date; exit at the CLOSE H trading sessions later. Returns SPY-hedged GROSS bps (stock open->close
minus SPY open->close over the same window); the harness subtracts cost_bps.

`chosen` is PRE-REGISTERED = 'n2_h5_m75k' (see PLAN.md); the other 11 configs are reported only as a
robustness map and are never carried to the holdout.
"""
from __future__ import annotations

import math

import pandas as pd

import research_data as rd

COST_BPS = 20.0             # MUST equal plan.json cost_bps (used only to rank variants for the report)
WINDOW_DAYS = 5            # cluster window, calendar days, measured by filing date
MIN_PER_INSIDER = 25_000.0  # each insider's purchase total within the window
N_INS_GRID = (2, 3)
HOLD_GRID = (3, 5, 10)
MIN_TOTAL_GRID = (75_000.0, 150_000.0)
PREREGISTERED = "n2_h5_m75k"


def _name(n: int, h: int, mt: float) -> str:
    return f"n{n}_h{h}_m{int(mt // 1000)}k"


def _parse(name: str) -> tuple[int, int, float]:
    a, b, c = name.split("_")
    return int(a[1:]), int(b[1:]), float(c[1:-1]) * 1000.0


def _universe() -> set[str]:
    return set(rd.universe("sp500")) | set(rd.universe("sp400"))


def _candidates(start: str) -> list[tuple[str, pd.Timestamp, int, float]]:
    """Every (ticker, filing_date, n_qualifying_insiders, qualifying_total) with n >= 2. No dedupe
    and no N_INS/MIN_TOTAL threshold here -- each variant filters + dedupes itself in _trades."""
    uni = _universe()
    lo = (pd.Timestamp(start) - pd.Timedelta(days=15)).strftime("%Y-%m-%d")
    data = rd.insider(lo)
    if data.empty:
        return []
    data = data[data["DOCUMENT_TYPE"].isin(["4", "4/A"])].copy()
    data["sym"] = data["ISSUERTRADINGSYMBOL"].astype(str).str.upper().str.strip()
    data = data[data["sym"].isin(uni)]
    data = data[data["TRANS_CODE"] == "P"]
    if "TRANS_ACQUIRED_DISP_CD" in data.columns:
        data = data[data["TRANS_ACQUIRED_DISP_CD"].astype(str).str.upper().str.startswith("A")]
    data["fdate"] = pd.to_datetime(data["FILING_DATE"], format="%d-%b-%Y", errors="coerce")
    data["val"] = (pd.to_numeric(data["TRANS_SHARES"], errors="coerce")
                   * pd.to_numeric(data["TRANS_PRICEPERSHARE"], errors="coerce"))
    data = data.dropna(subset=["fdate", "val", "RPTOWNERCIK"])
    data = data[data["val"] > 0]
    data = data.drop_duplicates(["ACCESSION_NUMBER", "TRANS_DATE", "TRANS_SHARES", "TRANS_CODE"])
    # one row per (ticker, insider, filing date)
    per = data.groupby(["sym", "RPTOWNERCIK", "fdate"], as_index=False)["val"].sum()
    win = pd.Timedelta(days=WINDOW_DAYS)
    cands: list[tuple[str, pd.Timestamp, int, float]] = []
    for sym, s in per.groupby("sym", sort=False):
        s = s.sort_values("fdate")
        arr = s[["fdate", "RPTOWNERCIK", "val"]].to_numpy(object)
        for fd in sorted(set(s["fdate"])):
            tot: dict[object, float] = {}
            for f, owner, v in arr:
                if fd - win < f <= fd:
                    tot[owner] = tot.get(owner, 0.0) + float(v)
            qual = {o: t for o, t in tot.items() if t >= MIN_PER_INSIDER}
            if len(qual) >= 2:
                cands.append((sym, fd, len(qual), float(sum(qual.values()))))
    return cands


def _trades(cands, prices, spy, n_ins_min, hold, min_total):
    win = pd.Timedelta(days=WINDOW_DAYS)
    last_fire: dict[str, pd.Timestamp] = {}
    out = []
    for sym, fd, n_ins, total in cands:
        if n_ins < n_ins_min or total < min_total:
            continue
        lf = last_fire.get(sym)
        if lf is not None and fd - lf < win:          # one trade per 5-day episode per ticker
            continue
        last_fire[sym] = fd                           # episode consumed even if price data is missing
        df = prices.get(sym)
        if df is None:
            continue
        idx = df.index
        pos = int(idx.searchsorted(fd, side="right"))  # first session strictly after the filing date
        exit_pos = pos + hold - 1
        if pos >= len(idx) or exit_pos >= len(idx):
            continue
        entry_day, exit_day = idx[pos], idx[exit_pos]
        if entry_day not in spy.index or exit_day not in spy.index:
            continue
        o, c = float(df.at[entry_day, "open"]), float(df.at[exit_day, "close"])
        so, sc = float(spy.at[entry_day, "open"]), float(spy.at[exit_day, "close"])
        if not (o > 0 and c > 0 and so > 0 and sc > 0):
            continue
        gross = (c / o - 1) * 1e4 - (sc / so - 1) * 1e4   # SPY-hedged, long
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


def run(start: str, end: str, phase: str, chosen: str | None) -> dict:
    cands = _candidates(start)
    syms = sorted({c[0] for c in cands})
    prices = rd.daily(syms + ["SPY"])
    spy = prices.get("SPY")
    if spy is None:
        raise RuntimeError("SPY daily bars missing from the archive -- required for the hedge")

    if phase == "holdout":
        n, h, mt = _parse(chosen)
        return {"variants": 1, "chosen": chosen,
                "trades": {chosen: _trades(cands, prices, spy, n, h, mt)}}

    trades: dict[str, list] = {}
    for n in N_INS_GRID:
        for h in HOLD_GRID:
            for mt in MIN_TOTAL_GRID:
                trades[_name(n, h, mt)] = _trades(cands, prices, spy, n, h, mt)
    best = max(trades, key=lambda k: _rank_t(trades[k]))   # reported for the Skeptic only
    print(f"train: {len(trades)} variants; best-looking (NOT chosen) = {best}; "
          f"pre-registered chosen = {PREREGISTERED}")
    return {"variants": len(trades), "chosen": PREREGISTERED, "trades": trades}
