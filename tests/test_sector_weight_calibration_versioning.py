"""
Tests for backtesting/sector_weight_calibration.py's version-bump gate.

Before this fix, run() called feedback_loop.save_sector_weights() directly
with no check at all — the ONE enforcement point this project's CHANGELOG.md
documents as "no scoring change goes live without a version bump — no
exceptions" (model_versioning.check_backtest_required(), already used by the
older global-calibration path in feedback_loop.run_calibration()) was never
applied to this newer per-sector weight path, even though it writes straight
to the file feedback_loop.load_live_weights_if_calibrated() feeds into live
scoring.
"""

from unittest.mock import patch

import backtesting.sector_weight_calibration as swc


def _outcome(date, confidence=92.0, technical_total=30.0, sentiment_total=10.0,
             news_total=10.0, pnl_dollars=100.0):
    return {
        "signal_date": date, "exit_date": date, "confidence": confidence,
        "technical_total": technical_total, "sentiment_total": sentiment_total,
        "news_total": news_total, "pnl_dollars": pnl_dollars,
    }


def _many_outcomes(n, win_biased_weights=None):
    """n synthetic qualifying outcomes, chronologically dated."""
    return [_outcome(f"2026-01-{(i % 28) + 1:02d}") for i in range(n)]


class TestVersionGateBlocksLargeWeightChanges:
    def test_large_fitted_change_is_not_saved_and_reported_blocked(self):
        big_change_weights = {"semiconductors": {"technical": 0.05, "sentiment": 0.05, "news": 0.90}}
        with patch.object(swc, "collect_per_sector_outcomes", return_value={"semiconductors": _many_outcomes(150)}):
            with patch.object(swc, "fit_sector_calibrated_weights", return_value=big_change_weights):
                with patch.object(swc, "_score_outcomes", side_effect=[0.0, 1.0]):  # old, new — new "passes" holdout
                    with patch.object(swc, "save_sector_weights") as mock_save:
                        result = swc.run()

        mock_save.assert_not_called()
        assert "semiconductors" in result["version_blocked"]
        assert "semiconductors" not in result["saved"]

    def test_small_fitted_change_is_saved_normally(self):
        small_change_weights = {"semiconductors": {"technical": 0.62, "sentiment": 0.23, "news": 0.15}}
        with patch.object(swc, "collect_per_sector_outcomes", return_value={"semiconductors": _many_outcomes(150)}):
            with patch.object(swc, "fit_sector_calibrated_weights", return_value=small_change_weights):
                with patch.object(swc, "_score_outcomes", side_effect=[0.0, 1.0]):
                    with patch.object(swc, "save_sector_weights") as mock_save:
                        result = swc.run()

        mock_save.assert_called_once()
        assert "semiconductors" in result["saved"]
        assert result["version_blocked"] == {}

    def test_multiple_sectors_gated_independently(self):
        weights = {
            "semiconductors": {"technical": 0.62, "sentiment": 0.23, "news": 0.15},  # small change
            "consumer_discretionary": {"technical": 0.05, "sentiment": 0.05, "news": 0.90},  # large change
        }
        with patch.object(swc, "collect_per_sector_outcomes", return_value={
            "semiconductors": _many_outcomes(150), "consumer_discretionary": _many_outcomes(150),
        }):
            with patch.object(swc, "fit_sector_calibrated_weights", return_value=weights):
                with patch.object(swc, "_score_outcomes", side_effect=[0.0, 1.0, 0.0, 1.0]):
                    with patch.object(swc, "save_sector_weights") as mock_save:
                        result = swc.run()

        assert "semiconductors" in result["saved"]
        assert "consumer_discretionary" in result["version_blocked"]
        saved_arg = mock_save.call_args[0][0]
        assert "consumer_discretionary" not in saved_arg

    def test_nothing_fitted_does_not_touch_model_versioning(self):
        """No candidate weights at all -> the version check has nothing to
        gate; must not error out on an empty pass."""
        with patch.object(swc, "collect_per_sector_outcomes", return_value={"semiconductors": []}):
            with patch.object(swc, "fit_sector_calibrated_weights", return_value={}):
                with patch.object(swc, "save_sector_weights") as mock_save:
                    result = swc.run()

        mock_save.assert_not_called()
        assert result["saved"] == {}
        assert result["version_blocked"] == {}
