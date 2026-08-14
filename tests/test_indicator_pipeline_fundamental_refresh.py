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
    # Same for the "did it actually report since last fetch" check — no
    # ticker has reported unless a test says otherwise.
    monkeypatch.setattr(ip, "_get_last_reported_earnings_date", lambda ticker: None)


def _fake_fundamentals(ticker, fetch_eps_growth_trend=True):
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

    def test_daily_cap_limits_how_many_bootstrap_in_one_call(self, monkeypatch):
        monkeypatch.setattr(ip, "_FUNDAMENTAL_MAX_TICKERS_PER_DAY", 3)
        tickers = ["NVDA", "AMD", "AVGO", "TSM", "MU"]  # 5 candidates, cap is 3
        with patch.object(ip.FundamentalClient, "get_all_fundamentals", side_effect=_fake_fundamentals):
            with _frozen_now(datetime(2026, 7, 20, 9, 0)):
                result = ip.fetch_fundamental_data(tickers)

        fetched_today = [t for t in tickers if result["fetched_dates"].get(t) == "2026-07-20"]
        assert len(fetched_today) == ip._FUNDAMENTAL_MAX_TICKERS_PER_DAY

    def test_daily_cap_holds_across_multiple_calls_same_day(self, monkeypatch):
        """
        The real incident this guards against: fetch_fundamental_data runs once
        per scan (pre-market, mid-session, post-close) per sector, all sharing one
        state file. A cap enforced only within a single call resets every time —
        3 candidates left over from call 1 plus 3 more capacity in call 2 fetched
        6 tickers in one day in production, double the intended daily ceiling.
        """
        monkeypatch.setattr(ip, "_FUNDAMENTAL_MAX_TICKERS_PER_DAY", 8)
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

    def test_report_since_last_fetch_forces_refresh_even_when_calendar_already_rolled_forward(self):
        """
        The real bug this guards against: once a company reports, yfinance's
        "next earnings date" calendar flips forward to the FOLLOWING quarter
        almost immediately (confirmed live for AMD — calendar showed Nov 3
        the same week it reported Aug 4), so the near-next-earnings check
        alone can't catch a report that already happened. This must catch it
        via the ticker's actual last-reported date instead.
        """
        ticker = "NVDA"
        from datetime import date
        with patch.object(ip, "_rotation_weekday", return_value=0):  # Monday, not today
            with patch.object(ip.FundamentalClient, "get_all_fundamentals", side_effect=_fake_fundamentals):
                with _frozen_now(datetime(2026, 7, 20, 9, 0)):
                    ip.fetch_fundamental_data([ticker])  # bootstrap
                # Wednesday: not rotation day, not stale, and "next earnings" is
                # 3 months out (already rolled forward) — but it actually
                # reported 2 days ago, after the bootstrap fetch.
                with patch.object(ip, "_get_upcoming_earnings_date", return_value=date(2026, 10, 20)):
                    with patch.object(ip, "_get_last_reported_earnings_date", return_value=date(2026, 7, 22)):
                        with _frozen_now(datetime(2026, 7, 24, 9, 0)):
                            result = ip.fetch_fundamental_data([ticker])

        assert result["fetched_dates"][ticker] == "2026-07-24"

    def test_rotation_only_touch_does_not_mask_a_missed_report(self):
        """
        The exact real-world bug (AMD, 2026-08): bootstrap pulls growth data,
        then a later PLAIN ROTATION refresh (fetch_growth=False) touches
        fetched_dates without re-pulling growth. If the missed-report check
        compared against fetched_dates (the general "was this ticker touched
        at all" date) instead of growth_fetched_dates (the "was growth data
        actually pulled" date), a report landing between the two would be
        permanently masked — fetched_dates would already be newer than the
        report, so the check would never fire, right up until ~3 months later
        when the NEXT earnings date's pre-earnings window opens.
        """
        ticker = "NVDA"
        from datetime import date
        with patch.object(ip, "_rotation_weekday", return_value=0):  # Monday
            with patch.object(ip.FundamentalClient, "get_all_fundamentals", side_effect=_fake_fundamentals):
                with _frozen_now(datetime(2026, 7, 6, 9, 0)):  # Monday: bootstrap, growth pulled
                    ip.fetch_fundamental_data([ticker])
                # Following Monday: rotation-only refresh (>=7d stale) — touches
                # fetched_dates but does NOT re-pull growth (fetch_growth=False).
                with _frozen_now(datetime(2026, 7, 13, 9, 0)):
                    ip.fetch_fundamental_data([ticker])

        # A report landed the day after bootstrap — after growth_fetched_dates
        # (2026-07-06) but before the rotation-only touch (2026-07-13).
        with patch.object(ip, "_rotation_weekday", return_value=0):
            with patch.object(ip.FundamentalClient, "get_all_fundamentals", side_effect=_fake_fundamentals):
                with patch.object(ip, "_get_upcoming_earnings_date", return_value=date(2026, 10, 15)):
                    with patch.object(ip, "_get_last_reported_earnings_date", return_value=date(2026, 7, 7)):
                        # Tuesday: not rotation day, not stale — only the
                        # missed-report check can force this refresh.
                        with _frozen_now(datetime(2026, 7, 14, 9, 0)):
                            result = ip.fetch_fundamental_data([ticker])

        assert result["fetched_dates"][ticker] == "2026-07-14"
        assert result["growth_fetched_dates"][ticker] == "2026-07-14"

    def test_report_before_last_fetch_does_not_force_refresh(self):
        """A last-reported date that's OLDER than (or equal to) the last fetch
        must not force a refresh — only a report that happened SINCE."""
        ticker = "NVDA"
        from datetime import date
        with patch.object(ip, "_rotation_weekday", return_value=0):  # Monday, not today
            with patch.object(ip.FundamentalClient, "get_all_fundamentals", side_effect=_fake_fundamentals):
                with _frozen_now(datetime(2026, 7, 20, 9, 0)):
                    ip.fetch_fundamental_data([ticker])  # bootstrap, last_fetch = 2026-07-20
                with patch.object(ip, "_get_upcoming_earnings_date", return_value=date(2026, 10, 20)):
                    with patch.object(ip, "_get_last_reported_earnings_date", return_value=date(2026, 7, 18)):
                        with _frozen_now(datetime(2026, 7, 21, 9, 0)):
                            result = ip.fetch_fundamental_data([ticker])

        assert result["fetched_dates"][ticker] == "2026-07-20"  # unchanged, not refreshed

    def test_already_fetched_today_is_not_refetched(self):
        ticker = "NVDA"
        calls = []

        def counting_fetch(self, t, fetch_eps_growth_trend=True):
            calls.append(t)
            return _fake_fundamentals(t)

        with patch.object(ip.FundamentalClient, "get_all_fundamentals", counting_fetch):
            with _frozen_now(datetime(2026, 7, 20, 9, 0)):
                ip.fetch_fundamental_data([ticker])
                ip.fetch_fundamental_data([ticker])  # same day, second scan

        assert calls == [ticker]


