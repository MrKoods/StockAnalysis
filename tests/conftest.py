"""
Repo-wide pytest fixtures.
"""

import logging.handlers

import pytest
import requests

import shared.utils.logger as logger_module
import shared.utils.scan_lock as scan_lock_module
import backtesting.backtest_engine as backtest_engine_module
import swing_model.feedback_loop as feedback_loop_module
import shared.utils.black_swan_detector as black_swan_detector_module
import monitoring.performance_dashboard as performance_dashboard_module
import shared.api_clients.market_data_client as market_data_client_module
import paper_trading.paper_runner as paper_runner_module
import paper_trading.paper_updater as paper_updater_module


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
def _isolate_paper_trading_csvs(tmp_path, monkeypatch):
    """
    Same class of problem as _isolate_csv_logs, this project's own repeatedly
    -learned lesson (see that fixture's and _isolate_feedback_loop_files'
    docstrings for two prior real-file-pollution incidents this exact
    "blanket autouse default" pattern was built to close) — caught again
    live, 2026-08-24: adding the rank-based parallel paper-trading track
    means run_paper_scan() now ALSO writes to RANK_TRADES_CSV on every
    call, and 5 existing tests across two files that already hand-patched
    PAPER_TRADES_CSV per-test had no reason to know about the new file at
    all — each one silently wrote real-looking rows into the actual
    paper_trading/rank_trades.csv until this fixture closed the gap.

    Isolates both CSV paths AND both lock-file paths, in BOTH paper_runner
    and paper_updater — paper_updater.py imports PAPER_TRADES_LOCK_FILE/
    RANK_TRADES_LOCK_FILE BY VALUE from paper_runner (`from
    paper_trading.paper_runner import ... PAPER_TRADES_LOCK_FILE,
    RANK_TRADES_LOCK_FILE`), a separate name binding in paper_updater's own
    module namespace — patching paper_runner's copy alone does not affect
    paper_updater's, so both must be patched explicitly (confirmed by
    tests/test_paper_updater_mark_to_market.py already needing to patch
    both modules' copies by hand for the same reason).

    Per-test monkeypatches that already exist (most of
    tests/test_multi_sector_live_pipeline.py, tests/test_app_ui_persistence.py)
    are harmless now, not redundant to remove — same reasoning as every
    other fixture in this file.
    """
    monkeypatch.setattr(paper_runner_module, "PAPER_TRADES_CSV", tmp_path / "paper_trades.csv")
    monkeypatch.setattr(paper_runner_module, "PAPER_TRADES_LOCK_FILE", tmp_path / "paper_trades.csv.lock")
    monkeypatch.setattr(paper_runner_module, "RANK_TRADES_CSV", tmp_path / "rank_trades.csv")
    monkeypatch.setattr(paper_runner_module, "RANK_TRADES_LOCK_FILE", tmp_path / "rank_trades.csv.lock")
    monkeypatch.setattr(paper_updater_module, "PAPER_TRADES_CSV", tmp_path / "paper_trades.csv")
    monkeypatch.setattr(paper_updater_module, "PAPER_TRADES_LOCK_FILE", tmp_path / "paper_trades.csv.lock")
    monkeypatch.setattr(paper_updater_module, "RANK_TRADES_CSV", tmp_path / "rank_trades.csv")
    monkeypatch.setattr(paper_updater_module, "RANK_TRADES_LOCK_FILE", tmp_path / "rank_trades.csv.lock")


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


@pytest.fixture(autouse=True)
def _isolate_feedback_loop_files(tmp_path, monkeypatch):
    """
    Same class of problem as _isolate_csv_logs, different subsystem:
    swing_model/feedback_loop.py has 5 of its own real-file defaults
    (_TRADE_OUTCOMES_FILE, _SIGNAL_WIN_RATES_FILE, _LIVE_WEIGHTS_FILE,
    _SECTOR_LIVE_WEIGHTS_FILE, _PAPER_TRADES_FILE) that most tests in
    tests/test_phase14_feedback.py already monkeypatch by hand per-test — but
    "by hand, in every test" has already failed silently once (see that
    file's test_result_contains_required_keys docstring: a test that forgot
    to patch _TRADE_OUTCOMES_FILE/_LIVE_WEIGHTS_FILE overwrote the real
    production calibrated_weights.json with a governance-bypassing
    last_calibrated timestamp) and a full-audit pass (2026-08-22) found the
    real data/logs/trade_outcomes.csv still 285 rows deep in obviously
    synthetic test data (round $100/$120 prices, blank structure/signal_key,
    millisecond-apart duplicate rows) — from some other, still-unidentified
    test path than the one already fixed in place. A blanket autouse default
    closes the whole class rather than relying on every current and future
    test remembering its own explicit patch; per-test monkeypatches that
    already exist are harmless now, not redundant to remove.
    """
    monkeypatch.setattr(feedback_loop_module, "_TRADE_OUTCOMES_FILE", tmp_path / "trade_outcomes.csv")
    monkeypatch.setattr(feedback_loop_module, "_SIGNAL_WIN_RATES_FILE", tmp_path / "signal_win_rates.json")
    monkeypatch.setattr(feedback_loop_module, "_LIVE_WEIGHTS_FILE", tmp_path / "calibrated_weights.json")
    monkeypatch.setattr(feedback_loop_module, "_SECTOR_LIVE_WEIGHTS_FILE", tmp_path / "calibrated_weights_by_sector.json")
    monkeypatch.setattr(feedback_loop_module, "_PAPER_TRADES_FILE", tmp_path / "paper_trades.csv")


