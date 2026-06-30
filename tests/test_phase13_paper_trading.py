"""
Tests for Phase 13: paper trade engine, fill tracker, paper trade metrics.
All tests avoid network calls and file I/O where possible.
"""

import csv
import json
import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone

from paper_trading.fill_tracker import log_fill, compute_avg_slippage, check_slippage_threshold
from paper_trading.paper_trade_engine import simulate_fill
from paper_trading.paper_trade_metrics import evaluate_paper_trading_pass, compute_forward_ev_accuracy


# ---------------------------------------------------------------------------
# simulate_fill
# ---------------------------------------------------------------------------

class TestSimulateFill:
    def test_no_slippage_when_prices_equal(self):
        result = simulate_fill("NVDA", "long_stock", 100.0, 100.0)
        assert result["slippage"] == pytest.approx(0.0)
        assert result["slippage_pct"] == pytest.approx(0.0)

    def test_positive_slippage_when_fill_higher(self):
        result = simulate_fill("NVDA", "long_stock", 100.0, 100.5)
        assert result["slippage"] == pytest.approx(0.5)
        assert result["slippage_pct"] == pytest.approx(0.005)

    def test_negative_slippage_when_fill_lower(self):
        result = simulate_fill("NVDA", "long_stock", 100.0, 99.5)
        assert result["slippage"] == pytest.approx(-0.5)

    def test_result_contains_required_keys(self):
        result = simulate_fill("NVDA", "long_stock", 100.0, 100.25)
        for key in ("ticker", "structure", "recommended_price", "actual_fill", "slippage", "slippage_pct"):
            assert key in result

    def test_recommended_price_preserved(self):
        result = simulate_fill("AMD", "long_call", 50.0, 50.3)
        assert result["recommended_price"] == pytest.approx(50.0)
        assert result["actual_fill"] == pytest.approx(50.3)


# ---------------------------------------------------------------------------
# fill_tracker.log_fill + compute_avg_slippage
# ---------------------------------------------------------------------------

class TestFillTracker:
    def test_log_fill_creates_file(self, tmp_path, monkeypatch):
        import paper_trading.fill_tracker as ft
        monkeypatch.setattr(ft, "_FILL_LOG_FILE", tmp_path / "fill_log.csv")
        log_fill("NVDA", "long_stock", 100.0, 100.5)
        assert (tmp_path / "fill_log.csv").exists()

    def test_log_fill_writes_correct_slippage(self, tmp_path, monkeypatch):
        import paper_trading.fill_tracker as ft
        log_path = tmp_path / "fill_log.csv"
        monkeypatch.setattr(ft, "_FILL_LOG_FILE", log_path)
        log_fill("NVDA", "long_stock", 100.0, 101.0)
        rows = list(csv.DictReader(log_path.open()))
        assert len(rows) == 1
        assert float(rows[0]["slippage_dollar"]) == pytest.approx(1.0)
        assert float(rows[0]["slippage_pct"]) == pytest.approx(0.01)

    def test_log_fill_appends_multiple_rows(self, tmp_path, monkeypatch):
        import paper_trading.fill_tracker as ft
        log_path = tmp_path / "fill_log.csv"
        monkeypatch.setattr(ft, "_FILL_LOG_FILE", log_path)
        log_fill("NVDA", "long_stock", 100.0, 100.5)
        log_fill("AMD", "long_stock", 50.0, 50.2)
        rows = list(csv.DictReader(log_path.open()))
        assert len(rows) == 2

    def test_compute_avg_slippage_no_file(self, tmp_path, monkeypatch):
        import paper_trading.fill_tracker as ft
        monkeypatch.setattr(ft, "_FILL_LOG_FILE", tmp_path / "nonexistent.csv")
        result = compute_avg_slippage()
        assert result["total_fills"] == 0
        assert result["avg_slippage_pct"] == 0.0

    def test_compute_avg_slippage_with_data(self, tmp_path, monkeypatch):
        import paper_trading.fill_tracker as ft
        log_path = tmp_path / "fill_log.csv"
        monkeypatch.setattr(ft, "_FILL_LOG_FILE", log_path)
        log_fill("NVDA", "long_stock", 100.0, 101.0)   # 1.0%
        log_fill("AMD", "long_stock", 50.0, 50.5)       # 1.0%
        result = compute_avg_slippage()
        assert result["total_fills"] == 2
        assert result["avg_slippage_pct"] == pytest.approx(0.01)

    def test_check_slippage_threshold_not_exceeded(self):
        assert check_slippage_threshold(0.005, 0.005) is False

    def test_check_slippage_threshold_exceeded(self):
        assert check_slippage_threshold(0.012, 0.005, threshold=0.15) is True

    def test_check_slippage_threshold_zero_modeled(self):
        assert check_slippage_threshold(0.01, 0.0) is False


