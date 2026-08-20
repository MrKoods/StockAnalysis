"""
Tests for swing_model/scoring.py.
Verifies the confidence scoring formula for the 5-category system:
  Technical 40 / Positioning 20 / Sentiment 15 / News 15 / Fundamental 10
  Modifier bounds and clamping 0-100
  High-vol regime cap at 70
"""

import pytest

from swing_model.scoring import (
    compute_confidence_score,
    compute_technical_sub_scores,
    compute_data_sufficiency,
    apply_high_vol_regime_cap,
    determine_direction,
    TECHNICAL_MAX,
    POSITIONING_MAX,
    SENTIMENT_MAX,
    NEWS_MAX,
    FUNDAMENTAL_MAX,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _zero_sent():
    return {"sentiment_score_total": 0.0, "dominant_sentiment": "neutral",
            "ratio_score": 0, "velocity_score": 0, "engagement_score": 0}


def _zero_news():
    return {"news_score_total": 0.0}


def _zero_positioning():
    return {"positioning_score_total": 0.0, "options_score": 0, "institutional_score": 0,
            "short_interest_score": 0, "insider_score": 0, "analyst_score": 0}


def _max_sent():
    return {"sentiment_score_total": 15.0, "dominant_sentiment": "bullish",
            "ratio_score": 7, "velocity_score": 5, "engagement_score": 3}


def _max_news():
    return {"news_score_total": 15.0,
            "credibility_weighted_score": 6, "theme_alignment_score": 4,
            "clustering_score": 3, "decay_score": 2}


def _max_positioning():
    return {"positioning_score_total": 20.0, "options_score": 6, "institutional_score": 5,
            "short_interest_score": 4, "insider_score": 3, "analyst_score": 2}


def _max_technical():
    """Inputs that produce breakout=8, trend=8, rs=8, rsi=8, vp=8 → total 40."""
    return {
        "breakout_volume_zscore": 3.0,
        "rs_zscore": 3.0,
        "rsi_14": 60.0,
        "breakout_confirmed": True,
        "trend_intact": True,
        "sma_20_above_sma_50": True,
        "price_above_sma_50": True,
        "macd_bullish": True,
    }


def _max_technical_bearish():
    """Bearish mirror of _max_technical() — breakout=8, trend=8, rs=8, rsi=8, vp=8 → total 40."""
    return {
        "breakout_volume_zscore": 3.0,
        "rs_zscore": -3.0,
        "rsi_14": 40.0,
        "breakdown_confirmed": True,
        "downtrend_intact": True,
        "sma_20_above_sma_50": False,
        "price_above_sma_50": False,
        "macd_bearish": True,
    }


# ---------------------------------------------------------------------------
# Technical sub-score tests
# ---------------------------------------------------------------------------

class TestTechnicalSubScores:
    def test_max_inputs_yield_40(self):
        sub = compute_technical_sub_scores(_max_technical(), volume_profile_score_override=8.0)
        assert sub["technical_total"] == pytest.approx(40.0)

    def test_each_sub_score_bounded_0_to_8(self):
        sub = compute_technical_sub_scores(_max_technical(), volume_profile_score_override=8.0)
        for key in ("breakout_score", "trend_score", "rs_score", "rsi_score", "volume_profile_score"):
            assert 0.0 <= sub[key] <= 8.0, f"{key} = {sub[key]} out of [0,8]"

    def test_zero_inputs_yield_low_score(self):
        zero = {"breakout_volume_zscore": -3.0, "rs_zscore": -3.0, "rsi_14": 20.0,
                "breakout_confirmed": False, "trend_intact": False,
                "sma_20_above_sma_50": False, "price_above_sma_50": False, "macd_bullish": False}
        sub = compute_technical_sub_scores(zero, volume_profile_score_override=0.0)
        assert sub["technical_total"] < 12  # Weak inputs → low score

    def test_breakout_capped_at_neutral_when_no_breakout(self):
        technical = {"breakout_volume_zscore": 3.0, "breakout_confirmed": False}
        sub = compute_technical_sub_scores(technical)
        assert sub["breakout_score"] <= 4.0

    def test_trend_score_8_when_trend_intact_and_macd_bullish(self):
        technical = {"trend_intact": True, "macd_bullish": True,
                     "sma_20_above_sma_50": True, "price_above_sma_50": True}
        sub = compute_technical_sub_scores(technical)
        assert sub["trend_score"] == 8.0

    def test_rsi_60_yields_max_rsi_score(self):
        sub = compute_technical_sub_scores({"rsi_14": 60.0})
        assert sub["rsi_score"] == 8.0

    def test_rsi_overbought_penalized(self):
        sub_normal = compute_technical_sub_scores({"rsi_14": 60.0})
        sub_overbought = compute_technical_sub_scores({"rsi_14": 85.0})
        assert sub_normal["rsi_score"] > sub_overbought["rsi_score"]

    def test_rs_zscore_positive_gives_high_rs_score(self):
        sub = compute_technical_sub_scores({"rs_zscore": 2.0})
        assert sub["rs_score"] > 6.0

    def test_rs_zscore_negative_gives_low_rs_score(self):
        sub = compute_technical_sub_scores({"rs_zscore": -2.0})
        assert sub["rs_score"] < 2.0

    def test_volume_profile_override_used(self):
        sub = compute_technical_sub_scores({}, volume_profile_score_override=6.0)
        assert sub["volume_profile_score"] == 6.0

    # -- Bearish direction (mirrors the bullish tests above) --

    def test_max_bearish_inputs_yield_40(self):
        sub = compute_technical_sub_scores(
            _max_technical_bearish(), volume_profile_score_override=8.0, direction="bearish"
        )
        assert sub["technical_total"] == pytest.approx(40.0)

    def test_each_bearish_sub_score_bounded_0_to_8(self):
        sub = compute_technical_sub_scores(
            _max_technical_bearish(), volume_profile_score_override=8.0, direction="bearish"
        )
        for key in ("breakout_score", "trend_score", "rs_score", "rsi_score", "volume_profile_score"):
            assert 0.0 <= sub[key] <= 8.0, f"{key} = {sub[key]} out of [0,8]"

    def test_bearish_breakout_capped_at_neutral_when_no_breakdown(self):
        technical = {"breakout_volume_zscore": 3.0, "breakdown_confirmed": False}
        sub = compute_technical_sub_scores(technical, direction="bearish")
        assert sub["breakout_score"] <= 4.0

    def test_bearish_trend_score_8_when_downtrend_intact_and_macd_bearish(self):
        technical = {"downtrend_intact": True, "macd_bearish": True,
                     "sma_20_above_sma_50": False, "price_above_sma_50": False}
        sub = compute_technical_sub_scores(technical, direction="bearish")
        assert sub["trend_score"] == 8.0

    def test_bearish_rsi_40_yields_max_rsi_score(self):
        # 100 - 40 = 60, inside the mirrored 50-70 sweet spot
        sub = compute_technical_sub_scores({"rsi_14": 40.0}, direction="bearish")
        assert sub["rsi_score"] == 8.0

    def test_bearish_rsi_overbought_penalized(self):
        # For bearish, a high (overbought) RSI is the unfavorable extreme, mirroring
        # test_rsi_overbought_penalized's low-oversold-RSI-is-unfavorable-for-bullish shape.
        sub_normal = compute_technical_sub_scores({"rsi_14": 40.0}, direction="bearish")
        sub_overbought = compute_technical_sub_scores({"rsi_14": 15.0}, direction="bearish")
        assert sub_normal["rsi_score"] > sub_overbought["rsi_score"]

    def test_bearish_rs_zscore_negative_gives_high_rs_score(self):
        # Underperformance confirms a bearish thesis, mirrors test_rs_zscore_positive_gives_high_rs_score
        sub = compute_technical_sub_scores({"rs_zscore": -2.0}, direction="bearish")
        assert sub["rs_score"] > 6.0

    def test_bearish_rs_zscore_positive_gives_low_rs_score(self):
        sub = compute_technical_sub_scores({"rs_zscore": 2.0}, direction="bearish")
        assert sub["rs_score"] < 2.0

    def test_bearish_uses_volume_profile_score_bearish_field(self):
        technical = {"volume_profile_score": 1.0, "volume_profile_score_bearish": 7.0}
        sub_bullish = compute_technical_sub_scores(technical, direction="bullish")
        sub_bearish = compute_technical_sub_scores(technical, direction="bearish")
        assert sub_bullish["volume_profile_score"] == 1.0
        assert sub_bearish["volume_profile_score"] == 7.0

    def test_bullish_default_unaffected_by_bearish_fields(self):
        # A ticker with strong bearish signals alongside neutral/absent bullish
        # ones should score the same on direction="bullish" as before this
        # feature existed — regression guard for the Phase 2 rewrite.
        sub = compute_technical_sub_scores(_max_technical(), volume_profile_score_override=8.0)
        assert sub["technical_total"] == pytest.approx(40.0)


# ---------------------------------------------------------------------------
# determine_direction tests
# ---------------------------------------------------------------------------

class TestDetermineDirection:
    def test_bullish_technical_and_sentiment_returns_bullish(self):
        technical = {"trend_intact": True, "breakout_confirmed": True}
        sentiment = {"dominant_sentiment": "bullish"}
        assert determine_direction(technical, sentiment) == "bullish"

    def test_bearish_technical_and_sentiment_returns_bearish_when_no_cfg(self):
        # cfg=None means "allow bearish" (backtesting/calibration callers) —
        # see determine_direction's own docstring.
        technical = {"downtrend_intact": True, "breakdown_confirmed": True}
        sentiment = {"dominant_sentiment": "bearish"}
        assert determine_direction(technical, sentiment) == "bearish"

    def test_bearish_defaults_to_bullish_when_flag_off(self):
        technical = {"downtrend_intact": True, "breakdown_confirmed": True}
        sentiment = {"dominant_sentiment": "bearish"}
        cfg = {"enable_bearish_signals": False}
        assert determine_direction(technical, sentiment, cfg) == "bullish"

    def test_bearish_defaults_to_bullish_when_flag_absent(self):
        technical = {"downtrend_intact": True, "breakdown_confirmed": True}
        sentiment = {"dominant_sentiment": "bearish"}
        assert determine_direction(technical, sentiment, cfg={}) == "bullish"

    def test_bearish_returned_when_flag_explicitly_enabled(self):
        technical = {"downtrend_intact": True, "breakdown_confirmed": True}
        sentiment = {"dominant_sentiment": "bearish"}
        cfg = {"enable_bearish_signals": True}
        assert determine_direction(technical, sentiment, cfg) == "bearish"

    def test_bearish_with_neutral_sentiment_allowed(self):
        # Mirrors the bullish branch's own dom_sentiment in ("bullish", "neutral") symmetry.
        technical = {"downtrend_intact": True, "breakdown_confirmed": True}
        sentiment = {"dominant_sentiment": "neutral"}
        cfg = {"enable_bearish_signals": True}
        assert determine_direction(technical, sentiment, cfg) == "bearish"

    def test_no_technical_confirmation_defaults_bullish(self):
        technical = {"trend_intact": False, "breakout_confirmed": False,
                     "downtrend_intact": False, "breakdown_confirmed": False}
        sentiment = {"dominant_sentiment": "neutral"}
        cfg = {"enable_bearish_signals": True}
        assert determine_direction(technical, sentiment, cfg) == "bullish"

    def test_conflicting_bullish_technical_bearish_sentiment_defaults_bullish(self):
        # Bullish technical always wins the first branch, regardless of the flag.
        technical = {"trend_intact": True, "breakout_confirmed": True}
        sentiment = {"dominant_sentiment": "bearish"}
        cfg = {"enable_bearish_signals": True}
        assert determine_direction(technical, sentiment, cfg) == "bullish"


# ---------------------------------------------------------------------------
# Base score tests
# ---------------------------------------------------------------------------

class TestBaseScore:
    def test_max_base_score_is_100(self):
        result = compute_confidence_score(
            technical=_max_technical(),
            positioning=_max_positioning(),
            sentiment=_max_sent(),
            news=_max_news(),
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=0, seasonality_modifier=0,
            macro_modifier=0,
            volume_profile_score=8.0,
            fundamental={"fundamental_score": 15.0, "data_quality": "complete"},
        )
        assert result["base_score"] == pytest.approx(100.0)

    def test_zero_inputs_yield_low_base(self):
        zero_tech = {"breakout_volume_zscore": -3.0, "rs_zscore": -3.0, "rsi_14": 20.0,
                     "breakout_confirmed": False, "trend_intact": False,
                     "sma_20_above_sma_50": False, "price_above_sma_50": False, "macd_bullish": False}
        result = compute_confidence_score(
            technical=zero_tech, positioning=_zero_positioning(), sentiment=_zero_sent(), news=_zero_news(),
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=0, seasonality_modifier=0,
            macro_modifier=0, volume_profile_score=0.0,
        )
        assert result["base_score"] < 20.0  # Some floor due to RSI/trend defaults

    def test_base_score_equals_sum_of_categories(self):
        result = compute_confidence_score(
            technical=_max_technical(),
            positioning=_max_positioning(),
            sentiment=_max_sent(),
            news=_max_news(),
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=0, seasonality_modifier=0,
            macro_modifier=0, volume_profile_score=8.0,
        )
        expected = (
            result["technical_total"] + result["positioning_total"]
            + result["sentiment_total"] + result["news_total"]
        )
        assert result["base_score"] == pytest.approx(expected, abs=0.01)

    def test_positioning_none_defaults_to_zero_contribution(self):
        result = compute_confidence_score(
            technical=_max_technical(), positioning=None, sentiment=_max_sent(), news=_max_news(),
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=0, seasonality_modifier=0, macro_modifier=0,
            volume_profile_score=8.0,
        )
        assert result["positioning_total"] == 0.0

    def test_fundamental_rescaled_from_internal_15_scale_to_10(self):
        max_fundamental = {"fundamental_score": 15.0, "data_quality": "complete"}
        result = compute_confidence_score(
            technical={}, positioning=_zero_positioning(), sentiment=_zero_sent(), news=_zero_news(),
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=0, seasonality_modifier=0, macro_modifier=0,
            fundamental=max_fundamental,
        )
        assert result["fundamental_score"] == pytest.approx(FUNDAMENTAL_MAX)


class TestScoringWeightsConfigurable:
    """Tier B batch 3 (2026-08-19): the 5 category maximums now read from
    config.scoring_weights instead of bare module constants — confirm a
    non-default value actually changes behavior, not just that the default
    (matching the module constants) still works."""

    def _kwargs(self, cfg=None):
        return dict(
            technical=_max_technical(), positioning=_max_positioning(),
            sentiment=_max_sent(), news=_max_news(),
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=0, seasonality_modifier=0, macro_modifier=0,
            volume_profile_score=8.0,
            fundamental={"fundamental_score": 15.0, "data_quality": "complete"},
            cfg=cfg,
        )

    def test_positioning_max_configurable(self):
        default_result = compute_confidence_score(**self._kwargs())
        assert default_result["positioning_total"] == POSITIONING_MAX

        narrower_cfg = {"scoring_weights": {"positioning_max": 10.0}}
        custom_result = compute_confidence_score(**self._kwargs(cfg=narrower_cfg))
        assert custom_result["positioning_total"] == 10.0  # clamped down, not the full 20

    def test_sentiment_max_configurable(self):
        default_result = compute_confidence_score(**self._kwargs())
        assert default_result["sentiment_total"] == SENTIMENT_MAX

        narrower_cfg = {"scoring_weights": {"sentiment_max": 8.0}}
        custom_result = compute_confidence_score(**self._kwargs(cfg=narrower_cfg))
        assert custom_result["sentiment_total"] == 8.0

    def test_news_max_configurable(self):
        default_result = compute_confidence_score(**self._kwargs())
        assert default_result["news_total"] == NEWS_MAX

        narrower_cfg = {"scoring_weights": {"news_max": 8.0}}
        custom_result = compute_confidence_score(**self._kwargs(cfg=narrower_cfg))
        assert custom_result["news_total"] == 8.0

    def test_technical_max_configurable(self):
        default_result = compute_confidence_score(**self._kwargs())
        assert default_result["technical_total"] == TECHNICAL_MAX

        narrower_cfg = {"scoring_weights": {"technical_max": 20.0}}
        custom_result = compute_confidence_score(**self._kwargs(cfg=narrower_cfg))
        assert custom_result["technical_total"] == 20.0

    def test_fundamental_max_configurable_and_rescale_ratio_still_correct(self):
        """fundamental_max is the numerator of a rescale ratio against
        FUNDAMENTAL_INTERNAL_MAX (15, fundamental_layer.py's own fixed
        internal scale, NOT config-driven) — confirm retuning the numerator
        alone still produces a correctly-proportioned contribution."""
        default_result = compute_confidence_score(**self._kwargs())
        assert default_result["fundamental_score"] == pytest.approx(FUNDAMENTAL_MAX)

        doubled_cfg = {"scoring_weights": {"fundamental_max": 20.0}}
        custom_result = compute_confidence_score(**self._kwargs(cfg=doubled_cfg))
        # Raw fundamental_score=15 (max of the internal -15..+15 scale) rescaled
        # by (20/15) -> 20.0, not the default (10/15) -> 10.0.
        assert custom_result["fundamental_score"] == pytest.approx(20.0)

    def test_technical_sub_scores_clamp_uses_same_config_value(self):
        """compute_technical_sub_scores resolves its own copy of
        technical_max from the same cfg — must agree with
        compute_confidence_score's, not silently diverge."""
        narrower_cfg = {"scoring_weights": {"technical_max": 20.0}}
        tech_sub = compute_technical_sub_scores(_max_technical(), cfg=narrower_cfg, volume_profile_score_override=8.0)
        assert tech_sub["technical_total"] == 20.0

    def test_no_cfg_preserves_hardcoded_defaults(self):
        """cfg=None (the default) must still return the old hardcoded caps —
        callers that don't pass cfg shouldn't change behavior."""
        result = compute_confidence_score(**self._kwargs(cfg=None))
        assert result["positioning_total"] == POSITIONING_MAX
        assert result["sentiment_total"] == SENTIMENT_MAX
        assert result["news_total"] == NEWS_MAX
        assert result["technical_total"] == TECHNICAL_MAX


# ---------------------------------------------------------------------------
# Fundamental staleness discount
# ---------------------------------------------------------------------------

class TestFundamentalStaleness:
    def _score_with_fundamental(self, fundamental, as_of_date=None):
        return compute_confidence_score(
            technical={}, positioning=_zero_positioning(), sentiment=_zero_sent(), news=_zero_news(),
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=0, seasonality_modifier=0, macro_modifier=0,
            fundamental=fundamental, as_of_date=as_of_date,
        )

    def test_missing_data_as_of_gets_full_weight(self):
        result = self._score_with_fundamental({"fundamental_score": 15.0, "data_quality": "complete"})
        assert result["fundamental_staleness_weight"] == pytest.approx(1.0)
        assert result["fundamental_score"] == pytest.approx(FUNDAMENTAL_MAX)

    def test_same_day_data_gets_full_weight(self):
        import datetime
        today = datetime.date(2026, 8, 5)
        result = self._score_with_fundamental(
            {"fundamental_score": 15.0, "data_quality": "complete", "data_as_of": "2026-08-05"},
            as_of_date=today,
        )
        assert result["fundamental_staleness_weight"] == pytest.approx(1.0)
        assert result["fundamental_score"] == pytest.approx(FUNDAMENTAL_MAX)

    def test_within_full_weight_window_no_discount(self):
        import datetime
        today = datetime.date(2026, 8, 5)
        result = self._score_with_fundamental(
            {"fundamental_score": 15.0, "data_quality": "complete", "data_as_of": "2026-08-03"},  # 2 days old
            as_of_date=today,
        )
        assert result["fundamental_staleness_weight"] == pytest.approx(1.0)

    def test_beyond_floor_days_clamps_at_floor_not_zero(self):
        import datetime
        today = datetime.date(2026, 8, 5)
        result = self._score_with_fundamental(
            {"fundamental_score": 15.0, "data_quality": "complete", "data_as_of": "2026-07-01"},  # 35 days old
            as_of_date=today,
        )
        assert result["fundamental_staleness_weight"] == pytest.approx(0.5)
        assert result["fundamental_score"] == pytest.approx(FUNDAMENTAL_MAX * 0.5)

    def test_linear_ramp_midpoint(self):
        import datetime
        # 3-day full-weight window, 15-day floor window -> midpoint age 9 days
        # should sit halfway between weight 1.0 and floor 0.5, i.e. 0.75.
        today = datetime.date(2026, 8, 12)
        result = self._score_with_fundamental(
            {"fundamental_score": 15.0, "data_quality": "complete", "data_as_of": "2026-08-03"},  # 9 days old
            as_of_date=today,
        )
        assert result["fundamental_staleness_weight"] == pytest.approx(0.75, abs=0.01)

    def test_matches_real_observed_staleness_e_g_tsm(self):
        # Mirrors an actual value seen in production scan logs: TSM's
        # fundamental data_as_of lagging 13 days behind a 2026-08-05 scan.
        import datetime
        today = datetime.date(2026, 8, 5)
        result = self._score_with_fundamental(
            {"fundamental_score": 15.0, "data_quality": "complete", "data_as_of": "2026-07-23"},
            as_of_date=today,
        )
        assert 0.5 <= result["fundamental_staleness_weight"] < 1.0
        assert result["fundamental_score"] < FUNDAMENTAL_MAX

    def test_unparseable_data_as_of_falls_back_to_full_weight(self):
        result = self._score_with_fundamental(
            {"fundamental_score": 15.0, "data_quality": "complete", "data_as_of": "not-a-date"},
        )
        assert result["fundamental_staleness_weight"] == pytest.approx(1.0)

    def test_negative_fundamental_contribution_also_discounted(self):
        import datetime
        today = datetime.date(2026, 8, 5)
        result = self._score_with_fundamental(
            {"fundamental_score": -15.0, "data_quality": "complete", "data_as_of": "2026-07-01"},
            as_of_date=today,
        )
        assert result["fundamental_score"] == pytest.approx(-FUNDAMENTAL_MAX * 0.5)


# ---------------------------------------------------------------------------
# Data-sufficiency proxy (heuristic, not a statistical CI)
# ---------------------------------------------------------------------------

class TestDataSufficiency:
    def _all_complete_positioning(self):
        return {"sub_signal_data_quality": {
            "options": "complete", "institutional": "complete",
            "short_interest": "complete", "insider": "complete", "analyst": "complete",
        }}

    def _all_complete_sentiment(self):
        return {"sub_signal_data_quality": {
            "ratio": "complete", "velocity": "complete", "engagement": "complete",
        }}

    def test_all_complete_gives_high_confidence(self):
        result = compute_data_sufficiency(
            self._all_complete_positioning(), self._all_complete_sentiment(),
            {"data_quality": "complete"},
        )
        assert result["data_confidence"] == "high"
        assert result["degraded_sub_signal_count"] == 0

    def test_fundamental_unavailable_alone_drops_to_medium(self):
        result = compute_data_sufficiency(
            self._all_complete_positioning(), self._all_complete_sentiment(),
            {"data_quality": "unavailable"},
        )
        assert result["degraded_sub_signal_count"] == 1
        assert result["data_confidence"] == "medium"

    def test_three_or_more_degraded_gives_low_confidence(self):
        positioning = self._all_complete_positioning()
        positioning["sub_signal_data_quality"]["options"] = "unavailable"
        positioning["sub_signal_data_quality"]["insider"] = "unavailable"
        result = compute_data_sufficiency(
            positioning, self._all_complete_sentiment(), {"data_quality": "unavailable"},
        )
        assert result["degraded_sub_signal_count"] == 3
        assert result["data_confidence"] == "low"

    def test_insufficient_baseline_counts_as_degraded(self):
        sentiment = self._all_complete_sentiment()
        sentiment["sub_signal_data_quality"]["ratio"] = "insufficient_baseline"
        result = compute_data_sufficiency(
            self._all_complete_positioning(), sentiment, {"data_quality": "complete"},
        )
        assert result["degraded_sub_signal_count"] == 1

    def test_missing_sub_signal_data_quality_only_counts_fundamental(self):
        result = compute_data_sufficiency({}, {}, {"data_quality": "complete"})
        assert result["total_sub_signals_checked"] == 1
        assert result["degraded_sub_signal_count"] == 0
        assert result["data_confidence"] == "high"

    def test_total_sub_signals_checked_counts_all_eight(self):
        result = compute_data_sufficiency(
            self._all_complete_positioning(), self._all_complete_sentiment(),
            {"data_quality": "complete"},
        )
        # 5 positioning + 3 sentiment + 1 fundamental = 9
        assert result["total_sub_signals_checked"] == 9

    def test_technical_data_quality_is_counted_when_supplied(self):
        """
        Technical previously reported no data-quality signal at all despite
        being the largest single scoring category (40 of 100 points) — a
        ticker with substitute (fallback) sma_50/macd values looked exactly
        as trustworthy as one with a full, real indicator set. technical is
        optional (default None) so existing callers that don't pass it are
        unaffected — see test_total_sub_signals_checked_counts_all_eight above.
        """
        technical = {"sub_signal_data_quality": {
            "sma_20": "complete", "sma_50": "partial", "atr": "complete", "macd": "complete",
        }}
        result = compute_data_sufficiency(
            self._all_complete_positioning(), self._all_complete_sentiment(),
            {"data_quality": "complete"}, technical,
        )
        # 5 positioning + 3 sentiment + 1 fundamental + 4 technical = 13
        assert result["total_sub_signals_checked"] == 13
        assert result["degraded_sub_signal_count"] == 1  # sma_50 alone

    def test_wired_into_compute_confidence_score_output(self):
        result = compute_confidence_score(
            technical=_max_technical(), positioning={"sub_signal_data_quality": {"options": "unavailable"}},
            sentiment=_zero_sent(), news=_zero_news(),
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=0, seasonality_modifier=0, macro_modifier=0,
            fundamental={"fundamental_score": 0.0, "data_quality": "unavailable"},
        )
        assert "data_confidence" in result
        assert "degraded_sub_signal_count" in result
        assert result["degraded_sub_signal_count"] >= 2  # options + fundamental at least


class TestCalibratedWinProbability:
    def _score(self, confidence_inputs, calibration=None):
        return compute_confidence_score(
            technical=confidence_inputs, positioning=_max_positioning(), sentiment=_max_sent(), news=_max_news(),
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=0, seasonality_modifier=0, macro_modifier=0,
            volume_profile_score=8.0, win_probability_calibration=calibration,
        )

    def test_no_calibration_falls_back_to_final_score_over_100(self):
        result = self._score(_max_technical())
        assert result["win_prob_calibrated"] is False
        assert result["calibrated_win_probability"] == pytest.approx(result["final_score"] / 100.0)

    def test_with_calibration_uses_real_curve_not_identity(self):
        calibration = [{"threshold": 50, "win_rate": 0.55}, {"threshold": 100, "win_rate": 0.62}]
        result = self._score(_max_technical(), calibration=calibration)
        assert result["win_prob_calibrated"] is True
        assert result["calibrated_win_probability"] != pytest.approx(result["final_score"] / 100.0)
        assert 0.55 <= result["calibrated_win_probability"] <= 0.62


# ---------------------------------------------------------------------------
# Modifier and clamping tests
# ---------------------------------------------------------------------------

class TestModifiers:
    def test_final_score_clamped_at_100(self):
        result = compute_confidence_score(
            technical=_max_technical(), positioning=_max_positioning(), sentiment=_max_sent(), news=_max_news(),
            regime_modifier=10, sector_rotation_modifier=5, earnings_modifier=0,
            cross_ticker_modifier=5, seasonality_modifier=5, macro_modifier=3,
            volume_profile_score=8.0,
        )
        assert result["final_score"] <= 100.0

    def test_final_score_clamped_at_zero(self):
        zero_tech = {"breakout_volume_zscore": 0, "rs_zscore": 0, "rsi_14": 50,
                     "breakout_confirmed": False, "trend_intact": False}
        result = compute_confidence_score(
            technical=zero_tech, positioning=_zero_positioning(), sentiment=_zero_sent(), news=_zero_news(),
            regime_modifier=-15, sector_rotation_modifier=-15, earnings_modifier=-20,
            cross_ticker_modifier=-10, seasonality_modifier=-5, macro_modifier=-10,
        )
        assert result["final_score"] >= 0.0

    def test_modifiers_are_clamped_to_bounds(self):
        """Passing out-of-bound modifiers: they should be silently clamped."""
        result = compute_confidence_score(
            technical=_max_technical(), positioning=_max_positioning(), sentiment=_max_sent(), news=_max_news(),
            regime_modifier=-100,   # should be clamped to -15
            sector_rotation_modifier=-100,  # clamped to -15
            earnings_modifier=-100,  # clamped to -20
            cross_ticker_modifier=100,
            seasonality_modifier=100, macro_modifier=100,
            volume_profile_score=8.0,
        )
        assert result["regime_modifier"] == -15.0
        assert result["sector_rotation_modifier"] == -15.0
        assert result["earnings_modifier"] == -20.0
        assert result["cross_ticker_modifier"] == 5.0
        assert result["seasonality_modifier"] == 5.0
        assert result["macro_modifier"] == 3.0

    def test_total_modifier_is_sum_of_all_modifiers(self):
        # regime (+5) and sector_rotation (-3) are opposite-signed here — a
        # real disagreement between the two lenses, not a double-count — so
        # they're expected to sum plainly, same as every other modifier pair.
        # See TestRegimeSectorRotationDedup below for the same-sign case.
        result = compute_confidence_score(
            technical=_max_technical(), positioning=_max_positioning(), sentiment=_max_sent(), news=_max_news(),
            regime_modifier=5, sector_rotation_modifier=-3, earnings_modifier=-10,
            cross_ticker_modifier=2, seasonality_modifier=3, macro_modifier=2,
            volume_profile_score=8.0,
        )
        expected_mod = 5 + (-3) + (-10) + 2 + 3 + 2
        assert result["total_modifier"] == pytest.approx(expected_mod, abs=0.01)

    def test_final_score_equals_base_plus_total_modifier(self):
        result = compute_confidence_score(
            technical=_max_technical(), positioning=_max_positioning(), sentiment=_max_sent(), news=_max_news(),
            regime_modifier=5, sector_rotation_modifier=0, earnings_modifier=-15,
            cross_ticker_modifier=2, seasonality_modifier=2, macro_modifier=0,
            volume_profile_score=8.0,
        )
        expected = min(100.0, max(0.0, result["base_score"] + result["total_modifier"]))
        assert result["final_score"] == pytest.approx(expected, abs=0.01)

    def test_earnings_modifier_within_bounds(self):
        from shared.utils.earnings_calendar import get_earnings_modifier
        result = get_earnings_modifier(ticker="NVDA", earnings_date=None)
        assert -20 <= result["confidence_modifier"] <= 0


# ---------------------------------------------------------------------------
# Regime x sector_rotation double-count dedup
# ---------------------------------------------------------------------------

class TestRegimeSectorRotationDedup:
    def _score(self, regime_modifier, sector_rotation_modifier):
        return compute_confidence_score(
            technical=_max_technical(), positioning=_max_positioning(), sentiment=_max_sent(), news=_max_news(),
            regime_modifier=regime_modifier, sector_rotation_modifier=sector_rotation_modifier,
            earnings_modifier=0, cross_ticker_modifier=0, seasonality_modifier=0, macro_modifier=0,
            volume_profile_score=8.0,
        )

    def test_both_negative_uses_larger_magnitude_not_sum(self):
        # Mirrors the actual live pattern (e.g. NVDA mid-session 08-05:
        # regime=-2.0, sector_rotation=-15.0) — both SMH-derived and both
        # negative should combine to -15.0 (the larger magnitude), not -17.0.
        result = self._score(regime_modifier=-2.0, sector_rotation_modifier=-15.0)
        assert result["regime_sector_rotation_combined"] == pytest.approx(-15.0)
        assert result["total_modifier"] == pytest.approx(-15.0)

    def test_both_positive_uses_larger_magnitude_not_sum(self):
        result = self._score(regime_modifier=5.0, sector_rotation_modifier=3.0)
        assert result["regime_sector_rotation_combined"] == pytest.approx(5.0)
        assert result["total_modifier"] == pytest.approx(5.0)

    def test_opposite_signs_still_sum_plainly(self):
        # A real disagreement between the two lenses — not a double-count —
        # so this case is left as a plain sum.
        result = self._score(regime_modifier=5.0, sector_rotation_modifier=-3.0)
        assert result["regime_sector_rotation_combined"] == pytest.approx(2.0)
        assert result["total_modifier"] == pytest.approx(2.0)

    def test_one_zero_sums_plainly(self):
        result = self._score(regime_modifier=5.0, sector_rotation_modifier=0.0)
        assert result["regime_sector_rotation_combined"] == pytest.approx(5.0)

    def test_both_zero(self):
        result = self._score(regime_modifier=0.0, sector_rotation_modifier=0.0)
        assert result["regime_sector_rotation_combined"] == pytest.approx(0.0)

    def test_raw_individual_modifiers_still_reported_unchanged(self):
        # The dedup only affects total_modifier's bottom line — the raw
        # per-modifier values must stay visible for audit/NOTE-detection
        # logic (paper_runner.py) that reads them individually.
        result = self._score(regime_modifier=-2.0, sector_rotation_modifier=-15.0)
        assert result["regime_modifier"] == pytest.approx(-2.0)
        assert result["sector_rotation_modifier"] == pytest.approx(-15.0)

    def test_dedup_applied_after_clamping_to_bounds(self):
        # regime clamps to -15 (from -100), sector_rotation clamps to -15 too
        # — same sign after clamping, so combined should be -15, not -30.
        result = self._score(regime_modifier=-100.0, sector_rotation_modifier=-100.0)
        assert result["regime_sector_rotation_combined"] == pytest.approx(-15.0)


# ---------------------------------------------------------------------------
# High-vol regime cap test
# ---------------------------------------------------------------------------

class TestRegimeCap:
    def test_high_vol_caps_at_70(self):
        result = apply_high_vol_regime_cap(score=95.0, regime="high_vol", cap=70.0)
        assert result == 70.0

    def test_no_cap_in_trending_regime(self):
        result = apply_high_vol_regime_cap(score=95.0, regime="trending_up", cap=70.0)
        assert result == 95.0

    def test_score_below_cap_not_affected(self):
        result = apply_high_vol_regime_cap(score=65.0, regime="high_vol", cap=70.0)
        assert result == 65.0

    def test_high_vol_regime_via_compute_score(self):
        result = compute_confidence_score(
            technical=_max_technical(), positioning=_max_positioning(), sentiment=_max_sent(), news=_max_news(),
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=0, seasonality_modifier=0, macro_modifier=0,
            volume_profile_score=8.0, regime="high_vol",
        )
        assert result["final_score"] <= 70.0


# ---------------------------------------------------------------------------
# Scope formula verification
# ---------------------------------------------------------------------------

class TestScopeFormula:
    """
    Verify the scope's base formula:
      base = tech_total + positioning_total + sent_total + news_total + fundamental_contribution
      final = base + sum(modifiers), clamped [0, 100].
    """

    def test_90_score_achievable(self):
        # Technical=40 (max), Positioning=15, Sentiment=8, News=7, Fundamental internal=15 (->10
        # contribution) → base=80; regime+cross_ticker modifiers=+10 → final=90.
        positioning = {"positioning_score_total": 15.0}
        sentiment = {"sentiment_score_total": 8.0, "dominant_sentiment": "bullish"}
        news = {"news_score_total": 7.0}
        fundamental = {"fundamental_score": 15.0, "data_quality": "complete"}
        result = compute_confidence_score(
            technical=_max_technical(), positioning=positioning, sentiment=sentiment, news=news,
            regime_modifier=5, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=5, seasonality_modifier=0, macro_modifier=0,
            volume_profile_score=8.0, fundamental=fundamental,
        )
        assert result["base_score"] == pytest.approx(80.0, abs=0.5)
        assert result["final_score"] == pytest.approx(90.0, abs=0.5)
        assert result["meets_threshold"] is True

    def test_meets_threshold_is_false_below_90(self):
        result = compute_confidence_score(
            technical={"rsi_14": 50.0, "trend_intact": False},
            positioning={"positioning_score_total": 2.0},
            sentiment={"sentiment_score_total": 3.0, "dominant_sentiment": "neutral"},
            news={"news_score_total": 2.0},
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=-15,
            cross_ticker_modifier=0, seasonality_modifier=0, macro_modifier=0,
        )
        assert result["meets_threshold"] is False

    def test_sentiment_offline_cap_at_70(self):
        sentiment_offline = {
            "sentiment_score_total": 15.0,
            "dominant_sentiment": "bullish",
            "sentiment_offline": True,
            "sentiment_offline_cap": 70,
        }
        result = compute_confidence_score(
            technical=_max_technical(), positioning=_max_positioning(), sentiment=sentiment_offline, news=_max_news(),
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=0, seasonality_modifier=0, macro_modifier=0,
            volume_profile_score=8.0,
        )
        assert result["final_score"] <= 70.0

    def test_positioning_offline_cap_at_70(self):
        positioning_offline = {
            "positioning_score_total": 0.0,
            "positioning_offline": True,
            "positioning_offline_cap": 70,
        }
        result = compute_confidence_score(
            technical=_max_technical(), positioning=positioning_offline, sentiment=_max_sent(), news=_max_news(),
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=0, seasonality_modifier=0, macro_modifier=0,
            volume_profile_score=8.0,
        )
        assert result["final_score"] <= 70.0

    def test_all_required_keys_present(self):
        result = compute_confidence_score(
            technical={}, positioning=_zero_positioning(), sentiment=_zero_sent(), news=_zero_news(),
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=0, seasonality_modifier=0, macro_modifier=0,
        )
        for key in (
            "breakout_score", "trend_score", "rs_score", "rsi_score", "volume_profile_score",
            "technical_total", "options_score", "institutional_score", "short_interest_score",
            "insider_score", "analyst_score", "positioning_total",
            "ratio_score", "velocity_score", "engagement_score", "sentiment_total",
            "credibility_score", "theme_score", "clustering_score", "decay_score", "news_total",
            "base_score", "regime_modifier", "sector_rotation_modifier", "earnings_modifier",
            "cross_ticker_modifier", "seasonality_modifier",
            "macro_modifier", "total_modifier", "final_score", "direction", "meets_threshold",
        ):
            assert key in result, f"Missing key: {key}"

    def test_category_maxes_sum_to_100(self):
        assert TECHNICAL_MAX + POSITIONING_MAX + SENTIMENT_MAX + NEWS_MAX + FUNDAMENTAL_MAX == 100


# ---------------------------------------------------------------------------
# direction_override tests
# ---------------------------------------------------------------------------

class TestDirectionOverride:
    def test_direction_override_bearish_uses_bearish_technical_scoring(self):
        result = compute_confidence_score(
            technical=_max_technical_bearish(), positioning=_zero_positioning(),
            sentiment=_zero_sent(), news=_zero_news(),
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=0, seasonality_modifier=0, macro_modifier=0,
            volume_profile_score=8.0, direction_override="bearish",
        )
        assert result["direction"] == "bearish"
        assert result["technical_total"] == pytest.approx(40.0)

    def test_no_override_recomputes_direction_internally(self):
        # Regression guard: omitting direction_override must behave exactly
        # like before this param existed.
        result = compute_confidence_score(
            technical=_max_technical(), positioning=_zero_positioning(),
            sentiment=_max_sent(), news=_zero_news(),
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=0, seasonality_modifier=0, macro_modifier=0,
            volume_profile_score=8.0,
        )
        assert result["direction"] == "bullish"
        assert result["technical_total"] == pytest.approx(40.0)

    def test_override_ignored_technical_still_scored_for_given_direction(self):
        # Passing bearish technical inputs but overriding to "bullish" should
        # score technical using the bullish formulas (low score, since the
        # inputs are bearish-favorable) — direction_override picks which
        # formula set runs, it doesn't relabel the result of the other one.
        result = compute_confidence_score(
            technical=_max_technical_bearish(), positioning=_zero_positioning(),
            sentiment=_zero_sent(), news=_zero_news(),
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=0, seasonality_modifier=0, macro_modifier=0,
            volume_profile_score=8.0, direction_override="bullish",
        )
        assert result["direction"] == "bullish"
        assert result["technical_total"] < 40.0


# ---------------------------------------------------------------------------
# Signal Integrity Audit finding B.1 — fundamental_contribution must mirror
# for direction: strong fundamentals help a bullish candidate and hurt a
# bearish one; weak/deteriorating fundamentals should do the opposite.
# ---------------------------------------------------------------------------

class TestFundamentalDirectionMirror:
    def _score(self, fundamental_score_raw, direction):
        return compute_confidence_score(
            technical={},  # all sub-scores default to 0/neutral — irrelevant here
            positioning=_zero_positioning(),
            sentiment=_zero_sent(), news=_zero_news(),
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=0, seasonality_modifier=0, macro_modifier=0,
            fundamental={"fundamental_score": fundamental_score_raw, "data_quality": "complete"},
            direction_override=direction,
        )

    def test_strong_fundamentals_help_bullish(self):
        result = self._score(15.0, "bullish")
        assert result["fundamental_score"] == pytest.approx(10.0)

    def test_strong_fundamentals_hurt_bearish(self):
        # A ticker with genuinely strong (rising) fundamentals should NOT
        # confirm a bearish thesis — the contribution flips negative.
        result = self._score(15.0, "bearish")
        assert result["fundamental_score"] == pytest.approx(-10.0)

    def test_weak_fundamentals_hurt_bullish(self):
        result = self._score(-15.0, "bullish")
        assert result["fundamental_score"] == pytest.approx(-10.0)

    def test_weak_fundamentals_help_bearish(self):
        # Deteriorating fundamentals should CONFIRM a bearish thesis, not
        # drag down an otherwise well-confirmed short (the bug this fixes).
        result = self._score(-15.0, "bearish")
        assert result["fundamental_score"] == pytest.approx(10.0)

    def test_neutral_fundamentals_unaffected_by_direction(self):
        assert self._score(0.0, "bullish")["fundamental_score"] == pytest.approx(0.0)
        assert self._score(0.0, "bearish")["fundamental_score"] == pytest.approx(0.0)
