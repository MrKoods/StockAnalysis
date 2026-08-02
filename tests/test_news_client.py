"""
Tests for shared/api_clients/news_client.py's pure/testable helper —
_parse_yahoo_news_item. The live fetch_news_yahoo() call itself isn't tested
here (no yfinance mocking convention exists elsewhere in this suite — see
test_positioning_client.py), consistent with the rest of this project's test
style: test the parsing logic against hand-built dicts instead of the live fetch.
"""

from datetime import datetime, timezone

from shared.api_clients.news_client import _parse_yahoo_news_item


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
