"""
Tests for shared/api_clients/fundamental_client.py's get_estimate_revisions(),
get_earnings_surprises(), get_eps_growth_trend(), and get_all_fundamentals().

Covers three Alpha Vantage removals — this client no longer touches AV at all:
- get_estimate_revisions(): analyst target price now comes from yfinance and the
  rating breakdown from Finnhub's /stock/recommendation, instead of Alpha
  Vantage's OVERVIEW call.
- get_earnings_history() was split: earnings_surprises/consecutive_beats moved
  to Finnhub's /stock/earnings (free, same shape needed).
- get_eps_growth_trend() (the one figure needing 8-quarter depth neither
  Finnhub's nor yfinance's quarterly-statement free tiers provide) moved from
  Alpha Vantage EARNINGS to yfinance's get_earnings_dates() history, confirmed
  live to return 24 quarters of real reported EPS across every ticker type in
  the watchlist. Still gated by get_all_fundamentals's fetch_eps_growth_trend
  parameter, not fetched every time — that's now about avoiding redundant
  lookups for a figure that can't change mid-quarter, not budget.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from shared.api_clients.fundamental_client import FundamentalClient


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "fake-av-key")
    monkeypatch.setenv("FINNHUB_API_KEY", "fake-finnhub-key")
    # get_valuation_metrics / get_estimate_revisions now also reach the Finnhub
    # and Seeking Alpha data clients (2026-08 API audit) — the real
    # RAPIDAPI_KEY/FINNHUB_API_KEY are live in the session via .env, so stub
    # those cross-client calls to empty by default. Tests that exercise them
    # patch the specific function.
    from shared.api_clients import finnhub_client, seeking_alpha_client, sec_edgar_client
    monkeypatch.setattr(finnhub_client, "get_metric", lambda t: {})
    monkeypatch.setattr(seeking_alpha_client, "get_factor_grades", lambda t: {})
    # get_all_fundamentals now also tries SEC XBRL first for the earnings trend
    # — stub it off by default (the real data.sec.gov is reachable via .env-less
    # CIK map but the retry ladder on a slow response would hang the suite).
    monkeypatch.setattr(sec_edgar_client, "fetch_fundamental_trend", lambda t, sector=None: {})


def _mock_yf_info(target=250.0, current=200.0):
    mock_ticker = MagicMock()
    mock_ticker.info = {"targetMeanPrice": target, "regularMarketPrice": current}
    return mock_ticker


class TestEstimateRevisions:
    def test_target_price_and_upside_from_yfinance(self):
        client = FundamentalClient()
        with patch("shared.api_clients.fundamental_client.yf.Ticker", return_value=_mock_yf_info(250.0, 200.0)):
            with patch.object(client, "_with_backoff", return_value=None):
                result = client.get_estimate_revisions("NVDA")

        assert result["analyst_target_price"] == 250.0
        assert result["current_price"] == 200.0
        assert result["implied_upside_pct"] == 0.25

    def test_rating_breakdown_uses_most_recent_finnhub_period(self):
        client = FundamentalClient()
        finnhub_response = [
            {"period": "2026-07-01", "strongBuy": 24, "buy": 40, "hold": 4, "sell": 1, "strongSell": 0},
            {"period": "2026-06-01", "strongBuy": 20, "buy": 38, "hold": 5, "sell": 2, "strongSell": 0},
        ]
        with patch("shared.api_clients.fundamental_client.yf.Ticker", return_value=_mock_yf_info()):
            with patch.object(client, "_with_backoff", return_value=finnhub_response):
                result = client.get_estimate_revisions("NVDA")

        assert result["analyst_rating_breakdown"] == {
            "strongBuy": 24, "buy": 40, "hold": 4, "sell": 1, "strongSell": 0,
        }

    def test_no_alpha_vantage_call_made(self):
        """get_estimate_revisions must never touch Alpha Vantage — the only
        backoff-wrapped call in this method is the Finnhub one."""
        client = FundamentalClient()
        with patch("shared.api_clients.fundamental_client.yf.Ticker", return_value=_mock_yf_info()):
            with patch.object(client, "_with_backoff", return_value=None) as mock_backoff:
                client.get_estimate_revisions("NVDA")
        assert mock_backoff.call_count == 1
        assert mock_backoff.call_args[0][2] == "analyst_recommendation"

    def test_missing_finnhub_key_still_returns_target_price(self):
        client = FundamentalClient()
        client._finnhub_key = ""
        with patch("shared.api_clients.fundamental_client.yf.Ticker", return_value=_mock_yf_info(250.0, 200.0)):
            result = client.get_estimate_revisions("NVDA")

        assert result["analyst_target_price"] == 250.0
        assert result["analyst_rating_breakdown"] is None

    def test_yfinance_failure_does_not_crash_and_still_tries_finnhub(self):
        client = FundamentalClient()
        finnhub_response = [{"strongBuy": 10, "buy": 20, "hold": 2, "sell": 0, "strongSell": 0}]
        with patch("shared.api_clients.fundamental_client.yf.Ticker", side_effect=Exception("network error")):
            with patch.object(client, "_with_backoff", return_value=finnhub_response):
                result = client.get_estimate_revisions("NVDA")

        assert result["analyst_target_price"] is None
        assert result["analyst_rating_breakdown"]["strongBuy"] == 10


class TestEarningsSurprisesFromFinnhub:
    def test_computes_surprises_and_consecutive_beats(self):
        client = FundamentalClient()
        finnhub_response = [
            {"period": "2026-06-30", "actual": 1.87, "estimate": 1.79},
            {"period": "2026-03-31", "actual": 1.50, "estimate": 1.40},
            {"period": "2025-12-31", "actual": 1.20, "estimate": 1.30},  # miss
            {"period": "2025-09-30", "actual": 1.10, "estimate": 1.00},
        ]
        with patch.object(client, "_with_backoff", return_value=finnhub_response) as mock_backoff:
            result = client.get_earnings_surprises("NVDA")

        assert result["consecutive_beats"] == 2  # most recent 2 quarters beat, 3rd missed
        assert result["earnings_surprises"][0] == pytest.approx((1.87 - 1.79) / 1.79, abs=1e-4)
        assert mock_backoff.call_args[0][2] == "earnings_surprises"

    def test_never_touches_alpha_vantage_budget(self):
        """get_earnings_surprises must not spend AV budget — see
        TestEpsGrowthTrendFromYfinance.test_never_touches_alpha_vantage for the
        module-level guard confirming AV isn't imported anywhere in this file."""
        client = FundamentalClient()
        with patch.object(client, "_with_backoff", return_value=[]) as mock_backoff:
            client.get_earnings_surprises("NVDA")
        assert mock_backoff.call_args[0][2] == "earnings_surprises"

    def test_missing_finnhub_key_returns_none(self):
        client = FundamentalClient()
        client._finnhub_key = ""
        assert client.get_earnings_surprises("NVDA") is None


