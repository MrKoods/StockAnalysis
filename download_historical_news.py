"""
One-time historical news downloader for backtesting.

Fetches Alpha Vantage NEWS_SENTIMENT for each watchlist ticker, one quarter
at a time, and stores results in data/historical_news/{TICKER}/{YYYY-QN}.json.

Rate limits (free tier):
  25 calls/day, 5 calls/minute (we use 20/day and 4/min to stay safe)

Re-run safe: already-downloaded quarters are skipped.
Priority: most-recent quarters first (test-set data arrives on day 1).

Usage:
  python download_historical_news.py              # collect everything
  python download_historical_news.py --status     # show what has been downloaded
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

_AV_BASE = "https://www.alphavantage.co/query"
_NEWS_DIR = Path("data/historical_news")
_PROGRESS_FILE = Path("data/historical_news/.progress.json")
_DAILY_LOG = Path("data/historical_news/.daily_calls.json")

# Tickers + date range to cover
TICKERS = ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"]

# Full dataset: 2021-Q3 → current quarter (most-recent first for test-set priority)
def _all_quarters() -> list[tuple[str, str, str]]:
    """
    Return list of (ql_label, time_from, time_to) tuples, most-recent first.
    ql_label: 'YYYY-QN'
    time_from / time_to: 'YYYYMMDDTHHmm' strings for AV API
    """
    now = datetime.now(timezone.utc)
    quarters = []
    # Go back from current quarter to 2021-Q3
    year, month = now.year, now.month
    while True:
        q = (month - 1) // 3 + 1
        q_start_month = (q - 1) * 3 + 1
        q_end_month = q * 3
        q_start = datetime(year, q_start_month, 1, tzinfo=timezone.utc)
        # End is start of NEXT quarter (or today if current)
        if q == 4:
            q_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            q_end = datetime(year, q_end_month + 1, 1, tzinfo=timezone.utc)
        q_end = min(q_end, now)

        ql = f"{year}-Q{q}"
        tf = q_start.strftime("%Y%m%dT%H%M")
        tt = q_end.strftime("%Y%m%dT%H%M")
        quarters.append((ql, tf, tt))

        # Step back one quarter
        if q == 1:
            year -= 1
            month = 10
        else:
            month = q_start_month - 1

        # Stop at 2021-Q3 (start of our historical data)
        if year < 2021 or (year == 2021 and q < 3):
            break

    return quarters


def _load_progress() -> dict:
    if _PROGRESS_FILE.exists():
        try:
            return json.loads(_PROGRESS_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_progress(prog: dict) -> None:
    _PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PROGRESS_FILE.write_text(json.dumps(prog, indent=2))


def _calls_today() -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if _DAILY_LOG.exists():
        try:
            data = json.loads(_DAILY_LOG.read_text())
            if data.get("date") == today:
                return int(data.get("count", 0))
        except Exception:
            pass
    return 0


def _increment_daily(n: int = 1) -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    count = _calls_today()
    count += n
    _DAILY_LOG.parent.mkdir(parents=True, exist_ok=True)
    _DAILY_LOG.write_text(json.dumps({"date": today, "count": count}))
    return count


def _fetch_quarter(api_key: str, ticker: str, time_from: str, time_to: str) -> list[dict]:
    """Fetch up to 200 AV news articles for ticker in the given window."""
    params = {
        "function": "NEWS_SENTIMENT",
        "tickers": ticker,
        "time_from": time_from,
        "time_to": time_to,
        "limit": 200,
        "sort": "EARLIEST",
        "apikey": api_key,
    }
    try:
        resp = requests.get(_AV_BASE, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"    ERROR fetching {ticker} {time_from}-{time_to}: {exc}")
        return []

    if "Information" in data:
        print(f"    RATE LIMIT hit: {data['Information'][:80]}")
        return None  # Signal rate-limit to caller

    if "feed" not in data:
        print(f"    Unexpected response for {ticker}: {list(data.keys())}")
        return []

    articles = []
    for item in data.get("feed", []):
        ts_raw = item.get("time_published", "")
        try:
            ts = datetime.strptime(ts_raw, "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        except ValueError:
            ts = datetime.now(timezone.utc)
        articles.append({
            "article_id": item.get("url", ts_raw),
            "timestamp_utc": ts.isoformat(),
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "source": item.get("source", ""),
            "source_domain": item.get("source_domain", ""),
            "overall_sentiment_score": float(item.get("overall_sentiment_score", 0.0)),
            "overall_sentiment_label": item.get("overall_sentiment_label", "Neutral"),
            "ticker_sentiment": item.get("ticker_sentiment", []),
        })
    return articles


def _save_articles(ticker: str, ql: str, articles: list[dict]) -> None:
    path = _NEWS_DIR / ticker / f"{ql}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(articles, indent=2), encoding="utf-8")


def print_status() -> None:
    prog = _load_progress()
    quarters = _all_quarters()
    total = len(TICKERS) * len(quarters)
    done = sum(1 for t in TICKERS for (ql, _, _) in quarters if prog.get(f"{t}/{ql}") == "ok")
    print(f"\nProgress: {done}/{total} ticker-quarters downloaded")
    print(f"  Daily calls today: {_calls_today()}/20")
    print()
    for ticker in TICKERS:
        ticker_done = [ql for (ql, _, _) in quarters if prog.get(f"{ticker}/{ql}") == "ok"]
        print(f"  {ticker}: {len(ticker_done)}/{len(quarters)} quarters — "
              f"{'COMPLETE' if len(ticker_done) == len(quarters) else 'in progress'}")
        if ticker_done:
            print(f"    Latest: {ticker_done[0]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true", help="Show download progress and exit")
    parser.add_argument("--daily-limit", type=int, default=20, help="Max AV calls today (default 20)")
    args = parser.parse_args()

    if args.status:
        print_status()
        return

    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
    if not api_key:
        print("ERROR: ALPHA_VANTAGE_API_KEY not set in environment / .env")
        return

    prog = _load_progress()
    quarters = _all_quarters()
    calls_today = _calls_today()
    daily_limit = args.daily_limit

    print(f"Historical news downloader")
    print(f"  Tickers: {', '.join(TICKERS)}")
    print(f"  Quarters: {len(quarters)} (most-recent first)")
    print(f"  Calls remaining today: {daily_limit - calls_today}/{daily_limit}")
    print()

    # Iterate quarters most-recent first, then tickers — this ensures test-set
    # data (recent quarters) is always collected before train-set data
    for ql, tf, tt in quarters:
        for ticker in TICKERS:
            key = f"{ticker}/{ql}"
            if prog.get(key) == "ok":
                continue  # Already downloaded

            if calls_today >= daily_limit:
                print(f"\nDaily limit ({daily_limit}) reached. Re-run tomorrow to continue.")
                print(f"Progress: {sum(1 for v in prog.values() if v == 'ok')}/{len(TICKERS) * len(quarters)} done")
                return

            print(f"  Fetching {ticker} {ql} ({tf} to {tt}) ... ", end="", flush=True)
            articles = _fetch_quarter(api_key, ticker, tf, tt)

            if articles is None:
                # Rate limit signal — wait and retry once
                print("rate limited, waiting 65s ...")
                time.sleep(65)
                articles = _fetch_quarter(api_key, ticker, tf, tt)
                if articles is None:
                    print("  Still failing — stopping for today.")
                    return

            calls_today = _increment_daily()
            _save_articles(ticker, ql, articles)
            prog[key] = "ok"
            _save_progress(prog)
            print(f"{len(articles)} articles saved  [{calls_today}/{daily_limit} calls today]")

            # Respect 4 calls/minute (15s gap)
            if calls_today < daily_limit:
                time.sleep(15)

    done = sum(1 for v in prog.values() if v == "ok")
    total = len(TICKERS) * len(quarters)
    print(f"\nAll done: {done}/{total} ticker-quarters collected.")


if __name__ == "__main__":
    main()
