"""
Tests for shared/api_clients/_http_backoff.py — the shared retry-with-backoff
core that replaced six independently hand-written copies across
market_data_client.py, positioning_client.py, news_client.py,
sec_edgar_client.py, sentiment_client.py, and fundamental_client.py.
"""

from shared.api_clients._http_backoff import (
    DEFAULT_BACKOFF_DELAYS,
    retry_with_backoff,
    http_get_with_backoff,
)


class TestRetryWithBackoff:
    def test_returns_result_on_first_success(self, monkeypatch):
        monkeypatch.setattr("shared.api_clients._http_backoff.time.sleep", lambda s: None)
        result = retry_with_backoff(lambda: "ok")
        assert result == "ok"

    def test_retries_then_succeeds(self, monkeypatch):
        monkeypatch.setattr("shared.api_clients._http_backoff.time.sleep", lambda s: None)
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ValueError("transient")
            return "recovered"

        result = retry_with_backoff(flaky, retries=3)
        assert result == "recovered"
        assert calls["n"] == 3

    def test_all_retries_exhausted_returns_none(self, monkeypatch):
        monkeypatch.setattr("shared.api_clients._http_backoff.time.sleep", lambda s: None)

        def always_fails():
            raise ValueError("permanent")

        result = retry_with_backoff(always_fails, retries=3)
        assert result is None

    def test_sleeps_the_configured_schedule(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr("shared.api_clients._http_backoff.time.sleep", lambda s: sleeps.append(s))

        def always_fails():
            raise ValueError("x")

        retry_with_backoff(always_fails, retries=3, delays=(1, 2, 4))
        assert sleeps == [1, 2]  # 2 sleeps between 3 attempts, no sleep after the last

    def test_extra_retries_beyond_delays_run_with_no_sleep(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr("shared.api_clients._http_backoff.time.sleep", lambda s: sleeps.append(s))
        calls = {"n": 0}

        def always_fails():
            calls["n"] += 1
            raise ValueError("x")

        result = retry_with_backoff(always_fails, retries=5, delays=(1,))
        assert result is None
        assert sleeps == [1]
        assert calls["n"] == 2  # stops once attempt >= len(delays), doesn't burn all 5

    def test_max_total_seconds_stops_early(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr("shared.api_clients._http_backoff.time.sleep", lambda s: sleeps.append(s))
        calls = {"n": 0}

        def always_fails():
            calls["n"] += 1
            raise ValueError("x")

        result = retry_with_backoff(always_fails, retries=3, delays=(30, 60, 120), max_total_seconds=50)
        assert result is None
        assert sleeps == [30]  # 30 alone fits under 50; 30+60=90 would exceed it
        assert calls["n"] == 2  # first attempt, one retry after the 30s sleep, then bail

    def test_should_retry_false_stops_immediately(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr("shared.api_clients._http_backoff.time.sleep", lambda s: sleeps.append(s))
        calls = {"n": 0}

        def always_fails():
            calls["n"] += 1
            raise ValueError("real rejection")

        result = retry_with_backoff(always_fails, retries=3, should_retry=lambda exc: False)
        assert result is None
        assert calls["n"] == 1  # no retry attempted at all
        assert sleeps == []

    def test_should_retry_true_retries_normally(self, monkeypatch):
        monkeypatch.setattr("shared.api_clients._http_backoff.time.sleep", lambda s: None)
        calls = {"n": 0}

        def flaky():
            calls["n"] += 1
            if calls["n"] < 2:
                raise ValueError("transient")
            return "ok"

        result = retry_with_backoff(flaky, retries=3, should_retry=lambda exc: True)
        assert result == "ok"

    def test_redact_applied_to_logged_error_text(self, monkeypatch, caplog):
        monkeypatch.setattr("shared.api_clients._http_backoff.time.sleep", lambda s: None)

        def always_fails():
            raise ValueError("key=SECRET123")

        with caplog.at_level("ERROR"):
            retry_with_backoff(
                always_fails, retries=1,
                redact=lambda text: text.replace("SECRET123", "***REDACTED***"),
            )
        assert "SECRET123" not in caplog.text
        assert "***REDACTED***" in caplog.text

    def test_no_redact_leaves_text_unchanged(self, monkeypatch, caplog):
        monkeypatch.setattr("shared.api_clients._http_backoff.time.sleep", lambda s: None)

        def always_fails():
            raise ValueError("plain error")

        with caplog.at_level("ERROR"):
            retry_with_backoff(always_fails, retries=1)
        assert "plain error" in caplog.text

    def test_default_delays_match_project_schedule(self):
        assert DEFAULT_BACKOFF_DELAYS == (30, 60, 120)

    def test_on_exhausted_fires_with_last_exception_after_natural_exhaustion(self, monkeypatch):
        monkeypatch.setattr("shared.api_clients._http_backoff.time.sleep", lambda s: None)
        seen = []

        def always_fails():
            raise ValueError("final error")

        result = retry_with_backoff(always_fails, retries=2, on_exhausted=lambda exc: seen.append(str(exc)))
        assert result is None
        assert seen == ["final error"]

    def test_on_exhausted_fires_on_max_total_seconds_cap(self, monkeypatch):
        monkeypatch.setattr("shared.api_clients._http_backoff.time.sleep", lambda s: None)
        seen = []

        def always_fails():
            raise ValueError("capped error")

        retry_with_backoff(
            always_fails, retries=3, delays=(30, 60, 120), max_total_seconds=50,
            on_exhausted=lambda exc: seen.append(str(exc)),
        )
        assert seen == ["capped error"]

    def test_on_exhausted_fires_on_should_retry_rejection(self, monkeypatch):
        monkeypatch.setattr("shared.api_clients._http_backoff.time.sleep", lambda s: None)
        seen = []

        def always_fails():
            raise ValueError("rejected")

        retry_with_backoff(
            always_fails, retries=3, should_retry=lambda exc: False,
            on_exhausted=lambda exc: seen.append(str(exc)),
        )
        assert seen == ["rejected"]

    def test_on_exhausted_not_called_on_success(self, monkeypatch):
        monkeypatch.setattr("shared.api_clients._http_backoff.time.sleep", lambda s: None)
        seen = []
        result = retry_with_backoff(lambda: "ok", on_exhausted=lambda exc: seen.append(exc))
        assert result == "ok"
        assert seen == []


class TestHttpGetWithBackoff:
    def test_successful_get_returns_parsed_json(self, monkeypatch):
        class _FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"ok": True}

        def _fake_get(url, params=None, headers=None, timeout=None):
            return _FakeResponse()

        monkeypatch.setattr("shared.api_clients._http_backoff.requests.get", _fake_get)
        result = http_get_with_backoff("https://example.com/api")
        assert result == {"ok": True}

    def test_parse_json_false_returns_raw_response(self, monkeypatch):
        class _FakeResponse:
            text = "<xml>raw</xml>"

            def raise_for_status(self):
                pass

        def _fake_get(url, params=None, headers=None, timeout=None):
            return _FakeResponse()

        monkeypatch.setattr("shared.api_clients._http_backoff.requests.get", _fake_get)
        result = http_get_with_backoff("https://example.com/api", parse_json=False)
        assert result.text == "<xml>raw</xml>"

    def test_passes_through_params_and_headers(self, monkeypatch):
        captured = {}

        class _FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {}

        def _fake_get(url, params=None, headers=None, timeout=None):
            captured["url"] = url
            captured["params"] = params
            captured["headers"] = headers
            captured["timeout"] = timeout
            return _FakeResponse()

        monkeypatch.setattr("shared.api_clients._http_backoff.requests.get", _fake_get)
        http_get_with_backoff(
            "https://example.com/api", params={"q": "1"}, headers={"X-Test": "y"}, timeout=7,
        )
        assert captured["url"] == "https://example.com/api"
        assert captured["params"] == {"q": "1"}
        assert captured["headers"] == {"X-Test": "y"}
        assert captured["timeout"] == 7

    def test_failure_retries_then_returns_none(self, monkeypatch):
        monkeypatch.setattr("shared.api_clients._http_backoff.time.sleep", lambda s: None)

        def _fake_get(url, params=None, headers=None, timeout=None):
            raise ConnectionError("down")

        monkeypatch.setattr("shared.api_clients._http_backoff.requests.get", _fake_get)
        result = http_get_with_backoff("https://example.com/api", retries=2, delays=(1,))
        assert result is None

    def test_should_retry_false_fails_fast_without_retrying(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr("shared.api_clients._http_backoff.time.sleep", lambda s: sleeps.append(s))
        calls = {"n": 0}

        def _fake_get(url, params=None, headers=None, timeout=None):
            calls["n"] += 1
            raise ConnectionError("real rejection")

        monkeypatch.setattr("shared.api_clients._http_backoff.requests.get", _fake_get)
        result = http_get_with_backoff(
            "https://example.com/api", retries=3, should_retry=lambda exc: False,
        )
        assert result is None
        assert calls["n"] == 1
        assert sleeps == []