# ---------------------------------------------------------------------------
# evaluate_paper_trading_pass
# ---------------------------------------------------------------------------

class TestEvaluatePaperTradingPass:
    def _win_outcomes(self, n_wins, n_losses, rr=3.0):
        outcomes = []
        for _ in range(n_wins):
            outcomes.append({"outcome": "win", "achieved_rr": rr, "pnl_pct": 0.03})
        for _ in range(n_losses):
            outcomes.append({"outcome": "loss", "achieved_rr": -1.0, "pnl_pct": -0.01})
        return outcomes

    def _fill_log(self, n, actual_slip=0.005, modeled_slip=0.005):
        return [{"slippage_pct": actual_slip, "modeled_slippage_pct": modeled_slip}] * n

    def test_overall_pass_when_all_criteria_met(self):
        outcomes = self._win_outcomes(90, 10, rr=3.0)  # 90% win rate, 3.0 avg rr
        fills = self._fill_log(10)
        result = evaluate_paper_trading_pass(outcomes, fills, trading_days_elapsed=60)
        assert result["win_rate_pass"] is True
        assert result["rr_pass"] is True
        assert result["slippage_pass"] is True
        assert result["duration_pass"] is True
        assert result["overall_pass"] is True

    def test_fails_when_win_rate_too_low(self):
        outcomes = self._win_outcomes(70, 30, rr=3.5)  # 70% win rate < 80%
        fills = self._fill_log(10)
        result = evaluate_paper_trading_pass(outcomes, fills, trading_days_elapsed=60)
        assert result["win_rate_pass"] is False
        assert result["overall_pass"] is False

    def test_fails_when_duration_insufficient(self):
        outcomes = self._win_outcomes(90, 10)
        fills = self._fill_log(10)
        result = evaluate_paper_trading_pass(outcomes, fills, trading_days_elapsed=30)  # < 60
        assert result["duration_pass"] is False
        assert result["overall_pass"] is False

    def test_fails_when_rr_too_low(self):
        outcomes = self._win_outcomes(90, 10, rr=2.0)  # avg_rr < 3.0
        fills = self._fill_log(10)
        result = evaluate_paper_trading_pass(outcomes, fills, trading_days_elapsed=60)
        assert result["rr_pass"] is False
        assert result["overall_pass"] is False

    def test_failures_list_populated_on_miss(self):
        outcomes = self._win_outcomes(70, 30)  # win rate miss
        result = evaluate_paper_trading_pass(outcomes, [], trading_days_elapsed=30)
        assert len(result["failures"]) >= 2  # win_rate + duration at minimum

    def test_empty_outcomes_all_fail(self):
        result = evaluate_paper_trading_pass([], [], trading_days_elapsed=0)
        assert result["overall_pass"] is False
        assert result["win_rate"] == 0.0

    def test_result_contains_required_keys(self):
        result = evaluate_paper_trading_pass([], [], 0)
        for key in ("overall_pass", "win_rate", "win_rate_pass", "avg_rr", "rr_pass",
                    "avg_slippage_excess", "slippage_pass", "duration_pass", "failures"):
            assert key in result


# ---------------------------------------------------------------------------
# compute_forward_ev_accuracy
# ---------------------------------------------------------------------------

class TestForwardEVAccuracy:
    def test_perfect_calibration_returns_one(self):
        outcomes = [
            {"pnl_pct": 5.0, "theoretical_ev": 5.0},
            {"pnl_pct": 5.0, "theoretical_ev": 5.0},
        ]
        assert compute_forward_ev_accuracy(outcomes) == pytest.approx(1.0)

    def test_empty_returns_zero(self):
        assert compute_forward_ev_accuracy([]) == 0.0

    def test_zero_theoretical_ev_returns_zero(self):
        outcomes = [{"pnl_pct": 3.0, "theoretical_ev": 0.0}]
        assert compute_forward_ev_accuracy(outcomes) == 0.0

    def test_overperformance_ratio_greater_than_one(self):
        outcomes = [{"pnl_pct": 6.0, "theoretical_ev": 4.0}]
        ratio = compute_forward_ev_accuracy(outcomes)
        assert ratio > 1.0

    def test_underperformance_ratio_less_than_one(self):
        outcomes = [{"pnl_pct": 2.0, "theoretical_ev": 4.0}]
        ratio = compute_forward_ev_accuracy(outcomes)
        assert ratio < 1.0
