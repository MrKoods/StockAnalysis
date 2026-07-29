"""
Repo-wide pytest fixtures.
"""

import logging.handlers

import pytest

import shared.utils.logger as logger_module
import backtesting.backtest_engine as backtest_engine_module


@pytest.fixture(autouse=True, scope="session")
def _isolate_app_log(tmp_path_factory):
    """
    Same issue as _isolate_csv_logs, for the RotatingFileHandler get_logger()
    attaches to every logger. Loggers created at import time (most modules do
    `logger = get_logger(__name__)` at module scope) already have a handler
    bound to the real data/logs/app.log before any per-test fixture runs, so
    monkeypatching _LOG_DIR alone wouldn't touch them — swap the handler
    directly on every logger created so far, and repoint _LOG_DIR so any
    logger created for the first time later in the session follows suit.
    """
    tmp_log_dir = tmp_path_factory.mktemp("logs")
    logger_module._LOG_DIR = tmp_log_dir
    for logger in logger_module._loggers.values():
        for handler in list(logger.handlers):
            if isinstance(handler, logging.handlers.RotatingFileHandler):
                logger.removeHandler(handler)
                handler.close()
        logger.addHandler(logger_module._make_file_handler(tmp_log_dir))


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
