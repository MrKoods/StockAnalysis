"""
Tests for swing_model/indicator_pipeline.py's fetch_fundamental_data().

Scope: the incremental-save fix specifically (no broader test coverage existed
for this module before). Covers the real incident this fix addresses — a
mid-batch interruption discarding already-fetched tickers because the old
code only saved once, after the entire loop finished.
"""

import json
from datetime import datetime
from unittest.mock import patch

import pytest

import swing_model.indicator_pipeline as ip


@pytest.fixture(autouse=True)
def _isolate_state_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ip, "_FUNDAMENTAL_STATE_PATH", tmp_path / "fundamental_state.json")


def _fake_fundamentals(ticker):
    return {"ticker": ticker, "valuation": {}, "earnings": {}, "revisions": {}}


class TestFetchFundamentalDataIncrementalSave:
    def test_all_succeed_saves_all_tickers_and_sets_last_updated(self):
        with patch.object(ip.FundamentalClient, "get_all_fundamentals", side_effect=_fake_fundamentals):
            with patch.object(ip, "datetime") as mock_dt:
                # Force the Monday-post-17:00-ET refresh path
                mock_dt.now.side_effect = lambda tz=None: datetime(2026, 7, 20, 18, 0, tzinfo=tz)
                result = ip.fetch_fundamental_data(["NVDA", "AMD"])

        assert result["last_updated"] is not None
        assert result["tickers"]["NVDA"]["ticker"] == "NVDA"
        assert result["tickers"]["AMD"]["ticker"] == "AMD"

    def test_interruption_mid_batch_preserves_already_fetched_tickers(self):
        """
        The actual bug: a mid-batch interruption (KeyboardInterrupt, matching
        the real Ctrl+C incident) must not discard tickers that already
        completed. With the old code (single save at the very end), this
        would leave the state file completely unchanged — none of NVDA's
        real progress would survive. With the fix, NVDA's fetch must already
        be on disk before AMD's interruption propagates.
        """
        call_order = []

        def fake_fetch(self, ticker):
            call_order.append(ticker)
            if ticker == "AMD":
                raise KeyboardInterrupt()
            return _fake_fundamentals(ticker)

        with patch.object(ip.FundamentalClient, "get_all_fundamentals", fake_fetch):
            with patch.object(ip, "datetime") as mock_dt:
                mock_dt.now.side_effect = lambda tz=None: datetime(2026, 7, 20, 18, 0, tzinfo=tz)
                with pytest.raises(KeyboardInterrupt):
                    ip.fetch_fundamental_data(["NVDA", "AMD", "AVGO"])

        # NVDA completed before the interruption — must be readable from disk,
        # not lost, even though the overall refresh never finished.
        on_disk = json.loads(ip._FUNDAMENTAL_STATE_PATH.read_text())
        assert on_disk["tickers"]["NVDA"]["ticker"] == "NVDA"
        # AVGO was never reached — the loop stopped at AMD's interruption.
        assert "AVGO" not in call_order

    def test_interruption_leaves_last_updated_unset_so_retry_happens(self):
        """
        A partially-completed batch must still look "not refreshed today" —
        otherwise the next scan sees last_updated == today and skips
        re-fetching the tickers that never got fresh data.
        """
        def fake_fetch(self, ticker):
            if ticker == "AMD":
                raise KeyboardInterrupt()
            return _fake_fundamentals(ticker)

        with patch.object(ip.FundamentalClient, "get_all_fundamentals", fake_fetch):
            with patch.object(ip, "datetime") as mock_dt:
                mock_dt.now.side_effect = lambda tz=None: datetime(2026, 7, 20, 18, 0, tzinfo=tz)
                with pytest.raises(KeyboardInterrupt):
                    ip.fetch_fundamental_data(["NVDA", "AMD"])

        on_disk = json.loads(ip._FUNDAMENTAL_STATE_PATH.read_text())
        assert on_disk["last_updated"] is None

    def test_caught_exception_on_one_ticker_does_not_abort_the_rest(self):
        """A normal (non-interrupt) per-ticker failure is already handled —
        confirms the incremental-save change didn't regress this behavior."""
        def fake_fetch(self, ticker):
            if ticker == "AMD":
                raise ValueError("API error")
            return _fake_fundamentals(ticker)

        with patch.object(ip.FundamentalClient, "get_all_fundamentals", fake_fetch):
            with patch.object(ip, "datetime") as mock_dt:
                mock_dt.now.side_effect = lambda tz=None: datetime(2026, 7, 20, 18, 0, tzinfo=tz)
                result = ip.fetch_fundamental_data(["NVDA", "AMD", "AVGO"])

        assert result["tickers"]["NVDA"]["ticker"] == "NVDA"
        assert result["tickers"]["AMD"] is None  # failed ticker recorded as None, not skipped
        assert result["tickers"]["AVGO"]["ticker"] == "AVGO"  # loop continued past the failure
        assert result["last_updated"] is not None  # full loop finished, just with one failure
