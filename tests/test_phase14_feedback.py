"""
Tests for Phase 14: feedback_loop.py and performance_dashboard.py.
All file I/O is redirected to tmp_path via monkeypatch.
"""

import csv
import json
from datetime import datetime, timedelta, timezone

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
# _fit_logistic_weights — regularized regression replacing the sign-only
# ±2pp heuristic for technical/sentiment/news weight calibration
# ---------------------------------------------------------------------------

def _synthetic_outcomes_technical_separates(n=60, seed=7):
    """
    technical_total clearly separates win/loss (wins centered higher, with
    noise); sentiment_total/news_total are pure noise unrelated to outcome.
    A correctly-working fit should identify technical as the dominant
    sub-signal.
    """
    import random
    rng = random.Random(seed)
    outcomes = []
    for i in range(n):
        is_win = i % 2 == 0
        tech = rng.gauss(32.0, 3.0) if is_win else rng.gauss(15.0, 3.0)
        sent = rng.gauss(7.5, 3.0)  # noise, same distribution regardless of outcome
        news = rng.gauss(7.5, 3.0)  # noise, same distribution regardless of outcome
        outcomes.append({
            "outcome": "win" if is_win else "loss",
            "technical_total": max(0.0, min(40.0, tech)),
            "sentiment_total": max(0.0, min(15.0, sent)),
            "news_total": max(0.0, min(15.0, news)),
        })
    return outcomes


class TestFitLogisticWeights:
    def test_none_with_too_few_samples(self):
        from swing_model.feedback_loop import _fit_logistic_weights, _MIN_SAMPLES_FOR_REGRESSION
        outcomes = _synthetic_outcomes_technical_separates(n=_MIN_SAMPLES_FOR_REGRESSION - 1)
        assert _fit_logistic_weights(outcomes) is None

    def test_none_when_all_same_outcome(self):
        from swing_model.feedback_loop import _fit_logistic_weights
        outcomes = [
            {"outcome": "win", "technical_total": 30.0, "sentiment_total": 8.0, "news_total": 6.0}
            for _ in range(30)
        ]
        assert _fit_logistic_weights(outcomes) is None

    def test_drops_a_zero_variance_feature_instead_of_aborting(self):
        # Changed 2026-08-15 (see CHANGELOG v2.2.57): a zero-variance feature
        # used to make the whole fit return None. Found via
        # backtesting/sector_weight_calibration.py — historical backtest
        # replay predates Alpha Vantage's article cache for nearly its whole
        # 13.5-year range, so news_total is constant across almost every
        # historical row, which made every per-sector calibration attempt
        # degenerate under the old all-or-nothing behavior. Now the
        # zero-variance feature is just dropped from the fit; the informative
        # ones still get fit normally.
        from swing_model.feedback_loop import _fit_logistic_weights
        import random
        rng = random.Random(1)
        outcomes = []
        for i in range(30):
            is_win = i % 2 == 0
            outcomes.append({
                "outcome": "win" if is_win else "loss",
                "technical_total": rng.gauss(30.0, 3.0) if is_win else rng.gauss(15.0, 3.0),
                "sentiment_total": 8.0,  # identical every row -> zero variance
                "news_total": rng.gauss(7.0, 2.0),
            })
        result = _fit_logistic_weights(outcomes)
        assert result is not None
        assert "sentiment" not in result
        assert set(result.keys()) == {"technical", "news"}
        assert abs(sum(result.values()) - 1.0) < 1e-9

    def test_none_when_every_feature_has_zero_variance(self):
        from swing_model.feedback_loop import _fit_logistic_weights
        outcomes = [
            {"outcome": "win" if i % 2 == 0 else "loss",
             "technical_total": 30.0, "sentiment_total": 8.0, "news_total": 7.0}
            for i in range(30)
        ]
        assert _fit_logistic_weights(outcomes) is None

    def test_identifies_the_actually_separating_sub_signal(self):
        from swing_model.feedback_loop import _fit_logistic_weights
        outcomes = _synthetic_outcomes_technical_separates()
        result = _fit_logistic_weights(outcomes)
        assert result is not None
        # technical clearly separates wins/losses; sentiment/news are pure
        # noise -> technical should end up with by far the largest fraction.
        assert result["technical"] > result["sentiment"]
        assert result["technical"] > result["news"]

    def test_weights_sum_to_one(self):
        from swing_model.feedback_loop import _fit_logistic_weights
        outcomes = _synthetic_outcomes_technical_separates()
        result = _fit_logistic_weights(outcomes)
        assert sum(result.values()) == pytest.approx(1.0, abs=1e-6)

    def test_non_numeric_fields_are_skipped_not_crashed(self):
        from swing_model.feedback_loop import _fit_logistic_weights
        outcomes = _synthetic_outcomes_technical_separates()
        outcomes.append({"outcome": "win", "technical_total": "bad", "sentiment_total": 5.0, "news_total": 5.0})
        result = _fit_logistic_weights(outcomes)
        assert result is not None  # the one bad row is skipped, rest still fit


