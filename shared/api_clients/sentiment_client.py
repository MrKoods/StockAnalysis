import json
import requests
from datetime import datetime, timedelta
from pathlib import Path

from shared.utils.logger import get_logger

logger = get_logger(__name__)

_TIMEOUT = 10


class SentimentClient:
    """Fetches and caches StockTwits sentiment snapshots.

    Uses the public StockTwits stream endpoint (no auth required for basic reads).
    Daily snapshots are cached under data/raw/sentiment/{TICKER}/{YYYY-MM-DD}.json
    so repeated calls on the same day avoid redundant API hits and historical trend
    analysis can look back over cached files.
    """

    def __init__(self, config: dict):
        api = config.get("api", {})
        self.base_url = api.get("stocktwits_base_url", "https://api.stocktwits.com/api/2")
        self.cache_dir = Path("data/raw/sentiment")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get_stocktwits_sentiment(self, ticker: str) -> dict:
        """Return current StockTwits sentiment snapshot (bullish/bearish ratio, message volume) for a ticker."""
        today = datetime.utcnow().strftime("%Y-%m-%d")
        cached = self._load_snapshot(ticker, today)
        if cached:
            return cached

        url = f"{self.base_url}/streams/symbol/{ticker.upper()}.json"
        try:
            resp = requests.get(url, timeout=_TIMEOUT)
            resp.raise_for_status()
            messages = resp.json().get("messages", [])
        except requests.RequestException as exc:
            logger.warning(f"StockTwits request failed for {ticker}: {exc}")
            return self._empty_snapshot(ticker, today)

        bullish = sum(
            1 for m in messages
            if m.get("entities", {}).get("sentiment", {}).get("basic") == "Bullish"
        )
        bearish = sum(
            1 for m in messages
            if m.get("entities", {}).get("sentiment", {}).get("basic") == "Bearish"
        )
        total = len(messages)

        snapshot = {
            "date": today,
            "ticker": ticker.upper(),
            "message_count": total,
            "bullish_count": bullish,
            "bearish_count": bearish,
            "neutral_count": total - bullish - bearish,
            "bullish_ratio": bullish / total if total > 0 else 0.0,
            "bearish_ratio": bearish / total if total > 0 else 0.0,
        }
        self._save_snapshot(ticker, snapshot)
        return snapshot

    def get_sentiment_history(self, ticker: str, lookback_days: int) -> list[dict]:
        """Return daily sentiment snapshots over the lookback window for trend analysis."""
        history = []
        today = datetime.utcnow().date()

        for days_back in range(lookback_days, -1, -1):
            date_str = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
            entry = self._load_snapshot(ticker, date_str)
            if entry:
                history.append(entry)

        # Always try to get a fresh snapshot for today if not cached yet
        if not history or history[-1]["date"] != today.strftime("%Y-%m-%d"):
            current = self.get_stocktwits_sentiment(ticker)
            if current["message_count"] > 0:
                history.append(current)

        return history

    def get_mention_spike(self, ticker: str) -> dict:
        """Return real-time mention count relative to baseline — used by day model for sudden spike detection."""
        snapshot = self.get_stocktwits_sentiment(ticker)
        # Simple heuristic: 30+ messages in the last stream fetch is elevated activity
        return {
            "ticker": ticker.upper(),
            "message_count": snapshot["message_count"],
            "is_spike": snapshot["message_count"] >= 30,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _empty_snapshot(self, ticker: str, date_str: str) -> dict:
        return {
            "date": date_str,
            "ticker": ticker.upper(),
            "message_count": 0,
            "bullish_count": 0,
            "bearish_count": 0,
            "neutral_count": 0,
            "bullish_ratio": 0.0,
            "bearish_ratio": 0.0,
        }

    def _save_snapshot(self, ticker: str, snapshot: dict) -> None:
        ticker_dir = self.cache_dir / ticker.upper()
        ticker_dir.mkdir(parents=True, exist_ok=True)
        path = ticker_dir / f"{snapshot['date']}.json"
        with open(path, "w") as f:
            json.dump(snapshot, f)

    def _load_snapshot(self, ticker: str, date_str: str) -> dict | None:
        path = self.cache_dir / ticker.upper() / f"{date_str}.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return None
