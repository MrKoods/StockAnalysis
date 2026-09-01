"""Shared price-frame loading + small numeric helpers for the deep layers."""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from shared.api_clients.market_data_client import fetch_ohlcv_batch


def load_price_frames(ticker: str, benchmark: str, *, period: str = "2y") -> dict:
    """
    Daily (and weekly-resampled) OHLCV for the ticker, its benchmark, and SPY.

    Returns {"ticker_daily", "ticker_weekly", "benchmark_daily", "spy_daily"};
    any value is None if that fetch failed.
    """
    batch = fetch_ohlcv_batch([ticker, benchmark, "SPY"], period=period, interval="1d") or {}
    tdf = batch.get(ticker)
    return {
        "ticker_daily": tdf,
        "ticker_weekly": to_weekly(tdf),
        "benchmark_daily": batch.get(benchmark),
        "spy_daily": batch.get("SPY"),
    }


def to_weekly(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df is None or df.empty:
        return None
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    weekly = df.resample("W-FRI").agg(agg).dropna(how="any")
    return weekly if len(weekly) >= 4 else None


def pct(a: float, b: float) -> Optional[float]:
    """(a / b - 1), guarded."""
    try:
        if b == 0:
            return None
        return round(a / b - 1.0, 4)
    except (TypeError, ZeroDivisionError):
        return None


def percentile_of(series: Optional[pd.Series], value: Optional[float]) -> Optional[float]:
    """Where `value` sits in `series`'s distribution, 0-100. None if too short."""
    if series is None or value is None:
        return None
    s = series.dropna()
    if len(s) < 30 or np.isnan(value):
        return None
    return round(float((s < value).mean()) * 100.0, 1)


def slope_sign(series: Optional[pd.Series], lookback: int = 20) -> Optional[str]:
    """'rising' / 'falling' / 'flat' for the last `lookback` points (OLS on index)."""
    if series is None:
        return None
    s = series.dropna()
    if len(s) < lookback:
        return None
    y = s.iloc[-lookback:].to_numpy(dtype=float)
    x = np.arange(len(y), dtype=float)
    m = float(np.polyfit(x, y, 1)[0])
    scale = float(np.mean(np.abs(y))) or 1.0
    norm = m * len(y) / scale
    if norm > 0.02:
        return "rising"
    if norm < -0.02:
        return "falling"
    return "flat"


def last(series: Optional[pd.Series]) -> Optional[float]:
    if series is None:
        return None
    s = series.dropna()
    return round(float(s.iloc[-1]), 4) if len(s) else None


def swing_pivots(df: pd.DataFrame, window: int = 5) -> tuple[list[float], list[float]]:
    """
    Fractal swing highs / lows: a bar whose High (Low) is the max (min) of the
    window bars on each side. Returns (highs, lows) price lists, oldest-first.
    """
    highs, lows = [], []
    h, lo = df["High"].to_numpy(), df["Low"].to_numpy()
    n = len(df)
    for i in range(window, n - window):
        seg_h, seg_l = h[i - window : i + window + 1], lo[i - window : i + window + 1]
        if h[i] == seg_h.max() and (seg_h == h[i]).sum() == 1:
            highs.append(round(float(h[i]), 2))
        if lo[i] == seg_l.min() and (seg_l == lo[i]).sum() == 1:
            lows.append(round(float(lo[i]), 2))
    return highs, lows


def cluster_levels(prices: list[float], tolerance_pct: float = 0.015) -> list[dict]:
    """
    Collapse nearby price points into levels. Returns [{"price", "touches"}]
    sorted by price. `tolerance_pct` is the max gap (fraction of price) to merge.
    """
    if not prices:
        return []
    ordered = sorted(prices)
    groups: list[list[float]] = [[ordered[0]]]
    for p in ordered[1:]:
        if abs(p - groups[-1][-1]) / groups[-1][-1] <= tolerance_pct:
            groups[-1].append(p)
        else:
            groups.append([p])
    return [
        {"price": round(sum(g) / len(g), 2), "touches": len(g)}
        for g in groups
    ]
