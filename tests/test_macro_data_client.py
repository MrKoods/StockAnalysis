"""Tests for shared/api_clients/macro_data_client.py — AV economic series feeding macro_overlay (MR-4)."""

from unittest.mock import patch

import pandas as pd
import pytest

import shared.api_clients.macro_data_client as md


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "K")


def test_treasury_yield_parses_to_ordered_series():
    payload = {"name": "10-Year Treasury", "interval": "daily", "unit": "percent", "data": [
        {"date": "2026-08-25", "value": "4.64"},
        {"date": "2026-08-24", "value": "4.70"},
        {"date": "2026-08-21", "value": "4.74"},
    ]}
    with patch("shared.api_clients.macro_data_client.http_get_with_backoff", return_value=payload):
        s = md.fetch_treasury_yield_10y()
    assert isinstance(s, pd.Series)
    assert list(s.index) == [pd.Timestamp("2026-08-21"), pd.Timestamp("2026-08-24"), pd.Timestamp("2026-08-25")]
    assert s.iloc[-1] == 4.64


def test_usd_strength_parses_fx_daily():
    payload = {"Meta Data": {}, "Time Series FX (Daily)": {
        "2026-08-27": {"1. open": "0.86", "4. close": "0.862"},
        "2026-08-26": {"1. open": "0.858", "4. close": "0.859"},
    }}
    with patch("shared.api_clients.macro_data_client.http_get_with_backoff", return_value=payload):
        s = md.fetch_usd_strength()
    assert s.iloc[-1] == 0.862 and s.index[-1] == pd.Timestamp("2026-08-27")


def test_throttle_returns_none():
    with patch("shared.api_clients.macro_data_client.http_get_with_backoff",
               return_value={"Information": "slow down"}):
        assert md.fetch_treasury_yield_10y() is None


def test_missing_key_returns_none(monkeypatch):
    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)
    assert md.fetch_treasury_yield_10y() is None


def test_fed_funds_and_cpi_parse():
    ff = {"data": [{"date": "2026-07-01", "value": "3.63"}, {"date": "2026-06-01", "value": "3.63"}]}
    with patch("shared.api_clients.macro_data_client.http_get_with_backoff", return_value=ff):
        s = md.fetch_federal_funds_rate()
    assert s.iloc[-1] == 3.63

    cpi = {"data": [{"date": "2026-07-01", "value": "320.1"}, {"date": "2026-06-01", "value": "319.0"}]}
    with patch("shared.api_clients.macro_data_client.http_get_with_backoff", return_value=cpi):
        s = md.fetch_cpi()
    assert s.iloc[-1] == 320.1


def test_series_survives_the_cache_round_trip():
    """Regression: the cached payload was keyed by pd.Timestamp, which
    json.dumps rejects — the cache write failed silently and every scan
    re-fetched the series. It must now be ISO-string-keyed and cache."""
    payload = {"data": [
        {"date": "2026-08-25", "value": "4.64"},
        {"date": "2026-08-24", "value": "4.70"},
    ]}
    with patch("shared.api_clients.macro_data_client.http_get_with_backoff", return_value=payload) as http:
        first = md.fetch_treasury_yield_10y()
        second = md.fetch_treasury_yield_10y()
    assert http.call_count == 1  # second call served from cache, no re-fetch
    assert isinstance(second, pd.Series)
    assert second.equals(first)
    assert second.index[-1] == pd.Timestamp("2026-08-25") and second.iloc[-1] == 4.64


def test_budget_exhausted_returns_none(monkeypatch):
    monkeypatch.setattr(md.rate_limiter, "acquire",
                        lambda *a, **k: (_ for _ in ()).throw(md.rate_limiter.BudgetExhausted("cap")))
    assert md.fetch_usd_strength() is None
