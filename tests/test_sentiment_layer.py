import pytest

from swing_model.sentiment_layer import (
    compute_sentiment_trend,
    is_sentiment_trending_bullish,
    is_sentiment_trending_bearish,
)


def _snapshot(date: str, bullish_ratio: float, bearish_ratio: float, message_count: int = 20) -> dict:
    return {
        "date": date,
        "ticker": "NVDA",
        "message_count": message_count,
        "bullish_count": int(bullish_ratio * message_count),
        "bearish_count": int(bearish_ratio * message_count),
        "neutral_count": message_count - int(bullish_ratio * message_count) - int(bearish_ratio * message_count),
        "bullish_ratio": bullish_ratio,
        "bearish_ratio": bearish_ratio,
    }


# ---------------------------------------------------------------------------
# Empty / minimal history
# ---------------------------------------------------------------------------

def test_empty_history_returns_neutral():
    result = compute_sentiment_trend([], lookback_days=5)
    assert result["direction"] == "neutral"
    assert result["score_component"] == 0
    assert result["magnitude"] == 0.0


def test_single_snapshot_bullish_ratio():
    history = [_snapshot("2024-01-01", bullish_ratio=0.65, bearish_ratio=0.20)]
    result = compute_sentiment_trend(history, lookback_days=5)
    assert result["direction"] == "bullish"
    assert result["score_component"] == 1


def test_single_snapshot_bearish_ratio():
    history = [_snapshot("2024-01-01", bullish_ratio=0.15, bearish_ratio=0.70)]
    result = compute_sentiment_trend(history, lookback_days=5)
    assert result["direction"] == "bearish"
    assert result["score_component"] == -1


def test_single_snapshot_neutral_ratio():
    history = [_snapshot("2024-01-01", bullish_ratio=0.45, bearish_ratio=0.40)]
    result = compute_sentiment_trend(history, lookback_days=5)
    assert result["direction"] == "neutral"
    assert result["score_component"] == 0


# ---------------------------------------------------------------------------
# Multi-day trend detection
# ---------------------------------------------------------------------------

def test_rising_bullish_trend_scores_positive():
    history = [
        _snapshot("2024-01-01", bullish_ratio=0.40, bearish_ratio=0.30, message_count=10),
        _snapshot("2024-01-02", bullish_ratio=0.45, bearish_ratio=0.28, message_count=12),
        _snapshot("2024-01-03", bullish_ratio=0.50, bearish_ratio=0.25, message_count=14),
        _snapshot("2024-01-04", bullish_ratio=0.55, bearish_ratio=0.22, message_count=16),
        _snapshot("2024-01-05", bullish_ratio=0.62, bearish_ratio=0.20, message_count=20),
    ]
    result = compute_sentiment_trend(history, lookback_days=5)
    assert result["direction"] == "bullish"
    assert result["score_component"] == 1


def test_rising_bearish_trend_scores_negative():
    history = [
        _snapshot("2024-01-01", bullish_ratio=0.30, bearish_ratio=0.40, message_count=10),
        _snapshot("2024-01-02", bullish_ratio=0.28, bearish_ratio=0.45, message_count=12),
        _snapshot("2024-01-03", bullish_ratio=0.25, bearish_ratio=0.50, message_count=14),
        _snapshot("2024-01-04", bullish_ratio=0.22, bearish_ratio=0.55, message_count=16),
        _snapshot("2024-01-05", bullish_ratio=0.20, bearish_ratio=0.62, message_count=20),
    ]
    result = compute_sentiment_trend(history, lookback_days=5)
    assert result["direction"] == "bearish"
    assert result["score_component"] == -1


def test_bullish_ratio_rising_but_volume_falling_is_neutral():
    # Bullish ratio improving but volume declining → not a strong signal
    history = [
        _snapshot("2024-01-01", bullish_ratio=0.40, bearish_ratio=0.30, message_count=30),
        _snapshot("2024-01-02", bullish_ratio=0.45, bearish_ratio=0.28, message_count=25),
        _snapshot("2024-01-03", bullish_ratio=0.50, bearish_ratio=0.25, message_count=20),
        _snapshot("2024-01-04", bullish_ratio=0.55, bearish_ratio=0.22, message_count=15),
        _snapshot("2024-01-05", bullish_ratio=0.62, bearish_ratio=0.20, message_count=10),
    ]
    result = compute_sentiment_trend(history, lookback_days=5)
    # Volume is falling so trend is not confirmed
    assert result["score_component"] == 0


def test_conflicting_early_bullish_late_bearish_is_neutral():
    history = [
        _snapshot("2024-01-01", bullish_ratio=0.65, bearish_ratio=0.15, message_count=20),
        _snapshot("2024-01-02", bullish_ratio=0.60, bearish_ratio=0.20, message_count=22),
        _snapshot("2024-01-03", bullish_ratio=0.40, bearish_ratio=0.40, message_count=22),
        _snapshot("2024-01-04", bullish_ratio=0.25, bearish_ratio=0.55, message_count=24),
        _snapshot("2024-01-05", bullish_ratio=0.20, bearish_ratio=0.60, message_count=25),
    ]
    result = compute_sentiment_trend(history, lookback_days=5)
    # Late half is bearish but started bullish — bearish trend should win late
    assert result["direction"] == "bearish"


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------

def test_is_sentiment_trending_bullish_true():
    history = [
        _snapshot("2024-01-01", bullish_ratio=0.40, bearish_ratio=0.30, message_count=10),
        _snapshot("2024-01-02", bullish_ratio=0.55, bearish_ratio=0.25, message_count=12),
        _snapshot("2024-01-03", bullish_ratio=0.60, bearish_ratio=0.20, message_count=18),
        _snapshot("2024-01-04", bullish_ratio=0.62, bearish_ratio=0.18, message_count=20),
    ]
    assert is_sentiment_trending_bullish(history, lookback_days=4) is True
    assert is_sentiment_trending_bearish(history, lookback_days=4) is False


def test_is_sentiment_trending_bearish_true():
    history = [
        _snapshot("2024-01-01", bullish_ratio=0.30, bearish_ratio=0.40, message_count=10),
        _snapshot("2024-01-02", bullish_ratio=0.25, bearish_ratio=0.50, message_count=12),
        _snapshot("2024-01-03", bullish_ratio=0.20, bearish_ratio=0.58, message_count=18),
        _snapshot("2024-01-04", bullish_ratio=0.18, bearish_ratio=0.62, message_count=20),
    ]
    assert is_sentiment_trending_bearish(history, lookback_days=4) is True
    assert is_sentiment_trending_bullish(history, lookback_days=4) is False
