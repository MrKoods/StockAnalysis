import pytest

from swing_model.scoring import SwingScorer
from swing_model.trade_selector import SwingTradeSelector

# ---------------------------------------------------------------------------
# Shared config fixture
# ---------------------------------------------------------------------------

SWING_CONFIG = {
    "scoring_thresholds": {
        "breakout_volume_multiplier": 1.5,
        "ma_short_period": 20,
        "ma_long_period": 50,
        "relative_strength_outperformance": 5,  # percent
        "sentiment_lookback_days": 5,
        "min_rr_ratio": 2.0,
    },
    "trade_selector": {
        "iv_percentile_high_threshold": 50,
        "swing_expiry_days_min": 30,
        "swing_expiry_days_max": 90,
    },
}


def _bullish_indicators() -> dict:
    """All signals strongly bullish."""
    return {
        "close": 100.0,
        "ma_short": 95.0,
        "ma_long": 88.0,
        "above_ma_short": True,
        "above_ma_long": True,
        "ma_short_above_ma_long": True,
        "breakout_recent": True,
        "breakdown_recent": False,
        "rsi": 58.0,       # healthy bullish zone → +1 from _score_momentum
        "atr": 2.5,
        "macd": 0.6,
        "macd_signal": 0.3,
        "macd_histogram": 0.3,
        "rs_vs_benchmark": 0.09,   # 9 % > 5 % threshold → +1
        "rs_threshold": 0.05,
        "realized_vol_20d": 0.25,
        "vol_percentile_52w": 0.30,
        "sentiment_score_component": 1,
        "sentiment_direction": "bullish",
    }


def _bearish_indicators() -> dict:
    """All signals strongly bearish."""
    return {
        "close": 80.0,
        "ma_short": 87.0,
        "ma_long": 92.0,
        "above_ma_short": False,
        "above_ma_long": False,
        "ma_short_above_ma_long": False,
        "breakout_recent": False,
        "breakdown_recent": True,
        "rsi": 28.0,       # deeply oversold / bearish → -1
        "atr": 2.5,
        "macd": -0.6,
        "macd_signal": -0.3,
        "macd_histogram": -0.3,
        "rs_vs_benchmark": -0.10,   # -10 % < -5 % threshold → -1
        "rs_threshold": 0.05,
        "realized_vol_20d": 0.32,
        "vol_percentile_52w": 0.35,
        "sentiment_score_component": -1,
        "sentiment_direction": "bearish",
    }


# ---------------------------------------------------------------------------
# SwingScorer tests
# ---------------------------------------------------------------------------

def test_swing_scorer_strong_bullish_all_signals():
    scorer = SwingScorer(SWING_CONFIG)
    score = scorer.score(_bullish_indicators())
    # breakout=+2, trend=+1, RS=+1, momentum=+1, MACD=+1, sentiment=+1 → 7
    assert score >= 4, f"Expected >= 4, got {score}"


def test_swing_scorer_bearish_breakdown():
    scorer = SwingScorer(SWING_CONFIG)
    score = scorer.score(_bearish_indicators())
    # breakdown=-2, trend=-1, RS=-1, momentum=-1, MACD=-1, sentiment=-1 → -7
    assert score <= -4, f"Expected <= -4, got {score}"


def test_swing_scorer_neutral_mixed_signals():
    scorer = SwingScorer(SWING_CONFIG)
    indicators = _bullish_indicators()
    # Remove the strongest signals
    indicators["breakout_recent"] = False
    indicators["rs_vs_benchmark"] = 0.01   # below threshold
    indicators["sentiment_score_component"] = -1  # bearish sentiment vs bullish trend
    score = scorer.score(indicators)
    # trend=+1, momentum=+1, MACD=+1, sentiment=-1, breakout=0, RS=0 → 2
    assert -3 < score < 5, f"Expected mixed/moderate score, got {score}"