def _mock_earnings_dates_df(eps_values, end="2026-08-01"):
    """
    Build a DataFrame shaped like yf.Ticker(t).get_earnings_dates() — a
    "Reported EPS" column indexed by earnings date, most-recent-first (index 0
    is closest to `end`). `None` entries simulate a scheduled-but-not-yet-
    reported future quarter (yfinance leaves those NaN).
    """
    dates = pd.date_range(end=end, periods=len(eps_values), freq="90D")[::-1]
    return pd.DataFrame({"Reported EPS": eps_values}, index=dates)


class TestEpsGrowthTrendFromYfinance:
    """
    eps_growth_trend moved off Alpha Vantage's EARNINGS endpoint onto yfinance's
    get_earnings_dates() history (confirmed live: 24 quarters of real reported
    EPS for NVDA/AMZN/ZION/LLY/ASML/TSM — comfortably past the 8 needed).
    """

    def test_computes_yoy_growth_from_earnings_dates(self):
        client = FundamentalClient()
        # 8 quarters, most-recent-first: index i compares against index i+4 (YoY).
        eps_values = [2.0, 1.8, 1.6, 1.4, 1.0, 0.9, 0.8, 0.7]
        mock_ticker = MagicMock()
        mock_ticker.get_earnings_dates.return_value = _mock_earnings_dates_df(eps_values)
        with patch("shared.api_clients.fundamental_client.yf.Ticker", return_value=mock_ticker):
            result = client.get_eps_growth_trend("NVDA")

        assert result is not None
        assert len(result["eps_growth_trend"]) == 4
        assert result["eps_growth_trend"][0] == pytest.approx((2.0 - 1.0) / 1.0, abs=1e-4)
        assert "earnings_surprises" not in result  # that's Finnhub's job

    def test_drops_future_unreported_quarter_before_computing(self):
        client = FundamentalClient()
        eps_values = [None, 2.0, 1.8, 1.6, 1.4, 1.0, 0.9, 0.8, 0.7]
        mock_ticker = MagicMock()
        mock_ticker.get_earnings_dates.return_value = _mock_earnings_dates_df(eps_values)
        with patch("shared.api_clients.fundamental_client.yf.Ticker", return_value=mock_ticker):
            result = client.get_eps_growth_trend("NVDA")

        assert result["eps_growth_trend"][0] == pytest.approx((2.0 - 1.0) / 1.0, abs=1e-4)

    def test_missing_reported_eps_column_returns_none(self):
        client = FundamentalClient()
        mock_ticker = MagicMock()
        mock_ticker.get_earnings_dates.return_value = pd.DataFrame({"EPS Estimate": [1.0]})
        with patch("shared.api_clients.fundamental_client.yf.Ticker", return_value=mock_ticker):
            result = client.get_eps_growth_trend("NVDA")
        assert result is None

    def test_empty_history_returns_none(self):
        client = FundamentalClient()
        mock_ticker = MagicMock()
        mock_ticker.get_earnings_dates.return_value = pd.DataFrame()
        with patch("shared.api_clients.fundamental_client.yf.Ticker", return_value=mock_ticker):
            result = client.get_eps_growth_trend("NVDA")
        assert result is None

    def test_yfinance_failure_returns_none(self):
        client = FundamentalClient()
        with patch("shared.api_clients.fundamental_client.yf.Ticker", side_effect=Exception("network error")):
            result = client.get_eps_growth_trend("NVDA")
        assert result is None

    def test_never_touches_alpha_vantage(self):
        """Module-level regression guard for the migration: fundamental_client no
        longer imports or references anything Alpha Vantage related."""
        import shared.api_clients.fundamental_client as fc_module
        assert not hasattr(fc_module, "check_av_budget")
        assert not hasattr(fc_module, "increment_av_call_count")
        assert not hasattr(fc_module, "_AV_BASE_URL")


