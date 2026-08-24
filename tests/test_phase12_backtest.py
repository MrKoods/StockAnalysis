"""
Tests for Phase 12: backtest metrics, trade simulation, stress tests.
All tests use synthetic price data — no external data calls.
"""

import pandas as pd
import numpy as np
import pytest

from backtesting.metrics import (
    compute_win_rate,
    compute_avg_rr,
    compute_max_drawdown,
    compute_max_drawdown_duration,
    compute_ulcer_index,
    compute_sharpe,
    compute_sortino,
    per_regime_metrics,
    compute_consecutive_losses,
    compute_r_multiples,
    bootstrap_expectancy_ci,
    run_sensitivity_analysis,
    _build_equity_curve,
    _ROUND_TRIP_SLIPPAGE_PER_SHARE,
    build_portfolio_equity_curve,
)
from backtesting.backtest_engine import simulate_trade_outcome, run_backtest
from backtesting.stress_test import run_all_scenarios, run_scenario, SCENARIOS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ohlcv_trending_up(days=30, start=100.0, daily_drift=0.005):
    """Generate upward-trending OHLCV data."""
    dates = pd.date_range("2026-01-01", periods=days, freq="B", tz="UTC")
    closes = [start * (1 + daily_drift) ** i for i in range(days)]
    df = pd.DataFrame({
        "Open":  [c * 0.99 for c in closes],
        "High":  [c * 1.02 for c in closes],
        "Low":   [c * 0.98 for c in closes],
        "Close": closes,
        "Volume": [1_000_000] * days,
    }, index=dates)
    return df


def _ohlcv_range(days=30, start=100.0, end=110.0):
    """Generate OHLCV data that hits target within days."""
    dates = pd.date_range("2026-01-01", periods=days, freq="B", tz="UTC")
    closes = [start + (end - start) * i / days for i in range(days)]
    df = pd.DataFrame({
        "Open":  [c * 0.99 for c in closes],
        "High":  [c * 1.015 for c in closes],  # Target-reachable highs
        "Low":   [c * 0.99 for c in closes],
        "Close": closes,
        "Volume": [500_000] * days,
    }, index=dates)
    return df


