import pytest

from swing_model.news_layer import compute_news_score, is_news_bullish, is_news_bearish


def _article(sentiment_score: float, relevance: float = 0.8) -> dict:
    return {
        "title": "Test article",
        "url": "https://example.com",
        "time_published": "20240101T120000",
        "overall_sentiment_score": sentiment_score,
        "ticker_sentiment_score": sentiment_score,
        "ticker_relevance_score": relevance,
    }


def test_no_articles_returns_neutral():
    result = compute_news_score([])
    assert result["direction"] == "neutral"
    assert result["score_component"] == 0
    assert result["article_count"] == 0


def test_strongly_bullish_articles():
    articles = [_article(0.5), _article(0.4), _article(0.6)]
    result = compute_news_score(articles)
    assert result["direction"] == "bullish"
    assert result["score_component"] == 1
    assert result["weighted_score"] > 0.15


def test_strongly_bearish_articles():
    articles = [_article(-0.5), _article(-0.4), _article(-0.3)]
    result = compute_news_score(articles)
    assert result["direction"] == "bearish"
    assert result["score_component"] == -1
    assert result["weighted_score"] < -0.15


def test_mixed_articles_return_neutral():
    # One bullish, one bearish of equal weight → near zero average
    articles = [_article(0.3), _article(-0.3)]
    result = compute_news_score(articles)
    assert result["direction"] == "neutral"
    assert result["score_component"] == 0


def test_relevance_weighting():
    # High relevance bearish article should dominate low relevance bullish one
    articles = [
        _article(0.5, relevance=0.1),   # bullish but barely relevant
        _article(-0.4, relevance=0.9),  # bearish and highly relevant
    ]
    result = compute_news_score(articles)
    assert result["direction"] == "bearish"


def test_is_news_bullish_helper():
    assert is_news_bullish([_article(0.5)]) is True
    assert is_news_bullish([_article(-0.5)]) is False


def test_is_news_bearish_helper():
    assert is_news_bearish([_article(-0.5)]) is True
    assert is_news_bearish([_article(0.5)]) is False


def test_swing_scorer_includes_news_component():
    from swing_model.scoring import SwingScorer

    config = {
        "scoring_thresholds": {
            "breakout_volume_multiplier": 1.5,
            "ma_short_period": 20,
            "ma_long_period": 50,
            "relative_strength_outperformance": 5,
            "sentiment_lookback_days": 5,
            "min_rr_ratio": 2.0,
        }
    }
    scorer = SwingScorer(config)

    base = {
        "close": 100.0, "ma_short": 95.0, "ma_long": 88.0,
        "above_ma_short": True, "above_ma_long": True, "ma_short_above_ma_long": True,
        "breakout_recent": True, "breakdown_recent": False,
        "rsi": 58.0, "atr": 2.5, "macd": 0.6, "macd_signal": 0.3, "macd_histogram": 0.3,
        "rs_vs_benchmark": 0.09, "rs_threshold": 0.05,
        "realized_vol_20d": 0.25, "vol_percentile_52w": 0.30,
        "sentiment_score_component": 1, "news_score_component": 0,
    }

    score_no_news = scorer.score({**base, "news_score_component": 0})
    score_bullish_news = scorer.score({**base, "news_score_component": 1})
    score_bearish_news = scorer.score({**base, "news_score_component": -1})

    assert score_bullish_news == score_no_news + 1
    assert score_bearish_news == score_no_news - 1
