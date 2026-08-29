"""Tests for shared/api_clients/seeking_alpha_client.py — SA data endpoints (not yet wired to scoring)."""

from unittest.mock import patch

import pytest

import shared.api_clients.seeking_alpha_client as sa


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("RAPIDAPI_KEY", "K")


def test_get_daily_ohlcv_parses_and_filters_sessions():
    payload = {"attributes": {
        "2026-08-25 00:00:00": {"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100, "adj": 1.0, "session": "market"},
        "2026-08-26 00:00:00": {"open": 1.5, "high": 2.5, "low": 1, "close": 2, "volume": 120, "adj": 1.0, "session": "market"},
        "2026-08-27 09:30:00": {"open": 2, "high": 2.1, "low": 1.9, "close": 2.05, "volume": 5, "session": "blended"},
    }}
    with patch.object(sa, "_sa_get", return_value=payload):
        bars = sa.get_daily_ohlcv("NVDA", "1Y")
    assert [b["date"] for b in bars] == ["2026-08-25", "2026-08-26"]  # blended point dropped
    assert bars[0]["volume"] == 100


def test_get_factor_grades_extracts_quant_rating_and_counts():
    payload = {"data": [
        {"attributes": {"asDate": "2026-08-28", "ratings": {
            "quantRating": 3.44, "sellSideRating": 4.69, "authorsRating": 3.86,
            "authorsRatingBuyCount30Day": 20, "authorsRatingBuyCount90Day": 32,
            "authorsRatingSellCount30Day": 2, "authorsRatingSellCount90Day": 5,
        }}},
        {"attributes": {"asDate": "2026-05-28", "ratings": {"quantRating": 3.2, "sellSideRating": 4.6}}},
    ]}
    with patch.object(sa, "_sa_get", return_value=payload):
        g = sa.get_factor_grades("NVDA")
    assert g["quant_rating"] == 3.44
    assert g["as_of"] == "2026-08-28"
    assert g["buy_count_30d"] == 20 and g["buy_count_90d"] == 32
    assert len(g["history"]) == 2


def test_get_factor_grades_empty_on_no_data():
    with patch.object(sa, "_sa_get", return_value={"data": []}):
        assert sa.get_factor_grades("NVDA") == {}


def test_get_fundamentals_parses_statement_lines():
    payload = {"data": [
        {"attributes": {"field": "total_revenue", "value": 96221000000.0, "year": 2027, "quarter": 2,
                        "period_end_date": "2026-07-26T00:00:00"}},
        {"attributes": {"field": "gross_profit", "value": 70000000000.0, "year": 2027, "quarter": 2,
                        "period_end_date": "2026-07-26T00:00:00"}},
    ]}
    with patch.object(sa, "_sa_get", return_value=payload):
        rows = sa.get_fundamentals("NVDA")
    assert rows[0]["field"] == "total_revenue"
    assert rows[0]["value"] == 96221000000.0
    assert rows[0]["period_end_date"] == "2026-07-26"


def test_analyst_price_target_resolves_id_and_reads_estimate():
    meta = {"data": [{"id": "1150", "attributes": {"name": "NVDA"}}]}
    target = {"estimates": {"1150": {"target_price_mean": {"0": [
        {"effectivedate": "2026-08-01T00:00:00", "dataitemvalue": "300.0"},
        {"effectivedate": "2026-08-27T00:00:00", "dataitemvalue": "320.0"},
    ]}}}, "revisions": {}}

    def _fake(path, params=None):
        return meta if "meta-data" in path else target

    with patch.object(sa, "_sa_get", side_effect=_fake):
        out = sa.get_analyst_price_target("NVDA")
    assert out["target_mean"] == 320.0  # newest effectivedate wins


def test_missing_key_returns_none(monkeypatch):
    monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
    assert sa._sa_get("/x") is None


def test_budget_exhausted_returns_none(monkeypatch):
    monkeypatch.setattr(sa.rate_limiter, "acquire",
                        lambda *a, **k: (_ for _ in ()).throw(sa.rate_limiter.BudgetExhausted("cap")))
    assert sa._sa_get("/x") is None