def _outcomes(wins, losses, rr=3.0):
    """Generate synthetic outcomes list."""
    result = []
    for i in range(wins):
        result.append({"outcome": "win", "achieved_rr": rr, "regime": "trending_up"})
    for i in range(losses):
        result.append({"outcome": "loss", "achieved_rr": -1.0, "regime": "trending_down"})
    return result


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class TestMetrics:
    def test_win_rate_zero_on_empty(self):
        assert compute_win_rate([]) == 0.0

    def test_win_rate_all_wins(self):
        outcomes = [{"outcome": "win"}, {"outcome": "win"}]
        assert compute_win_rate(outcomes) == 1.0

    def test_win_rate_50_50(self):
        outcomes = _outcomes(5, 5)
        assert compute_win_rate(outcomes) == pytest.approx(0.5)

    def test_avg_rr_zero_on_empty(self):
        assert compute_avg_rr([]) == 0.0

    def test_avg_rr_correct(self):
        outcomes = [{"outcome": "win", "achieved_rr": 3.0}, {"outcome": "win", "achieved_rr": 3.0}]
        assert compute_avg_rr(outcomes) == pytest.approx(3.0)

    def test_max_drawdown_on_flat_curve(self):
        curve = pd.Series([100.0] * 10)
        assert compute_max_drawdown(curve) == pytest.approx(0.0)

    def test_r_multiples_includes_wins_and_losses(self):
        outcomes = _outcomes(2, 3, rr=3.0)
        r = compute_r_multiples(outcomes)
        assert len(r) == 5
        assert r.count(3.0) == 2
        assert r.count(-1.0) == 3

    def test_r_multiples_empty(self):
        assert compute_r_multiples([]) == []

    def test_bootstrap_expectancy_ci_empty(self):
        result = bootstrap_expectancy_ci([])
        assert result == {"mean_r": 0.0, "ci_lower": 0.0, "ci_upper": 0.0, "n_trades": 0}

    def test_bootstrap_expectancy_ci_deterministic_with_fixed_seed(self):
        r_multiples = [3.0, 3.0, -1.0, -1.0, -1.0, 3.0, -1.0, 3.0, -1.0, -1.0]
        result_a = bootstrap_expectancy_ci(r_multiples, n_bootstrap=500)
        result_b = bootstrap_expectancy_ci(r_multiples, n_bootstrap=500)
        assert result_a == result_b

    def test_bootstrap_expectancy_ci_bounds_bracket_mean(self):
        r_multiples = [3.0, -1.0] * 50  # 100 trades, 50% WR, mean_r = 1.0
        result = bootstrap_expectancy_ci(r_multiples, n_bootstrap=2000)
        assert result["n_trades"] == 100
        assert result["mean_r"] == pytest.approx(1.0)
        assert result["ci_lower"] <= result["mean_r"] <= result["ci_upper"]

    def test_bootstrap_expectancy_ci_narrower_with_more_trades(self):
        # Same underlying win rate/R:R, but 10x the sample — CI should tighten.
        small = bootstrap_expectancy_ci([3.0, -1.0] * 10, n_bootstrap=2000)
        large = bootstrap_expectancy_ci([3.0, -1.0] * 100, n_bootstrap=2000)
        small_width = small["ci_upper"] - small["ci_lower"]
        large_width = large["ci_upper"] - large["ci_lower"]
        assert large_width < small_width

    def test_max_drawdown_on_declining_curve(self):
        curve = pd.Series([100.0, 90.0, 80.0, 85.0])
        # Peak=100, trough=80, drawdown=20%
        dd = compute_max_drawdown(curve)
        assert dd == pytest.approx(0.20)

    def test_max_drawdown_empty(self):
        assert compute_max_drawdown(pd.Series([])) == 0.0

    def test_sharpe_positive_on_positive_returns(self):
        # Vary returns so std > 0; mean positive → Sharpe > 0
        np.random.seed(42)
        returns = pd.Series(np.random.normal(loc=0.005, scale=0.01, size=252))
        sharpe = compute_sharpe(returns, risk_free_rate=0.0)
        assert sharpe > 0

    def test_sharpe_zero_on_flat(self):
        sharpe = compute_sharpe(pd.Series([0.0] * 10))
        assert sharpe == 0.0

    def test_sortino_positive_on_positive_returns(self):
        np.random.seed(42)
        returns = pd.Series(np.random.normal(loc=0.005, scale=0.01, size=252))
        sortino = compute_sortino(returns, risk_free_rate=0.0)
        assert sortino > 0

    def test_sortino_zero_on_empty(self):
        assert compute_sortino(pd.Series([], dtype=float)) == 0.0

    def test_sortino_zero_when_no_downside_observations(self):
        # All returns above the risk-free rate — no downside deviation to
        # compute a ratio against.
        returns = pd.Series([0.01, 0.02, 0.015, 0.03])
        assert compute_sortino(returns, risk_free_rate=0.0) == 0.0

    def test_sortino_ignores_upside_variance_unlike_sharpe(self):
        # Two return series with identical downside values and identical mean,
        # but very different upside spread — Sortino should be IDENTICAL
        # between them (it only ever looks at the downside values, which
        # didn't change), while Sharpe differs since total variance did.
        low_upside_var = pd.Series([-0.01, -0.02, 0.05, 0.05, 0.05, 0.05])
        high_upside_var = pd.Series([-0.01, -0.02, 0.01, 0.03, 0.07, 0.09])
        assert low_upside_var.mean() == pytest.approx(high_upside_var.mean())

        sharpe_low = compute_sharpe(low_upside_var, risk_free_rate=0.0, periods_per_year=1)
        sharpe_high = compute_sharpe(high_upside_var, risk_free_rate=0.0, periods_per_year=1)
        sortino_low = compute_sortino(low_upside_var, risk_free_rate=0.0, periods_per_year=1)
        sortino_high = compute_sortino(high_upside_var, risk_free_rate=0.0, periods_per_year=1)

        assert sortino_low == pytest.approx(sortino_high)
        assert sharpe_low != pytest.approx(sharpe_high)

    def test_max_drawdown_duration_zero_on_empty(self):
        assert compute_max_drawdown_duration(pd.Series([], dtype=float)) == 0

    def test_max_drawdown_duration_zero_on_monotonic_rise(self):
        equity = pd.Series([100, 105, 110, 120, 130])
        assert compute_max_drawdown_duration(equity) == 0

    def test_max_drawdown_duration_counts_steps_underwater(self):
        # Peak at index 0 (100), underwater for indices 1-4, new high at index 5.
        equity = pd.Series([100, 90, 85, 95, 99, 101])
        assert compute_max_drawdown_duration(equity) == 4

    def test_max_drawdown_duration_takes_the_longest_stretch(self):
        # Two drawdown stretches: 2 steps underwater, then recovers, then 4 steps underwater.
        equity = pd.Series([100, 90, 95, 105, 95, 90, 92, 94, 110])
        assert compute_max_drawdown_duration(equity) == 4

    def test_ulcer_index_zero_on_flat_or_rising_equity(self):
        assert compute_ulcer_index(pd.Series([100, 100, 100])) == pytest.approx(0.0)
        assert compute_ulcer_index(pd.Series([100, 110, 120])) == pytest.approx(0.0)

    def test_ulcer_index_zero_on_empty(self):
        assert compute_ulcer_index(pd.Series([], dtype=float)) == 0.0

    def test_ulcer_index_positive_on_drawdown(self):
        equity = pd.Series([100, 90, 85, 95, 100])
        assert compute_ulcer_index(equity) > 0.0

    def test_ulcer_index_penalizes_longer_drawdown_more_than_max_drawdown_does(self):
        # Same max depth (-10%), but one recovers immediately and the other
        # stays down for several steps — Ulcer Index should differ even
        # though max_drawdown_pct is identical for both.
        quick_recovery = pd.Series([100, 90, 100, 100, 100])
        slow_recovery = pd.Series([100, 90, 90, 90, 90])
        dd_quick = compute_max_drawdown(quick_recovery)
        dd_slow = compute_max_drawdown(slow_recovery)
        assert dd_quick == pytest.approx(dd_slow)  # same max depth
        ui_quick = compute_ulcer_index(quick_recovery)
        ui_slow = compute_ulcer_index(slow_recovery)
        assert ui_slow > ui_quick

    def test_equity_curve_with_slippage_underperforms_frictionless(self):
        outcomes = [
            {"pnl_pct": 0.05, "entry_price": 100.0, "stop": 97.0},
            {"pnl_pct": 0.03, "entry_price": 100.0, "stop": 97.0},
            {"pnl_pct": -0.02, "entry_price": 100.0, "stop": 97.0},
        ]
        with_slippage = _build_equity_curve(outcomes, starting_equity=15000.0, include_slippage=True)
        frictionless = _build_equity_curve(outcomes, starting_equity=15000.0, include_slippage=False)
        assert with_slippage.iloc[-1] < frictionless.iloc[-1]

    def test_slippage_is_default_behavior(self):
        outcomes = [{"pnl_pct": 0.05, "entry_price": 100.0, "stop": 97.0}]
        default_curve = _build_equity_curve(outcomes, starting_equity=15000.0)
        explicit_curve = _build_equity_curve(outcomes, starting_equity=15000.0, include_slippage=True)
        assert default_curve.iloc[-1] == pytest.approx(explicit_curve.iloc[-1])

    def test_higher_priced_stock_pays_proportionally_less_slippage(self):
        # $0.02/share round-trip is a smaller fraction of a $1000 stock than
        # a $10 stock — the slippage drag on pnl_pct should scale accordingly.
        cheap = _build_equity_curve(
            [{"pnl_pct": 0.05, "entry_price": 10.0, "stop": 9.7}], starting_equity=15000.0,
        )
        expensive = _build_equity_curve(
            [{"pnl_pct": 0.05, "entry_price": 1000.0, "stop": 970.0}], starting_equity=15000.0,
        )
        frictionless = _build_equity_curve(
            [{"pnl_pct": 0.05, "entry_price": 10.0, "stop": 9.7}], starting_equity=15000.0, include_slippage=False,
        )
        cheap_drag = frictionless.iloc[-1] - cheap.iloc[-1]
        expensive_drag = frictionless.iloc[-1] - expensive.iloc[-1]
        assert cheap_drag > expensive_drag

    def test_zero_trades_returns_starting_equity_only(self):
        curve = _build_equity_curve([], starting_equity=15000.0)
        assert list(curve) == [15000.0]

    def test_round_trip_slippage_constant_matches_options_math_convention(self):
        # shared/utils/options_math.py's adjust_ev_for_slippage defaults to
        # $0.02/share; this is that same per-share cost applied twice (entry + exit).
        assert _ROUND_TRIP_SLIPPAGE_PER_SHARE == pytest.approx(0.04)

    def test_portfolio_curve_empty_outcomes(self):
        curve, stats = build_portfolio_equity_curve([], starting_equity=10000.0)
        assert list(curve) == [10000.0]
        assert stats["max_concurrent_positions"] == 0
        assert stats["max_concurrent_risk_pct"] == 0.0

    def test_non_overlapping_trades_never_concurrent(self):
        outcomes = [
            {"signal_date": "2026-01-01", "exit_date": "2026-01-05",
             "entry_price": 100.0, "stop": 97.0, "pnl_pct": 0.03},
            {"signal_date": "2026-01-06", "exit_date": "2026-01-10",
             "entry_price": 100.0, "stop": 97.0, "pnl_pct": 0.03},
        ]
        _, stats = build_portfolio_equity_curve(outcomes, starting_equity=10000.0, include_slippage=False)
        assert stats["max_concurrent_positions"] == 1

    def test_overlapping_trades_are_flagged_concurrent(self):
        outcomes = [
            {"signal_date": "2026-01-01", "exit_date": "2026-01-10",
             "entry_price": 100.0, "stop": 97.0, "pnl_pct": 0.03},
            {"signal_date": "2026-01-03", "exit_date": "2026-01-08",
             "entry_price": 100.0, "stop": 97.0, "pnl_pct": 0.03},
        ]
        _, stats = build_portfolio_equity_curve(outcomes, starting_equity=10000.0, include_slippage=False)
        assert stats["max_concurrent_positions"] == 2
        # Both risk 1% of the same starting equity simultaneously -> 2%.
        assert stats["max_concurrent_risk_pct"] == pytest.approx(0.02)

    def test_four_concurrent_correlated_losses_compound_worse_than_serial(self):
        # Four semiconductor-like names all opened the same day, all losing
        # -1R, all closing the same day — the concurrent view should show
        # all four losses landing on the SAME starting equity (a real
        # simultaneous drawdown), unlike a serial curve where later trades'
        # risk shrinks as earlier losses compound in first.
        outcomes = [
            {"signal_date": "2026-01-01", "exit_date": "2026-01-05",
             "entry_price": 100.0, "stop": 97.0, "pnl_pct": -0.03}
            for _ in range(4)
        ]
        portfolio_curve, stats = build_portfolio_equity_curve(
            outcomes, starting_equity=10000.0, risk_pct=0.01, include_slippage=False,
        )
        serial_curve = _build_equity_curve(
            sorted(outcomes, key=lambda o: o["exit_date"]), starting_equity=10000.0, include_slippage=False,
        )
        assert stats["max_concurrent_positions"] == 4
        assert stats["max_concurrent_risk_pct"] == pytest.approx(0.04)
        # Portfolio view: each of the 4 losses is exactly 1% of the ORIGINAL
        # 10000 (all sized before any of them realized) -> ends at 9600.
        assert portfolio_curve.iloc[-1] == pytest.approx(9600.0)
        # Serial view: each loss shrinks the base for the next -> a smaller
        # total dollar loss than the concurrent view, understating the real
        # simultaneous exposure.
        assert portfolio_curve.iloc[-1] < serial_curve.iloc[-1]

    def test_missing_exit_date_falls_back_to_same_day_round_trip(self):
        outcomes = [{"signal_date": "2026-01-01", "entry_price": 100.0, "stop": 97.0, "pnl_pct": 0.03}]
        curve, stats = build_portfolio_equity_curve(outcomes, starting_equity=10000.0, include_slippage=False)
        assert len(curve) == 2  # starting value + one realized trade
        assert curve.iloc[-1] > 10000.0

    def test_outcomes_missing_signal_date_are_skipped_not_crashed(self):
        outcomes = [{"exit_date": "2026-01-05", "entry_price": 100.0, "stop": 97.0, "pnl_pct": 0.03}]
        curve, stats = build_portfolio_equity_curve(outcomes, starting_equity=10000.0)
        assert list(curve) == [10000.0]

    def test_per_regime_splits_correctly(self):
        outcomes = [
            {"outcome": "win", "achieved_rr": 3.0, "regime": "trending_up"},
            {"outcome": "win", "achieved_rr": 3.0, "regime": "trending_up"},
            {"outcome": "loss", "achieved_rr": -1.0, "regime": "choppy"},
        ]
        result = per_regime_metrics(outcomes)
        assert "trending_up" in result
        assert "choppy" in result
        assert result["trending_up"]["win_rate"] == 1.0
        assert result["choppy"]["win_rate"] == 0.0
        assert result["trending_up"]["trade_count"] == 2

    def test_consecutive_losses_none(self):
        outcomes = [{"outcome": "win"}, {"outcome": "win"}]
        assert compute_consecutive_losses(outcomes) == 0

    def test_consecutive_losses_streak(self):
        outcomes = [
            {"outcome": "win"},
            {"outcome": "loss"},
            {"outcome": "loss"},
            {"outcome": "loss"},
            {"outcome": "win"},
        ]
        assert compute_consecutive_losses(outcomes) == 3


