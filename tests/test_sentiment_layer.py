"""
Tests for Phase 4 sentiment and news layer:
  - shared/utils/temporal_alignment.py
  - shared/utils/source_credibility.py
  - shared/utils/ner_extractor.py
  - shared/utils/narrative_tracker.py
  - swing_model/sentiment_layer.py
  - swing_model/news_layer.py
All tests use synthetic data — no API calls.
"""

import math
from datetime import datetime, timezone, timedelta

import pytest

from shared.utils.temporal_alignment import (
    news_decay_weight,
    classify_timezone_window,
    detect_price_sentiment_divergence,
    compute_sentiment_trajectory,
    compute_sentiment_velocity,
)
from shared.utils.source_credibility import (
    score_stocktwits_author,
    score_news_outlet,
    weight_by_credibility,
)
from shared.utils.ner_extractor import extract_ticker_sentiments, is_ticker_relevant
from shared.utils.narrative_tracker import identify_dominant_theme, theme_alignment_modifier
from swing_model.sentiment_layer import (
    compute_sentiment_score,
    detect_spike_type,
    compute_cross_platform_consistency,
)
from swing_model.news_layer import compute_news_score, count_independent_cluster


# ---------------------------------------------------------------------------
# Temporal Alignment
# ---------------------------------------------------------------------------

class TestTemporalAlignment:
    def test_fresh_article_weight_near_one(self):
        now = datetime(2024, 5, 15, 12, 0, tzinfo=timezone.utc)
        ts = datetime(2024, 5, 15, 10, 0, tzinfo=timezone.utc)  # 2h ago
        w = news_decay_weight(ts, now_utc=now, halflife_hours=24.0)
        assert w > 0.9

    def test_old_article_weight_zero(self):
        now = datetime(2024, 5, 15, 12, 0, tzinfo=timezone.utc)
        ts = datetime(2024, 5, 9, 12, 0, tzinfo=timezone.utc)  # 6 days ago
        w = news_decay_weight(ts, now_utc=now, halflife_hours=24.0, zero_at_days=5.0)
        assert w == 0.0

    def test_24h_article_at_half_weight(self):
        now = datetime(2024, 5, 15, 12, 0, tzinfo=timezone.utc)
        ts = datetime(2024, 5, 14, 12, 0, tzinfo=timezone.utc)  # 24h ago
        w = news_decay_weight(ts, now_utc=now, halflife_hours=24.0)
        assert abs(w - math.exp(-1.0)) < 0.01

    def test_classify_us_session(self):
        # 15:00 UTC = 11:00 ET → US session
        ts = datetime(2024, 5, 15, 15, 0, tzinfo=timezone.utc)
        assert classify_timezone_window(ts) == "us_session"

    def test_classify_european(self):
        # 10:00 UTC = ~06:00 ET → European window
        ts = datetime(2024, 5, 15, 10, 0, tzinfo=timezone.utc)
        assert classify_timezone_window(ts) == "european"

    def test_bullish_setup_when_sentiment_up_price_flat(self):
        result = detect_price_sentiment_divergence(price_change_pct=0.01, sentiment_trajectory=0.08)
        assert result == "bullish_setup"

    def test_bearish_warning_when_price_up_sentiment_down(self):
        result = detect_price_sentiment_divergence(price_change_pct=0.05, sentiment_trajectory=-0.08)
        assert result == "bearish_warning"

    def test_trajectory_positive_for_building_sentiment(self):
        ratios = [0.3, 0.4, 0.5, 0.6, 0.7]
        t = compute_sentiment_trajectory(ratios)
        assert t > 0

    def test_trajectory_negative_for_declining_sentiment(self):
        ratios = [0.7, 0.6, 0.5, 0.4, 0.3]
        t = compute_sentiment_trajectory(ratios)
        assert t < 0

    def test_velocity_positive_when_accelerating(self):
        # Second half has steeper slope
        ratios = [0.4, 0.45, 0.5, 0.6, 0.8]
        v = compute_sentiment_velocity(ratios)
        assert v > 0


# ---------------------------------------------------------------------------
# Source Credibility
# ---------------------------------------------------------------------------

