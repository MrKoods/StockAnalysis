"""
Tests for news_layer.py's direction-mirroring — no prior coverage existed for
count_independent_cluster's or theme_alignment_modifier's bearish paths, even
though both were fixed (Signal Integrity Audit findings B.3/B.4). Added while
building the direction-parity registry/CI check (2026-08-19).
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import swing_model.news_layer as news_layer
from swing_model.news_layer import compute_news_score, count_independent_cluster
from shared.utils.narrative_tracker import theme_alignment_modifier


def _article(sentiment_label, domain):
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_domain": domain,
        "overall_sentiment_label": sentiment_label,
    }


class TestConfigWiredNewsParams:
    """Tier B batch 2 (2026-08-19): decay_halflife_hours/decay_zero_at_days/
    cluster_window_days now read from config instead of being hardcoded —
    confirm compute_news_score actually threads a non-default cfg value
    through to the underlying functions, not just that the defaults work."""

    def test_cluster_window_days_threaded_from_cfg(self):
        seen = {}
        real = news_layer.count_independent_cluster

        def spy(*args, **kwargs):
            seen["window_days"] = kwargs.get("window_days")
            return real(*args, **kwargs)

        with patch.object(news_layer, "count_independent_cluster", side_effect=spy):
            compute_news_score([], [], "NVDA", cfg={"news": {"cluster_window_days": 7}})
        assert seen["window_days"] == 7

    def test_decay_params_threaded_from_cfg(self):
        seen = []
        real = news_layer.news_decay_weight

        def spy(*args, **kwargs):
            seen.append((kwargs.get("halflife_hours"), kwargs.get("zero_at_days")))
            return real(*args, **kwargs)

        av_articles = [{
            "title": "NVDA earnings beat expectations",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "source_domain": "reuters.com",
            "overall_sentiment_label": "bullish",
        }]
        with patch.object(news_layer, "news_decay_weight", side_effect=spy):
            compute_news_score(
                av_articles, [], "NVDA",
                cfg={"news": {"decay_halflife_hours": 48.0, "decay_zero_at_days": 10.0}},
            )
        assert seen  # at least one decay call happened
        assert all(call == (48.0, 10.0) for call in seen)


class TestCountIndependentClusterDirection:
    def test_bullish_direction_counts_bullish_articles(self):
        articles = [
            _article("bullish", "a.com"),
            _article("bullish", "b.com"),
            _article("bearish", "c.com"),
        ]
        assert count_independent_cluster(articles, "NVDA", direction="bullish") == 2

    def test_bearish_direction_counts_bearish_articles_not_bullish(self):
        # Previously returned max(bull_count, bear_count) regardless of
        # direction — a bearish candidate would wrongly get full clustering
        # credit off a cluster of bullish-leaning articles that actually
        # oppose its own thesis.
        articles = [
            _article("bullish", "a.com"),
            _article("bullish", "b.com"),
            _article("bearish", "c.com"),
        ]
        assert count_independent_cluster(articles, "NVDA", direction="bearish") == 1

    def test_bearish_cluster_scores_full_credit_for_bearish_direction(self):
        articles = [
            _article("bearish", "a.com"),
            _article("bearish", "b.com"),
            _article("bullish", "c.com"),
        ]
        assert count_independent_cluster(articles, "NVDA", direction="bearish") == 2


class TestThemeAlignmentModifierBearishMirror:
    def test_supply_chain_theme_flips_sign_for_bearish(self):
        # Bullish: supply-chain issues are adverse (-0.5). Bearish: the same
        # narrative CONFIRMS the bearish thesis — mirrored sign, not neutral.
        assert theme_alignment_modifier("supply_chain", "bullish", "NVDA") == -0.5
        assert theme_alignment_modifier("supply_chain", "bearish", "NVDA") == 0.5

    def test_memory_cycle_theme_flips_sign_for_mu(self):
        assert theme_alignment_modifier("memory_cycle", "bullish", "MU") == 0.5
        assert theme_alignment_modifier("memory_cycle", "bearish", "MU") == -0.5

    def test_memory_cycle_theme_neutral_for_non_mu_both_directions(self):
        assert theme_alignment_modifier("memory_cycle", "bullish", "NVDA") == 0.0
        assert theme_alignment_modifier("memory_cycle", "bearish", "NVDA") == 0.0


class TestAvTickerSentimentMR1:
    """MR-1/MR-2 (2026-08 API audit): when an Alpha Vantage article carries a
    per-ticker sentiment_score + relevance_score, the News layer uses that
    scored value instead of keyword-matching the headline — and the article
    counts for the ticker even if the alias-keyword matcher misses it."""

    def _av_article(self, ticker, score, relevance, title="Some macro headline"):
        # Timestamp relative to "now", not a fixed literal — news_layer's decay
        # weight zeroes out (and excludes) an article past decay_zero_at_days
        # (5.0 by default), which a hardcoded past date silently drifts into as
        # real calendar time passes (broke CI 2026-09-02: an article dated
        # 2026-08-27 was still fresh when this test was written, and 6 days
        # stale — fully decayed out — five days later, with no code change).
        ts = (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat()
        return {
            "title": title, "timestamp_utc": ts,
            "source": "Reuters", "source_domain": "reuters.com",
            "overall_sentiment_score": 0.0, "overall_sentiment_label": "Neutral",
            "ticker_sentiment": [
                {"ticker": ticker, "relevance_score": str(relevance),
                 "ticker_sentiment_score": str(score), "ticker_sentiment_label": "x"}
            ],
        }

    def test_av_sentiment_used_when_headline_has_no_ticker_name(self):
        # Headline never says "Zions" — the keyword matcher would score this 0,
        # but AV says it's relevant and bearish.
        art = self._av_article("ZION", score=-0.4, relevance=0.6,
                               title="Regional lenders slump on deposit-flight fears")
        out = compute_news_score([art], [], "ZION", direction="bullish")
        assert out["relevant_article_count"] == 1
        assert out["data_quality"] == "complete"
        # bearish AV sentiment opposes a bullish thesis -> low credibility score
        assert out["credibility_weighted_score"] < 3.0

    def test_low_relevance_av_article_is_excluded(self):
        art = self._av_article("ZION", score=0.5, relevance=0.02)
        out = compute_news_score([art], [], "ZION")
        assert out["relevant_article_count"] == 0

    def test_bullish_av_sentiment_scores_high_for_bullish_thesis(self):
        art = self._av_article("NVDA", score=0.6, relevance=0.9,
                               title="Nvidia demand outlook raised across the Street")
        out = compute_news_score([art], [], "NVDA", direction="bullish")
        assert out["credibility_weighted_score"] > 3.0
