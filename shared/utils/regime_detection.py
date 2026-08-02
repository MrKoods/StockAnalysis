"""
SHARED: Classifies market into trending/choppy/high-vol/range-bound
using VIX level, SMH trend (sector benchmark direction), and market breadth.
Regime is computed daily and stored as a field in each ticker's indicator output.
"""

from typing import Optional

import pandas as pd

from shared.indicators.technical_common import sma

REGIME_TRENDING_UP = "trending_up"
REGIME_TRENDING_DOWN = "trending_down"
REGIME_CHOPPY = "choppy"
REGIME_HIGH_VOL = "high_vol"


def classify_regime(
    vix: float,
    smh_ohlcv: pd.DataFrame,
    breadth_advance_decline: Optional[float] = None,
    vix_high_threshold: float = 25.0,
    vix_extreme_threshold: float = 30.0,
    smh_trend_period: int = 20,
) -> str:
    """
    Classify current market regime.

    Priority order:
    1. VIX > vix_extreme_threshold → REGIME_HIGH_VOL
    2. SMH trending up (close > SMA20 and SMA20 rising) → REGIME_TRENDING_UP
    3. SMH trending down (close < SMA20 and SMA20 falling) → REGIME_TRENDING_DOWN
    4. Otherwise → REGIME_CHOPPY
    """
    if vix > vix_extreme_threshold:
        return REGIME_HIGH_VOL

    close = smh_ohlcv["Close"]
    if len(close) < smh_trend_period + 2:
        return REGIME_CHOPPY

    sma20 = sma(close, smh_trend_period)
    current_sma = sma20.iloc[-1]
    prev_sma = sma20.iloc[-2]
    current_close = close.iloc[-1]

    if pd.isna(current_sma) or pd.isna(prev_sma):
        return REGIME_CHOPPY

    sma_rising = current_sma > prev_sma
    price_above_sma = current_close > current_sma

    if price_above_sma and sma_rising:
        return REGIME_TRENDING_UP
    if not price_above_sma and not sma_rising:
        return REGIME_TRENDING_DOWN

    # Mixed signals (e.g., SMA falling but price above, or vice versa).
    # Elevated VIX (above high threshold but below the extreme cutoff already
    # handled at the top of this function) combined with a directionless trend
    # is exactly the "choppy AND volatile" case the score_cap=70 safety brake
    # (REGIME_HIGH_VOL, see get_regime_modifiers) exists for — both branches
    # previously returned REGIME_CHOPPY here, silently making vix_high_threshold
    # a no-op and skipping that brake for the 25-30 VIX band.
    if vix > vix_high_threshold:
        return REGIME_HIGH_VOL

    return REGIME_CHOPPY


def get_regime_modifiers(regime: str, cfg: dict) -> dict:
    """
    Return confidence weight adjustments for the current regime.

    Returns dict used by scoring.py:
    {
        breakout_weight_delta: float,
        momentum_weight_delta: float,
        mean_reversion_weight_delta: float,
        rsi_weight_delta: float,
        score_cap: float or None,
        regime_modifier: float,  # net modifier to final score (-15 to +10)
    }
    """
    r = cfg.get("modifiers", {}).get("regime", {})
    if regime == REGIME_TRENDING_UP:
        return {
            "breakout_weight_delta": r.get("trending_up_breakout_boost", 10),
            "momentum_weight_delta": r.get("trending_up_breakout_boost", 10),
            "mean_reversion_weight_delta": r.get("trending_up_mean_reversion_penalty", -10),
            "rsi_weight_delta": 0,
            "score_cap": None,
            "regime_modifier": 5.0,  # net modifier applied in scoring.py
        }
    if regime == REGIME_TRENDING_DOWN:
        return {
            "breakout_weight_delta": r.get("trending_up_breakout_boost", 10),
            "momentum_weight_delta": 0,
            "mean_reversion_weight_delta": r.get("trending_up_mean_reversion_penalty", -10),
            "rsi_weight_delta": 0,
            "score_cap": None,
            "regime_modifier": -5.0,
        }
    if regime == REGIME_CHOPPY:
        return {
            "breakout_weight_delta": r.get("choppy_breakout_penalty", -15),
            "momentum_weight_delta": r.get("choppy_breakout_penalty", -15),
            "mean_reversion_weight_delta": 0,
            "rsi_weight_delta": r.get("choppy_rsi_boost", 10),
            "score_cap": None,
            # -8 -> -2 (v2.2.33): swept -8/-4/-2/0 against the 3-sector pooled
            # backtest; -2 gave the best Sharpe (3.43 vs 3.34/3.39/3.40). Weaker
            # signal than the RS-anchor/RSI-band changes in this same round —
            # the differences across this sweep are small and derived from a
            # few dozen choppy-regime bars, closer to the edge of what this
            # dataset can distinguish from noise. Kept because it's a genuine,
            # if modest, local optimum, not a hunch.
            "regime_modifier": -2.0,
        }
    if regime == REGIME_HIGH_VOL:
        return {
            "breakout_weight_delta": -15,
            "momentum_weight_delta": -15,
            "mean_reversion_weight_delta": 0,
            "rsi_weight_delta": 0,
            "score_cap": r.get("high_vol_score_cap", 70),
            "regime_modifier": -15.0,
        }
    return {
        "breakout_weight_delta": 0, "momentum_weight_delta": 0,
        "mean_reversion_weight_delta": 0, "rsi_weight_delta": 0,
        "score_cap": None, "regime_modifier": 0.0,
    }