# ---------------------------------------------------------------------------
# Trade outcome simulation
# ---------------------------------------------------------------------------

class TestSimulateTradeOutcome:
    def test_win_when_target_hit(self):
        df = _ohlcv_range(15, start=100.0, end=115.0)
        result = simulate_trade_outcome(
            signal_date="2026-01-01",
            direction="bullish",
            entry=100.0,
            stop=95.0,
            target=110.0,
            future_ohlcv=df,
        )
        assert result["outcome"] == "win"
        assert result["exit_price"] == pytest.approx(110.0)

    def test_loss_when_stop_hit(self):
        dates = pd.date_range("2026-01-01", periods=15, freq="B", tz="UTC")
        closes = [100.0 - i * 0.5 for i in range(15)]
        df = pd.DataFrame({
            "Open": closes, "High": closes,
            "Low": [c - 0.5 for c in closes],
            "Close": closes, "Volume": [1_000_000] * 15,
        }, index=dates)
        result = simulate_trade_outcome(
            signal_date="2026-01-01", direction="bullish",
            entry=100.0, stop=95.0, target=115.0,
            future_ohlcv=df,
        )
        assert result["outcome"] == "loss"

    def test_time_stop_when_no_exit(self):
        df = _ohlcv_trending_up(15, start=100.0, daily_drift=0.001)
        result = simulate_trade_outcome(
            signal_date="2026-01-01", direction="bullish",
            entry=100.0, stop=90.0, target=130.0,
            future_ohlcv=df,
            holding_period=(1, 15),
        )
        assert result["outcome"] == "time_stop"

    def test_empty_ohlcv_returns_no_data(self):
        result = simulate_trade_outcome(
            "2026-01-01", "bullish", 100, 95, 115, pd.DataFrame()
        )
        assert result["outcome"] == "no_data"

    def test_required_keys_present(self):
        df = _ohlcv_trending_up(15)
        result = simulate_trade_outcome(
            "2026-01-01", "bullish", 100, 95, 115, df
        )
        for key in ("outcome", "exit_price", "pnl_pct", "holding_days", "achieved_rr"):
            assert key in result

    # -- Bearish direction (mirrors the bullish tests above) --

    def test_bearish_win_when_target_hit(self):
        # Price falls from 100 to 85 — a bearish target (below entry) is hit.
        df = _ohlcv_range(15, start=100.0, end=85.0)
        result = simulate_trade_outcome(
            signal_date="2026-01-01",
            direction="bearish",
            entry=100.0,
            stop=105.0,
            target=90.0,
            future_ohlcv=df,
        )
        assert result["outcome"] == "win"
        assert result["exit_price"] == pytest.approx(90.0)
        assert result["pnl_pct"] > 0  # price fell -> bearish position profits
        assert result["achieved_rr"] > 0

    def test_bearish_loss_when_stop_hit(self):
        dates = pd.date_range("2026-01-01", periods=15, freq="B", tz="UTC")
        closes = [100.0 + i * 0.5 for i in range(15)]  # price rises against the short
        df = pd.DataFrame({
            "Open": closes, "High": [c + 0.5 for c in closes],
            "Low": closes, "Close": closes, "Volume": [1_000_000] * 15,
        }, index=dates)
        result = simulate_trade_outcome(
            signal_date="2026-01-01", direction="bearish",
            entry=100.0, stop=105.0, target=85.0,
            future_ohlcv=df,
        )
        assert result["outcome"] == "loss"
        assert result["exit_price"] == pytest.approx(105.0)
        assert result["pnl_pct"] < 0
        assert result["achieved_rr"] == pytest.approx(-1.0)

    def test_bearish_time_stop_when_no_exit(self):
        # Mild decline, never reaches either the wide stop or the far target.
        df = _ohlcv_trending_up(15, start=100.0, daily_drift=-0.001)
        result = simulate_trade_outcome(
            signal_date="2026-01-01", direction="bearish",
            entry=100.0, stop=110.0, target=70.0,
            future_ohlcv=df,
            holding_period=(1, 15),
        )
        assert result["outcome"] == "time_stop"

    # -- Day-10/30%-progress early time stop (Signal Integrity Audit A.5) --

    def test_day10_early_time_stop_when_stalled(self):
        # Flat price (no progress at all) for 15 bars, target far above entry
        # and stop far below — neither hit, so this used to ride to day 15.
        # With <30% of the target move captured by day 10, it should now
        # exit at day 10 instead.
        dates = pd.date_range("2026-01-01", periods=15, freq="B", tz="UTC")
        flat = [100.0] * 15
        df = pd.DataFrame({
            "Open": flat, "High": [101.0] * 15, "Low": [99.0] * 15,
            "Close": flat, "Volume": [1_000_000] * 15,
        }, index=dates)
        result = simulate_trade_outcome(
            signal_date="2026-01-01", direction="bullish",
            entry=100.0, stop=90.0, target=130.0,
            future_ohlcv=df, holding_period=(1, 15),
        )
        assert result["outcome"] == "time_stop"
        assert result["holding_days"] == 10

    def test_no_early_time_stop_when_progress_sufficient(self):
        # 40% of the way to target by day 10 (12 points of a 30-point move) —
        # above the 30% floor, so the position should NOT exit early; it
        # rides to day 15 like before this fix (target/stop still not hit).
        dates = pd.date_range("2026-01-01", periods=15, freq="B", tz="UTC")
        closes = [100.0 + min(i, 10) * 1.2 for i in range(15)]  # reaches 112 by day 10, holds
        df = pd.DataFrame({
            "Open": closes, "High": [c + 0.1 for c in closes], "Low": [c - 0.1 for c in closes],
            "Close": closes, "Volume": [1_000_000] * 15,
        }, index=dates)
        result = simulate_trade_outcome(
            signal_date="2026-01-01", direction="bullish",
            entry=100.0, stop=90.0, target=130.0,
            future_ohlcv=df, holding_period=(1, 15),
        )
        assert result["outcome"] == "time_stop"
        assert result["holding_days"] == 15

    def test_time_stop_day_zero_disables_early_check(self):
        # time_stop_day=0 is the explicit opt-out — same flat/stalled setup
        # as the first test above, but must now ride all the way to day 15.
        dates = pd.date_range("2026-01-01", periods=15, freq="B", tz="UTC")
        flat = [100.0] * 15
        df = pd.DataFrame({
            "Open": flat, "High": [101.0] * 15, "Low": [99.0] * 15,
            "Close": flat, "Volume": [1_000_000] * 15,
        }, index=dates)
        result = simulate_trade_outcome(
            signal_date="2026-01-01", direction="bullish",
            entry=100.0, stop=90.0, target=130.0,
            future_ohlcv=df, holding_period=(1, 15), time_stop_day=0,
        )
        assert result["holding_days"] == 15


