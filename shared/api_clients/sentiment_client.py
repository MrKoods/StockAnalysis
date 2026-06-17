# SHARED: Sentiment data client wrapping StockTwits and StockGeist APIs.
# Both models can consume this — swing model uses multi-day trend; day model may use
# real-time mention spikes if sentiment is added to the day scoring layer later.


class SentimentClient:

    def __init__(self, config: dict):
        pass

    def get_stocktwits_sentiment(self, ticker: str) -> dict:
        """Return current StockTwits sentiment snapshot (bullish/bearish ratio, message volume) for a ticker."""
        pass

    def get_sentiment_history(self, ticker: str, lookback_days: int) -> list[dict]:
        """Return daily sentiment snapshots over the lookback window for trend analysis."""
        pass

    def get_mention_spike(self, ticker: str) -> dict:
        """Return real-time mention count relative to baseline — used by day model for sudden spike detection."""
        pass