class TestEpsGrowthTrendGating:
    def test_bootstrap_and_earnings_priority_request_growth_trend(self):
        calls = {}

        def recording_fetch(ticker, fetch_eps_growth_trend=True):
            calls[ticker] = fetch_eps_growth_trend
            return _fake_fundamentals(ticker)

        with patch.object(ip.FundamentalClient, "get_all_fundamentals", side_effect=recording_fetch):
            with _frozen_now(datetime(2026, 7, 20, 9, 0)):
                ip.fetch_fundamental_data(["NVDA"])  # bootstrap — never fetched before

        assert calls["NVDA"] is True

    def test_plain_rotation_refresh_does_not_request_growth_trend(self):
        calls = {}

        def recording_fetch(ticker, fetch_eps_growth_trend=True):
            calls[ticker] = fetch_eps_growth_trend
            return _fake_fundamentals(ticker)

        with patch.object(ip, "_rotation_weekday", return_value=0):  # Monday
            with patch.object(ip.FundamentalClient, "get_all_fundamentals", side_effect=recording_fetch):
                with _frozen_now(datetime(2026, 7, 20, 9, 0)):
                    ip.fetch_fundamental_data(["NVDA"])  # bootstrap fetch, growth trend=True
                with _frozen_now(datetime(2026, 7, 27, 9, 0)):  # following Monday, stale rotation
                    ip.fetch_fundamental_data(["NVDA"])

        assert calls["NVDA"] is False  # the rotation-only refresh

    def test_old_eps_growth_trend_carried_forward_when_not_refetched(self):
        def fetch_with_growth(ticker, fetch_eps_growth_trend=True):
            earnings = {"earnings_surprises": [0.1], "consecutive_beats": 1}
            if fetch_eps_growth_trend:
                earnings["eps_growth_trend"] = [0.42]
            return {"ticker": ticker, "valuation": {}, "earnings": earnings, "revisions": {}}

        with patch.object(ip, "_rotation_weekday", return_value=0):  # Monday
            with patch.object(ip.FundamentalClient, "get_all_fundamentals", side_effect=fetch_with_growth):
                with _frozen_now(datetime(2026, 7, 20, 9, 0)):
                    ip.fetch_fundamental_data(["NVDA"])  # bootstrap: gets real eps_growth_trend
                with _frozen_now(datetime(2026, 7, 27, 9, 0)):  # rotation-only refresh
                    result = ip.fetch_fundamental_data(["NVDA"])

        # The rotation refresh didn't request growth trend, but the old value
        # should still be present — carried forward, not wiped to missing/None.
        assert result["tickers"]["NVDA"]["earnings"]["eps_growth_trend"] == [0.42]
        # The Finnhub-sourced field still reflects the newer refresh.
        assert result["tickers"]["NVDA"]["earnings"]["earnings_surprises"] == [0.1]

    def test_old_revenue_and_margin_carried_forward_when_not_refetched(self):
        """revenue_yoy_growth/gross_margin_* are gated by the same fetch_growth
        flag as eps_growth_trend (same quarterly filing) — must carry forward
        the same way on a plain rotation refresh."""
        def fetch_with_revenue(ticker, fetch_eps_growth_trend=True):
            earnings = {"earnings_surprises": [0.1], "consecutive_beats": 1}
            if fetch_eps_growth_trend:
                earnings["eps_growth_trend"] = [0.42]
                earnings["revenue_yoy_growth"] = 0.12
                earnings["gross_margin_latest"] = 0.55
                earnings["gross_margin_prior"] = 0.53
            return {"ticker": ticker, "valuation": {}, "earnings": earnings, "revisions": {}}

        with patch.object(ip, "_rotation_weekday", return_value=0):  # Monday
            with patch.object(ip.FundamentalClient, "get_all_fundamentals", side_effect=fetch_with_revenue):
                with _frozen_now(datetime(2026, 7, 20, 9, 0)):
                    ip.fetch_fundamental_data(["NVDA"])  # bootstrap
                with _frozen_now(datetime(2026, 7, 27, 9, 0)):  # rotation-only refresh
                    result = ip.fetch_fundamental_data(["NVDA"])

        earnings = result["tickers"]["NVDA"]["earnings"]
        assert earnings["revenue_yoy_growth"] == 0.12
        assert earnings["gross_margin_latest"] == 0.55
        assert earnings["gross_margin_prior"] == 0.53


