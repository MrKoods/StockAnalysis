"""Round 5: minute-level families on Dukascopy data (protocol: research_results/PROTOCOL10_minute_families.md).

Each instrument is held as [session x 390] minute matrices. A trade enters at the OPEN of minute
e and exits at a stop/target (checked minute by minute, stop first) or at the CLOSE of minute x.
Shorts are mirrored into long space, as everywhere else in this project.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .. import dukascopy

N = 390
ETFS = {"SPY", "QQQ", "DIA", "IWM", "GLD", "TLT", "XLF", "XLE"}


def m_of(hh: int, mm: int) -> int:
    """Minute index of a clock time (09:30 -> 0, 15:59 -> 389)."""
    return (hh * 60 + mm) - (9 * 60 + 30)


@dataclass
class Inst:
    sym: str
    days: np.ndarray
    O: np.ndarray
    H: np.ndarray
    L: np.ndarray
    C: np.ndarray
    atr: np.ndarray      # daily ATR(14) known before the session (prior sessions only)
    pc: np.ndarray       # previous session close
    trend20: np.ndarray  # sign(prev close - SMA20 of prior closes)
    cost_bps: float


def load_inst(sym: str) -> Inst | None:
    df = dukascopy.load(sym)
    if df.empty:
        return None
    df = df.assign(day=df.index.date, m=(df.index.hour * 60 + df.index.minute) - 570)
    piv = {k: df.pivot_table(index="day", columns="m", values=k, aggfunc="first").reindex(columns=range(N))
           for k in ("open", "high", "low", "close")}
    full = piv["close"].notna().sum(axis=1) >= 380
    piv = {k: v[full].ffill(axis=1).bfill(axis=1) for k, v in piv.items()}
    hi, lo, cl = piv["high"].max(axis=1), piv["low"].min(axis=1), piv["close"][N - 1]
    pc = cl.shift()
    tr = pd.concat([hi - lo, (hi - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().shift()
    sma = cl.rolling(20).mean().shift()
    ok = atr.notna() & sma.notna()
    f = lambda s: s[ok].to_numpy(float)  # noqa: E731
    return Inst(sym, np.array(list(piv["close"].index[ok])), *(piv[k][ok].to_numpy(float) for k in
                ("open", "high", "low", "close")), f(atr), f(pc), np.sign(f(pc - sma)),
                1.0 if sym in ETFS else 2.0)


def simulate(I: Inst, rows, sign, e, x, stop, tp):
    """Vectorized over trades. Returns gross return (fraction) per trade, NaN if invalid."""
    s = sign[:, None]
    O, H, L, C = I.O[rows] * s, I.H[rows], I.L[rows], I.C[rows] * s
    Hm = np.where(s > 0, H, -L)
    Lm = np.where(s > 0, L, -H)
    st, tg = stop * sign, tp * sign
    n = len(rows)
    entry = O[np.arange(n), e]
    pnl = np.full(n, np.nan)
    done = np.zeros(n, bool)
    for k in range(int(e.min()) if n else 0, N):
        act = ~done & (e <= k) & (k <= x)
        if not act.any():
            if (k > x).all():
                break
            continue
        hit_s = act & (Lm[:, k] <= st)
        pnl = np.where(hit_s, np.minimum(O[:, k], st) - entry, pnl)
        done |= hit_s
        hit_t = act & ~hit_s & (Hm[:, k] >= tg)
        pnl = np.where(hit_t, tg - entry, pnl)
        done |= hit_t
        fin = act & ~done & (k == x)
        pnl = np.where(fin, C[:, k] - entry, pnl)
        done |= fin
    return pnl / np.abs(entry)


def _out(I: Inst, rows, sign, ret, e, x):
    ok = ~np.isnan(ret)
    return {"day": I.days[rows][ok], "sym": np.full(ok.sum(), I.sym), "sign": sign[ok],
            "ret": ret[ok], "minutes": (x - e + 1)[ok].astype(float), "cost": np.full(ok.sum(), I.cost_bps)}


# ---------------- IMOM: intraday momentum ----------------
def imom(I: Inst, p):
    early, late, mode, thr, confirm = p
    if early == "pc-1000":
        sig = I.C[:, m_of(9, 59)] / I.pc - 1
    else:  # "o-1000"
        sig = I.C[:, m_of(9, 59)] / I.O[:, 0] - 1
    sig_atr = sig * I.pc / I.atr
    e = m_of(15, 30) if late == "1530" else m_of(15, 0)
    rows = np.flatnonzero(np.abs(sig_atr) >= thr)
    sign = np.sign(sig[rows]) * (1 if mode == "mom" else -1)
    if confirm:
        mid = I.C[rows, e - 1] / I.O[rows, m_of(12, 0)] - 1
        keep = np.sign(mid) == sign
        rows, sign = rows[keep], sign[keep]
    keep = sign != 0
    rows, sign = rows[keep], sign[keep]
    n = len(rows)
    ee, xx = np.full(n, e), np.full(n, N - 1)
    ret = simulate(I, rows, sign, ee, xx, np.full(n, -np.inf) * sign, np.full(n, np.inf) * sign)
    return _out(I, rows, sign, ret, ee, xx)


# ---------------- ORB: opening-range breakout ----------------
def orb(I: Inst, p):
    rng_min, entry_mode, stop_mode, target = p
    hi = I.H[:, :rng_min].max(axis=1)
    lo = I.L[:, :rng_min].min(axis=1)
    if entry_mode == "candle":            # direction of the opening range's net move, enter at its end
        d = np.sign(I.C[:, rng_min - 1] - I.O[:, 0])
        rows = np.flatnonzero(d != 0)
        sign, e = d[rows], np.full(len(rows), rng_min)
    else:                                  # first 1-minute close outside the range, enter next minute
        up = I.C[:, rng_min:] > hi[:, None]
        dn = I.C[:, rng_min:] < lo[:, None]
        first_up = np.where(up.any(axis=1), up.argmax(axis=1), N)
        first_dn = np.where(dn.any(axis=1), dn.argmax(axis=1), N)
        k = np.minimum(first_up, first_dn) + rng_min + 1
        rows = np.flatnonzero(k < m_of(15, 30))
        sign = np.where(first_up[rows] < first_dn[rows], 1.0, -1.0)
        e = k[rows]
    entry = I.O[rows, e]
    if stop_mode == "other":
        stop = np.where(sign > 0, lo[rows], hi[rows])
    elif stop_mode == "mid":
        stop = (hi[rows] + lo[rows]) / 2
    else:
        stop = entry - sign * float(stop_mode) * I.atr[rows]
    risk = (entry - stop) * sign
    keep = risk > 0
    rows, sign, e, entry, stop, risk = rows[keep], sign[keep], e[keep], entry[keep], stop[keep], risk[keep]
    tp = np.inf * sign if target == "none" else entry + sign * float(target) * risk
    x = np.full(len(rows), N - 1)
    ret = simulate(I, rows, sign, e, x, stop, np.broadcast_to(tp, len(rows)).astype(float))
    return _out(I, rows, sign, ret, e, x)


# ---------------- NB: noise-boundary momentum ----------------
def nb(I: Inst, p):
    k, step = p
    move = np.abs(I.C / I.O[:, :1] - 1)                     # |move from the open| by minute
    avg = pd.DataFrame(move).rolling(14, min_periods=10).mean().shift().to_numpy()
    upper = I.O[:, :1] * (1 + k * avg)
    lower = I.O[:, :1] * (1 - k * avg)
    checks = list(range(step - 1, N - 1, step))     # signal on the close of minute c ...
    days, signs, rets, mins = [], [], [], []
    for r in np.flatnonzero(~np.isnan(avg).any(axis=1)):
        pos, entry, t_in = 0, 0.0, 0
        for c in checks:
            px = I.C[r, c]
            want = 1 if px > upper[r, c] else (-1 if px < lower[r, c] else 0)
            fill = I.O[r, c + 1]                     # ... filled at the next minute's open
            if pos != 0 and want != pos:             # back inside (or flipped): close the position
                rets.append(pos * (fill / entry - 1))
                days.append(r)
                signs.append(pos)
                mins.append(c + 1 - t_in)
                pos = 0
            if pos == 0 and want != 0:
                pos, entry, t_in = want, fill, c + 1
        if pos != 0:
            rets.append(pos * (I.C[r, N - 1] / entry - 1))
            days.append(r)
            signs.append(pos)
            mins.append(N - t_in)
    rows = np.array(days, int)
    return {"day": I.days[rows], "sym": np.full(len(rows), I.sym), "sign": np.array(signs, float),
            "ret": np.array(rets), "minutes": np.array(mins, float),   # ret is already directional
            "cost": np.full(len(rows), I.cost_bps)}


# ---------------- GAPM: G2 gap fade at minute resolution ----------------
def gapm(I: Inst, p):
    thr, entry_t, stop_atr, exit_t, trend = p
    g = (I.O[:, 0] - I.pc) / I.atr
    rows = np.flatnonzero(np.abs(g) >= thr)
    sign = -np.sign(g[rows])
    if trend:
        keep = sign * I.trend20[rows] > 0
        rows, sign = rows[keep], sign[keep]
    e = np.full(len(rows), {"0930": 0, "0935": 5, "1000": 30}[entry_t])
    x = np.full(len(rows), {"1100": m_of(10, 59), "1330": m_of(13, 29), "1600": N - 1}[exit_t])
    entry = I.O[rows, e]
    tp = I.pc[rows]
    keep = (tp - entry) * sign > 0
    rows, sign, e, x, entry, tp = rows[keep], sign[keep], e[keep], x[keep], entry[keep], tp[keep]
    stop = entry - sign * stop_atr * I.atr[rows] if stop_atr else np.full(len(rows), -np.inf) * sign
    ret = simulate(I, rows, sign, e, x, stop, tp)
    return _out(I, rows, sign, ret, e, x)


BUILDERS = {"IMOM": imom, "ORB": orb, "NB": nb, "GAPM": gapm}


@dataclass(frozen=True)
class MCfg:
    family: str
    p: tuple


def grid():
    for early, late, mode, thr, conf in itertools.product(["pc-1000", "o-1000"], ["1530", "1500"],
                                                          ["mom", "rev"], [0.0, 0.1, 0.25, 0.5], [False, True]):
        yield MCfg("IMOM", (early, late, mode, thr, conf))
    for rm, em, st, tg in itertools.product([5, 15, 30], ["break", "candle"], ["other", "mid", "0.1", "0.25"],
                                            ["1", "2", "5", "none"]):
        yield MCfg("ORB", (rm, em, st, tg))
    for k, step in itertools.product([0.5, 1.0, 1.5], [15, 30, 60]):
        yield MCfg("NB", (k, step))
    for thr, et, st, xt, tr in itertools.product([0.25, 0.5, 1.0], ["0930", "0935", "1000"], [0.0, 0.5, 1.0],
                                                 ["1100", "1330", "1600"], [False, True]):
        yield MCfg("GAPM", (thr, et, st, xt, tr))


def run(I: Inst, cfg: MCfg):
    return BUILDERS[cfg.family](I, cfg.p)


def score(trades: dict, lo, hi, drift: dict[str, float]):
    """Net excess bps per trade for trades with lo <= day < hi. drift: per-symbol mean 1-minute
    return in the evaluated period (removes the instrument's own drift over the holding time)."""
    m = np.array([lo <= d < hi for d in trades["day"]])
    if not m.any():
        return np.array([]), np.array([]), np.array([]), np.array([])
    mu = np.array([drift.get(s, 0.0) for s in trades["sym"][m]])
    exc = trades["ret"][m] - trades["sign"][m] * mu * trades["minutes"][m]
    bps = exc * 1e4 - 2 * trades["cost"][m]
    return trades["day"][m], bps, trades["sign"][m], trades["sym"][m]


def drift_per_minute(I: Inst, lo, hi) -> float:
    m = np.array([lo <= d < hi for d in I.days])
    r = I.C[m, -1] / I.O[m, 0] - 1
    return float(np.nanmean(r) / N) if m.any() else 0.0