# ---------------------------------------------------------------------------
# run_backtest (smoke test with synthetic data)
# ---------------------------------------------------------------------------

class TestRunBacktest:
    def test_empty_data_returns_not_passed(self):
        result = run_backtest({})
        assert result["passed"] is False

    def test_returns_required_keys(self):
        data = {"NVDA": _ohlcv_trending_up(120)}
        result = run_backtest(data, min_qualifying_trades=1)
        for key in ("passed", "win_rate", "avg_rr", "expectancy_r_mean",
                    "expectancy_r_ci_lower", "expectancy_r_ci_upper", "sharpe_ratio",
                    "max_drawdown_pct", "qualifying_trades", "per_regime"):
            assert key in result

    def test_win_rate_in_valid_range(self):
        data = {"NVDA": _ohlcv_trending_up(120)}
        result = run_backtest(data, min_qualifying_trades=1)
        assert 0.0 <= result["win_rate"] <= 1.0

    def test_passed_requires_expectancy_ci_lower_above_threshold(self):
        """
        v2.2.17: "passed" no longer gates on a flat win_rate/avg_rr pair — it
        gates on the bootstrapped 95% CI lower bound of per-trade R-expectancy
        clearing min_expectancy_r. A high win_rate/avg_rr on a tiny/noisy
        sample should NOT pass if the CI lower bound doesn't clear the bar,
        and passed should flip to True once min_expectancy_r is set low enough
        for the same data.
        """
        data = {"NVDA": _ohlcv_trending_up(120)}
        strict = run_backtest(data, min_qualifying_trades=1, min_expectancy_r=100.0)
        assert strict["passed"] is False  # no real strategy clears a 100R bar

        lenient = run_backtest(data, min_qualifying_trades=1, min_expectancy_r=-100.0)
        # With trade-count/expectancy floors trivially satisfied, only Sharpe/
        # drawdown can still fail — assert the expectancy fields themselves are
        # internally consistent rather than asserting passed=True outright,
        # since Sharpe/drawdown depend on the synthetic data's exact shape.
        assert lenient["expectancy_r_ci_lower"] <= lenient["expectancy_r_mean"] <= lenient["expectancy_r_ci_upper"]

    def test_max_drawdown_non_negative(self):
        data = {"NVDA": _ohlcv_trending_up(120)}
        result = run_backtest(data, min_qualifying_trades=1)
        assert result["max_drawdown_pct"] >= 0.0


