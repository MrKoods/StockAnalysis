"""
Tests for swing_model/scoring.py.
Verifies the exact confidence scoring formula from the scope:
  Technical 60 / Sentiment 25 / News 15
  Modifier bounds and clamping 0-100
  High-vol regime cap at 70
"""

import pytest

from swing_model.scoring import (
    compute_confidence_score,
    compute_technical_sub_scores,
    apply_high_vol_regime_cap,
    CONFIDENCE_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _zero_sent():
    return {"sentiment_score_total": 0.0, "dominant_sentiment": "neutral",
            "trajectory_score": 0, "velocity_score": 0,
            "cross_platform_score": 0, "spike_score": 0}


def _zero_news():
    return {"news_score_total": 0.0}


def _max_sent():
    return {"sentiment_score_total": 25.0, "dominant_sentiment": "bullish",
            "trajectory_score": 10, "velocity_score": 5,
            "cross_platform_score": 5, "spike_score": 5}


def _max_news():
    return {"news_score_total": 15.0,
            "credibility_weighted_score": 6, "theme_alignment_score": 4,
            "clustering_score": 3, "decay_score": 2}


def _max_technical():
    """Inputs that produce breakout=12, trend=12, rs=12, rsi=12, vp=12 → total 60."""
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


# ---------------------------------------------------------------------------
# Technical sub-score tests
# ---------------------------------------------------------------------------

class TestTechnicalSubScores:
    def test_max_inputs_yield_60(self):
        sub = compute_technical_sub_scores(_max_technical(), volume_profile_score_override=12.0)
        assert sub["technical_total"] == pytest.approx(60.0)

    def test_each_sub_score_bounded_0_to_12(self):
        sub = compute_technical_sub_scores(_max_technical(), volume_profile_score_override=12.0)
        for key in ("breakout_score", "trend_score", "rs_score", "rsi_score", "volume_profile_score"):
            assert 0.0 <= sub[key] <= 12.0, f"{key} = {sub[key]} out of [0,12]"

    def test_zero_inputs_yield_low_score(self):
        zero = {"breakout_volume_zscore": -3.0, "rs_zscore": -3.0, "rsi_14": 20.0,
                "breakout_confirmed": False, "trend_intact": False,
                "sma_20_above_sma_50": False, "price_above_sma_50": False, "macd_bullish": False}
        sub = compute_technical_sub_scores(zero, volume_profile_score_override=0.0)
        assert sub["technical_total"] < 15  # Weak inputs → low score

    def test_breakout_capped_at_neutral_when_no_breakout(self):
        technical = {"breakout_volume_zscore": 3.0, "breakout_confirmed": False}
        sub = compute_technical_sub_scores(technical)
        assert sub["breakout_score"] <= 6.0

    def test_trend_score_12_when_trend_intact_and_macd_bullish(self):
        technical = {"trend_intact": True, "macd_bullish": True,
                     "sma_20_above_sma_50": True, "price_above_sma_50": True}
        sub = compute_technical_sub_scores(technical)
        assert sub["trend_score"] == 12.0

    def test_rsi_60_yields_max_rsi_score(self):
        sub = compute_technical_sub_scores({"rsi_14": 60.0})
        assert sub["rsi_score"] == 12.0

    def test_rsi_overbought_penalized(self):
        sub_normal = compute_technical_sub_scores({"rsi_14": 60.0})
        sub_overbought = compute_technical_sub_scores({"rsi_14": 85.0})
        assert sub_normal["rsi_score"] > sub_overbought["rsi_score"]

    def test_rs_zscore_positive_gives_high_rs_score(self):
        sub = compute_technical_sub_scores({"rs_zscore": 2.0})
        assert sub["rs_score"] > 9.0

    def test_rs_zscore_negative_gives_low_rs_score(self):
        sub = compute_technical_sub_scores({"rs_zscore": -2.0})
        assert sub["rs_score"] < 3.0

    def test_volume_profile_override_used(self):
        sub = compute_technical_sub_scores({}, volume_profile_score_override=9.0)
        assert sub["volume_profile_score"] == 9.0


# ---------------------------------------------------------------------------
# Base score tests
# ---------------------------------------------------------------------------

class TestBaseScore:
    def test_max_base_score_is_100(self):
        result = compute_confidence_score(
            technical=_max_technical(),
            sentiment=_max_sent(),
            news=_max_news(),
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=0, insider_modifier=0, seasonality_modifier=0,
            macro_modifier=0,
            volume_profile_score=12.0,
        )
        assert result["base_score"] == pytest.approx(100.0)

    def test_zero_inputs_yield_low_base(self):
        zero_tech = {"breakout_volume_zscore": -3.0, "rs_zscore": -3.0, "rsi_14": 20.0,
                     "breakout_confirmed": False, "trend_intact": False,
                     "sma_20_above_sma_50": False, "price_above_sma_50": False, "macd_bullish": False}
        result = compute_confidence_score(
            technical=zero_tech, sentiment=_zero_sent(), news=_zero_news(),
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=0, insider_modifier=0, seasonality_modifier=0,
            macro_modifier=0, volume_profile_score=0.0,
        )
        assert result["base_score"] < 20.0  # Some floor due to RSI/trend defaults

    def test_base_score_equals_technical_plus_sentiment_plus_news(self):
        result = compute_confidence_score(
            technical=_max_technical(),
            sentiment=_max_sent(),
            news=_max_news(),
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=0, insider_modifier=0, seasonality_modifier=0,
            macro_modifier=0, volume_profile_score=12.0,
        )
        expected = result["technical_total"] + result["sentiment_total"] + result["news_total"]
        assert result["base_score"] == pytest.approx(expected, abs=0.01)


# ---------------------------------------------------------------------------
# Modifier and clamping tests
# ---------------------------------------------------------------------------

class TestModifiers:
    def test_final_score_clamped_at_100(self):
        result = compute_confidence_score(
            technical=_max_technical(), sentiment=_max_sent(), news=_max_news(),
            regime_modifier=10, sector_rotation_modifier=5, earnings_modifier=0,
            cross_ticker_modifier=5, insider_modifier=8, seasonality_modifier=5, macro_modifier=3,
            volume_profile_score=12.0,
        )
        assert result["final_score"] <= 100.0

    def test_final_score_clamped_at_zero(self):
        zero_tech = {"breakout_volume_zscore": 0, "rs_zscore": 0, "rsi_14": 50,
                     "breakout_confirmed": False, "trend_intact": False}
        result = compute_confidence_score(
            technical=zero_tech, sentiment=_zero_sent(), news=_zero_news(),
            regime_modifier=-15, sector_rotation_modifier=-15, earnings_modifier=-20,
            cross_ticker_modifier=-10, insider_modifier=-8, seasonality_modifier=-5, macro_modifier=-10,
        )
        assert result["final_score"] >= 0.0

    def test_modifiers_are_clamped_to_bounds(self):
        """Passing out-of-bound modifiers: they should be silently clamped."""
        result = compute_confidence_score(
            technical=_max_technical(), sentiment=_max_sent(), news=_max_news(),
            regime_modifier=-100,   # should be clamped to -15
            sector_rotation_modifier=-100,  # clamped to -15
            earnings_modifier=-100,  # clamped to -20
            cross_ticker_modifier=100, insider_modifier=100,
            seasonality_modifier=100, macro_modifier=100,
            volume_profile_score=12.0,
        )
        assert result["regime_modifier"] == -15.0
        assert result["sector_rotation_modifier"] == -15.0
        assert result["earnings_modifier"] == -20.0
        assert result["cross_ticker_modifier"] == 5.0
        assert result["insider_modifier"] == 8.0
        assert result["seasonality_modifier"] == 5.0
        assert result["macro_modifier"] == 3.0

    def test_total_modifier_is_sum_of_all_modifiers(self):
        result = compute_confidence_score(
            technical=_max_technical(), sentiment=_max_sent(), news=_max_news(),
            regime_modifier=5, sector_rotation_modifier=3, earnings_modifier=-10,
            cross_ticker_modifier=2, insider_modifier=4, seasonality_modifier=3, macro_modifier=2,
            volume_profile_score=12.0,
        )
        expected_mod = 5 + 3 + (-10) + 2 + 4 + 3 + 2
        assert result["total_modifier"] == pytest.approx(expected_mod, abs=0.01)

    def test_final_score_equals_base_plus_total_modifier(self):
        result = compute_confidence_score(
            technical=_max_technical(), sentiment=_max_sent(), news=_max_news(),
            regime_modifier=5, sector_rotation_modifier=0, earnings_modifier=-15,
            cross_ticker_modifier=2, insider_modifier=0, seasonality_modifier=2, macro_modifier=0,
            volume_profile_score=12.0,
        )
        expected = min(100.0, max(0.0, result["base_score"] + result["total_modifier"]))
        assert result["final_score"] == pytest.approx(expected, abs=0.01)

    def test_earnings_modifier_within_bounds(self):
        from shared.utils.earnings_calendar import get_earnings_modifier
        result = get_earnings_modifier(ticker="NVDA", earnings_date=None)
        assert -20 <= result["confidence_modifier"] <= 0


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
            technical=_max_technical(), sentiment=_max_sent(), news=_max_news(),
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=0, insider_modifier=0, seasonality_modifier=0, macro_modifier=0,
            volume_profile_score=12.0, regime="high_vol",
        )
        assert result["final_score"] <= 70.0


