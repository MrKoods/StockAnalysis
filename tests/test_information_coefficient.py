"""
Tests for the predictive-power metrics — the three functions that exist
specifically to stop this project fooling itself again (docs/v2_postmortem.md,
rules 2 and 10).
"""

import numpy as np
import pandas as pd
import pytest

from backtesting.metrics import (
    benjamini_hochberg_correction,
    bootstrap_ic_ci,
    bootstrap_mean_ci,
    compute_cross_sectional_ic,
    compute_information_coefficient,
)


class TestInformationCoefficient:
    def test_perfect_rank_agreement_scores_one(self):
        result = compute_information_coefficient([1, 2, 3, 4, 5], [10, 20, 30, 40, 50])
        assert result["ic"] == pytest.approx(1.0)
        assert result["n"] == 5

    def test_perfect_rank_inversion_scores_minus_one(self):
        result = compute_information_coefficient([1, 2, 3, 4, 5], [50, 40, 30, 20, 10])
        assert result["ic"] == pytest.approx(-1.0)

    def test_spearman_is_rank_based_not_linear(self):
        # A monotonic but wildly non-linear relationship is still a perfect
        # *rank* correlation — this is why IC uses Spearman by default.
        result = compute_information_coefficient([1, 2, 3, 4, 5], [1, 4, 9, 100, 10_000])
        assert result["ic"] == pytest.approx(1.0)

    def test_too_few_pairs_returns_neutral_not_nan(self):
        result = compute_information_coefficient([1, 2], [3, 4])
        assert result["ic"] == 0.0
        assert result["p_value"] == 1.0
        assert result["n"] == 2

    def test_constant_series_returns_neutral_not_nan(self):
        # scipy returns NaN for a zero-variance input; propagating that to a
        # caller would poison every downstream aggregate silently.
        result = compute_information_coefficient([5, 5, 5, 5], [1, 2, 3, 4])
        assert result["ic"] == 0.0
        assert result["p_value"] == 1.0

    def test_none_and_nan_pairs_are_dropped(self):
        result = compute_information_coefficient(
            [1, 2, None, 4, float("nan"), 6],
            [10, 20, 30, 40, 50, 60],
        )
        assert result["n"] == 4

    def test_noise_is_not_significant(self):
        rng = np.random.default_rng(0)
        result = compute_information_coefficient(
            rng.normal(size=500).tolist(),
            rng.normal(size=500).tolist(),
        )
        assert abs(result["ic"]) < 0.15
        assert result["p_value"] > 0.05


class TestCrossSectionalIC:
    def _panel(self, n_dates, n_names, ic_strength, seed=0):
        rng = np.random.default_rng(seed)
        rows = []
        for d in range(n_dates):
            scores = rng.normal(size=n_names)
            noise = rng.normal(size=n_names)
            fwd = ic_strength * scores + (1 - ic_strength) * noise
            for i in range(n_names):
                rows.append({"date": pd.Timestamp("2020-01-01") + pd.Timedelta(days=d),
                             "score": scores[i], "fwd": fwd[i]})
        return pd.DataFrame(rows)

    def test_detects_a_real_cross_sectional_signal(self):
        panel = self._panel(n_dates=120, n_names=50, ic_strength=0.3)
        result = compute_cross_sectional_ic(panel, "score", "fwd")
        assert result["mean_ic"] > 0.15
        assert result["t_stat"] > 3
        assert result["p_value"] < 0.01
        assert result["n_dates"] == 120

    def test_pure_noise_is_not_significant(self):
        panel = self._panel(n_dates=120, n_names=50, ic_strength=0.0, seed=7)
        result = compute_cross_sectional_ic(panel, "score", "fwd")
        assert abs(result["mean_ic"]) < 0.05
        assert result["p_value"] > 0.05

    def test_dates_with_too_few_names_are_skipped(self):
        panel = pd.DataFrame({
            "date": [pd.Timestamp("2020-01-01")] * 2 + [pd.Timestamp("2020-01-02")] * 5,
            "score": [1, 2, 1, 2, 3, 4, 5],
            "fwd": [1, 2, 1, 2, 3, 4, 5],
        })
        result = compute_cross_sectional_ic(panel, "score", "fwd")
        assert result["n_dates"] == 1

    def test_insufficient_dates_returns_neutral(self):
        panel = self._panel(n_dates=2, n_names=50, ic_strength=0.5)
        result = compute_cross_sectional_ic(panel, "score", "fwd")
        assert result["mean_ic"] == 0.0
        assert result["p_value"] == 1.0


