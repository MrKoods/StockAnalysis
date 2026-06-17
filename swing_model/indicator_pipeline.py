# SWING-ONLY: Orchestrates the full daily indicator data pull for the semiconductor watchlist.
# Calls shared API clients and shared technical indicators, then combines results with sentiment
# data from sentiment_layer.py into a unified per-ticker indicator dict for the scorer.


class SwingIndicatorPipeline:

    def __init__(self, swing_config: dict, global_config: dict):
        pass

    def run(self) -> list[dict]:
        """Fetch and compute all swing indicators for every ticker in the watchlist. Returns a list of ticker dicts."""
        pass

    def _fetch_technical(self, ticker: str) -> dict:
        """Pull daily OHLCV and compute MA, breakout, and relative-strength indicators for one ticker."""
        pass

    def _fetch_sentiment(self, ticker: str) -> dict:
        """Pull multi-day sentiment data for one ticker and return raw scores for sentiment_layer."""
        pass