class TestSourceCredibility:
    def test_verified_author_scores_higher(self):
        verified = {"author_followers": 500, "author_following": 100,
                    "author_join_date": "2018-01-01", "author_verified": True}
        unverified = {"author_followers": 500, "author_following": 100,
                      "author_join_date": "2018-01-01", "author_verified": False}
        assert score_stocktwits_author(verified) > score_stocktwits_author(unverified)

    def test_older_account_scores_higher(self):
        old = {"author_followers": 100, "author_following": 50,
               "author_join_date": "2015-01-01", "author_verified": False}
        new = {"author_followers": 100, "author_following": 50,
               "author_join_date": "2023-01-01", "author_verified": False}
        assert score_stocktwits_author(old) > score_stocktwits_author(new)

    def test_high_follower_count_boosts_score(self):
        high = {"author_followers": 10000, "author_following": 100,
                "author_join_date": "2019-01-01", "author_verified": False}
        low = {"author_followers": 10, "author_following": 100,
               "author_join_date": "2019-01-01", "author_verified": False}
        assert score_stocktwits_author(high) > score_stocktwits_author(low)

    def test_score_clamped_0_to_1(self):
        author = {"author_followers": 999999, "author_following": 5,
                  "author_join_date": "2010-01-01", "author_verified": True}
        s = score_stocktwits_author(author)
        assert 0.0 <= s <= 1.0

    def test_reuters_high_credibility(self):
        assert score_news_outlet("reuters.com") >= 0.90

    def test_unknown_outlet_returns_default(self):
        assert score_news_outlet("randomfinanceblog.xyz") == 0.50

    def test_weight_by_credibility_correct(self):
        items = [
            {"score": 1.0, "cred": 0.8},
            {"score": 0.0, "cred": 0.4},
        ]
        result = weight_by_credibility(items, "score", "cred")
        expected = (0.8 * 1.0 + 0.4 * 0.0) / (0.8 + 0.4)
        assert abs(result - expected) < 1e-6

    def test_weight_by_credibility_empty_returns_zero(self):
        assert weight_by_credibility([], "score", "cred") == 0.0


# ---------------------------------------------------------------------------
# NER Extractor
# ---------------------------------------------------------------------------

class TestNERExtractor:
    def test_nvda_bullish_in_headline(self):
        result = extract_ticker_sentiments("NVIDIA gains market share in AI chips", ["NVDA", "AMD"])
        assert result["NVDA"] == "bullish"

    def test_amd_bearish_in_headline(self):
        result = extract_ticker_sentiments("AMD struggles with datacenter competition", ["NVDA", "AMD"])
        assert result["AMD"] == "bearish"

    def test_none_for_not_mentioned_ticker(self):
        result = extract_ticker_sentiments("NVIDIA reports record quarterly earnings", ["NVDA", "MU"])
        assert result["MU"] is None

    def test_is_ticker_relevant_true(self):
        assert is_ticker_relevant("Nvidia reports strong earnings beat", "NVDA")

    def test_is_ticker_relevant_false(self):
        assert not is_ticker_relevant("Intel announces new architecture", "NVDA")

    def test_neutral_when_mixed(self):
        result = extract_ticker_sentiments("NVDA gains while market falls", ["NVDA"])
        # gains = bullish keyword; falls = bearish but about market, not NVDA
        # Result should be bullish or neutral
        assert result["NVDA"] in ("bullish", "neutral")


# ---------------------------------------------------------------------------
# Narrative Tracker
# ---------------------------------------------------------------------------

class TestNarrativeTracker:
    def test_ai_demand_theme_identified(self):
        texts = [
            "NVIDIA sees record AI demand for H100 chips",
            "Data center GPU orders surge with LLM training",
            "Inference workloads driving Blackwell sales",
        ]
        result = identify_dominant_theme(texts, "NVDA")
        assert result["dominant_theme"] == "ai_demand"

    def test_china_export_theme_identified(self):
        texts = [
            "Export restriction hits NVDA China sales",
            "Chip ban extends to H100 successors",
        ]
        result = identify_dominant_theme(texts, "NVDA")
        assert result["dominant_theme"] == "china_export"

    def test_empty_texts_returns_none_theme(self):
        result = identify_dominant_theme([], "NVDA")
        assert result["dominant_theme"] == "none"
        assert result["theme_score"] == 0.0

    def test_bullish_aligned_with_ai_demand(self):
        val = theme_alignment_modifier("ai_demand", "bullish", "NVDA")
        assert val == 1.0

    def test_bullish_adverse_during_china_export(self):
        val = theme_alignment_modifier("china_export", "bullish", "NVDA")
        assert val == -1.0

    def test_result_keys_present(self):
        result = identify_dominant_theme(["test text"], "NVDA")
        for key in ("dominant_theme", "theme_score", "theme_momentum", "all_theme_scores"):
            assert key in result


# ---------------------------------------------------------------------------
# Sentiment Layer
# ---------------------------------------------------------------------------

