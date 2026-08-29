"""Tests for shared/api_clients/cache.py — the cross-process on-disk response cache."""

import time

import pandas as pd

from shared.api_clients import cache


def test_miss_then_hit():
    calls = []

    def fetch():
        calls.append(1)
        return {"a": 1}

    r1 = cache.cached_call("ns", "k", ttl=100, fetch_fn=fetch)
    r2 = cache.cached_call("ns", "k", ttl=100, fetch_fn=fetch)
    assert r1 == r2 == {"a": 1}
    assert len(calls) == 1  # second call served from cache


def test_expiry_refetches():
    calls = []

    def fetch():
        calls.append(1)
        return len(calls)

    assert cache.cached_call("ns", "k", ttl=0.05, fetch_fn=fetch) == 1
    time.sleep(0.08)
    assert cache.cached_call("ns", "k", ttl=0.05, fetch_fn=fetch) == 2


def test_falsy_result_not_cached_by_default():
    calls = []

    def fetch():
        calls.append(1)
        return []

    cache.cached_call("ns", "empty", ttl=100, fetch_fn=fetch)
    cache.cached_call("ns", "empty", ttl=100, fetch_fn=fetch)
    assert len(calls) == 2  # empty result re-fetched, not pinned


def test_store_falsy_true_caches_empty():
    calls = []

    def fetch():
        calls.append(1)
        return []

    cache.cached_call("ns", "empty", ttl=100, fetch_fn=fetch, store_falsy=True)
    cache.cached_call("ns", "empty", ttl=100, fetch_fn=fetch, store_falsy=True)
    assert len(calls) == 1


def test_pickle_format_roundtrips_dataframe():
    df = pd.DataFrame({"Close": [1.0, 2.0, 3.0]})

    def fetch():
        return df

    cache.cached_call("ohlcv", "NVDA", ttl=100, fetch_fn=fetch, format="pickle")
    got = cache.cached_call("ohlcv", "NVDA", ttl=100, fetch_fn=lambda: None, format="pickle")
    pd.testing.assert_frame_equal(got, df)


def test_get_returns_none_past_ttl():
    cache.put("ns", "k", {"x": 1})
    val, age = cache.get("ns", "k", ttl=100)
    assert val == {"x": 1} and age is not None
    val, age = cache.get("ns", "k", ttl=-1)
    assert val is None and age is None


def test_unreadable_entry_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_CACHE_DIR", tmp_path)
    p = tmp_path / "ns" / "k.json"
    p.parent.mkdir(parents=True)
    p.write_text("{ this is not json", encoding="utf-8")
    val, age = cache.get("ns", "k", ttl=100)
    assert val is None


def test_key_sanitisation():
    cache.put("ns", "a/b:c?d", {"ok": True})
    val, _ = cache.get("ns", "a/b:c?d", ttl=100)
    assert val == {"ok": True}


def test_clear_namespace():
    cache.put("ns1", "k", 1)
    cache.put("ns2", "k", 2)
    cache.clear("ns1")
    assert cache.get("ns1", "k", ttl=100)[0] is None
    assert cache.get("ns2", "k", ttl=100)[0] == 2
