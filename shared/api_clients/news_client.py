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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yfinance as yf

from shared.utils.logger import get_logger
from shared.utils.atomic_io import atomic_write_json, exclusive_lock
from shared.api_clients._http_backoff import http_get_with_backoff

logger = get_logger(__name__)

_AV_BASE_URL = "https://www.alphavantage.co/query"
_AV_COUNTER_FILE = Path("data/processed/av_call_count.json")
_AV_COUNTER_LOCK_FILE = Path("data/processed/av_call_count.json.lock")
_FINNHUB_BASE_URL = "https://finnhub.io/api/v1"


def fetch_news_alpha_vantage(
    ticker: str,
    time_from: Optional[str] = None,
    limit: int = 10,
) -> list[dict]:
    """
    Fetch news and sentiment from Alpha Vantage NEWS_SENTIMENT endpoint.
    Enforces 20 call/day budget. Returns empty list if budget exceeded.

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

    if not check_av_budget():
        logger.warning(f"Alpha Vantage budget exhausted for today — skipping news fetch for {ticker}.")
        return []

    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": ticker,
        "apikey": api_key,
        "limit": limit,
    }
    if time_from:
        params["time_from"] = time_from

    data = http_get_with_backoff(
        _AV_BASE_URL, params=params,
        redact=lambda text: _redact_secrets(text, params),
        label="fetch_news_alpha_vantage",
    )
    increment_av_call_count()

    if data is None:
        return []
    if "feed" not in data:
        logger.warning(f"AV news: unexpected response structure for {ticker}: {list(data.keys())}")
        return []

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
    """
    try:
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

    to_date = datetime.now(timezone.utc).date()
    from_date = to_date - timedelta(days=lookback_days)
    params = {
        "symbol": ticker,
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "token": api_key,
    }

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


def check_av_budget(daily_limit: int = 20) -> bool:
    """Return True if a call is available within today's budget."""
    return get_av_call_count()["count"] < daily_limit


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


