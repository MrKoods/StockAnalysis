"""
Tests for Phase 13: paper trade engine, fill tracker, paper trade metrics.
All tests avoid network calls and file I/O where possible.
"""

import csv
import pytest

from paper_trading.fill_tracker import log_fill, compute_avg_slippage, check_slippage_threshold
from paper_trading.paper_trade_engine import simulate_fill
from paper_trading.paper_trade_metrics import (
    evaluate_paper_trading_pass,
    compute_forward_ev_accuracy,
    load_paper_trade_gate_inputs,
)
from paper_trading.paper_updater import _CSV_COLUMNS


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
        # Strong, consistent edge over a reasonably large sample — CI lower
        # bound should clear 0.3R comfortably.
        outcomes = self._win_outcomes(90, 10, rr=3.0)  # mean_r = 2.6
        fills = self._fill_log(10)
        result = evaluate_paper_trading_pass(outcomes, fills, trading_days_elapsed=60)
        assert result["expectancy_pass"] is True
        assert result["slippage_pass"] is True
        assert result["duration_pass"] is True
        assert result["overall_pass"] is True

    def test_fails_when_expectancy_ci_too_low(self):
        """
        v2.2.19 (mirrors the backtest gate's v2.2.17 change): "passed" no longer
        gates on a flat win_rate/avg_rr pair — it gates on the bootstrapped 95%
        CI lower bound of per-trade R-expectancy clearing min_expectancy_r. A
        small, noisy sample with a weak/negative mean edge should not pass even
        though win_rate alone might look plausible.
        """
        outcomes = self._win_outcomes(3, 2, rr=0.5)  # mean_r = -0.1, n=5
        fills = self._fill_log(10)
        result = evaluate_paper_trading_pass(outcomes, fills, trading_days_elapsed=60)
        assert result["expectancy_pass"] is False
        assert result["overall_pass"] is False

    def test_passes_once_min_expectancy_r_lowered_for_same_data(self):
        outcomes = self._win_outcomes(3, 2, rr=0.5)
        fills = self._fill_log(10)
        strict = evaluate_paper_trading_pass(outcomes, fills, trading_days_elapsed=60, min_expectancy_r=100.0)
        assert strict["overall_pass"] is False  # no real edge clears a 100R bar
        lenient = evaluate_paper_trading_pass(outcomes, fills, trading_days_elapsed=60, min_expectancy_r=-100.0)
        assert lenient["expectancy_r_ci_lower"] <= lenient["expectancy_r_mean"] <= lenient["expectancy_r_ci_upper"]

    def test_fails_when_duration_insufficient(self):
        outcomes = self._win_outcomes(90, 10, rr=3.0)
        fills = self._fill_log(10)
        result = evaluate_paper_trading_pass(outcomes, fills, trading_days_elapsed=30)  # < 60
        assert result["duration_pass"] is False
        assert result["overall_pass"] is False

    def test_failures_list_populated_on_miss(self):
        outcomes = self._win_outcomes(3, 2, rr=0.5)  # weak edge, small sample
        result = evaluate_paper_trading_pass(outcomes, [], trading_days_elapsed=30)
        assert len(result["failures"]) >= 2  # expectancy + duration at minimum

    def test_empty_outcomes_all_fail(self):
        result = evaluate_paper_trading_pass([], [], trading_days_elapsed=0)
        assert result["overall_pass"] is False
        assert result["win_rate"] == 0.0
        assert result["expectancy_r_ci_lower"] == 0.0

    def test_result_contains_required_keys(self):
        result = evaluate_paper_trading_pass([], [], 0)
        for key in ("overall_pass", "data_status", "win_rate", "avg_rr", "expectancy_r_mean",
                    "expectancy_r_ci_lower", "expectancy_r_ci_upper", "expectancy_pass",
                    "avg_slippage_excess", "slippage_pass", "duration_pass", "failures"):
            assert key in result

    def test_zero_trades_reports_insufficient_data_not_expectancy_failure(self):
        """
        v2.2.20: at n=0 (paper trading's actual current state — see
        score_distribution_diagnostic.py), the CI lower bound is trivially 0.0,
        which reads identically to "the edge genuinely failed" without this
        distinction. overall_pass must still stay False (safe default), but the
        failure reason should say so, not imply a real expectancy miss.
        """
        result = evaluate_paper_trading_pass([], [], trading_days_elapsed=60)
        assert result["overall_pass"] is False
        assert result["data_status"] == "insufficient_trades"
        assert any(f.startswith("insufficient_trade_data_") for f in result["failures"])
        assert not any(f.startswith("expectancy_ci_lower_") for f in result["failures"])

    def test_few_trades_still_reports_insufficient_data(self):
        outcomes = self._win_outcomes(3, 2, rr=0.5)  # n=5, below the 15-trade floor
        fills = self._fill_log(10)
        result = evaluate_paper_trading_pass(outcomes, fills, trading_days_elapsed=60)
        assert result["data_status"] == "insufficient_trades"

    def test_enough_trades_reports_evaluated(self):
        outcomes = self._win_outcomes(90, 10, rr=3.0)  # n=100, well above the floor
        fills = self._fill_log(10)
        result = evaluate_paper_trading_pass(outcomes, fills, trading_days_elapsed=60)
        assert result["data_status"] == "evaluated"


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