def _mock_quarterly_income_stmt(revenue_values, gross_profit_values=None, end="2026-06-30"):
    """
    Build a DataFrame shaped like yf.Ticker(t).quarterly_income_stmt — rows are
    line items ("Total Revenue", "Gross Profit"), columns are quarter-end dates,
    most-recent-first (matches real yfinance column ordering).
    """
    dates = pd.date_range(end=end, periods=len(revenue_values), freq="90D")[::-1]
    data = {"Total Revenue": revenue_values}
    if gross_profit_values is not None:
        data["Gross Profit"] = gross_profit_values
    return pd.DataFrame(data, index=dates).T


class TestRevenueAndMarginTrend:
    def test_computes_yoy_revenue_growth_and_margins(self):
        client = FundamentalClient()
        # 6 quarters, most-recent-first columns: index 0 vs index 4 = YoY.
        revenue = [7500.0, 7000.0, 6800.0, 6500.0, 6000.0, 5800.0]
        gross_profit = [4200.0, 3900.0, 3700.0, 3500.0, 3000.0, 2800.0]
        mock_ticker = MagicMock()
        mock_ticker.quarterly_income_stmt = _mock_quarterly_income_stmt(revenue, gross_profit)
        with patch("shared.api_clients.fundamental_client.yf.Ticker", return_value=mock_ticker):
            result = client.get_revenue_and_margin_trend("AMD")

        assert result is not None
        assert result["revenue_yoy_growth"] == pytest.approx((7500.0 - 6000.0) / 6000.0, abs=1e-4)
        assert result["gross_margin_latest"] == pytest.approx(4200.0 / 7500.0, abs=1e-4)
        assert result["gross_margin_prior"] == pytest.approx(3900.0 / 7000.0, abs=1e-4)

    def test_fewer_than_five_quarters_skips_yoy_growth_but_keeps_margins(self):
        client = FundamentalClient()
        revenue = [7500.0, 7000.0]
        gross_profit = [4200.0, 3900.0]
        mock_ticker = MagicMock()
        mock_ticker.quarterly_income_stmt = _mock_quarterly_income_stmt(revenue, gross_profit)
        with patch("shared.api_clients.fundamental_client.yf.Ticker", return_value=mock_ticker):
            result = client.get_revenue_and_margin_trend("AMD")

        assert result["revenue_yoy_growth"] is None
        assert result["gross_margin_latest"] == pytest.approx(4200.0 / 7500.0, abs=1e-4)

    def test_missing_gross_profit_row_leaves_margins_none(self):
        client = FundamentalClient()
        revenue = [7500.0, 7000.0, 6800.0, 6500.0, 6000.0]
        mock_ticker = MagicMock()
        mock_ticker.quarterly_income_stmt = _mock_quarterly_income_stmt(revenue)
        with patch("shared.api_clients.fundamental_client.yf.Ticker", return_value=mock_ticker):
            result = client.get_revenue_and_margin_trend("AMD")

        assert result["gross_margin_latest"] is None
        assert result["revenue_yoy_growth"] is not None

    def test_missing_total_revenue_row_returns_none(self):
        client = FundamentalClient()
        mock_ticker = MagicMock()
        mock_ticker.quarterly_income_stmt = pd.DataFrame({"Other Line": [1.0]}).T
        with patch("shared.api_clients.fundamental_client.yf.Ticker", return_value=mock_ticker):
            result = client.get_revenue_and_margin_trend("AMD")
        assert result is None

    def test_empty_statement_returns_none(self):
        client = FundamentalClient()
        mock_ticker = MagicMock()
        mock_ticker.quarterly_income_stmt = pd.DataFrame()
        with patch("shared.api_clients.fundamental_client.yf.Ticker", return_value=mock_ticker):
            result = client.get_revenue_and_margin_trend("AMD")
        assert result is None

    def test_yfinance_failure_returns_none(self):
        client = FundamentalClient()
        with patch("shared.api_clients.fundamental_client.yf.Ticker", side_effect=Exception("network error")):
            result = client.get_revenue_and_margin_trend("AMD")
        assert result is None


