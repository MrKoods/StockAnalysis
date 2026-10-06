"""Liquidity Sweep Reversal: setup detection and trade simulation for one session.

All logic is written once, for SHORT setups. Long setups run through the same
code on a mirrored copy of the bars (prices negated, high <-> low), so a long
sweep of a low-side level becomes a short sweep of a high-side level. Prices
are mirrored back when a Setup is recorded.

Interpretations of the written rules (confirm these on the charts):
  * A sweep only counts when price reaches the level from the inside: some
    bar since the level became active (up to and including the crossing bar)
    must have traded at or inside it. A gap beyond the level that never
    returns to it burns the level without a setup.
  * The first time a level is traded SWEEP_TICKS beyond, it is "used",
    whether or not a setup follows. "Unswept" for take-profit uses the same test.
  * Reclaim window = the 5m bar where the sweep starts + the next
    RECLAIM_BARS-1 bars. The CHoCH window starts at the reclaim bar's close.
  * If price makes a new extreme after the reclaim but before the CHoCH, the
    sweep extreme (and so the stop and the CHoCH leg) extends to it. During
    the entry stage, taking out the extreme cancels the setup, as written.
  * The trigger must be a rejection candle: it closes out of the zone AND
    closes in the trade direction (red for shorts, green for longs). It may
    be the same candle that first traded into the zone.  [user, 2026-10-05]
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .config import Params
from .levels import Level

FIVE_MIN = pd.Timedelta(minutes=5)


@dataclass
class Setup:
    ticker: str
    day: object
    direction: str
    level_name: str
    level: float
    status: str
    sweep_start: pd.Timestamp | None = None
    reclaim_close: pd.Timestamp | None = None
    extreme: float | None = None
    extreme_ts: pd.Timestamp | None = None
    swing: float | None = None
    swing_ts: pd.Timestamp | None = None
    choch_ts: pd.Timestamp | None = None
    zone_kind: str | None = None
    zone_lo: float | None = None
    zone_hi: float | None = None
    trigger_ts: pd.Timestamp | None = None
    entry_ts: pd.Timestamp | None = None
    entry: float | None = None
    stop: float | None = None
    tp: float | None = None
    tp_name: str | None = None
    tp2: float | None = None
    risk: float | None = None
    planned_r: float | None = None
    exit_ts: pd.Timestamp | None = None
    exit: float | None = None
    exit_reason: str | None = None
    r_gross: float | None = None
    r_net: float | None = None
    tp2_exit_reason: str | None = None
    r_net_tp2: float | None = None

    def to_dict(self):
        return asdict(self)


def swing_lows(low: np.ndarray, n: int) -> np.ndarray:
    """Fractal swing lows: strictly below the n bars on each side."""
    out = np.zeros(len(low), dtype=bool)
    for i in range(n, len(low) - n):
        w = low[i - n:i + n + 1]
        if all(low[i] < w[k] for k in range(len(w)) if k != n):
            out[i] = True
    return out


class _Day:
    """One session's 1m bars, optionally mirrored for long setups."""

    def __init__(self, m1: pd.DataFrame, sign: int):
        self.sign = sign
        self.ts = m1.index
        if sign == 1:
            self.o, self.h, self.l, self.c = (m1[k].to_numpy(float) for k in ("open", "high", "low", "close"))
        else:
            self.o, self.c = -m1["open"].to_numpy(float), -m1["close"].to_numpy(float)
            self.h, self.l = -m1["low"].to_numpy(float), -m1["high"].to_numpy(float)
        self.n = len(self.ts)

    def px(self, x):
        return None if x is None else float(self.sign * x)


def _first_beyond(d: _Day, price: float, lv: Level, dist: float, upward: bool, before: int | None = None):
    """Index of the first 1m bar (in lv's active window) trading `dist` beyond `price`."""
    hi = d.n if before is None else before
    for i in range(hi):
        if not (lv.active_from <= d.ts[i] < lv.active_to):
            continue
        if (d.h[i] >= price + dist) if upward else (d.l[i] <= price - dist):
            return i
    return None


