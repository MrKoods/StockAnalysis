"""Five more strategy families (protocol: research_results/PROTOCOL5_new_families.md).

All results are NET bps per trade (2 bps per side). Every builder returns a dict of per-trade
arrays: day (entry session), bps, sign (+1 long / -1 short), and filter features.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .families import orb, simulate
from .hourly import SLOTS, TICK, Panel, load_panel

COST_BPS = 2.0


@dataclass
class XPanel:
    """Universe as aligned [ticker x session x slot] arrays (NaN where missing)."""
    tickers: list
    days: np.ndarray
    O: np.ndarray
    H: np.ndarray
    L: np.ndarray
    C: np.ndarray
    atr: np.ndarray
    pc: np.ndarray
    trend: np.ndarray
    panels: list


def build(tickers: list[str]) -> XPanel:
    panels = [p for p in (load_panel(t) for t in tickers) if p is not None]
    days = np.array(sorted({d for p in panels for d in p.days}))
    d_ix = {d: i for i, d in enumerate(days)}
    nT, nD = len(panels), len(days)
    shp3, shp2 = (nT, nD, SLOTS), (nT, nD)
    O, H, L, C = (np.full(shp3, np.nan) for _ in range(4))
    atr, pc, trend = (np.full(shp2, np.nan) for _ in range(3))
    for i, p in enumerate(panels):
        j = np.array([d_ix[d] for d in p.days])
        O[i, j], H[i, j], L[i, j], C[i, j] = p.O, p.H, p.L, p.C
        atr[i, j], pc[i, j], trend[i, j] = p.atr, p.pc, p.trend
    return XPanel([p.ticker for p in panels], days, O, H, L, C, atr, pc, trend, panels)


def _pct_rank(sig: np.ndarray) -> np.ndarray:
    """Per-session percentile rank across tickers (sig is [ticker x session])."""
    return pd.DataFrame(sig.T).rank(axis=1, pct=True).to_numpy().T


def _trades(X: XPanel, ti, di, sign, gross_frac):
    ok = ~np.isnan(gross_frac)
    ti, di, sign, g = ti[ok], di[ok], sign[ok], gross_frac[ok]
    price = X.O[ti, di, 0]
    return {"day": X.days[di], "bps": sign * g * 1e4 - 2 * COST_BPS, "sign": sign.astype(float),
            "trend": sign * X.trend[ti, di], "atr_px": X.atr[ti, di] / price, "price": price}


def _select(rank, q, mode):
    """Long the bottom-q names for 'rev' (top-q for 'mom'); short the other tail."""
    lo, hi = rank <= q, rank > 1 - q
    longs, shorts = (lo, hi) if mode == "rev" else (hi, lo)
    ti_l, di_l = np.nonzero(longs)
    ti_s, di_s = np.nonzero(shorts)
    ti = np.concatenate([ti_l, ti_s])
    di = np.concatenate([di_l, di_s])
    sign = np.concatenate([np.ones(len(ti_l)), -np.ones(len(ti_s))])
    return ti, di, sign


# ---------------- XS: cross-sectional morning ----------------
def xs(X: XPanel, p):
    win, rel, q, mode, x = p
    k, e = (0, 1) if win == "h1" else (2, 3)
    sig = X.C[:, :, k] / X.O[:, :, 0] - 1
    if rel == "mkt":
        sig = sig - np.nanmean(sig, axis=0, keepdims=True)
    ti, di, sign = _select(_pct_rank(sig), q, mode)
    g = X.C[ti, di, x] / X.O[ti, di, e] - 1
    return _trades(X, ti, di, sign, g)


# ---------------- PER: same-slot periodicity ----------------
def per(X: XPanel, p):
    k, n, q, mode = p
    r = X.C[:, :, k] / X.O[:, :, k] - 1
    hist = pd.DataFrame(r.T).shift(1).rolling(n, min_periods=int(0.8 * n)).mean().to_numpy().T.copy()
    hist[np.isnan(r)] = np.nan
    ti, di, sign = _select(_pct_rank(hist), q, "rev" if mode == "rev" else "mom")
    return _trades(X, ti, di, sign, r[ti, di])


# ---------------- ON: overnight (close -> next session open) ----------------
def on(X: XPanel, p):
    sig_kind, rel, q, mode = p
    nxt_open = np.concatenate([X.O[:, 1:, 0], np.full((len(X.tickers), 1), np.nan)], axis=1)
    g_all = nxt_open / X.C[:, :, SLOTS - 1] - 1
    if sig_kind == "all_long":
        ti, di = np.nonzero(~np.isnan(g_all))
        return _trades(X, ti, di, np.ones(len(ti)), g_all[ti, di])
    if sig_kind == "intraday":
        sig = X.C[:, :, SLOTS - 1] / X.O[:, :, 0] - 1
    elif sig_kind == "lasthour":
        sig = X.C[:, :, SLOTS - 1] / X.C[:, :, 4] - 1
    else:  # close-to-close
        sig = X.C[:, :, SLOTS - 1] / X.pc - 1
    if rel == "mkt":
        sig = sig - np.nanmean(sig, axis=0, keepdims=True)
    ti, di, sign = _select(_pct_rank(sig), q, mode)
    return _trades(X, ti, di, sign, g_all[ti, di])


# ---------------- MR: idiosyncratic intraday mean reversion ----------------
def mr(X: XPanel, p):
    j, measure, thr, mode, x, target, stop_atr = p
    frac = X.C[:, :, j] / X.O[:, :, 0] - 1
    if measure == "idio":
        frac = frac - np.nanmean(frac, axis=0, keepdims=True)
    move = frac * X.O[:, :, 0] / X.atr                     # in daily ATR
    ti, di = np.nonzero(np.abs(move) >= thr)
    sign = -np.sign(move[ti, di]) if mode == "rev" else np.sign(move[ti, di])
    e = j + 1
    O, H, L, C = X.O[ti, di], X.H[ti, di], X.L[ti, di], X.C[ti, di]
    atr = X.atr[ti, di]
    entry = O[:, e]
    stop = entry - sign * stop_atr * atr if stop_atr else -np.inf * sign
    tp = O[:, 0] if target == "open" else np.inf * sign
    if target == "open":
        ok = (tp - entry) * sign > 0
        ti, di, sign, O, H, L, C, atr, entry = ti[ok], di[ok], sign[ok], O[ok], H[ok], L[ok], C[ok], atr[ok], entry[ok]
        tp = tp[ok]
        stop = stop[ok] if np.ndim(stop) else stop
    n = len(ti)
    r_atr = simulate(O, H, L, C, sign, np.full(n, e), np.full(n, x),
                     np.broadcast_to(stop, n).astype(float), np.broadcast_to(tp, n).astype(float), atr)
    pnl = r_atr * atr + 2 * TICK                           # back to gross price P&L
    return _trades(X, ti, di, sign, pnl / entry)


# ---------------- NR: opening-range breakout after a narrow day ----------------
def nr(X: XPanel, p):
    kind, stop_mode, target, last_entry = p
    out = []
    t_ix = {t: i for i, t in enumerate(X.tickers)}
    d_ix = {d: i for i, d in enumerate(X.days)}
    for P in X.panels:
        rng = P.H.max(axis=1) - P.L.min(axis=1)
        hi, lo = P.H.max(axis=1), P.L.min(axis=1)
        prev = np.concatenate([[np.nan], rng[:-1]])
        if kind == "inside":
            flag = np.concatenate([[False, False], (hi[1:-1] < hi[:-2]) & (lo[1:-1] > lo[:-2])])
        else:
            w = 4 if kind == "nr4" else 7
            mn = pd.Series(rng).rolling(w).min().to_numpy()
            flag = np.concatenate([[False], (rng[:-1] <= mn[:-1])])
        flag &= ~np.isnan(prev)
        rows, sign, e, xs_, stop, tp = orb(P, (stop_mode, target, last_entry))
        keep = flag[rows]
        if not keep.any():
            continue
        rows, sign, e, xs_, stop, tp = rows[keep], sign[keep], e[keep], xs_[keep], stop[keep], tp[keep]
        r_atr = simulate(P.O[rows], P.H[rows], P.L[rows], P.C[rows], sign, e, xs_, stop, tp, P.atr[rows])
        entry = P.O[rows, e]
        pnl = r_atr * P.atr[rows] + 2 * TICK
        out.append((np.full(len(rows), t_ix[P.ticker]), np.array([d_ix[d] for d in P.days[rows]]), sign, pnl / entry))
    if not out:
        return None
    ti, di, sign, g = (np.concatenate([o[k] for o in out]) for k in range(4))
    return _trades(X, ti.astype(int), di.astype(int), sign, g)


BUILDERS = {"XS": xs, "PER": per, "ON": on, "MR": mr, "NR": nr}


@dataclass(frozen=True)
class Cfg2:
    family: str
    p: tuple


def grid():
    for win, rel, q, mode, x in itertools.product(["h1", "am"], ["raw", "mkt"], [0.05, 0.1, 0.2],
                                                  ["rev", "mom"], [4, 6]):
        yield Cfg2("XS", (win, rel, q, mode, x))
    for k, n, q, mode in itertools.product(range(SLOTS), [5, 10, 20, 40], [0.05, 0.1, 0.2], ["mom", "rev"]):
        yield Cfg2("PER", (k, n, q, mode))
    yield Cfg2("ON", ("all_long", "raw", 0, "mom"))
    for s, rel, q, mode in itertools.product(["intraday", "lasthour", "cc"], ["raw", "mkt"],
                                             [0.05, 0.1, 0.2], ["rev", "mom"]):
        yield Cfg2("ON", (s, rel, q, mode))
    for j, meas, thr, mode, x, tg, st in itertools.product([0, 1, 2, 3], ["raw", "idio"], [0.5, 1.0, 1.5],
                                                          ["rev", "mom"], [4, 6], ["none", "open"], [0.0, 1.0]):
        if x < j + 1 or (tg == "open" and mode == "mom"):
            continue
        yield Cfg2("MR", (j, meas, thr, mode, x, tg, st))
    for kind, st, tg, le in itertools.product(["nr4", "nr7", "inside"], ["other", "mid", "atr05"],
                                              ["1.0", "2.0", "none"], [3, 5]):
        yield Cfg2("NR", (kind, st, tg, le))


FILTERS = {
    "none": lambda d: np.ones(len(d["bps"]), bool),
    "long": lambda d: d["sign"] > 0, "short": lambda d: d["sign"] < 0,
    "with_trend": lambda d: d["trend"] > 0, "against_trend": lambda d: d["trend"] < 0,
    "high_vol": lambda d: d["atr_px"] >= 0.025, "low_vol": lambda d: d["atr_px"] < 0.025,
    "price>=50": lambda d: d["price"] >= 50,
}


def run(X: XPanel, cfg: Cfg2):
    return BUILDERS[cfg.family](X, cfg.p)


def to_panel_for_tests(ticker: str, P: Panel) -> XPanel:   # pragma: no cover - test helper
    return XPanel([ticker], P.days, P.O[None], P.H[None], P.L[None], P.C[None], P.atr[None],
                  P.pc[None], P.trend[None], [P])