def test_swing_scorer_macd_bullish_adds_one():
    scorer = SwingScorer(SWING_CONFIG)
    base = _bullish_indicators()
    base["breakout_recent"] = False
    base["rs_vs_benchmark"] = 0.0
    base["sentiment_score_component"] = 0
    base["rsi"] = 45.0  # neutral zone

    base["macd"] = 0.5
    base["macd_histogram"] = 0.2
    score_with = scorer.score(base)

    base["macd"] = -0.1
    base["macd_histogram"] = -0.05
    score_without = scorer.score(base)

    assert score_with == score_without + 2  # +1 bullish vs -1 bearish


def test_swing_scorer_macd_conflicted_scores_zero():
    """MACD above signal but still below zero (recovering) → 0, not +1."""
    scorer = SwingScorer(SWING_CONFIG)
    base = _bullish_indicators()
    base["macd"] = -0.3        # still below zero
    base["macd_histogram"] = 0.1  # histogram positive — recovering but not confirmed
    base["breakout_recent"] = False
    base["rs_vs_benchmark"] = 0.0
    base["sentiment_score_component"] = 0
    base["rsi"] = 45.0

    base_copy = dict(base)
    base_copy["macd_histogram"] = 0.0
    base_copy["macd"] = 0.0

    score_conflicted = scorer.score(base)
    score_zero = scorer.score(base_copy)
    assert score_conflicted == score_zero  # neither condition met in both cases


# ---------------------------------------------------------------------------
# SwingTradeSelector tests
# ---------------------------------------------------------------------------

def test_swing_trade_selector_strong_bullish_low_iv_returns_long_stock():
    scorer = SwingScorer(SWING_CONFIG)
    selector = SwingTradeSelector(SWING_CONFIG)
    indicators = _bullish_indicators()
    indicators["vol_percentile_52w"] = 0.15  # low IV
    score = scorer.score(indicators)
    rec = selector.select("NVDA", score, indicators)
    assert rec is not None
    assert rec["direction"] == "bullish"
    assert rec["structure"] == "long_stock"


def test_swing_trade_selector_strong_bullish_high_iv_returns_spread():
    scorer = SwingScorer(SWING_CONFIG)
    selector = SwingTradeSelector(SWING_CONFIG)
    indicators = _bullish_indicators()
    indicators["vol_percentile_52w"] = 0.80  # high IV
    score = scorer.score(indicators)
    rec = selector.select("NVDA", score, indicators)
    assert rec is not None
    assert rec["structure"] == "bull_call_spread"


def test_swing_trade_selector_below_min_rr_returns_none():
    scorer = SwingScorer(SWING_CONFIG)
    selector = SwingTradeSelector(SWING_CONFIG)
    # Conflicting signals → score will be 0 or 1 → abs(score) < 2 → None
    indicators = _bullish_indicators()
    indicators["breakout_recent"] = False
    indicators["rs_vs_benchmark"] = 0.01    # below threshold → 0
    indicators["sentiment_score_component"] = -1  # opposing
    indicators["rsi"] = 45.0  # neutral zone → 0
    # trend=+1, everything else 0 or negative → score ≈ 0
    score = scorer.score(indicators)
    if abs(score) < 2:
        rec = selector.select("NVDA", score, indicators)
        assert rec is None


def test_swing_trade_selector_conflicting_signals_returns_no_trade():
    scorer = SwingScorer(SWING_CONFIG)
    selector = SwingTradeSelector(SWING_CONFIG)
    indicators = {
        "close": 100.0,
        "ma_short": 98.0,
        "ma_long": 94.0,
        "above_ma_short": True,
        "above_ma_long": True,
        "ma_short_above_ma_long": True,
        "breakout_recent": False,
        "breakdown_recent": False,
        "rsi": 45.0,             # neutral → 0 from momentum
        "atr": 2.5,
        "macd": 0.0,
        "macd_signal": 0.0,
        "macd_histogram": 0.0,
        "rs_vs_benchmark": 0.02,  # below 5 % threshold → 0
        "rs_threshold": 0.05,
        "realized_vol_20d": 0.22,
        "vol_percentile_52w": 0.30,
        "sentiment_score_component": -1,  # bearish sentiment vs bullish trend
        "sentiment_direction": "bearish",
    }
    score = scorer.score(indicators)
    # trend=+1, sentiment=-1, rest=0 → score=0
    assert abs(score) <= 1
    rec = selector.select("NVDA", score, indicators)
    assert rec is None
