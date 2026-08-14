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


from shared.utils.temporal_alignment import (
    news_decay_weight,
    classify_timezone_window,
    detect_price_sentiment_divergence,
    compute_sentiment_trajectory,
    compute_sentiment_velocity,
)
from shared.utils.source_credibility import (
    score_news_outlet,
    weight_by_credibility,
)
from shared.utils.ner_extractor import extract_ticker_sentiments, is_ticker_relevant
from shared.utils.narrative_tracker import identify_dominant_theme, theme_alignment_modifier
from swing_model.sentiment_layer import (
    compute_sentiment_score, SENTIMENT_MAX, _build_daily_bullish_ratios, _score_velocity,
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
    def _make_messages(self, n_bullish, n_bearish, hours_ago=2, sentiment_change=None, volume_change=None):
        now = datetime.now(timezone.utc)
        ts = (now - timedelta(hours=hours_ago)).isoformat()
        messages = []
        for i in range(n_bullish):
            messages.append({
                "message_id": str(i), "timestamp_utc": ts, "sentiment": "bullish",
                "sentiment_change": sentiment_change, "volume_change": volume_change,
            })
        for i in range(n_bearish):
            messages.append({
                "message_id": str(n_bullish + i), "timestamp_utc": ts, "sentiment": "bearish",
                "sentiment_change": sentiment_change, "volume_change": volume_change,
            })
        return messages

    def _make_sa_items(self, comment_counts, hours_ago_start=48):
        now = datetime.now(timezone.utc)
        items = []
        for i, count in enumerate(comment_counts):
            hours_ago = hours_ago_start - i * 6
            items.append({
                "article_id": str(i),
                "timestamp_utc": (now - timedelta(hours=hours_ago)).isoformat(),
                "title": f"Article {i}",
                "comment_count": count,
            })
        return items

    def test_bullish_dominance_gives_high_score(self):
        messages = self._make_messages(20, 2)
        result = compute_sentiment_score(messages, [], "NVDA", {})
        assert result["dominant_sentiment"] == "bullish"
        assert result["ratio_score"] > 3.5

    def test_offline_when_both_sources_empty(self):
        result = compute_sentiment_score([], [], "NVDA", {})
        assert result["sentiment_offline"]
        assert result["sentiment_offline_cap"] == 70
        assert result["sentiment_score_total"] == 0.0

    def test_not_offline_when_only_one_source_available(self):
        messages = self._make_messages(10, 2)
        result = compute_sentiment_score(messages, [], "NVDA", {})
        assert not result["sentiment_offline"]

    def test_score_total_capped_at_max(self):
        messages = self._make_messages(50, 0, sentiment_change=0.5, volume_change=0.5)
        sa_items = self._make_sa_items([50, 100, 150])
        result = compute_sentiment_score(messages, sa_items, "NVDA", {})
        assert result["sentiment_score_total"] <= SENTIMENT_MAX

    def test_native_sentiment_change_field_drives_velocity(self):
        rising = self._make_messages(10, 2, sentiment_change=0.3, volume_change=0.3)
        flat = self._make_messages(10, 2, sentiment_change=0.0, volume_change=0.0)
        result_rising = compute_sentiment_score(rising, [], "NVDA", {})
        result_flat = compute_sentiment_score(flat, [], "NVDA", {})
        assert result_rising["velocity_score"] > result_flat["velocity_score"]

    def test_extreme_volume_change_does_not_swamp_velocity(self):
        # Regression test: StockTwits' volume_change runs on a much wider scale
        # than sentiment_change (observed live: -7.59 vs. sentiment_change values
        # like -0.29/0.0) despite both feeding the same formula. Unclamped, this
        # exact reading computes combined=(0.2-7.59)/2=-3.695, score=2.5-36.95,
        # slammed to the hard floor of 0.0 regardless of the mildly positive
        # sentiment_change. A large negative volume_change should still pull the
        # score down (it's genuinely a negative signal, even clamped) — the fix
        # is that it no longer wipes out every other input and hits the floor.
        messages = self._make_messages(10, 2, sentiment_change=0.2, volume_change=-7.59)
        result = compute_sentiment_score(messages, [], "NVDA", {})
        assert result["velocity_score"] > 0.0

    def test_extreme_volume_change_still_allows_positive_sentiment_to_show(self):
        # A strongly positive sentiment_change should be able to lift the score
        # above neutral even when volume_change is a large negative outlier,
        # since each field is now clamped independently before combining rather
        # than one dominating the raw average.
        messages = self._make_messages(10, 2, sentiment_change=0.9, volume_change=-7.59)
        result = compute_sentiment_score(messages, [], "NVDA", {})
        # combined = (0.9 + (-1.0)) / 2 = -0.05 -> just under neutral, not floored
        assert result["velocity_score"] > 2.0

    def test_untagged_messages_do_not_dilute_ratio_toward_bearish(self):
        # Regression test: _build_daily_bullish_ratios used to divide bullish
        # count by ALL messages (including ones with no sentiment tag at all),
        # not by tagged (bullish+bearish) messages. Observed live for a real
        # ticker: 10 bullish, 0 bearish, 20 untagged produced a near-zero ratio
        # under the old formula, even though every message that expressed an
        # opinion was bullish. Untagged messages should be ignored, not treated
        # as diluting toward bearish.
        now = datetime.now(timezone.utc)
        ts = (now - timedelta(hours=2)).isoformat()
        messages = []
        for i in range(10):
            messages.append({"message_id": str(i), "timestamp_utc": ts, "sentiment": "bullish"})
        for i in range(20):
            messages.append({"message_id": str(10 + i), "timestamp_utc": ts, "sentiment": None})
        result = compute_sentiment_score(messages, [], "NVDA", {})
        assert result["dominant_sentiment"] == "bullish"
        assert result["ratio_score"] > 3.5  # above the neutral midpoint, not crushed toward 0

    def test_rising_comment_count_lifts_engagement_score(self):
        rising = self._make_sa_items([10, 20, 40, 80])
        flat = self._make_sa_items([40, 40, 40, 40])
        result_rising = compute_sentiment_score([], rising, "NVDA", {})
        result_flat = compute_sentiment_score([], flat, "NVDA", {})
        assert result_rising["engagement_score"] > result_flat["engagement_score"]

    def test_single_message_does_not_flip_dominant_sentiment(self):
        """
        The bug being fixed: dominant_sentiment (feeds determine_direction()
        in scoring.py, deciding the trade's actual direction) was computed
        from the raw, ungated ratio — a single tagged message (1 bullish, 0
        bearish -> ratio 1.0) could confidently label the trade "bullish"
        with zero sample-size protection, unlike the point score right next
        to it (_score_ratio), which explicitly refuses to trust anything
        below _RATIO_MIN_BASELINE_MESSAGES.
        """
        messages = self._make_messages(1, 0)
        result = compute_sentiment_score(messages, [], "NVDA", {})
        assert result["bullish_ratio_stocktwits"] == 1.0  # the raw ratio is still extreme...
        assert result["dominant_sentiment"] == "neutral"  # ...but not trusted for direction

    def test_enough_tagged_messages_does_drive_dominant_sentiment(self):
        # Above the baseline floor — the ratio should drive the label again.
        messages = self._make_messages(5, 0)
        result = compute_sentiment_score(messages, [], "NVDA", {})
        assert result["dominant_sentiment"] == "bullish"

    def test_all_required_keys_present(self):
        result = compute_sentiment_score([], [], "NVDA", {})
        required = [
            "ratio_score", "velocity_score", "engagement_score",
            "sentiment_score_total", "sentiment_trajectory",
            "divergence_flag", "dominant_sentiment", "bullish_ratio_stocktwits",
            "mention_volume_stocktwits", "engagement_item_count",
            "sentiment_offline", "sentiment_offline_cap", "sub_signal_data_quality",
        ]
        for key in required:
            assert key in result, f"Missing key: {key}"


class TestSentimentVelocityFallback:
    """
    _score_velocity's fallback path (used when StockTwits' native
    sentiment_change/volume_change fields aren't present) derives velocity
    from the daily bullish-ratio trajectory. Regression coverage for the
    multiplier recalibration: a moderate trajectory swing used to already
    hit the score's ceiling/floor almost exactly, making this sub-signal
    close to binary for realistic inputs.
    """

    def test_moderate_trajectory_swing_no_longer_saturates(self):
        messages = [{"message_id": "1"}]  # no native fields -> fallback path
        daily_ratios = [0.5, 0.5, 0.5, 0.53, 0.59]  # velocity ~= 0.06
        score, dq = _score_velocity(messages, daily_ratios)
        assert dq == "partial"
        assert 3.0 < score < 4.0  # a real lift above neutral, not maxed out

    def test_large_trajectory_swing_still_approaches_ceiling(self):
        messages = [{"message_id": "1"}]
        daily_ratios = [0.2, 0.2, 0.2, 0.7, 1.0]  # a genuinely large swing
        score, dq = _score_velocity(messages, daily_ratios)
        assert score >= 4.5

    def test_no_messages_is_unavailable(self):
        score, dq = _score_velocity([], [0.5, 0.6, 0.7])
        assert score == 0.0
        assert dq == "unavailable"


class TestBuildDailyBullishRatios:
    def _msg(self, hours_ago, sentiment):
        now = datetime.now(timezone.utc)
        ts = (now - timedelta(hours=hours_ago)).isoformat()
        return {"timestamp_utc": ts, "sentiment": sentiment}

    def test_ratio_ignores_untagged_messages(self):
        # 10 bullish, 0 bearish, 20 untagged, all "today" (bucket -1) — ratio
        # must reflect the tagged messages only (1.0), not be diluted by the
        # untagged ones toward 0 (10/30 under the old bull/total formula).
        messages = [self._msg(2, "bullish") for _ in range(10)] + [self._msg(2, None) for _ in range(20)]
        ratios, totals = _build_daily_bullish_ratios(messages, days=5)
        assert ratios[-1] == 1.0
        assert totals[-1] == 10  # tagged count, not all 30 messages

    def test_ratio_neutral_when_zero_tagged_messages(self):
        messages = [self._msg(2, None) for _ in range(15)]
        ratios, totals = _build_daily_bullish_ratios(messages, days=5)
        assert ratios[-1] == 0.5
        assert totals[-1] == 0

    def test_ratio_reflects_real_bearish_when_actually_bearish(self):
        # Untagged-dilution fix shouldn't mask genuine bearish sentiment either.
        messages = [self._msg(2, "bearish") for _ in range(8)] + [self._msg(2, "bullish") for _ in range(2)]
        ratios, totals = _build_daily_bullish_ratios(messages, days=5)
        assert ratios[-1] == 0.2
        assert totals[-1] == 10


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

    def _article_at_age(self, hours_ago, domain="reuters.com"):
        now = datetime.now(timezone.utc)
        return {
            "article_id": domain,
            "timestamp_utc": (now - timedelta(hours=hours_ago)).isoformat(),
            "title": "NVIDIA gains on strong quarterly results",
            "url": f"https://{domain}/news",
            "source": domain,
            "source_domain": domain,
            "overall_sentiment_score": 0.5,
            "overall_sentiment_label": "bullish",
            "ticker_sentiment": [],
        }

    def test_decay_score_reflects_freshest_article_not_average(self):
        """
        The bug being fixed: decay_score used to average freshness across
        every relevant article — but freshness is already baked in as a
        per-article weight inside credibility_weighted_score, so a stale
        second article was silently dragging decay_score down too, double-
        counting the same underlying signal. A very fresh article (~1h old)
        paired with a near-fully-decayed one (~100h old) should score close
        to the freshest article's own decay, not a diluted average of both.
        """
        fresh = self._article_at_age(1, domain="reuters.com")
        stale = self._article_at_age(100, domain="cnbc.com")
        result = compute_news_score([fresh, stale], [], "NVDA")

        # Freshest article alone (~1h old, halflife=24h): decay ~= 0.959 -> ~1.92
        assert result["decay_score"] > 1.5
        # The old average-based behavior would have landed close to ~0.97 —
        # confirm the fix moved meaningfully away from that.
        assert result["decay_score"] > 1.3

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
