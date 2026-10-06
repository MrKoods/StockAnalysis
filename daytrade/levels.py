"""Key levels: previous-day high/low and the most recent completed 4-hour bar.

Everything here is computed from bars that have fully closed before the level
becomes active, so nothing looks ahead.

4H bars inside regular hours: A = 09:30-13:30 (closes 13:30), B = 13:30-16:00.
Before 13:30 on day D the most recent completed 4H bar is B of the previous
session; from 13:30 it is A of day D.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

import pandas as pd

from .config import TZ

FOUR_H_SPLIT = time(13, 30)


@dataclass
class Level:
    name: str
    side: str            # "high" (short setups sweep it) or "low" (long setups)
    price: float
    active_from: pd.Timestamp
    active_to: pd.Timestamp  # exclusive


def build_5m(m1: pd.DataFrame, m5: pd.DataFrame) -> pd.DataFrame:
    """5m bars: resampled from 1m where 1m exists (internal consistency), else yfinance 5m."""
    if len(m1):
        r = m1.resample("5min", label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna(subset=["open"])
        m1_days = set(m1.index.date)
        m5 = m5[[d not in m1_days for d in m5.index.date]] if len(m5) else m5
        out = pd.concat([m5, r]) if len(m5) else r
    else:
        out = m5
    return out.sort_index()


def _at(day, t: time) -> pd.Timestamp:
    return pd.Timestamp.combine(day, t).tz_localize(TZ)


def day_levels(bars5: pd.DataFrame) -> dict:
    """Map each session date -> list[Level] usable during that session."""
    by_day = {d: g for d, g in bars5.groupby(bars5.index.date)}
    days = sorted(by_day)
    out = {}
    for prev, day in zip(days, days[1:]):
        p = by_day[prev]
        g = by_day[day]
        open_, split, close = _at(day, time(9, 30)), _at(day, FOUR_H_SPLIT), _at(day, time(16, 0))
        pb = p[p.index.time >= FOUR_H_SPLIT]
        ga = g[g.index.time < FOUR_H_SPLIT]
        lv = [
            Level("PDH", "high", float(p["high"].max()), open_, close),
            Level("PDL", "low", float(p["low"].min()), open_, close),
        ]
        if len(pb):
            lv += [
                Level("4H_H(prev B)", "high", float(pb["high"].max()), open_, split),
                Level("4H_L(prev B)", "low", float(pb["low"].min()), open_, split),
            ]
        if len(ga):
            lv += [
                Level("4H_H(A)", "high", float(ga["high"].max()), split, close),
                Level("4H_L(A)", "low", float(ga["low"].min()), split, close),
            ]
        out[day] = _dedupe(lv)
    return out


def _dedupe(levels: list[Level]) -> list[Level]:
    """Same side + same price + overlapping window -> one level (one sweep, one setup)."""
    kept: list[Level] = []
    for lv in levels:
        dup = next(
            (k for k in kept if k.side == lv.side and abs(k.price - lv.price) < 1e-9
             and k.active_from < lv.active_to and lv.active_from < k.active_to),
            None,
        )
        if dup is None:
            kept.append(lv)
        else:
            dup.name = f"{dup.name}+{lv.name}"
            dup.active_from = min(dup.active_from, lv.active_from)
            dup.active_to = max(dup.active_to, lv.active_to)
    return kept
