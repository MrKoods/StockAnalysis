# SWING-ONLY: Multi-day sentiment trend scoring using StockTwits mention volume and bullish/bearish ratio.
# Swing model evaluates sentiment trend over 3-5 days, unlike the day model which looks for sudden spikes.


def compute_sentiment_trend(history: list[dict], lookback_days: int) -> dict:
    """
    Score the directional sentiment trend over the lookback window.
    Returns a dict with trend direction, magnitude, and a raw sentiment score component.
    """
    pass


def is_sentiment_trending_bullish(history: list[dict], lookback_days: int) -> bool:
    """Return True if both mention volume and bullish ratio are rising over the lookback window."""
    pass


def is_sentiment_trending_bearish(history: list[dict], lookback_days: int) -> bool:
    """Return True if mention volume is rising but bearish ratio dominates over the lookback window."""
    pass
