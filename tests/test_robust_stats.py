"""Tests for shared.utils.robust_stats — the MAD-based outlier check backing
paper_runner.py's ev_outlier flag (fix for the MU long_strangle EV/$ anomaly)."""

import pytest

from shared.utils.robust_stats import robust_z_score, is_outlier, DEFAULT_OUTLIER_THRESHOLD


class TestRobustZScore:
    def test_none_with_fewer_than_five_points(self):
        assert robust_z_score(10.0, [1.0, 2.0, 3.0]) is None

    def test_none_when_all_historical_values_identical(self):
        # MAD == 0 — no meaningful spread to compare against, would divide by zero.
        assert robust_z_score(5.0, [1.0, 1.0, 1.0, 1.0, 1.0]) is None

    def test_zero_for_value_equal_to_median(self):
        history = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert robust_z_score(3.0, history) == pytest.approx(0.0)

    def test_positive_for_value_above_median(self):
        history = [1.0, 2.0, 3.0, 4.0, 5.0]
        z = robust_z_score(10.0, history)
        assert z > 0

    def test_negative_for_value_below_median(self):
        history = [1.0, 2.0, 3.0, 4.0, 5.0]
        z = robust_z_score(-10.0, history)
        assert z < 0

    def test_resistant_to_a_single_extreme_historical_point(self):
        # A mean/std z-score would have its mean dragged toward 1000 and its
        # std inflated by it, shrinking the z-score it reports for a new
        # extreme value. Median/MAD shouldn't move nearly as much.
        clean_history = [10.0, 11.0, 9.0, 10.5, 9.5, 10.2, 9.8]
        contaminated_history = clean_history + [1000.0]
        z_clean = robust_z_score(50.0, clean_history)
        z_contaminated = robust_z_score(50.0, contaminated_history)
        assert z_clean > 5  # a jump from ~10 to 50 is a real outlier
        # Adding one contaminating point shouldn't collapse the z-score toward zero.
        assert z_contaminated > 3

    def test_mirrors_the_mu_long_strangle_scenario(self):
        # AVGO/NVDA-like history clustered around ev/$/day ~1.5-2.0; a MU-like
        # reading around 12 should register as a large, clearly flagged outlier.
        history = [1.5, 1.8, 1.6, 1.9, 1.7, 1.55, 1.65, 1.75]
        z = robust_z_score(12.0, history)
        assert z is not None
        assert z >= DEFAULT_OUTLIER_THRESHOLD


class TestIsOutlier:
    def test_false_when_not_enough_history(self):
        assert is_outlier(100.0, [1.0, 2.0]) is False

    def test_false_for_a_typical_value(self):
        history = [1.5, 1.8, 1.6, 1.9, 1.7, 1.55, 1.65, 1.75]
        assert is_outlier(1.72, history) is False

    def test_true_for_a_large_deviation(self):
        history = [1.5, 1.8, 1.6, 1.9, 1.7, 1.55, 1.65, 1.75]
        assert is_outlier(12.0, history) is True

    def test_custom_threshold_is_respected(self):
        history = [1.5, 1.8, 1.6, 1.9, 1.7, 1.55, 1.65, 1.75]
        # A moderate deviation might not clear the default 3.5 bar but should
        # clear a much looser custom one.
        z = robust_z_score(3.0, history)
        assert z is not None
        assert is_outlier(3.0, history, threshold=abs(z) - 0.01) is True
        assert is_outlier(3.0, history, threshold=abs(z) + 0.01) is False
