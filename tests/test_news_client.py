"""
Tests for shared/api_clients/news_client.py's pure/testable helper —
_parse_yahoo_news_item. The live fetch_news_yahoo() call itself isn't tested
here (no yfinance mocking convention exists elsewhere in this suite — see
test_positioning_client.py), consistent with the rest of this project's test
style: test the parsing logic against hand-built dicts instead of the live fetch.

Also covers fetch_news_alpha_vantage's secret-redaction wiring, now routed
through the shared shared/api_clients/_http_backoff.py module (previously
this client's own hand-written _backoff_get) — a regression test that didn't
exist before this consolidation, so nothing would have caught it if the
redact closure had been dropped or miswired during the migration.
"""

from datetime import datetime, timezone
from unittest.mock import patch

from shared.api_clients.news_client import _parse_yahoo_news_item, fetch_news_alpha_vantage


class TestParseYahooNewsItem:
    def test_parses_current_nested_content_shape(self):
        # Real shape returned by yf.Ticker(ticker).news as of 2026-08 — title,
        # pubDate, provider, and canonicalUrl all live under item["content"],
        # not at the top level. Regression test for the bug where every Yahoo
        # article silently carried title="" (item.get("title", "") looked at
        # the wrong level), so is_ticker_relevant could never match any of them.
        item = {
            "id": "9d485d6e-9306-3cd5-9fb0-e23613b0a85e",
            "content": {
                "id": "9d485d6e-9306-3cd5-9fb0-e23613b0a85e",
                "title": "Zions (ZION) Stock Trades At A Discount To Earnings After A 105% Run",
                "pubDate": "2026-08-01T05:08:07Z",
                "displayTime": "2026-08-01T05:08:07Z",
                "provider": {"displayName": "Simply Wall St.", "url": "https://simplywall.st/"},
                "canonicalUrl": {"url": "https://finance.yahoo.com/markets/stocks/articles/zions-zion.html"},
            },
        }
        result = _parse_yahoo_news_item(item)
        assert result["title"] == "Zions (ZION) Stock Trades At A Discount To Earnings After A 105% Run"
        assert result["publisher"] == "Simply Wall St."
        assert result["link"] == "https://finance.yahoo.com/markets/stocks/articles/zions-zion.html"
        assert result["article_id"] == "9d485d6e-9306-3cd5-9fb0-e23613b0a85e"
        assert result["timestamp_utc"] == datetime(2026, 8, 1, 5, 8, 7, tzinfo=timezone.utc).isoformat()

    def test_falls_back_to_legacy_flat_shape(self):
        # Older/alternate yfinance response shape (no "content" key) — must
        # still parse correctly, not just silently return empty fields.
        item = {
            "uuid": "abc-123",
            "title": "Some Legacy-Shaped Headline",
            "link": "https://finance.yahoo.com/news/legacy",
            "publisher": "Reuters",
            "providerPublishTime": 1785600000,
        }
        result = _parse_yahoo_news_item(item)
        assert result["title"] == "Some Legacy-Shaped Headline"
        assert result["publisher"] == "Reuters"
        assert result["link"] == "https://finance.yahoo.com/news/legacy"
        assert result["article_id"] == "abc-123"

    def test_missing_content_and_flat_fields_returns_empty_title_not_error(self):
        # Truly malformed item (neither shape) — must degrade gracefully to an
        # empty title (which is_ticker_relevant will correctly treat as
        # non-matching) rather than raising.
        result = _parse_yahoo_news_item({"id": "x"})
        assert result["title"] == ""
        assert result["publisher"] == "Yahoo Finance"

    def test_content_present_but_missing_provider_and_url(self):
        item = {"content": {"title": "Headline With No Provider Info", "pubDate": "2026-08-01T00:00:00Z"}}
        result = _parse_yahoo_news_item(item)
        assert result["title"] == "Headline With No Provider Info"
        assert result["publisher"] == "Yahoo Finance"
        assert result["link"] == ""

    def test_malformed_pub_date_falls_back_to_now(self):
        item = {"content": {"title": "Headline", "pubDate": "not-a-real-date"}}
        result = _parse_yahoo_news_item(item)
        assert result["title"] == "Headline"
        # Just confirm it parsed to *some* valid ISO timestamp, not a crash
        datetime.fromisoformat(result["timestamp_utc"])


