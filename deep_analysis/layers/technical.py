"""
Deep technical view — multi-timeframe trend, momentum, volatility, volume,
relative strength, support/resistance, and price structure — from daily and
weekly OHLCV. Pure computation; the only feed is the price frames.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from shared.indicators.technical_common import atr, macd, rsi, sma
from deep_analysis.layers._prices import (
    cluster_levels,
    last,
    load_price_frames,
    pct,
    percentile_of,
    slope_sign,
    swing_pivots,
)

_MA_PERIODS = (10, 20, 50, 100, 200)


def _ma_stack(close: pd.Series) -> dict:
    price = float(close.iloc[-1])
    stack = {}
    for p in _MA_PERIODS:
        if len(close) < p:
            continue
        ma = sma(close, p)
        stack[f"sma_{p}"] = {
            "value": last(ma),
            "price_vs_pct": pct(price, float(ma.iloc[-1])),
            "slope": slope_sign(ma, min(20, p)),
        }
    aligned_up = all(
        stack.get(f"sma_{a}", {}).get("value", 0) >= stack.get(f"sma_{b}", {}).get("value", 0)
        for a, b in zip(_MA_PERIODS, _MA_PERIODS[1:])
        if f"sma_{a}" in stack and f"sma_{b}" in stack
    )
    aligned_down = all(
        stack.get(f"sma_{a}", {}).get("value", 0) <= stack.get(f"sma_{b}", {}).get("value", 0)
        for a, b in zip(_MA_PERIODS, _MA_PERIODS[1:])
        if f"sma_{a}" in stack and f"sma_{b}" in stack
    )
    stack["alignment"] = "bullish" if aligned_up else "bearish" if aligned_down else "mixed"
    return stack


def _momentum(close: pd.Series, weekly_close: Optional[pd.Series]) -> dict:
    rsi_d = rsi(close, 14)
    rsi_now = last(rsi_d)
    macd_line, signal_line, hist = macd(close)
    hist_recent = hist.dropna()
    roc = {
        f"roc_{n}d": pct(float(close.iloc[-1]), float(close.iloc[-n - 1]))
        for n in (21, 63, 126, 252)
        if len(close) > n + 1
    }
    out = {
        "rsi_14": rsi_now,
        "rsi_14_percentile_1y": percentile_of(rsi_d.tail(252), rsi_now) if rsi_now is not None else None,
        "rsi_state": (
            "overbought" if rsi_now is not None and rsi_now >= 70
            else "oversold" if rsi_now is not None and rsi_now <= 30
            else "neutral"
        ),
        "macd_line_vs_signal": (
            "above" if last(macd_line) is not None and last(signal_line) is not None
            and last(macd_line) > last(signal_line) else "below"
        ),
        "macd_histogram": last(hist),
        "macd_histogram_trend": slope_sign(hist_recent, 5) if len(hist_recent) >= 5 else None,
        **roc,
    }
    if weekly_close is not None and len(weekly_close) >= 20:
        wr = rsi(weekly_close, 14)
        out["rsi_14_weekly"] = last(wr)
        wm, ws, _ = macd(weekly_close)
        out["macd_weekly_line_vs_signal"] = (
            "above" if last(wm) is not None and last(ws) is not None and last(wm) > last(ws) else "below"
        )
    return out


def _rsi_divergence(close: pd.Series) -> Optional[str]:
    """Compare the last two RSI swing extremes vs price over ~60 bars."""
    if len(close) < 60:
        return None
    r = rsi(close, 14).dropna()
    c = close.loc[r.index]
    seg_r, seg_c = r.tail(60).to_numpy(), c.tail(60).to_numpy()
    # crude local extrema (window 3)
    highs = [i for i in range(3, len(seg_c) - 3) if seg_c[i] == seg_c[i - 3 : i + 4].max()]
    lows = [i for i in range(3, len(seg_c) - 3) if seg_c[i] == seg_c[i - 3 : i + 4].min()]
    if len(highs) >= 2 and seg_c[highs[-1]] > seg_c[highs[-2]] and seg_r[highs[-1]] < seg_r[highs[-2]]:
        return "bearish (price higher high, RSI lower high)"
    if len(lows) >= 2 and seg_c[lows[-1]] < seg_c[lows[-2]] and seg_r[lows[-1]] > seg_r[lows[-2]]:
        return "bullish (price lower low, RSI higher low)"
    return "none"


def _volatility(df: pd.DataFrame) -> dict:
    close, high, low = df["Close"], df["High"], df["Low"]
    a = atr(high, low, close, 14)
    atr_now = last(a)
    price = float(close.iloc[-1])
    atr_pct = round(atr_now / price * 100, 2) if atr_now else None
    ret = close.pct_change().dropna()
    realized_20d = round(float(ret.tail(20).std() * np.sqrt(252) * 100), 1) if len(ret) >= 20 else None
    # Bollinger band width (20, 2) percentile — a low percentile = squeeze
    ma20 = sma(close, 20)
    sd20 = close.rolling(20).std()
    bbw = ((ma20 + 2 * sd20) - (ma20 - 2 * sd20)) / ma20
    return {
        "atr_14": atr_now,
        "atr_pct_of_price": atr_pct,
        "atr_percentile_1y": percentile_of((a / close * 100).tail(252), atr_pct) if atr_pct else None,
        "realized_vol_20d_annualized_pct": realized_20d,
        "bollinger_bandwidth_percentile_1y": percentile_of(bbw.tail(252), last(bbw)),
    }


def _volume(df: pd.DataFrame) -> dict:
    vol, close = df["Volume"], df["Close"]
    if vol.dropna().empty:
        return {"data_quality": "unavailable"}
    v20 = vol.rolling(20).mean()
    v60 = vol.rolling(60).mean()
    change = close.diff()
    up_vol = vol.where(change > 0, 0.0).rolling(20).sum()
    down_vol = vol.where(change < 0, 0.0).rolling(20).sum()
    udr = last(up_vol / down_vol.replace(0, np.nan))
    obv = (np.sign(change).fillna(0) * vol).cumsum()
    return {
        "last_vs_20d_avg": pct(float(vol.iloc[-1]), float(v20.iloc[-1])) if not np.isnan(v20.iloc[-1]) else None,
        "20d_avg_vs_60d_avg": pct(float(v20.iloc[-1]), float(v60.iloc[-1])) if not np.isnan(v60.iloc[-1]) else None,
        "up_down_volume_ratio_20d": round(udr, 2) if udr is not None else None,
        "obv_slope_50d": slope_sign(obv, 50),
    }


def _relative_strength(t_close: pd.Series, b_close: pd.Series, bench: str) -> dict:
    idx = t_close.index.intersection(b_close.index)
    t, b = t_close.loc[idx], b_close.loc[idx]
    if len(t) < 30:
        return {"data_quality": "unavailable"}
    spreads = {}
    for n, label in ((21, "1m"), (63, "3m"), (126, "6m"), (252, "12m")):
        if len(t) > n + 1:
            tr = float(t.iloc[-1] / t.iloc[-n - 1] - 1)
            br = float(b.iloc[-1] / b.iloc[-n - 1] - 1)
            spreads[f"vs_{bench}_{label}_pp"] = round((tr - br) * 100, 1)
    rs_line = (t / b)
    rs_tail = rs_line.tail(63)
    return {
        **spreads,
        "rs_line_slope_50d": slope_sign(rs_line, 50),
        "rs_line_at_3m_high": bool(rs_line.iloc[-1] >= rs_tail.max() * 0.999),
        "rs_line_at_3m_low": bool(rs_line.iloc[-1] <= rs_tail.min() * 1.001),
    }


def _structure(df: pd.DataFrame) -> dict:
    close = df["Close"]
    price = float(close.iloc[-1])
    hi_252 = float(df["High"].tail(252).max())
    lo_252 = float(df["Low"].tail(252).min())
    rng_60 = df.tail(60)
    hi_60, lo_60 = float(rng_60["High"].max()), float(rng_60["Low"].min())
    pos_60 = round((price - lo_60) / (hi_60 - lo_60), 2) if hi_60 > lo_60 else None

    highs, lows = swing_pivots(df.tail(252), window=5)
    a = atr(df["High"], df["Low"], close, 14)
    atr_now = float(a.iloc[-1]) if not a.dropna().empty else price * 0.02
    resistance = [lvl for lvl in cluster_levels(highs) if lvl["price"] > price]
    support = [lvl for lvl in cluster_levels(lows) if lvl["price"] < price]
    nearest_res = min(resistance, key=lambda x: x["price"] - price) if resistance else None
    nearest_sup = max(support, key=lambda x: x["price"] - price) if support else None

    return {
        "price": round(price, 2),
        "pct_from_52w_high": pct(price, hi_252),
        "pct_from_52w_low": pct(price, lo_252),
        "position_in_60d_range": pos_60,
        "nearest_resistance": (
            {**nearest_res, "distance_pct": pct(nearest_res["price"], price),
             "distance_atr": round((nearest_res["price"] - price) / atr_now, 1)}
            if nearest_res else None
        ),
        "nearest_support": (
            {**nearest_sup, "distance_pct": pct(nearest_sup["price"], price),
             "distance_atr": round((price - nearest_sup["price"]) / atr_now, 1)}
            if nearest_sup else None
        ),
        "resistance_levels": resistance[:4],
        "support_levels": support[-4:],
    }


def _observations(summary: dict, detail: dict) -> list[str]:
    obs: list[str] = []
    stack = detail.get("ma_stack", {})
    if stack.get("alignment") == "bullish":
        obs.append("Moving-average stack (10/20/50/100/200) is aligned bullishly — each above the next.")
    elif stack.get("alignment") == "bearish":
        obs.append("Moving-average stack is aligned bearishly — each below the next.")
    for p in (50, 200):
        node = stack.get(f"sma_{p}")
        if node and node.get("price_vs_pct") is not None:
            side = "above" if node["price_vs_pct"] > 0 else "below"
            obs.append(f"Price is {abs(node['price_vs_pct']) * 100:.1f}% {side} the {p}-day SMA "
                       f"({node['slope']} slope).")
    mom = detail.get("momentum", {})
    if mom.get("rsi_14") is not None:
        pctl = mom.get("rsi_14_percentile_1y")
        obs.append(f"Daily RSI(14) is {mom['rsi_14']:.0f}"
                   + (f", {pctl:.0f}th percentile of the last year." if pctl is not None else "."))
    if mom.get("rsi_14_weekly") is not None:
        obs.append(f"Weekly RSI(14) is {mom['rsi_14_weekly']:.0f}.")
    if detail.get("rsi_divergence") not in (None, "none"):
        obs.append(f"RSI divergence over the last ~60 sessions: {detail['rsi_divergence']}.")
    if mom.get("macd_histogram_trend"):
        obs.append(f"MACD line is {mom['macd_line_vs_signal']} its signal; histogram {mom['macd_histogram_trend']}.")
    vol = detail.get("volatility", {})
    if vol.get("bollinger_bandwidth_percentile_1y") is not None and vol["bollinger_bandwidth_percentile_1y"] <= 15:
        obs.append(f"Bollinger bandwidth is in the {vol['bollinger_bandwidth_percentile_1y']:.0f}th percentile "
                   "— a volatility squeeze.")
    if vol.get("atr_pct_of_price") is not None:
        obs.append(f"ATR(14) is {vol['atr_pct_of_price']:.1f}% of price"
                   + (f" ({vol['atr_percentile_1y']:.0f}th percentile of the last year)."
                      if vol.get("atr_percentile_1y") is not None else "."))
    vlm = detail.get("volume", {})
    if vlm.get("up_down_volume_ratio_20d") is not None:
        obs.append(f"20-day up/down volume ratio is {vlm['up_down_volume_ratio_20d']:.2f}; "
                   f"OBV 50-day slope {vlm.get('obv_slope_50d')}.")
    rs = detail.get("relative_strength", {})
    rs_spreads = {k: v for k, v in rs.items() if k.endswith("_pp")}
    if rs_spreads:
        parts = ", ".join(f"{k.replace('vs_', '').replace('_pp', '')}: {v:+.1f}pp" for k, v in rs_spreads.items())
        obs.append(f"Relative strength vs benchmark ({parts}); RS line 50-day slope {rs.get('rs_line_slope_50d')}.")
    st = detail.get("structure", {})
    if st.get("pct_from_52w_high") is not None:
        obs.append(f"{abs(st['pct_from_52w_high']) * 100:.0f}% below the 52-week high, "
                   f"{st['pct_from_52w_low'] * 100:.0f}% above the 52-week low; "
                   f"sits at {st.get('position_in_60d_range')} of the 60-day range.")
    if st.get("nearest_resistance"):
        nr = st["nearest_resistance"]
        obs.append(f"Nearest resistance ~{nr['price']} ({nr['distance_pct'] * 100:+.1f}%, {nr['distance_atr']} ATR, "
                   f"{nr['touches']} touches).")
    if st.get("nearest_support"):
        ns = st["nearest_support"]
        obs.append(f"Nearest support ~{ns['price']} ({ns['distance_pct'] * 100:+.1f}%, {ns['distance_atr']} ATR, "
                   f"{ns['touches']} touches).")
    return obs


def analyze_technical(ticker: str, benchmark: str = "SMH", *, frames: Optional[dict] = None) -> dict:
    """Deep technical view for `ticker` against `benchmark`."""
    frames = frames or load_price_frames(ticker, benchmark)
    df = frames.get("ticker_daily")
    if df is None or len(df) < 60:
        return {"summary": {}, "detail": {}, "observations": [], "data_quality": "unavailable"}

    close = df["Close"]
    weekly = frames.get("ticker_weekly")
    weekly_close = weekly["Close"] if weekly is not None else None
    bench_df = frames.get("benchmark_daily")

    detail = {
        "ma_stack": _ma_stack(close),
        "momentum": _momentum(close, weekly_close),
        "rsi_divergence": _rsi_divergence(close),
        "volatility": _volatility(df),
        "volume": _volume(df),
        "relative_strength": (
            _relative_strength(close, bench_df["Close"], benchmark)
            if bench_df is not None else {"data_quality": "unavailable"}
        ),
        "structure": _structure(df),
    }

    summary = {
        "price": detail["structure"]["price"],
        "ma_alignment": detail["ma_stack"]["alignment"],
        "rsi_14": detail["momentum"]["rsi_14"],
        "trend_daily": detail["ma_stack"].get("sma_50", {}).get("slope"),
        "trend_weekly": (
            slope_sign(sma(weekly_close, 10), 10) if weekly_close is not None and len(weekly_close) >= 10 else None
        ),
        "atr_pct_of_price": detail["volatility"]["atr_pct_of_price"],
        "rs_50d_slope": detail["relative_strength"].get("rs_line_slope_50d"),
        "history_bars": len(df),
    }

    dq = "complete"
    if bench_df is None or detail["volume"].get("data_quality") == "unavailable":
        dq = "partial"

    return {
        "summary": summary,
        "detail": detail,
        "observations": _observations(summary, detail),
        "data_quality": dq,
    }
