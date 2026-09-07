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
    assert out["cik"] == "0001045810"
    assert len(out["activist_13d"]) == 2       # SC 13D + SC 13D/A in window; the 400-day-old one excluded
    assert len(out["passive_13g"]) == 1
    assert len(out["institutional_13f"]) == 1
    assert len(out["insider_form4"]) == 2
    assert out["activist_13d"][0]["form"] == "SC 13D"
    assert out["insider_form4"][0]["primaryDocument"] == "d"


def test_ownership_filings_empty_when_submissions_unavailable():
    with patch.object(sec, "fetch_submissions", return_value=None):
        out = sec.fetch_recent_ownership_filings("NVDA")
    assert out == {
        "cik": None, "activist_13d": [], "passive_13g": [], "institutional_13f": [], "insider_form4": [],
    }


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

    def test_picks_the_tag_with_the_most_recent_data_not_the_first(self, monkeypatch):
        """NVDA reported revenue under RevenueFromContractWithCustomer... through
        FY2022, then switched to Revenues. 'First candidate with any data' locked
        onto the abandoned tag and scored 3-year-old quarters."""
        old_pairs = [("2021-01-01", "2021-03-28"), ("2021-04-01", "2021-06-28")]
        new_pairs = [(f"2025-{m:02d}-01", f"2025-{m + 2:02d}-28") for m in (1, 4, 7, 10)] + \
                    [(f"2026-{m:02d}-01", f"2026-{m + 2:02d}-28") for m in (1, 4)]
        facts = {
            "RevenueFromContractWithCustomerExcludingAssessedTax":
                self._quarterly("rev", [10, 11], old_pairs),
            "Revenues": self._quarterly("rev", [100, 110, 120, 130, 150, 165], new_pairs),
            "EarningsPerShareDiluted": self._quarterly("eps", [1.0, 1.1, 1.2, 1.3, 1.5, 1.65], new_pairs),
            "GrossProfit": self._quarterly("gp", [60, 66, 72, 78, 95, 105], new_pairs),
        }
        monkeypatch.setattr(sec, "fetch_financial_facts", lambda t, c, **k: facts)
        out = sec.fetch_fundamental_trend("NVDA", sector="semiconductors")
        assert out["revenue_yoy_growth"] == round((165 - 110) / 110, 4)  # from Revenues, not the old tag

    def test_yoy_matches_by_calendar_when_q4_is_missing(self, monkeypatch):
        """Most filers file a 10-K, not a Q4 10-Q, so the quarterly XBRL series
        has a Q4-shaped hole. Position-based i-vs-i+4 then compares Q2 against
        the prior Q1; calendar matching must not."""
        pairs = [
            ("2025-01-27", "2025-04-27"),  # Q1'25
            ("2025-04-28", "2025-07-27"),  # Q2'25
            ("2025-07-28", "2025-10-26"),  # Q3'25   (no Q4'25 — 10-K only)
            ("2026-01-26", "2026-04-26"),  # Q1'26
            ("2026-04-27", "2026-07-26"),  # Q2'26
        ]
        facts = {
            "EarningsPerShareDiluted": self._quarterly("eps", [1.0, 1.08, 1.30, 2.39, 2.46], pairs),
            "Revenues": self._quarterly("rev", [44, 46.7, 57, 81.6, 96.2], pairs),
            "GrossProfit": self._quarterly("gp", [28, 30, 37, 52, 62], pairs),
        }
        monkeypatch.setattr(sec, "fetch_financial_facts", lambda t, c, **k: facts)
        out = sec.fetch_fundamental_trend("NVDA", sector="semiconductors")
        # Q2'26 vs Q2'25 — not Q2'26 vs Q1'25
        assert out["revenue_yoy_growth"] == round((96.2 - 46.7) / 46.7, 4)
        assert out["eps_growth_trend"][0] == round((2.46 - 1.08) / 1.08, 4)

    def test_physically_impossible_gross_margin_is_dropped(self, monkeypatch):
        """Seen on MU's FY2026 10-Qs: a 90-day GrossProfit fact several times its
        matching revenue. A >95% (or negative) margin is the filer's own XBRL
        being inconsistent — don't surface it."""
        pairs = [(f"2025-{m:02d}-01", f"2025-{m + 2:02d}-28") for m in (1, 4, 7, 10)] + \
                [(f"2026-{m:02d}-01", f"2026-{m + 2:02d}-28") for m in (1, 4)]
        facts = {
            "EarningsPerShareDiluted": self._quarterly("eps", [1.0, 1.1, 1.2, 1.3, 1.5, 1.65], pairs),
            "Revenues": self._quarterly("rev", [100, 110, 120, 130, 150, 165], pairs),
            "GrossProfit": self._quarterly("gp", [60, 66, 72, 78, 160, 180], pairs),  # last two absurd
        }
        monkeypatch.setattr(sec, "fetch_financial_facts", lambda t, c, **k: facts)
        out = sec.fetch_fundamental_trend("MU", sector="semiconductors")
        assert out["gross_margin_latest"] == round(78 / 130, 4)   # last sane quarter
        assert out["gross_margin_prior"] == round(72 / 120, 4)

    def test_non_429_4xx_is_not_retried(self, monkeypatch):
        """companyconcept 404s (a tag the filer doesn't use) must short-circuit,
        not burn the 30s->60s->120s ladder — several probes per line item."""
        import requests

        slept = []
        monkeypatch.setattr("shared.api_clients._http_backoff.time.sleep", lambda s: slept.append(s))

        def _404_get(*a, **k):
            resp = requests.Response()
            resp.status_code = 404
            raise requests.exceptions.HTTPError("404 Client Error: Not Found", response=resp)

        monkeypatch.setattr("shared.api_clients._http_backoff.requests.get", _404_get)
        assert sec._get_with_backoff("https://data.sec.gov/api/xbrl/companyconcept/CIK0/us-gaap/Foo.json") is None
        assert slept == []

    def test_ytd_periods_filtered_out(self, monkeypatch):
        # A 270-day YTD fact alongside real quarterly ones must be ignored.
        q = [{"start": "2026-01-01", "end": "2026-03-31", "val": 100.0, "duration_days": 89, "form": "10-Q"}]
        ytd = [{"start": "2026-01-01", "end": "2026-09-30", "val": 300.0, "duration_days": 272, "form": "10-Q"}]
        from shared.api_clients.sec_edgar_client import _quarterly_series
        assert [p["val"] for p in _quarterly_series(q + ytd)] == [100.0]


