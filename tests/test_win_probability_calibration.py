"""
Tests for swing_model/win_probability_calibration.py — replaces
trade_selector.py's uncalibrated win_prob = confidence/100 with a real,
backtest-derived mapping.
"""

import pytest

from swing_model.win_probability_calibration import (
    fit_calibration_curve,
    calibrate_win_probability,
    load_calibration,
    save_calibration,
)


class TestFitCalibrationCurve:
    def test_empty_input_returns_empty(self):
        assert fit_calibration_curve([]) == []

    def test_drops_zero_trade_rows(self):
        rows = [
            {"threshold": 85, "win_rate": 0.0, "qualifying_trades": 0},
            {"threshold": 90, "win_rate": 0.6, "qualifying_trades": 100},
        ]
        result = fit_calibration_curve(rows)
        assert len(result) == 1
        assert result[0]["threshold"] == 90

    def test_output_sorted_by_threshold(self):
        rows = [
            {"threshold": 90, "win_rate": 0.6, "qualifying_trades": 100},
            {"threshold": 60, "win_rate": 0.55, "qualifying_trades": 200},
        ]
        result = fit_calibration_curve(rows)
        assert [r["threshold"] for r in result] == [60, 90]

    def test_smooths_a_noisy_dip_to_non_decreasing(self):
        # A raw dip at threshold 85 (0.55 < 0.58 at threshold 80) should be
        # smoothed away — a higher score should never calibrate to worse odds.
        rows = [
            {"threshold": 80, "win_rate": 0.58, "qualifying_trades": 400},
            {"threshold": 85, "win_rate": 0.55, "qualifying_trades": 350},
            {"threshold": 90, "win_rate": 0.63, "qualifying_trades": 300},
        ]
        result = fit_calibration_curve(rows)
        rates = [r["win_rate"] for r in result]
        for a, b in zip(rates, rates[1:]):
            assert a <= b + 1e-9

    def test_preserves_n_trades(self):
        rows = [{"threshold": 90, "win_rate": 0.6, "qualifying_trades": 296}]
        result = fit_calibration_curve(rows)
        assert result[0]["n_trades"] == 296


class TestCalibrateWinProbability:
    def test_empty_calibration_falls_back_to_confidence_over_100(self):
        assert calibrate_win_probability(65.0, []) == pytest.approx(0.65)

    def test_exact_match_on_a_calibration_point(self):
        points = [{"threshold": 60, "win_rate": 0.56}, {"threshold": 90, "win_rate": 0.60}]
        assert calibrate_win_probability(60.0, points) == pytest.approx(0.56)
        assert calibrate_win_probability(90.0, points) == pytest.approx(0.60)

    def test_interpolates_between_two_points(self):
        points = [{"threshold": 60, "win_rate": 0.50}, {"threshold": 90, "win_rate": 0.60}]
        # Halfway between 60 and 90 -> halfway between 0.50 and 0.60
        assert calibrate_win_probability(75.0, points) == pytest.approx(0.55)

    def test_clamps_below_lowest_threshold_no_extrapolation(self):
        points = [{"threshold": 60, "win_rate": 0.56}, {"threshold": 90, "win_rate": 0.60}]
        assert calibrate_win_probability(20.0, points) == pytest.approx(0.56)

    def test_clamps_above_highest_threshold_no_extrapolation(self):
        points = [{"threshold": 60, "win_rate": 0.56}, {"threshold": 90, "win_rate": 0.60}]
        assert calibrate_win_probability(99.0, points) == pytest.approx(0.60)

    def test_multi_segment_interpolation_picks_correct_segment(self):
        points = [
            {"threshold": 50, "win_rate": 0.50},
            {"threshold": 70, "win_rate": 0.55},
            {"threshold": 90, "win_rate": 0.63},
        ]
        assert calibrate_win_probability(60.0, points) == pytest.approx(0.525)
        assert calibrate_win_probability(80.0, points) == pytest.approx(0.59)

    def test_realistic_gap_between_raw_score_and_calibrated_probability(self):
        # The actual motivating case: a score of 90 should NOT calibrate to 0.90.
        points = [{"threshold": 90, "win_rate": 0.598, "n_trades": 296}]
        calibrated = calibrate_win_probability(90.0, points)
        uncalibrated = 90.0 / 100.0
        assert calibrated < uncalibrated - 0.2


class TestLoadSaveCalibration:
    def test_load_returns_none_when_file_missing(self, tmp_path):
        assert load_calibration(tmp_path / "nonexistent.json") is None

    def test_save_then_load_roundtrip(self, tmp_path):
        path = tmp_path / "calibration.json"
        points = [{"threshold": 90, "win_rate": 0.6, "n_trades": 296}]
        save_calibration(points, "test source", path=path)
        loaded = load_calibration(path)
        assert loaded == points

    def test_load_returns_none_for_malformed_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json", encoding="utf-8")
        assert load_calibration(path) is None

    def test_load_returns_none_for_empty_points_list(self, tmp_path):
        path = tmp_path / "empty.json"
        save_calibration([], "test source", path=path)
        assert load_calibration(path) is None
