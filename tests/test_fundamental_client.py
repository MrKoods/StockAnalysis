"""
Tests for shared/api_clients/fundamental_client.py's get_estimate_revisions().

Covers the hybrid AV-budget reduction: analyst target price now comes from
yfinance and the rating breakdown from Finnhub's /stock/recommendation, instead
of Alpha Vantage's OVERVIEW call — get_earnings_history() still uses Alpha
Vantage (kept deliberately, see its module docstring), so this also guards
against that call accidentally being touched by this change.
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


class TestEarningsHistoryUnaffected:
    def test_earnings_history_still_calls_alpha_vantage(self):
        """Regression guard: this hybrid change must not touch get_earnings_history
        at all — it stays on Alpha Vantage deliberately (8-quarter YoY depth that
        Finnhub/yfinance free tiers can't match)."""
        client = FundamentalClient()
        fake_av_data = {
            "quarterlyEarnings": [
                {"reportedEPS": "1.0", "estimatedEPS": "0.9"} for _ in range(8)
            ]
        }
        with patch.object(client, "_with_backoff", return_value=fake_av_data) as mock_backoff:
            with patch("shared.api_clients.fundamental_client.check_av_budget", return_value=True):
                with patch("shared.api_clients.fundamental_client.increment_av_call_count") as mock_incr:
                    result = client.get_earnings_history("NVDA")

        assert result is not None
        mock_incr.assert_called_once()
        assert mock_backoff.call_args[0][2] == "earnings_history"
