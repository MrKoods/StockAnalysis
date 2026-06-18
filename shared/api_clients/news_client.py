import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

from shared.utils.logger import get_logger

load_dotenv()

logger = get_logger(__name__)

_TIMEOUT = 15
_BASE_URL = "https://www.alphavantage.co/query"

# Alpha Vantage free tier: 25 requests/day, 5/minute.
# With 6 tickers we make 6 calls — add a small sleep to stay under the per-minute cap.
_RATE_LIMIT_SLEEP = 13  # seconds between calls (≈ 4–5 calls/min)


class NewsClient:
    """Fetches and caches Alpha Vantage News & Sentiment data.

    Requires ALPHA_VANTAGE_API_KEY in the environment (or .env file).
    If the key is missing the client returns empty results so the rest of
    the pipeline continues without news signals — it does NOT raise.

    Daily responses are cached under data/raw/news/{TICKER}/{YYYY-MM-DD}.json
    to avoid burning free-tier quota on repeated same-day runs.
    """

    def __init__(self, config: dict):
        self.api_key: str | None = os.getenv("ALPHA_VANTAGE_API_KEY")
        self.base_url: str = config.get("api", {}).get(
            "alpha_vantage_base_url", _BASE_URL
        )
        self.cache_dir = Path("data/raw/news")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        if not self.api_key:
            logger.warning(
                "ALPHA_VANTAGE_API_KEY not set — news signals will be skipped. "
                "Add the key to your .env file to enable Phase 8."
            )

    def get_news_sentiment(self, ticker: str, lookback_days: int = 3) -> list[dict]:
        """Return recent news articles with sentiment scores for a ticker.

        Each article dict contains:
          title, url, time_published, overall_sentiment_score,
          ticker_sentiment_score, ticker_relevance_score
        Only articles where relevance_score > 0.3 are included.
        Results are cached per ticker per day.
        """
        if not self.api_key:
            return []

        today = datetime.utcnow().strftime("%Y-%m-%d")
        cached = self._load_cache(ticker, today)
        if cached is not None:
            return cached

        time_from = (datetime.utcnow() - timedelta(days=lookback_days)).strftime(
            "%Y%m%dT0000"
        )
        params = {
            "function": "NEWS_SENTIMENT",
            "tickers": ticker.upper(),
            "time_from": time_from,
            "sort": "RELEVANCE",
            "limit": 50,
            "apikey": self.api_key,
        }

        try:
            resp = requests.get(self.base_url, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            logger.warning(f"Alpha Vantage news request failed for {ticker}: {exc}")
            return []

        if "Information" in data:
            # Rate-limit message from AV ("Thank you for using Alpha Vantage...")
            logger.warning(f"Alpha Vantage rate limit hit for {ticker}: {data['Information']}")
            return []

        articles = []
        for item in data.get("feed", []):
            ticker_info = _find_ticker_sentiment(item.get("ticker_sentiment", []), ticker)
            if ticker_info is None:
                continue
            relevance = float(ticker_info.get("relevance_score", 0))
            if relevance < 0.3:
                continue
            articles.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "time_published": item.get("time_published", ""),
                    "overall_sentiment_score": float(item.get("overall_sentiment_score", 0)),
                    "ticker_sentiment_score": float(
                        ticker_info.get("ticker_sentiment_score", 0)
                    ),
                    "ticker_relevance_score": relevance,
                }
            )

        self._save_cache(ticker, today, articles)
        time.sleep(_RATE_LIMIT_SLEEP)  # respect per-minute cap between tickers
        return articles

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cache_path(self, ticker: str, date_str: str) -> Path:
        ticker_dir = self.cache_dir / ticker.upper()
        ticker_dir.mkdir(parents=True, exist_ok=True)
        return ticker_dir / f"{date_str}.json"

    def _save_cache(self, ticker: str, date_str: str, articles: list[dict]) -> None:
        with open(self._cache_path(ticker, date_str), "w") as f:
            json.dump(articles, f)

    def _load_cache(self, ticker: str, date_str: str) -> list[dict] | None:
        path = self._cache_path(ticker, date_str)
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return None


def _find_ticker_sentiment(ticker_sentiment_list: list[dict], ticker: str) -> dict | None:
    """Return the sentiment entry for `ticker` from the per-article ticker_sentiment array."""
    target = ticker.upper()
    for entry in ticker_sentiment_list:
        if entry.get("ticker", "").upper() == target:
            return entry
    return None
