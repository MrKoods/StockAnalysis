"""
Tests for the data.sec.gov JSON functions added to sec_edgar_client.py —
fetch_submissions, fetch_recent_ownership_filings, fetch_financial_facts.
Not yet wired into scoring; these just verify the client parses the real
response shapes.
"""

from datetime import date, timedelta
from unittest.mock import patch

import pytest

import shared.api_clients.sec_edgar_client as sec


@pytest.fixture(autouse=True)
def _cik(monkeypatch):
    monkeypatch.setattr(sec, "_ticker_cik_cache", {"NVDA": "0001045810", "ZION": "0000109380"})


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


def test_fetch_submissions_trims_to_recent_rows():
    payload = {
        "name": "NVIDIA CORP",
        "filings": {"recent": {
            "form": ["10-Q", "8-K", "4", "SC 13G/A"],
            "filingDate": ["2026-08-20", "2026-08-15", "2026-08-10", "2026-07-01"],
            "accessionNumber": ["a1", "a2", "a3", "a4"],
            "primaryDocument": ["d1", "d2", "d3", "d4"],
        }},
    }
    with patch.object(sec, "_get_json", return_value=payload):
        subs = sec.fetch_submissions("NVDA")
    assert subs["name"] == "NVIDIA CORP"
    assert subs["cik"] == "0001045810"
    assert len(subs["recent"]) == 4
    assert subs["recent"][0] == {
        "form": "10-Q", "filingDate": "2026-08-20",
        "accessionNumber": "a1", "primaryDocument": "d1",
    }


def test_fetch_submissions_no_cik_returns_none(monkeypatch):
    monkeypatch.setattr(sec, "_ticker_cik_cache", {})
    assert sec.fetch_submissions("ZZZZ") is None


def test_ownership_filings_bucketed_and_windowed():
    recent_day = (date.today() - timedelta(days=10)).isoformat()
    old_day = (date.today() - timedelta(days=400)).isoformat()
    payload = {
        "name": "X", "filings": {"recent": {
            "form": ["SC 13D", "SC 13D/A", "SC 13G", "13F-HR", "4", "4", "10-K", "SC 13D"],
            "filingDate": [recent_day] * 6 + [recent_day, old_day],
            "accessionNumber": [f"a{i}" for i in range(8)],
            "primaryDocument": ["d"] * 8,
        }},
    }
    with patch.object(sec, "_get_json", return_value=payload):
        out = sec.fetch_recent_ownership_filings("NVDA", lookback_days=120)
    assert len(out["activist_13d"]) == 2       # SC 13D + SC 13D/A in window; the 400-day-old one excluded
    assert len(out["passive_13g"]) == 1
    assert len(out["institutional_13f"]) == 1
    assert len(out["insider_form4"]) == 2
    assert out["activist_13d"][0]["form"] == "SC 13D"


def test_ownership_filings_empty_when_submissions_unavailable():
    with patch.object(sec, "fetch_submissions", return_value=None):
        out = sec.fetch_recent_ownership_filings("NVDA")
    assert out == {"activist_13d": [], "passive_13g": [], "institutional_13f": [], "insider_form4": []}


def test_financial_facts_parses_companyconcept_series():
    concept_payload = {
        "units": {"USD": [
            {"end": "2026-03-31", "val": 90_000_000_000, "fy": 2026, "fp": "Q1", "form": "10-Q"},
            {"end": "2026-06-30", "val": 96_000_000_000, "fy": 2026, "fp": "Q2", "form": "10-Q"},
            {"end": "2026-06-30", "val": 96_221_000_000, "fy": 2026, "fp": "Q2", "form": "10-Q/A"},  # amendment wins
        ]},
    }
    with patch.object(sec, "_get_json", return_value=concept_payload):
        facts = sec.fetch_financial_facts("NVDA", ["Revenues"])
    assert "Revenues" in facts
    series = facts["Revenues"]
    assert [p["end"] for p in series] == ["2026-03-31", "2026-06-30"]
    assert series[-1]["val"] == 96_221_000_000.0  # later-filed value for the same period end