def _days(s, e):
    from datetime import datetime
    return (datetime.strptime(e, "%Y-%m-%d") - datetime.strptime(s, "%Y-%m-%d")).days


# Real Form 4 XML shape, trimmed to what the parser reads — schema confirmed
# live against a real AMD Form 4 (CIK 2488, accession 0001452385-26-000008,
# 2026-09-06): reportingOwner/reportingOwnerId/rptOwnerName,
# reportingOwnerRelationship/officerTitle, periodOfReport, and
# nonDerivativeTable/nonDerivativeTransaction + derivativeTable/
# derivativeTransaction sharing the same transactionCoding/transactionAmounts
# shape. No XML namespace on this document type.
_SAMPLE_FORM4_XML = """<?xml version="1.0"?>
<ownershipDocument>
    <periodOfReport>2026-08-25</periodOfReport>
    <issuer><issuerTradingSymbol>AMD</issuerTradingSymbol></issuer>
    <reportingOwner>
        <reportingOwnerId><rptOwnerName>Hu Jean X.</rptOwnerName></reportingOwnerId>
        <reportingOwnerRelationship><officerTitle>EVP, CFO and Treasurer</officerTitle></reportingOwnerRelationship>
    </reportingOwner>
    <nonDerivativeTable>
        <nonDerivativeTransaction>
            <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
            <transactionAmounts>
                <transactionShares><value>900</value></transactionShares>
                <transactionPricePerShare><value>470.13</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
        </nonDerivativeTransaction>
        <nonDerivativeHolding>
            <postTransactionAmounts><sharesOwnedFollowingTransaction><value>19243</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
        </nonDerivativeHolding>
    </nonDerivativeTable>
    <derivativeTable>
        <derivativeTransaction>
            <transactionCoding><transactionCode>M</transactionCode></transactionCoding>
            <transactionAmounts>
                <transactionShares><value>7261</value></transactionShares>
                <transactionPricePerShare><value>0</value></transactionPricePerShare>
                <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
            </transactionAmounts>
        </derivativeTransaction>
    </derivativeTable>
</ownershipDocument>"""


