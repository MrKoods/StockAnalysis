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
    _extract_capex_snippets,
    _list_filing_exhibits,
    fetch_recent_8k_filings,
    fetch_hyperscaler_capex_snippets,
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

# Real <content> shape (verified 2026-07-29) for the capex-relevant filings path —
# one earnings filing (item 2.02, has an ex99 exhibit) and one unrelated
# director-departure filing (item 5.02, should be filtered out before any
# exhibit fetch is even attempted).
_ATOM_FEED_WITH_CONTENT = """<?xml version="1.0" encoding="ISO-8859-1" ?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <content type="text/xml">
      <accession-number>0001018724-26-000012</accession-number>
      <filing-date>2026-04-29</filing-date>
      <filing-href>https://www.sec.gov/Archives/edgar/data/1018724/000101872426000012/0001018724-26-000012-index.htm</filing-href>
      <filing-type>8-K</filing-type>
      <items-desc>items 2.02 and 9.01</items-desc>
    </content>
    <link href="https://www.sec.gov/Archives/edgar/data/1018724/000101872426000012/0001018724-26-000012-index.htm" rel="alternate" type="text/html" />
    <summary type="html"> &lt;b&gt;Filed:&lt;/b&gt; 2026-04-29&lt;br&gt;Item 2.02: Results of Operations and Financial Condition</summary>
    <title>8-K  - Current report</title>
    <updated>2026-04-29T20:18:55-04:00</updated>
  </entry>
  <entry>
    <content type="text/xml">
      <accession-number>0001018724-26-000003</accession-number>
      <filing-date>2026-01-23</filing-date>
      <filing-href>https://www.sec.gov/Archives/edgar/data/1018724/000101872426000003/0001018724-26-000003-index.htm</filing-href>
      <filing-type>8-K</filing-type>
      <items-desc>item 5.02</items-desc>
    </content>
    <link href="https://www.sec.gov/Archives/edgar/data/1018724/000101872426000003/0001018724-26-000003-index.htm" rel="alternate" type="text/html" />
    <summary type="html"> &lt;b&gt;Filed:&lt;/b&gt; 2026-01-23&lt;br&gt;Item 5.02: Departure of Directors</summary>
    <title>8-K  - Current report</title>
    <updated>2026-01-23T17:01:33-05:00</updated>
  </entry>
</feed>"""

# Real index.json shape (verified 2026-07-29) for the earnings filing above.
_INDEX_JSON = {
    "directory": {
        "item": [
            {"name": "0001018724-26-000012-index.html", "type": "text.gif"},
            {"name": "amzn-20260331xex991.htm", "type": "text.gif"},
            {"name": "amzn-20260331xex992.htm", "type": "text.gif"},
            {"name": "amzn-20260429.htm", "type": "text.gif"},
        ]
    }
}

# Real language from AMZN's actual Q1 2026 earnings exhibit.
_EXHIBIT_HTML_WITH_CAPEX = """
<html><body>
<p>Operating cash flow increased 15% to $113.9 billion for the trailing
twelve months, driven primarily by a year-over-year increase of $59.3 billion
in <b>purchases of property and equipment</b>, net of proceeds from sales and
incentives. This increase primarily reflects investments in artificial
intelligence infrastructure.</p>
</body></html>
"""

_EXHIBIT_HTML_NO_CAPEX = "<html><body><p>Board election results were certified.</p></body></html>"


@pytest.fixture(autouse=True)
def _reset_cik_cache():
    """The ticker->CIK map is cached at module scope — isolate tests from each other."""
    sec_edgar_client._ticker_cik_cache = None
    yield
    sec_edgar_client._ticker_cik_cache = None