class TestFetchNewsAlphaVantageRedaction:
    def test_api_key_never_appears_in_logs_on_failure(self, monkeypatch, caplog):
        monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "SUPERSECRETKEY123")

        def _fake_get(url, params=None, headers=None, timeout=None):
            # requests' real HTTPError/ConnectionError string representation
            # embeds the full request URL including query params — simulate
            # that shape rather than a bare message with no key in it at all.
            full_url = f"{url}?apikey={params.get('apikey', '')}&tickers=NVDA"
            raise ConnectionError(f"Failed to establish connection to {full_url}")

        with patch("shared.api_clients.news_client.check_av_budget", return_value=True), \
             patch("shared.api_clients.news_client.increment_av_call_count", return_value=1), \
             patch("shared.api_clients._http_backoff.requests.get", side_effect=_fake_get), \
             patch("shared.api_clients._http_backoff.time.sleep"), \
             caplog.at_level("WARNING"):
            result = fetch_news_alpha_vantage("NVDA")

        assert result == []
        assert "SUPERSECRETKEY123" not in caplog.text
        assert "***REDACTED***" in caplog.text


class TestAlphaVantageBudgetReservation:
    """
    A share of the daily Alpha Vantage budget is held for the post_close scan
    (v2.2.108).

    Without a reservation the budget was first-come-first-served across the
    day's three scans, so the EARLIEST scan — ranking on the least information —
    spent it and the most informed one went without. Measured live 2026-08-26:
    all 20 calls consumed, post_close got only 6, and TGT's news fetch was
    skipped outright. Structurally the same failure as the rank-track slot bug
    fixed in v2.2.100, where the first scan of the day claimed every per-sector
    slot.

    A reservation rather than a raised ceiling on purpose: AV's free tier allows
    25/day against the 20 used here, so raising the limit buys five calls and
    does nothing about the ordering.
    """

    @staticmethod
    def _at(monkeypatch, used):
        import shared.api_clients.news_client as nc
        monkeypatch.setattr(nc, "get_av_call_count", lambda: {"count": used, "date": "2026-08-26"})
        return nc

    def test_earlier_scans_stop_at_the_reserved_boundary(self, monkeypatch):
        nc = self._at(monkeypatch, 12)
        assert nc.check_av_budget(20, scan_type="pre_market", reserved_for_owner=8) is False
        assert nc.check_av_budget(20, scan_type="mid_session", reserved_for_owner=8) is False

    def test_owner_scan_can_use_the_reserve(self, monkeypatch):
        nc = self._at(monkeypatch, 12)
        assert nc.check_av_budget(20, scan_type="post_close", reserved_for_owner=8) is True

    def test_owner_scan_still_stops_at_the_full_limit(self, monkeypatch):
        nc = self._at(monkeypatch, 20)
        assert nc.check_av_budget(20, scan_type="post_close", reserved_for_owner=8) is False

    def test_earlier_scans_unaffected_below_the_boundary(self, monkeypatch):
        nc = self._at(monkeypatch, 11)
        assert nc.check_av_budget(20, scan_type="pre_market", reserved_for_owner=8) is True

    def test_no_scan_type_keeps_original_behaviour(self, monkeypatch):
        """Callers that don't know their scan type must not be changed."""
        nc = self._at(monkeypatch, 15)
        assert nc.check_av_budget(20) is True
        assert nc.check_av_budget(20, scan_type=None, reserved_for_owner=8) is True

    def test_zero_reservation_restores_first_come_first_served(self, monkeypatch):
        nc = self._at(monkeypatch, 15)
        assert nc.check_av_budget(20, scan_type="pre_market", reserved_for_owner=0) is True

    def test_reservation_larger_than_limit_does_not_go_negative(self, monkeypatch):
        nc = self._at(monkeypatch, 0)
        assert nc.check_av_budget(5, scan_type="pre_market", reserved_for_owner=99) is False