class TestForm4XmlUrl:
    def test_strips_xsl_render_prefix_and_dashes(self):
        url = sec._form4_xml_url(
            "0000002488", "0001452385-26-000008", "xslF345X06/wk-form4_1787864688.xml",
        )
        assert url == "https://www.sec.gov/Archives/edgar/data/2488/000145238526000008/wk-form4_1787864688.xml"

    def test_missing_accession_or_document_returns_none(self):
        assert sec._form4_xml_url("2488", None, "doc.xml") is None
        assert sec._form4_xml_url("2488", "0001-26-000008", None) is None


class TestParseForm4Xml:
    def test_parses_owner_title_and_both_tables(self):
        parsed = sec._parse_form4_xml(_SAMPLE_FORM4_XML)
        assert parsed["owner"] == "Hu Jean X."
        assert parsed["owner_title"] == "EVP, CFO and Treasurer"
        assert parsed["period"] == "2026-08-25"
        codes = [t["code"] for t in parsed["transactions"]]
        assert codes == ["S", "M"]  # nonDerivativeHolding (no transactionCoding) correctly skipped

    def test_computes_dollar_value_from_shares_times_price(self):
        parsed = sec._parse_form4_xml(_SAMPLE_FORM4_XML)
        sale = parsed["transactions"][0]
        assert sale["shares"] == 900.0
        assert sale["price"] == 470.13
        assert sale["value"] == pytest.approx(900 * 470.13)

    def test_zero_price_exercise_has_zero_value_not_none(self):
        parsed = sec._parse_form4_xml(_SAMPLE_FORM4_XML)
        exercise = parsed["transactions"][1]
        assert exercise["code"] == "M"
        assert exercise["value"] == 0.0

    def test_malformed_xml_returns_none_not_raise(self):
        assert sec._parse_form4_xml("<not><valid xml") is None

    def test_multiple_reporting_owners_kept_as_list_owner_is_first(self):
        xml = _SAMPLE_FORM4_XML.replace(
            "</reportingOwner>",
            "</reportingOwner>\n    <reportingOwner>"
            "<reportingOwnerId><rptOwnerName>Su Lisa T.</rptOwnerName></reportingOwnerId>"
            "<reportingOwnerRelationship><officerTitle>CEO</officerTitle></reportingOwnerRelationship>"
            "</reportingOwner>",
            1,
        )
        parsed = sec._parse_form4_xml(xml)
        assert parsed["owner"] == "Hu Jean X."  # unchanged — scoring builds sets from this
        assert parsed["owners"] == ["Hu Jean X.", "Su Lisa T."]

    def test_director_with_no_officer_title_gets_role_label(self):
        xml = _SAMPLE_FORM4_XML.replace(
            "<reportingOwnerRelationship><officerTitle>EVP, CFO and Treasurer</officerTitle></reportingOwnerRelationship>",
            "<reportingOwnerRelationship><isDirector>1</isDirector><isTenPercentOwner>true</isTenPercentOwner></reportingOwnerRelationship>",
        )
        parsed = sec._parse_form4_xml(xml)
        assert parsed["owner_title"] == "Director, 10% owner"


class TestForm4XmlFetchFallbackAndCache:
    _INDEX_JSON = (
        '{"directory": {"item": ['
        '{"name": "xslF345X06/wf-form4.xml"}, '
        '{"name": "wf-form4_real.xml"}, '
        '{"name": "0001452385-26-000008-index.htm"}]}}'
    )

    def test_falls_back_to_accession_index_when_guessed_path_serves_html(self, monkeypatch):
        calls = []

        def fake_get_text(url):
            calls.append(url)
            if url.endswith("/index.json"):
                return self._INDEX_JSON
            if url.endswith("wf-form4_real.xml"):
                return _SAMPLE_FORM4_XML
            return "<html>XSL-rendered viewer, not the raw XML</html>"

        monkeypatch.setattr(sec, "_get_text", fake_get_text)
        text = sec._form4_xml_text("2488", {"accessionNumber": "0001452385-26-000008",
                                            "primaryDocument": "xslF345X06/wf-form4.xml"})
        assert "<ownershipDocument" in text
        assert any(u.endswith("/index.json") for u in calls)

    def test_fetch_form4_caches_xml_body_across_calls(self, monkeypatch):
        owned = {
            "cik": "2488",
            "insider_form4": [{"accessionNumber": "0001452385-26-000008", "primaryDocument": "xslF345X06/x.xml"}],
        }
        monkeypatch.setattr(sec, "fetch_recent_ownership_filings", lambda t, lookback_days=120: owned)
        hits = []
        monkeypatch.setattr(sec, "_get_text", lambda url: hits.append(url) or _SAMPLE_FORM4_XML)

        first = sec.fetch_form4_transactions("AMD")
        second = sec.fetch_form4_transactions("AMD")
        assert first == second
        assert len(hits) == 1  # second call served from cache, no re-fetch


