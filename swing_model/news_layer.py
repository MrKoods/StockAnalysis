"""
NER-extracted ticker-specific news sentiment; source credibility weighting;
narrative theme tracking; news clustering; timezone-adjusted windows.
Output used by scoring.py for the News component (max 15 points).
"""

from datetime import datetime, timezone
from typing import Optional

from shared.utils.source_credibility import score_news_outlet
from shared.utils.ner_extractor import extract_ticker_sentiments, is_ticker_relevant
from shared.utils.narrative_tracker import identify_dominant_theme, theme_alignment_modifier
from shared.utils.temporal_alignment import news_decay_weight


def compute_news_score(
    alpha_vantage_articles: list[dict],
    yahoo_articles: list[dict],
    ticker: str,
    cfg: Optional[dict] = None,
) -> dict:
    """
    Compute the full news score bundle for a ticker.

    Scoring spec (sum = 15):
    - credibility_weighted_score:  0-6
    - theme_alignment_score:       0-4
    - clustering_score:            0-3
    - decay_score:                 0-2

    Returns dict with all fields required by scoring.py.
    """
    if cfg is None:
        cfg = {}

    now = datetime.now(timezone.utc)
    watchlist = cfg.get("watchlist", {}).get("tickers", ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"])

    all_articles = list(alpha_vantage_articles) + list(yahoo_articles)

    # ---------------------------------------------------------------------------
    # Filter to relevant articles only (NER confirms ticker mention)
    # ---------------------------------------------------------------------------
    relevant = []
    ner_results = []
    for art in all_articles:
        title = art.get("title", "")
        if is_ticker_relevant(title, ticker):
            ts = _parse_ts(art.get("timestamp_utc", ""))
            decay = news_decay_weight(ts, now_utc=now, halflife_hours=24.0, zero_at_days=5.0)
            if decay <= 0.0:
                continue  # Too old

            ner = extract_ticker_sentiments(title, watchlist)
            ticker_sentiment = ner.get(ticker)
            outlet_cred = score_news_outlet(art.get("source_domain", "") or art.get("publisher", ""))

            article_record = {
                **art,
                "_ts": ts,
                "_decay": decay,
                "_credibility": outlet_cred,
                "_ner_sentiment": ticker_sentiment,
            }
            relevant.append(article_record)
            ner_results.append({"ticker": ticker, "sentiment": ticker_sentiment, "title": title})

    # ---------------------------------------------------------------------------
    # 1. Credibility-weighted score (0-6)
    # ---------------------------------------------------------------------------
    credibility_weighted_score = _score_credibility_weighted(relevant, ticker)

    # ---------------------------------------------------------------------------
    # 2. Theme alignment score (0-4)
    # ---------------------------------------------------------------------------
    texts = [art.get("title", "") for art in relevant]
    theme_result = identify_dominant_theme(texts, ticker, lookback_days=5)
    dominant_theme = theme_result["dominant_theme"]

    # Determine dominant direction from NER
    bull_count = sum(1 for r in ner_results if r["sentiment"] == "bullish")
    bear_count = sum(1 for r in ner_results if r["sentiment"] == "bearish")
    trade_direction = "bullish" if bull_count >= bear_count else "bearish"

    alignment_val = theme_alignment_modifier(dominant_theme, trade_direction, ticker)
    # alignment_val in [-1, +1]; scale to [0, 4]. Zero when no theme / no articles.
    if dominant_theme == "none" or not relevant:
        theme_alignment_score = 0.0
    else:
        theme_alignment_score = min(4.0, max(0.0, (alignment_val + 1.0) * 2.0))

    # ---------------------------------------------------------------------------
    # 3. Clustering score (0-3)
    # ---------------------------------------------------------------------------
    cluster_count = count_independent_cluster(relevant, ticker, window_days=2)
    clustering_score = float(min(3, cluster_count))

    # ---------------------------------------------------------------------------
    # 4. Decay score (0-2): average freshness of relevant articles
    # ---------------------------------------------------------------------------
    if relevant:
        avg_decay = sum(art["_decay"] for art in relevant) / len(relevant)
        decay_score = round(avg_decay * 2.0, 2)
    else:
        decay_score = 0.0

    news_score_total = credibility_weighted_score + theme_alignment_score + clustering_score + decay_score

    return {
        # Sub-scores
        "credibility_weighted_score": round(credibility_weighted_score, 2),
        "theme_alignment_score": round(theme_alignment_score, 2),
        "clustering_score": round(clustering_score, 2),
        "decay_score": round(decay_score, 2),
        "news_score_total": round(min(15.0, news_score_total), 2),

        # Metadata
        "news_decay_weighted_score": round(credibility_weighted_score, 2),
        "dominant_narrative_theme": dominant_theme,
        "theme_momentum": theme_result.get("theme_momentum", "stable"),
        "news_cluster_count": cluster_count,
        "source_credibility_weighted_score": round(credibility_weighted_score, 2),
        "ner_sentiment_per_article": ner_results,
        "relevant_article_count": len(relevant),
        "total_article_count": len(all_articles),
    }


def score_news_credibility(
    articles: list[dict],
    ticker: str,
) -> float:
    """
    Compute credibility-weighted news sentiment score for a ticker (0-6).
    NER extracts ticker-specific sentiment from each article.
    Weight = source_credibility × decay_weight.
    """
    return _score_credibility_weighted(articles, ticker)


def count_independent_cluster(
    articles: list[dict],
    ticker: str,
    window_days: int = 2,
) -> int:
    """
    Count independent same-direction news articles in window_days (cap at 3).
    Independence requires: different source_domain.
    """
    if not articles:
        return 0

    now = datetime.now(timezone.utc)
    from datetime import timedelta
    cutoff = now - timedelta(days=window_days)

    seen_domains = set()
    directions = []

    for art in articles:
        ts = art.get("_ts") or _parse_ts(art.get("timestamp_utc", ""))
        if ts < cutoff:
            continue
        domain = art.get("source_domain", "") or art.get("publisher", "unknown")
        sentiment = art.get("_ner_sentiment") or art.get("overall_sentiment_label", "Neutral")

        if domain in seen_domains:
            continue
        seen_domains.add(domain)

        normalized = sentiment.lower() if isinstance(sentiment, str) else "neutral"
        if normalized in ("bullish", "positive", "somewhat-bullish"):
            directions.append("bullish")
        elif normalized in ("bearish", "negative", "somewhat-bearish"):
            directions.append("bearish")

    if not directions:
        return 0

    bull_count = directions.count("bullish")
    bear_count = directions.count("bearish")
    return min(3, max(bull_count, bear_count))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _score_credibility_weighted(articles: list[dict], ticker: str) -> float:
    """
    Credibility × decay weighted sentiment → scaled to [0, 6].
    Neutral articles score at 0.5 weight (halfway contribution).
    """
    if not articles:
        return 0.0

    weighted_sum = 0.0
    total_weight = 0.0

    for art in articles:
        cred = art.get("_credibility")
        if cred is None:
            cred = score_news_outlet(art.get("source_domain", "") or art.get("publisher", ""))
        decay = art.get("_decay", 1.0)
        w = cred * decay

        sentiment = art.get("_ner_sentiment") or art.get("overall_sentiment_label", "Neutral")
        normalized = str(sentiment).lower()
        if normalized in ("bullish", "positive", "somewhat-bullish"):
            sentiment_val = 1.0
        elif normalized in ("bearish", "negative", "somewhat-bearish"):
            sentiment_val = 0.0
        else:
            sentiment_val = 0.5

        weighted_sum += w * sentiment_val
        total_weight += w

    if total_weight == 0:
        return 0.0

    # weighted_avg in [0, 1]; scale to [0, 6]
    weighted_avg = weighted_sum / total_weight
    return round(weighted_avg * 6.0, 2)


def _parse_ts(ts_str: str) -> datetime:
    """Parse ISO timestamp string to UTC datetime."""
    if not ts_str:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return datetime.now(timezone.utc)
