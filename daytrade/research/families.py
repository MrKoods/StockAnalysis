"""Other day-trading strategy families on hourly bars (2y x ~510 tickers).

Slots (NY): 0=09:30 1=10:30 2=11:30 3=12:30 4=13:30 5=14:30 6=15:30-16:00.
Every config yields events {row, sign, e (entry slot, enter at its open), x (exit at close
of slot x unless stopped/targeted earlier), stop, tp (raw prices; +-inf = none)}.
One shared simulator: shorts are mirrored into long space; stop checked before target
inside a bar; results in units of daily ATR, net of 1 cent/share per side.

Families
  MOM  morning move -> trade with it (mom) or against it (rev) later in the day
  GAP  overnight gap -> fade toward the previous close, or go with it
  ORB  first-hour range breakout on an hourly close, entry next bar open
Split as hourly.py: search < 2025-07-01, holdout after (never scored in the search).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np

from ..config import UNIVERSE
from .hourly import SLOTS, TICK, Panel

ETFS = set(UNIVERSE[:10])
INF = np.inf


@dataclass(frozen=True)
class Cfg:
    family: str
    p: tuple   # family-specific parameters, see the builders


def simulate(O, H, L, C, sign, e, x, stop, tp, atr):
    """Vectorized; arrays are per event (O/H/L/C are [n x SLOTS]). Returns net ATR units."""
    n = len(e)
    s = sign[:, None]
    Om, Cm = O * s, C * s
    Hm = np.where(s > 0, H, -L)
    Lm = np.where(s > 0, L, -H)
    st, tg = stop * sign, tp * sign                 # mirrored: stop below, target above
    entry = Om[np.arange(n), e]
    out = np.full(n, np.nan)
    done = np.zeros(n, bool)
    for k in range(SLOTS):
        act = ~done & (e <= k) & (k <= x)
        if not act.any():
            continue
        hit_s = act & (Lm[:, k] <= st)
        out = np.where(hit_s, np.minimum(Om[:, k], st) - entry, out)
        done |= hit_s
        hit_t = act & ~hit_s & (Hm[:, k] >= tg)
        out = np.where(hit_t, tg - entry, out)  # limit fill at the target price
        done |= hit_t
        fin = act & ~done & (k == x)
        out = np.where(fin, Cm[:, k] - entry, out)
        done |= fin
    return (out - 2 * TICK) / atr


# ---------- family builders: return dict(rows, sign, e, x, stop, tp) for one panel ----------

def mom(P: Panel, p):
    sig, e, x, thr, mode, stop_atr = p
    if sig == "on1":
        k, ref = 0, P.pc
    elif sig == "h1":
        k, ref = 0, P.O[:, 0]
    else:  # "am": open -> 12:30 bar close
        k, ref = 2, P.O[:, 0]
    move = (P.C[:, k] - ref) / P.atr
    rows = np.flatnonzero(np.abs(move) >= max(thr, 1e-9))
    sign = np.sign(move[rows]) * (1 if mode == "mom" else -1)
    entry = P.O[rows, e]
    stop = entry - sign * stop_atr * P.atr[rows] if stop_atr else np.full(len(rows), -INF) * sign
    return rows, sign, np.full(len(rows), e), np.full(len(rows), x), stop, np.full(len(rows), INF) * sign


def gap(P: Panel, p):
    thr, mode, entry_mode, target, stop_atr, x = p
    g = (P.O[:, 0] - P.pc) / P.atr
    rows = np.flatnonzero(np.abs(g) >= thr)
    sign = -np.sign(g[rows]) if mode == "fade" else np.sign(g[rows])
    if entry_mode == "open":
        e = np.zeros(len(rows), int)
    else:
        e = np.ones(len(rows), int)
        if entry_mode == "h1confirm":       # first hour moved in the trade's direction
            ok = np.sign(P.C[rows, 0] - P.O[rows, 0]) == sign
            rows, sign, e = rows[ok], sign[ok], e[ok]
    entry = P.O[rows, e]
    a = P.atr[rows]
    stop = entry - sign * stop_atr * a if stop_atr else -INF * sign
    if target == "pc":
        tp = P.pc[rows]
        ok = (tp - entry) * sign > 0
        rows, sign, e, entry, a = rows[ok], sign[ok], e[ok], entry[ok], a[ok]
        stop = stop[ok] if np.ndim(stop) else stop
        tp = tp[ok]
    elif target == "none":
        tp = INF * sign
    else:
        tp = entry + sign * float(target) * a
    stop = np.broadcast_to(stop, len(rows)).astype(float)
    tp = np.broadcast_to(tp, len(rows)).astype(float)
    return rows, sign, e, np.full(len(rows), x), stop, tp


def orb(P: Panel, p):
    stop_mode, target, last_entry = p
    hi, lo = P.H[:, 0], P.L[:, 0]
    out = []
    taken = np.zeros(len(hi), bool)
    for k in range(1, last_entry):           # breakout close on slot k -> entry at k+1
        up = ~taken & (P.C[:, k] > hi)
        dn = ~taken & (P.C[:, k] < lo)
        for m, sgn in ((up, 1), (dn, -1)):
            r = np.flatnonzero(m)
            if len(r):
                out.append((r, np.full(len(r), sgn), np.full(len(r), k + 1)))
        taken |= up | dn
    if not out:
        z = np.array([], int)
        return z, z, z, z, z.astype(float), z.astype(float)
    rows = np.concatenate([o[0] for o in out])
    sign = np.concatenate([o[1] for o in out]).astype(float)
    e = np.concatenate([o[2] for o in out])
    entry = P.O[rows, e]
    if stop_mode == "other":
        stop = np.where(sign > 0, lo[rows], hi[rows])
    elif stop_mode == "mid":
        stop = (hi[rows] + lo[rows]) / 2
    else:
        stop = entry - sign * 0.5 * P.atr[rows]
    risk = (entry - stop) * sign
    ok = risk > 0
    rows, sign, e, entry, stop, risk = rows[ok], sign[ok], e[ok], entry[ok], stop[ok], risk[ok]
    tp = INF * sign if target == "none" else entry + sign * float(target) * risk
    return rows, sign, e, np.full(len(rows), SLOTS - 1), stop, np.broadcast_to(tp, len(rows)).astype(float)


BUILDERS = {"MOM": mom, "GAP": gap, "ORB": orb}


def grid():
    for sig, (e, x), thr, mode, st in itertools.product(
            ["on1", "h1", "am"], [(None, 5), (None, 6), (5, 5), (5, 6), (6, 6)],
            [0.0, 0.25, 0.5, 1.0], ["mom", "rev"], [0.0, 0.5, 1.0]):
        e0 = (1 if sig != "am" else 3) if e is None else e
        if e0 > x:
            continue
        yield Cfg("MOM", (sig, e0, x, thr, mode, st))
    for thr, mode, em, tg, st, x in itertools.product(
            [0.25, 0.5, 1.0, 1.5], ["fade", "go"], ["open", "h1any", "h1confirm"],
            ["pc", "none", "0.5", "1.0"], [0.0, 0.5, 1.0], [2, 6]):
        if tg == "pc" and mode == "go":
            continue
        yield Cfg("GAP", (thr, mode, em, tg, st, x))
    for st, tg, le in itertools.product(["other", "mid", "atr05"], ["1.0", "2.0", "none"], [3, 5]):
        yield Cfg("ORB", (st, tg, le))


def run_cfg(P: Panel, cfg: Cfg):
    rows, sign, e, x, stop, tp = BUILDERS[cfg.family](P, cfg.p)
    if not len(rows):
        return None
    sign = np.asarray(sign, float)
    r = simulate(P.O[rows], P.H[rows], P.L[rows], P.C[rows], sign, np.asarray(e, int),
                 np.asarray(x, int), np.asarray(stop, float), np.asarray(tp, float), P.atr[rows])
    return {"r": r, "day": P.days[rows], "sign": sign, "trend": sign * P.trend[rows],
            "gapdir": sign * P.gap[rows], "atr_px": P.atr[rows] / P.O[rows, 0],
            "price": P.O[rows, 0], "etf": np.full(len(rows), P.ticker in ETFS)}


FILTERS = {
    "none": lambda d: np.ones(len(d["r"]), bool),
    "long": lambda d: d["sign"] > 0, "short": lambda d: d["sign"] < 0,
    "etf": lambda d: d["etf"], "stocks": lambda d: ~d["etf"],
    "with_trend": lambda d: d["trend"] > 0, "against_trend": lambda d: d["trend"] < 0,
    "with_gap": lambda d: d["gapdir"] > 0, "against_gap": lambda d: d["gapdir"] < 0,
    "high_vol": lambda d: d["atr_px"] >= 0.025, "low_vol": lambda d: d["atr_px"] < 0.025,
    "price>=50": lambda d: d["price"] >= 50,
}
