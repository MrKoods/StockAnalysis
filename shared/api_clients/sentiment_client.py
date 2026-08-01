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

logger = get_logger(__name__)

_STOCKTWITS_HOST = "stocktwits.p.rapidapi.com"
_SEEKING_ALPHA_HOST = "seeking-alpha-finance.p.rapidapi.com"
_BACKOFF_DELAYS = [30, 60, 120]

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

    This is a proxy, not true community sentiment — this RapidAPI subscription's
    Instablogs endpoints only support single-post lookup by numeric ID (no
    ticker-searchable community-blog feed), so commentCount velocity on
    editorial news is used instead as a weaker retail-engagement signal.

    Returns list of dicts:
    {article_id, timestamp_utc, title, comment_count}
    Returns [] if RAPIDAPI_KEY is not configured or the request fails.
    """
    api_key = os.environ.get("RAPIDAPI_KEY", "")
    if not api_key:
        logger.warning("RAPIDAPI_KEY not set — Seeking Alpha engagement unavailable.")
        return []

    url = f"https://{_SEEKING_ALPHA_HOST}/v1/symbols/news"
    params = {"ticker_slug": ticker, "page_number": 1, "category": "all"}
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
    backoff (30s -> 60s -> 120s). 4xx client errors (except 429) are not
    retried. Returns parsed JSON or None.
    """
    # StockTwits' backend fronts this RapidAPI endpoint with Cloudflare bot
    # protection that blocks the default python-requests User-Agent (403 +
    # "Just a moment..." challenge page) — a browser/curl-like UA passes.
    headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": host, "User-Agent": "curl/8.4.0"}
    delays = _BACKOFF_DELAYS
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if 400 <= status < 500 and status != 429:
                logger.warning(f"RapidAPI request rejected with HTTP {status} (no retry): {exc}")
                return None
            if attempt < len(delays):
                logger.warning(f"RapidAPI request failed (attempt {attempt + 1}): {exc}. Retry in {delays[attempt]}s.")
                time.sleep(delays[attempt])
        except Exception as exc:
            if attempt < len(delays):
                logger.warning(f"RapidAPI request failed (attempt {attempt + 1}): {exc}. Retry in {delays[attempt]}s.")
                time.sleep(delays[attempt])
    logger.error(f"All retries exhausted for {url}")
    return None