class TestGetAllFundamentalsGating:
    def test_fetch_eps_growth_trend_true_calls_both_sources(self):
        client = FundamentalClient()
        with patch("shared.api_clients.fundamental_client.yf.Ticker", return_value=_mock_yf_info()):
            with patch.object(client, "get_earnings_surprises", return_value={"earnings_surprises": [0.1], "consecutive_beats": 1}) as mock_surprises:
                with patch.object(client, "get_eps_growth_trend", return_value={"eps_growth_trend": [0.2]}) as mock_growth:
                    with patch.object(client, "get_estimate_revisions", return_value={}):
                        result = client.get_all_fundamentals("NVDA", fetch_eps_growth_trend=True)

        mock_surprises.assert_called_once()
        mock_growth.assert_called_once()
        assert result["earnings"]["eps_growth_trend"] == [0.2]
        assert result["earnings"]["earnings_surprises"] == [0.1]

    def test_fetch_eps_growth_trend_false_skips_alpha_vantage(self):
        client = FundamentalClient()
        with patch("shared.api_clients.fundamental_client.yf.Ticker", return_value=_mock_yf_info()):
            with patch.object(client, "get_earnings_surprises", return_value={"earnings_surprises": [0.1], "consecutive_beats": 1}):
                with patch.object(client, "get_eps_growth_trend") as mock_growth:
                    with patch.object(client, "get_estimate_revisions", return_value={}):
                        result = client.get_all_fundamentals("NVDA", fetch_eps_growth_trend=False)

        mock_growth.assert_not_called()
        assert "eps_growth_trend" not in result["earnings"]
        assert result["earnings"]["earnings_surprises"] == [0.1]  # Finnhub side still refreshes


