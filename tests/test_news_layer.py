"""
Tests for news_layer.py's direction-mirroring — no prior coverage existed for
count_independent_cluster's or theme_alignment_modifier's bearish paths, even
though both were fixed (Signal Integrity Audit findings B.3/B.4). Added while
building the direction-parity registry/CI check (2026-08-19).
"""

from datetime import datetime, timezone
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
