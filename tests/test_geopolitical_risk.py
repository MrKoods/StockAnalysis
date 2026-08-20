"""
Tests for shared.utils.geopolitical_risk.apply_geopolitical_penalty — extracted
from paper_runner.py/run_swing_model.py's duplicated inline blocks while
consolidating the two live pipelines (2026-08-19).
"""

from shared.utils.geopolitical_risk import apply_geopolitical_penalty


def _cfg(tickers=("TSM", "ASML"), penalty=-5):
    return {"geopolitical_risk_tickers": list(tickers), "geopolitical_penalty": penalty}


class TestApplyGeopoliticalPenalty:
    def test_flagged_ticker_gets_penalized(self):
        score, note = apply_geopolitical_penalty(_cfg(), "TSM", 90.0)
        assert score == 85.0
        assert "Geopolitical" in note

    def test_unflagged_ticker_is_untouched(self):
        score, note = apply_geopolitical_penalty(_cfg(), "NVDA", 90.0)
        assert score == 90.0
        assert note == ""

    def test_penalty_clamped_at_zero(self):
        score, note = apply_geopolitical_penalty(_cfg(penalty=-50), "TSM", 10.0)
        assert score == 0.0
        assert note != ""

    def test_missing_config_keys_default_to_no_penalty(self):
        score, note = apply_geopolitical_penalty({}, "TSM", 90.0)
        assert score == 90.0
        assert note == ""
