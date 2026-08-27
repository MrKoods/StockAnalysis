"""
Tests for run_swing_model._safe_fetch (v2.2.110).

Seven external-feed wrappers each carried their own bare `except Exception`,
which degraded EVERY failure to an empty list. That is right for a feed
outage — one flaky ticker must not kill a 48-ticker scan — and wrong for a
programming fault, which then presents as "the vendor returned nothing".

It cost a real debugging detour the same day: v2.2.108 added kwargs to
_fetch_av_news_safe, a stale test stub raised TypeError on the new signature,
and the wrapper swallowed it into an empty result that read as "AV was simply
not called". Same class as an SEC block reading as "no filings" (v2.2.109) —
a fault indistinguishable from a legitimate empty answer.
"""

import swing_model.run_swing_model as rsm


class TestExpectedFailuresDegradeQuietly:
    """The reason the catch exists: a scan survives one bad feed."""

    def _run(self, monkeypatch, exc):
        entries = []
        monkeypatch.setattr(rsm, "write_validation_entry", lambda t, k, d: entries.append((t, k, d)))

        def boom(_):
            raise exc

        return rsm._safe_fetch("TestFeed", "NVDA", boom, "NVDA"), entries

    def test_network_error_returns_empty_without_validation_entry(self, monkeypatch):
        out, entries = self._run(monkeypatch, OSError("connection reset by peer"))
        assert out == []
        assert entries == []

    def test_bad_json_returns_empty_without_validation_entry(self, monkeypatch):
        out, entries = self._run(monkeypatch, ValueError("Expecting value: line 1 column 1"))
        assert out == []
        assert entries == []

    def test_missing_payload_field_returns_empty(self, monkeypatch):
        out, entries = self._run(monkeypatch, KeyError("messages"))
        assert out == []
        assert entries == []


class TestProgrammingFaultsAreLoud:
    def _run(self, monkeypatch, exc):
        entries = []
        monkeypatch.setattr(rsm, "write_validation_entry", lambda t, k, d: entries.append((t, k, d)))

        def boom(_):
            raise exc

        return rsm._safe_fetch("TestFeed", "NVDA", boom, "NVDA"), entries

    def test_wrong_signature_writes_a_validation_entry(self, monkeypatch):
        """The exact shape that wasted time on 2026-08-26."""
        out, entries = self._run(
            monkeypatch, TypeError("f() got an unexpected keyword argument 'scan_type'")
        )
        assert out == [], "the scan must still survive"
        assert entries == [("NVDA", "fetch_bug", "TestFeed_TypeError")]

    def test_attribute_error_writes_a_validation_entry(self, monkeypatch):
        out, entries = self._run(monkeypatch, AttributeError("'NoneType' has no attribute 'get'"))
        assert entries == [("NVDA", "fetch_bug", "TestFeed_AttributeError")]

    def test_logs_at_error_level(self, monkeypatch, caplog):
        monkeypatch.setattr(rsm, "write_validation_entry", lambda *a: None)

        def boom(_):
            raise TypeError("bad signature")

        with caplog.at_level("ERROR"):
            rsm._safe_fetch("TestFeed", "NVDA", boom, "NVDA")
        assert any(r.levelname == "ERROR" and "UNEXPECTED" in r.message for r in caplog.records)

    def test_reporting_failure_never_breaks_the_scan(self, monkeypatch):
        """If validation logging itself fails, the scan still continues."""
        def explode(*a):
            raise OSError("validation log unwritable")

        monkeypatch.setattr(rsm, "write_validation_entry", explode)

        def boom(_):
            raise TypeError("bad signature")

        assert rsm._safe_fetch("TestFeed", "NVDA", boom, "NVDA") == []


class TestNormalOperation:
    def test_result_passes_through(self):
        assert rsm._safe_fetch("F", "NVDA", lambda t: [{"a": 1}], "NVDA") == [{"a": 1}]

    def test_none_becomes_empty_list(self):
        assert rsm._safe_fetch("F", "NVDA", lambda t: None, "NVDA") == []

    def test_kwargs_are_forwarded(self):
        seen = {}

        def fn(t, scan_type=None, cfg=None):
            seen.update(scan_type=scan_type, cfg=cfg)
            return []

        rsm._safe_fetch("F", "NVDA", fn, "NVDA", scan_type="post_close", cfg={"x": 1})
        assert seen == {"scan_type": "post_close", "cfg": {"x": 1}}
