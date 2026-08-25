"""
Tests for update_paper_trades()'s run_calibration parameter (2026-08-24,
rank-based parallel paper-trading track) — _maybe_run_calibration() writes
into the SHARED data/processed/calibrated_weights.json that feeds live
scoring weights for BOTH the threshold and rank tracks (same scoring.py
engine). The rank track's very different outcome distribution must never
silently recalibrate weights the threshold track also depends on, so its
daily-cycle call passes run_calibration=False — confirmed here by spying on
_maybe_run_calibration rather than asserting on calibrated_weights.json
directly (keeps this test decoupled from feedback_loop.py's own internals).
"""

import pandas as pd
import pytest

import paper_trading.paper_runner as pr
import paper_trading.paper_updater as pu
from paper_trading.paper_updater import update_paper_trades


def _row(**overrides):
    row = {col: "" for col in pr._CSV_COLUMNS}
    row.update({
        "signal_date": "2026-08-10",
        "ticker": "NVDA",
        "direction": "bullish",
        "entry_price": "100.00",
        "stop_loss": "95.00",
        "target": "115.00",
        "position_type": "shares",
        "position_size": "10",
        "dollar_risk": "75.00",
        "actual_dollar_risk": "50.00",
        "fill_date": "2026-08-11",
        "fill_price": "100.00",
        "outcome": "",
    })
    row.update(overrides)
    return row


def _bars_that_hit_stop():
    # Low <= stop_loss (95) on the first bar -> guaranteed "loss" close,
    # so closed_count > 0 and the run_calibration gate actually matters.
    return pd.DataFrame(
        [{"Open": 99.0, "High": 100.0, "Low": 94.0, "Close": 94.5}],
        index=pd.to_datetime(["2026-08-12"]),
    )


@pytest.fixture(autouse=True)
def _isolate_csv(tmp_path, monkeypatch):
    csv_path = tmp_path / "trades.csv"
    lock_path = tmp_path / "trades.csv.lock"
    monkeypatch.setattr(pr, "PAPER_TRADES_CSV", csv_path)
    monkeypatch.setattr(pr, "PAPER_TRADES_LOCK_FILE", lock_path)
    monkeypatch.setattr(pu, "fetch_next_earnings_date", lambda ticker: None)
    monkeypatch.setattr(pu, "_download_ohlcv", lambda ticker, start: _bars_that_hit_stop())
    monkeypatch.setattr(pu, "send_paper_outcome_alert", lambda trade, track="threshold": True)
    return csv_path, lock_path


def test_run_calibration_false_never_invokes_maybe_run_calibration(monkeypatch, _isolate_csv):
    csv_path, lock_path = _isolate_csv
    pr._append_row(_row(), csv_path=csv_path, lock_path=lock_path)

    calls = []
    monkeypatch.setattr(pu, "_maybe_run_calibration", lambda trades: calls.append(trades))

    closed_count = update_paper_trades(csv_path=csv_path, lock_path=lock_path, run_calibration=False)

    assert closed_count == 1  # confirms the trade really did close this run
    assert calls == []  # ...but calibration was never touched


def test_run_calibration_true_default_still_invokes_it_as_before(monkeypatch, _isolate_csv):
    """Regression guard: the new parameter must not silently change the
    threshold track's existing behavior. Default (omitted) and explicit
    True both still call _maybe_run_calibration when trades close, exactly
    as before this parameter existed."""
    csv_path, lock_path = _isolate_csv
    pr._append_row(_row(), csv_path=csv_path, lock_path=lock_path)

    calls = []
    monkeypatch.setattr(pu, "_maybe_run_calibration", lambda trades: calls.append(trades))

    closed_count = update_paper_trades(csv_path=csv_path, lock_path=lock_path)  # run_calibration omitted

    assert closed_count == 1
    assert len(calls) == 1
