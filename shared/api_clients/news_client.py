"""
SHARED: Wraps Alpha Vantage News & Sentiment + Yahoo Finance + Finnhub headlines.
Produces timestamped articles; Alpha Vantage articles carry pre-computed sentiment
scores, Yahoo and Finnhub articles do not (NER-based sentiment applied downstream
by news_layer.py for those).
Enforces the 20-call/day Alpha Vantage budget (tracked in data/processed/av_call_count.json).
All timestamps normalized to UTC. Implements exponential backoff.
"""

import os
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yfinance as yf

from shared.utils.logger import get_logger
from shared.utils.atomic_io import atomic_write_json, exclusive_lock
from shared.api_clients._http_backoff import http_get_with_backoff
from shared.api_clients import rate_limiter

logger = get_logger(__name__)

_AV_BASE_URL = "https://www.alphavantage.co/query"
_AV_COUNTER_FILE = Path("data/processed/av_call_count.json")
_AV_COUNTER_LOCK_FILE = Path("data/processed/av_call_count.json.lock")
_FINNHUB_BASE_URL = "https://finnhub.io/api/v1"


def fetch_news_alpha_vantage(
    ticker: str,
    time_from: Optional[str] = None,
    limit: int = 10,
    scan_type: Optional[str] = None,
    cfg: Optional[dict] = None,
) -> list[dict]:
    """
    Fetch news and sentiment from Alpha Vantage NEWS_SENTIMENT endpoint.
    Enforces the configured daily budget, with a share reserved for the
    post_close scan (see check_av_budget). Returns [] if exhausted.

    Returns list of dicts:
    {
        article_id, timestamp_utc, title, url, source, source_domain,
        overall_sentiment_score, overall_sentiment_label,
        ticker_sentiment: list[{ticker, relevance_score, sentiment_score, sentiment_label}]
    }
    """
    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
    if not api_key:
        logger.warning("ALPHA_VANTAGE_API_KEY not set — AV news unavailable.")
        return []

    av_cfg = (cfg or {}).get("alpha_vantage", {})
    daily_limit = int(av_cfg.get("daily_limit", 20))
    reserved = int(av_cfg.get("reserve_for_owner_scan", 0))
    if not check_av_budget(daily_limit, scan_type=scan_type, reserved_for_owner=reserved):
        held = (
            f" ({reserved} of {daily_limit} held for the {AV_OWNER_SCAN_TYPE} scan)"
            if scan_type is not None and scan_type != AV_OWNER_SCAN_TYPE and reserved > 0
            else ""
        )
        logger.warning(
            f"Alpha Vantage budget exhausted for today{held} — skipping news fetch for {ticker}."
        )
        return []

    # Cross-process pacing + hard daily cap. AV's free tier throttles above
    # ~1 req/s (HTTP 200 + {"Information": ...}) and allows 25/day; the limiter
    # enforces both across the 3 daily scan processes.
    try:
        rate_limiter.acquire("alphavantage.co")
    except rate_limiter.BudgetExhausted as exc:
        logger.warning(f"AV news: {exc} — skipping news fetch for {ticker}.")
        return []

    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": ticker,
        "apikey": api_key,
        "limit": limit,
    }
    if time_from:
        params["time_from"] = time_from

    data = _av_get_with_throttle_retry(params, ticker)
    if data is None:
        return []

    # Only a call that actually returned articles counts against the per-scan
    # reservation counter (av_call_count.json). A throttle response (handled in
    # _av_get_with_throttle_retry) returns nothing and must not burn the
    # post_close scan's reserved share — the previous on_attempt increment
    # counted every attempt, throttled or not, which is exactly why gated days
    # exhausted the budget on error responses (2026-08 API audit).
    increment_av_call_count()

    articles = []
    for item in data.get("feed", []):
        ts_raw = item.get("time_published", "")
        try:
            # AV format: "20240115T143022"
            ts = datetime.strptime(ts_raw, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            ts = datetime.now(timezone.utc)

        source = item.get("source", "")
        articles.append({
            "article_id": item.get("url", ts_raw),
            "timestamp_utc": ts.isoformat(),
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "source": source,
            "source_domain": item.get("source_domain", source.lower().replace(" ", "") + ".com"),
            "overall_sentiment_score": float(item.get("overall_sentiment_score", 0.0)),
            "overall_sentiment_label": item.get("overall_sentiment_label", "Neutral"),
            "ticker_sentiment": item.get("ticker_sentiment", []),
        })

    logger.info(f"AV news: fetched {len(articles)} articles for {ticker}.")
    return articles


# Keys Alpha Vantage puts a soft-failure message under, always with HTTP 200:
#  - "Information": the free-tier "spread your requests out (1/sec)" throttle,
#     and the "premium endpoint" upsell
#  - "Note":        the older "5 calls/minute" throttle message
#  - "Error Message": a genuine bad request (unknown function, bad symbol)
_AV_SOFT_FAILURE_KEYS = ("Information", "Note", "Error Message")


def is_av_throttle_response(data: Optional[dict]) -> bool:
    """True if an Alpha Vantage JSON body is a throttle/soft-failure, not real data."""
    return isinstance(data, dict) and any(k in data for k in _AV_SOFT_FAILURE_KEYS)


def _av_get_with_throttle_retry(
    params: dict, ticker: str, max_throttle_retries: int = 1,
) -> Optional[dict]:
    """
    GET the AV query endpoint, treating a {"Information"|"Note"|"Error Message"}
    body as a throttle rather than data: log it, wait, re-pace, retry once, then
    give up returning None. A None here never counts against the daily budget.
    """
    for attempt in range(max_throttle_retries + 1):
        data = http_get_with_backoff(
            _AV_BASE_URL, params=params,
            redact=lambda text: _redact_secrets(text, params),
            label="fetch_news_alpha_vantage",
        )
        if data is None:
            return None
        if is_av_throttle_response(data):
            msg = next((data[k] for k in _AV_SOFT_FAILURE_KEYS if k in data), "")
            logger.warning(
                f"AV: throttled/soft-failed for {ticker} "
                f"({str(msg)[:110]}) — not counted against budget"
            )
            if attempt < max_throttle_retries:
                time.sleep(2.5)
                try:
                    rate_limiter.acquire("alphavantage.co")
                except rate_limiter.BudgetExhausted:
                    return None
                continue
            return None
        if "feed" not in data:
            logger.warning(
                f"AV news: unexpected response structure for {ticker}: {list(data.keys())}"
            )
            return None
        return data
    return None


def _parse_yahoo_news_item(item: dict) -> dict:
    """
    Parse one raw item from yf.Ticker(ticker).news into this client's article shape.

    yfinance's news response nests the real content under item["content"]
    (title, pubDate, provider.displayName, canonicalUrl.url) — item["title"] etc.
    at the top level are always absent under this shape. Every article was
    silently carrying title="" before this was handled (confirmed live:
    is_ticker_relevant can never match an empty string, so no Yahoo article ever
    counted toward News regardless of any alias list — this starved every ticker's
    News score, worst for tickers with thin Finnhub coverage as their only other
    free source, e.g. regional banks). Falls back to the old flat top-level fields
    when "content" isn't present, in case yfinance reverts or an older cached
    client version returns the pre-change shape.
    """
    content = item.get("content") or {}
    title = content.get("title") or item.get("title", "")
    pub_date = content.get("pubDate") or content.get("displayTime")
    link = (content.get("canonicalUrl") or {}).get("url") or item.get("link", "")
    publisher = (content.get("provider") or {}).get("displayName") or item.get("publisher", "Yahoo Finance")

    if pub_date:
        try:
            ts = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            ts = datetime.now(timezone.utc)
    else:
        # yfinance returns Unix timestamp under the old flat shape
        ts_raw = item.get("providerPublishTime") or item.get("publishedAt")
        ts = datetime.fromtimestamp(float(ts_raw), tz=timezone.utc) if ts_raw else datetime.now(timezone.utc)

    return {
        "article_id": content.get("id") or item.get("uuid") or link,
        "timestamp_utc": ts.isoformat(),
        "title": title,
        "link": link,
        "publisher": publisher,
        "source_domain": "finance.yahoo.com",
        "overall_sentiment_score": None,
        "overall_sentiment_label": None,
        "ticker_sentiment": [],
    }


def fetch_news_yahoo(ticker: str, limit: int = 10) -> list[dict]:
    """
    Fetch Yahoo Finance headlines via yfinance as secondary/fallback news source.

    Returns list of dicts:
    {article_id, timestamp_utc, title, link, publisher}
    No pre-computed sentiment scores — NER applied downstream.

    Cached ~4h (cache.TTL["news"]) so the noon scan reuses the pre-market pull
    and only pre-market + post-close actually hit yfinance for news.
    """
    def _fetch():
        try:
            rate_limiter.acquire("yfinance")
            info = yf.Ticker(ticker).news
            if not info:
                logger.info(f"Yahoo Finance: no news for {ticker}.")
                return []
            articles = [_parse_yahoo_news_item(item) for item in info[:limit]]
            logger.info(f"Yahoo Finance: fetched {len(articles)} articles for {ticker}.")
            return articles
        except Exception as exc:
            logger.error(f"Yahoo Finance news fetch failed for {ticker}: {exc}")
            return []

    from shared.api_clients import cache
    return cache.cached_call("news", f"yahoo_{ticker}_{limit}", cache.TTL["news"], _fetch)


def fetch_news_finnhub(ticker: str, lookback_days: int = 7) -> list[dict]:
    """
    Fetch company news headlines from Finnhub's free-tier /company-news endpoint.

    Returns list of dicts (same shape as fetch_news_yahoo):
    {article_id, timestamp_utc, title, url, source, source_domain}
    No pre-computed sentiment scores — NER applied downstream.
    """
    api_key = os.environ.get("FINNHUB_API_KEY", "")
    if not api_key:
        logger.warning("FINNHUB_API_KEY not set — Finnhub news unavailable.")
        return []

    from shared.api_clients import cache
    parsed = cache.cached_call(
        "news", f"finnhub_{ticker}_{lookback_days}", cache.TTL["news"],
        lambda: _fetch_news_finnhub_uncached(ticker, lookback_days, api_key),
    )
    return parsed


def _fetch_news_finnhub_uncached(ticker: str, lookback_days: int, api_key: str) -> list[dict]:
    to_date = datetime.now(timezone.utc).date()
    from_date = to_date - timedelta(days=lookback_days)
    params = {
        "symbol": ticker,
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "token": api_key,
    }

    rate_limiter.acquire("finnhub.io")
    data = http_get_with_backoff(
        f"{_FINNHUB_BASE_URL}/company-news", params=params,
        redact=lambda text: _redact_secrets(text, params),
        label="fetch_news_finnhub",
    )
    if not isinstance(data, list):
        logger.warning(f"Finnhub news: unexpected response for {ticker}: {data}")
        return []

    articles = []
    for item in data:
        ts_raw = item.get("datetime", 0)
        try:
            ts = datetime.fromtimestamp(float(ts_raw), tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            ts = datetime.now(timezone.utc)

        source = item.get("source", "")
        articles.append({
            "article_id": str(item.get("id") or item.get("url", ts_raw)),
            "timestamp_utc": ts.isoformat(),
            "title": item.get("headline", ""),
            "url": item.get("url", ""),
            "source": source,
            "source_domain": source.lower().replace(" ", "") + ".com" if source else "",
            "overall_sentiment_score": None,
            "overall_sentiment_label": None,
            "ticker_sentiment": [],
        })

    logger.info(f"Finnhub: fetched {len(articles)} articles for {ticker}.")
    return articles


def get_av_call_count() -> dict:
    """Load today's Alpha Vantage call count from persistent counter file."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _AV_COUNTER_FILE.exists():
        try:
            data = json.loads(_AV_COUNTER_FILE.read_text(encoding="utf-8"))
            if data.get("date") == today:
                return data
        except (json.JSONDecodeError, KeyError):
            pass
    return {"date": today, "count": 0}


def increment_av_call_count() -> int:
    """
    Increment and persist Alpha Vantage call counter. Returns new count.

    Locked around the whole read-modify-write cycle — pre_market/mid_session/
    post_close scans can run concurrently (scan_lock.py only mutexes two
    instances of the SAME scan_type against each other, by design), and all
    three hit this counter. Without the lock, two overlapping scans could
    both read count=N and both write back N+1, silently losing a real API
    call from the count and letting the true daily usage exceed this
    counter's view of it — undermining the very rate-limit enforcement this
    file exists for.
    """
    with exclusive_lock(_AV_COUNTER_LOCK_FILE):
        data = get_av_call_count()
        data["count"] += 1
        atomic_write_json(_AV_COUNTER_FILE, data)
        return data["count"]


# The scan that owns the reserved share of the daily budget. post_close ranks
# on the full session's data and owns the rank track's per-sector slots
# (rank_track.scan_type), so it is the scan whose news coverage matters most.
AV_OWNER_SCAN_TYPE = "post_close"


def check_av_budget(
    daily_limit: int = 20,
    scan_type: Optional[str] = None,
    reserved_for_owner: int = 0,
) -> bool:
    """
    Return True if a call is available within today's budget.

    reserved_for_owner (2026-08-26, v2.2.108): calls held back for the
    AV_OWNER_SCAN_TYPE scan. Earlier scans see an effective limit of
    `daily_limit - reserved_for_owner`; the owner scan sees the full
    `daily_limit`.

    Without this the budget was purely first-come-first-served across the day's
    three scans, so the EARLIEST scan — ranking on the least information — spent
    it and the most informed one went without. Measured live 2026-08-26: all 20
    calls were consumed, the post_close scan got only 6 of them, and TGT's news
    fetch was skipped outright. Structurally the same failure as the rank-track
    slot bug fixed in v2.2.100, where the first scan of the day claimed every
    per-sector slot.

    Deliberately a reservation rather than a raised ceiling: Alpha Vantage's
    free tier allows 25/day against the 20 used here, so raising the limit buys
    five calls and does not address the ordering at all.

    scan_type=None keeps the original unreserved behaviour, so callers that do
    not know their scan type are unaffected.
    """
    count = get_av_call_count()["count"]
    if scan_type is not None and scan_type != AV_OWNER_SCAN_TYPE and reserved_for_owner > 0:
        return count < max(0, daily_limit - reserved_for_owner)
    return count < daily_limit


_SECRET_PARAM_KEYS = ("apikey", "api_key", "token")


def _redact_secrets(text: str, params: dict) -> str:
    """
    Strip API key/token param values out of an error message before it's logged.
    requests' HTTPError embeds the full request URL, including query params, so an
    unredacted 429/403/5xx would otherwise write the live key to disk in plaintext.
    """
    for key in _SECRET_PARAM_KEYS:
        val = params.get(key)
        if val:
            text = text.replace(str(val), "***REDACTED***")
    return text


