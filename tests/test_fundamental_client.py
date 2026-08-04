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