@pytest.fixture(autouse=True)
def _no_real_backoff_sleep(monkeypatch):
    """
    A forced-failure test exercises the real retry loop — don't actually wait
    30s/60s/120s for it. The retry loop itself now lives in the shared
    shared/api_clients/_http_backoff.py module (previously sec_edgar_client's
    own hand-written _get_with_backoff), so that's where time.sleep is
    patched now.
    """
    import shared.api_clients._http_backoff as http_backoff
    monkeypatch.setattr(http_backoff.time, "sleep", lambda _seconds: None)


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
        with patch("shared.api_clients._http_backoff.requests.get") as mock_get:
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
        with patch("shared.api_clients._http_backoff.requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_json_response(_TICKER_MAP_JSON),
                _mock_xml_response(_ATOM_FEED),
            ]
            articles = fetch_recent_8k_filings("NVDA")
        for art in articles:
            assert "NVDA" in art["title"]

    def test_no_entries_returns_empty_list(self):
        with patch("shared.api_clients._http_backoff.requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_json_response(_TICKER_MAP_JSON),
                _mock_xml_response(_EMPTY_ATOM_FEED),
            ]
            articles = fetch_recent_8k_filings("NVDA")
        assert articles == []

    def test_unknown_ticker_skips_fetch_and_returns_empty(self):
        with patch("shared.api_clients._http_backoff.requests.get") as mock_get:
            mock_get.return_value = _mock_json_response(_TICKER_MAP_JSON)
            articles = fetch_recent_8k_filings("NOTATICKER")
        assert articles == []
        # Only the ticker-map call should have happened — no browse-edgar call
        # for a ticker with no resolvable CIK.
        assert mock_get.call_count == 1

    def test_ticker_map_fetch_failure_returns_empty_list(self):
        with patch("shared.api_clients._http_backoff.requests.get", side_effect=Exception("network down")):
            articles = fetch_recent_8k_filings("NVDA")
        assert articles == []

    def test_ticker_cik_map_cached_across_calls(self):
        with patch("shared.api_clients._http_backoff.requests.get") as mock_get:
            mock_get.side_effect = [
                _mock_json_response(_TICKER_MAP_JSON),
                _mock_xml_response(_EMPTY_ATOM_FEED),
                _mock_xml_response(_EMPTY_ATOM_FEED),
            ]
            fetch_recent_8k_filings("NVDA")
            fetch_recent_8k_filings("NVDA")
        # Ticker map fetched once, browse-edgar fetched once per call = 3 total.
        assert mock_get.call_count == 3


class TestExtractCapexSnippets:
    def test_finds_snippet_around_context_term(self):
        html = "<p>We spent more on <b>capital expenditures</b> this quarter.</p>"
        snippets = _extract_capex_snippets(html)
        assert len(snippets) == 1
        assert "capital expenditures" in snippets[0].lower()
        assert "<b>" not in snippets[0]  # HTML stripped

    def test_no_context_terms_returns_empty(self):
        assert _extract_capex_snippets("<p>Board election results certified.</p>") == []

    def test_caps_at_max_snippets(self):
        # Well-separated (400+ chars apart) so each is a genuinely distinct
        # snippet rather than triggering the overlap-dedup logic.
        filler = "x" * 400
        html = f"capital expenditures{filler}capex{filler}infrastructure investment{filler}data center"
        snippets = _extract_capex_snippets(html, max_snippets=2)
        assert len(snippets) == 2

    def test_overlapping_terms_dont_produce_duplicate_snippets(self):
        # "capex" and "capital expenditures" both present close together —
        # should count as one snippet, not two near-identical ones.
        html = "Our capex (capital expenditures) plan for the year is set."
        snippets = _extract_capex_snippets(html, max_snippets=5)
        assert len(snippets) == 1


