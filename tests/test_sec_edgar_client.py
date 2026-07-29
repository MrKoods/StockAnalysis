"""
Tests for shared/api_clients/sec_edgar_client.py.

Response shapes below are copied from the live endpoints (verified 2026-07-29)
rather than invented, since a mismatch here would silently return zero
filings forever without ever raising.
"""

from unittest.mock import MagicMock, patch

import pytest

import shared.api_clients.sec_edgar_client as sec_edgar_client
from shared.api_clients.sec_edgar_client import (
    _extract_item_descriptions,
    fetch_recent_8k_filings,
)

_TICKER_MAP_JSON = {
    "0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
    "1": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
}

# Trimmed real Atom response shape (2 entries) from
# https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001045810&type=8-K&output=atom
_ATOM_FEED = """<?xml version="1.0" encoding="ISO-8859-1" ?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <category label="form type" scheme="https://www.sec.gov/" term="8-K" />
    <link href="https://www.sec.gov/Archives/edgar/data/1045810/000104581026000060/0001045810-26-000060-index.htm" rel="alternate" type="text/html" />
    <summary type="html"> &lt;b&gt;Filed:&lt;/b&gt; 2026-07-02 &lt;b&gt;AccNo:&lt;/b&gt; 0001045810-26-000060 &lt;b&gt;Size:&lt;/b&gt; 138 KB&lt;br&gt;Item 5.02: Departure of Directors or Certain Officers; Election of Directors; Appointment of Certain Officers: Compensatory Arrangements of Certain Officers</summary>
    <title>8-K  - Current report</title>
    <updated>2026-07-02T09:23:16-04:00</updated>
  </entry>
  <entry>
    <category label="form type" scheme="https://www.sec.gov/" term="8-K" />
    <link href="https://www.sec.gov/Archives/edgar/data/1045810/000119312526275783/0001193125-26-275783-index.htm" rel="alternate" type="text/html" />
    <summary type="html"> &lt;b&gt;Filed:&lt;/b&gt; 2026-06-18 &lt;b&gt;AccNo:&lt;/b&gt; 0001193125-26-275783 &lt;b&gt;Size:&lt;/b&gt; 1 MB&lt;br&gt;Item 8.01: Other Events&lt;br&gt;Item 9.01: Financial Statements and Exhibits</summary>
    <title>8-K  - Current report</title>
    <updated>2026-06-18T16:00:24-04:00</updated>
  </entry>
</feed>"""

_EMPTY_ATOM_FEED = """<?xml version="1.0" encoding="ISO-8859-1" ?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>UNKNOWN CORP  (0000000000)</title>
</feed>"""


@pytest.fixture(autouse=True)
def _reset_cik_cache():
    """The ticker->CIK map is cached at module scope — isolate tests from each other."""
    sec_edgar_client._ticker_cik_cache = None
    yield
    sec_edgar_client._ticker_cik_cache = None


@pytest.fixture(autouse=True)
def _no_real_backoff_sleep(monkeypatch):
    """A forced-failure test exercises the real retry loop — don't actually wait 30s/60s/120s for it."""
    monkeypatch.setattr(sec_edgar_client.time, "sleep", lambda _seconds: None)


def _mock_json_response(data):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = data
    return resp


def _mock_xml_response(xml_text):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.content = xml_text.encode("utf-8")
    return resp


class TestExtractItemDescriptions:
    def test_extracts_single_item(self):
        summary = " <b>Filed:</b> 2026-07-02 <b>AccNo:</b> x <b>Size:</b> 1 KB<br>Item 5.02: Departure of Directors"
        result = _extract_item_descriptions(summary)
        assert result == "Item 5.02: Departure of Directors"

    def test_extracts_multiple_items_joined(self):
        summary = " <b>Filed:</b> x<br>Item 8.01: Other Events<br>Item 9.01: Financial Statements and Exhibits"
        result = _extract_item_descriptions(summary)
        assert result == "Item 8.01: Other Events; Item 9.01: Financial Statements and Exhibits"

    def test_empty_summary_returns_empty_string(self):
        assert _extract_item_descriptions(None) == ""
        assert _extract_item_descriptions("") == ""

    def test_summary_with_no_item_lines_returns_empty(self):
        summary = " <b>Filed:</b> 2026-07-02 <b>AccNo:</b> x <b>Size:</b> 1 KB"
        assert _extract_item_descriptions(summary) == ""


class TestFetchRecent8kFilings:
    def test_returns_parsed_articles_with_item_descriptions(self):
        with patch("shared.api_clients.sec_edgar_client.requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_json_response(_TICKER_MAP_JSON),
                _mock_xml_response(_ATOM_FEED),
            ]
            articles = fetch_recent_8k_filings("NVDA")

        assert len(articles) == 2
        assert articles[0]["title"] == "NVDA 8-K: Item 5.02: Departure of Directors or Certain Officers; Election of Directors; Appointment of Certain Officers: Compensatory Arrangements of Certain Officers"
        assert articles[0]["source_domain"] == "sec.gov"
        assert articles[0]["source"] == "SEC EDGAR"
        assert articles[0]["url"].startswith("https://www.sec.gov/Archives/")
        assert articles[0]["timestamp_utc"].startswith("2026-07-02")
        assert articles[1]["title"] == "NVDA 8-K: Item 8.01: Other Events; Item 9.01: Financial Statements and Exhibits"

    def test_title_always_contains_ticker_for_relevance_filter(self):
        with patch("shared.api_clients.sec_edgar_client.requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_json_response(_TICKER_MAP_JSON),
                _mock_xml_response(_ATOM_FEED),
            ]
            articles = fetch_recent_8k_filings("NVDA")
        for art in articles:
            assert "NVDA" in art["title"]

    def test_no_entries_returns_empty_list(self):
        with patch("shared.api_clients.sec_edgar_client.requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_json_response(_TICKER_MAP_JSON),
                _mock_xml_response(_EMPTY_ATOM_FEED),
            ]
            articles = fetch_recent_8k_filings("NVDA")
        assert articles == []

    def test_unknown_ticker_skips_fetch_and_returns_empty(self):
        with patch("shared.api_clients.sec_edgar_client.requests.get") as mock_get:
            mock_get.return_value = _mock_json_response(_TICKER_MAP_JSON)
            articles = fetch_recent_8k_filings("NOTATICKER")
        assert articles == []
        # Only the ticker-map call should have happened — no browse-edgar call
        # for a ticker with no resolvable CIK.
        assert mock_get.call_count == 1

    def test_ticker_map_fetch_failure_returns_empty_list(self):
        with patch("shared.api_clients.sec_edgar_client.requests.get", side_effect=Exception("network down")):
            articles = fetch_recent_8k_filings("NVDA")
        assert articles == []

    def test_ticker_cik_map_cached_across_calls(self):
        with patch("shared.api_clients.sec_edgar_client.requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_json_response(_TICKER_MAP_JSON),
                _mock_xml_response(_EMPTY_ATOM_FEED),
                _mock_xml_response(_EMPTY_ATOM_FEED),
            ]
            fetch_recent_8k_filings("NVDA")
            fetch_recent_8k_filings("NVDA")
        # Ticker map fetched once, browse-edgar fetched once per call = 3 total.
        assert mock_get.call_count == 3
