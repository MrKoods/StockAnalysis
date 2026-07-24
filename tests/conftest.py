"""
Repo-wide pytest fixtures.
"""

import pytest

import shared.utils.logger as logger_module
import backtesting.backtest_engine as backtest_engine_module


@pytest.fixture(autouse=True)
def _isolate_csv_logs(tmp_path, monkeypatch):
    """
    Redirect write_audit_entry/write_validation_entry/write_override_entry's
    default paths into this test's tmp_path, for every test automatically.

    Without this, any test that exercises a real error path (a mocked API
    failure, a data_validator edge case, an intentionally malformed fixture)
    calls straight through to shared/utils/logger.py's write_*_entry helpers,
    which default to the real data/logs/*.csv files — silently appending
    synthetic test entries (ohlcv_empty_dataframe, sentiment_bullish_ratio_out_
    of_bounds_1.5, etc.) to the production validation/audit/override logs.
    Observed in practice: a full test-suite run left a burst of fake entries
    in the real validation_log.csv, indistinguishable at a glance from actual
    production data issues — the file was found to be 99.7% test pollution
    going back to its very first entry once actually audited.
    """
    monkeypatch.setattr(logger_module, "_AUDIT_LOG_PATH", tmp_path / "audit_log.csv")
    monkeypatch.setattr(logger_module, "_VALIDATION_LOG_PATH", tmp_path / "validation_log.csv")
    monkeypatch.setattr(logger_module, "_OVERRIDE_LOG_PATH", tmp_path / "override_log.csv")


@pytest.fixture(autouse=True)
def _isolate_backtest_reports(tmp_path, monkeypatch):
    """
    Same issue, different subsystem: test_phase12_backtest.py's run_backtest()
    smoke tests call straight through to backtest_engine._save_report(), which
    defaulted to the real backtesting/reports/ directory — writing a real-looking
    (but synthetic, all-zero) swing_backtest_<today>.json every time the test
    suite ran.
    """
    monkeypatch.setattr(backtest_engine_module, "_REPORTS_DIR", tmp_path / "reports")
