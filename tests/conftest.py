"""
Repo-wide pytest fixtures.

Every fixture here is autouse and blanket-scoped by design. V2 learned this the
hard way, repeatedly: relying on each test to remember its own patch left the
real validation_log.csv 99.7% synthetic, put 285 fake rows in the real
trade_outcomes.csv, overwrote production calibrated weights, and once posted a
genuine message to the live Discord channel. Defaults must be safe; per-test
patches are a bonus, never the mechanism. See docs/v2_postmortem.md, rule 9.
"""

import logging.handlers

import pytest
import requests

import shared.api_clients.market_data_client as market_data_client_module
import shared.utils.logger as logger_module


@pytest.fixture(autouse=True, scope="session")
def _isolate_app_log(tmp_path_factory):
    """
    Redirect the RotatingFileHandler get_logger() attaches to every logger.

    Modules bind `logger = get_logger(__name__)` at import time, so a handler
    pointing at the real data/logs/app.log already exists before any per-test
    fixture runs — patching _LOG_DIR alone would not touch them. Swap the
    handler on every logger created so far, and repoint _LOG_DIR so loggers
    created later in the session follow suit.
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
    Redirect write_audit_entry / write_validation_entry / write_override_entry
    away from the real data/logs/*.csv files, for every test automatically.
    """
    monkeypatch.setattr(logger_module, "_AUDIT_LOG_PATH", tmp_path / "audit_log.csv")
    monkeypatch.setattr(logger_module, "_VALIDATION_LOG_PATH", tmp_path / "validation_log.csv")
    monkeypatch.setattr(logger_module, "_OVERRIDE_LOG_PATH", tmp_path / "override_log.csv")


@pytest.fixture(autouse=True)
def _isolate_ohlcv_cache(monkeypatch):
    """
    fetch_ohlcv_batch() keeps a process-lifetime in-memory cache keyed by
    (ticker, interval). Production risk is nil — a fresh process per run starts
    empty — but tests mock yf.download and call the real function on top, so
    without clearing this one test's mocked data could satisfy another test's
    request for the same symbol instead of exercising its own mock.
    """
    monkeypatch.setattr(market_data_client_module, "_OHLCV_BATCH_CACHE", {})


@pytest.fixture(autouse=True)
def _block_real_network_posts(monkeypatch):
    """
    Fail loudly on any real HTTP POST from a test.

    Raises rather than silently no-op'ing, so a test that reaches an unmocked
    network path fails immediately and points straight at the missing mock,
    instead of either a real send slipping through or a false pass from an
    unintended stub. A test that specifically wants to verify send behavior
    patches requests.post inside its own body, which runs after this fixture
    and correctly overrides it.
    """
    def _blocked_post(url, *args, **kwargs):
        raise RuntimeError(
            f"Blocked a real HTTP POST to {url!r} during a test. Mock the call "
            "explicitly if this path is intended."
        )

    monkeypatch.setattr(requests, "post", _blocked_post)
