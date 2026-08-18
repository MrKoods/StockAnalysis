"""
Tests for shared/api_clients/sentiment_client.py — StockTwits + Seeking Alpha
via RapidAPI. Previously had zero dedicated test coverage despite being the
most stateful API client in this package (a per-host circuit breaker, a
per-host rate limiter, a last-known-good engagement cache with TTL, and its
own Cloudflare-bypass User-Agent) — existing tests elsewhere in this suite
only ever monkeypatch fetch_stocktwits/fetch_seeking_alpha_engagement to
return [] wholesale, exercising none of this module's own logic. Also serves
as regression coverage for the migration of _rapidapi_get's retry/GET loop
onto the shared shared/api_clients/_http_backoff.py module (previously its
own hand-written copy) — the circuit breaker and rate limiter stayed local
policy, composed on top of the shared retry mechanics.
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

import shared.api_clients.sentiment_client as sc


@pytest.fixture(autouse=True)
def _reset_module_state(monkeypatch):
    """Circuit breaker / rate limiter state is module-level — isolate tests from each other."""
    sc._consecutive_failures.clear()
    sc._last_call_at.clear()
    monkeypatch.setenv("RAPIDAPI_KEY", "fake-rapidapi-key")
    yield
    sc._consecutive_failures.clear()
    sc._last_call_at.clear()


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Never actually wait for backoff or rate-limit sleeps in tests."""
    monkeypatch.setattr("shared.api_clients._http_backoff.time.sleep", lambda s: None)
    monkeypatch.setattr(sc.time, "sleep", lambda s: None)


def _mock_json_response(data):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = data
    return resp


def _http_error(status_code):
    resp = MagicMock()
    resp.status_code = status_code
    err = requests.exceptions.HTTPError(f"{status_code} error")
    err.response = resp
    return err


# ---------------------------------------------------------------------------
# fetch_stocktwits
# ---------------------------------------------------------------------------

class TestFetchStocktwits:
    def test_missing_api_key_returns_empty(self, monkeypatch):
        monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
        assert sc.fetch_stocktwits("NVDA") == []

    def test_parses_messages_with_sentiment_tag(self):
        raw = {
            "messages": [
                {
                    "id": 1, "created_at": "2026-08-01T12:00:00Z", "body": "Bullish on NVDA",
                    "entities": {"sentiment": {"basic": "Bullish"}},
                    "symbols": [{"symbol": "NVDA", "sentiment_change": 0.1, "volume_change": 0.2}],
                    "likes": {"total": 5},
                },
            ]
        }
        with patch("shared.api_clients._http_backoff.requests.get", return_value=_mock_json_response(raw)):
            result = sc.fetch_stocktwits("NVDA")
        assert len(result) == 1
        assert result[0]["sentiment"] == "bullish"
        assert result[0]["body"] == "Bullish on NVDA"
        assert result[0]["likes"] == 5
        assert result[0]["sentiment_change"] == 0.1

    def test_message_with_no_sentiment_tag_is_none(self):
        raw = {"messages": [{"id": 1, "created_at": "2026-08-01T12:00:00Z", "body": "neutral post", "entities": {}, "symbols": []}]}
        with patch("shared.api_clients._http_backoff.requests.get", return_value=_mock_json_response(raw)):
            result = sc.fetch_stocktwits("NVDA")
        assert result[0]["sentiment"] is None

    def test_malformed_timestamp_falls_back_to_now(self):
        raw = {"messages": [{"id": 1, "created_at": "not-a-date", "body": "x", "entities": {}, "symbols": []}]}
        with patch("shared.api_clients._http_backoff.requests.get", return_value=_mock_json_response(raw)):
            result = sc.fetch_stocktwits("NVDA")
        datetime.fromisoformat(result[0]["timestamp_utc"])  # doesn't raise

    def test_unexpected_response_shape_returns_empty(self):
        with patch("shared.api_clients._http_backoff.requests.get", return_value=_mock_json_response({"messages": "not-a-list"})):
            result = sc.fetch_stocktwits("NVDA")
        assert result == []

    def test_request_failure_returns_empty_not_raises(self):
        with patch("shared.api_clients._http_backoff.requests.get", side_effect=ConnectionError("down")):
            result = sc.fetch_stocktwits("NVDA")
        assert result == []

    def test_respects_limit(self):
        raw = {"messages": [
            {"id": i, "created_at": "2026-08-01T12:00:00Z", "body": f"msg{i}", "entities": {}, "symbols": []}
            for i in range(5)
        ]}
        with patch("shared.api_clients._http_backoff.requests.get", return_value=_mock_json_response(raw)):
            result = sc.fetch_stocktwits("NVDA", limit=2)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# fetch_seeking_alpha_engagement