class TestPriorTargetPriceCarryForward:
    def test_prior_target_price_stashed_before_overwrite(self):
        def fetch_with_target(ticker, fetch_eps_growth_trend=True, _call={"n": 0}):
            _call["n"] += 1
            target = 250.0 if _call["n"] == 1 else 275.0
            return {
                "ticker": ticker, "valuation": {}, "earnings": {},
                "revisions": {"analyst_target_price": target, "current_price": 200.0},
            }

        with patch.object(ip, "_rotation_weekday", return_value=0):  # Monday
            with patch.object(ip.FundamentalClient, "get_all_fundamentals", side_effect=fetch_with_target):
                with _frozen_now(datetime(2026, 7, 20, 9, 0)):
                    ip.fetch_fundamental_data(["NVDA"])  # bootstrap: target=250.0
                with _frozen_now(datetime(2026, 7, 27, 9, 0)):  # rotation refresh: target=275.0
                    result = ip.fetch_fundamental_data(["NVDA"])

        revisions = result["tickers"]["NVDA"]["revisions"]
        assert revisions["analyst_target_price"] == 275.0
        assert revisions["prior_analyst_target_price"] == 250.0
        assert revisions["prior_target_as_of"] == "2026-07-20"

    def test_no_prior_target_on_first_ever_fetch(self):
        with patch.object(ip.FundamentalClient, "get_all_fundamentals", side_effect=_fake_fundamentals):
            with _frozen_now(datetime(2026, 7, 20, 9, 0)):
                result = ip.fetch_fundamental_data(["NVDA"])

        assert "prior_analyst_target_price" not in result["tickers"]["NVDA"]["revisions"]


class TestIncrementalSave:
    def test_interruption_mid_batch_preserves_already_fetched_tickers(self):
        """
        A mid-batch interruption (KeyboardInterrupt) must not discard tickers
        that already completed — NVDA's fetch must already be on disk before
        AMD's interruption propagates.
        """
        call_order = []

        def fake_fetch(self, ticker, fetch_eps_growth_trend=True):
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
        def fake_fetch(self, ticker, fetch_eps_growth_trend=True):
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
        def fake_fetch(self, ticker, fetch_eps_growth_trend=True):
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
