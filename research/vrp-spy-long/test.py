"""vrp-spy-long: variance-risk-premium timing on SPY, long/short to isolate the premium from beta.

Signal (session t): VRP_t = VIX_t - RV_t, RV = annualized 20-session realized vol of SPY.
Standardize VRP over a trailing window (all data <= t, no look-ahead): z_t = (VRP_t - mean)/std.
Side = long if z_t > k, short if z_t < -k, else flat. Enter at the NEXT session's close (so VIX_t's
16:15 ET close is already known before entry), hold 20 sessions, exit at close. Gross = raw signed
SPY return in bps; the harness subtracts the cost floor and clusters by month.

Under the null (VRP has no predictive power) the long and short legs sample the same return
distribution equally often, so the equity premium cancels and E[gross] = 0: a positive mean is the
VRP edge, not market beta.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import research_data as rd

HOLD = 20
RV_WIN = 20
CONFIGS = {
    "k0_z126": (0.0, 126), "k05_z126": (0.5, 126), "k10_z126": (1.0, 126),
    "k0_z252": (0.0, 252), "k05_z252": (0.5, 252), "k10_z252": (1.0, 252),
}
CHOSEN = "k0_z126"   # pre-registered primary (median split, 6-month standardization; fits paper depth)


def _features():
    spy = rd.daily(["SPY"])["SPY"].copy()
    spy.index = pd.to_datetime(spy.index).normalize()
    close = spy["close"].astype(float).sort_index()
    vix = rd.cboe(["VIX"])["VIX"].copy()
    vix.index = pd.to_datetime(vix.index).normalize()
    vix = vix.reindex(close.index).ffill()              # VIX on every NYSE session (past-only fill)
    ret = np.log(close / close.shift(1))
    rv = ret.rolling(RV_WIN).std() * np.sqrt(252) * 100.0
    vrp = vix - rv
    return close, vrp


def _trades(close, vrp, k, zwin):
    z = (vrp - vrp.rolling(zwin).mean()) / vrp.rolling(zwin).std()
    sessions = close.index
    cvals = close.to_numpy()
    zvals = z.to_numpy()
    n = len(sessions)
    out = []
    for i in range(n):
        zi = zvals[i]
        if not np.isfinite(zi):
            continue
        side = 1 if zi > k else (-1 if zi < -k else 0)
        if side == 0:
            continue
        e = i + 1              # enter at the next session's close (VIX_t close already known)
        x = i + 1 + HOLD       # exit 20 sessions after entry
        if x >= n:
            continue
        gross = side * (cvals[x] / cvals[e] - 1.0) * 1e4
        out.append({"date": sessions[x], "gross_bps": float(gross)})
    return out


def run(start, end, phase, chosen):
    close, vrp = _features()
    names = [chosen] if phase == "holdout" else list(CONFIGS)
    trades = {name: _trades(close, vrp, *CONFIGS[name]) for name in names}
    return {"variants": len(CONFIGS), "chosen": CHOSEN, "trades": trades}