class TestRecomputeWeightsUsesRegressionWhenPossible:
    def test_falls_back_to_heuristic_below_regression_threshold(self):
        from swing_model.feedback_loop import _recompute_weights
        outcomes = [_outcome(result="win")] * 4 + [_outcome(result="loss", tech=10.0)] * 4
        current = {"technical": 0.60, "sentiment": 0.25, "news": 0.15}
        # Should not raise, should still produce a valid normalized weight dict
        # via the old heuristic path (too few samples for regression).
        result = _recompute_weights(outcomes, current)
        assert sum(result.values()) == pytest.approx(1.0, abs=1e-3)

    def test_uses_regression_result_when_enough_varied_data(self):
        from swing_model.feedback_loop import _recompute_weights
        outcomes = _synthetic_outcomes_technical_separates()
        current = {"technical": 0.60, "sentiment": 0.25, "news": 0.15}
        result = _recompute_weights(outcomes, current)
        assert sum(result.values()) == pytest.approx(1.0, abs=1e-3)
        # technical clearly dominates in the synthetic data -> should end up
        # at or near its upper bound (0.80) after normalization.
        assert result["technical"] > current["technical"]


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
        # Every other test in this class monkeypatches _TRADE_OUTCOMES_FILE/
        # _LIVE_WEIGHTS_FILE (see module docstring: "All file I/O is redirected
        # to tmp_path via monkeypatch"). This one didn't, so run_calibration()
        # fell through to its real defaults — reading the actual
        # data/logs/trade_outcomes.csv and, on a passing calibration, writing
        # the actual data/processed/calibrated_weights.json straight into
        # live scoring. Confirmed live: running this suite silently overwrote
        # the production weight file with an uncalibrated-governance-bypassing
        # last_calibrated timestamp.
        import swing_model.feedback_loop as fl
        p = tmp_path / "outcomes.csv"
        outcomes = [_outcome(result="win")] * 16 + [_outcome(result="loss")] * 4
        _write_outcomes(p, outcomes)
        monkeypatch.setattr(fl, "_TRADE_OUTCOMES_FILE", p)
        monkeypatch.setattr(fl, "_LIVE_WEIGHTS_FILE", tmp_path / "weights.json")
        monkeypatch.setattr(fl, "_SIGNAL_WIN_RATES_FILE", tmp_path / "rates.json")
        result = run_calibration()
        for key in ("status", "weights_updated"):
            assert key in result

    def test_explicit_outcomes_param_bypasses_trade_outcomes_file(self, tmp_path, monkeypatch):
        """
        v2.2.20: run_calibration() accepts outcomes directly now — real callers
        should pass load_calibration_outcomes_from_paper_trades() since
        trade_outcomes.csv stays empty (no version has gone live). Confirms
        the explicit-outcomes path works even with a nonexistent trade_outcomes.csv.
        """
        import swing_model.feedback_loop as fl
        monkeypatch.setattr(fl, "_TRADE_OUTCOMES_FILE", tmp_path / "does_not_exist.csv")
        monkeypatch.setattr(fl, "_LIVE_WEIGHTS_FILE", tmp_path / "weights.json")
        monkeypatch.setattr(fl, "_SIGNAL_WIN_RATES_FILE", tmp_path / "rates.json")
        outcomes = [_outcome(result="win")] * 16 + [_outcome(result="loss")] * 4
        result = run_calibration(outcomes=outcomes)
        assert result["status"] in ("pass", "fail")  # not "no_data" — the file being missing didn't matter

    def test_cfg_holdout_and_threshold_are_honored(self, tmp_path, monkeypatch):
        """cfg's feedback_loop block should actually change behavior, not just document it."""
        import swing_model.feedback_loop as fl
        monkeypatch.setattr(fl, "_LIVE_WEIGHTS_FILE", tmp_path / "weights.json")
        monkeypatch.setattr(fl, "_SIGNAL_WIN_RATES_FILE", tmp_path / "rates.json")
        outcomes = [_outcome(result="win")] * 10 + [_outcome(result="loss")] * 4  # n=14
        cfg = {"feedback_loop": {"out_of_sample_holdout": 3}}
        # Default holdout_count=5 needs 15 trades minimum; cfg's holdout=3 needs only 13.
        result = run_calibration(outcomes=outcomes, cfg=cfg)
        assert result["status"] != "insufficient_data"
        assert result["holdout_count"] == 3

    def test_explicit_kwarg_overrides_cfg(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        monkeypatch.setattr(fl, "_LIVE_WEIGHTS_FILE", tmp_path / "weights.json")
        monkeypatch.setattr(fl, "_SIGNAL_WIN_RATES_FILE", tmp_path / "rates.json")
        outcomes = [_outcome(result="win")] * 10 + [_outcome(result="loss")] * 4
        cfg = {"feedback_loop": {"out_of_sample_holdout": 3}}
        result = run_calibration(outcomes=outcomes, holdout_count=2, cfg=cfg)
        assert result["holdout_count"] == 2


# ---------------------------------------------------------------------------
# load_calibration_outcomes_from_paper_trades
# ---------------------------------------------------------------------------

class TestLoadCalibrationOutcomesFromPaperTrades:
    def _write_paper_trades(self, path, rows):
        from paper_trading.paper_updater import _CSV_COLUMNS
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    def test_missing_file_returns_empty_list(self, tmp_path):
        from swing_model.feedback_loop import load_calibration_outcomes_from_paper_trades
        result = load_calibration_outcomes_from_paper_trades(tmp_path / "nonexistent.csv")
        assert result == []

    def test_only_closed_trades_included(self, tmp_path):
        from swing_model.feedback_loop import load_calibration_outcomes_from_paper_trades
        path = tmp_path / "paper_trades.csv"
        self._write_paper_trades(path, [
            {"signal_date": "2026-07-01", "ticker": "NVDA", "outcome": "win", "achieved_rr": "2.5",
             "technical_score": "30.0", "sentiment_score": "10.0", "news_score": "8.0"},
            {"signal_date": "2026-07-02", "ticker": "AMD", "outcome": ""},  # still open
        ])
        result = load_calibration_outcomes_from_paper_trades(path)
        assert len(result) == 1
        assert result[0]["ticker"] == "NVDA"

    def test_field_names_mapped_to_feedback_loop_schema(self, tmp_path):
        from swing_model.feedback_loop import load_calibration_outcomes_from_paper_trades
        path = tmp_path / "paper_trades.csv"
        self._write_paper_trades(path, [
            {"signal_date": "2026-07-01", "ticker": "NVDA", "outcome": "win", "achieved_rr": "2.5",
             "technical_score": "30.0", "sentiment_score": "10.0", "news_score": "8.0"},
        ])
        result = load_calibration_outcomes_from_paper_trades(path)
        row = result[0]
        assert row["technical_total"] == "30.0"
        assert row["sentiment_total"] == "10.0"
        assert row["news_total"] == "8.0"
        assert row["signal_key"] == "unknown"  # known gap — see function docstring


# ---------------------------------------------------------------------------
# live-weight calibration gating (load_live_weights_if_calibrated)
# ---------------------------------------------------------------------------

class TestLoadLiveWeightsIfCalibrated:
    def test_no_file_returns_none(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        from swing_model.feedback_loop import load_live_weights_if_calibrated
        monkeypatch.setattr(fl, "_LIVE_WEIGHTS_FILE", tmp_path / "does_not_exist.json")
        assert load_live_weights_if_calibrated() is None

    def test_placeholder_weights_without_metadata_return_none(self, tmp_path, monkeypatch):
        # Simulates calibrated_weights.json existing on disk as a hardcoded
        # placeholder (never actually produced by a passing calibration) —
        # exactly today's real on-disk state. Must NOT silently start
        # affecting live scoring.
        import swing_model.feedback_loop as fl
        from swing_model.feedback_loop import load_live_weights_if_calibrated
        weights_path = tmp_path / "weights.json"
        weights_path.write_text(json.dumps({"technical": 0.6, "sentiment": 0.25, "news": 0.15}))
        monkeypatch.setattr(fl, "_LIVE_WEIGHTS_FILE", weights_path)
        assert load_live_weights_if_calibrated() is None

    def test_genuinely_calibrated_weights_are_returned(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        from swing_model.feedback_loop import load_live_weights_if_calibrated, _save_live_weights
        monkeypatch.setattr(fl, "_LIVE_WEIGHTS_FILE", tmp_path / "weights.json")
        _save_live_weights({"technical": 0.65, "sentiment": 0.2, "news": 0.15}, n_trades=40)
        result = load_live_weights_if_calibrated()
        assert result == {"technical": 0.65, "sentiment": 0.2, "news": 0.15}

    def test_saved_metadata_does_not_leak_into_weight_dict(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        from swing_model.feedback_loop import load_live_weights_if_calibrated, _save_live_weights
        monkeypatch.setattr(fl, "_LIVE_WEIGHTS_FILE", tmp_path / "weights.json")
        _save_live_weights({"technical": 0.65, "sentiment": 0.2, "news": 0.15}, n_trades=40)
        result = load_live_weights_if_calibrated()
        assert "last_calibrated" not in result
        assert "n_trades" not in result

    def test_run_calibration_pass_makes_weights_available(self, tmp_path, monkeypatch):
        """End-to-end: a genuine passing calibration should flip
        load_live_weights_if_calibrated() from None to a real dict."""
        import swing_model.feedback_loop as fl
        from swing_model.feedback_loop import load_live_weights_if_calibrated
        monkeypatch.setattr(fl, "_LIVE_WEIGHTS_FILE", tmp_path / "weights.json")
        monkeypatch.setattr(fl, "_SIGNAL_WIN_RATES_FILE", tmp_path / "rates.json")
        assert load_live_weights_if_calibrated() is None

        # Strong, consistent technical-favors-wins signal so the >5pp version
        # gate isn't tripped by the very first small nudge, and holdout passes.
        outcomes = (
            [_outcome(result="win", tech=45.0, sent=20.0, news=10.0)] * 16
            + [_outcome(result="loss", tech=10.0, sent=20.0, news=10.0)] * 4
        )
        result = run_calibration(outcomes=outcomes)
        if result["status"] == "pass" and not result["needs_version_increment"]:
            assert load_live_weights_if_calibrated() is not None
        else:
            # Whatever the outcome, unweighted defaults must still be inert.
            assert load_live_weights_if_calibrated() is None


class TestFitSectorCalibratedWeights:
    def test_sector_below_sample_floor_gets_no_entry(self):
        from swing_model.feedback_loop import fit_sector_calibrated_weights, _MIN_SAMPLES_FOR_SECTOR_CALIBRATION
        assert _MIN_SAMPLES_FOR_SECTOR_CALIBRATION > 10  # sanity: test data below stays below
        outcomes = [_outcome(result="win", tech=45.0)] * 5 + [_outcome(result="loss", tech=10.0)] * 5
        result = fit_sector_calibrated_weights({"regional_banks": outcomes})
        assert "regional_banks" not in result

    def test_sector_at_or_above_floor_with_real_signal_gets_fit(self):
        from swing_model.feedback_loop import fit_sector_calibrated_weights, _MIN_SAMPLES_FOR_SECTOR_CALIBRATION
        n_half = _MIN_SAMPLES_FOR_SECTOR_CALIBRATION // 2 + 5
        outcomes = _synthetic_outcomes_technical_separates(n=n_half * 2)
        result = fit_sector_calibrated_weights({"consumer_discretionary": outcomes})
        assert "consumer_discretionary" in result
        weights = result["consumer_discretionary"]
        assert set(weights.keys()) >= {"technical", "sentiment", "news", "n_trades", "shrinkage_factor", "last_calibrated"}
        assert abs(weights["technical"] + weights["sentiment"] + weights["news"] - 1.0) < 1e-6
        assert weights["n_trades"] == n_half * 2

    def test_low_sample_sector_near_floor_is_shrunk_toward_default(self):
        # Just above the floor: shrinkage_factor should be well below 1.0,
        # pulling the result toward _DEFAULT_WEIGHTS rather than fully
        # trusting a thin fit.
        from swing_model.feedback_loop import (
            fit_sector_calibrated_weights, _MIN_SAMPLES_FOR_SECTOR_CALIBRATION, _SECTOR_SHRINKAGE_FULL_TRUST_N,
        )
        outcomes = _synthetic_outcomes_technical_separates(n=_MIN_SAMPLES_FOR_SECTOR_CALIBRATION)
        result = fit_sector_calibrated_weights({"healthcare": outcomes})
        if "healthcare" in result:  # fit may still be degenerate at exactly the floor
            assert result["healthcare"]["shrinkage_factor"] < _MIN_SAMPLES_FOR_SECTOR_CALIBRATION / _SECTOR_SHRINKAGE_FULL_TRUST_N + 0.01

    def test_multiple_sectors_fit_independently(self):
        from swing_model.feedback_loop import fit_sector_calibrated_weights, _MIN_SAMPLES_FOR_SECTOR_CALIBRATION
        n = _MIN_SAMPLES_FOR_SECTOR_CALIBRATION + 20
        result = fit_sector_calibrated_weights({
            "semiconductors": _synthetic_outcomes_technical_separates(n=n, seed=1),
            "regional_banks": [_outcome(result="win")] * 5,  # below floor
        })
        assert "semiconductors" in result
        assert "regional_banks" not in result

    def test_weights_stay_within_recompute_weights_bounds(self):
        from swing_model.feedback_loop import fit_sector_calibrated_weights, _MIN_SAMPLES_FOR_SECTOR_CALIBRATION
        n = _MIN_SAMPLES_FOR_SECTOR_CALIBRATION + 100
        result = fit_sector_calibrated_weights({"semiconductors": _synthetic_outcomes_technical_separates(n=n)})
        if "semiconductors" in result:
            w = result["semiconductors"]
            assert 0.30 <= w["technical"] <= 0.80
            assert 0.05 <= w["sentiment"] <= 0.40
            assert 0.05 <= w["news"] <= 0.30


class TestLoadLiveWeightsIfCalibratedPerSector:
    def test_sector_with_no_entry_falls_back_to_global(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        from swing_model.feedback_loop import load_live_weights_if_calibrated, _save_live_weights, save_sector_weights
        monkeypatch.setattr(fl, "_LIVE_WEIGHTS_FILE", tmp_path / "global.json")
        monkeypatch.setattr(fl, "_SECTOR_LIVE_WEIGHTS_FILE", tmp_path / "by_sector.json")
        _save_live_weights({"technical": 0.55, "sentiment": 0.30, "news": 0.15}, n_trades=40)
        save_sector_weights({"consumer_discretionary": {
            "technical": 0.35, "sentiment": 0.47, "news": 0.18, "n_trades": 405,
            "shrinkage_factor": 1.0, "last_calibrated": "2026-08-15T00:00:00+00:00",
        }})
        # regional_banks has no entry -> falls back to the global weights
        assert load_live_weights_if_calibrated(sector="regional_banks") == {
            "technical": 0.55, "sentiment": 0.30, "news": 0.15,
        }

    def test_sector_with_entry_returns_its_own_weights(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        from swing_model.feedback_loop import load_live_weights_if_calibrated, save_sector_weights
        monkeypatch.setattr(fl, "_LIVE_WEIGHTS_FILE", tmp_path / "global.json")
        monkeypatch.setattr(fl, "_SECTOR_LIVE_WEIGHTS_FILE", tmp_path / "by_sector.json")
        save_sector_weights({"consumer_discretionary": {
            "technical": 0.35, "sentiment": 0.47, "news": 0.18, "n_trades": 405,
            "shrinkage_factor": 1.0, "last_calibrated": "2026-08-15T00:00:00+00:00",
        }})
        result = load_live_weights_if_calibrated(sector="consumer_discretionary")
        assert result == {"technical": 0.35, "sentiment": 0.47, "news": 0.18}

    def test_sector_none_preserves_original_global_only_behavior(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        from swing_model.feedback_loop import load_live_weights_if_calibrated, save_sector_weights
        monkeypatch.setattr(fl, "_LIVE_WEIGHTS_FILE", tmp_path / "global.json")
        monkeypatch.setattr(fl, "_SECTOR_LIVE_WEIGHTS_FILE", tmp_path / "by_sector.json")
        save_sector_weights({"consumer_discretionary": {
            "technical": 0.35, "sentiment": 0.47, "news": 0.18, "n_trades": 405,
            "shrinkage_factor": 1.0, "last_calibrated": "2026-08-15T00:00:00+00:00",
        }})
        assert load_live_weights_if_calibrated() is None  # no global calibration saved


# ---------------------------------------------------------------------------
# should_recalibrate
# ---------------------------------------------------------------------------

class TestShouldRecalibrate:
    def test_never_calibrated_and_below_floor_returns_false(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        from swing_model.feedback_loop import should_recalibrate
        monkeypatch.setattr(fl, "_LIVE_WEIGHTS_FILE", tmp_path / "does_not_exist.json")
        assert should_recalibrate(closed_trade_count=5) is False

    def test_never_calibrated_and_above_floor_returns_true(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        from swing_model.feedback_loop import should_recalibrate
        monkeypatch.setattr(fl, "_LIVE_WEIGHTS_FILE", tmp_path / "does_not_exist.json")
        assert should_recalibrate(closed_trade_count=20) is True

    def test_due_every_n_trades_since_last_calibration(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        from swing_model.feedback_loop import should_recalibrate, _save_live_weights
        monkeypatch.setattr(fl, "_LIVE_WEIGHTS_FILE", tmp_path / "weights.json")
        _save_live_weights({"technical": 0.6, "sentiment": 0.25, "news": 0.15}, n_trades=20)

        cfg = {"feedback_loop": {"recalibrate_every_n_trades": 20, "recalibrate_monthly": False}}
        assert should_recalibrate(closed_trade_count=35, cfg=cfg) is False  # only +15 since last
        assert should_recalibrate(closed_trade_count=41, cfg=cfg) is True   # +21 since last

    def test_not_due_when_recently_calibrated_and_few_new_trades(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        from swing_model.feedback_loop import should_recalibrate, _save_live_weights
        monkeypatch.setattr(fl, "_LIVE_WEIGHTS_FILE", tmp_path / "weights.json")
        _save_live_weights({"technical": 0.6, "sentiment": 0.25, "news": 0.15}, n_trades=20)

        cfg = {"feedback_loop": {"recalibrate_every_n_trades": 20, "recalibrate_monthly": False}}
        assert should_recalibrate(closed_trade_count=22, cfg=cfg) is False

    def test_monthly_cadence_triggers_after_30_days(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        from swing_model.feedback_loop import should_recalibrate

        old_timestamp = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        weights_path = tmp_path / "weights.json"
        weights_path.write_text(json.dumps({
            "technical": 0.6, "sentiment": 0.25, "news": 0.15,
            "last_calibrated": old_timestamp, "n_trades": 20,
        }))
        monkeypatch.setattr(fl, "_LIVE_WEIGHTS_FILE", weights_path)

        cfg = {"feedback_loop": {"recalibrate_every_n_trades": 1000, "recalibrate_monthly": True}}
        assert should_recalibrate(closed_trade_count=21, cfg=cfg) is True

    def test_monthly_disabled_does_not_trigger_on_time_alone(self, tmp_path, monkeypatch):
        import swing_model.feedback_loop as fl
        from swing_model.feedback_loop import should_recalibrate

        old_timestamp = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()
        weights_path = tmp_path / "weights.json"
        weights_path.write_text(json.dumps({
            "technical": 0.6, "sentiment": 0.25, "news": 0.15,
            "last_calibrated": old_timestamp, "n_trades": 20,
        }))
        monkeypatch.setattr(fl, "_LIVE_WEIGHTS_FILE", weights_path)

        cfg = {"feedback_loop": {"recalibrate_every_n_trades": 1000, "recalibrate_monthly": False}}
        assert should_recalibrate(closed_trade_count=21, cfg=cfg) is False


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
        result = generate_weekly_summary(
            str(tmp_path / "nonexistent.csv"), paper_trades_path=tmp_path / "paper_trades.csv"
        )
        assert result["status"] == "no_data"
        assert result["total_trades"] == 0
        assert "go_live_gate" in result

    def test_win_rates_computed_correctly(self, tmp_path, monkeypatch):
        import monitoring.performance_dashboard as pd_mod
        monkeypatch.setattr(pd_mod, "_PERFORMANCE_LOG", tmp_path / "perf_log.csv")
        path = tmp_path / "outcomes.csv"
        self._write_trade_csv(path, 8, 2)
        result = generate_weekly_summary(str(path), paper_trades_path=tmp_path / "paper_trades.csv")
        assert result["win_rate_10"] == pytest.approx(0.8)
        assert result["total_trades"] == 10

    def test_review_triggered_on_low_win_rate(self, tmp_path, monkeypatch):
        import monitoring.performance_dashboard as pd_mod
        monkeypatch.setattr(pd_mod, "_PERFORMANCE_LOG", tmp_path / "perf_log.csv")
        path = tmp_path / "outcomes.csv"
        self._write_trade_csv(path, 12, 8)  # 60% — below 70%
        result = generate_weekly_summary(str(path), paper_trades_path=tmp_path / "paper_trades.csv")
        assert result["review_triggered"] is True

    def test_no_review_trigger_on_good_win_rate(self, tmp_path, monkeypatch):
        import monitoring.performance_dashboard as pd_mod
        monkeypatch.setattr(pd_mod, "_PERFORMANCE_LOG", tmp_path / "perf_log.csv")
        path = tmp_path / "outcomes.csv"
        self._write_trade_csv(path, 17, 3)  # 85%
        result = generate_weekly_summary(str(path), paper_trades_path=tmp_path / "paper_trades.csv")
        assert result["review_triggered"] is False

    def test_required_keys_present(self, tmp_path, monkeypatch):
        import monitoring.performance_dashboard as pd_mod
        monkeypatch.setattr(pd_mod, "_PERFORMANCE_LOG", tmp_path / "perf_log.csv")
        path = tmp_path / "outcomes.csv"
        self._write_trade_csv(path, 8, 2)
        result = generate_weekly_summary(str(path), paper_trades_path=tmp_path / "paper_trades.csv")
        for key in ("win_rate_10", "win_rate_20", "win_rate_50", "avg_rr_20",
                    "peak_to_trough_pct", "total_trades", "review_triggered", "go_live_gate"):
            assert key in result

    def test_go_live_gate_reflects_paper_trades_csv(self, tmp_path, monkeypatch):
        """
        The go-live gate reads paper_trading/paper_trades.csv, not the
        trade_outcomes.csv this function otherwise operates on — confirms
        they're genuinely independent by giving each a different trade count.
        """
        import monitoring.performance_dashboard as pd_mod
        monkeypatch.setattr(pd_mod, "_PERFORMANCE_LOG", tmp_path / "perf_log.csv")
        path = tmp_path / "outcomes.csv"
        self._write_trade_csv(path, 8, 2)

        paper_trades_path = tmp_path / "paper_trades.csv"
        from paper_trading.paper_updater import _CSV_COLUMNS
        with open(paper_trades_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerow({"signal_date": "2026-01-01", "ticker": "NVDA", "outcome": "win", "achieved_rr": "2.0"})

        result = generate_weekly_summary(str(path), paper_trades_path=paper_trades_path)
        assert result["go_live_gate"]["data_status"] == "insufficient_trades"  # n=1, below the floor
        assert result["total_trades"] == 10  # unaffected — from trade_outcomes.csv, a different file


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