class TestAlphaVantageThrottleHandling:
    """
    The free tier answers HTTP 200 with {"Information": "...1 request per
    second..."} when called too fast. Before the 2026-08 API audit this was
    logged as "unexpected response structure", NOT retried, and — because the
    call counter incremented on every attempt via on_attempt — still burned one
    of the day's 25. On days with a sector-wide event gate (which fans an AV
    confirmation out to every ticker in the sector) the budget was gone by
    mid-session, entirely on error responses.
    """

    def _fake_response(self, body: dict):
        class _R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return body

        return lambda url, params=None, headers=None, timeout=None: _R()

    def test_information_throttle_returns_empty_and_does_not_count(self, monkeypatch):
        monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "K")
        import shared.api_clients.news_client as nc
        inc = []
        monkeypatch.setattr(nc, "check_av_budget", lambda *a, **k: True)
        monkeypatch.setattr(nc, "increment_av_call_count", lambda: inc.append(1))
        monkeypatch.setattr("shared.api_clients.news_client.time.sleep", lambda *_: None)
        with patch("shared.api_clients._http_backoff.requests.get",
                   side_effect=self._fake_response({"Information": "Please slow down to 1 request per second"})):
            result = fetch_news_alpha_vantage("NVDA")
        assert result == []
        assert inc == []  # throttle must not burn the reservation counter

    def test_note_throttle_also_handled(self, monkeypatch):
        monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "K")
        import shared.api_clients.news_client as nc
        monkeypatch.setattr(nc, "check_av_budget", lambda *a, **k: True)
        monkeypatch.setattr(nc, "increment_av_call_count", lambda: (_ for _ in ()).throw(AssertionError("counted a throttle")))
        monkeypatch.setattr("shared.api_clients.news_client.time.sleep", lambda *_: None)
        with patch("shared.api_clients._http_backoff.requests.get",
                   side_effect=self._fake_response({"Note": "5 calls per minute"})):
            assert fetch_news_alpha_vantage("NVDA") == []

    def test_real_feed_still_counts_and_parses(self, monkeypatch):
        monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "K")
        import shared.api_clients.news_client as nc
        inc = []
        monkeypatch.setattr(nc, "check_av_budget", lambda *a, **k: True)
        monkeypatch.setattr(nc, "increment_av_call_count", lambda: inc.append(1))
        body = {"feed": [{
            "time_published": "20260827T120000", "title": "NVDA rallies", "url": "http://x",
            "source": "Reuters", "overall_sentiment_score": 0.3, "overall_sentiment_label": "Bullish",
            "ticker_sentiment": [{"ticker": "NVDA", "relevance_score": "0.9", "ticker_sentiment_score": "0.4"}],
        }]}
        with patch("shared.api_clients._http_backoff.requests.get", side_effect=self._fake_response(body)):
            result = fetch_news_alpha_vantage("NVDA")
        assert len(result) == 1 and result[0]["title"] == "NVDA rallies"
        assert result[0]["ticker_sentiment"][0]["ticker"] == "NVDA"
        assert inc == [1]  # a real fetch counts exactly once

    def test_budget_exhausted_from_limiter_returns_empty(self, monkeypatch):
        monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "K")
        import shared.api_clients.news_client as nc
        monkeypatch.setattr(nc, "check_av_budget", lambda *a, **k: True)
        monkeypatch.setattr(nc.rate_limiter, "acquire",
                            lambda *a, **k: (_ for _ in ()).throw(nc.rate_limiter.BudgetExhausted("cap")))
        assert fetch_news_alpha_vantage("NVDA") == []

    def test_is_av_throttle_response_helper(self):
        from shared.api_clients.news_client import is_av_throttle_response
        assert is_av_throttle_response({"Information": "x"}) is True
        assert is_av_throttle_response({"Note": "x"}) is True
        assert is_av_throttle_response({"Error Message": "x"}) is True
        assert is_av_throttle_response({"feed": []}) is False
        assert is_av_throttle_response(None) is False
