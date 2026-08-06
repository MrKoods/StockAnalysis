"""Tests for shared.utils.isotonic — PAVA isotonic regression backing the
win-probability calibration curve (win_probability_calibration.py)."""

import pytest

from shared.utils.isotonic import isotonic_regression


class TestIsotonicRegression:
    def test_empty_input(self):
        assert isotonic_regression([]) == []

    def test_single_value(self):
        assert isotonic_regression([5.0]) == [5.0]

    def test_already_monotone_is_unchanged(self):
        assert isotonic_regression([1, 2, 3, 4, 5]) == [1, 2, 3, 4, 5]

    def test_simple_violation_pools_to_mean(self):
        # Textbook example: [3, 1, 2] -> [2, 2, 2]
        result = isotonic_regression([3, 1, 2])
        assert result == pytest.approx([2.0, 2.0, 2.0])

    def test_three_point_violation_with_trailing_point(self):
        # Textbook example: [1, 3, 2] -> [1, 2.5, 2.5]
        result = isotonic_regression([1, 3, 2])
        assert result == pytest.approx([1.0, 2.5, 2.5])

    def test_fully_decreasing_pools_to_overall_mean(self):
        result = isotonic_regression([5, 4, 3, 2, 1])
        assert result == pytest.approx([3.0] * 5)

    def test_result_is_always_non_decreasing(self):
        values = [10, 2, 8, 1, 9, 3, 15, 4]
        result = isotonic_regression(values)
        for a, b in zip(result, result[1:]):
            assert a <= b + 1e-9

    def test_output_same_length_as_input(self):
        values = [5, 3, 8, 1, 9, 2, 7]
        assert len(isotonic_regression(values)) == len(values)

    def test_heavier_weight_pulls_merged_value_toward_it(self):
        # 10 and 2 violate; weight the second point (2) 100x — the merged
        # value should land close to 2, not the unweighted midpoint (6).
        result = isotonic_regression([1, 10, 2], weights=[1, 1, 100])
        assert result[1] == pytest.approx(result[2])
        assert result[1] < 3.0  # much closer to 2 than to the unweighted mean of 6

    def test_equal_weights_matches_unweighted_default(self):
        values = [3, 1, 2]
        assert isotonic_regression(values, weights=[1, 1, 1]) == pytest.approx(
            isotonic_regression(values)
        )

    def test_matches_real_win_rate_sensitivity_shape(self):
        # Loosely mirrors an actual pooled sensitivity_analysis reading (noisy
        # but broadly increasing win rate as threshold rises) — the smoothed
        # curve should be non-decreasing and should not move any point wildly
        # far from its neighbors.
        win_rates = [0.5625, 0.5609, 0.5619, 0.5607, 0.5626, 0.5657, 0.5745,
                     0.5743, 0.5766, 0.5707, 0.5980, 0.6250]
        weights = [544, 542, 541, 535, 519, 495, 470, 444, 418, 368, 296, 192]
        result = isotonic_regression(win_rates, weights=weights)
        for a, b in zip(result, result[1:]):
            assert a <= b + 1e-9
        assert result[0] == pytest.approx(0.5625, abs=0.01)
        assert result[-1] >= result[0]