class TestWithBackoff:
    """
    Direct coverage for FundamentalClient._with_backoff, previously only
    ever exercised through patch.object(client, "_with_backoff", ...) at
    every call site in this file — its own internals (retry-with-backoff
    now delegated to shared/api_clients/_http_backoff.py, secret redaction,
    the elapsed-time cap, and the validation_log.csv write on final
    failure) were never directly tested.
    """

    def test_successful_call_returns_result_directly(self):
        client = FundamentalClient()
        result = client._with_backoff(lambda: "ok", "NVDA", "test_label")
        assert result == "ok"

    def test_finnhub_key_redacted_from_validation_log_entry(self, monkeypatch):
        monkeypatch.setenv("FINNHUB_API_KEY", "fake-finnhub-key")
        client = FundamentalClient()
        monkeypatch.setattr("shared.api_clients._http_backoff.time.sleep", lambda s: None)

        def _always_fails():
            raise ConnectionError("Failed for https://finnhub.io/x?token=fake-finnhub-key")

        with patch("shared.api_clients.fundamental_client.write_validation_entry") as mock_write:
            result = client._with_backoff(_always_fails, "NVDA", "test_label")

        assert result is None
        mock_write.assert_called_once()
        args = mock_write.call_args[0]
        assert args[0] == "NVDA"
        assert args[1] == "fundamental_test_label_error"
        assert "fake-finnhub-key" not in args[2]
        assert "***REDACTED***" in args[2]

    def test_elapsed_cap_gives_up_early_and_still_writes_validation_entry(self, monkeypatch):
        # Default schedule (30, 60, 120) under the real 90s cap happens to
        # land exactly on the cap boundary (30+60=90, not > 90) — natural
        # 3-attempt exhaustion and the cap coincide, so that wouldn't
        # actually prove the cap fires *early*. Lowering the cap to 40s
        # here forces it to trigger after the first 30s sleep, before a
        # 3rd attempt would ever happen (2 calls to fn(), not 3).
        monkeypatch.setenv("FINNHUB_API_KEY", "fake-finnhub-key")
        monkeypatch.setattr("shared.api_clients.fundamental_client._MAX_TOTAL_BACKOFF_SECONDS", 40)
        client = FundamentalClient()
        sleeps = []
        monkeypatch.setattr("shared.api_clients._http_backoff.time.sleep", lambda s: sleeps.append(s))
        calls = {"n": 0}

        def _always_fails():
            calls["n"] += 1
            raise ConnectionError("down")

        with patch("shared.api_clients.fundamental_client.write_validation_entry") as mock_write:
            result = client._with_backoff(_always_fails, "NVDA", "test_label")

        assert result is None
        assert calls["n"] == 2  # first attempt, one retry after the 30s sleep, then capped out
        assert sleeps == [30]   # the 60s retry never happens — 30+60 would exceed the 40s cap
        mock_write.assert_called_once()


class TestSaAndFinnhubEnrichment:
    """2026-08 API audit: get_estimate_revisions also pulls the SA Quant Rating
    + 30d/90d rating-count direction; get_valuation_metrics falls back to
    Finnhub /stock/metric for fields yfinance's .info didn't supply."""

    def test_estimate_revisions_carries_sa_rating_direction(self, monkeypatch):
        from shared.api_clients import seeking_alpha_client
        monkeypatch.setattr(seeking_alpha_client, "get_factor_grades", lambda t: {
            "quant_rating": 4.1,
            "buy_count_30d": 25, "hold_count_30d": 3, "sell_count_30d": 1,
            "buy_count_90d": 15, "hold_count_90d": 8, "sell_count_90d": 4,
        })
        client = FundamentalClient()
        with patch("shared.api_clients.fundamental_client.yf.Ticker", return_value=_mock_yf_info()), \
             patch.object(client, "_with_backoff", return_value=[{"strongBuy": 5}]):
            out = client.get_estimate_revisions("NVDA")
        assert out["sa_quant_rating"] == 4.1
        assert out["sa_rating_revision"] == "up"   # 30d net (24/29) well above 90d net (11/27)

    def test_valuation_falls_back_to_finnhub_metric(self, monkeypatch):
        from shared.api_clients import finnhub_client
        monkeypatch.setattr(finnhub_client, "get_metric",
                            lambda t: {"peTTM": 33.9, "evToEbitdaTTM": 26.4, "evToRevenueTTM": 20.1})
        client = FundamentalClient()
        # yfinance .info supplies nothing
        bare = MagicMock()
        bare.info = {}
        with patch("shared.api_clients.fundamental_client.yf.Ticker", return_value=bare):
            out = client.get_valuation_metrics("NVDA")
        assert out["trailingPE"] == 33.9
        assert out["enterpriseToEbitda"] == 26.4

    def test_finnhub_fallback_not_used_when_yfinance_complete(self, monkeypatch):
        from shared.api_clients import finnhub_client
        called = []
        monkeypatch.setattr(finnhub_client, "get_metric", lambda t: called.append(1) or {})
        client = FundamentalClient()
        full = MagicMock()
        full.info = {"trailingPE": 30.0, "forwardPE": 24.0, "enterpriseToEbitda": 25.0}
        with patch("shared.api_clients.fundamental_client.yf.Ticker", return_value=full):
            client.get_valuation_metrics("NVDA")
        assert called == []


