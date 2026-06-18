def compute_sentiment_trend(history: list[dict], lookback_days: int) -> dict:
    """
    Score the directional sentiment trend over the lookback window.
    Returns a dict with trend direction, magnitude, and a raw sentiment score component.

    Requires at least 2 data points to detect a trend; with only 1 point it falls back
    to the snapshot's bullish/bearish ratio as a static signal.
    """
    if not history:
        return {"direction": "neutral", "magnitude": 0.0, "score_component": 0}

    recent = history[-lookback_days:] if len(history) >= lookback_days else history

    if len(recent) < 2:
        snapshot = recent[0]
        bull = snapshot.get("bullish_ratio", 0.0)
        bear = snapshot.get("bearish_ratio", 0.0)
        if bull > 0.55:
            return {"direction": "bullish", "magnitude": bull, "score_component": 1}
        if bear > 0.55:
            return {"direction": "bearish", "magnitude": bear, "score_component": -1}
        return {"direction": "neutral", "magnitude": 0.0, "score_component": 0}

    mid = len(recent) // 2
    first_half = recent[:mid]
    second_half = recent[mid:]

    def avg(lst, key):
        return sum(s.get(key, 0.0) for s in lst) / len(lst)

    avg_bull_early = avg(first_half, "bullish_ratio")
    avg_bull_late = avg(second_half, "bullish_ratio")
    avg_bear_early = avg(first_half, "bearish_ratio")
    avg_bear_late = avg(second_half, "bearish_ratio")
    avg_vol_early = avg(first_half, "message_count")
    avg_vol_late = avg(second_half, "message_count")

    volume_rising = avg_vol_late >= avg_vol_early
    bull_rising = avg_bull_late > avg_bull_early
    bear_rising = avg_bear_late > avg_bear_early

    if volume_rising and bull_rising and avg_bull_late > 0.50:
        return {"direction": "bullish", "magnitude": avg_bull_late, "score_component": 1}
    if volume_rising and bear_rising and avg_bear_late > 0.50:
        return {"direction": "bearish", "magnitude": avg_bear_late, "score_component": -1}
    return {"direction": "neutral", "magnitude": 0.0, "score_component": 0}


def is_sentiment_trending_bullish(history: list[dict], lookback_days: int) -> bool:
    """Return True if both mention volume and bullish ratio are rising over the lookback window."""
    return compute_sentiment_trend(history, lookback_days)["direction"] == "bullish"


def is_sentiment_trending_bearish(history: list[dict], lookback_days: int) -> bool:
    """Return True if mention volume is rising but bearish ratio dominates over the lookback window."""
    return compute_sentiment_trend(history, lookback_days)["direction"] == "bearish"
