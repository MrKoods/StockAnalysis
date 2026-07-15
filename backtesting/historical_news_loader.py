"""
Loads cached historical Alpha Vantage news articles for backtesting.
Articles are stored as quarterly JSON files downloaded by download_historical_news.py.

Directory layout:
  data/historical_news/{TICKER}/{YYYY-Q{N}.json}
  e.g.  data/historical_news/NVDA/2025-Q1.json

Each file is a list of article dicts in the same format returned by
fetch_news_alpha_vantage() — compatible with compute_news_score().
"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

_NEWS_DIR = Path("data/historical_news")


def quarter_label(dt: datetime) -> str:
    """Return 'YYYY-QN' string for a datetime."""
    q = (dt.month - 1) // 3 + 1
    return f"{dt.year}-Q{q}"


def load_historical_news(
    ticker: str,
    bar_date: datetime,
    lookback_days: int = 5,
) -> list[dict]:
    """
    Return AV news articles for `ticker` published in
    [bar_date - lookback_days, bar_date].

    Loads quarterly JSON files from data/historical_news/{ticker}/.
    Returns [] if no cached files exist for the window (backtest will
    fall back to neutral news values).
    """
    if bar_date.tzinfo is None:
        bar_date = bar_date.replace(tzinfo=timezone.utc)

    window_start = bar_date - timedelta(days=lookback_days)
    articles = []

    # Need to cover at most 2 quarters (window might span a quarter boundary)
    quarters_needed = {quarter_label(window_start), quarter_label(bar_date)}

    for ql in quarters_needed:
        path = _NEWS_DIR / ticker / f"{ql}.json"
        if not path.exists():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for art in raw:
            ts_str = art.get("timestamp_utc", "")
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
            if window_start <= ts <= bar_date:
                articles.append(art)

    return articles


def has_historical_news(ticker: str, bar_date: datetime) -> bool:
    """Return True if at least one quarterly file exists for this ticker/date."""
    ql = quarter_label(bar_date if bar_date.tzinfo else bar_date.replace(tzinfo=timezone.utc))
    return (_NEWS_DIR / ticker / f"{ql}.json").exists()
