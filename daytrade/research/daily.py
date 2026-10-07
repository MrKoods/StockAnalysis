"""Short-horizon daily families (protocol: research_results/PROTOCOL8_daily_families.md).

Prices are addressed by "points": point 2d = open of session d, 2d+1 = close of session d.
Every trade = (ticker, entry point, exit point, sign, gross return). The hedge benchmark is an
equal-weight universe index defined on the same points, so any entry/exit pair can be hedged.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import DATA_DIR

DDIR = DATA_DIR / "daily_max"
COST_BPS = 2.0
ETF_GROUP = {**{t: "broad" for t in ("SPY", "QQQ", "IWM", "DIA")},
             **{t: "sector" for t in ("XLF", "XLE", "XLK", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB")},
             "TLT": "other", "GLD": "other"}


def universe(name: str) -> list[str]:
    return pd.read_csv(DDIR / f"_{name}.csv")["ticker"].tolist()


@dataclass
class DPanel:
    tickers: list
    dates: np.ndarray        # datetime.date per session
    O: np.ndarray            # [ticker x session]
    H: np.ndarray
    L: np.ndarray
    C: np.ndarray
    V: np.ndarray

    def __post_init__(self):
        C, O, H, L = self.C, self.O, self.H, self.L
        prevC = _shift(C, 1)
        tr = np.fmax(H - L, np.fmax(np.abs(H - prevC), np.abs(L - prevC)))
        self.atr = _roll(tr, 14, np.nanmean)                      # through session d
        self.sma5, self.sma20, self.sma200 = (_roll(C, n, np.nanmean) for n in (5, 20, 200))
        self.dvol20 = _roll(C * self.V, 20, np.nanmean)
        self.prevC = prevC
        with np.errstate(invalid="ignore", divide="ignore"):
            r_on = np.nanmean(O / prevC - 1, axis=0)
            r_id = np.nanmean(C / O - 1, axis=0)
        r_on, r_id = np.nan_to_num(r_on), np.nan_to_num(r_id)
        steps = np.empty(2 * len(self.dates))
        steps[0::2], steps[1::2] = np.log1p(r_on), np.log1p(r_id)
        steps[0] = 0.0
        self.logI = np.cumsum(steps)                             # equal-weight index at every point

    def price(self, ti, p):
        d = p // 2
        return np.where(p % 2 == 0, self.O[ti, d], self.C[ti, d])

    def bench(self, p_in, p_out):
        return np.expm1(self.logI[p_out] - self.logI[p_in])


def _shift(a, k):
    out = np.full_like(a, np.nan)
    out[:, k:] = a[:, :-k]
    return out


def _roll(a, n, fn):
    return pd.DataFrame(a.T).rolling(n, min_periods=int(0.8 * n)).mean().to_numpy().T


def load(name: str, start="1999-01-01") -> DPanel:
    frames = {}
    for t in universe(name):
        p = DDIR / f"{t}.parquet"
        if p.exists():
            df = pd.read_parquet(p)
            frames[t] = df[df.index >= start]
    idx = sorted(set().union(*[f.index for f in frames.values()]))
    tick = list(frames)
    arr = {k: np.full((len(tick), len(idx)), np.nan) for k in ("open", "high", "low", "close", "volume")}
    pos = {d: i for i, d in enumerate(idx)}
    for i, t in enumerate(tick):
        j = np.array([pos[d] for d in frames[t].index])
        for k in arr:
            arr[k][i, j] = frames[t][k].to_numpy(float)
    return DPanel(tick, np.array([d.date() for d in idx]), arr["open"], arr["high"], arr["low"],
                  arr["close"], arr["volume"])


def _trades(P: DPanel, ti, p_in, p_out, sign, r, etf=False):
    ok = ~np.isnan(r) & (p_out < 2 * len(P.dates))
    ti, p_in, p_out, sign, r = ti[ok], p_in[ok], p_out[ok], sign[ok].astype(float), r[ok]
    d_in = p_in // 2
    out = {"day": P.dates[d_in], "raw": sign * r * 1e4 - 2 * COST_BPS, "sign": sign,
           "hold": (p_out - p_in) / 2.0}
    if etf:
        out["hedged"] = out["raw"]            # replaced by the CAL scorer (period-specific baseline)
        out["etf_group"] = np.array([ETF_GROUP.get(P.tickers[i], "other") for i in ti])
        out["ti"], out["p_in"], out["p_out"] = ti, p_in, p_out
    else:
        out["hedged"] = sign * (r - P.bench(p_in, p_out)) * 1e4 - 2 * COST_BPS
        # Filter features must be known at entry: an open entry on session d may only use data
        # through the close of d-1 (using d's close here was a look-ahead bug, fixed 2026-10-07).
        fd = np.where(p_in % 2 == 0, d_in - 1, d_in).clip(0)
        c = P.C[ti, fd]
        out["trend"] = sign * np.sign(c - P.sma200[ti, fd])
        out["atr_px"] = P.atr[ti, fd] / c
        med = np.nanmedian(P.dvol20, axis=0)
        out["liquid"] = P.dvol20[ti, fd] >= med[fd]
    return out


def _rank_select(P, sig, q, mode):
    rank = pd.DataFrame(sig.T).rank(axis=1, pct=True).to_numpy().T
    lo, hi = rank <= q, rank > 1 - q
    longs, shorts = (lo, hi) if mode == "rev" else (hi, lo)
    tl, dl = np.nonzero(longs)
    ts, ds = np.nonzero(shorts)
    return (np.concatenate([tl, ts]), np.concatenate([dl, ds]),
            np.concatenate([np.ones(len(tl)), -np.ones(len(ts))]))


def _entry_exit_fixed(P, ti, d, sign, h, entry):
    p_in = 2 * d + 1 if entry == "close" else 2 * (d + 1)
    p_out = 2 * (d + h) + 1
    keep = p_out < 2 * len(P.dates)
    ti, d, sign, p_in, p_out = ti[keep], d[keep], sign[keep], p_in[keep], p_out[keep]
    r = P.price(ti, p_out) / P.price(ti, p_in) - 1
    return ti, p_in, p_out, sign, r


# ---------------- REV ----------------
def rev(P: DPanel, p):
    k, q, mode, h, entry = p
    sig = P.C / _shift(P.C, k) - 1
    ti, d, sign = _rank_select(P, sig, q, mode)
    return _trades(P, *_entry_exit_fixed(P, ti, d, sign, h, entry))


# ---------------- MRV ----------------
def _rsi2(C):
    diff = np.diff(C, axis=1, prepend=np.nan)
    up, dn = np.where(diff > 0, diff, 0.0), np.where(diff < 0, -diff, 0.0)
    a = 1 / 2
    U = pd.DataFrame(up.T).ewm(alpha=a, adjust=False).mean().to_numpy().T
    D = pd.DataFrame(dn.T).ewm(alpha=a, adjust=False).mean().to_numpy().T
    with np.errstate(invalid="ignore", divide="ignore"):
        return 100 - 100 / (1 + U / D)


def mrv(P: DPanel, p):
    sig_kind, thr, trend, exit_rule, entry = p
    if sig_kind == "rsi2":
        s = _rsi2(P.C)
        long, short = s < thr, s > 100 - thr
    elif sig_kind == "ibs":
        with np.errstate(invalid="ignore", divide="ignore"):
            s = (P.C - P.L) / (P.H - P.L)
        long, short = s < thr, s > 1 - thr
    else:  # consecutive down/up closes
        dn = (P.C < P.prevC).astype(float)
        up = (P.C > P.prevC).astype(float)
        n = int(thr)
        long = pd.DataFrame(dn.T).rolling(n).sum().to_numpy().T == n
        short = pd.DataFrame(up.T).rolling(n).sum().to_numpy().T == n
    if trend == "with200":
        long &= P.C > P.sma200
        short &= P.C < P.sma200
    tl, dl = np.nonzero(long)
    ts, ds = np.nonzero(short)
    ti, d = np.concatenate([tl, ts]), np.concatenate([dl, ds])
    sign = np.concatenate([np.ones(len(tl)), -np.ones(len(ts))])
    if exit_rule == "sma5":
        nD = len(P.dates)
        exit_d = np.minimum(d + 10, nD - 1)
        done = np.zeros(len(d), bool)
        for j in range(1, 11):
            dj = np.minimum(d + j, nD - 1)
            cond = ~done & (sign * (P.C[ti, dj] - P.sma5[ti, dj]) > 0)
            exit_d = np.where(cond, dj, exit_d)
            done |= cond
        p_in = 2 * d + 1 if entry == "close" else 2 * (d + 1)
        p_out = 2 * exit_d + 1
        keep = (d + 10 < nD) & (p_out > p_in)
        ti, sign, p_in, p_out = ti[keep], sign[keep], p_in[keep], p_out[keep]
        r = P.price(ti, p_out) / P.price(ti, p_in) - 1
        return _trades(P, ti, p_in, p_out, sign, r)
    return _trades(P, *_entry_exit_fixed(P, ti, d, sign, int(exit_rule), entry))


# ---------------- ONX ----------------
def onx(P: DPanel, p):
    sig_kind, q, mode = p
    if sig_kind == "all_long":
        ti, d = np.nonzero(~np.isnan(P.C[:, :-1]))
        sign = np.ones(len(ti))
    else:
        sig = P.C / P.O - 1 if sig_kind == "intraday" else P.C / P.prevC - 1
        ti, d, sign = _rank_select(P, sig, q, mode)
        keep = d < len(P.dates) - 1
        ti, d, sign = ti[keep], d[keep], sign[keep]
    p_in, p_out = 2 * d + 1, 2 * (d + 1)
    r = P.price(ti, p_out) / P.price(ti, p_in) - 1
    return _trades(P, ti, p_in, p_out, sign, r)


# ---------------- GAPD ----------------
def gapd(P: DPanel, p):
    thr, mode, trend, exit_rule, target = p
    atr_prev, sma20p, sma200p = _shift(P.atr, 1), _shift(P.sma20, 1), _shift(P.sma200, 1)
    g = (P.O - P.prevC) / atr_prev
    ti, d = np.nonzero(np.abs(g) >= thr)
    sign = -np.sign(g[ti, d]) if mode == "fade" else np.sign(g[ti, d])
    if trend != "none":
        ref = sma20p if trend == "with20" else sma200p
        ok = sign * (P.prevC[ti, d] - ref[ti, d]) > 0
        ti, d, sign = ti[ok], d[ok], sign[ok]
    nD = len(P.dates)
    hold = 0 if exit_rule == "c0" else 1
    keep = d + hold < nD
    ti, d, sign = ti[keep], d[keep], sign[keep]
    p_in, p_out = 2 * d, 2 * (d + hold) + 1
    entry = P.O[ti, d]
    exitp = P.C[ti, d + hold]
    if target == "pc":
        pc = P.prevC[ti, d]
        hit = np.where(sign > 0, P.H[ti, d] >= pc, P.L[ti, d] <= pc)
        exitp = np.where(hit, pc, exitp)
        p_out = np.where(hit, 2 * d + 1, p_out)
    return _trades(P, ti, p_in, p_out, sign, exitp / entry - 1)


# ---------------- BRK ----------------
def brk(P: DPanel, p):
    n, mode, h, entry = p
    prior_max = _shift(pd.DataFrame(P.C.T).rolling(n).max().to_numpy().T, 1)
    prior_min = _shift(pd.DataFrame(P.C.T).rolling(n).min().to_numpy().T, 1)
    hi, lo = P.C > prior_max, P.C < prior_min
    longs, shorts = (hi, lo) if mode == "follow" else (lo, hi)
    tl, dl = np.nonzero(longs)
    ts, ds = np.nonzero(shorts)
    ti, d = np.concatenate([tl, ts]), np.concatenate([dl, ds])
    sign = np.concatenate([np.ones(len(tl)), -np.ones(len(ts))])
    return _trades(P, *_entry_exit_fixed(P, ti, d, sign, h, entry))


# ---------------- CAL (ETF panel) ----------------
def cal(P: DPanel, p):
    kind, a, b = p
    dates = pd.to_datetime(pd.Series(P.dates))
    nD = len(dates)
    month = dates.dt.to_period("M").to_numpy()
    if kind == "tom":            # enter at the close of the a-th last day of the month, exit close of day b of next
        last_idx = np.flatnonzero(np.r_[month[1:] != month[:-1], True])
        ins, outs = [], []
        for li in last_idx:
            di, do = li - (a - 1), li + b
            if di >= 0 and do < nD:
                ins.append(di)
                outs.append(do)
        d_in, d_out = np.array(ins), np.array(outs)
    elif kind == "preholiday":   # hold the last session before a weekday market closure
        bd = np.busday_count(np.array(P.dates[:-1], dtype="datetime64[D]"),
                             np.array(P.dates[1:], dtype="datetime64[D]"))
        pre = np.flatnonzero(bd > 1)
        d_in, d_out = pre - 1, pre
        keep = d_in >= 0
        d_in, d_out = d_in[keep], d_out[keep]
    else:                        # day of week a (0=Mon): hold from the prior close to that close
        dow = dates.dt.weekday.to_numpy()
        d_out = np.flatnonzero(dow == a)
        d_out = d_out[d_out > 0]
        d_in = d_out - 1
    T = len(P.tickers)
    ti = np.repeat(np.arange(T), len(d_in))
    din, dout = np.tile(d_in, T), np.tile(d_out, T)
    p_in, p_out = 2 * din + 1, 2 * dout + 1
    r = P.price(ti, p_out) / P.price(ti, p_in) - 1
    return _trades(P, ti, p_in, p_out, np.ones(len(ti)), r, etf=True)


def cal_hedge(P: DPanel, d: dict, mask: np.ndarray) -> np.ndarray:
    """CAL excess: raw minus the ETF's mean return over windows of equal length whose entry date is
    in the same evaluated subset (mask over trades defines the period)."""
    out = d["raw"].copy()
    if not mask.any():
        return out
    first, last = d["day"][mask].min(), d["day"][mask].max()
    in_per = (P.dates >= first) & (P.dates <= last)
    for ti in np.unique(d["ti"][mask]):
        for L in np.unique(((d["p_out"] - d["p_in"]) // 2)[mask & (d["ti"] == ti)]):
            c = P.C[ti]
            base = np.nanmean((c[L:] / c[:-L] - 1)[in_per[:-L]]) if L > 0 else 0.0
            sel = mask & (d["ti"] == ti) & ((d["p_out"] - d["p_in"]) // 2 == L)
            out[sel] = d["raw"][sel] - base * 1e4
    return out


BUILDERS = {"REV": rev, "MRV": mrv, "ONX": onx, "GAPD": gapd, "BRK": brk, "CAL": cal}


@dataclass(frozen=True)
class DCfg:
    family: str
    p: tuple


def grid():
    for k, q, mode, h, e in itertools.product([1, 2, 3, 5, 10], [0.05, 0.1, 0.2], ["rev", "mom"],
                                              [1, 2, 3, 5], ["close", "open"]):
        yield DCfg("REV", (k, q, mode, h, e))
    for (sk, thrs), tr, ex, e in itertools.product(
            [("rsi2", (5, 10, 20)), ("ibs", (0.1, 0.2, 0.3)), ("down", (3, 4, 5))],
            ["none", "with200"], ["sma5", "1", "3", "5"], ["close", "open"]):
        for thr in thrs:
            yield DCfg("MRV", (sk, thr, tr, ex, e))
    yield DCfg("ONX", ("all_long", 0, "mom"))
    for sk, q, mode in itertools.product(["intraday", "cc"], [0.05, 0.1, 0.2], ["rev", "mom"]):
        yield DCfg("ONX", (sk, q, mode))
    for thr, mode, tr, ex, tg in itertools.product([0.25, 0.5, 1.0, 1.5], ["fade", "go"],
                                                   ["none", "with20", "with200"], ["c0", "c1"], ["pc", "none"]):
        if tg == "pc" and mode == "go":
            continue
        yield DCfg("GAPD", (thr, mode, tr, ex, tg))
    for n, mode, h, e in itertools.product([5, 10, 20, 55], ["follow", "fade"], [1, 3, 5, 10], ["close", "open"]):
        yield DCfg("BRK", (n, mode, h, e))
    for a, b in itertools.product([1, 2, 3, 4], [1, 2, 3, 4, 5]):
        yield DCfg("CAL", ("tom", a, b))
    yield DCfg("CAL", ("preholiday", 0, 0))
    for a in range(5):
        yield DCfg("CAL", ("dow", a, 0))


FILTERS = {
    "none": lambda d: np.ones(len(d["raw"]), bool),
    "long": lambda d: d["sign"] > 0, "short": lambda d: d["sign"] < 0,
    "with_trend": lambda d: d["trend"] > 0, "against_trend": lambda d: d["trend"] < 0,
    "liquid": lambda d: d["liquid"], "illiquid": lambda d: ~d["liquid"],
    "low_vol": lambda d: d["atr_px"] < 0.025, "high_vol": lambda d: d["atr_px"] >= 0.025,
}
CAL_FILTERS = {
    "none": lambda d: np.ones(len(d["raw"]), bool),
    "broad": lambda d: d["etf_group"] == "broad",
    "sector": lambda d: d["etf_group"] == "sector",
    "other": lambda d: d["etf_group"] == "other",
}


def run(P: DPanel, cfg: DCfg):
    return BUILDERS[cfg.family](P, cfg.p)


def nw_t(day, bps, lag: int) -> float:
    """Newey-West t of the mean of the per-entry-date summed series."""
    s = pd.Series(bps).groupby(np.asarray(day)).sum().to_numpy()
    n = len(s)
    if n < 10:
        return float("nan")
    x = s - s.mean()
    var = x @ x / n
    for k in range(1, min(lag, n - 1) + 1):
        w = 1 - k / (lag + 1)
        var += 2 * w * (x[k:] @ x[:-k]) / n
    return float(s.mean() / np.sqrt(var / n)) if var > 0 else float("nan")


def max_lag(cfg: DCfg) -> int:
    f, p = cfg.family, cfg.p
    if f == "REV":
        return p[3] + 1
    if f == "MRV":
        return 11 if p[3] == "sma5" else int(p[3]) + 1
    if f == "BRK":
        return p[2] + 1
    if f == "CAL":
        return 10
    return 2