def test_rating_revision_from_counts_helper():
    from shared.api_clients.fundamental_client import _rating_revision_from_counts
    up = {"buy_count_30d": 20, "hold_count_30d": 2, "sell_count_30d": 0,
          "buy_count_90d": 10, "hold_count_90d": 8, "sell_count_90d": 4}
    assert _rating_revision_from_counts(up) == "up"
    assert _rating_revision_from_counts({}) is None


class TestGetAllFundamentalsSecFirst:
    """get_all_fundamentals tries SEC XBRL for the earnings trend before the
    yfinance scrapes (2026-08 API audit), falling back per-field."""

    def test_sec_trend_used_and_yfinance_not_called(self, monkeypatch):
        from shared.api_clients import sec_edgar_client
        monkeypatch.setattr(sec_edgar_client, "fetch_fundamental_trend",
                            lambda t, sector=None: {
                                "eps_growth_trend": [0.2, 0.15, 0.1, 0.05],
                                "revenue_yoy_growth": 0.3,
                                "gross_margin_latest": 0.64, "_source": "sec_xbrl",
                            })
        client = FundamentalClient()
        eps_called = []
        monkeypatch.setattr(client, "get_eps_growth_trend", lambda t: eps_called.append(1) or {})
        monkeypatch.setattr(client, "get_revenue_and_margin_trend", lambda t: eps_called.append(1) or {})
        monkeypatch.setattr(client, "get_earnings_surprises", lambda t: None)
        monkeypatch.setattr(client, "get_valuation_metrics", lambda t: {})
        monkeypatch.setattr(client, "get_estimate_revisions", lambda t: {})
        out = client.get_all_fundamentals("NVDA", fetch_eps_growth_trend=True, sector="semiconductors")
        assert out["earnings"]["eps_growth_trend"] == [0.2, 0.15, 0.1, 0.05]
        assert out["earnings"]["revenue_yoy_growth"] == 0.3
        assert out["earnings"]["_earnings_trend_source"] == "sec_xbrl"
        assert eps_called == []  # yfinance scrapes skipped

    def test_falls_back_to_yfinance_when_sec_empty(self, monkeypatch):
        from shared.api_clients import sec_edgar_client
        monkeypatch.setattr(sec_edgar_client, "fetch_fundamental_trend", lambda t, sector=None: {})
        client = FundamentalClient()
        monkeypatch.setattr(client, "get_eps_growth_trend", lambda t: {"eps_growth_trend": [0.1]})
        monkeypatch.setattr(client, "get_revenue_and_margin_trend", lambda t: {"revenue_yoy_growth": 0.05})
        monkeypatch.setattr(client, "get_earnings_surprises", lambda t: None)
        monkeypatch.setattr(client, "get_valuation_metrics", lambda t: {})
        monkeypatch.setattr(client, "get_estimate_revisions", lambda t: {})
        out = client.get_all_fundamentals("TSM", fetch_eps_growth_trend=True, sector="semiconductors")
        assert out["earnings"]["eps_growth_trend"] == [0.1]
        assert out["earnings"]["revenue_yoy_growth"] == 0.05
        assert "_earnings_trend_source" not in out["earnings"]
