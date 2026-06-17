# SWING-ONLY: Rules-based composite scoring for swing candidates.
# Combines technical signals (breakout, trend structure, relative strength) with
# multi-day sentiment trend into a single integer score per ticker.
# All thresholds come from swing_config.yaml — no hardcoded values here.


class SwingScorer:

    def __init__(self, swing_config: dict):
        pass

    def score(self, ticker_indicators: dict) -> int:
        """Compute and return the composite swing score for one ticker. Positive = bullish, negative = bearish."""
        pass

    def _score_breakout(self, indicators: dict) -> int:
        """Return +2 for confirmed bullish breakout, -2 for bearish breakdown, 0 otherwise."""
        pass

    def _score_trend_structure(self, indicators: dict) -> int:
        """Return +1 if price > 50-day MA and 20-day MA > 50-day MA, -1 for inverse, 0 otherwise."""
        pass

    def _score_relative_strength(self, indicators: dict) -> int:
        """Return +1 if ticker 20-day return outperforms benchmark by threshold, -1 for inverse."""
        pass

    def _score_sentiment(self, indicators: dict) -> int:
        """Return +1 for building bullish sentiment trend, -1 for bearish, 0 for neutral/flat."""
        pass
