"""Round 6: the day-trader strategy library (protocol: research_results/PROTOCOL11_daytrader_library.md).

Every family turns a [session x 390-minute] instrument into trade events:
    rows (session index), sign (+1 long / -1 short), e (entry minute), x (latest exit minute),
    stop, tp (raw prices; +-inf = none), fill (entry price for stop-order fills inside bar e, else NaN)
A market entry fills at the OPEN of minute e. A stop-order fill happens inside minute e at `fill`;
on that minute only the stop is checked (conservative). Stops are checked before targets.
At most one trade per direction per session.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .. import dukascopy
from .minute import N, m_of

INF = np.inf
ETFS = {"SPY", "QQQ", "DIA", "IWM", "GLD", "TLT", "XLF", "XLE"}
TX = {"1200": m_of(11, 59), "1400": m_of(13, 59), "close": N - 1}


@dataclass
class Inst:
    sym: str
    days: np.ndarray
    O: np.ndarray
    H: np.ndarray
    L: np.ndarray
    C: np.ndarray
    atr: np.ndarray
    pc: np.ndarray
    pdh: np.ndarray
    pdl: np.ndarray
    trend20: np.ndarray
    cost_bps: float

    def __post_init__(self):
        self.hod = np.maximum.accumulate(self.H, axis=1)
        self.lod = np.minimum.accumulate(self.L, axis=1)
        tp = (self.H + self.L + self.C) / 3
        self.avg = np.cumsum(tp, axis=1) / np.arange(1, N + 1)        # session average price (TWAP)
        S = len(self.days)
        self.C5 = self.C[:, 4::5]                                        # 5-minute closes (78)
        self.H15 = self.H.reshape(S, 26, 15).max(axis=2)
        self.L15 = self.L.reshape(S, 26, 15).min(axis=2)


def load(sym: str) -> Inst | None:
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
                ("open", "high", "low", "close")), f(atr), f(pc), f(hi.shift()), f(lo.shift()),
                np.sign(f(pc - sma)), 1.0 if sym in ETFS else 2.0)


# ---------------- shared simulator ----------------
def simulate(I: Inst, rows, sign, e, x, stop, tp, fill):
    n = len(rows)
    if n == 0:
        return np.array([])
    s = sign[:, None]
    O, C = I.O[rows] * s, I.C[rows] * s
    Hm = np.where(s > 0, I.H[rows], -I.L[rows])
    Lm = np.where(s > 0, I.L[rows], -I.H[rows])
    st, tg = stop * sign, tp * sign
    has_fill = ~np.isnan(fill)
    entry = np.where(has_fill, fill * sign, O[np.arange(n), e])
    pnl = np.full(n, np.nan)
    done = (entry <= st) | (entry >= tg)                 # already beyond stop/target: invalid trade
    for k in range(int(e.min()), N):
        act = ~done & (e <= k) & (k <= x)
        if not act.any():
            if (k > x).all():
                break
            continue
        first = act & has_fill & (k == e)
        hit_s = act & (Lm[:, k] <= st)
        px_s = np.where(first, st, np.minimum(O[:, k], st))
        pnl = np.where(hit_s, px_s - entry, pnl)
        done |= hit_s
        hit_t = act & ~hit_s & ~first & (Hm[:, k] >= tg)
        pnl = np.where(hit_t, tg - entry, pnl)
        done |= hit_t
        fin = act & ~done & (k == x)
        pnl = np.where(fin, C[:, k] - entry, pnl)
        done |= fin
    return pnl / np.abs(entry)


def _first(mask: np.ndarray, start: int = 0, end: int = N):
    """First True column in [start, end) per row, or -1."""
    sub = mask[:, start:end]
    any_ = sub.any(axis=1)
    return np.where(any_, sub.argmax(axis=1) + start, -1)


def _ev(rows, sign, e, x, stop, tp, fill=None):
    n = len(rows)
    b = lambda v: np.broadcast_to(np.asarray(v, float), n).astype(float)  # noqa: E731
    return {"rows": np.asarray(rows, int), "sign": b(sign), "e": np.asarray(e, int),
            "x": np.broadcast_to(np.asarray(x, int), n).astype(int), "stop": b(stop), "tp": b(tp),
            "fill": b(np.nan if fill is None else fill)}


def _cat(*evs):
    evs = [v for v in evs if v is not None and len(v["rows"])]
    if not evs:
        return None
    return {k: np.concatenate([v[k] for v in evs]) for k in evs[0]}


def _targets(entry, stop, sign, tgt, extra=None):
    risk = (entry - stop) * sign
    if tgt == "none":
        return INF * sign
    if tgt in ("1R", "2R", "3R"):
        return np.where(np.isfinite(risk), entry + sign * float(tgt[0]) * risk, INF * sign)
    return extra   # family-specific level target


def _both(fn, *a):
    """Run a one-direction builder for longs (+1) and shorts (-1) and concatenate."""
    return _cat(fn(1, *a), fn(-1, *a))


def _dir(I: Inst, d: int):
    """Directional views: long space for d=+1, mirrored for d=-1 (prices negated, H<->L)."""
    if d == 1:
        return I.O, I.H, I.L, I.C, I.hod, I.lod, I.pdh, I.pdl
    return -I.O, -I.L, -I.H, -I.C, -I.lod, -I.hod, -I.pdl, -I.pdh


# ---------------- families ----------------
def orb(I, p):
    R, trig, stop_mode, tgt, tx, last = p

    def one(d):
        O, H, L, C, *_ = _dir(I, d)
        hi, lo = H[:, :R].max(axis=1), L[:, :R].min(axis=1)
        lastc = m_of(*last)
        if trig == "close":
            k = _first(C > hi[:, None], R, lastc)
            rows = np.flatnonzero(k >= 0)
            e, fill = k[rows] + 1, None
            entry = O[rows, e]
        else:  # stop-order touch
            k = _first(H > hi[:, None], R, lastc)
            rows = np.flatnonzero(k >= 0)
            e = k[rows]
            entry = np.maximum(hi[rows], O[rows, e])
            fill = entry * d
        stop = {"other": lo[rows], "mid": (hi[rows] + lo[rows]) / 2,
                "atr": entry - 0.25 * I.atr[rows]}[stop_mode]
        tp = _targets(entry, stop, 1, tgt)
        return _ev(rows, d, e, TX[tx], stop * d, tp * d, fill)
    return _cat(one(1), one(-1))


def orbf(I, p):
    R, n, stop_mode, tgt, tx = p

    def one(d):   # long fade of a failed DOWNSIDE break (mirrored for shorts)
        O, H, L, C, *_ = _dir(I, d)
        hi, lo = H[:, :R].max(axis=1), L[:, :R].min(axis=1)
        brk = _first(L < lo[:, None], R, m_of(14, 0))
        rows, e_l, ext_l = [], [], []
        for r in np.flatnonzero(brk >= 0):
            k0 = brk[r]
            back = np.flatnonzero(C[r, k0:min(k0 + n, N - 1)] > lo[r])
            if len(back):
                k = k0 + back[0]
                rows.append(r)
                e_l.append(k + 1)
                ext_l.append(L[r, k0:k + 1].min())
        rows, e = np.array(rows, int), np.array(e_l, int)
        if not len(rows):
            return None
        entry, ext = O[rows, e], np.array(ext_l)
        stop = ext - 0.05 * I.atr[rows] if stop_mode == "ext" else entry - 0.25 * I.atr[rows]
        lvl = {"mid": (hi[rows] + lo[rows]) / 2, "other": hi[rows]}
        tp = lvl[tgt] if tgt in lvl else _targets(entry, stop, 1, tgt)
        return _ev(rows, d, e, TX[tx], stop * d, tp * d)
    return _cat(one(1), one(-1))


def gapgo(I, p, fade=False):
    g, W, confirm, stop_mode, tgt, tx = p
    gap = (I.O[:, 0] - I.pc) / I.atr
    rows = np.flatnonzero(np.abs(gap) >= g)
    sign = np.sign(gap[rows]) * (-1 if fade else 1)
    if W > 0 and confirm:
        ok = sign * (I.C[rows, W - 1] - I.O[rows, 0]) > 0
        rows, sign = rows[ok], sign[ok]
    e = np.full(len(rows), W)
    entry = I.O[rows, W]
    atr = I.atr[rows]
    if stop_mode == "orx" and W > 0:
        stop = np.where(sign > 0, I.L[rows, :W].min(axis=1), I.H[rows, :W].max(axis=1))
    elif stop_mode in ("0.5", "1.0", "orx"):
        stop = entry - sign * float(0.5 if stop_mode == "orx" else stop_mode) * atr
    else:
        stop = -INF * sign
    if tgt == "pc":
        tp = I.pc[rows]
    elif tgt == "half":
        tp = I.O[rows, 0] + (I.pc[rows] - I.O[rows, 0]) / 2
    else:
        tp = _targets(entry * sign, stop * sign, 1, tgt) * sign
    if fade and tgt in ("pc", "half"):
        ok = (tp - entry) * sign > 0
        rows, sign, e, stop, tp = rows[ok], sign[ok], e[ok], np.broadcast_to(stop, len(ok))[ok], tp[ok]
    return _ev(rows, sign, e, TX[tx], stop, tp)


def gapfill(I, p):
    g, W, confirm, tgt, stop_mode, tx = p
    return gapgo(I, (g, W, confirm, stop_mode, tgt, tx), fade=True)


def pull(I, p):
    D, m, frac, tgt, tx = p

    def one(d):
        O, H, L, C, *_ = _dir(I, d)
        drive = (C[:, D - 1] - O[:, 0]) / I.atr
        cand = np.flatnonzero(drive >= m)
        rows, e_l, stop_l, ext_l = [], [], [], []
        for r in cand:
            ext = H[r, :D].max()
            need = ext - frac * (ext - O[r, 0])
            low, pulled = INF, False
            for k in range(D, m_of(12, 0)):
                low = min(low, L[r, k])
                if not pulled and low <= need:
                    pulled = True
                if pulled and C[r, k] > low + 0.5 * (ext - low):
                    rows.append(r)
                    e_l.append(k + 1)
                    stop_l.append(low - 0.02 * I.atr[r])
                    ext_l.append(ext)
                    break
                if C[r, k] < O[r, 0]:      # drive fully erased: no setup
                    break
        if not rows:
            return None
        rows, e = np.array(rows, int), np.array(e_l, int)
        entry, stop = O[rows, e], np.array(stop_l)
        tp = np.array(ext_l) if tgt == "ext" else _targets(entry, stop, 1, tgt)
        return _ev(rows, d, e, TX[tx], stop * d, np.asarray(tp) * d)
    return _cat(one(1), one(-1))


def drivef(I, p):
    D, m, stop_mode, tgt, tx = p
    drive = (I.C[:, D - 1] - I.O[:, 0]) / I.atr
    rows = np.flatnonzero(np.abs(drive) >= m)
    sign = -np.sign(drive[rows])
    entry = I.O[rows, D]
    ext = np.where(sign < 0, I.H[rows, :D].max(axis=1), I.L[rows, :D].min(axis=1))
    stop = ext - sign * 0.1 * I.atr[rows] if stop_mode == "ext" else entry - sign * 0.5 * I.atr[rows]
    lv = {"half": I.O[rows, 0] + 0.5 * (I.C[rows, D - 1] - I.O[rows, 0]), "open": I.O[rows, 0]}
    tp = lv[tgt] if tgt in lv else _targets(entry * sign, stop * sign, 1, tgt) * sign
    return _ev(rows, sign, np.full(len(rows), D), TX[tx], stop, tp)


def hod(I, p):
    T, rmin, stop_mode, tgt = p

    def one(d):
        O, H, L, C, hodd, lodd, *_ = _dir(I, d)
        prev_hod = np.concatenate([np.full((len(O), 1), INF), hodd[:, :-1]], axis=1)
        rng_ok = (hodd - lodd) / I.atr[:, None] >= rmin
        k = _first((C > prev_hod) & rng_ok, m_of(*T), m_of(15, 30))
        rows = np.flatnonzero(k >= 0)
        e = k[rows] + 1
        entry = O[rows, e]
        stop = entry - 0.25 * I.atr[rows] if stop_mode == "atr" else (hodd[rows, k[rows]] + lodd[rows, k[rows]]) / 2
        return _ev(rows, d, e, N - 1, stop * d, _targets(entry, stop, 1, tgt) * d)
    return _cat(one(1), one(-1))


def pdb(I, p):
    inside, stop_mode, tgt, last = p

    def one(d):
        O, H, L, C, _, _, pdh, pdl = _dir(I, d)
        ok_open = (O[:, 0] <= pdh) & (O[:, 0] >= pdl) if inside else np.ones(len(O), bool)
        k = _first((C > pdh[:, None]) & ok_open[:, None], 15, m_of(*last))
        rows = np.flatnonzero(k >= 0)
        e = k[rows] + 1
        entry = O[rows, e]
        stop = {"lvl": pdh[rows] - 0.1 * I.atr[rows], "0.25": entry - 0.25 * I.atr[rows],
                "0.5": entry - 0.5 * I.atr[rows]}[stop_mode]
        return _ev(rows, d, e, N - 1, stop * d, _targets(entry, stop, 1, tgt) * d)
    return _cat(one(1), one(-1))


def retest(I, p):
    win, stop_k, tgt, last = p

    def one(d):
        O, H, L, C, _, _, pdh, _ = _dir(I, d)
        brk = _first(C > pdh[:, None], 15, m_of(*last))
        rows, e_l = [], []
        for r in np.flatnonzero(brk >= 0):
            k0 = brk[r]
            touched = False
            for k in range(k0 + 1, min(k0 + 1 + win, m_of(*last))):
                if L[r, k] <= pdh[r] + 0.05 * I.atr[r]:
                    touched = True
                if C[r, k] < pdh[r] - 0.25 * I.atr[r]:
                    break                                   # failed breakout, not a retest
                if touched and C[r, k] > pdh[r] and C[r, k] > O[r, k]:
                    rows.append(r)
                    e_l.append(k + 1)
                    break
        if not rows:
            return None
        rows, e = np.array(rows, int), np.array(e_l, int)
        entry = O[rows, e]
        stop = pdh[rows] - stop_k * I.atr[rows]
        return _ev(rows, d, e, N - 1, stop * d, _targets(entry, stop, 1, tgt) * d)
    return _cat(one(1), one(-1))


def mean(I, p):
    k, T, step, tgt, stop_atr, hold = p
    dev = (I.C - I.avg) / I.atr[:, None]
    checks = np.zeros(N, bool)
    checks[m_of(*T):m_of(15, 0):step] = True

    def one(d):   # d=+1: price stretched BELOW the average -> buy
        trig = (-d * dev >= k) & checks[None, :]
        kk = _first(trig, m_of(*T), m_of(15, 0))
        rows = np.flatnonzero(kk >= 0)
        sig = kk[rows]
        e = sig + 1
        entry = I.O[rows, e]
        avg = I.avg[rows, sig]
        tp = avg if tgt == "avg" else entry + (avg - entry) / 2
        stop = entry - d * stop_atr * I.atr[rows] if stop_atr else np.full(len(rows), -INF * d)
        x = np.full(len(rows), N - 1) if hold == "close" else np.minimum(e + int(hold), N - 1)
        return _ev(rows, d, e, x, stop, tp)
    return _cat(one(1), one(-1))


def _rsi(c, n):
    diff = np.diff(c, axis=1, prepend=np.nan)
    up, dn = np.where(diff > 0, diff, 0.0), np.where(diff < 0, -diff, 0.0)
    U = pd.DataFrame(up.T).ewm(alpha=1 / n, adjust=False, min_periods=n).mean().to_numpy().T
    Dn = pd.DataFrame(dn.T).ewm(alpha=1 / n, adjust=False, min_periods=n).mean().to_numpy().T
    with np.errstate(invalid="ignore", divide="ignore"):
        return 100 - 100 / (1 + U / Dn)


def osc(I, p):
    ind, stop_atr, tgt, hold = p
    c5 = I.C5
    mid = pd.DataFrame(c5.T).rolling(20, min_periods=8).mean().to_numpy().T
    if ind.startswith("rsi"):
        n, lo = (2, 5) if ind == "rsi2_5" else (2, 10) if ind == "rsi2_10" else (14, 25) if ind == "rsi14_25" else (14, 20)
        r = _rsi(c5, n)
        buy, sell = r < lo, r > 100 - lo
    else:
        width = 2.0 if ind == "bb2" else 2.5
        sd = pd.DataFrame(c5.T).rolling(20, min_periods=8).std().to_numpy().T
        buy, sell = c5 < mid - width * sd, c5 > mid + width * sd
    out = []
    for d, sig in ((1, buy), (-1, sell)):
        j = _first(sig, 6, 66)                          # 10:00 .. 15:00 bar closes
        rows = np.flatnonzero(j >= 0)
        e = 5 * j[rows] + 5
        entry = I.O[rows, e]
        stop = entry - d * stop_atr * I.atr[rows]
        tp = mid[rows, j[rows]] if tgt == "mid" else _targets(entry * d, stop * d, 1, tgt) * d
        x = np.full(len(rows), N - 1) if hold == "close" else np.minimum(e + int(hold), N - 1)
        out.append(_ev(rows, d, e, x, stop, tp))
    return _cat(*out)


def maxo(I, p):
    fast, slow, stop_atr, tgt = p
    ema = lambda span: pd.DataFrame(I.C5.T).ewm(span=span, adjust=False).mean().to_numpy().T  # noqa: E731
    f, s = ema(fast), ema(slow)
    up = (f > s) & np.concatenate([np.zeros((len(f), 1), bool), f[:, :-1] <= s[:, :-1]], axis=1)
    dn = (f < s) & np.concatenate([np.zeros((len(f), 1), bool), f[:, :-1] >= s[:, :-1]], axis=1)
    out = []
    for d, sig in ((1, up), (-1, dn)):
        j = _first(sig, 6, 72)
        rows = np.flatnonzero(j >= 0)
        e = 5 * j[rows] + 5
        entry = I.O[rows, e]
        stop = entry - d * stop_atr * I.atr[rows]
        out.append(_ev(rows, d, e, N - 1, stop, _targets(entry * d, stop * d, 1, tgt) * d))
    return _cat(*out)


def rs(I, p, spy: Inst | None = None):
    T, k, mode, tx, stop_atr = p
    if spy is None or I.sym == "SPY":
        return None
    sidx = {dd: i for i, dd in enumerate(spy.days)}
    m = np.array([dd in sidx for dd in I.days])
    rows_all = np.flatnonzero(m)
    srow = np.array([sidx[dd] for dd in I.days[rows_all]])
    t = m_of(*T)
    rel = (I.C[rows_all, t] / I.O[rows_all, 0] - 1) - (spy.C[srow, t] / spy.O[srow, 0] - 1)
    rel_atr = rel * I.O[rows_all, 0] / I.atr[rows_all]
    sel = np.abs(rel_atr) >= k
    rows = rows_all[sel]
    sign = np.sign(rel_atr[sel]) * (1 if mode == "mom" else -1)
    e = np.full(len(rows), t + 1)
    entry = I.O[rows, t + 1]
    stop = entry - sign * stop_atr * I.atr[rows] if stop_atr else -INF * sign
    x = TX[tx] if tx != "60" else np.minimum(e + 60, N - 1)
    return _ev(rows, sign, e, x, stop, INF * sign)


def pwr(I, p):
    T, k, mode = p
    t = m_of(*T)
    mv = (I.C[:, t - 1] - I.O[:, 0]) / I.atr
    rows = np.flatnonzero(np.abs(mv) >= k)
    sign = np.sign(mv[rows]) * (1 if mode == "mom" else -1)
    return _ev(rows, sign, np.full(len(rows), t), N - 1, -INF * sign, INF * sign)


def lunch(I, p):
    k, tx, mode = p
    t = m_of(11, 30)
    mv = (I.C[:, t - 1] - I.O[:, 0]) / I.atr
    rows = np.flatnonzero(np.abs(mv) >= k)
    sign = np.sign(mv[rows]) * (1 if mode == "mom" else -1)
    x = m_of(13, 29) if tx == "1330" else N - 1
    return _ev(rows, sign, np.full(len(rows), t), x, -INF * sign, INF * sign)


def nr15(I, p):
    thr, tgt, tx = p
    rng = I.H15 - I.L15
    prior = pd.DataFrame(rng.T).expanding(min_periods=2).mean().shift().to_numpy().T
    nr = (rng < thr * prior)
    out = []
    for d in (1, -1):
        rows, e_l, stop_l = [], [], []
        for r in range(len(I.days)):
            js = np.flatnonzero(nr[r, 2:22]) + 2              # NR bars from 10:00 to 14:59
            best = None                                       # EARLIEST breakout in time across NR bars
            for j in js:                                      # (not the first NR bar: that would peek)
                start, end = 15 * (j + 1), min(15 * (j + 1) + 30, N - 1)
                lvl = I.H15[r, j] if d == 1 else I.L15[r, j]
                hit = np.flatnonzero((I.C[r, start:end] - lvl) * d > 0)
                if len(hit) and (best is None or start + hit[0] + 1 < best[0]):
                    best = (start + hit[0] + 1, I.L15[r, j] if d == 1 else I.H15[r, j])
            if best is not None:
                rows.append(r)
                e_l.append(best[0])
                stop_l.append(best[1])
        if not rows:
            continue
        rows, e = np.array(rows, int), np.array(e_l, int)
        entry, stop = I.O[rows, e], np.array(stop_l)
        out.append(_ev(rows, d, e, TX[tx], stop, _targets(entry * d, stop * d, 1, tgt) * d))
    return _cat(*out)


def sweep(I, p):
    level, n, confirm, stop_mode, tgt = p

    def one(d):   # SHORT setups in mirrored space are longs: here d=+1 means short sweep of a high level
        O, H, L, C, hodd, lodd, pdh, pdl = _dir(I, -d)   # mirror so that "sweep above a high" is generic
        # In this view we look for price trading ABOVE a level then closing back BELOW -> trade DOWN (sign -1*... )
        if level == "pd":
            lvl, start, opp = pdh, 1, pdl
        elif level == "pc":
            lvl, start, opp = (I.pc if -d == 1 else -I.pc), 1, None
        elif level == "or30":
            lvl, start = H[:, :30].max(axis=1), 30
            opp = L[:, :30].min(axis=1)
        else:  # "am": morning high as of 11:00
            lvl, start = hodd[:, m_of(10, 59)], m_of(11, 0)
            opp = lodd[:, m_of(10, 59)]
        was_below = np.maximum.accumulate(L <= lvl[:, None], axis=1)
        k0 = _first((H > lvl[:, None] + 0.02 * I.atr[:, None]) & was_below, start, m_of(15, 0))
        rows, e_l, ext_l = [], [], []
        for r in np.flatnonzero(k0 >= 0):
            k = k0[r]
            back = np.flatnonzero(C[r, k:min(k + n, N - 2)] < lvl[r])
            if not len(back):
                continue
            kr = k + back[0]
            if confirm:
                if kr + 1 >= N - 1 or not C[r, kr + 1] < C[r, kr]:
                    continue
                kr += 1
            rows.append(r)
            e_l.append(kr + 1)
            ext_l.append(H[r, k:kr + 1].max())
        if not rows:
            return None
        rows, e = np.array(rows, int), np.array(e_l, int)
        # trade direction in this mirrored view is DOWN; convert to real-space sign
        entry, ext = O[rows, e], np.array(ext_l)
        stop = ext + 0.05 * I.atr[rows] if stop_mode == "ext" else entry + 0.25 * I.atr[rows]
        if tgt == "opp" and opp is not None:
            tp = opp[rows]
        else:
            risk = stop - entry
            tp = entry - (float(tgt[0]) if tgt in ("1R", "2R") else (INF if tgt == "none" else 2.0)) * risk
        real = -d          # view sign
        sign = -real       # we sold the sweep in the view -> real direction is -view
        return _ev(rows, sign, e, N - 1, stop * real, tp * real)
    return _cat(one(1), one(-1))


BUILDERS = {"ORB": orb, "ORBF": orbf, "GAPGO": gapgo, "GAPFILL": gapfill, "PULL": pull, "DRIVEF": drivef,
            "HOD": hod, "PDB": pdb, "RETEST": retest, "MEAN": mean, "OSC": osc, "MAX": maxo, "RS": rs,
            "PWR": pwr, "LUNCH": lunch, "NR15": nr15, "SWEEP": sweep}


@dataclass(frozen=True)
class LCfg:
    family: str
    p: tuple


def grid():
    P = itertools.product
    for R, trig, st, tg, tx, last in P([5, 15, 30, 60], ["close", "touch"], ["other", "mid", "atr"],
                                       ["1R", "2R", "3R", "none"], ["1200", "close"], [(11, 0), (14, 0)]):
        yield LCfg("ORB", (R, trig, st, tg, tx, last))
    for R, n, st, tg, tx in P([15, 30, 60], [5, 15, 30], ["ext", "atr"], ["mid", "other", "1R", "2R"], ["1200", "close"]):
        yield LCfg("ORBF", (R, n, st, tg, tx))
    for g, W, cf, st, tg, tx in P([0.25, 0.5, 1.0, 1.5], [0, 5, 15, 30], [False, True], ["orx", "0.5", "1.0"],
                                  ["1R", "2R", "none"], ["1200", "close"]):
        if W == 0 and cf:
            continue
        yield LCfg("GAPGO", (g, W, cf, st, tg, tx))
    for g, W, cf, tg, st, tx in P([0.25, 0.5, 1.0, 1.5], [0, 5, 15, 30], [False, True], ["pc", "half", "1R"],
                                  ["none", "0.5", "1.0"], ["1200", "1400", "close"]):
        if (W == 0 and cf) or (tg == "1R" and st == "none"):
            continue
        yield LCfg("GAPFILL", (g, W, cf, tg, st, tx))
    for D, m, fr, tg, tx in P([15, 30], [0.3, 0.5, 0.8], [0.33, 0.5], ["1R", "2R", "3R", "ext", "none"], ["1400", "close"]):
        yield LCfg("PULL", (D, m, fr, tg, tx))
    for D, m, st, tg, tx in P([15, 30], [0.5, 0.8, 1.2], ["ext", "atr"], ["half", "open", "1R", "2R"], ["1200", "close"]):
        yield LCfg("DRIVEF", (D, m, st, tg, tx))
    for T, r, st, tg in P([(10, 30), (11, 30), (13, 0)], [0.5, 0.8], ["atr", "mid"], ["1R", "2R", "none"]):
        yield LCfg("HOD", (T, r, st, tg))
    for ins, st, tg, last in P([True, False], ["lvl", "0.25", "0.5"], ["1R", "2R", "3R", "none"], [(12, 0), (15, 0)]):
        yield LCfg("PDB", (ins, st, tg, last))
    for win, sk, tg, last in P([30, 60, 120], [0.1, 0.25], ["1R", "2R", "3R", "none"], [(12, 0), (15, 0)]):
        yield LCfg("RETEST", (win, sk, tg, last))
    for k, T, step, tg, st, hold in P([0.3, 0.5, 0.75, 1.0], [(10, 0), (11, 0)], [1, 5, 15], ["avg", "half"],
                                      [0.0, 0.5, 1.0], ["close", "30", "60"]):
        yield LCfg("MEAN", (k, T, step, tg, st, hold))
    for ind, st, tg, hold in P(["rsi2_5", "rsi2_10", "rsi14_25", "rsi14_20", "bb2", "bb25"], [0.25, 0.5],
                               ["mid", "1R", "2R"], ["close", "30", "60"]):
        yield LCfg("OSC", (ind, st, tg, hold))
    for (fa, sl), st, tg in P([(9, 21), (5, 20), (20, 50)], [0.25, 0.5, 1.0], ["2R", "none"]):
        yield LCfg("MAX", (fa, sl, st, tg))
    for T, k, mode, tx, st in P([(10, 0), (10, 30), (11, 30), (13, 0)], [0.3, 0.5, 1.0], ["mom", "rev"],
                                ["close", "1400", "60"], [0.0, 0.5]):
        yield LCfg("RS", (T, k, mode, tx, st))
    for T, k, mode in P([(14, 30), (15, 0), (15, 30)], [0.3, 0.5, 1.0], ["mom", "rev"]):
        yield LCfg("PWR", (T, k, mode))
    for k, tx, mode in P([0.3, 0.5, 1.0], ["1330", "close"], ["mom", "rev"]):
        yield LCfg("LUNCH", (k, tx, mode))
    for thr, tg, tx in P([0.5, 0.6, 0.75], ["1R", "2R", "none"], ["1400", "close"]):
        yield LCfg("NR15", (thr, tg, tx))
    for lv, n, cf, st, tg in P(["pd", "pc", "or30", "am"], [1, 5, 15], [False, True], ["ext", "atr"],
                               ["1R", "2R", "opp", "none"]):
        yield LCfg("SWEEP", (lv, n, cf, st, tg))


def features(I: Inst, ev: dict) -> dict:
    """Filter features. Each must be known BEFORE the entry minute: the first-30-minute range only
    exists for entries at/after 10:00 (NaN otherwise, so both or30 filters exclude earlier trades).
    Using it for earlier entries was a look-ahead bug (caught 2026-10-07: ORB search t 11.5)."""
    r, s = ev["rows"], ev["sign"]
    or30 = (I.H[r, :30].max(axis=1) - I.L[r, :30].min(axis=1)) / I.atr[r]
    or30 = np.where(ev["e"] >= 30, or30, np.nan)
    gap = (I.O[r, 0] - I.pc[r]) / I.atr[r]
    inside = (I.O[r, 0] <= I.pdh[r]) & (I.O[r, 0] >= I.pdl[r])
    return {"trend": s * I.trend20[r], "gap": s * gap, "or30": or30, "inside": inside}


FILTERS = {
    "none": lambda f, s: np.ones(len(s), bool),
    "long": lambda f, s: s > 0, "short": lambda f, s: s < 0,
    "with_trend": lambda f, s: f["trend"] > 0, "against_trend": lambda f, s: f["trend"] < 0,
    "with_gap": lambda f, s: f["gap"] > 0.1, "against_gap": lambda f, s: f["gap"] < -0.1,
    "wide_or30": lambda f, s: f["or30"] >= 0.5, "narrow_or30": lambda f, s: f["or30"] < 0.5,
    "open_inside": lambda f, s: f["inside"], "open_outside": lambda f, s: ~f["inside"],
}


def run(I: Inst, cfg: LCfg, spy: Inst | None = None):
    """-> dict of per-trade arrays (day, sym, sign, ret, minutes, cost, + filter features) or None."""
    fn = BUILDERS[cfg.family]
    ev = fn(I, cfg.p, spy) if cfg.family == "RS" else fn(I, cfg.p)
    if ev is None or not len(ev["rows"]):
        return None
    keep = (ev["e"] < N) & (ev["e"] <= ev["x"])
    ev = {k: v[keep] for k, v in ev.items()}
    if not len(ev["rows"]):
        return None
    ret = simulate(I, ev["rows"], ev["sign"], ev["e"], ev["x"], ev["stop"], ev["tp"], ev["fill"])
    ok = ~np.isnan(ret)
    f = features(I, ev)
    out = {"day": I.days[ev["rows"]][ok], "sym": np.full(ok.sum(), I.sym), "sign": ev["sign"][ok],
           "ret": ret[ok], "minutes": (ev["x"] - ev["e"] + 1)[ok].astype(float),
           "cost": np.full(ok.sum(), I.cost_bps)}
    out.update({k: v[ok] for k, v in f.items()})
    return out
