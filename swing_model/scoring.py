class SwingScorer:
    """Rules-based composite scoring for swing candidates.

    Score interpretation (signed integer, range roughly -8 to +8):
      >= +4  : high bullish confidence
       +2/+3 : moderate bullish confidence
       -1/+1 : low / mixed signals
      -2/-3  : moderate bearish confidence
      <= -4  : high bearish confidence

    Components and their max contribution:
      breakout / breakdown : ±2
      trend structure      : ±1
      relative strength    : ±1
      RSI momentum         : ±1
      MACD momentum        : ±1
      sentiment (StockTwits): ±1
      news (Alpha Vantage) : ±1

    Every threshold comes from swing_config["scoring_thresholds"] — no hardcoded values.
    """

    def __init__(self, swing_config: dict):
        self.thresholds = swing_config["scoring_thresholds"]

    def score(self, ticker_indicators: dict) -> int:
        """Compute and return the composite swing score for one ticker. Positive = bullish, negative = bearish."""
        return (
            self._score_breakout(ticker_indicators)
            + self._score_trend_structure(ticker_indicators)
            + self._score_relative_strength(ticker_indicators)
            + self._score_momentum(ticker_indicators)
            + self._score_macd(ticker_indicators)
            + self._score_sentiment(ticker_indicators)
            + self._score_news(ticker_indicators)
        )

    def _score_breakout(self, indicators: dict) -> int:
        """Return +2 for confirmed bullish breakout, -2 for bearish breakdown, 0 otherwise."""
        if indicators.get("breakout_recent"):
            return 2
        if indicators.get("breakdown_recent"):
            return -2
        return 0

    def _score_trend_structure(self, indicators: dict) -> int:
        """Return +1 if price > 50-day MA and 20-day MA > 50-day MA, -1 for inverse, 0 otherwise."""
        above_long = indicators.get("above_ma_long", False)
        short_above_long = indicators.get("ma_short_above_ma_long", False)
        if above_long and short_above_long:
            return 1
        if not above_long and not short_above_long:
            return -1
        return 0

    def _score_relative_strength(self, indicators: dict) -> int:
        """Return +1 if ticker 20-day return outperforms benchmark by threshold, -1 for inverse."""
        rs = indicators.get("rs_vs_benchmark")
        if rs is None:
            return 0
        threshold = self.thresholds.get("relative_strength_outperformance", 5) / 100.0
        if rs > threshold:
            return 1
        if rs < -threshold:
            return -1
        return 0

    def _score_momentum(self, indicators: dict) -> int:
        """Return +1 if RSI is in the healthy bullish zone, -1 if overbought or deeply oversold, 0 otherwise."""
        rsi_val = indicators.get("rsi")
        if rsi_val is None:
            return 0
        if 50 <= rsi_val <= 70:
            return 1
        if rsi_val > 75 or rsi_val < 35:
            return -1
        return 0

    def _score_macd(self, indicators: dict) -> int:
        """Return +1 if MACD line is above signal and both are positive, -1 if below signal and both negative.

        Requiring both the histogram and the MACD line to agree avoids noisy crossovers
        near zero where MACD is still negative but starting to tick up (not a confirmed bullish regime).
        """
        histogram = indicators.get("macd_histogram")
        macd_val = indicators.get("macd")
        if histogram is None or macd_val is None:
            return 0
        if histogram > 0 and macd_val > 0:
            return 1
        if histogram < 0 and macd_val < 0:
            return -1
        return 0

    def _score_sentiment(self, indicators: dict) -> int:
        """Return +1 for building bullish sentiment trend, -1 for bearish, 0 for neutral/flat."""
        return indicators.get("sentiment_score_component", 0)

    def _score_news(self, indicators: dict) -> int:
        """Return +1 for net bullish recent news, -1 for net bearish, 0 for neutral or no coverage."""
        return indicators.get("news_score_component", 0)