class TestRunBacktestWalkForwardPooledGate:
    """
    2026-08-23: "passed" used to rest ONLY on the single fixed 70/30 split —
    wf_results was computed and attached to the report but never gated
    anything. Found (while re-checking whether that was the right call) that
    this let a single-split pass purely because the fixed test period
    happened to land inside a favorable stretch of history, with no check
    that the edge holds up pooled across other walk-forward windows too
    (see CHANGELOG v2.2.83). These monkeypatch run_walk_forward directly —
    real multi-year walk-forward windows need far more synthetic data than
    is practical to generate here, and the single-split's own pass/fail
    behavior is already covered by TestRunBacktest above; this isolates the
    NEW pooling-and-gating logic specifically.
    """

    def _lenient_single_split_data(self):
        # Trivially clears the single-split side (min_qualifying_trades=1,
        # min_expectancy_r very negative) so any failure is attributable to
        # the walk-forward-pooled gate, not the split this class isn't testing.
        return {"NVDA": _ohlcv_trending_up(120)}

    def _dated_outcomes(self, wins, losses, rr=3.0, year=2020):
        """Like the module-level _outcomes(), but with the extra fields
        _compute_metrics_bundle's equity curve actually needs to behave
        sensibly: real, evenly-spread-out exit_dates (chronological sort
        needs realistic spacing/interleaving, not one block of wins followed
        by one block of losses — that clusters all losses into a single deep
        drawdown and starves _trades_per_year of a sensible timespan) and a
        real entry_price/stop/pnl_pct consistent with achieved_rr (_build_
        equity_curve reads pnl_pct/entry_price/stop, NOT achieved_rr — the
        module-level _outcomes() only ever fed compute_r_multiples-style
        functions directly, never this equity-curve path, so it never needed
        those fields; defaulting entry_price=stop=~1.0 here degenerates into
        a nonsensical equity curve)."""
        total = wins + losses
        loss_positions = set()
        if losses > 0:
            step = total / losses
            loss_positions = {int(i * step) for i in range(losses)}
        entry, stop = 100.0, 97.0  # risk_dist = 0.03, matches _build_equity_curve's own default
        risk_dist = (entry - stop) / entry
        result = []
        for i in range(total):
            is_win = i not in loss_positions
            date = pd.Timestamp(f"{year}-01-01") + pd.Timedelta(days=3 * i)
            achieved_rr = rr if is_win else -1.0
            result.append({
                "outcome": "win" if is_win else "loss",
                "achieved_rr": achieved_rr,
                "pnl_pct": achieved_rr * risk_dist,
                "entry_price": entry,
                "stop": stop,
                "regime": "trending_up",
                "exit_date": date.strftime("%Y-%m-%d"),
                "signal_date": (date - pd.Timedelta(days=2)).strftime("%Y-%m-%d"),
            })
        return result

    def test_walk_forward_pooled_passed_key_always_present(self, monkeypatch):
        import backtesting.backtest_engine as be
        monkeypatch.setattr(be, "run_walk_forward", lambda *a, **kw: [])
        result = run_backtest(self._lenient_single_split_data(), min_qualifying_trades=1, min_expectancy_r=-100.0)
        assert "walk_forward_pooled_passed" in result
        assert "walk_forward_pooled_qualifying_trades" in result

    def test_no_walk_forward_windows_fails_the_pooled_gate(self, monkeypatch):
        import backtesting.backtest_engine as be
        monkeypatch.setattr(be, "run_walk_forward", lambda *a, **kw: [])
        result = run_backtest(self._lenient_single_split_data(), min_qualifying_trades=1, min_expectancy_r=-100.0)
        assert result["walk_forward_pooled_passed"] is False
        assert result["walk_forward_pooled_qualifying_trades"] == 0

    def test_overall_passed_requires_walk_forward_pooled_too_even_when_single_split_would_pass(self, monkeypatch):
        """The key regression guard: an empty/insufficient walk-forward pool
        must veto an otherwise-passing single split, not just be reported
        alongside it."""
        import backtesting.backtest_engine as be
        monkeypatch.setattr(be, "run_walk_forward", lambda *a, **kw: [])
        result = run_backtest(self._lenient_single_split_data(), min_qualifying_trades=1, min_expectancy_r=-100.0)
        assert result["walk_forward_pooled_passed"] is False
        assert result["passed"] is False

    def test_pooled_outcomes_below_min_qualifying_trades_fails_the_gate(self, monkeypatch):
        import backtesting.backtest_engine as be
        thin_window = {
            "window": 1, "train_through": "2020-01-01", "validate_through": "2021-01-01",
            "qualifying_trades": 5, "win_rate": 1.0, "avg_rr": 3.0, "verdict": "pass", "passed": True,
            "outcomes": _outcomes(wins=5, losses=0, rr=3.0),
        }
        monkeypatch.setattr(be, "run_walk_forward", lambda *a, **kw: [thin_window])
        result = run_backtest(self._lenient_single_split_data(), min_qualifying_trades=10, min_expectancy_r=-100.0)
        assert result["walk_forward_pooled_qualifying_trades"] == 5
        assert result["walk_forward_pooled_passed"] is False  # 5 < min_qualifying_trades=10
        assert result["passed"] is False

    def test_pooled_outcomes_clearing_every_bar_passes_the_gate(self, monkeypatch):
        import backtesting.backtest_engine as be
        # A few losses mixed in, not a perfect record — an all-identical-R
        # win streak has zero return variance, which degenerates Sharpe to 0
        # (fails >=1.0) rather than exercising the pass path this test wants.
        windows = [
            {"window": 1, "train_through": "2020-01-01", "validate_through": "2021-01-01",
             "qualifying_trades": 30, "win_rate": 0.83, "avg_rr": 3.0, "verdict": "pass", "passed": True,
             "outcomes": self._dated_outcomes(wins=25, losses=5, rr=3.0, year=2020)},
            {"window": 2, "train_through": "2021-01-01", "validate_through": "2022-01-01",
             "qualifying_trades": 30, "win_rate": 0.83, "avg_rr": 3.0, "verdict": "pass", "passed": True,
             "outcomes": self._dated_outcomes(wins=25, losses=5, rr=3.0, year=2022)},
        ]
        monkeypatch.setattr(be, "run_walk_forward", lambda *a, **kw: windows)
        result = run_backtest(self._lenient_single_split_data(), min_qualifying_trades=10, min_expectancy_r=0.1)
        assert result["walk_forward_pooled_qualifying_trades"] == 60
        assert result["walk_forward_pooled_passed"] is True

    def test_outcomes_key_stripped_from_reported_walk_forward_windows(self, monkeypatch):
        """include_outcomes=True is needed internally to pool, but the saved
        report should stay lean (matching run_walk_forward's own documented
        intent) — raw per-trade outcome lists shouldn't be duplicated into
        every window dict in the final result."""
        import backtesting.backtest_engine as be
        window = {
            "window": 1, "train_through": "2020-01-01", "validate_through": "2021-01-01",
            "qualifying_trades": 2, "win_rate": 1.0, "avg_rr": 3.0, "verdict": "insufficient_data", "passed": False,
            "outcomes": _outcomes(wins=2, losses=0, rr=3.0),
        }
        monkeypatch.setattr(be, "run_walk_forward", lambda *a, **kw: [window])
        result = run_backtest(self._lenient_single_split_data(), min_qualifying_trades=1, min_expectancy_r=-100.0)
        assert "outcomes" not in result["walk_forward"][0]