class TestBootstrapICCI:
    def test_strong_signal_ci_excludes_zero(self):
        rng = np.random.default_rng(1)
        scores = rng.normal(size=300)
        returns = 0.6 * scores + 0.4 * rng.normal(size=300)
        result = bootstrap_ic_ci(scores.tolist(), returns.tolist(), n_bootstrap=500)
        assert result["ci_lower"] > 0
        assert result["n"] == 300

    def test_noise_ci_straddles_zero(self):
        rng = np.random.default_rng(2)
        result = bootstrap_ic_ci(
            rng.normal(size=300).tolist(),
            rng.normal(size=300).tolist(),
            n_bootstrap=500,
        )
        assert result["ci_lower"] < 0 < result["ci_upper"]

    def test_is_deterministic_across_calls(self):
        # A go/no-go verdict that flips between runs on identical data from
        # resampling noise alone would undermine the gate itself.
        rng = np.random.default_rng(3)
        scores, returns = rng.normal(size=100).tolist(), rng.normal(size=100).tolist()
        first = bootstrap_ic_ci(scores, returns, n_bootstrap=300)
        second = bootstrap_ic_ci(scores, returns, n_bootstrap=300)
        assert first == second

    def test_too_few_pairs_returns_zeros(self):
        result = bootstrap_ic_ci([1.0], [2.0])
        assert result == {"ic_mean": 0.0, "ci_lower": 0.0, "ci_upper": 0.0, "n": 1}


class TestBenjaminiHochberg:
    def test_the_v2_2_96_mistake_does_not_survive_correction(self):
        # The actual shape of the V2 error: one p=0.0501 reading among ~15
        # correlations computed in the same run, reported as a real finding.
        p_values = [0.0501] + [0.2, 0.35, 0.4, 0.5, 0.55, 0.6, 0.65,
                               0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 0.99]
        assert benjamini_hochberg_correction(p_values) == [False] * 15

    def test_genuinely_strong_findings_survive(self):
        p_values = [0.0001, 0.0002, 0.0005, 0.6, 0.7]
        result = benjamini_hochberg_correction(p_values)
        assert result[:3] == [True, True, True]
        assert result[3:] == [False, False]

    def test_a_lone_significant_p_value_survives(self):
        assert benjamini_hochberg_correction([0.01]) == [True]

    def test_step_up_flags_everything_below_the_largest_passing_rank(self):
        # BH is a step-up procedure: once rank k passes, every smaller p-value
        # is flagged too, even one that would fail its own rank threshold.
        # With n=4 the thresholds are 0.0125 / 0.025 / 0.0375 / 0.05, so 0.02
        # fails its own rank-1 bar but is still flagged because rank 2 passes.
        p_values = [0.02, 0.024, 0.5, 0.5]
        assert benjamini_hochberg_correction(p_values) == [True, True, False, False]

    def test_empty_input(self):
        assert benjamini_hochberg_correction([]) == []

    def test_order_is_preserved(self):
        result = benjamini_hochberg_correction([0.9, 0.0001, 0.8])
        assert result == [False, True, False]


class TestBootstrapMeanCI:
    def test_clearly_positive_mean_excludes_zero(self):
        rng = np.random.default_rng(4)
        values = (rng.normal(size=400) + 0.5).tolist()
        result = bootstrap_mean_ci(values, n_bootstrap=500)
        assert result["ci_lower"] > 0
        assert result["mean"] == pytest.approx(0.5, abs=0.15)

    def test_zero_centred_mean_straddles_zero(self):
        rng = np.random.default_rng(5)
        result = bootstrap_mean_ci(rng.normal(size=400).tolist(), n_bootstrap=500)
        assert result["ci_lower"] < 0 < result["ci_upper"]

    def test_empty_input_returns_zeros(self):
        assert bootstrap_mean_ci([]) == {"mean": 0.0, "ci_lower": 0.0, "ci_upper": 0.0, "n": 0}

    def test_all_nan_input_returns_zeros(self):
        assert bootstrap_mean_ci([float("nan"), float("nan")])["n"] == 0
