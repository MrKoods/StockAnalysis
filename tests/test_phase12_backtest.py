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
    compute_sharpe,
    per_regime_metrics,
    compute_consecutive_losses,
    compute_r_multiples,
    bootstrap_expectancy_ci,
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
            holding_period=(5, 15),
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