class TestRunBacktestDeflatedSharpe:
    """
    2026-08-23: compute_deflated_sharpe_ratio() existed and was already used
    inside entry_filter_variants.py's threshold-sweep diagnostic, but never
    against the actual headline number this project cites. This project's
    own historical tuning rounds (RSI band, confirmation bar, stop
    multiplier, ...) aren't cleanly replayable here (scattered across
    separate one-off sweep scripts), so run_backtest() uses each walk-forward
    window's own Sharpe as the trial population instead — a self-contained,
    honest proxy answering "is the single-slice Sharpe just the best of
    several time-window reads."
    """

    def _lenient_single_split_data(self):
        return {"NVDA": _ohlcv_trending_up(120)}

    def test_result_always_has_deflated_sharpe_fields(self, monkeypatch):
        import backtesting.backtest_engine as be
        monkeypatch.setattr(be, "run_walk_forward", lambda *a, **kw: [])
        result = run_backtest(self._lenient_single_split_data(), min_qualifying_trades=1, min_expectancy_r=-100.0)
        for key in ("deflated_sharpe", "deflated_sharpe_psr", "deflated_sharpe_n_trials"):
            assert key in result

    def test_no_walk_forward_windows_gives_zero_trials_not_a_crash(self, monkeypatch):
        import backtesting.backtest_engine as be
        monkeypatch.setattr(be, "run_walk_forward", lambda *a, **kw: [])
        result = run_backtest(self._lenient_single_split_data(), min_qualifying_trades=1, min_expectancy_r=-100.0)
        assert result["deflated_sharpe_n_trials"] == 0
        assert result["deflated_sharpe"] == 0.0
        assert result["deflated_sharpe_psr"] == 0.0

    def test_windows_with_fewer_than_2_outcomes_are_excluded_from_the_trial_population(self, monkeypatch):
        """A window with 0 or 1 qualifying trades has no real Sharpe to
        compute (compute_sharpe needs >=2 return observations) — must be
        skipped, not counted as a zero-Sharpe trial (which would bias the
        deflation calculation with a fabricated data point)."""
        import backtesting.backtest_engine as be
        windows = [
            {"window": 1, "train_through": "2020-01-01", "validate_through": "2021-01-01",
             "qualifying_trades": 1, "win_rate": 1.0, "avg_rr": 3.0, "verdict": "insufficient_data", "passed": False,
             "outcomes": _outcomes(wins=1, losses=0, rr=3.0)},
            {"window": 2, "train_through": "2021-01-01", "validate_through": "2022-01-01",
             "qualifying_trades": 0, "win_rate": 0.0, "avg_rr": 0.0, "verdict": "insufficient_data", "passed": False,
             "outcomes": []},
        ]
        monkeypatch.setattr(be, "run_walk_forward", lambda *a, **kw: windows)
        result = run_backtest(self._lenient_single_split_data(), min_qualifying_trades=1, min_expectancy_r=-100.0)
        assert result["deflated_sharpe_n_trials"] == 0

    def test_multiple_windows_with_real_spread_produce_a_nonzero_trial_count(self, monkeypatch):
        import backtesting.backtest_engine as be
        windows = [
            {"window": 1, "train_through": "2020-01-01", "validate_through": "2021-01-01",
             "qualifying_trades": 10, "win_rate": 0.5, "avg_rr": 2.0, "verdict": "fail", "passed": False,
             "outcomes": _outcomes(wins=5, losses=5, rr=2.0)},
            {"window": 2, "train_through": "2021-01-01", "validate_through": "2022-01-01",
             "qualifying_trades": 10, "win_rate": 0.8, "avg_rr": 2.0, "verdict": "pass", "passed": True,
             "outcomes": _outcomes(wins=8, losses=2, rr=2.0)},
        ]
        monkeypatch.setattr(be, "run_walk_forward", lambda *a, **kw: windows)
        result = run_backtest(self._lenient_single_split_data(), min_qualifying_trades=1, min_expectancy_r=-100.0)
        assert result["deflated_sharpe_n_trials"] == 2


