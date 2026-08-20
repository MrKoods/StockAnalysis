"""
Tests for backtesting/walk_forward.py's config wiring (Tier B batch 2/3,
2026-08-19) — run_walk_forward previously had zero test coverage at all.
initial_train_months/validate_months now default from
config.backtesting.walk_forward_windows instead of bare hardcoded literals
(18/24) — validate_months in particular was corrected from a stale config
value of 6 to the code's real, deliberately-chosen 24 (see the function's
own docstring for why).
"""

from unittest.mock import patch

from backtesting.walk_forward import run_walk_forward


class TestConfigResolution:
    def test_explicit_overrides_skip_config_load_entirely(self):
        """Passing both explicitly must never touch config at all."""
        with patch("swing_model.indicator_pipeline.load_config") as mock_load:
            run_walk_forward({}, initial_train_months=12, validate_months=6)
        mock_load.assert_not_called()

    def test_missing_override_reads_from_config_path(self):
        with patch("swing_model.indicator_pipeline.load_config") as mock_load:
            mock_load.return_value = {
                "backtesting": {"walk_forward_windows": {"initial_train_months": 12, "initial_validate_months": 9}}
            }
            run_walk_forward({}, config_path="fake/path.yaml")
        mock_load.assert_called_once_with("fake/path.yaml")

    def test_empty_historical_data_returns_empty_list_regardless(self):
        assert run_walk_forward({}) == []
        assert run_walk_forward({}, initial_train_months=12, validate_months=6) == []