@pytest.fixture(autouse=True)
def _isolate_black_swan_state(tmp_path, monkeypatch):
    """
    Same class of problem as _isolate_feedback_loop_files, applied
    immediately to its own new file: black_swan_detector.py's
    load/save_black_swan_state() (added 2026-08-23 to give paper_runner.py a
    real crash circuit breaker) default to data/processed/black_swan_state.json.
    Isolated from day one instead of waiting to discover a test wrote a fake
    "black swan triggered" episode into the real state file.
    """
    monkeypatch.setattr(black_swan_detector_module, "_STATE_FILE", tmp_path / "black_swan_state.json")


@pytest.fixture(autouse=True)
def _isolate_performance_log(tmp_path, monkeypatch):
    """
    Same class of problem, caught live while adding the fix above:
    monitoring/performance_dashboard.py's log_performance_entry() defaults to
    the real data/logs/performance_log.csv. Writing tests/test_weekly_summary_
    wiring.py without this fixture immediately wrote 2 synthetic rows into
    the real file — proof this class of bug is still easy to reintroduce
    even right after fixing the last instance of it, not just a one-off.
    """
    monkeypatch.setattr(performance_dashboard_module, "_PERFORMANCE_LOG", tmp_path / "performance_log.csv")


@pytest.fixture(autouse=True)
def _isolate_ohlcv_cache(monkeypatch):
    """
    market_data_client.py::fetch_ohlcv_batch() gained a process-lifetime
    in-memory cache (2026-08-23, dedup fix for run_pipeline/_fetch_market_
    context's overlapping fetches) keyed by (ticker, interval). Real
    production risk is nil (a fresh process per scan naturally starts with
    an empty cache) but tests/test_market_data_client.py mocks yf.download
    directly and calls the real fetch_ohlcv_batch() on top — without
    clearing this between tests, one test's mocked data for a given ticker
    could silently satisfy a later test's request for that same ticker
    symbol instead of exercising its own mock.
    """
    monkeypatch.setattr(market_data_client_module, "_OHLCV_BATCH_CACHE", {})


@pytest.fixture(autouse=True)
def _isolate_scan_lock(tmp_path, monkeypatch):
    """
    Same issue, different subsystem: run_paper_scan() now acquires a file lock
    (shared/utils/scan_lock.py) at its default path, data/processed/scan_locks/,
    before every test that exercises it even indirectly (test_app_ui_persistence.py
    calls pr.run_paper_scan() directly). Without this, tests would create/remove
    a real lock file in the actual project directory and — if a test ever
    crashed between acquiring and releasing it — could leave a stale lock
    behind that blocks a real future scan.
    """
    monkeypatch.setattr(scan_lock_module, "_LOCK_DIR", tmp_path / "scan_locks")


@pytest.fixture(autouse=True)
def _block_real_discord_sends(monkeypatch):
    """
    Same class of problem as the fixtures above, different subsystem: a test
    exercising any code path that reaches shared/utils/discord_alerts.py's
    send_*_alert functions without explicitly mocking requests.post (or
    _post_to_webhook) posts a REAL message to whichever Discord channel
    DISCORD_WEBHOOK_URL in .env points at. Observed in practice: a signal-
    decay test using synthetic fixture data (NVDA, confidence 85->40, entry
    $100/stop $95) genuinely posted to the real trading-alerts channel,
    because an earlier import in the same test session had already loaded
    .env (paper_updater.py calls load_dotenv() at module scope) and the test
    itself forgot to mock the alert sender.

    requests.post is used nowhere else in this codebase (confirmed by grep —
    every other API client here uses requests.get), so blocking it globally
    for tests is precisely scoped to this one risk, not a broad network ban.

    Raises loudly rather than silently no-op'ing, so a test that forgets to
    mock its alert path fails immediately and obviously — pointing straight
    at the missing mock — instead of either a real send slipping through or
    a false "it worked" from an unintended stub. A test that specifically
    wants to verify real send behavior (see test_discord_alerts.py) already
    monkeypatches requests.post itself inside the test body, which runs
    after this fixture's setup and so correctly overrides it.
    """
    def _blocked_post(url, *args, **kwargs):
        raise RuntimeError(
            f"Blocked a real HTTP POST to {url!r} during a test. This test path "
            "reaches a real Discord send — mock requests.post (or the specific "
            "discord_alerts.send_*/_post_to_webhook function involved) explicitly."
        )

    monkeypatch.setattr(requests, "post", _blocked_post)
