"""
SHARED: Wraps StockTwits (real-time crowd Bullish/Bearish tagged messages) and
Seeking Alpha Finance (comment-count engagement proxy), both via RapidAPI.

Replaces the earlier Reddit/PRAW-based sentiment source: StockTwits messages
carry an explicit `entities.sentiment.basic` tag ("Bullish"/"Bearish") rather
than requiring keyword/NLP inference over free text, which simplifies scoring
considerably versus the original Reddit design.

Both clients share a single RAPIDAPI_KEY env var, distinguished by the
x-rapidapi-host header per request. All timestamps normalized to UTC.
Implements exponential backoff. Never raises — returns [] on any failure so
the sentiment layer can fall back to its offline/degraded-scoring path.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from shared.utils.atomic_io import atomic_write_json
from shared.utils.logger import get_logger
from shared.api_clients._http_backoff import http_get_with_backoff, DEFAULT_BACKOFF_DELAYS

logger = get_logger(__name__)

_STOCKTWITS_HOST = "stocktwits.p.rapidapi.com"
# Switched 2026-08-06 from tipsters/seeking-alpha-finance to apidojo/seeking-alpha:
# the account's Pro plan (10,000/month) was subscribed on apidojo's listing, not
# tipsters' — different RapidAPI publishers, different hosts, different quotas,
# despite the near-identical product name. tipsters' subscription was still on its
# original Basic/500 plan, which is what was causing every scan to 429 all day.
_SEEKING_ALPHA_HOST = "seeking-alpha.p.rapidapi.com"

# The live scan loop (run_swing_model.py, paper_runner.py) calls fetch_stocktwits
# and fetch_seeking_alpha_engagement once per ticker in a tight loop with no
# delay between tickers — confirmed live (2026-08-03) to 429 Seeking Alpha for
# 6 consecutive tickers, each burning the full 30s->60s->120s backoff before
# giving up (~25 min of a scan spent retrying). Paced per-host, independently,
# since StockTwits and Seeking Alpha are separate RapidAPI subscriptions with
# presumably separate quotas — StockTwits had zero failures in that same test.
_MIN_SECONDS_BETWEEN_CALLS = 2.0
_last_call_at: dict[str, float] = {}


def _wait_for_rate_limit(host: str) -> None:
    elapsed = time.monotonic() - _last_call_at.get(host, 0.0)
    remaining = _MIN_SECONDS_BETWEEN_CALLS - elapsed
    if remaining > 0:
        time.sleep(remaining)
    _last_call_at[host] = time.monotonic()

# Per-host circuit breaker: confirmed live (2026-08-06) that once a RapidAPI
# host starts 429ing, it 429s for every remaining ticker in the scan too —
# not a one-off blip. Paying the full 30s->60s->120s backoff per ticker on a
# host that's already proven dead this run turned a ~20min scan into ~90min
# for zero benefit (falls back to cache either way). After one full retry
# exhaustion, skip the retries for the rest of this process — one fast
# no-backoff attempt per call, so the host can still be used the moment it
# recovers, without re-paying the 210s tax each time.
_CIRCUIT_BREAKER_THRESHOLD = 1
_consecutive_failures: dict[str, int] = {}


def _circuit_open(host: str) -> bool:
    return _consecutive_failures.get(host, 0) >= _CIRCUIT_BREAKER_THRESHOLD

# Last-known-good cache for Seeking Alpha engagement items, keyed by ticker.
# A transient RapidAPI outage (observed live: repeated "All retries exhausted"
# across multiple tickers on the same day) used to make _score_engagement()
# hard-zero that sub-signal for every ticker scanned while the API was down,
# capping total sentiment at 12/15 for reasons unrelated to the stock. Falling
# back to the most recent successful fetch (within _ENGAGEMENT_CACHE_MAX_AGE_HOURS)
# instead of an empty list keeps that sub-signal informative through a short outage.
_ENGAGEMENT_CACHE_PATH = Path("data/processed/sentiment_engagement_cache.json")
_ENGAGEMENT_CACHE_MAX_AGE_HOURS = 48


def fetch_stocktwits(ticker: str, limit: int = 30) -> list[dict]:
    """
    Fetch recent StockTwits messages for a ticker.

    Returns list of dicts:
    {
        message_id, timestamp_utc, body, sentiment ('bullish' | 'bearish' | None),
        sentiment_change, volume_change, likes
    }
    sentiment is read directly from StockTwits' entities.sentiment.basic tag —
    no keyword inference needed (unlike the old Reddit-based classifier).
    Returns [] if RAPIDAPI_KEY is not configured or the request fails.
    """
    api_key = os.environ.get("RAPIDAPI_KEY", "")
    if not api_key:
        logger.warning("RAPIDAPI_KEY not set — StockTwits sentiment unavailable.")
        return []

    url = f"https://{_STOCKTWITS_HOST}/streams/symbol/{ticker}.json"
    data = _rapidapi_get(url, _STOCKTWITS_HOST, api_key)
    if data is None:
        return []

    raw_messages = data.get("messages", [])
    if not isinstance(raw_messages, list):
        logger.warning(f"StockTwits: unexpected response shape for {ticker}: {list(data.keys())}")
        return []

    messages = []
    for item in raw_messages[:limit]:
        ts_raw = item.get("created_at", "")
        try:
            ts = datetime.strptime(ts_raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            ts = datetime.now(timezone.utc)

        entities = item.get("entities") or {}
        sentiment_obj = entities.get("sentiment") or {}
        basic = sentiment_obj.get("basic")
        sentiment = basic.lower() if isinstance(basic, str) else None

        symbol_data = {}
        for sym in item.get("symbols", []):
            if sym.get("symbol") == ticker:
                symbol_data = sym
                break

        messages.append({
            "message_id": item.get("id"),
            "timestamp_utc": ts.isoformat(),
            "body": item.get("body", ""),
            "sentiment": sentiment,
            "sentiment_change": symbol_data.get("sentiment_change"),
            "volume_change": symbol_data.get("volume_change"),
            "likes": (item.get("likes") or {}).get("total", 0),
        })

    logger.info(f"StockTwits: fetched {len(messages)} messages for {ticker}.")
    return messages


def fetch_seeking_alpha_engagement(ticker: str, limit: int = 10) -> list[dict]:
    """
    Fetch recent Seeking Alpha editorial news items for a ticker and surface
    each item's commentCount as an engagement-velocity proxy.

    This is a proxy, not true community sentiment — apidojo's `news/v2/list-by-symbol`
    is a ticker-scoped editorial news feed (not a community-blog feed), so
    commentCount velocity on editorial news is used instead as a weaker
    retail-engagement signal.

    Returns list of dicts:
    {article_id, timestamp_utc, title, comment_count}
    Returns [] if RAPIDAPI_KEY is not configured or the request fails.
    """
    api_key = os.environ.get("RAPIDAPI_KEY", "")
    if not api_key:
        logger.warning("RAPIDAPI_KEY not set — Seeking Alpha engagement unavailable.")
        return []

    url = f"https://{_SEEKING_ALPHA_HOST}/news/v2/list-by-symbol"
    params = {"id": ticker.lower(), "size": limit, "number": 1}
    data = _rapidapi_get(url, _SEEKING_ALPHA_HOST, api_key, params=params)
    if data is None:
        return _load_cached_engagement(ticker)

    raw_items = data.get("data", [])
    if not isinstance(raw_items, list):
        logger.warning(f"Seeking Alpha: unexpected response shape for {ticker}: {list(data.keys())}")
        return _load_cached_engagement(ticker)

    items = []
    for item in raw_items[:limit]:
        attrs = item.get("attributes") or {}
        ts_raw = attrs.get("publishOn", "")
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")) if ts_raw else datetime.now(timezone.utc)
        except ValueError:
            ts = datetime.now(timezone.utc)

        items.append({
            "article_id": item.get("id", ts_raw),
            "timestamp_utc": ts.isoformat(),
            "title": attrs.get("title", ""),
            "comment_count": attrs.get("commentCount", 0),
        })

    logger.info(f"Seeking Alpha: fetched {len(items)} engagement items for {ticker}.")
    if items:
        _save_cached_engagement(ticker, items)
        return items
    return _load_cached_engagement(ticker)


def _load_cached_engagement(ticker: str) -> list[dict]:
    """
    Return the last successful Seeking Alpha engagement fetch for `ticker` if
    it's within _ENGAGEMENT_CACHE_MAX_AGE_HOURS, else []. Never raises — a
    missing/corrupt cache file just means no fallback is available.
    """
    try:
        if not _ENGAGEMENT_CACHE_PATH.exists():
            return []
        cache = json.loads(_ENGAGEMENT_CACHE_PATH.read_text(encoding="utf-8"))
        entry = cache.get(ticker)
        if not entry:
            return []
        fetched_at = datetime.fromisoformat(entry["fetched_at"])
        age_hours = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600.0
        if age_hours > _ENGAGEMENT_CACHE_MAX_AGE_HOURS:
            return []
        logger.warning(
            f"Seeking Alpha: live fetch unavailable for {ticker} — using cached "
            f"engagement data from {age_hours:.1f}h ago."
        )
        return entry.get("items", [])
    except Exception as exc:
        logger.warning(f"Seeking Alpha: failed to read engagement cache for {ticker}: {exc}")
        return []


def _save_cached_engagement(ticker: str, items: list[dict]) -> None:
    """Persist the latest successful engagement fetch for `ticker`, keyed alongside other tickers."""
    try:
        cache = {}
        if _ENGAGEMENT_CACHE_PATH.exists():
            try:
                cache = json.loads(_ENGAGEMENT_CACHE_PATH.read_text(encoding="utf-8"))
            except Exception:
                cache = {}
        cache[ticker] = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "items": items,
        }
        atomic_write_json(_ENGAGEMENT_CACHE_PATH, cache)
    except Exception as exc:
        logger.warning(f"Seeking Alpha: failed to write engagement cache for {ticker}: {exc}")


def _rapidapi_get(url: str, host: str, api_key: str, params: Optional[dict] = None, retries: int = 3) -> Optional[dict]:
    """
    GET a RapidAPI endpoint with the required auth headers and exponential
    backoff (30s -> 60s -> 120s, via shared/api_clients/_http_backoff.py).
    4xx client errors (except 429) are not retried. Returns parsed JSON or None.

    If this host has already exhausted its retries once this process (circuit
    open — see _CIRCUIT_BREAKER_THRESHOLD), skips the backoff and makes a
    single fast probe instead: the host has proven dead for the rest of this
    scan often enough that paying 210s/ticker to confirm it again isn't worth
    it, but a single cheap attempt still lets it recover mid-run if it comes
    back. Rate limiting (_wait_for_rate_limit) and the circuit breaker itself
    are RapidAPI-specific policy that stays local — only the generic
    retry/GET mechanics are shared with the other API clients.
    """
    # StockTwits' backend fronts this RapidAPI endpoint with Cloudflare bot
    # protection that blocks the default python-requests User-Agent (403 +
    # "Just a moment..." challenge page) — a browser/curl-like UA passes.
    headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": host, "User-Agent": "curl/8.4.0"}
    circuit_open = _circuit_open(host)
    delays = () if circuit_open else DEFAULT_BACKOFF_DELAYS
    attempts = 1 if circuit_open else retries
    _wait_for_rate_limit(host)

    # A definitive rejection (4xx that isn't 429) must NOT trip the circuit
    # breaker the same way a genuine exhaustion does — it's not evidence the
    # host is down, just that this particular request was rejected. Tracked
    # via closure so the code after the call can tell the two apart from a
    # bare None return, which doesn't carry that distinction on its own.
    rejected = False

    def _should_retry(exc: BaseException) -> bool:
        nonlocal rejected
        if isinstance(exc, requests.exceptions.HTTPError):
            status = exc.response.status_code if exc.response is not None else 0
            if 400 <= status < 500 and status != 429:
                logger.warning(f"RapidAPI request rejected with HTTP {status} (no retry): {exc}")
                rejected = True
                return False
        return True

    label = f"RapidAPI {host}" + (" (circuit open, single probe)" if circuit_open else "")
    result = http_get_with_backoff(
        url, params=params, headers=headers, retries=attempts, delays=delays,
        label=label, should_retry=_should_retry,
    )

    if result is not None:
        _consecutive_failures[host] = 0
    elif not rejected:
        _consecutive_failures[host] = _consecutive_failures.get(host, 0) + 1

    return result
