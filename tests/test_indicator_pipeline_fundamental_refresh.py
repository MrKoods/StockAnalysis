"""
Tests for swing_model/indicator_pipeline.py's fetch_fundamental_data().

Covers the staggered per-ticker refresh cadence (cold-start bootstrap, earnings-
date priority, weekday rotation, daily fetch cap) and the incremental-save
behavior that protects against a mid-batch interruption discarding already-
fetched tickers.
"""

import contextlib
import json
from datetime import datetime
from unittest.mock import patch

import pytest

import swing_model.indicator_pipeline as ip


@pytest.fixture(autouse=True)
def _isolate_state_file(tmp_path, monkeypatch):
    monkeypatch.setattr(ip, "_FUNDAMENTAL_STATE_PATH", tmp_path / "fundamental_state.json")
    monkeypatch.setattr(ip, "_FUNDAMENTAL_HISTORY_DIR", tmp_path / "fundamental_history")
    # No ticker has a known earnings date unless a test says otherwise —
    # keeps rotation/bootstrap behavior deterministic and free of network calls.
    monkeypatch.setattr(ip, "_get_upcoming_earnings_date", lambda ticker: None)


def _fake_fundamentals(ticker):
    return {"ticker": ticker, "valuation": {}, "earnings": {}, "revisions": {}}


@contextlib.contextmanager
def _frozen_now(dt):
    """Patch ip.datetime.now so _ET-aware calls resolve to a fixed instant, while
    leaving .strptime (used by _days_since) pointed at the real implementation —
    fully replacing the module's `datetime` name breaks any other datetime.* call."""
    with patch.object(ip, "datetime") as mock_dt:
        mock_dt.now.side_effect = lambda tz=None: dt.replace(tzinfo=tz) if tz else dt
        mock_dt.strptime = datetime.strptime  # this module's own name, unaffected by the ip.datetime patch
        yield


class TestBootstrap:
    def test_never_fetched_tickers_are_bootstrapped_immediately(self):
        # 2026-07-20 is a Monday; bootstrap shouldn't care what day it is.
        with patch.object(ip.FundamentalClient, "get_all_fundamentals", side_effect=_fake_fundamentals):
            with _frozen_now(datetime(2026, 7, 20, 9, 0)):
                result = ip.fetch_fundamental_data(["NVDA", "AMD"])

        assert result["tickers"]["NVDA"]["ticker"] == "NVDA"
        assert result["tickers"]["AMD"]["ticker"] == "AMD"
        assert result["fetched_dates"]["NVDA"] == "2026-07-20"
        assert result["fetched_dates"]["AMD"] == "2026-07-20"

    def test_daily_cap_limits_how_many_bootstrap_in_one_call(self):
        tickers = ["NVDA", "AMD", "AVGO", "TSM", "MU"]  # 5 candidates, cap is 3
        with patch.object(ip.FundamentalClient, "get_all_fundamentals", side_effect=_fake_fundamentals):
            with _frozen_now(datetime(2026, 7, 20, 9, 0)):
                result = ip.fetch_fundamental_data(tickers)

        fetched_today = [t for t in tickers if result["fetched_dates"].get(t) == "2026-07-20"]
        assert len(fetched_today) == ip._FUNDAMENTAL_MAX_TICKERS_PER_DAY

    def test_daily_cap_holds_across_multiple_calls_same_day(self):
        """
        The real incident this guards against: fetch_fundamental_data runs once
        per scan (pre-market, mid-session, post-close) per sector, all sharing one
        state file. A cap enforced only within a single call resets every time —
        3 candidates left over from call 1 plus 3 more capacity in call 2 fetched
        6 tickers in one day in production, double the intended daily ceiling.
        """
        semis = ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"]  # 6 candidates
        banks = ["ZION", "KEY", "HBAN", "RF", "FITB"]  # 5 candidates
        with patch.object(ip.FundamentalClient, "get_all_fundamentals", side_effect=_fake_fundamentals):
            with _frozen_now(datetime(2026, 7, 20, 5, 30)):
                ip.fetch_fundamental_data(semis)  # pre-market, sector call 1
                ip.fetch_fundamental_data(banks)  # pre-market, sector call 2
                result = ip.fetch_fundamental_data(semis)  # mid-session, sector call 1 again

        fetched_today = [
            t for t in semis + banks if result["fetched_dates"].get(t) == "2026-07-20"
        ]
        assert len(fetched_today) == ip._FUNDAMENTAL_MAX_TICKERS_PER_DAY

    def test_leftover_bootstrap_candidates_fetch_on_a_later_call(self):
        tickers = ["NVDA", "AMD", "AVGO", "TSM", "MU"]
        with patch.object(ip.FundamentalClient, "get_all_fundamentals", side_effect=_fake_fundamentals):
            with _frozen_now(datetime(2026, 7, 20, 9, 0)):
                ip.fetch_fundamental_data(tickers)  # first 3 fetched
            # Next day: the still-unfetched tickers should get picked up.
            with _frozen_now(datetime(2026, 7, 21, 9, 0)):
                result = ip.fetch_fundamental_data(tickers)

        assert all(result["tickers"].get(t) is not None for t in tickers)