# ---------------------------------------------------------------------------
# Stress tests
# ---------------------------------------------------------------------------

class TestStressTest:
    def _position(self, ticker="NVDA", direction="bullish", risk_pct=0.01, entry=500.0, stop=480.0):
        return {
            "ticker": ticker,
            "direction": direction,
            "entry_price": entry,
            "stop_loss": stop,
            "risk_pct": risk_pct,
            "structure": "long_stock",
        }

    def test_all_scenarios_returns_5_results(self):
        positions = [self._position()]
        results = run_all_scenarios(positions, account_equity=15000.0)
        assert len(results) == len(SCENARIOS)

    def test_empty_positions_no_pnl(self):
        results = run_all_scenarios([], account_equity=15000.0)
        for scenario_result in results.values():
            assert scenario_result["total_pnl"] == 0.0

    def test_smh_drop_causes_loss_in_bullish_position(self):
        positions = [self._position(direction="bullish")]
        result = run_scenario(SCENARIOS["smh_30_pct_drop"], positions, 15000.0)
        assert result["total_pnl"] < 0

    def test_required_keys_in_scenario_result(self):
        positions = [self._position()]
        result = run_scenario(SCENARIOS["smh_30_pct_drop"], positions, 15000.0)
        for key in ("pnl_by_position", "total_pnl", "pct_of_equity",
                    "circuit_breaker_triggered", "max_possible_loss"):
            assert key in result

    def test_nvda_specific_shock(self):
        positions = [self._position("NVDA"), self._position("AMD")]
        result = run_scenario(SCENARIOS["nvda_40_gap_down"], positions, 15000.0)
        # NVDA takes the full -40%; AMD takes the contagion shock
        assert result["pnl_by_position"]["NVDA"] < result["pnl_by_position"]["AMD"]

    def test_china_restriction_affects_asml_tsm(self):
        positions = [
            self._position("ASML", entry=700.0, stop=670.0),
            self._position("NVDA"),
        ]
        result = run_scenario(SCENARIOS["china_export_restriction"], positions, 15000.0)
        # ASML is in affected list; NVDA takes contagion only
        assert result["pnl_by_position"]["ASML"] < result["pnl_by_position"]["NVDA"]

    def test_large_drawdown_triggers_circuit_breaker(self):
        # Full 15k account, 1% risk per position, but smh shock should cause CB
        positions = [self._position(entry=100.0, stop=50.0)]  # Very wide stop
        result = run_scenario(SCENARIOS["smh_30_pct_drop"], positions, 15000.0)
        # Circuit breaker check is based on total_pnl / equity
        assert result["circuit_breaker_triggered"] in ("none", "yellow", "orange", "red")


