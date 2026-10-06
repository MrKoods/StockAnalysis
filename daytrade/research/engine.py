"""Generalized Liquidity Sweep Reversal engine for variant search.

Same mirrored-short design as `daytrade.strategy`, but every rule step is a
switch (`Det`) and exits are a separate, cheap stage (`Exit`), so one detection
pass can be scored under many exit policies. With default `Det()` and
`Exit()` it reproduces `daytrade.backtest.run()` trade for trade
(tests/test_research_engine.py).

Works on 1m base bars with a 5m sweep/reclaim timeframe (the user's rules), or
on 5m base bars with a 15m sweep timeframe (the longer-history variant).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import time

import numpy as np
import pandas as pd

from .. import data
from ..config import UNIVERSE
from ..levels import Level, build_5m, day_levels
from ..strategy import swing_lows

TICK = 0.01
LAST_ENTRY, FLATTEN = time(15, 30), time(15, 55)


@dataclass(frozen=True)
class Det:
    base: str = "1m"                 # base bars: "1m" (sweep on 5m) or "5m" (sweep on 15m)
    sweep_ticks: int = 2
    sweep_atr: float | None = None   # if set, sweep distance = sweep_atr * daily ATR
    reclaim_bars: int = 3
    swing_n: int = 2
    choch_window: int = 20
    entry_timeout: int = 15
    zone: str = "fvg_or_fib"         # fvg_or_fib | fvg | fib
    trigger: str = "rejection"       # rejection | close_out | limit_edge | limit_mid | choch
    extend_extreme: bool = True
    swing_after_extreme: bool = False
    levels: str = "all"              # all | pd (PDH/PDL only) | 4h

    @property
    def htf_min(self) -> int:
        return 5 if self.base == "1m" else 15


@dataclass(frozen=True)
class Exit:
    stop_buf_ticks: int = 2
    stop_buf_atr: float = 0.0        # extra buffer in daily-ATR units
    target: str = "level"            # level | R | level_cap | none
    target_r: float = 2.0
    min_r: float = 1.5               # level targets only
    be_at_r: float | None = None     # move stop to breakeven after +x R
    partial_at_r: float | None = None  # take 50% at +x R, then stop to breakeven
    max_hold: int | None = None      # bars
    slippage_ticks: int = 1


@dataclass
class Entry:
    ticker: str
    day: object
    direction: str
    key: tuple
    e: int                     # index of the entry bar
    fill_on_bar: bool          # limit fill inside bar e (vs. market at its open)
    entry: float               # mirrored-space prices from here down
    extreme: float
    level_name: str
    targets: list              # [(price, name)] unswept opposing levels, nearest first
    zone_kind: str
    feats: dict = field(default_factory=dict)


class DayBars:
    """A session's bars in short space (sign=+1) or mirrored long space (sign=-1)."""

    def __init__(self, df: pd.DataFrame, sign: int):
        self.sign, self.ts = sign, df.index
        if sign == 1:
            self.o, self.h, self.l, self.c = (df[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        else:
            self.o, self.c = -df["open"].to_numpy(float), -df["close"].to_numpy(float)
            self.h, self.l = -df["low"].to_numpy(float), -df["high"].to_numpy(float)
        self.v = df["volume"].to_numpy(float)
        self.n = len(df)
        self.tod = np.array([t.hour * 60 + t.minute for t in df.index])
        self._sw: dict[int, np.ndarray] = {}
        tp = (self.h + self.l + self.c) / 3
        cv = np.cumsum(self.v)
        self.vwap = np.where(cv > 0, np.cumsum(tp * self.v) / np.maximum(cv, 1), tp)

    def swings(self, n: int) -> np.ndarray:
        if n not in self._sw:
            self._sw[n] = swing_lows(self.l, n)
        return self._sw[n]


class Universe:
    """All sessions for all tickers, loaded once."""

    def __init__(self, tickers=None, base: str = "1m"):
        self.base = base
        self.days: dict[tuple, dict] = {}
        spy_move: dict = {}
        for t in tickers or UNIVERSE:
            m1 = data.load(t, "1m")
            m5 = build_5m(m1, data.load(t, "5m"))
            if not len(m5):
                continue
            lv = day_levels(m5)
            daily = data.load(t, "1d")
            if len(daily):
                daily = daily.set_axis([x.date() for x in daily.index])
            else:  # fallback: daily bars rebuilt from intraday
                daily = m5.groupby(m5.index.date).agg(
                    open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
            prev_c = daily["close"].shift()
            tr = pd.concat([daily["high"] - daily["low"], (daily["high"] - prev_c).abs(),
                            (daily["low"] - prev_c).abs()], axis=1).max(axis=1)
            atr = tr.rolling(14).mean().shift()          # known before the session opens
            sma20 = daily["close"].rolling(20).mean().shift()
            bars = m1 if base == "1m" else m5
            for day, g in bars.groupby(bars.index.date):
                if day not in lv or pd.isna(atr.get(day)):
                    continue
                if base == "5m" and len(g) < 70:
                    continue
                if base == "1m" and len(g) < 350:
                    continue
                self.days[(t, day)] = {
                    "levels": lv[day], "atr": float(atr[day]), "df": g,
                    "prev_close": float(prev_c[day]),
                    "trend20": float(np.sign(prev_c[day] - sma20[day])) if not pd.isna(sma20[day]) else 0.0,
                    "spy": spy_move,
                    1: DayBars(g, 1), -1: DayBars(g, -1),
                }
                if t == "SPY":
                    spy_move[day] = (g, float(atr[day]))
        self.spy = spy_move

    def sessions(self):
        return sorted({k[1] for k in self.days})


def _first_beyond(d: DayBars, price, lv: Level, dist, upward, before=None):
    hi = d.n if before is None else before
    act = (d.ts[:hi] >= lv.active_from) & (d.ts[:hi] < lv.active_to)
    hit = (d.h[:hi] >= price + dist) if upward else (d.l[:hi] <= price - dist)
    idx = np.flatnonzero(act & hit)
    return int(idx[0]) if len(idx) else None


def _level_ok(name: str, mode: str) -> bool:
    if mode == "all":
        return True
    is_pd = name.startswith("PD")
    return is_pd if mode == "pd" else ("4H" in name and not is_pd)


def detect(U: Universe, det: Det) -> list[Entry]:
    assert det.base == U.base, "detection base must match the Universe's bars"
    out: list[Entry] = []
    for key, ctx in U.days.items():
        for sign, direction, side, opp in ((1, "short", "high", "low"), (-1, "long", "low", "high")):
            d: DayBars = ctx[sign]
            targets = [x for x in ctx["levels"] if x.side == opp]
            for lv in ctx["levels"]:
                if lv.side != side or not _level_ok(lv.name, det.levels):
                    continue
                en = _detect_level(key, ctx, d, lv, targets, det)
                if en is not None:
                    en.direction = direction
                    out.append(en)
    return out


def _detect_level(key, ctx, d: DayBars, lv: Level, targets, det: Det) -> Entry | None:
    lvl = d.sign * lv.price
    dist = det.sweep_atr * ctx["atr"] if det.sweep_atr is not None else det.sweep_ticks * TICK
    i0 = _first_beyond(d, lvl, lv, dist, upward=True)
    if i0 is None:
        return None
    a = np.flatnonzero((d.ts >= lv.active_from) & (d.ts < lv.active_to))[0]
    if not (d.l[a:i0 + 1] <= lvl).any():
        return None

    step = pd.Timedelta(minutes=det.htf_min)
    k_start = d.ts[i0].floor(f"{det.htf_min}min")
    reclaim_end = None
    for r in range(det.reclaim_bars):
        idx = np.flatnonzero((d.ts >= k_start + r * step) & (d.ts < k_start + (r + 1) * step))
        if not len(idx):
            break
        if d.c[idx[-1]] < lvl:
            reclaim_end = k_start + (r + 1) * step
            break
    if reclaim_end is None:
        return None

    sweep_idx = np.flatnonzero((d.ts >= k_start) & (d.ts < reclaim_end))
    x_idx = int(sweep_idx[np.argmax(d.h[sweep_idx])])
    extreme = d.h[x_idx]
    start_idx = int(sweep_idx[0])
    sw = d.swings(det.swing_n)
    j0 = int(np.searchsorted(d.ts, reclaim_end))
    choch = None
    for j in range(j0, min(j0 + det.choch_window, d.n)):
        if d.h[j] > extreme:
            if not det.extend_extreme:
                return None
            extreme, x_idx = d.h[j], j
            continue
        lo = x_idx if det.swing_after_extreme else start_idx
        confirmed = [i for i in range(lo, j - det.swing_n) if sw[i]]
        if confirmed and d.c[j] < d.l[confirmed[-1]]:
            choch = j
            break
    if choch is None:
        return None

    zone = None
    kind = "fib"
    if det.zone != "fib":
        for t in range(x_idx, choch - 1):
            if d.l[t] > d.h[t + 2]:
                zone, kind = (d.h[t + 2], d.l[t]), "fvg"
                break
    if zone is None:
        if det.zone == "fvg":
            return None
        leg = extreme - d.c[choch]
        zone = (d.c[choch] + 0.62 * leg, d.c[choch] + 0.79 * leg)
    z_lo, z_hi = zone

    e = None
    fill_on_bar = False
    entry = None
    if det.trigger == "choch":
        e = choch + 1
    else:
        touched = False
        limit = z_lo if det.trigger == "limit_edge" else (z_lo + z_hi) / 2
        for k in range(choch + 1, min(choch + 1 + det.entry_timeout, d.n)):
            if det.trigger.startswith("limit"):
                if d.h[k] >= limit:
                    e, fill_on_bar, entry = k, True, max(limit, d.o[k])
                    break
                continue
            if d.h[k] > extreme:
                return None
            touched = touched or d.h[k] >= z_lo
            if touched and d.c[k] < z_lo and (det.trigger == "close_out" or d.c[k] < d.o[k]):
                e = k + 1
                break
    if e is None or e >= d.n:
        return None
    if d.ts[e].time() >= LAST_ENTRY:
        return None
    if entry is None:
        entry = d.o[e]

    cands = []
    for t in targets:
        q = d.sign * t.price
        if not (t.active_from <= d.ts[e] < t.active_to) or q >= entry:
            continue
        if _first_beyond(d, q, t, TICK * 2, upward=False, before=e) is not None:
            continue
        cands.append((q, t.name))
    cands.sort(reverse=True)

    atr = ctx["atr"]
    sign = d.sign
    spy = _spy_move(ctx["spy"], d.ts[e], sign)
    feats = {
        "tod": int(d.tod[e]),
        "sweep_depth_atr": float((extreme - lvl) / atr),
        "risk_atr": float((extreme + 2 * TICK - entry) / atr),
        "risk_pct": float((extreme + 2 * TICK - entry) / abs(entry) * 100),
        # mirrored: positive = price above VWAP for a short (stretched in the fade direction)
        "vwap_dist_atr": float((d.c[e - 1] - d.vwap[e - 1]) / atr),
        "day_move_atr": float((d.c[e - 1] - d.o[0]) / atr),
        "gap_atr": float((d.o[0] - sign * ctx["prev_close"]) / atr),
        "trend20": float(sign * ctx["trend20"]),   # +1 = prior trend up for a short (counter-trend)
        "spy_move": spy,
        "rvol_sweep": float(d.v[sweep_idx].mean() / max(d.v[:max(1, start_idx)].mean(), 1)),
        "level_kind": "pd" if lv.name.startswith("PD") else "4h",
        "price": float(abs(entry)),
    }
    return Entry(key[0], key[1], "", key, e, fill_on_bar, float(entry), float(extreme),
                 lv.name, cands, kind, feats)


def _spy_move(spy: dict, ts, sign) -> float:
    """SPY's move from its open to the last closed bar, in SPY daily ATRs, mirrored."""
    rec = spy.get(ts.date())
    if rec is None:
        return 0.0
    g, atr = rec
    before = g[g.index < ts]
    if not len(before):
        return 0.0
    return float(sign * (before["close"].iloc[-1] - g["open"].iloc[0]) / atr)


def simulate(U: Universe, en: Entry, ex: Exit) -> dict | None:
    """Exit one entry (mirrored short). None = skipped by the exit's own rules."""
    ctx = U.days[en.key]
    d: DayBars = ctx[1 if en.direction == "short" else -1]
    slip = ex.slippage_ticks * TICK
    stop = en.extreme + ex.stop_buf_ticks * TICK + ex.stop_buf_atr * ctx["atr"]
    entry = en.entry
    if entry >= stop:
        return None
    R = stop - entry
    lv = [q for q, _ in en.targets if q < entry]
    if ex.target == "level":
        if not lv or (entry - lv[0]) / R < ex.min_r:
            return None
        tp = lv[0]
    elif ex.target == "R":
        tp = entry - ex.target_r * R
    elif ex.target == "level_cap":
        tp = max(lv[0], entry - ex.target_r * R) if lv else entry - ex.target_r * R
    else:
        tp = None

    pos, pnl = 1.0, 0.0
    cur = stop
    part_done = False
    reason, xb = "end_of_data", d.n - 1
    for b in range(en.e, d.n):
        first = b == en.e and en.fill_on_bar
        held = b - en.e
        if d.ts[b].time() >= FLATTEN or (ex.max_hold is not None and held >= ex.max_hold and not first):
            pnl += pos * (entry - d.o[b])
            reason, xb, pos = "time", b, 0.0
            break
        if not first and d.o[b] >= cur:
            pnl += pos * (entry - d.o[b])
            reason, xb, pos = "stop_gap", b, 0.0
            break
        if d.h[b] >= cur:
            pnl += pos * (entry - cur)
            reason, xb, pos = ("stop" if cur > entry else "breakeven"), b, 0.0
            break
        if first:
            continue
        new_cur = cur
        if ex.partial_at_r is not None and not part_done and d.l[b] <= entry - ex.partial_at_r * R:
            pnl += 0.5 * ex.partial_at_r * R
            pos, part_done, new_cur = 0.5, True, entry
        if tp is not None and d.l[b] <= tp:
            pnl += pos * (entry - tp)
            reason, xb, pos = "tp", b, 0.0
            break
        if ex.be_at_r is not None and d.l[b] <= entry - ex.be_at_r * R:
            new_cur = min(new_cur, entry)
        cur = new_cur
    if pos > 0:
        pnl += pos * (entry - d.c[-1])
    gross = pnl / R
    return {
        "ticker": en.ticker, "day": en.day, "direction": en.direction, "level": en.level_name,
        "entry_bar": en.e, "exit_bar": xb, "reason": reason, "zone_kind": en.zone_kind,
        "r_gross": float(gross), "r_net": float((pnl - 2 * slip) / R), **en.feats,
    }


def run(U: Universe, entries: list[Entry], ex: Exit, keep=None, max_per_day: int = 2) -> pd.DataFrame:
    """Simulate, filter (`keep(feats_row) -> bool`), then apply per-stock daily limits."""
    rows = []
    for en in entries:
        r = simulate(U, en, ex)
        if r is not None and (keep is None or keep(r)):
            rows.append(r)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values(["ticker", "day", "entry_bar"])
    taken = []
    for _, g in df.groupby(["ticker", "day"], sort=False):
        busy, n = -1, 0
        for i, r in g.iterrows():
            if n >= max_per_day or r["entry_bar"] <= busy:
                continue
            taken.append(i)
            n += 1
            busy = r["exit_bar"]
    return df.loc[taken].reset_index(drop=True)


def stats(tr: pd.DataFrame) -> dict:
    if tr.empty:
        return {"n": 0, "mean": np.nan, "t_day": np.nan, "win": np.nan, "days_pos": np.nan}
    per_day = tr.groupby("day")["r_net"].sum()
    sd = per_day.std(ddof=1)
    t = per_day.mean() / (sd / np.sqrt(len(per_day))) if sd > 0 and len(per_day) > 1 else np.nan
    return {
        "n": len(tr), "mean": float(tr["r_net"].mean()), "t_day": float(t),
        "win": float((tr["r_net"] > 0).mean()), "days_pos": float((per_day > 0).mean()),
        "total": float(tr["r_net"].sum()),
    }


__all__ = ["Det", "Exit", "Entry", "Universe", "detect", "simulate", "run", "stats", "replace"]


def simulate_reverse(U: Universe, en: Entry, k: float = 1.0, risk: float | None = None,
                     slippage_ticks: int = 1) -> dict | None:
    """Diagnostic: take the OPPOSITE side at the same entry, symmetric bracket of
    `risk` (default: the setup's own stop distance) with a k*risk target."""
    ctx = U.days[en.key]
    d: DayBars = ctx[1 if en.direction == "short" else -1]
    R = risk if risk is not None else en.extreme + 2 * TICK - en.entry
    if R <= 0:
        return None
    entry = en.entry
    stop, tp = entry - R, entry + k * R          # long in mirrored space
    pnl, reason = None, "end_of_data"
    for b in range(en.e, d.n):
        first = b == en.e and en.fill_on_bar
        if d.ts[b].time() >= FLATTEN:
            pnl, reason = d.o[b] - entry, "time"
            break
        if d.l[b] <= stop:
            pnl, reason = (min(d.o[b], stop) if not first else stop) - entry, "stop"
            break
        if not first and d.h[b] >= tp:
            pnl, reason = tp - entry, "tp"
            break
    if pnl is None:
        pnl = d.c[-1] - entry
    slip = slippage_ticks * TICK
    return {"ticker": en.ticker, "day": en.day, "direction": en.direction, "reason": reason,
            "r_net": float((pnl - 2 * slip) / R), **en.feats}