def test_financial_facts_absent_concept_is_omitted():
    with patch.object(sec, "_get_json", return_value=None):
        facts = sec.fetch_financial_facts("NVDA", ["Revenues", "NonexistentConcept"])
    assert facts == {}


class TestFetchFundamentalTrend:
    """SEC XBRL as the deep-history replacement for the yfinance earnings/
    revenue scrapes, and the first real fundamentals for regional banks."""

    def _quarterly(self, concept, vals, start_end_pairs):
        return [
            {"start": s, "end": e, "val": float(v), "fy": 2026, "fp": "Q1",
             "form": "10-Q", "unit": "USD", "duration_days": _days(s, e)}
            for v, (s, e) in zip(vals, start_end_pairs)
        ]

    def test_semis_eps_yoy_and_margin(self, monkeypatch):
        pairs = [(f"2025-{m:02d}-01", f"2025-{m+2:02d}-28") for m in (1, 4, 7, 10)] + \
                [(f"2026-{m:02d}-01", f"2026-{m+2:02d}-28") for m in (1, 4)]
        facts = {
            "EarningsPerShareDiluted": self._quarterly("eps", [1.0, 1.1, 1.2, 1.3, 1.5, 1.65], pairs),
            "Revenues": self._quarterly("rev", [100, 110, 120, 130, 150, 165], pairs),
            "GrossProfit": self._quarterly("gp", [60, 66, 72, 78, 95, 105], pairs),
        }
        monkeypatch.setattr(sec, "fetch_financial_facts", lambda t, c, **k: facts)
        out = sec.fetch_fundamental_trend("NVDA", sector="semiconductors")
        assert out["_source"] == "sec_xbrl"
        assert out["eps_growth_trend"][0] == round((1.65 - 1.1) / 1.1, 4)   # Q2'26 vs Q2'25
        assert out["revenue_yoy_growth"] == round((165 - 110) / 110, 4)
        assert out["gross_margin_latest"] == round(105 / 165, 4)
        assert out["gross_margin_prior"] == round(95 / 150, 4)

    def test_bank_uses_nii_plus_noninterest_income_as_revenue(self, monkeypatch):
        pairs = [(f"2025-{m:02d}-01", f"2025-{m+2:02d}-28") for m in (1, 4, 7, 10)] + \
                [(f"2026-{m:02d}-01", f"2026-{m+2:02d}-28") for m in (1, 4)]
        facts = {
            "EarningsPerShareDiluted": self._quarterly("eps", [1.0]*4 + [1.2, 1.3], pairs),
            "InterestIncomeExpenseNet": self._quarterly("nii", [50, 51, 52, 53, 55, 56], pairs),
            "NoninterestIncome": self._quarterly("noni", [20, 21, 22, 23, 25, 26], pairs),
        }
        monkeypatch.setattr(sec, "fetch_financial_facts", lambda t, c, **k: facts)
        out = sec.fetch_fundamental_trend("ZION", sector="regional_banks")
        # revenue proxy latest = 56 + 26 = 82; year ago = 51 + 21 = 72
        assert out["revenue_yoy_growth"] == round((82 - 72) / 72, 4)
        assert "gross_margin_latest" not in out  # banks don't have it

    def test_no_xbrl_data_returns_empty(self, monkeypatch):
        monkeypatch.setattr(sec, "fetch_financial_facts", lambda t, c, **k: {})
        assert sec.fetch_fundamental_trend("TSM", sector="semiconductors") == {}

    def test_ytd_periods_filtered_out(self, monkeypatch):
        # A 270-day YTD fact alongside real quarterly ones must be ignored.
        q = [{"start": "2026-01-01", "end": "2026-03-31", "val": 100.0, "duration_days": 89, "form": "10-Q"}]
        ytd = [{"start": "2026-01-01", "end": "2026-09-30", "val": 300.0, "duration_days": 272, "form": "10-Q"}]
        from shared.api_clients.sec_edgar_client import _quarterly_series
        assert [p["val"] for p in _quarterly_series(q + ytd)] == [100.0]


def _days(s, e):
    from datetime import datetime
    return (datetime.strptime(e, "%Y-%m-%d") - datetime.strptime(s, "%Y-%m-%d")).days