# ---------------------------------------------------------------------------
# Scope formula verification
# ---------------------------------------------------------------------------

class TestScopeFormula:
    """
    Verify the scope's base formula: base = tech_total + sent_total + news_total
    and final = base + sum(modifiers), clamped [0, 100].
    Uses inputs engineered to produce a target 90/100 final score.
    """

    def test_90_score_achievable(self):
        # Technical sub-scores: breakout=11, trend=9, rs=9, rsi=9, vp=9 → total=47
        # (vol_z=2.5→11, trend_intact+no_macd→9, rs_z=1.5→9, rsi=52→9, vp=9)
        technical = {
            "breakout_volume_zscore": 2.5,
            "rs_zscore": 1.5,
            "rsi_14": 52.0,
            "breakout_confirmed": True,
            "trend_intact": True,
            "sma_20_above_sma_50": True,
            "price_above_sma_50": True,
            "macd_bullish": False,
        }
        # Sentiment: total=20
        sentiment = {
            "sentiment_score_total": 20.0,
            "dominant_sentiment": "bullish",
            "trajectory_score": 8, "velocity_score": 4,
            "cross_platform_score": 4, "spike_score": 4,
        }
        # News: total=13
        news = {
            "news_score_total": 13.0,
            "credibility_weighted_score": 5, "theme_alignment_score": 4,
            "clustering_score": 2, "decay_score": 2,
        }
        result = compute_confidence_score(
            technical=technical, sentiment=sentiment, news=news,
            regime_modifier=5, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=5, insider_modifier=0, seasonality_modifier=0, macro_modifier=0,
            volume_profile_score=9.0,
        )
        # base_score = 47 + 20 + 13 = 80; modifiers = 5 + 5 = 10; final = 90
        assert result["base_score"] == pytest.approx(80.0, abs=1.0)
        assert result["final_score"] == pytest.approx(90.0, abs=1.0)
        assert result["meets_threshold"] is True

    def test_meets_threshold_is_false_below_90(self):
        result = compute_confidence_score(
            technical={"rsi_14": 50.0, "trend_intact": False},
            sentiment={"sentiment_score_total": 5.0, "dominant_sentiment": "neutral"},
            news={"news_score_total": 3.0},
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=-15,
            cross_ticker_modifier=0, insider_modifier=0, seasonality_modifier=0, macro_modifier=0,
        )
        assert result["meets_threshold"] is False

    def test_sentiment_offline_cap_at_70(self):
        sentiment_offline = {
            "sentiment_score_total": 25.0,
            "dominant_sentiment": "bullish",
            "sentiment_offline": True,
            "sentiment_offline_cap": 70,
        }
        result = compute_confidence_score(
            technical=_max_technical(), sentiment=sentiment_offline, news=_max_news(),
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=0, insider_modifier=0, seasonality_modifier=0, macro_modifier=0,
            volume_profile_score=12.0,
        )
        assert result["final_score"] <= 70.0

    def test_all_required_keys_present(self):
        result = compute_confidence_score(
            technical={}, sentiment=_zero_sent(), news=_zero_news(),
            regime_modifier=0, sector_rotation_modifier=0, earnings_modifier=0,
            cross_ticker_modifier=0, insider_modifier=0, seasonality_modifier=0, macro_modifier=0,
        )
        for key in (
            "breakout_score", "trend_score", "rs_score", "rsi_score", "volume_profile_score",
            "technical_total", "trajectory_score", "velocity_score", "cross_platform_score",
            "spike_score", "sentiment_total", "credibility_score", "theme_score",
            "clustering_score", "decay_score", "news_total", "base_score",
            "regime_modifier", "sector_rotation_modifier", "earnings_modifier",
            "cross_ticker_modifier", "insider_modifier", "seasonality_modifier",
            "macro_modifier", "total_modifier", "final_score", "direction", "meets_threshold",
        ):
            assert key in result, f"Missing key: {key}"
