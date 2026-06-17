# DAY-ONLY: Rules-based composite scoring for intraday candidates.
# Combines opening range breakout, VWAP hold, relative volume, and options flow confirmation
# into a single integer score per ticker. All thresholds come from day_config.yaml.


class DayScorer:

    def __init__(self, day_config: dict):
        pass

    def score(self, ticker_indicators: dict) -> int:
        """Compute and return the composite day score for one ticker. Positive = bullish, negative = bearish."""
        pass

    def _score_opening_range_break(self, indicators: dict) -> int:
        """Return +2 for confirmed bullish ORB with relative volume, -2 for bearish, 0 otherwise."""
        pass

    def _score_vwap_hold(self, indicators: dict) -> int:
        """Return +1 if price is holding above VWAP after a pullback, -1 if rejected below VWAP."""
        pass

    def _score_options_flow(self, indicators: dict) -> int:
        """Return +1 if unusual call activity and IV expansion confirm the direction, -1 for put-side."""
        pass

    def _score_news_catalyst(self, indicators: dict) -> int:
        """Return +1 if a real-time news catalyst aligns with price direction, -1 for conflicting news."""
        pass
