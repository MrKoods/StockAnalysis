"""Round 2: volume ("stocks in play") families (protocol: research_results/PROTOCOL7_volume_families.md).

Same output contract as families2: per-trade dict with day, bps (net, 2 bps/side), sign, features.
RVOL = volume / mean of the same measure over the prior 14 sessions (known before it is used).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .families import simulate
from .families2 import XPanel, _pct_rank, _select, _trades
from .hourly import SLOTS, TICK


def _rvol(vol: np.ndarray, n: int = 14) -> np.ndarray:
    """vol is [ticker x session]; ratio to the trailing mean of the prior n sessions."""
    hist = pd.DataFrame(vol.T).shift(1).rolling(n, min_periods=10).mean().to_numpy().T
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(hist > 0, vol / hist, np.nan)


def _pick(rv: np.ndarray, sel: str) -> np.ndarray:
    """Boolean [ticker x session]: which names are 'in play' under rule `sel`."""
    if sel.startswith("top"):
        k = int(sel[3:])
        rk = pd.DataFrame(rv.T).rank(axis=1, ascending=False, method="first").to_numpy().T
        return rk <= k
    if sel == "low":
        return rv < 1.0
    return rv >= float(sel[2:])          # "ge2", "ge3"


def _sim_rows(X: XPanel, ti, di, sign, e: int, x: int, stop, tp):
    O, H, L, C = X.O[ti, di], X.H[ti, di], X.L[ti, di], X.C[ti, di]
    atr = X.atr[ti, di]
    n = len(ti)
    r_atr = simulate(O, H, L, C, sign, np.full(n, e), np.full(n, x), stop, tp, atr)
    entry = O[:, e]
    return _trades(X, ti, di, sign, (r_atr * atr + 2 * TICK) / entry)


# ---------------- SIP: first-hour stocks in play ----------------
def sip(X: XPanel, p):
    sel, mode, stop_mode, target, x = p
    inplay = _pick(_rvol(X.V[:, :, 0]), sel)
    move = X.C[:, :, 0] - X.O[:, :, 0]
    ti, di = np.nonzero(inplay & (move != 0) & ~np.isnan(move))
    sign = np.sign(move[ti, di]) * (1 if mode == "mom" else -1)
    entry = X.O[ti, di, 1]
    if stop_mode == "fh":
        stop = np.where(sign > 0, X.L[ti, di, 0], X.H[ti, di, 0])
    elif stop_mode == "atr05":
        stop = entry - sign * 0.5 * X.atr[ti, di]
    else:
        stop = -np.inf * sign
    risk = (entry - stop) * sign
    ok = (risk > 0) & ~np.isnan(entry)
    ti, di, sign, entry, stop, risk = ti[ok], di[ok], sign[ok], entry[ok], stop[ok], risk[ok]
    if target == "none" or stop_mode == "none":
        tp = np.inf * sign
    else:
        tp = entry + sign * float(target) * risk
    return _sim_rows(X, ti, di, sign, 1, x, stop.astype(float), tp.astype(float))


# ---------------- GAPV: gaps split by volume ----------------
def gapv(X: XPanel, p):
    thr, vsel, measure, mode, target, x = p
    if measure == "prevday":
        allnan = np.all(np.isnan(X.V), axis=2)
        dayvol = np.where(allnan, np.nan, np.nansum(X.V, axis=2))
        prev = np.concatenate([np.full((len(X.tickers), 1), np.nan), dayvol[:, :-1]], axis=1)
        rv, e = _rvol(prev), 0
    else:
        rv, e = _rvol(X.V[:, :, 0]), 1
    g = (X.O[:, :, 0] - X.pc) / X.atr
    ti, di = np.nonzero(_pick(rv, vsel) & (np.abs(g) >= thr))
    sign = np.sign(g[ti, di]) * (1 if mode == "go" else -1)
    entry = X.O[ti, di, e]
    if target == "pc":
        tp = X.pc[ti, di]
        ok = (tp - entry) * sign > 0
        ti, di, sign, tp = ti[ok], di[ok], sign[ok], tp[ok]
    else:
        tp = np.inf * sign
    stop = -np.inf * sign
    return _sim_rows(X, ti, di, sign, e, x, np.asarray(stop, float), np.asarray(tp, float))


# ---------------- ONV: overnight, conditioned on last-hour volume ----------------
def onv(X: XPanel, p):
    vsel, q, mode = p
    nxt_open = np.concatenate([X.O[:, 1:, 0], np.full((len(X.tickers), 1), np.nan)], axis=1)
    g_all = nxt_open / X.C[:, :, SLOTS - 1] - 1
    sig = X.C[:, :, SLOTS - 1] / X.C[:, :, 4] - 1
    if vsel != "any":
        lastvol = X.V[:, :, 5] + X.V[:, :, 6]
        sig = np.where(_pick(_rvol(lastvol), vsel), sig, np.nan)
    ti, di, sign = _select(_pct_rank(sig), q, mode)
    return _trades(X, ti, di, sign, g_all[ti, di])


BUILDERS = {"SIP": sip, "GAPV": gapv, "ONV": onv}


@dataclass(frozen=True)
class Cfg3:
    family: str
    p: tuple


def grid():
    for sel, mode, st, tg, x in itertools.product(["top5", "top10", "top20", "ge2", "ge3"], ["mom", "rev"],
                                                  ["none", "fh", "atr05"], ["none", "1.0", "2.0"], [4, 6]):
        if st == "none" and tg != "none":
            continue
        yield Cfg3("SIP", (sel, mode, st, tg, x))
    for thr, vs, meas, mode, tg, x in itertools.product([0.25, 0.5, 1.0], ["ge2", "low", "top10"],
                                                        ["prevday", "firsthour"], ["go", "fade"],
                                                        ["pc", "none"], [2, 6]):
        if tg == "pc" and mode == "go":
            continue
        yield Cfg3("GAPV", (thr, vs, meas, mode, tg, x))
    for vs, q, mode in itertools.product(["ge2", "low", "any"], [0.05, 0.1, 0.2], ["rev", "mom"]):
        yield Cfg3("ONV", (vs, q, mode))


def run(X: XPanel, cfg: Cfg3):
    return BUILDERS[cfg.family](X, cfg.p)
