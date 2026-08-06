"""
Tests for backtesting/threshold_optimization_analysis.py — reports what
real backtest data suggests about the go-live threshold without changing
CONFIDENCE_THRESHOLD itself.
"""

import pytest

from backtesting.threshold_optimization_analysis import evaluate_thresholds


def _outcome(confidence, outcome, pnl_pct, achieved_rr, day):
    import pandas as pd
    return {
        "confidence": confidence, "outcome": outcome, "pnl_pct": pnl_pct,
        "achieved_rr": achieved_rr, "entry_price": 100.0, "stop": 97.0,
        "exit_date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=day),
        "signal_date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=day - 5),
        "regime": "trending_up",
    }


class TestEvaluateThresholds:
    def test_empty_outcomes_reports_zero_for_every_threshold(self):
        rows = evaluate_thresholds([], [85, 90])
        assert all(r["qualifying_trades"] == 0 for r in rows)
        assert all(r["clears_go_live_gate"] is False for r in rows)

    def test_higher_threshold_has_fewer_or_equal_qualifying_trades(self):
        outcomes = [
            _outcome(85 + (i % 11), "win" if i % 3 else "loss", 0.03 if i % 3 else -0.01, 3.0 if i % 3 else -1.0, i)
            for i in range(60)
        ]
        rows = evaluate_thresholds(outcomes, [85, 90, 95])
        counts = [r["qualifying_trades"] for r in rows]
        assert counts[0] >= counts[1] >= counts[2]

    def test_ev_per_trade_r_formula(self):
        # All wins at achieved_rr=3.0 -> win_rate=1.0, avg_rr=3.0 ->
        # ev_per_trade_r = 1.0*3.0 - 0 = 3.0
        outcomes = [_outcome(90, "win", 0.03, 3.0, i) for i in range(10)]
        rows = evaluate_thresholds(outcomes, [90])
        assert rows[0]["ev_per_trade_r"] == pytest.approx(3.0)

    def test_all_losses_gives_negative_ev(self):
        outcomes = [_outcome(90, "loss", -0.01, -1.0, i) for i in range(10)]
        rows = evaluate_thresholds(outcomes, [90])
        assert rows[0]["ev_per_trade_r"] == pytest.approx(-1.0)

    def test_clears_gate_requires_minimum_trade_count(self):
        # Great win rate but far too few trades to clear _MIN_QUALIFYING_TRADES.
        outcomes = [_outcome(90, "win", 0.03, 3.0, i) for i in range(10)]
        rows = evaluate_thresholds(outcomes, [90])
        assert rows[0]["clears_go_live_gate"] is False

    def test_result_rows_have_expected_keys(self):
        outcomes = [_outcome(90, "win", 0.03, 3.0, i) for i in range(5)]
        rows = evaluate_thresholds(outcomes, [90])
        for key in ("threshold", "qualifying_trades", "win_rate", "avg_rr",
                    "ev_per_trade_r", "expectancy_r_ci_lower", "sharpe_ratio",
                    "max_drawdown_pct", "clears_go_live_gate"):
            assert key in rows[0]