def scan_day(ticker: str, day, m1: pd.DataFrame, levels: list[Level], p: Params) -> list[Setup]:
    setups: list[Setup] = []
    for sign, direction, side, opp in ((1, "short", "high", "low"), (-1, "long", "low", "high")):
        d = _Day(m1, sign)
        sw = swing_lows(d.l, p.swing_n)
        targets = [lv for lv in levels if lv.side == opp]
        for lv in (x for x in levels if x.side == side):
            s = _scan_level(ticker, day, d, sw, lv, targets, p)
            if s is not None:
                s.direction = direction
                setups.append(s)
    return setups


def _scan_level(ticker, day, d: _Day, sw, lv: Level, targets, p: Params) -> Setup | None:
    lvl = d.sign * lv.price
    s = Setup(ticker, day, "", lv.name, lv.price, "")

    i0 = _first_beyond(d, lvl, lv, p.sweep_dist, upward=True)
    if i0 is None:
        return None  # never swept: not a setup, not counted
    active = np.flatnonzero((d.ts >= lv.active_from) & (d.ts < lv.active_to))
    if not (d.l[active[0]:i0 + 1] <= lvl).any():
        s.status = "broken_from_outside"  # never traded at/inside the level since it became active
        return s

    # 2. Reclaim: a 5m close back inside within RECLAIM_BARS 5m bars.
    k_start = d.ts[i0].floor("5min")
    s.sweep_start = k_start
    reclaim_end = None
    for r in range(p.reclaim_bars):
        b0, b1 = k_start + r * FIVE_MIN, k_start + (r + 1) * FIVE_MIN
        idx = np.flatnonzero((d.ts >= b0) & (d.ts < b1))
        if not len(idx):
            break
        if d.c[idx[-1]] < lvl:
            reclaim_end = b1
            break
    if reclaim_end is None:
        s.status = "no_reclaim"
        return s
    s.reclaim_close = reclaim_end

    sweep_idx = np.flatnonzero((d.ts >= k_start) & (d.ts < reclaim_end))
    x_idx = int(sweep_idx[np.argmax(d.h[sweep_idx])])
    extreme = d.h[x_idx]
    s.extreme, s.extreme_ts = d.px(extreme), d.ts[x_idx]

    # 3. CHoCH: 1m close below the most recent confirmed swing low formed after the sweep began.
    start_idx = int(sweep_idx[0])
    j0 = int(np.searchsorted(d.ts, reclaim_end))
    choch = swing_i = None
    for j in range(j0, min(j0 + p.choch_window, d.n)):
        if d.h[j] > extreme:
            extreme, x_idx = d.h[j], j  # new extreme before the CHoCH: extend
            continue
        confirmed = [i for i in range(start_idx, j - p.swing_n) if sw[i]]
        if confirmed and d.c[j] < d.l[confirmed[-1]]:
            choch, swing_i = j, confirmed[-1]
            break
    if choch is None:
        s.status = "no_choch"
        return s
    s.extreme, s.extreme_ts = d.px(extreme), d.ts[x_idx]
    s.choch_ts = d.ts[choch]
    s.swing, s.swing_ts = d.px(d.l[swing_i]), d.ts[swing_i]

    # 4. Entry zone: first bearish FVG inside the CHoCH leg, else 62-79% retracement.
    zone = None
    for t in range(x_idx, choch - 1):
        if d.l[t] > d.h[t + 2]:
            zone, s.zone_kind = (d.h[t + 2], d.l[t]), "fvg"
            break
    if zone is None:
        leg = extreme - d.c[choch]
        zone = (d.c[choch] + p.fib_lo * leg, d.c[choch] + p.fib_hi * leg)
        s.zone_kind = "fib"
    z_lo, z_hi = zone
    s.zone_lo, s.zone_hi = sorted((d.px(z_lo), d.px(z_hi)))

    # 5. Trigger: trade into the zone, then a bearish close back below it; enter next bar's open.
    trigger = None
    touched = False
    for k in range(choch + 1, min(choch + 1 + p.entry_timeout, d.n)):
        if d.h[k] > extreme:
            s.status = "invalidated_before_entry"
            return s
        touched = touched or d.h[k] >= z_lo
        if touched and d.c[k] < z_lo and d.c[k] < d.o[k]:
            trigger = k
            break
    if trigger is None:
        s.status = "entry_timeout"
        return s
    s.trigger_ts = d.ts[trigger]
    e = trigger + 1
    if e >= d.n:
        s.status = "no_next_bar"
        return s
    s.entry_ts = d.ts[e]
    if d.ts[e].time() >= p.last_entry:
        s.status = "after_last_entry"
        return s

    entry = d.o[e]
    stop = extreme + p.stop_buffer
    s.entry, s.stop = d.px(entry), d.px(stop)
    if entry >= stop:
        s.status = "opened_beyond_stop"
        return s
    risk = stop - entry
    s.risk = float(risk)

    # 7. Take profit: nearest unswept opposing level beyond entry.
    cands = []
    for t in targets:
        q = d.sign * t.price
        if not (t.active_from <= d.ts[e] < t.active_to) or q >= entry:
            continue
        if _first_beyond(d, q, t, p.sweep_dist, upward=False, before=e) is not None:
            continue  # already swept before entry
        cands.append((q, t.name))
    cands.sort(reverse=True)
    if not cands:
        s.status = "no_target"
        return s
    tp, s.tp_name = cands[0]
    s.tp = d.px(tp)
    tp2 = cands[1][0] if len(cands) > 1 else None
    s.tp2 = d.px(tp2)
    s.planned_r = float((entry - tp) / risk)
    if s.planned_r < p.min_r:
        s.status = "below_min_r"
        return s

    # 8. Exits.
    xi, xpx, why = _run_exit(d, e, entry, stop, tp, p)
    s.exit_ts, s.exit, s.exit_reason = d.ts[xi], d.px(xpx), why
    gross = entry - xpx
    s.r_gross = float(gross / risk)
    s.r_net = float((gross - 2 * p.slippage) / risk)
    s.tp2_exit_reason, s.r_net_tp2 = _tp2_variant(d, e, entry, stop, tp, tp2, risk, p, (xi, xpx, why))
    s.status = "candidate"
    return s