class TestListFilingExhibits:
    def test_returns_ex99_urls_only(self):
        with patch("shared.api_clients._http_backoff.requests.get") as mock_get:
            mock_get.return_value = _mock_json_response(_INDEX_JSON)
            urls = _list_filing_exhibits(
                "https://www.sec.gov/Archives/edgar/data/1018724/000101872426000012/0001018724-26-000012-index.htm"
            )
        assert len(urls) == 2
        assert all("ex99" in u.lower() for u in urls)
        assert all(u.startswith("https://www.sec.gov/Archives/edgar/data/1018724/000101872426000012/") for u in urls)

    def test_non_index_url_returns_empty(self):
        assert _list_filing_exhibits("https://www.sec.gov/not-an-index-page.htm") == []
        assert _list_filing_exhibits(None) == []

    def test_fetch_failure_returns_empty(self):
        with patch("shared.api_clients._http_backoff.requests.get", side_effect=Exception("down")):
            assert _list_filing_exhibits("https://www.sec.gov/x/y-index.htm") == []


class TestFetchHyperscalerCapexSnippets:
    def test_filters_to_earnings_related_items_and_extracts_snippet(self):
        amzn_map = _TICKER_MAP_JSON | {"2": {"cik_str": 1018724, "ticker": "AMZN", "title": "AMAZON COM INC"}}
        exhibit_resp = MagicMock()
        exhibit_resp.raise_for_status.return_value = None
        exhibit_resp.text = _EXHIBIT_HTML_WITH_CAPEX

        def _side_effect(url, params=None, timeout=None, headers=None):
            if url == sec_edgar_client._TICKER_MAP_URL:
                return _mock_json_response(amzn_map)
            if url == sec_edgar_client._BROWSE_EDGAR_URL:
                return _mock_xml_response(_ATOM_FEED_WITH_CONTENT)
            if url.endswith("index.json"):
                return _mock_json_response(_INDEX_JSON)
            if "ex99" in url.lower():
                return exhibit_resp
            raise AssertionError(f"Unexpected URL requested: {url}")

        with patch("shared.api_clients._http_backoff.requests.get", side_effect=_side_effect):
            articles = fetch_hyperscaler_capex_snippets("AMZN")

        assert len(articles) >= 1
        assert all("AMZN" in a["title"] for a in articles)
        assert all(a["source_domain"] == "sec.gov" for a in articles)
        assert any("property and equipment" in a["title"].lower() for a in articles)

    def test_non_earnings_filing_never_triggers_exhibit_fetch(self):
        """Only the item-5.02 (director departure) filing exists — no exhibit fetch should happen."""
        atom_only_5_02 = """<?xml version="1.0" encoding="ISO-8859-1" ?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <content type="text/xml">
      <filing-href>https://www.sec.gov/Archives/edgar/data/1018724/x/x-index.htm</filing-href>
      <items-desc>item 5.02</items-desc>
    </content>
    <updated>2026-01-23T17:01:33-05:00</updated>
  </entry>
</feed>"""

        def _side_effect(url, params=None, timeout=None, headers=None):
            if url == sec_edgar_client._TICKER_MAP_URL:
                return _mock_json_response(_TICKER_MAP_JSON | {"2": {"cik_str": 1018724, "ticker": "AMZN", "title": "AMAZON COM INC"}})
            if url == sec_edgar_client._BROWSE_EDGAR_URL:
                return _mock_xml_response(atom_only_5_02)
            raise AssertionError(f"Unexpected URL requested (exhibit fetch should never happen): {url}")

        with patch("shared.api_clients._http_backoff.requests.get", side_effect=_side_effect):
            articles = fetch_hyperscaler_capex_snippets("AMZN")
        assert articles == []

    def test_exhibit_without_capex_language_produces_no_snippets(self):
        def _side_effect(url, params=None, timeout=None, headers=None):
            if url == sec_edgar_client._TICKER_MAP_URL:
                return _mock_json_response(_TICKER_MAP_JSON | {"2": {"cik_str": 1018724, "ticker": "AMZN", "title": "AMAZON COM INC"}})
            if url == sec_edgar_client._BROWSE_EDGAR_URL:
                return _mock_xml_response(_ATOM_FEED_WITH_CONTENT)
            if url.endswith("index.json"):
                return _mock_json_response(_INDEX_JSON)
            if "ex99" in url.lower():
                resp = MagicMock()
                resp.raise_for_status.return_value = None
                resp.text = _EXHIBIT_HTML_NO_CAPEX
                return resp
            raise AssertionError(f"Unexpected URL requested: {url}")

        with patch("shared.api_clients._http_backoff.requests.get", side_effect=_side_effect):
            articles = fetch_hyperscaler_capex_snippets("AMZN")
        assert articles == []

    def test_unknown_ticker_returns_empty(self):
        with patch("shared.api_clients._http_backoff.requests.get") as mock_get:
            mock_get.return_value = _mock_json_response(_TICKER_MAP_JSON)
            articles = fetch_hyperscaler_capex_snippets("NOTATICKER")
        assert articles == []
        assert mock_get.call_count == 1


