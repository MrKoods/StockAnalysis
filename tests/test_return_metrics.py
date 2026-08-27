"""
Tests for the risk/return side of backtesting.metrics.

The annualization tests below are the important ones. V2 reported a Sharpe of
9.10 for weeks because a trade-indexed equity curve was annualized with
sqrt(252) as though each trade were a trading day — a single wrong constant that
made a mediocre strategy look extraordinary (docs/v2_postmortem.md).
"""

import math

import numpy as np
import pandas as pd
import pytest

from backtesting.metrics import (
    compute_cagr,
    compute_max_drawdown,
    compute_max_drawdown_duration,
    compute_sharpe,
    compute_sortino,
    compute_ulcer_index,
    summarize_returns,
)


class TestCAGR:
    def test_doubling_over_one_year(self):
        curve = pd.Series(np.linspace(100, 200, 253))
        assert compute_cagr(curve, periods_per_year=252) == pytest.approx(1.0, abs=0.01)

    def test_flat_curve_is_zero(self):
        assert compute_cagr(pd.Series([100.0] * 253)) == pytest.approx(0.0)

    def test_monthly_curve_uses_monthly_periods(self):
        curve = pd.Series([100.0 * (1.01 ** i) for i in range(13)])
        assert compute_cagr(curve, periods_per_year=12) == pytest.approx(0.1268, abs=0.001)

    def test_empty_and_single_point_return_zero(self):
        assert compute_cagr(pd.Series(dtype=float)) == 0.0
        assert compute_cagr(pd.Series([100.0])) == 0.0

    def test_non_positive_values_return_zero_not_complex(self):
        # A negative endpoint under a fractional exponent yields a complex
        # number in plain Python; guard rather than propagate.
        assert compute_cagr(pd.Series([100.0, -5.0])) == 0.0


class TestDrawdown:
    def test_simple_peak_to_trough(self):
        curve = pd.Series([100, 120, 90, 110])
        assert compute_max_drawdown(curve) == pytest.approx(0.25)

    def test_monotonic_rise_has_no_drawdown(self):
        assert compute_max_drawdown(pd.Series([100, 110, 120])) == pytest.approx(0.0)

    def test_duration_counts_steps_underwater(self):
        # Underwater at indices 2,3,4; recovers to a new high at index 5.
        curve = pd.Series([100, 120, 110, 105, 115, 130])
        assert compute_max_drawdown_duration(curve) == 3

    def test_duration_takes_the_longest_of_several_episodes(self):
        curve = pd.Series([100, 90, 110, 105, 104, 103, 120])
        assert compute_max_drawdown_duration(curve) == 3

    def test_depth_and_duration_are_independent(self):
        # Same 20% depth, very different time underwater — the reason both
        # numbers get reported instead of just the depth.
        brief = pd.Series([100, 80, 130])
        prolonged = pd.Series([100, 80, 85, 90, 95, 99, 130])
        assert compute_max_drawdown(brief) == pytest.approx(compute_max_drawdown(prolonged))
        assert compute_max_drawdown_duration(brief) < compute_max_drawdown_duration(prolonged)

    def test_ulcer_index_penalises_the_prolonged_case(self):
        brief = pd.Series([100, 80, 130, 131, 132, 133, 134])
        prolonged = pd.Series([100, 80, 85, 90, 95, 99, 134])
        assert compute_ulcer_index(prolonged) > compute_ulcer_index(brief)

    def test_empty_curves_return_zero(self):
        empty = pd.Series(dtype=float)
        assert compute_max_drawdown(empty) == 0.0
        assert compute_max_drawdown_duration(empty) == 0
        assert compute_ulcer_index(empty) == 0.0


class TestSharpeAnnualization:
    def test_periods_per_year_scales_by_its_square_root(self):
        rng = np.random.default_rng(0)
        returns = pd.Series(rng.normal(0.001, 0.01, size=500))
        daily = compute_sharpe(returns, risk_free_rate=0.0, periods_per_year=252)
        monthly = compute_sharpe(returns, risk_free_rate=0.0, periods_per_year=12)
        assert daily / monthly == pytest.approx(math.sqrt(252 / 12), rel=0.01)

    def test_the_v2_error_shape_inflates_sharpe(self):
        # 120 trade-level returns annualized as if daily vs. at their real
        # observed frequency (~30 trades/yr). The first is the V2 bug.
        rng = np.random.default_rng(1)
        trade_returns = pd.Series(rng.normal(0.01, 0.05, size=120))
        wrong = compute_sharpe(trade_returns, risk_free_rate=0.0, periods_per_year=252)
        right = compute_sharpe(trade_returns, risk_free_rate=0.0, periods_per_year=30)
        assert wrong > right * 2.5

    def test_zero_variance_returns_zero_not_inf(self):
        assert compute_sharpe(pd.Series([0.01] * 50)) == 0.0

    def test_empty_returns_zero(self):
        assert compute_sharpe(pd.Series(dtype=float)) == 0.0


class TestSortino:
    def test_upside_spread_changes_sharpe_but_not_sortino(self):
        # Identical mean and identical downside observations, different upside
        # shape. Sortino is unchanged because its denominator only sees the
        # downside; Sharpe falls for the wider-spread series because it
        # penalises the big winners too. This is the whole point of Sortino.
        tight = pd.Series([0.03, 0.03, -0.01, -0.02] * 25)
        wide = pd.Series([0.05, 0.01, -0.01, -0.02] * 25)

        assert tight.mean() == pytest.approx(wide.mean())
        assert compute_sortino(tight, risk_free_rate=0.0) == pytest.approx(
            compute_sortino(wide, risk_free_rate=0.0)
        )
        assert compute_sharpe(tight, risk_free_rate=0.0) > compute_sharpe(wide, risk_free_rate=0.0)

    def test_larger_winners_raise_sortino_when_downside_varies(self):
        steady = pd.Series([0.01, -0.01, 0.01, -0.02] * 25)
        spiky = pd.Series([0.05, -0.01, 0.05, -0.02] * 25)
        assert compute_sortino(spiky, risk_free_rate=0.0) > compute_sortino(steady, risk_free_rate=0.0)

    def test_no_downside_observations_returns_zero(self):
        assert compute_sortino(pd.Series([0.01] * 50), risk_free_rate=0.0) == 0.0

    def test_constant_downside_returns_zero_not_inf(self):
        # Every losing period identical -> zero downside deviation. Guarded
        # rather than dividing by zero.
        assert compute_sortino(pd.Series([0.01, -0.01] * 50), risk_free_rate=0.0) == 0.0

    def test_empty_returns_zero(self):
        assert compute_sortino(pd.Series(dtype=float)) == 0.0


class TestSummarizeReturns:
    def test_reports_the_standard_bundle(self):
        rng = np.random.default_rng(2)
        returns = pd.Series(rng.normal(0.0005, 0.01, size=1000))
        summary = summarize_returns(returns)
        assert set(summary) == {
            "cagr", "sharpe", "sortino", "max_drawdown",
            "max_drawdown_duration", "ulcer_index", "volatility", "n_periods",
        }
        assert summary["n_periods"] == 1000
        assert summary["max_drawdown"] > 0

    def test_empty_series_returns_a_zeroed_bundle(self):
        summary = summarize_returns(pd.Series(dtype=float))
        assert summary["n_periods"] == 0
        assert summary["sharpe"] == 0.0

    def test_nan_returns_are_treated_as_flat_periods(self):
        returns = pd.Series([0.01, np.nan, 0.01])
        assert summarize_returns(returns)["n_periods"] == 3
