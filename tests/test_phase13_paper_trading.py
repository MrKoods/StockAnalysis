"""
Tests for Phase 13: paper trade metrics (go-live gate evaluation, forward EV
accuracy, signal accuracy). All tests avoid network calls and file I/O where
possible.

fill_tracker.py/paper_trade_engine.py (and their tests, formerly here) were
removed — orphaned modules never wired into the real pipeline
(paper_runner.py/paper_updater.py), so their slippage-tracking/recalibration
logic could never actually fire. evaluate_paper_trading_pass's own fill_log
parameter is unaffected: load_paper_trade_gate_inputs already always returns
an empty fill_log (see TestLoadPaperTradeGateInputs.test_fill_log_always_empty
below), so nothing here ever depended on fill_tracker's data in practice.
"""

import csv
import pytest

from paper_trading.paper_trade_metrics import (
    evaluate_paper_trading_pass,
    compute_forward_ev_accuracy,
    load_paper_trade_gate_inputs,
    compute_signal_accuracy,
)
from paper_trading.paper_updater import _CSV_COLUMNS


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
            {"signal_date": "2026-07-01", "ticker": "NVDA", "outcome": "win", "achieved_rr": "2.5", "position_size": "5"},
            {"signal_date": "2026-07-02", "ticker": "AMD", "outcome": ""},  # still open
        ]
        path = self._write_trades(tmp_path, rows)
        result = load_paper_trade_gate_inputs(path)
        assert len(result["trade_outcomes"]) == 1
        assert result["trade_outcomes"][0]["ticker"] == "NVDA"

    def test_fill_log_always_empty(self, tmp_path):
        rows = [{"signal_date": "2026-07-01", "ticker": "NVDA", "outcome": "win", "achieved_rr": "2.5", "position_size": "5"}]
        path = self._write_trades(tmp_path, rows)
        result = load_paper_trade_gate_inputs(path)
        assert result["fill_log"] == []

    def test_unfunded_closed_trade_excluded_from_outcomes(self, tmp_path):
        # A signal that qualified but sized to 0 (structure cost more than
        # the confidence tier's risk budget) shouldn't count toward the
        # go-live gate the same as a real, capital-deployed trade — see
        # compute_signal_accuracy for where this data belongs instead.
        rows = [
            {"signal_date": "2026-07-01", "ticker": "NVDA", "outcome": "win", "achieved_rr": "2.5", "position_size": "5"},
            {"signal_date": "2026-07-02", "ticker": "LLY", "outcome": "win", "achieved_rr": "2.5", "position_size": "0"},
        ]
        path = self._write_trades(tmp_path, rows)
        result = load_paper_trade_gate_inputs(path)
        assert len(result["trade_outcomes"]) == 1
        assert result["trade_outcomes"][0]["ticker"] == "NVDA"

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
            {"signal_date": "2026-01-01", "ticker": "NVDA", "outcome": "win", "achieved_rr": "2.5", "position_size": "5"},
            {"signal_date": "2026-01-02", "ticker": "AMD", "outcome": "loss", "achieved_rr": "-1.0", "position_size": "3"},
        ]
        path = self._write_trades(tmp_path, rows)
        inputs = load_paper_trade_gate_inputs(path)
        result = evaluate_paper_trading_pass(**inputs)
        assert result["data_status"] == "insufficient_trades"  # n=2, below the 15-trade floor


# ---------------------------------------------------------------------------
# compute_signal_accuracy
# ---------------------------------------------------------------------------

class TestComputeSignalAccuracy:
    def _write_trades(self, tmp_path, rows):
        path = tmp_path / "paper_trades.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        return path

    def test_missing_file_returns_zeros(self, tmp_path):
        result = compute_signal_accuracy(tmp_path / "does_not_exist.csv")
        assert result == {
            "total_closed": 0, "funded_count": 0, "unfunded_count": 0,
            "win_rate_all": 0.0, "win_rate_funded": 0.0, "win_rate_unfunded": 0.0,
        }

    def test_unfunded_wins_count_toward_accuracy_but_not_funded_rate(self, tmp_path):
        # JNJ-shaped case: qualified, correct direction (win), but sized to 0
        # (couldn't afford any structure at this account size). Should count
        # toward win_rate_all and win_rate_unfunded, not win_rate_funded.
        rows = [
            {"signal_date": "2026-08-11", "ticker": "JNJ", "outcome": "win", "position_size": "0"},
            {"signal_date": "2026-08-07", "ticker": "AMZN", "outcome": "loss", "position_size": "2"},
        ]
        path = self._write_trades(tmp_path, rows)
        result = compute_signal_accuracy(path)
        assert result["total_closed"] == 2
        assert result["funded_count"] == 1
        assert result["unfunded_count"] == 1
        assert result["win_rate_all"] == pytest.approx(0.5)
        assert result["win_rate_funded"] == pytest.approx(0.0)
        assert result["win_rate_unfunded"] == pytest.approx(1.0)

    def test_open_trades_excluded_from_all_counts(self, tmp_path):
        rows = [
            {"signal_date": "2026-08-11", "ticker": "MRK", "outcome": "", "position_size": "5"},
        ]
        path = self._write_trades(tmp_path, rows)
        result = compute_signal_accuracy(path)
        assert result["total_closed"] == 0

    def test_all_funded_leaves_unfunded_rate_at_zero(self, tmp_path):
        rows = [
            {"signal_date": "2026-08-07", "ticker": "AMZN", "outcome": "win", "position_size": "2"},
        ]
        path = self._write_trades(tmp_path, rows)
        result = compute_signal_accuracy(path)
        assert result["unfunded_count"] == 0
        assert result["win_rate_unfunded"] == 0.0
        assert result["win_rate_funded"] == pytest.approx(1.0)