class TestForeignPrivateIssuer6KFallback:
    """
    Foreign private issuers file 6-K, never 8-K (v2.2.107).

    The client asked for `type=8-K` only, so TSM and ASML returned zero filings
    on every scan since the SEC source was added — silently, because an empty
    feed is indistinguishable from "nothing was filed". Verified against SEC's
    submissions API on 2026-08-26: TSM 712 6-K / 0 8-K, ASML 361 / 0, domestic
    NVDA 63 8-K. Since these filings feed the Event Severity Gate, neither
    ticker could raise a critical event from its own disclosures.
    """

    @staticmethod
    def _atom(form_type, n=2):
        entries = "".join(
            f'<entry><summary>Item 8.01: Other Events</summary>'
            f'<updated>2026-08-2{i}T12:00:00-04:00</updated>'
            f'<link href="https://sec.gov/f{i}"/></entry>'
            for i in range(n)
        )
        return f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>'.encode()

    def _patch(self, monkeypatch, responses):
        """responses: {form_type: body}. Records the order types were tried."""
        import shared.api_clients.sec_edgar_client as sec
        monkeypatch.setattr(sec, "_load_ticker_cik_map", lambda: {"TSM": "0001046179", "NVDA": "0001045810"})
        sec._ticker_form_type_cache.clear()
        tried = []

        class R:
            def __init__(self, content): self.content = content

        def fake(url, params=None, retries=3):
            tried.append(params["type"])
            body = responses.get(params["type"])
            return R(body) if body is not None else R(self._atom("x", 0))

        monkeypatch.setattr(sec, "_get_with_backoff", fake)
        return tried

    def test_foreign_issuer_falls_back_to_6k(self, monkeypatch):
        from shared.api_clients.sec_edgar_client import fetch_recent_8k_filings
        tried = self._patch(monkeypatch, {"6-K": self._atom("6-K")})
        articles = fetch_recent_8k_filings("TSM")
        assert tried == ["8-K", "6-K"], "must try 8-K first, then fall back"
        assert len(articles) == 2
        assert "6-K" in articles[0]["title"]

    def test_domestic_filer_costs_one_request(self, monkeypatch):
        """No extra call for the common case."""
        from shared.api_clients.sec_edgar_client import fetch_recent_8k_filings
        tried = self._patch(monkeypatch, {"8-K": self._atom("8-K")})
        articles = fetch_recent_8k_filings("NVDA")
        assert tried == ["8-K"]
        assert len(articles) == 2
        assert "8-K" in articles[0]["title"]

    def test_result_is_cached_across_calls(self, monkeypatch):
        """The cross-scan result cache means a repeat call makes zero requests."""
        from shared.api_clients.sec_edgar_client import fetch_recent_8k_filings
        tried = self._patch(monkeypatch, {"6-K": self._atom("6-K")})
        fetch_recent_8k_filings("TSM")
        fetch_recent_8k_filings("TSM")
        assert tried == ["8-K", "6-K"]  # second call served from cache.cached_call

    def test_discovered_form_type_persists_when_result_cache_is_cold(self, monkeypatch):
        """With the result cache cleared, a foreign issuer still only re-tries
        6-K (form type discovered in-process), not 8-K then 6-K again."""
        from shared.api_clients import cache
        from shared.api_clients.sec_edgar_client import fetch_recent_8k_filings
        tried = self._patch(monkeypatch, {"6-K": self._atom("6-K")})
        fetch_recent_8k_filings("TSM")
        cache.clear("news")
        fetch_recent_8k_filings("TSM")
        assert tried == ["8-K", "6-K", "6-K"]

    def test_no_filings_of_either_type_returns_empty(self, monkeypatch):
        from shared.api_clients.sec_edgar_client import fetch_recent_8k_filings
        tried = self._patch(monkeypatch, {})
        assert fetch_recent_8k_filings("TSM") == []
        assert tried == ["8-K", "6-K"]