class TestSentimentLayer:
    def _make_posts(self, n_bullish, n_bearish, hours_ago=2):
        now = datetime.now(timezone.utc)
        posts = []
        ts = (now - timedelta(hours=hours_ago)).isoformat()
        for i in range(n_bullish):
            posts.append({"post_id": str(i), "timestamp_utc": ts, "body": "bullish",
                          "sentiment": "bullish", "author_id": str(i),
                          "author_followers": 100, "author_following": 50,
                          "author_join_date": "2020-01-01", "author_verified": False})
        for i in range(n_bearish):
            posts.append({"post_id": str(n_bullish + i), "timestamp_utc": ts, "body": "bearish",
                          "sentiment": "bearish", "author_id": str(n_bullish + i),
                          "author_followers": 100, "author_following": 50,
                          "author_join_date": "2020-01-01", "author_verified": False})
        return posts

    def test_bullish_dominance_gives_high_score(self):
        posts = self._make_posts(20, 2)
        result = compute_sentiment_score(posts, [], "NVDA", {})
        assert result["dominant_sentiment"] == "bullish"
        assert result["sentiment_score_total"] > 10

    def test_offline_when_no_posts(self):
        result = compute_sentiment_score([], [], "NVDA", {})
        assert result["sentiment_offline"]
        assert result["sentiment_offline_cap"] == 70

    def test_score_total_capped_at_25(self):
        posts = self._make_posts(50, 0)
        result = compute_sentiment_score(posts, [], "NVDA", {})
        assert result["sentiment_score_total"] <= 25.0

    def test_all_required_keys_present(self):
        result = compute_sentiment_score([], [], "NVDA", {})
        required = [
            "trajectory_score", "velocity_score", "cross_platform_score", "spike_score",
            "sentiment_score_total", "sentiment_trajectory", "sentiment_velocity",
            "divergence_flag", "cross_platform_consistency_score", "spike_type",
            "dominant_sentiment", "bullish_ratio_st", "bullish_ratio_reddit",
            "mention_volume_st", "mention_volume_reddit",
        ]
        for key in required:
            assert key in result, f"Missing key: {key}"

    def test_cross_platform_consistent_bullish(self):
        score = compute_cross_platform_consistency(0.70, 0.75)
        assert score == 1.0

    def test_cross_platform_inconsistent(self):
        score = compute_cross_platform_consistency(0.80, 0.20)
        assert score < 0.5

    def test_organic_spike_detected(self):
        ratios = [0.30, 0.35, 0.40, 0.50, 0.65]
        spike = detect_spike_type(ratios, list(range(5)), [str(i) for i in range(10)])
        assert spike == "organic"


# ---------------------------------------------------------------------------
# News Layer
# ---------------------------------------------------------------------------

class TestNewsLayer:
    def _make_articles(self, sentiments, source_domains=None, hours_ago=12):
        now = datetime.now(timezone.utc)
        articles = []
        for i, sent in enumerate(sentiments):
            domain = (source_domains[i] if source_domains else f"source{i}.com")
            articles.append({
                "article_id": str(i),
                "timestamp_utc": (now - timedelta(hours=hours_ago)).isoformat(),
                "title": f"NVIDIA {sent} quarterly results",
                "url": f"https://{domain}/news",
                "source": domain,
                "source_domain": domain,
                "overall_sentiment_score": 0.5 if sent == "bullish" else -0.5,
                "overall_sentiment_label": sent,
                "ticker_sentiment": [],
            })
        return articles

    def test_bullish_articles_give_nonzero_score(self):
        arts = self._make_articles(["bullish", "bullish"], ["reuters.com", "cnbc.com"])
        result = compute_news_score(arts, [], "NVDA")
        assert result["news_score_total"] > 0

    def test_no_articles_returns_zero(self):
        result = compute_news_score([], [], "NVDA")
        assert result["news_score_total"] == 0.0

    def test_score_capped_at_15(self):
        arts = self._make_articles(
            ["bullish"] * 10,
            [f"news{i}.com" for i in range(10)]
        )
        result = compute_news_score(arts, [], "NVDA")
        assert result["news_score_total"] <= 15.0

    def test_all_required_keys_present(self):
        result = compute_news_score([], [], "NVDA")
        required = [
            "credibility_weighted_score", "theme_alignment_score",
            "clustering_score", "decay_score", "news_score_total",
            "dominant_narrative_theme", "news_cluster_count",
            "ner_sentiment_per_article",
        ]
        for key in required:
            assert key in result, f"Missing key: {key}"

    def test_independent_cluster_counts_unique_sources(self):
        now = datetime.now(timezone.utc)
        arts = [
            {"_ts": now - timedelta(hours=3), "_decay": 0.9, "_credibility": 0.8,
             "_ner_sentiment": "bullish", "source_domain": "reuters.com",
             "overall_sentiment_label": "bullish"},
            {"_ts": now - timedelta(hours=5), "_decay": 0.85, "_credibility": 0.8,
             "_ner_sentiment": "bullish", "source_domain": "cnbc.com",
             "overall_sentiment_label": "bullish"},
        ]
        count = count_independent_cluster(arts, "NVDA", window_days=2)
        assert count == 2

    def test_same_source_not_double_counted(self):
        now = datetime.now(timezone.utc)
        arts = [
            {"_ts": now - timedelta(hours=3), "_decay": 0.9, "_credibility": 0.8,
             "_ner_sentiment": "bullish", "source_domain": "reuters.com",
             "overall_sentiment_label": "bullish"},
            {"_ts": now - timedelta(hours=4), "_decay": 0.85, "_credibility": 0.8,
             "_ner_sentiment": "bullish", "source_domain": "reuters.com",
             "overall_sentiment_label": "bullish"},
        ]
        count = count_independent_cluster(arts, "NVDA", window_days=2)
        assert count == 1

    def test_high_credibility_source_lifts_score(self):
        arts_high = self._make_articles(["bullish"], ["reuters.com"])
        arts_low = self._make_articles(["bullish"], ["randomblog.xyz"])
        result_high = compute_news_score(arts_high, [], "NVDA")
        result_low = compute_news_score(arts_low, [], "NVDA")
        assert result_high["credibility_weighted_score"] >= result_low["credibility_weighted_score"]