class TestFetchForm4Transactions:
    """
    End-to-end orchestration: fetch_recent_ownership_filings -> per-filing XML
    fetch -> _parse_form4_xml -> aggregated buy/sell tally. Figures below
    (44 sells, $45,045,752.81, one seller "Hu Jean X.") match the real AMD
    data confirmed live 2026-09-06 via the actual production code path.
    """

    def test_sell_only_filing_aggregates_correctly(self, monkeypatch):
        owned = {
            "cik": "2488",
            "insider_form4": [{"accessionNumber": "0001452385-26-000008", "primaryDocument": "xslF345X06/x.xml"}],
        }
        monkeypatch.setattr(sec, "fetch_recent_ownership_filings", lambda t, lookback_days=120: owned)
        monkeypatch.setattr(sec, "_get_text", lambda url: _SAMPLE_FORM4_XML)

        result = sec.fetch_form4_transactions("AMD")
        assert result["filings_seen"] == 1
        assert result["filings_parsed"] == 1
        assert result["open_market_buys"] == 0
        assert result["open_market_sells"] == 1
        assert result["sell_value"] == pytest.approx(900 * 470.13)
        assert result["net_value"] == pytest.approx(-900 * 470.13)
        assert result["read"] == "net selling"
        assert result["other_activity"] == {"M": 1}
        assert result["recent"][0]["owner"] == "Hu Jean X."
        assert result["recent"][0]["code"] == "S"

    def test_no_cik_returns_empty_result(self, monkeypatch):
        monkeypatch.setattr(sec, "fetch_recent_ownership_filings",
                            lambda t, lookback_days=120: {"cik": None, "insider_form4": [{"accessionNumber": "a", "primaryDocument": "d"}]})
        result = sec.fetch_form4_transactions("AMD")
        assert result["filings_seen"] == 1
        assert result["filings_parsed"] == 0
        assert result["read"] == "no usable insider data"

    def test_grants_only_filing_reads_as_grants_exercises_only(self, monkeypatch):
        grants_only_xml = _SAMPLE_FORM4_XML.replace(
            "<transactionCode>S</transactionCode>", "<transactionCode>A</transactionCode>",
        )
        owned = {
            "cik": "2488",
            "insider_form4": [{"accessionNumber": "0001452385-26-000008", "primaryDocument": "xslF345X06/x.xml"}],
        }
        monkeypatch.setattr(sec, "fetch_recent_ownership_filings", lambda t, lookback_days=120: owned)
        monkeypatch.setattr(sec, "_get_text", lambda url: grants_only_xml)

        result = sec.fetch_form4_transactions("AMD")
        assert result["open_market_buys"] == 0
        assert result["open_market_sells"] == 0
        assert result["read"] == "grants / exercises only"
        assert result["other_activity"] == {"A": 1, "M": 1}

    def test_fetch_failure_for_one_filing_does_not_crash(self, monkeypatch):
        owned = {
            "cik": "2488",
            "insider_form4": [{"accessionNumber": "a1", "primaryDocument": "d1"}],
        }
        monkeypatch.setattr(sec, "fetch_recent_ownership_filings", lambda t, lookback_days=120: owned)
        monkeypatch.setattr(sec, "_get_text", lambda url: None)  # simulates a fetch failure
        result = sec.fetch_form4_transactions("AMD")
        assert result["filings_seen"] == 1
        assert result["filings_parsed"] == 0
        assert result["read"] == "no usable insider data"
