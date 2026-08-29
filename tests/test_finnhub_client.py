"""Tests for shared/api_clients/finnhub_client.py — Finnhub endpoints for the phase-2 layer re-routing."""

from unittest.mock import patch

import pytest

import shared.api_clients.finnhub_client as fh


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("FINNHUB_API_KEY", "K")
    monkeypatch.setattr("shared.api_clients.finnhub_client.retry_with_backoff",
                        lambda fn, **kw: _safe(fn))


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


class _R:
    def __init__(self, body, headers=None):
        self._b = body
        self.headers = headers or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._b


def test_recommendation_trend():
    body = [
        {"period": "2026-08-01", "strongBuy": 23, "buy": 41, "hold": 3, "sell": 1, "strongSell": 0},
        {"period": "2026-07-01", "strongBuy": 24, "buy": 40, "hold": 4, "sell": 1, "strongSell": 0},
    ]
    with patch("shared.api_clients.finnhub_client.requests.get", return_value=_R(body)):
        out = fh.get_recommendation_trend("NVDA")
    assert out[0]["period"] == "2026-08-01" and out[0]["strongBuy"] == 23


def test_insider_mspr_sorted_recent_first():
    body = {"data": [
        {"year": 2026, "month": 1, "mspr": -100, "change": -500000},
        {"year": 2026, "month": 3, "mspr": 12.5, "change": 20000},
    ]}
    with patch("shared.api_clients.finnhub_client.requests.get", return_value=_R(body)):
        out = fh.get_insider_mspr("NVDA")
    assert out[0]["month"] == 3 and out[0]["mspr"] == 12.5


def test_peers():
    with patch("shared.api_clients.finnhub_client.requests.get",
               return_value=_R(["NVDA", "AVGO", "MU", "AMD"])):
        assert fh.get_peers("NVDA") == ["NVDA", "AVGO", "MU", "AMD"]


def test_profile_extracts_shares_outstanding():
    body = {"ticker": "ZION", "shareOutstanding": 145.94, "marketCapitalization": 10136.9,
            "finnhubIndustry": "Banking", "ipo": "1966-01-01"}
    with patch("shared.api_clients.finnhub_client.requests.get", return_value=_R(body)):
        p = fh.get_profile("ZION")
    assert p["shares_outstanding_m"] == 145.94 and p["industry"] == "Banking"


def test_quote_rejects_zero_price():
    with patch("shared.api_clients.finnhub_client.requests.get",
               return_value=_R({"c": 0, "h": 0, "l": 0, "o": 0, "pc": 0})):
        assert fh.get_quote("NVDA") == {}


def test_quote_parses_real():
    with patch("shared.api_clients.finnhub_client.requests.get",
               return_value=_R({"c": 227.98, "h": 230.47, "l": 220.9, "o": 222.86, "pc": 209.66, "t": 1787860800})):
        q = fh.get_quote("NVDA")
    assert q["current"] == 227.98 and q["prev_close"] == 209.66


def test_no_key_returns_none(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    assert fh._get("/x", {}, "x") is None
