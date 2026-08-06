"""
Tests for backtesting.metrics.compute_deflated_sharpe_ratio — the
multiple-testing correction for picking the best Sharpe out of a sweep
(run_sensitivity_analysis's threshold sweep, entry_filter_variants.py's
filter-variant sweep). Pure-math tests only; no historical data needed.
"""

import numpy as np
import pytest
from scipy.stats import norm

from backtesting.metrics import compute_deflated_sharpe_ratio


class TestEdgeCases:
    def test_zero_trials_returns_zeros(self):
        result = compute_deflated_sharpe_ratio([], selected_sharpe=1.0, n_observations=100)
        assert result == {
            "expected_max_sharpe_under_null": 0.0,
            "deflated_sharpe": 0.0,
            "psr": 0.0,
            "n_trials": 0,
            "n_observations": 100,
        }

    def test_fewer_than_two_observations_returns_zeros(self):
        result = compute_deflated_sharpe_ratio([1.0, 2.0], selected_sharpe=2.0, n_observations=1)
        assert result["psr"] == 0.0
        assert result["deflated_sharpe"] == 0.0

    def test_single_trial_has_zero_expected_max_under_null(self):
        # With nothing to compare against, there's no "best of N" inflation to
        # correct for — expected_max_sharpe_under_null collapses to 0 and the
        # result should reduce to a standard (non-deflated) PSR.
        result = compute_deflated_sharpe_ratio([1.2], selected_sharpe=1.2, n_observations=100)
        assert result["expected_max_sharpe_under_null"] == 0.0
        assert result["n_trials"] == 1
        expected_psr = float(norm.cdf(1.2 * np.sqrt(99)))
        assert result["psr"] == pytest.approx(round(expected_psr, 4), abs=1e-3)


class TestMultipleTestingCorrection:
    def test_more_trials_raises_the_bar_for_the_same_selected_sharpe(self):
        # Same selected Sharpe, same observation count, but drawn from a wider
        # sweep — the correction should demand more to call it real, since
        # more trials means a bigger chance the winner is just noise.
        rng = np.random.default_rng(7)
        few_trials = list(rng.normal(0.0, 0.3, size=5))
        many_trials = list(rng.normal(0.0, 0.3, size=200))

        selected_sharpe = 1.5
        n_obs = 100

        few = compute_deflated_sharpe_ratio(few_trials, selected_sharpe, n_obs)
        many = compute_deflated_sharpe_ratio(many_trials, selected_sharpe, n_obs)

        assert many["expected_max_sharpe_under_null"] > few["expected_max_sharpe_under_null"]
        assert many["psr"] <= few["psr"]

    def test_weak_selected_sharpe_among_many_trials_fails_the_bar(self):
        # A mediocre Sharpe that just happened to be the best of a large sweep
        # should not clear the 95% PSR bar this codebase's go-live gate uses
        # elsewhere (backtest_engine.run_backtest's sharpe >= 1.0 floor is a
        # much lower bar than "is this Sharpe distinguishable from luck").
        rng = np.random.default_rng(3)
        trials = list(rng.normal(0.0, 0.4, size=50))
        selected_sharpe = max(trials + [0.3])
        result = compute_deflated_sharpe_ratio(trials + [0.3], selected_sharpe, n_observations=40)
        assert result["psr"] < 0.95

    def test_strong_selected_sharpe_with_many_observations_and_few_trials_passes(self):
        # A genuinely strong, well-observed Sharpe chosen from a small sweep
        # should survive the correction — the point of this metric is to
        # catch overfit sweep winners, not to reject every result.
        trials = [0.1, -0.2, 3.0]
        result = compute_deflated_sharpe_ratio(trials, selected_sharpe=3.0, n_observations=500)
        assert result["psr"] > 0.95

    def test_deflated_sharpe_is_selected_minus_expected_max(self):
        trials = [0.2, 0.4, 1.8, -0.1]
        result = compute_deflated_sharpe_ratio(trials, selected_sharpe=1.8, n_observations=80)
        assert result["deflated_sharpe"] == pytest.approx(
            round(1.8 - result["expected_max_sharpe_under_null"], 4)
        )

    def test_n_trials_and_n_observations_echoed_back(self):
        result = compute_deflated_sharpe_ratio([0.1, 0.2, 0.3], selected_sharpe=0.3, n_observations=42)
        assert result["n_trials"] == 3
        assert result["n_observations"] == 42


class TestDegenerateInputs:
    def test_all_identical_sharpe_ratios_no_crash(self):
        # Zero variance across trials (every trial performed identically) —
        # should fall back gracefully rather than dividing by zero.
        result = compute_deflated_sharpe_ratio([1.0, 1.0, 1.0], selected_sharpe=1.0, n_observations=50)
        assert result["expected_max_sharpe_under_null"] == 0.0
        assert 0.0 <= result["psr"] <= 1.0

    def test_negative_selected_sharpe_gives_low_psr(self):
        result = compute_deflated_sharpe_ratio(
            [-0.5, -0.3, -0.8, -0.2], selected_sharpe=-0.2, n_observations=60,
        )
        assert result["psr"] < 0.5