def _run_exit(d: _Day, start: int, entry, stop, tp, p: Params):
    """Short position from bar `start`. Returns (bar index, exit price, reason)."""
    for b in range(start, d.n):
        if d.ts[b].time() >= p.flatten:
            return b, d.o[b], "time"
        if d.o[b] >= stop:
            return b, d.o[b], "stop_gap"
        if d.h[b] >= stop:          # stop first if both hit in the same bar
            return b, stop, "stop"
        if tp is not None and d.l[b] <= tp:
            return b, tp, "tp"
    return d.n - 1, d.c[-1], "end_of_data"


def _tp2_variant(d, e, entry, stop, tp, tp2, risk, p, base):
    """Half off at TP1, stop to breakeven, rest targets TP2 (evaluated from the next bar)."""
    xi, xpx, why = base
    if tp2 is None or why != "tp":
        return why, float((entry - xpx - 2 * p.slippage) / risk)
    half1 = entry - tp - 2 * p.slippage
    if xi + 1 >= d.n:
        return "tp1_only", float(half1 / risk)
    _, x2, why2 = _run_exit(d, xi + 1, entry, entry, tp2, p)
    half2 = entry - x2 - 2 * p.slippage
    return f"tp1+{why2}", float((0.5 * half1 + 0.5 * half2) / risk)