class TestRequestFailureIsDistinguishableFromNoFilings:
    """
    A failed SEC request must not look like "this company filed nothing"
    (v2.2.109).

    Both used to return []. That meant an SEC throttle or block — the stated
    enforcement for their fair-access policy, which this project is technically
    out of compliance with while SEC_EDGAR_USER_AGENT points at a
    non-routable domain — produced exactly what a quiet news week produces. The
    model would lose one of five news sources AND every filing-based Event
    Severity Gate trigger while looking completely healthy, with scores drifting
    down across the board and no visible cause. Same shape as the TSM/ASML 8-K
    bug fixed one version earlier.

    Low probability (~156 sequential requests/day against a 10/second limit),
    but poor detectability is exactly what makes it expensive when it happens.
    """

    @staticmethod
    def _empty_feed():
        class R:
            content = b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
        return R()

    def _setup(self, monkeypatch, resp):
        import shared.api_clients.sec_edgar_client as sec
        monkeypatch.setattr(sec, "_load_ticker_cik_map", lambda: {"NVDA": "0001045810"})
        sec._ticker_form_type_cache.clear()
        entries = []
        monkeypatch.setattr(sec, "write_validation_entry", lambda t, k, d: entries.append((t, k, d)))
        monkeypatch.setattr(sec, "_get_with_backoff", lambda url, params=None, retries=3: resp)
        return sec, entries

    def test_request_failure_is_logged_to_validation(self, monkeypatch):
        sec, entries = self._setup(monkeypatch, None)
        assert sec.fetch_recent_8k_filings("NVDA") == []
        assert len(entries) == 1
        assert entries[0][1] == "sec_edgar"
        assert "request_failed" in entries[0][2]

    def test_genuinely_no_filings_logs_nothing(self, monkeypatch):
        """A quiet week must stay quiet — otherwise the signal is worthless."""
        sec, entries = self._setup(monkeypatch, self._empty_feed())
        assert sec.fetch_recent_8k_filings("NVDA") == []
        assert entries == []

    def test_failed_8k_does_not_fall_through_to_6k(self, monkeypatch):
        """
        A failed 8-K request must not cause the 6-K fallback to fire and cache
        6-K as this ticker's form type — that would silently mislabel a domestic
        filer off the back of a transient outage.
        """
        import shared.api_clients.sec_edgar_client as sec
        monkeypatch.setattr(sec, "_load_ticker_cik_map", lambda: {"NVDA": "0001045810"})
        sec._ticker_form_type_cache.clear()
        monkeypatch.setattr(sec, "write_validation_entry", lambda *a: None)
        tried = []

        def fake(url, params=None, retries=3):
            tried.append(params["type"])
            return None

        monkeypatch.setattr(sec, "_get_with_backoff", fake)
        sec.fetch_recent_8k_filings("NVDA")
        assert tried == ["8-K"], "must stop on failure, not try 6-K"
        assert "NVDA" not in sec._ticker_form_type_cache

    def test_malformed_feed_counts_as_failure(self, monkeypatch):
        class R:
            content = b"<<<not xml at all"
        sec, entries = self._setup(monkeypatch, R())
        assert sec.fetch_recent_8k_filings("NVDA") == []
        assert any("request_failed" in e[2] for e in entries)
