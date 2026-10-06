"""Hourly version of the sweep-reversal idea, on ~2 years x ~510 tickers (yfinance 1h).

Bars per session (NY): 09:30, 10:30, ..., 14:30, 15:30 (the last is 30 minutes).
Everything is vectorized as [event x slot] matrices. Long setups are mirrored
into short space exactly as in the 1m/5m engine.

Setup (short side; longs mirrored):
  level   = PDH (prev session high) or 2DH (max high of the prev 2 sessions)
  sweep   = first bar trading >= level + depth*ATR, after price was at/inside the level
  reclaim = that bar closes back below the level (rb=1), or the next bar does (rb=2)
  confirm = none | color (next bar closes red) | break (next bar closes below the
            reclaim bar's low)
  entry   = open of the bar after reclaim/confirmation, no later than the 14:30 bar
  stop    = sweep extreme + buf*ATR ;  target = k*R, or the opposite level, or none
  exit    = stop first if both hit in one bar; otherwise at the session close
Costs: 1 cent per share per side.

Split fixed before searching (2026-10-06): search = sessions before 2025-07-01,
holdout = 2025-07-01 onward (never scored until a pre-registered shortlist exists).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from ..config import DATA_DIR, UNIVERSE
from ..config import ROOT

HOLDOUT_START = date(2025, 7, 1)
SLOTS = 7
TICK = 0.01


def tickers():
    return UNIVERSE + pd.read_csv(ROOT / "daytrade" / "sp500_new.csv")["ticker"].tolist()


@dataclass
class Panel:
    """One ticker: [day x slot] OHLC matrices + daily context."""
    ticker: str
    days: np.ndarray
    O: np.ndarray
    H: np.ndarray
    L: np.ndarray
    C: np.ndarray
    atr: np.ndarray
    pdh: np.ndarray
    pdl: np.ndarray
    h2: np.ndarray
    l2: np.ndarray
    trend: np.ndarray     # sign(prev close - SMA20 of closes), known before the open
    gap: np.ndarray       # (open - prev close) / ATR
    pc: np.ndarray | None = None   # previous session close
    V: np.ndarray | None = None    # [day x slot] volume


def load_panel(t: str) -> Panel | None:
    p = DATA_DIR / "1h" / f"{t}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    df.index = pd.DatetimeIndex(df.index).tz_convert("America/New_York")
    df = df[df.index.date < pd.Timestamp.now(tz="America/New_York").date()]   # complete sessions only
    slot = (df.index.hour * 60 + df.index.minute - 570) // 60
    df = df[(slot >= 0) & (slot < SLOTS)].assign(slot=slot[(slot >= 0) & (slot < SLOTS)], day=lambda x: x.index.date)
    piv = {k: df.pivot_table(index="day", columns="slot", values=k, aggfunc="first").reindex(columns=range(SLOTS))
           for k in ("open", "high", "low", "close", "volume")}
    full = piv["close"].notna().all(axis=1) & piv["open"].notna().all(axis=1)
    piv = {k: v[full] for k, v in piv.items()}
    if len(piv["close"]) < 60:
        return None
    hi, lo = piv["high"].max(axis=1), piv["low"].min(axis=1)
    cl, op = piv["close"][SLOTS - 1], piv["open"][0]
    pc = cl.shift()
    tr = pd.concat([hi - lo, (hi - pc).abs(), (lo - pc).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().shift()
    sma = cl.rolling(20).mean().shift()
    ok = atr.notna() & sma.notna()
    f = lambda s: s[ok].to_numpy(float)  # noqa: E731
    return Panel(t, np.array(list(piv["close"].index[ok])),
                 piv["open"][ok].to_numpy(float), piv["high"][ok].to_numpy(float),
                 piv["low"][ok].to_numpy(float), piv["close"][ok].to_numpy(float),
                 f(atr), f(hi.shift()), f(lo.shift()), f(hi.rolling(2).max().shift()),
                 f(lo.rolling(2).min().shift()), np.sign(f(pc - sma)), f((op - pc) / atr), f(pc),
                 piv["volume"][ok].to_numpy(float))


@dataclass(frozen=True)
class HDet:
    level: str = "pd"        # pd | 2d
    depth: float = 0.0       # sweep distance in ATR (0 = 2 ticks)
    rb: int = 1              # reclaim within 1 or 2 bars
    confirm: str = "none"    # none | color | break


@dataclass(frozen=True)
class HExit:
    buf: float = 0.0         # stop buffer in ATR
    target: str = "R"        # R | level | none
    k: float = 1.0


def events(P: Panel, det: HDet) -> dict | None:
    """All setups for one ticker, both directions, in short space."""
    out = []
    for sign in (1, -1):
        if sign == 1:
            O, H, L, C = P.O, P.H, P.L, P.C
            lvl = P.pdh if det.level == "pd" else P.h2
            opp = P.pdl if det.level == "pd" else P.l2
        else:
            O, H, L, C = -P.O, -P.L, -P.H, -P.C
            lvl = -(P.pdl if det.level == "pd" else P.l2)
            opp = -(P.pdh if det.level == "pd" else P.h2)
        dist = np.maximum(det.depth * P.atr, 2 * TICK)[:, None]
        beyond = H >= lvl[:, None] + dist
        inside = np.maximum.accumulate(L <= lvl[:, None], axis=1)  # traded at/inside the level so far
        valid = beyond & inside
        has = valid.any(axis=1)
        f = np.where(has, valid.argmax(axis=1), -1)
        rows = np.flatnonzero(has)
        if not len(rows):
            continue
        f = f[rows]
        r = np.full(len(rows), -1)
        for step in range(det.rb):
            s = f + step
            okslot = s < SLOTS
            cond = okslot & (C[rows, np.minimum(s, SLOTS - 1)] < lvl[rows]) & (r < 0)
            r = np.where(cond, s, r)
        keep = r >= 0
        rows, f, r = rows[keep], f[keep], r[keep]
        ext = np.array([H[i, a:b + 1].max() for i, a, b in zip(rows, f, r)])
        e = r + 1
        if det.confirm != "none":
            cs = np.minimum(r + 1, SLOTS - 1)
            if det.confirm == "color":
                ok = C[rows, cs] < O[rows, cs]
            else:
                ok = C[rows, cs] < L[rows, r]
            ok &= (r + 1 < SLOTS) & (H[rows, cs] <= ext)   # no new extreme on the confirm bar
            rows, f, r, ext, e = rows[ok], f[ok], r[ok], ext[ok], (r + 2)[ok]
        ok = e <= 5                                          # last entry: 14:30 bar
        rows, f, r, ext, e = rows[ok], f[ok], r[ok], ext[ok], e[ok]
        if not len(rows):
            continue
        out.append(dict(sign=np.full(len(rows), sign), row=rows, e=e, ext=ext, f=f,
                        entry=O[rows, e], opp=opp[rows], O=O[rows], H=H[rows], L=L[rows], C=C[rows],
                        atr=P.atr[rows], day=P.days[rows], trend=sign * P.trend[rows],
                        gap=sign * P.gap[rows], depth=(ext - lvl[rows]) / P.atr[rows],
                        price=np.abs(O[rows, e])))
    if not out:
        return None
    return {k: np.concatenate([o[k] for o in out]) for k in out[0]}


def exits(ev: dict, ex: HExit) -> np.ndarray:
    """Net R per event (NaN = skipped)."""
    n = len(ev["e"])
    entry = ev["entry"]
    stop = ev["ext"] + 2 * TICK + ex.buf * ev["atr"]
    R = stop - entry
    valid = R > 0
    if ex.target == "R":
        tp = entry - ex.k * R
    elif ex.target == "level":
        tp = ev["opp"].copy()
        valid &= tp < entry
    else:
        tp = np.full(n, -np.inf)
    pnl = np.full(n, np.nan)
    done = ~valid
    idx = np.arange(n)
    for s in range(SLOTS):
        act = ~done & (ev["e"] <= s)
        if not act.any():
            continue
        h, lo, o = ev["H"][idx, s], ev["L"][idx, s], ev["O"][idx, s]
        hit_stop = act & (h >= stop)
        px = np.where(o >= stop, o, stop)
        pnl = np.where(hit_stop, entry - px, pnl)
        done |= hit_stop
        hit_tp = act & ~hit_stop & (lo <= tp)
        pnl = np.where(hit_tp, entry - tp, pnl)
        done |= hit_tp
    still = ~done
    pnl = np.where(still, entry - ev["C"][:, SLOTS - 1], pnl)
    return np.where(valid, (pnl - 2 * TICK) / np.where(R > 0, R, np.nan), np.nan)


def det_grid():
    for lv, dp, rb, cf in itertools.product(["pd", "2d"], [0.0, 0.05, 0.1, 0.2], [1, 2],
                                            ["none", "color", "break"]):
        yield HDet(lv, dp, rb, cf)


def exit_grid():
    for buf, (tg, k) in itertools.product([0.0, 0.05, 0.1, 0.2],
                                          [("R", 0.5), ("R", 1.0), ("R", 1.5), ("R", 2.0), ("R", 3.0),
                                           ("level", 0), ("none", 0)]):
        yield HExit(buf, tg, k)


FILTERS = {
    "none": lambda ev: np.ones(len(ev["e"]), bool),
    "short": lambda ev: ev["sign"] == 1,
    "long": lambda ev: ev["sign"] == -1,
    "entry<=11:30": lambda ev: ev["e"] <= 2,
    "entry>=12:30": lambda ev: ev["e"] >= 3,
    "sweep_first_bar": lambda ev: ev["f"] == 0,
    "sweep_after_open": lambda ev: ev["f"] >= 1,
    "counter_trend": lambda ev: ev["trend"] > 0,
    "with_trend": lambda ev: ev["trend"] < 0,
    "gap_into_level": lambda ev: ev["gap"] > 0,
    "gap_away": lambda ev: ev["gap"] <= 0,
    "deep": lambda ev: ev["depth"] >= 0.15,
    "shallow": lambda ev: ev["depth"] < 0.15,
    "price>=50": lambda ev: ev["price"] >= 50,
    "atr_small_vs_px": lambda ev: ev["atr"] / ev["price"] < 0.02,
    "atr_large_vs_px": lambda ev: ev["atr"] / ev["price"] >= 0.02,
}
