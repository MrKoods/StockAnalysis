"""
Tests for shared/api_clients/fundamental_client.py's get_estimate_revisions(),
get_earnings_surprises(), get_eps_growth_trend(), and get_all_fundamentals().

Covers two AV-budget reductions:
- get_estimate_revisions(): analyst target price now comes from yfinance and the
  rating breakdown from Finnhub's /stock/recommendation, instead of Alpha
  Vantage's OVERVIEW call.
- get_earnings_history() was split: earnings_surprises/consecutive_beats moved
  to Finnhub's /stock/earnings (free, same shape needed), leaving Alpha Vantage
  responsible only for eps_growth_trend (the one figure needing 8-quarter depth
  neither free-tier source provides) — and even that call is now gated by
  get_all_fundamentals's fetch_eps_growth_trend parameter, not fetched every time.
"""

from unittest.mock import MagicMock, patch

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
        """The whole point of this change: get_estimate_revisions must never touch
        Alpha Vantage — check_av_budget/increment_av_call_count should not fire."""
        client = FundamentalClient()
        with patch("shared.api_clients.fundamental_client.yf.Ticker", return_value=_mock_yf_info()):
            with patch.object(client, "_with_backoff", return_value=None) as mock_backoff:
                with patch("shared.api_clients.fundamental_client.check_av_budget") as mock_budget:
                    client.get_estimate_revisions("NVDA")
                    mock_budget.assert_not_called()
        # The only backoff-wrapped call in this method must be the Finnhub one.
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
        """The whole point of this move: get_earnings_surprises must not spend AV budget."""
        client = FundamentalClient()
        with patch.object(client, "_with_backoff", return_value=[]):
            with patch("shared.api_clients.fundamental_client.check_av_budget") as mock_budget:
                with patch("shared.api_clients.fundamental_client.increment_av_call_count") as mock_incr:
                    client.get_earnings_surprises("NVDA")
        mock_budget.assert_not_called()
        mock_incr.assert_not_called()

    def test_missing_finnhub_key_returns_none(self):
        client = FundamentalClient()
        client._finnhub_key = ""
        assert client.get_earnings_surprises("NVDA") is None


class TestEpsGrowthTrendFromAlphaVantage:
    def test_still_calls_alpha_vantage_and_spends_budget(self):
        """Regression guard: eps_growth_trend must stay on Alpha Vantage — 8-quarter
        YoY depth that Finnhub/yfinance free tiers can't match."""
        client = FundamentalClient()
        fake_av_data = {
            "quarterlyEarnings": [
                {"reportedEPS": "1.0", "estimatedEPS": "0.9"} for _ in range(8)
            ]
        }
        with patch.object(client, "_with_backoff", return_value=fake_av_data) as mock_backoff:
            with patch("shared.api_clients.fundamental_client.check_av_budget", return_value=True):
                with patch("shared.api_clients.fundamental_client.increment_av_call_count") as mock_incr:
                    result = client.get_eps_growth_trend("NVDA")

        assert result is not None
        assert "eps_growth_trend" in result
        assert "earnings_surprises" not in result  # that's Finnhub's job now
        mock_incr.assert_called_once()
        assert mock_backoff.call_args[0][2] == "eps_growth_trend"

    def test_budget_exhausted_returns_none_without_calling_av(self):
        client = FundamentalClient()
        with patch("shared.api_clients.fundamental_client.check_av_budget", return_value=False):
            with patch.object(client, "_with_backoff") as mock_backoff:
                result = client.get_eps_growth_trend("NVDA")
        assert result is None
        mock_backoff.assert_not_called()


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