# ---------------------------------------------------------------------------

class TestFetchSeekingAlphaEngagement:
    def test_missing_api_key_returns_empty(self, monkeypatch):
        monkeypatch.delenv("RAPIDAPI_KEY", raising=False)
        assert sc.fetch_seeking_alpha_engagement("NVDA") == []

    def test_parses_items_and_writes_cache(self, tmp_path, monkeypatch):
        cache_path = tmp_path / "cache.json"
        monkeypatch.setattr(sc, "_ENGAGEMENT_CACHE_PATH", cache_path)
        raw = {"data": [{"id": "a1", "attributes": {"title": "NVDA surges", "commentCount": 12, "publishOn": "2026-08-01T00:00:00Z"}}]}
        with patch("shared.api_clients._http_backoff.requests.get", return_value=_mock_json_response(raw)):
            result = sc.fetch_seeking_alpha_engagement("NVDA")
        assert len(result) == 1
        assert result[0]["comment_count"] == 12
        assert cache_path.exists()

    def test_failure_falls_back_to_cache(self, tmp_path, monkeypatch):
        cache_path = tmp_path / "cache.json"
        monkeypatch.setattr(sc, "_ENGAGEMENT_CACHE_PATH", cache_path)
        cache_path.write_text(json.dumps({
            "NVDA": {"fetched_at": datetime.now(timezone.utc).isoformat(),
                      "items": [{"article_id": "cached1", "comment_count": 3}]}
        }), encoding="utf-8")
        with patch("shared.api_clients._http_backoff.requests.get", side_effect=ConnectionError("down")):
            result = sc.fetch_seeking_alpha_engagement("NVDA")
        assert result == [{"article_id": "cached1", "comment_count": 3}]

    def test_stale_cache_beyond_max_age_not_used(self, tmp_path, monkeypatch):
        cache_path = tmp_path / "cache.json"
        monkeypatch.setattr(sc, "_ENGAGEMENT_CACHE_PATH", cache_path)
        stale_time = datetime.now(timezone.utc) - timedelta(hours=sc._ENGAGEMENT_CACHE_MAX_AGE_HOURS + 1)
        cache_path.write_text(json.dumps({
            "NVDA": {"fetched_at": stale_time.isoformat(), "items": [{"article_id": "old"}]}
        }), encoding="utf-8")
        with patch("shared.api_clients._http_backoff.requests.get", side_effect=ConnectionError("down")):
            result = sc.fetch_seeking_alpha_engagement("NVDA")
        assert result == []

    def test_no_cache_and_failure_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "_ENGAGEMENT_CACHE_PATH", tmp_path / "nonexistent.json")
        with patch("shared.api_clients._http_backoff.requests.get", side_effect=ConnectionError("down")):
            result = sc.fetch_seeking_alpha_engagement("NVDA")
        assert result == []

    def test_unexpected_response_shape_falls_back_to_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sc, "_ENGAGEMENT_CACHE_PATH", tmp_path / "nonexistent.json")
        with patch("shared.api_clients._http_backoff.requests.get", return_value=_mock_json_response({"data": "not-a-list"})):
            result = sc.fetch_seeking_alpha_engagement("NVDA")
        assert result == []


# ---------------------------------------------------------------------------
# _rapidapi_get — retry/GET mechanics (shared/api_clients/_http_backoff.py)
# composed with the circuit breaker / rate limiter policy that stays local.
# ---------------------------------------------------------------------------

