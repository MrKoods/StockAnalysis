"""Tests for shared/api_clients/rate_limiter.py — the cross-process pacing/cap gate."""

import time

import pytest

from shared.api_clients import rate_limiter as rl


@pytest.fixture(autouse=True)
def _fast_limits(monkeypatch):
    """Shrink the real intervals so tests aren't slow; keep one capped host."""
    monkeypatch.setattr(rl, "DEFAULT_LIMITS", {
        "fast.test":    {"min_interval": 0.05, "daily_cap": None},
        "capped.test":  {"min_interval": 0.0, "daily_cap": 3},
    })


def test_host_for_url():
    assert rl.host_for_url("https://www.alphavantage.co/query?function=X") == "www.alphavantage.co"
    assert rl.host_for_url("data.sec.gov") == "data.sec.gov"


def test_acquire_paces_calls():
    t0 = time.time()
    for _ in range(4):
        rl.acquire("fast.test")
    elapsed = time.time() - t0
    # 4 calls at 0.05s min interval => at least 3 gaps ~= 0.15s (first is free).
    assert elapsed >= 0.12


def test_acquire_first_call_is_immediate():
    t0 = time.time()
    rl.acquire("fast.test")
    assert time.time() - t0 < 0.04


def test_daily_cap_raises_budget_exhausted():
    for _ in range(3):
        rl.acquire("capped.test")
    with pytest.raises(rl.BudgetExhausted):
        rl.acquire("capped.test")


def test_usage_reports_count_and_remaining():
    rl.acquire("capped.test")
    rl.acquire("capped.test")
    u = rl.usage("capped.test")
    assert u["count"] == 2
    assert u["daily_cap"] == 3
    assert u["remaining"] == 1


def test_unknown_host_uses_fallback_and_does_not_raise():
    rl.acquire("something.unknown")
    rl.acquire("something.unknown")
    assert rl.usage("something.unknown")["daily_cap"] is None


def test_cap_counter_resets_across_utc_day(monkeypatch):
    import shared.api_clients.rate_limiter as mod
    real_dt = mod.datetime

    class _FrozenDay:
        day = "2026-01-01"

        @classmethod
        def now(cls, tz=None):
            d = real_dt.now(tz)
            return d.replace(year=2026, month=1, day=int(cls.day[-2:]))

    monkeypatch.setattr(mod, "datetime", _FrozenDay)
    for _ in range(3):
        rl.acquire("capped.test")
    with pytest.raises(rl.BudgetExhausted):
        rl.acquire("capped.test")

    _FrozenDay.day = "2026-01-02"  # next day
    rl.acquire("capped.test")  # counter should have reset
    assert rl.usage("capped.test")["count"] == 1


def test_note_remaining_only_warns_when_window_nearly_spent(caplog):
    """Finnhub's X-Ratelimit-Remaining is a per-minute window that resets to 60
    each minute, so a mid-range value is normal and must not warn (it fired
    ~30x/scan before). Only a near-zero value is worth a line."""
    import logging

    with caplog.at_level(logging.WARNING):
        rl.note_remaining("finnhub.io", 45)
        rl.note_remaining("finnhub.io", 10)
        rl.note_remaining("finnhub.io", None)
    assert caplog.records == []

    with caplog.at_level(logging.WARNING):
        rl.note_remaining("finnhub.io", 1)
    assert any("calls left in the current window" in r.message for r in caplog.records)


def test_locking_failure_degrades_open(monkeypatch):
    """A broken lock must not block a scan — acquire logs and lets the call through."""
    import shared.api_clients.rate_limiter as mod

    def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(mod, "exclusive_lock", _boom)
    rl.acquire("fast.test")  # must not raise
