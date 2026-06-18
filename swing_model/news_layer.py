"""
News sentiment scoring for the swing model.

Consumes a list of article dicts from NewsClient and produces a single
integer score component (+1 / 0 / -1) for the swing scorer.

Design rationale (from project scope):
  - News weight is 15-20 % of the composite score — it's the fastest signal
    but often already priced in and least validated in isolation.
  - Only articles with high ticker relevance (filtered upstream) count.
  - Multi-article weighted average avoids one headline dominating.
  - Threshold is intentionally conservative so a thin news day doesn't
    produce a spurious signal.
"""

_BULLISH_THRESHOLD = 0.15   # weighted avg score above this → bullish
_BEARISH_THRESHOLD = -0.15  # weighted avg score below this → bearish


def compute_news_score(articles: list[dict]) -> dict:
    """
    Aggregate recent news articles into a directional news score.

    Parameters
    ----------
    articles : list[dict]
        Each dict must contain 'ticker_sentiment_score' (float, -1 to 1)
        and 'ticker_relevance_score' (float, 0 to 1).

    Returns
    -------
    dict with keys:
        direction       : "bullish" | "bearish" | "neutral"
        weighted_score  : float — relevance-weighted avg sentiment (-1 to 1)
        article_count   : int
        score_component : int — +1 / 0 / -1 for the swing scorer
    """
    if not articles:
        return {
            "direction": "neutral",
            "weighted_score": 0.0,
            "article_count": 0,
            "score_component": 0,
        }

    total_weight = sum(a["ticker_relevance_score"] for a in articles)
    if total_weight == 0:
        weighted_avg = 0.0
    else:
        weighted_avg = (
            sum(a["ticker_sentiment_score"] * a["ticker_relevance_score"] for a in articles)
            / total_weight
        )

    if weighted_avg >= _BULLISH_THRESHOLD:
        direction = "bullish"
        component = 1
    elif weighted_avg <= _BEARISH_THRESHOLD:
        direction = "bearish"
        component = -1
    else:
        direction = "neutral"
        component = 0

    return {
        "direction": direction,
        "weighted_score": round(weighted_avg, 4),
        "article_count": len(articles),
        "score_component": component,
    }


def is_news_bullish(articles: list[dict]) -> bool:
    """Return True if recent news is net bullish for the ticker."""
    return compute_news_score(articles)["direction"] == "bullish"


def is_news_bearish(articles: list[dict]) -> bool:
    """Return True if recent news is net bearish for the ticker."""
    return compute_news_score(articles)["direction"] == "bearish"