class TestRapidapiGetCircuitBreaker:
    def test_success_resets_consecutive_failures(self):
        sc._consecutive_failures["host-a"] = 3
        with patch("shared.api_clients._http_backoff.requests.get", return_value=_mock_json_response({"ok": True})):
            result = sc._rapidapi_get("https://x.test", "host-a", "key")
        assert result == {"ok": True}
        assert sc._consecutive_failures["host-a"] == 0

    def test_non_429_4xx_does_not_retry_or_trip_breaker(self):
        calls = {"n": 0}

        def _side_effect(*a, **k):
            calls["n"] += 1
            raise _http_error(404)

        with patch("shared.api_clients._http_backoff.requests.get", side_effect=_side_effect):
            result = sc._rapidapi_get("https://x.test", "host-b", "key")
        assert result is None
        assert calls["n"] == 1  # fails fast, no retry burned
        assert sc._consecutive_failures.get("host-b", 0) == 0

    def test_429_is_retried_through_full_schedule(self):
        calls = {"n": 0}

        def _side_effect(*a, **k):
            calls["n"] += 1
            raise _http_error(429)

        with patch("shared.api_clients._http_backoff.requests.get", side_effect=_side_effect):
            result = sc._rapidapi_get("https://x.test", "host-c", "key")
        assert result is None
        assert calls["n"] == 3  # unlike a non-429 4xx, 429 gets the full retry schedule

    def test_exhaustion_trips_circuit_breaker(self):
        with patch("shared.api_clients._http_backoff.requests.get", side_effect=ConnectionError("down")):
            sc._rapidapi_get("https://x.test", "host-d", "key")
        assert sc._consecutive_failures["host-d"] == 1

    def test_circuit_open_makes_single_probe_only(self):
        sc._consecutive_failures["host-e"] = sc._CIRCUIT_BREAKER_THRESHOLD
        calls = {"n": 0}

        def _side_effect(*a, **k):
            calls["n"] += 1
            raise ConnectionError("still down")

        with patch("shared.api_clients._http_backoff.requests.get", side_effect=_side_effect):
            result = sc._rapidapi_get("https://x.test", "host-e", "key")
        assert result is None
        assert calls["n"] == 1  # no backoff schedule burned — single fast probe only
        assert sc._consecutive_failures["host-e"] == sc._CIRCUIT_BREAKER_THRESHOLD + 1

    def test_circuit_open_recovers_on_success(self):
        sc._consecutive_failures["host-f"] = sc._CIRCUIT_BREAKER_THRESHOLD
        with patch("shared.api_clients._http_backoff.requests.get", return_value=_mock_json_response({"ok": True})):
            result = sc._rapidapi_get("https://x.test", "host-f", "key")
        assert result == {"ok": True}
        assert sc._consecutive_failures["host-f"] == 0

    def test_circuit_open_bool(self):
        assert sc._circuit_open("host-fresh") is False
        sc._consecutive_failures["host-fresh"] = sc._CIRCUIT_BREAKER_THRESHOLD
        assert sc._circuit_open("host-fresh") is True


# ---------------------------------------------------------------------------
# _wait_for_rate_limit
# ---------------------------------------------------------------------------

class TestRateLimiter:
    def test_first_call_for_a_host_never_waits(self, monkeypatch):
        # A mocked clock starting near 0.0 would make "first call ever"
        # indistinguishable from "a call 0 seconds ago" (both look like
        # elapsed=0 against _last_call_at.get(host, 0.0)'s default) — real
        # time.monotonic() never actually starts at 0 (it's a large
        # system-uptime-based value), so the mocked clock starts far from
        # zero here to match real behavior.
        monkeypatch.setattr(sc.time, "monotonic", lambda: 10_000.0)
        sleeps = []
        monkeypatch.setattr(sc.time, "sleep", lambda s: sleeps.append(s))
        sc._wait_for_rate_limit("host-g")
        assert sleeps == []

    def test_waits_remaining_time_when_called_too_soon(self, monkeypatch):
        clock = {"t": 10_000.0}
        monkeypatch.setattr(sc.time, "monotonic", lambda: clock["t"])
        sleeps = []
        monkeypatch.setattr(sc.time, "sleep", lambda s: sleeps.append(s))

        sc._wait_for_rate_limit("host-g2")  # records t=10000.0 as last call
        clock["t"] = 10_000.5  # only 0.5s later
        sc._wait_for_rate_limit("host-g2")
        assert sleeps == [pytest.approx(sc._MIN_SECONDS_BETWEEN_CALLS - 0.5)]

    def test_no_wait_once_enough_time_has_elapsed(self, monkeypatch):
        clock = {"t": 10_000.0}
        monkeypatch.setattr(sc.time, "monotonic", lambda: clock["t"])
        sleeps = []
        monkeypatch.setattr(sc.time, "sleep", lambda s: sleeps.append(s))

        sc._wait_for_rate_limit("host-h")
        clock["t"] = 10_000.0 + sc._MIN_SECONDS_BETWEEN_CALLS + 1.0
        sc._wait_for_rate_limit("host-h")
        assert sleeps == []

    def test_hosts_tracked_independently(self, monkeypatch):
        clock = {"t": 10_000.0}
        monkeypatch.setattr(sc.time, "monotonic", lambda: clock["t"])
        sleeps = []
        monkeypatch.setattr(sc.time, "sleep", lambda s: sleeps.append(s))

        sc._wait_for_rate_limit("host-i")
        clock["t"] = 10_000.1
        sc._wait_for_rate_limit("host-j")  # different host, no prior call for THIS host
        assert sleeps == []
