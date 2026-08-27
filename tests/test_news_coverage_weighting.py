"""
Tests for per-sector News coverage weighting (v2.2.111).

News coverage is wildly uneven by sector — a property of a company's media
profile, not of its trade setup. Measured live 2026-08-26 (mean Finnhub
articles per ticker): semiconductors 65.1, consumer_discretionary 55.0,
healthcare 29.1, regional_banks 5.4, with 7 of 12 banks matching ZERO relevant
articles out of 30+ fetched. v2.2.103 stopped that absence being scored as BAD
news (it floors at a neutral 5.0/15), but a neutral score still occupies 15 of
the 100 composite points while carrying no information.

Ships DISABLED. "Banks have thin coverage" is measured; "therefore bank news is
less predictive" is not. This is the zero-API-cost control to measure real
sourcing alternatives against.
"""

import yaml

from shared.utils.sector_config import get_news_weight_scale
from swing_model.scoring import compute_confidence_score


_TECHNICAL = {
    "close": 100, "sma_20": 99, "sma_50": 95, "rsi_14": 55, "atr_14": 2,
    "macd_line": 1, "macd_signal": 0.5, "macd_hist": 0.5, "rolling_high_20": 101,
    "rolling_low_20": 95, "volume_sma_20": 1e6, "rs_vs_benchmark": 1.0,
    "breakout_volume_zscore": 1.0, "rs_zscore": 0.5, "rsi_zscore": 0.2,
    "volume_zscore_current": 1.0, "breakout_confirmed": True, "breakdown_confirmed": False,
    "trend_intact": True, "downtrend_intact": False, "sma_20_above_sma_50": True,
    "price_above_sma_50": True, "macd_bullish": True, "macd_bearish": False,
    "macd_data_available": True, "volume_profile_score": 4.0, "volume_profile_score_bearish": 4.0,
}


def _score(news_total=5.0, scale=1.0):
    return compute_confidence_score(
        technical=_TECHNICAL,
        positioning={"positioning_score_total": 12.0},
        sentiment={"sentiment_score_total": 9.0},
        news={"news_score_total": news_total},
        fundamental={"fundamental_score": 0.0, "data_quality": "complete"},
        regime_modifier=0.0, sector_rotation_modifier=0.0, earnings_modifier=0.0,
        cross_ticker_modifier=0.0, seasonality_modifier=0.0, macro_modifier=0.0,
        news_weight_scale=scale,
    )


class TestDisabledByDefault:
    def test_default_scale_is_a_true_no_op(self):
        assert _score(scale=1.0)["final_score"] == _score()["final_score"]

    def test_caps_are_untouched_at_scale_one(self):
        r = _score(scale=1.0)
        assert (r["technical_max"], r["sentiment_max"], r["news_max"]) == (40.0, 15.0, 15.0)

    def test_real_config_ships_disabled(self):
        """Turning this on mid-experiment would contaminate the rank track
        ahead of its 2026-09-19 checkpoint."""
        cfg = yaml.safe_load(open("config/swing_config.yaml").read())
        block = cfg["scoring_weights"]["news_coverage_weighting"]
        assert block["enabled"] is False

    def test_helper_returns_no_op_while_disabled(self):
        cfg = yaml.safe_load(open("config/swing_config.yaml").read())
        assert get_news_weight_scale(cfg, "regional_banks") == 1.0


class TestRedistribution:
    def test_pool_is_conserved(self):
        """base_score must stay bounded and comparable across sectors."""
        r = _score(scale=0.5)
        assert r["technical_max"] + r["sentiment_max"] + r["news_max"] == 70.0

    def test_news_cap_scales_and_freed_points_go_to_the_others(self):
        r = _score(scale=0.5)
        assert r["news_max"] == 7.5
        assert r["technical_max"] > 40.0
        assert r["sentiment_max"] > 15.0

    def test_freed_points_split_pro_rata_not_evenly(self):
        """Technical's 40:15 edge over Sentiment must be preserved, so this
        changes the news/other balance without re-ranking those two."""
        r = _score(scale=0.5)
        gained_t = r["technical_max"] - 40.0
        gained_s = r["sentiment_max"] - 15.0
        assert abs((gained_t / gained_s) - (40.0 / 15.0)) < 0.01


class TestDirectionalEffect:
    """Not a blanket boost — it helps tickers whose news is uninformative and
    penalises tickers whose news is genuinely strong."""

    def test_weak_news_ticker_gains(self):
        """A bank at the v2.2.103 neutral floor of 5.0/15."""
        assert _score(news_total=5.0, scale=0.5)["final_score"] > _score(news_total=5.0)["final_score"]

    def test_strong_news_ticker_loses(self):
        """TFC scored 11.1/15 on 2026-08-26 and would lose 2.47 points."""
        assert _score(news_total=13.0, scale=0.5)["final_score"] < _score(news_total=13.0)["final_score"]


class TestHelperResolution:
    CFG = {"scoring_weights": {"news_coverage_weighting": {
        "enabled": True, "sectors": {"regional_banks": 0.5}}}}

    def test_configured_sector_gets_its_scale(self):
        assert get_news_weight_scale(self.CFG, "regional_banks") == 0.5

    def test_unlisted_sector_is_never_silently_reweighted(self):
        assert get_news_weight_scale(self.CFG, "healthcare") == 1.0

    def test_unknown_sector_is_safe(self):
        assert get_news_weight_scale(self.CFG, None) == 1.0

    def test_malformed_value_falls_back_to_no_op(self):
        cfg = {"scoring_weights": {"news_coverage_weighting": {
            "enabled": True, "sectors": {"regional_banks": "half"}}}}
        assert get_news_weight_scale(cfg, "regional_banks") == 1.0

    def test_empty_config_is_safe(self):
        assert get_news_weight_scale({}, "regional_banks") == 1.0