# ---------------------------------------------------------------------------
# load_paper_trade_gate_inputs
# ---------------------------------------------------------------------------

class TestLoadPaperTradeGateInputs:
    def _write_trades(self, tmp_path, rows):
        path = tmp_path / "paper_trades.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_missing_file_returns_empty_defaults(self, tmp_path):
        result = load_paper_trade_gate_inputs(tmp_path / "does_not_exist.csv")
        assert result == {"trade_outcomes": [], "fill_log": [], "trading_days_elapsed": 0}

    def test_only_closed_trades_included_in_outcomes(self, tmp_path):
        rows = [
            {"signal_date": "2026-07-01", "ticker": "NVDA", "outcome": "win", "achieved_rr": "2.5"},
            {"signal_date": "2026-07-02", "ticker": "AMD", "outcome": ""},  # still open
        ]
        path = self._write_trades(tmp_path, rows)
        result = load_paper_trade_gate_inputs(path)
        assert len(result["trade_outcomes"]) == 1
        assert result["trade_outcomes"][0]["ticker"] == "NVDA"

    def test_fill_log_always_empty(self, tmp_path):
        rows = [{"signal_date": "2026-07-01", "ticker": "NVDA", "outcome": "win", "achieved_rr": "2.5"}]
        path = self._write_trades(tmp_path, rows)
        result = load_paper_trade_gate_inputs(path)
        assert result["fill_log"] == []

    def test_trading_days_elapsed_counts_from_earliest_signal_date(self, tmp_path):
        # Includes an open trade's signal_date too — duration is about how long
        # the system has run, not how many trades closed.
        rows = [
            {"signal_date": "2026-07-01", "ticker": "NVDA", "outcome": "win", "achieved_rr": "2.5"},
            {"signal_date": "2026-06-20", "ticker": "AMD", "outcome": ""},
        ]
        path = self._write_trades(tmp_path, rows)
        result = load_paper_trade_gate_inputs(path)
        assert result["trading_days_elapsed"] > 0

    def test_result_feeds_directly_into_evaluate_paper_trading_pass(self, tmp_path):
        rows = [
            {"signal_date": "2026-01-01", "ticker": "NVDA", "outcome": "win", "achieved_rr": "2.5"},
            {"signal_date": "2026-01-02", "ticker": "AMD", "outcome": "loss", "achieved_rr": "-1.0"},
        ]
        path = self._write_trades(tmp_path, rows)
        inputs = load_paper_trade_gate_inputs(path)
        result = evaluate_paper_trading_pass(**inputs)
        assert result["data_status"] == "insufficient_trades"  # n=2, below the 15-trade floor
