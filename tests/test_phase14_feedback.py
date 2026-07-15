"""
Tests for Phase 14: feedback_loop.py and performance_dashboard.py.
All file I/O is redirected to tmp_path via monkeypatch.
"""

import csv
import json
import pytest

from swing_model.feedback_loop import (
    log_trade_outcome,
    update_signal_win_rates,
    run_calibration,
    build_signal_key,
)
from monitoring.performance_dashboard import (
    generate_weekly_summary,
    check_review_trigger,
    log_performance_entry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _outcome(ticker="NVDA", result="win", tech=45.0, sent=20.0, news=10.0, conf=92.0, rr=3.0):
    return {
        "ticker": ticker,
        "entry_date": "2026-06-01",
        "exit_date": "2026-06-08",
        "entry_price": 500.0,
        "exit_price": 530.0 if result == "win" else 490.0,
        "direction": "bullish",
        "structure": "long_stock",
        "confidence_score": conf,
        "technical_total": tech,
        "sentiment_total": sent,
        "news_total": news,
        "holding_days": 5,
        "pnl_dollars": 150.0 if result == "win" else -150.0,
        "pnl_pct": 3.0 if result == "win" else -1.0,
        "outcome": result,
        "achieved_rr": rr if result == "win" else -1.0,
        "signal_key": "B1_T1_BUL_RSI_MID_BUL",
    }


def _write_outcomes(path, outcomes):
    from swing_model.feedback_loop import _OUTCOMES_COLUMNS
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_OUTCOMES_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for o in outcomes:
            writer.writerow({col: o.get(col, "") for col in _OUTCOMES_COLUMNS})


# ---------------------------------------------------------------------------
# log_trade_outcome
# ---------------------------------------------------------------------------

class TestLogTradeOutcome:
    def test_creates_csv_on_first_write(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        monkeypatch.setattr(fl, "_TRADE_OUTCOMES_FILE", tmp_path / "outcomes.csv")
        monkeypatch.setattr(fl, "_SIGNAL_WIN_RATES_FILE", tmp_path / "rates.json")
        log_trade_outcome(_outcome())
        assert (tmp_path / "outcomes.csv").exists()

    def test_appends_multiple_outcomes(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        p = tmp_path / "outcomes.csv"
        monkeypatch.setattr(fl, "_TRADE_OUTCOMES_FILE", p)
        monkeypatch.setattr(fl, "_SIGNAL_WIN_RATES_FILE", tmp_path / "rates.json")
        log_trade_outcome(_outcome("NVDA", "win"))
        log_trade_outcome(_outcome("AMD", "loss"))
        rows = list(csv.DictReader(p.open()))
        assert len(rows) == 2

    def test_writes_correct_outcome_field(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        p = tmp_path / "outcomes.csv"
        monkeypatch.setattr(fl, "_TRADE_OUTCOMES_FILE", p)
        monkeypatch.setattr(fl, "_SIGNAL_WIN_RATES_FILE", tmp_path / "rates.json")
        log_trade_outcome(_outcome("NVDA", "loss"))
        rows = list(csv.DictReader(p.open()))
        assert rows[0]["outcome"] == "loss"

    def test_also_updates_signal_win_rates(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        monkeypatch.setattr(fl, "_TRADE_OUTCOMES_FILE", tmp_path / "outcomes.csv")
        rates_path = tmp_path / "rates.json"
        monkeypatch.setattr(fl, "_SIGNAL_WIN_RATES_FILE", rates_path)
        log_trade_outcome(_outcome("NVDA", "win"))
        assert rates_path.exists()


# ---------------------------------------------------------------------------
# update_signal_win_rates
# ---------------------------------------------------------------------------

class TestUpdateSignalWinRates:
    def test_creates_rates_file(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        rates_path = tmp_path / "rates.json"
        monkeypatch.setattr(fl, "_SIGNAL_WIN_RATES_FILE", rates_path)
        update_signal_win_rates(_outcome("NVDA", "win"))
        assert rates_path.exists()

    def test_increments_win_count(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        rates_path = tmp_path / "rates.json"
        monkeypatch.setattr(fl, "_SIGNAL_WIN_RATES_FILE", rates_path)
        update_signal_win_rates(_outcome("NVDA", "win"))
        update_signal_win_rates(_outcome("NVDA", "win"))
        data = json.loads(rates_path.read_text())
        assert data["B1_T1_BUL_RSI_MID_BUL"]["wins"] == 2

    def test_win_rate_computed_after_10_samples(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        rates_path = tmp_path / "rates.json"
        monkeypatch.setattr(fl, "_SIGNAL_WIN_RATES_FILE", rates_path)
        for _ in range(8):
            update_signal_win_rates(_outcome(result="win"))
        for _ in range(2):
            update_signal_win_rates(_outcome(result="loss"))
        data = json.loads(rates_path.read_text())
        key = "B1_T1_BUL_RSI_MID_BUL"
        assert "win_rate" in data[key]
        assert data[key]["win_rate"] == pytest.approx(0.8)

    def test_no_win_rate_before_10_samples(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        rates_path = tmp_path / "rates.json"
        monkeypatch.setattr(fl, "_SIGNAL_WIN_RATES_FILE", rates_path)
        for _ in range(5):
            update_signal_win_rates(_outcome(result="win"))
        data = json.loads(rates_path.read_text())
        assert "win_rate" not in data.get("B1_T1_BUL_RSI_MID_BUL", {})


# ---------------------------------------------------------------------------
# run_calibration
# ---------------------------------------------------------------------------

class TestRunCalibration:
    def test_returns_no_data_when_no_file(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        monkeypatch.setattr(fl, "_TRADE_OUTCOMES_FILE", tmp_path / "nonexistent.csv")
        result = run_calibration()
        assert result["status"] == "no_data"
        assert result["weights_updated"] is False

    def test_insufficient_data_returns_early(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        p = tmp_path / "outcomes.csv"
        _write_outcomes(p, [_outcome() for _ in range(5)])
        monkeypatch.setattr(fl, "_TRADE_OUTCOMES_FILE", p)
        monkeypatch.setattr(fl, "_LIVE_WEIGHTS_FILE", tmp_path / "weights.json")
        monkeypatch.setattr(fl, "_SIGNAL_WIN_RATES_FILE", tmp_path / "rates.json")
        result = run_calibration()
        assert result["status"] == "insufficient_data"

    def test_calibration_with_enough_data(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        p = tmp_path / "outcomes.csv"
        outcomes = [_outcome(result="win")] * 16 + [_outcome(result="loss")] * 4
        _write_outcomes(p, outcomes)
        monkeypatch.setattr(fl, "_TRADE_OUTCOMES_FILE", p)
        monkeypatch.setattr(fl, "_LIVE_WEIGHTS_FILE", tmp_path / "weights.json")
        monkeypatch.setattr(fl, "_SIGNAL_WIN_RATES_FILE", tmp_path / "rates.json")
        result = run_calibration()
        assert "status" in result
        assert "weights_updated" in result
        assert "holdout_win_rate_old" in result

    def test_result_contains_required_keys(self, tmp_path, monkeypatch):
        result = run_calibration()
        for key in ("status", "weights_updated"):
            assert key in result


# ---------------------------------------------------------------------------
# build_signal_key
# ---------------------------------------------------------------------------

class TestBuildSignalKey:
    def test_format_contains_breakout_and_trend(self):
        state = {
            "breakout_confirmed": True,
            "trend_aligned": True,
            "relative_strength_direction": "bullish",
            "rsi": 55,
            "sentiment_direction": "bullish",
        }
        key = build_signal_key(state)
        assert key.startswith("B1_T1_")

    def test_no_breakout_encoded(self):
        state = {
            "breakout_confirmed": False,
            "trend_aligned": False,
            "relative_strength_direction": "bearish",
            "rsi": 30,
            "sentiment_direction": "bearish",
        }
        key = build_signal_key(state)
        assert key.startswith("B0_T0_")

    def test_rsi_buckets_correct(self):
        base = {"breakout_confirmed": True, "trend_aligned": True,
                "relative_strength_direction": "neutral", "sentiment_direction": "neutral"}
        assert "RSI_LOW" in build_signal_key({**base, "rsi": 35})
        assert "RSI_MID" in build_signal_key({**base, "rsi": 50})
        assert "RSI_HIGH" in build_signal_key({**base, "rsi": 70})

    def test_same_state_same_key(self):
        state = {
            "breakout_confirmed": True, "trend_aligned": True,
            "relative_strength_direction": "bullish", "rsi": 55, "sentiment_direction": "bullish"
        }
        assert build_signal_key(state) == build_signal_key(state)


# ---------------------------------------------------------------------------
# performance_dashboard
# ---------------------------------------------------------------------------

class TestCheckReviewTrigger:
    def test_triggers_below_70pct(self):
        assert check_review_trigger(0.65) is True

    def test_does_not_trigger_above_70pct(self):
        assert check_review_trigger(0.75) is False

    def test_exactly_70pct_does_not_trigger(self):
        assert check_review_trigger(0.70) is False


class TestGenerateWeeklySummary:
    def _write_trade_csv(self, path, n_wins, n_losses):
        outcomes = []
        for _ in range(n_wins):
            outcomes.append({
                "outcome": "win", "pnl_dollars": 150, "pnl_pct": 3.0,
                "achieved_rr": 3.0, "confidence_score": 92.0,
                "structure": "long_stock", "theoretical_ev": 3.0,
            })
        for _ in range(n_losses):
            outcomes.append({
                "outcome": "loss", "pnl_dollars": -150, "pnl_pct": -1.0,
                "achieved_rr": -1.0, "confidence_score": 90.0,
                "structure": "long_stock", "theoretical_ev": 3.0,
            })
        cols = list(outcomes[0].keys())
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            writer.writeheader()
            for o in outcomes:
                writer.writerow(o)

    def test_returns_no_data_when_missing(self, tmp_path):
        result = generate_weekly_summary(str(tmp_path / "nonexistent.csv"))
        assert result["status"] == "no_data"
        assert result["total_trades"] == 0

    def test_win_rates_computed_correctly(self, tmp_path, monkeypatch):
        import monitoring.performance_dashboard as pd_mod
        monkeypatch.setattr(pd_mod, "_PERFORMANCE_LOG", tmp_path / "perf_log.csv")
        path = tmp_path / "outcomes.csv"
        self._write_trade_csv(path, 8, 2)
        result = generate_weekly_summary(str(path))
        assert result["win_rate_10"] == pytest.approx(0.8)
        assert result["total_trades"] == 10

    def test_review_triggered_on_low_win_rate(self, tmp_path, monkeypatch):
        import monitoring.performance_dashboard as pd_mod
        monkeypatch.setattr(pd_mod, "_PERFORMANCE_LOG", tmp_path / "perf_log.csv")
        path = tmp_path / "outcomes.csv"
        self._write_trade_csv(path, 12, 8)  # 60% — below 70%
        result = generate_weekly_summary(str(path))
        assert result["review_triggered"] is True

    def test_no_review_trigger_on_good_win_rate(self, tmp_path, monkeypatch):
        import monitoring.performance_dashboard as pd_mod
        monkeypatch.setattr(pd_mod, "_PERFORMANCE_LOG", tmp_path / "perf_log.csv")
        path = tmp_path / "outcomes.csv"
        self._write_trade_csv(path, 17, 3)  # 85%
        result = generate_weekly_summary(str(path))
        assert result["review_triggered"] is False

    def test_required_keys_present(self, tmp_path, monkeypatch):
        import monitoring.performance_dashboard as pd_mod
        monkeypatch.setattr(pd_mod, "_PERFORMANCE_LOG", tmp_path / "perf_log.csv")
        path = tmp_path / "outcomes.csv"
        self._write_trade_csv(path, 8, 2)
        result = generate_weekly_summary(str(path))
        for key in ("win_rate_10", "win_rate_20", "win_rate_50", "avg_rr_20",
                    "peak_to_trough_pct", "total_trades", "review_triggered"):
            assert key in result


class TestLogPerformanceEntry:
    def test_creates_log_file(self, tmp_path, monkeypatch):
        import monitoring.performance_dashboard as pd_mod
        log_path = tmp_path / "perf_log.csv"
        monkeypatch.setattr(pd_mod, "_PERFORMANCE_LOG", log_path)
        log_performance_entry({
            "generated_at": "2026-06-29T18:00:00+00:00",
            "win_rate_10": 0.8, "win_rate_20": 0.75, "win_rate_50": 0.7,
            "avg_rr_20": 2.8, "peak_to_trough_pct": 3.0,
            "total_trades": 50, "review_triggered": False,
        })
        assert log_path.exists()

    def test_appends_rows(self, tmp_path, monkeypatch):
        import monitoring.performance_dashboard as pd_mod
        log_path = tmp_path / "perf_log.csv"
        monkeypatch.setattr(pd_mod, "_PERFORMANCE_LOG", log_path)
        entry = {"generated_at": "2026-06-01T18:00:00+00:00", "win_rate_10": 0.8,
                 "win_rate_20": 0.75, "win_rate_50": 0.7, "avg_rr_20": 2.8,
                 "peak_to_trough_pct": 1.5, "total_trades": 20, "review_triggered": False}
        log_performance_entry(entry)
        log_performance_entry(entry)
        rows = list(csv.DictReader(log_path.open()))
        assert len(rows) == 2