class TestRotationAndEarningsPriority:
    def test_ticker_not_on_its_rotation_day_and_not_stale_is_skipped(self):
        ticker = "NVDA"
        with patch.object(ip, "_rotation_weekday", return_value=0):  # Monday
            with patch.object(ip.FundamentalClient, "get_all_fundamentals", side_effect=_fake_fundamentals):
                with _frozen_now(datetime(2026, 7, 20, 9, 0)):  # Monday: bootstrap-fetches it
                    ip.fetch_fundamental_data([ticker])
                # Tuesday, one day later: not its rotation day, not stale (>=7d) yet.
                with _frozen_now(datetime(2026, 7, 21, 9, 0)):
                    result = ip.fetch_fundamental_data([ticker])

        assert result["fetched_dates"][ticker] == "2026-07-20"  # unchanged

    def test_ticker_refreshes_on_its_rotation_day_once_stale(self):
        ticker = "NVDA"
        with patch.object(ip, "_rotation_weekday", return_value=0):  # Monday
            with patch.object(ip.FundamentalClient, "get_all_fundamentals", side_effect=_fake_fundamentals):
                with _frozen_now(datetime(2026, 7, 20, 9, 0)):
                    ip.fetch_fundamental_data([ticker])
                # Following Monday: rotation day AND >= 7 days stale.
                with _frozen_now(datetime(2026, 7, 27, 9, 0)):
                    result = ip.fetch_fundamental_data([ticker])

        assert result["fetched_dates"][ticker] == "2026-07-27"

    def test_upcoming_earnings_forces_refresh_off_rotation_day(self):
        ticker = "NVDA"
        with patch.object(ip, "_rotation_weekday", return_value=0):  # Monday
            with patch.object(ip.FundamentalClient, "get_all_fundamentals", side_effect=_fake_fundamentals):
                with _frozen_now(datetime(2026, 7, 20, 9, 0)):
                    ip.fetch_fundamental_data([ticker])  # bootstrap
                # Wednesday (not its rotation day), but earnings are tomorrow.
                from datetime import date
                with patch.object(ip, "_get_upcoming_earnings_date", return_value=date(2026, 7, 23)):
                    with _frozen_now(datetime(2026, 7, 22, 9, 0)):
                        result = ip.fetch_fundamental_data([ticker])

        assert result["fetched_dates"][ticker] == "2026-07-22"

    def test_already_fetched_today_is_not_refetched(self):
        ticker = "NVDA"
        calls = []

        def counting_fetch(self, t):
            calls.append(t)
            return _fake_fundamentals(t)

        with patch.object(ip.FundamentalClient, "get_all_fundamentals", counting_fetch):
            with _frozen_now(datetime(2026, 7, 20, 9, 0)):
                ip.fetch_fundamental_data([ticker])
                ip.fetch_fundamental_data([ticker])  # same day, second scan

        assert calls == [ticker]


class TestIncrementalSave:
    def test_interruption_mid_batch_preserves_already_fetched_tickers(self):
        """
        A mid-batch interruption (KeyboardInterrupt) must not discard tickers
        that already completed — NVDA's fetch must already be on disk before
        AMD's interruption propagates.
        """
        call_order = []

        def fake_fetch(self, ticker):
            call_order.append(ticker)
            if ticker == "AMD":
                raise KeyboardInterrupt()
            return _fake_fundamentals(ticker)

        with patch.object(ip.FundamentalClient, "get_all_fundamentals", fake_fetch):
            with _frozen_now(datetime(2026, 7, 20, 9, 0)):
                with pytest.raises(KeyboardInterrupt):
                    ip.fetch_fundamental_data(["NVDA", "AMD", "AVGO"])

        on_disk = json.loads(ip._FUNDAMENTAL_STATE_PATH.read_text())
        assert on_disk["tickers"]["NVDA"]["ticker"] == "NVDA"
        # The daily cap (3) means all three were candidates, but AMD's
        # interruption stopped the loop before AVGO ran.
        assert "AVGO" not in call_order

    def test_interruption_leaves_ticker_unfetched_so_retry_happens(self):
        def fake_fetch(self, ticker):
            if ticker == "AMD":
                raise KeyboardInterrupt()
            return _fake_fundamentals(ticker)

        with patch.object(ip.FundamentalClient, "get_all_fundamentals", fake_fetch):
            with _frozen_now(datetime(2026, 7, 20, 9, 0)):
                with pytest.raises(KeyboardInterrupt):
                    ip.fetch_fundamental_data(["NVDA", "AMD"])

        on_disk = json.loads(ip._FUNDAMENTAL_STATE_PATH.read_text())
        assert "AMD" not in on_disk["fetched_dates"]

    def test_caught_exception_on_one_ticker_does_not_abort_the_rest(self):
        def fake_fetch(self, ticker):
            if ticker == "AMD":
                raise ValueError("API error")
            return _fake_fundamentals(ticker)

        with patch.object(ip.FundamentalClient, "get_all_fundamentals", fake_fetch):
            with _frozen_now(datetime(2026, 7, 20, 9, 0)):
                result = ip.fetch_fundamental_data(["NVDA", "AMD", "AVGO"])

        assert result["tickers"]["NVDA"]["ticker"] == "NVDA"
        assert result["tickers"]["AMD"] is None  # failed ticker recorded as None, not skipped
        assert result["tickers"]["AVGO"]["ticker"] == "AVGO"  # loop continued past the failure
        # AMD's fetched_dates is deliberately left unset on failure (same as the
        # interruption case) so a subsequent scan today still treats it as due,
        # rather than silently waiting for its next rotation day.
        assert "AMD" not in result["fetched_dates"]