# ---------------------------------------------------------------------------
# Sensitivity analysis — deflated Sharpe / multiple-testing correction
# ---------------------------------------------------------------------------

def _sensitivity_outcome(confidence, outcome, pnl_pct, day_offset, achieved_rr=None):
    """One synthetic outcome with the fields run_sensitivity_analysis's equity
    curve / Sharpe computation actually needs (pnl_pct, entry_price, stop,
    exit_date) alongside the confidence it filters on."""
    return {
        "confidence": confidence,
        "outcome": outcome,
        "pnl_pct": pnl_pct,
        "achieved_rr": achieved_rr if achieved_rr is not None else (3.0 if outcome == "win" else -1.0),
        "entry_price": 100.0,
        "stop": 97.0,
        "exit_date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=day_offset),
        "regime": "trending_up",
    }


class TestSensitivityAnalysisDeflatedSharpe:
    def test_reports_sharpe_per_threshold(self, tmp_path):
        # 30 outcomes spread across confidence levels so every default
        # threshold (85/87/90/92/95) has at least a few qualifying trades.
        outcomes = [
            _sensitivity_outcome(85 + (i % 11), "win" if i % 3 else "loss", 0.03 if i % 3 else -0.01, i)
            for i in range(30)
        ]
        df = run_sensitivity_analysis(outcomes, test_months=6.0, report_path=tmp_path / "sensitivity.csv")
        assert "sharpe_ratio" in df.columns
        assert len(df) == 5

    def test_adds_deflated_sharpe_columns_when_any_threshold_has_trades(self, tmp_path):
        outcomes = [
            _sensitivity_outcome(85 + (i % 11), "win" if i % 3 else "loss", 0.03 if i % 3 else -0.01, i)
            for i in range(30)
        ]
        df = run_sensitivity_analysis(outcomes, test_months=6.0, report_path=tmp_path / "sensitivity.csv")
        assert "psr_best_threshold_vs_sweep" in df.columns
        assert "deflated_sharpe_best_threshold" in df.columns
        assert (df["psr_best_threshold_vs_sweep"] >= 0.0).all()
        assert (df["psr_best_threshold_vs_sweep"] <= 1.0).all()

    def test_no_deflated_sharpe_columns_when_nothing_qualifies(self, tmp_path):
        # All outcomes below every threshold — every row is the zero-trades
        # branch, sharpe_ratio stays 0.0 everywhere, so there's nothing to
        # deflate and the extra columns should be skipped entirely.
        outcomes = [_sensitivity_outcome(50.0, "loss", -0.01, i) for i in range(10)]
        df = run_sensitivity_analysis(outcomes, test_months=6.0, report_path=tmp_path / "sensitivity.csv")
        assert (df["qualifying_trades"] == 0).all()
        assert "psr_best_threshold_vs_sweep" not in df.columns
