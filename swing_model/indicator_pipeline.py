import pandas as pd

from shared.api_clients.market_data_client import MarketDataClient
from shared.api_clients.news_client import NewsClient
from shared.api_clients.sentiment_client import SentimentClient
from shared.indicators.technical_common import (
    moving_average,
    is_breakout,
    relative_strength,
    rolling_low,
    average_volume,
    rsi,
    atr,
    macd,
)
from swing_model.news_layer import compute_news_score
from swing_model.sentiment_layer import compute_sentiment_trend
from shared.utils.logger import get_logger

logger = get_logger(__name__)

# Extra history fetched beyond what the scoring window needs, to warm up MA50 and ATR.
_LOOKBACK_DAYS = 400


class SwingIndicatorPipeline:
    """Orchestrates the full daily indicator data pull for the semiconductor watchlist."""

    def __init__(self, swing_config: dict, global_config: dict):
        self.swing_config = swing_config
        self.global_config = global_config
        self.tickers: list[str] = swing_config["watchlist"]["tickers"]
        self.benchmark: str = swing_config["watchlist"]["sector_etf_benchmark"][0]
        self.thresholds: dict = swing_config["scoring_thresholds"]
        self.market_data = MarketDataClient(global_config)
        self.sentiment = SentimentClient(global_config)
        self.news = NewsClient(global_config)
        self._benchmark_df: pd.DataFrame | None = None

    def run(self) -> list[dict]:
        """Fetch and compute all swing indicators for every ticker in the watchlist."""
        logger.info(f"Fetching benchmark data ({self.benchmark})")
        try:
            self._benchmark_df = self.market_data.get_daily_ohlcv(self.benchmark, _LOOKBACK_DAYS)
        except ValueError as exc:
            logger.warning(f"Benchmark fetch failed: {exc}; relative strength will be skipped")
            self._benchmark_df = None

        results = []
        for ticker in self.tickers:
            logger.info(f"Processing {ticker}")
            try:
                tech = self._fetch_technical(ticker)
                sent = self._fetch_sentiment(ticker)
                news = self._fetch_news(ticker)
                results.append({"ticker": ticker, **tech, **sent, **news})
            except Exception as exc:
                logger.warning(f"Skipping {ticker}: {exc}")

        return results

    def _fetch_technical(self, ticker: str) -> dict:
        """Pull daily OHLCV and compute MA, breakout, and relative-strength indicators for one ticker."""
        df = self.market_data.get_daily_ohlcv(ticker, _LOOKBACK_DAYS)
        t = self.thresholds
        short = t["ma_short_period"]
        long_ = t["ma_long_period"]
        vol_mult = t["breakout_volume_multiplier"]

        ma_short_s = moving_average(df, short)
        ma_long_s = moving_average(df, long_)
        breakout_s = is_breakout(df, lookback_window=short, volume_multiplier=vol_mult)
        rsi_s = rsi(df)
        atr_s = atr(df)
        macd_df = macd(df)

        # Breakdown: close below prior 20-day low with volume confirmation
        prior_low_s = rolling_low(df, short).shift(1)
        prior_avg_vol_s = average_volume(df, short).shift(1)
        breakdown_s = (df["Close"] < prior_low_s) & (df["Volume"] > vol_mult * prior_avg_vol_s)

        close = float(df["Close"].iloc[-1])
        ma_short_val = float(ma_short_s.iloc[-1])
        ma_long_val = float(ma_long_s.iloc[-1])
        rsi_val = float(rsi_s.iloc[-1])
        atr_val = float(atr_s.iloc[-1])

        # Look back 3 sessions for a recent breakout/breakdown signal
        breakout_recent = bool(breakout_s.iloc[-3:].any())
        breakdown_recent = bool(breakdown_s.iloc[-3:].any())

        # Relative strength vs. benchmark
        rs_value: float | None = None
        if self._benchmark_df is not None:
            rs_s = relative_strength(df, self._benchmark_df, window=short)
            if not rs_s.empty and not pd.isna(rs_s.iloc[-1]):
                rs_value = float(rs_s.iloc[-1])

        # Realized volatility and 52-week percentile (used by trade selector for IV regime proxy)
        returns = df["Close"].pct_change().dropna()
        realized_vol_20d = float(returns.iloc[-20:].std() * (252 ** 0.5)) if len(returns) >= 20 else 0.0
        vol_percentile_52w = _rolling_vol_percentile(returns, window=20, lookback=252)

        # Sector regime: True if benchmark close is above its own 50-day MA (allow longs)
        sector_above_ma50 = True
        if self._benchmark_df is not None:
            bench_ma50 = moving_average(self._benchmark_df, 50)
            if not bench_ma50.empty and not pd.isna(bench_ma50.iloc[-1]):
                sector_above_ma50 = float(self._benchmark_df["Close"].iloc[-1]) > float(bench_ma50.iloc[-1])

        # Broad market filter: True if SPY is above its 200-day MA (stand aside when below)
        market_above_ma200 = True
        try:
            spy_df = self.market_data.get_daily_ohlcv("SPY", 400)
            spy_ma200 = moving_average(spy_df, 200)
            if not spy_ma200.empty and not pd.isna(spy_ma200.iloc[-1]):
                market_above_ma200 = float(spy_df["Close"].iloc[-1]) > float(spy_ma200.iloc[-1])
        except Exception as exc:
            logger.warning(f"SPY market filter fetch failed: {exc}; defaulting to allow trades")

        return {
            "close": round(close, 2),
            "ma_short": round(ma_short_val, 2),
            "ma_long": round(ma_long_val, 2),
            "above_ma_short": close > ma_short_val,
            "above_ma_long": close > ma_long_val,
            "ma_short_above_ma_long": ma_short_val > ma_long_val,
            "breakout_recent": breakout_recent,
            "breakdown_recent": breakdown_recent,
            "rsi": round(rsi_val, 2),
            "atr": round(atr_val, 4),
            "macd": round(float(macd_df["macd"].iloc[-1]), 4),
            "macd_signal": round(float(macd_df["signal"].iloc[-1]), 4),
            "macd_histogram": round(float(macd_df["histogram"].iloc[-1]), 4),
            "rs_vs_benchmark": round(rs_value, 4) if rs_value is not None else None,
            "rs_threshold": t["relative_strength_outperformance"] / 100.0,
            "realized_vol_20d": round(realized_vol_20d, 4),
            "vol_percentile_52w": round(vol_percentile_52w, 4),
            "sector_above_ma50": sector_above_ma50,
            "market_above_ma200": market_above_ma200,
        }

    def _fetch_sentiment(self, ticker: str) -> dict:
        """Pull multi-day sentiment data for one ticker and return raw scores for sentiment_layer."""
        lookback = self.thresholds.get("sentiment_lookback_days", 5)
        try:
            history = self.sentiment.get_sentiment_history(ticker, lookback)
            trend = compute_sentiment_trend(history, lookback)
        except Exception as exc:
            logger.warning(f"Sentiment fetch failed for {ticker}: {exc}")
            history = []
            trend = {"direction": "neutral", "magnitude": 0.0, "score_component": 0}

        return {
            "sentiment_direction": trend["direction"],
            "sentiment_magnitude": trend["magnitude"],
            "sentiment_score_component": trend["score_component"],
            "sentiment_history": history,
        }

    def _fetch_news(self, ticker: str) -> dict:
        """Pull recent news articles from Alpha Vantage and score them for the news layer."""
        lookback = self.thresholds.get("news_lookback_days", 3)
        try:
            articles = self.news.get_news_sentiment(ticker, lookback_days=lookback)
            score = compute_news_score(articles)
        except Exception as exc:
            logger.warning(f"News fetch failed for {ticker}: {exc}")
            articles = []
            score = {"direction": "neutral", "weighted_score": 0.0, "article_count": 0, "score_component": 0}

        return {
            "news_direction": score["direction"],
            "news_weighted_score": score["weighted_score"],
            "news_article_count": score["article_count"],
            "news_score_component": score["score_component"],
        }


def _rolling_vol_percentile(returns: pd.Series, window: int = 20, lookback: int = 252) -> float:
    """Return the fraction of prior `lookback` rolling-vol observations below the current one."""
    if len(returns) < window + lookback:
        return 0.5
    current_vol = returns.iloc[-window:].std() * (252 ** 0.5)
    prior_vols = [
        returns.iloc[i - window : i].std() * (252 ** 0.5)
        for i in range(window, len(returns) - window)
    ]
    if not prior_vols:
        return 0.5
    return sum(v < current_vol for v in prior_vols) / len(prior_vols)
