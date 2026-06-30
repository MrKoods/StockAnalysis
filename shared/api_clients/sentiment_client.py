"""
SHARED: Wraps StockTwits API + Reddit via PRAW.
Produces timestamped posts with bullish/bearish labels and credibility metadata.
All timestamps normalized to UTC immediately on ingestion.
Implements exponential backoff on all API calls.
"""

import os
import time
import logging
from datetime import datetime, timezone
from typing import Optional

import requests

from shared.utils.logger import get_logger

logger = get_logger(__name__)

_STOCKTWITS_BASE = "https://api.stocktwits.com/api/2"
_DEFAULT_SUBREDDITS = ["wallstreetbets", "investing", "stocks", "StockMarket", "semiconductors"]

_BULLISH_REDDIT_KEYWORDS = [
    "buy", "long", "calls", "bull", "bullish", "moon", "rocket", "squeeze",
    "breakout", "upside", "strong", "buy the dip", "accumulate",
]
_BEARISH_REDDIT_KEYWORDS = [
    "sell", "short", "puts", "bear", "bearish", "dump", "crash", "down",
    "avoid", "weak", "overvalued", "exit", "reduce",
]


def fetch_stocktwits(ticker: str, limit: int = 30) -> list[dict]:
    """
    Fetch recent StockTwits posts for a ticker.

    Returns list of dicts:
    {
        post_id, timestamp_utc, body, sentiment (bullish/bearish/None),
        author_id, author_username, author_followers, author_following,
        author_join_date, author_verified
    }
    """
    access_token = os.environ.get("STOCKTWITS_ACCESS_TOKEN")
    params: dict = {"limit": limit}
    if access_token:
        params["access_token"] = access_token

    url = f"{_STOCKTWITS_BASE}/streams/symbol/{ticker}.json"
    resp = _backoff_get(url, params)
    if resp is None:
        logger.warning(f"StockTwits: no response for {ticker} — sentiment-offline mode.")
        return []

    try:
        data = resp.json()
    except Exception as exc:
        logger.error(f"StockTwits: JSON parse error for {ticker}: {exc}")
        return []

    messages = data.get("messages", [])
    posts = []
    for msg in messages:
        ts_raw = msg.get("created_at", "")
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            ts = datetime.now(timezone.utc)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        sentiment_raw = msg.get("entities", {}).get("sentiment")
        if isinstance(sentiment_raw, dict):
            label = sentiment_raw.get("basic", "").lower()
            sentiment = label if label in ("bullish", "bearish") else None
        else:
            sentiment = None

        user = msg.get("user", {})
        posts.append({
            "post_id": str(msg.get("id", "")),
            "timestamp_utc": ts.isoformat(),
            "body": msg.get("body", ""),
            "sentiment": sentiment,
            "author_id": str(user.get("id", "")),
            "author_username": user.get("username", ""),
            "author_followers": int(user.get("followers", 0)),
            "author_following": int(user.get("following", 0)),
            "author_join_date": user.get("join_date", None),
            "author_verified": bool(user.get("official", False)),
        })

    logger.info(f"StockTwits: fetched {len(posts)} posts for {ticker}.")
    return posts


def fetch_reddit(
    ticker: str,
    subreddits: Optional[list[str]] = None,
    limit: int = 50,
    time_filter: str = "week",
) -> list[dict]:
    """
    Fetch Reddit posts mentioning ticker from configured subreddits via PRAW.

    Returns list of dicts:
    {
        post_id, timestamp_utc, title, body, subreddit, score,
        num_comments, author_name, author_created_utc, author_link_karma, sentiment
    }
    Sentiment is keyword-classified here (Reddit has no native labels).
    """
    try:
        import praw
    except ImportError:
        logger.warning("praw not installed — Reddit sentiment unavailable.")
        return []

    client_id = os.environ.get("REDDIT_CLIENT_ID")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET")
    user_agent = os.environ.get("REDDIT_USER_AGENT", "StockAnalysis/1.0")

    if not client_id or not client_secret:
        logger.warning("Reddit credentials not configured — Reddit sentiment unavailable.")
        return []

    try:
        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
        )
    except Exception as exc:
        logger.error(f"PRAW init failed: {exc}")
        return []

    if subreddits is None:
        subreddits = _DEFAULT_SUBREDDITS

    posts = []
    query = ticker
    for sub_name in subreddits:
        try:
            subreddit = reddit.subreddit(sub_name)
            results = subreddit.search(query, time_filter=time_filter, limit=limit // len(subreddits))
            for post in results:
                ts = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)
                body = post.selftext or ""
                combined_text = f"{post.title} {body}"
                sentiment = classify_sentiment_reddit(combined_text)
                author = post.author
                posts.append({
                    "post_id": post.id,
                    "timestamp_utc": ts.isoformat(),
                    "title": post.title,
                    "body": body,
                    "subreddit": sub_name,
                    "score": post.score,
                    "num_comments": post.num_comments,
                    "author_name": str(author) if author else "deleted",
                    "author_created_utc": float(author.created_utc) if author else None,
                    "author_link_karma": int(author.link_karma) if author else 0,
                    "sentiment": sentiment,
                })
        except Exception as exc:
            logger.warning(f"Reddit r/{sub_name} search failed for {ticker}: {exc}")
            continue

    logger.info(f"Reddit: fetched {len(posts)} posts for {ticker} across {subreddits}.")
    return posts


def classify_sentiment_reddit(text: str) -> Optional[str]:
    """
    Naive keyword-based sentiment classifier for Reddit posts.
    Returns 'bullish', 'bearish', or None (neutral/ambiguous).
    Reddit doesn't provide native sentiment labels.
    """
    if not text:
        return None
    text_lower = text.lower()
    bull = sum(1 for kw in _BULLISH_REDDIT_KEYWORDS if kw in text_lower)
    bear = sum(1 for kw in _BEARISH_REDDIT_KEYWORDS if kw in text_lower)
    if bull > bear:
        return "bullish"
    if bear > bull:
        return "bearish"
    return None


def _backoff_get(url: str, params: dict, retries: int = 3, **kwargs) -> Optional[requests.Response]:
    """GET request with exponential backoff (30s → 60s → 120s → None)."""
    delays = [30, 60, 120]
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=10, **kwargs)
            resp.raise_for_status()
            return resp
        except Exception as exc:
            if attempt < len(delays):
                logger.warning(f"Request failed (attempt {attempt+1}): {exc}. Retry in {delays[attempt]}s.")
                time.sleep(delays[attempt])
    logger.error(f"All retries exhausted for {url}")
    return None
