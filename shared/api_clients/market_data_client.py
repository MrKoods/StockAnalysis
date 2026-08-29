"""
SHARED: Wraps yfinance — pulls daily OHLCV + earnings calendar data.
Primary price data source. Alpha Vantage daily endpoint is the fallback.
Enforces Alpha Vantage call budget (global_config.yaml).
Implements exponential backoff (30s → 60s → 120s → fallback).
"""

import re
from datetime import date, datetime, timezone
from typing import Optional

import yfinance as yf
import pandas as pd

from shared.utils.logger import get_logger
from shared.api_clients._http_backoff import retry_with_backoff
from shared.api_clients import rate_limiter

logger = get_logger(__name__)


def _trim_incomplete_last_bar(df: pd.DataFrame) -> pd.DataFrame:
    """
    Drop trailing rows with a NaN Close.

    yfinance includes an in-progress bar for the current calendar day whenever a
    daily-interval request is made during market hours (including pre-market) —
    Open/Volume may already have partial prints, but Close stays NaN until the
    session actually closes. Every downstream indicator (SMA/RSI/ATR/MACD) assumes
    the last row is a completed bar, so trim it rather than let a NaN close through.
    Retrying won't fix this (the bar stays incomplete for hours), so this returns
    the trimmed — possibly empty — DataFrame rather than raising.
    """
    while not df.empty and pd.isna(df["Close"].iloc[-1]):
        df = df.iloc[:-1]
    return df


def fetch_ohlcv(
    ticker: str,
    period: str = "6mo",
    interval: str = "1d",
    retries: int = 3,
) -> Optional[pd.DataFrame]:
    """
    Fetch daily OHLCV bars for a single ticker via yfinance.

    Returns DataFrame with columns [Open, High, Low, Close, Volume] indexed by UTC date.
    Returns None if all retries fail (caller should invoke fallback or data-unavailable mode).

    Backoff: 30s → 60s → 120s → None
    """
    def _fetch():
        t = yf.Ticker(ticker)
        df = t.history(period=period, interval=interval, auto_adjust=True)
        if df.empty:
            raise ValueError(f"Empty response for {ticker}")
        # Normalize index to UTC
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
        # Keep standard columns only
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df = _trim_incomplete_last_bar(df)
        return df

    return retry_with_backoff(_fetch, retries=retries, label=f"fetch_ohlcv({ticker})")


def fetch_ohlcv_since(ticker: str, start: str) -> Optional[pd.DataFrame]:
    """
    Daily OHLC(V) for `ticker` from `start` (YYYY-MM-DD) to now, via yfinance.

    Returns a DataFrame indexed by date with columns [Open, High, Low, Close],
    or None if unavailable / start is not in the past.

    Guards against start >= today: yfinance's `start=` with no `end=` sends the
    request's "now" as endDate, so a start date that is today or tomorrow (a
    post-close ET signal is already tomorrow in UTC) produces
    "start date cannot be after end date", which yfinance surfaces as
    "possibly delisted; no price data found" — a misleading log line on every
    fresh signal (2026-08 API audit, YF-5). Callers get a clean None instead.
    """
    try:
        start_date = datetime.strptime(start[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        logger.warning(f"fetch_ohlcv_since({ticker}): unparseable start {start!r}")
        return None
    if start_date >= date.today():
        return None

    def _fetch():
        rate_limiter.acquire("yfinance")
        df = yf.download(ticker, start=start, auto_adjust=True, progress=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.index = pd.to_datetime(df.index)
        cols = [c for c in ("Open", "High", "Low", "Close") if c in df.columns]
        return df[cols].dropna()

    return retry_with_backoff(_fetch, retries=3, label=f"fetch_ohlcv_since({ticker})")


# Process-lifetime OHLCV cache, keyed by (ticker, interval) -> (df, days_covered).
# 2026-08-23 full model audit: swing_model/indicator_pipeline.py::run_pipeline()
# (period="6mo") and swing_model/run_swing_model.py::_fetch_market_context()
# (period="3mo") both call fetch_ohlcv_batch() for a heavily-overlapping ticker
# set (every watchlist ticker + every sector benchmark), seconds apart, in the
# same scan — nearly doubling yfinance call volume every run across 4 sectors,
# 3x/day. Both live and paper trading are launched as a fresh process per scan
# (Windows Task Scheduler), so a simple no-expiry, per-process cache is exactly
# right: it can't go stale within one scan and it can't leak into the next one
# (new process). Cleared per-test by tests/conftest.py's autouse
# _isolate_ohlcv_cache fixture — without that, a test mocking yf.download for
# ticker "X" could silently serve a different test's mocked "X" data back.
_OHLCV_BATCH_CACHE: dict[tuple[str, str], tuple[pd.DataFrame, int]] = {}


def _period_to_days(period: str) -> int:
    """
    Approximate calendar days for a yfinance period string ('3mo', '6mo',
    '1y', '5d', ...). Returns 0 for an unrecognized format, which the cache
    treats as "no cached entry can possibly satisfy this" — always re-fetch
    rather than guess.
    """
    match = re.match(r"^(\d+)(d|mo|y)$", period)
    if not match:
        return 0
    n, unit = int(match.group(1)), match.group(2)
    return n * {"d": 1, "mo": 30, "y": 365}[unit]


def fetch_ohlcv_batch(
    tickers: list[str],
    period: str = "6mo",
    interval: str = "1d",
) -> dict[str, Optional[pd.DataFrame]]:
    """
    Fetch OHLCV for multiple tickers in a single yfinance call.
    Returns dict mapping ticker → DataFrame (or None on failure for that ticker).

    Serves a ticker from _OHLCV_BATCH_CACHE instead of re-fetching whenever an
    already-cached entry (from an earlier, equal-or-longer period request this
    same process) covers the requested period — see the cache's own comment
    for why this is safe. A ticker with insufficient or no cached coverage is
    always fetched for real; this never returns stale-relative-to-request data,
    it only skips a redundant call when the cache already has enough history.
    """
    requested_days = _period_to_days(period)
    result: dict[str, Optional[pd.DataFrame]] = {}
    to_fetch: list[str] = []

    for ticker in tickers:
        cached = _OHLCV_BATCH_CACHE.get((ticker, interval))
        if cached is not None and cached[1] >= requested_days:
            result[ticker] = cached[0]
        else:
            to_fetch.append(ticker)

    if not to_fetch:
        return result

    def _fetch():
        raw = yf.download(
            tickers=" ".join(to_fetch),
            period=period,
            interval=interval,
            auto_adjust=True,
            group_by="ticker",
            threads=True,
            progress=False,
        )
        if raw.empty:
            raise ValueError("Empty batch response from yfinance")
        return raw

    if len(to_fetch) == 1:
        df = fetch_ohlcv(to_fetch[0], period=period, interval=interval)
        result[to_fetch[0]] = df
        if df is not None:
            _OHLCV_BATCH_CACHE[(to_fetch[0], interval)] = (df, requested_days)
        return result

    raw = retry_with_backoff(_fetch, retries=3, label="fetch_ohlcv_batch")
    if raw is None:
        for ticker in to_fetch:
            result[ticker] = None
        return result

    for ticker in to_fetch:
        try:
            if ticker in raw.columns.get_level_values(0):
                df = raw[ticker][["Open", "High", "Low", "Close", "Volume"]].copy()
                df = df.dropna(how="all")
                df = _trim_incomplete_last_bar(df)
                if df.empty:
                    result[ticker] = None
                    continue
                # Normalize index to UTC
                if df.index.tz is None:
                    df.index = df.index.tz_localize("UTC")
                else:
                    df.index = df.index.tz_convert("UTC")
                result[ticker] = df
                _OHLCV_BATCH_CACHE[(ticker, interval)] = (df, requested_days)
            else:
                logger.warning(f"Ticker {ticker} not found in batch response.")
                result[ticker] = None
        except Exception as exc:
            logger.error(f"Error extracting {ticker} from batch: {exc}")
            result[ticker] = None

    return result


def fetch_upcoming_earnings_date(ticker: str):
    """
    A ticker's next known earnings date (a plain ``date``), via yfinance's
    calendar. Cached for 7 days — earnings dates move at most once a quarter,
    and this used to be called once per not-yet-refreshed ticker on EVERY scan
    (~180 raw yfinance calls/day) purely to schedule fundamental refreshes.

    Normalises yfinance's shifting calendar shape (a bare date, or a dict with
    raw/fmt keys on newer versions). Returns None if unavailable rather than
    raising — this is a scheduling hint, not a required input.
    """
    def _fetch():
        rate_limiter.acquire("yfinance")
        cal = yf.Ticker(ticker).calendar or {}
        dates = cal.get("Earnings Date") or []
        if not dates:
            return None
        first = dates[0] if hasattr(dates, "__getitem__") else None
        if first is None:
            return None
        if isinstance(first, dict):
            raw = first.get("raw") or first.get("timestamp")
            fmt = first.get("fmt") or first.get("date")
            if raw:
                return pd.Timestamp(raw, unit="s").date().isoformat()
            if fmt:
                return pd.Timestamp(fmt).date().isoformat()
            return None
        return pd.Timestamp(first).date().isoformat()

    from shared.api_clients import cache
    try:
        iso = cache.cached_call("earnings_calendar", f"upcoming_{ticker}", cache.TTL["earnings_calendar"], _fetch)
    except Exception:
        iso = None
    return datetime.strptime(iso, "%Y-%m-%d").date() if iso else None


def fetch_last_reported_earnings_date(ticker: str):
    """
    A ticker's most recently ACTUALLY reported earnings date (a plain ``date``),
    via yfinance's earnings-date history. Deliberately separate from
    fetch_upcoming_earnings_date: once a company reports, yfinance's calendar
    flips to the NEXT quarter almost immediately, so the forward-looking value
    can't tell you a report just landed. Cached 7 days. Returns None if
    unavailable.
    """
    def _fetch():
        rate_limiter.acquire("yfinance")
        df = yf.Ticker(ticker).get_earnings_dates(limit=4)
        if df is None or df.empty or "Reported EPS" not in df.columns:
            return None
        reported = df["Reported EPS"].dropna()
        if reported.empty:
            return None
        return reported.sort_index(ascending=False).index[0].date().isoformat()

    from shared.api_clients import cache
    try:
        iso = cache.cached_call("earnings_calendar", f"last_reported_{ticker}", cache.TTL["earnings_calendar"], _fetch)
    except Exception:
        iso = None
    return datetime.strptime(iso, "%Y-%m-%d").date() if iso else None


def fetch_earnings_calendar(ticker: str) -> Optional[dict]:
    """
    Fetch upcoming earnings date for a ticker via yfinance calendar data.

    Returns dict with keys: {next_earnings_date: datetime, days_to_earnings: int}
    Returns None if data unavailable.
    """
    def _fetch():
        t = yf.Ticker(ticker)
        cal = t.calendar
        if cal is None:
            return None

        next_date = None

        try:
            # yfinance >= 0.2.x returns a dict; older versions return a DataFrame
            if isinstance(cal, dict):
                earnings_dates = cal.get("Earnings Date") or cal.get("earningsDate") or []
                if not earnings_dates:
                    return None
                first = earnings_dates[0] if hasattr(earnings_dates, "__getitem__") else None
                if first is None:
                    return None
                # Newer yfinance may return list of dicts with raw (unix ts) or fmt (string)
                if isinstance(first, dict):
                    raw = first.get("raw") or first.get("timestamp")
                    fmt = first.get("fmt") or first.get("date")
                    if raw:
                        next_date = pd.Timestamp(raw, unit="s").to_pydatetime()
                    elif fmt:
                        next_date = pd.Timestamp(fmt).to_pydatetime()
                else:
                    next_date = pd.Timestamp(first).to_pydatetime()
            elif hasattr(cal, "empty"):
                if cal.empty:
                    return None
                dates = cal.columns.tolist() if hasattr(cal, "columns") else cal.index.tolist()
                if dates:
                    next_date = pd.Timestamp(dates[0]).to_pydatetime()
        except Exception as exc:
            logger.warning(f"[fetch_earnings_calendar({ticker})] Parse error: {exc} — skipping.")
            return None

        if next_date is None:
            return None

        if next_date.tzinfo is None:
            next_date = next_date.replace(tzinfo=timezone.utc)

        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        days_to_earnings = (next_date.replace(tzinfo=timezone.utc) - today).days

        return {
            "next_earnings_date": next_date,
            "days_to_earnings": days_to_earnings,
        }

    return retry_with_backoff(_fetch, retries=3, label=f"fetch_earnings_calendar({ticker})")


def fetch_vix(period: str = "1mo", retries: int = 3) -> Optional[float]:
    """
    Fetch current VIX level via yfinance (^VIX).
    Returns latest closing value or None on failure.
    """
    def _fetch():
        df = yf.download("^VIX", period=period, interval="1d", progress=False, auto_adjust=True)
        if df.empty:
            raise ValueError("Empty VIX response")
        # yfinance >= 0.2.x returns MultiIndex columns for single-ticker downloads
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        return float(close.iloc[-1])

    return retry_with_backoff(_fetch, retries=retries, label="fetch_vix")


def fetch_vix_pct_change(period: str = "1mo", retries: int = 3) -> Optional[float]:
    """
    Fetch VIX's most recent session-over-session % change via yfinance (^VIX).

    fetch_vix() only ever returned the latest level, discarding the prior
    close needed to compute a change — used by black_swan_detector.check_black_swan
    for its vix_current_pct_change input (a true tick-level intraday spike isn't
    available from this daily-bar source; this is the closest free proxy, in
    keeping with how the rest of this pipeline already treats "current" data as
    the latest available daily bar, refreshed 2-3x/day, not live streaming).
    Returns None on failure or if fewer than 2 bars are available.
    """
    def _fetch():
        df = yf.download("^VIX", period=period, interval="1d", progress=False, auto_adjust=True)
        if df.empty:
            raise ValueError("Empty VIX response")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        if len(close) < 2:
            return None
        prior, latest = float(close.iloc[-2]), float(close.iloc[-1])
        if prior == 0:
            return None
        return (latest - prior) / prior

    return retry_with_backoff(_fetch, retries=retries, label="fetch_vix_pct_change")


def fetch_vix_and_pct_change(period: str = "1mo", retries: int = 3) -> tuple[Optional[float], Optional[float]]:
    """
    fetch_vix() and fetch_vix_pct_change() need the same ^VIX daily series
    (the second is only fetch_vix() plus the prior close it discards) but
    _fetch_market_context() was calling both independently — two full
    yf.download("^VIX", ...) round trips, back to back, every scan (2026-08-23
    full model audit finding). This does one fetch and derives both values
    from it. fetch_vix()/fetch_vix_pct_change() are left as they were for any
    caller that only needs one value — this is purely for the one call site
    that needs both.

    Returns (latest_level, pct_change) — either may be None independently
    (e.g. exactly 2 bars gives a valid pct_change but a "latest" is always
    derivable whenever pct_change is; only a wholesale fetch failure or fewer
    than 2 bars affects both at once, in which case both are None).
    """
    def _fetch():
        df = yf.download("^VIX", period=period, interval="1d", progress=False, auto_adjust=True)
        if df.empty:
            raise ValueError("Empty VIX response")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        return close

    close = retry_with_backoff(_fetch, retries=retries, label="fetch_vix_and_pct_change")
    if close is None or len(close) == 0:
        return None, None
    latest = float(close.iloc[-1])
    if len(close) < 2:
        return latest, None
    prior = float(close.iloc[-2])
    pct_change = (latest - prior) / prior if prior != 0 else None
    return latest, pct_change


# fetch_treasury_yield / fetch_dxy (yfinance ^TNX / DX-Y.NYB) were removed
# 2026-08 (API audit MR-4) — the live macro overlay now reads the actual
# 10-yr Treasury yield and a USD/EUR strength series from Alpha Vantage's
# economic-data endpoints (shared/api_clients/macro_data_client.py). The
# backtest still uses its own cached TNX.csv / DXY.csv (backtesting/simulation.py).


def fetch_insider_transactions(ticker: str) -> Optional[list[dict]]:
    """
    Fetch SEC Form 4 insider transactions for a ticker via yfinance.
    Returns list of {date, insider_name, transaction_type, shares, value} dicts.
    Note: yfinance insider data has 1-2 business day delay — treat as confirmation only.
    """
    def _fetch():
        t = yf.Ticker(ticker)
        insiders = t.insider_transactions
        if insiders is None or insiders.empty:
            return []
        records = []
        for _, row in insiders.iterrows():
            try:
                date = row.get("Start Date", row.get("Date", None))
                if hasattr(date, "to_pydatetime"):
                    date = date.to_pydatetime()
                if date and hasattr(date, "tzinfo") and date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                records.append({
                    "date": date,
                    "insider_name": row.get("Insider", ""),
                    "position": row.get("Position", ""),
                    "transaction_type": row.get("Transaction", ""),
                    "shares": row.get("Shares", 0),
                    "value": row.get("Value", 0),
                })
            except Exception:
                continue
        return records

    return retry_with_backoff(_fetch, retries=3, label=f"fetch_insider_transactions({ticker})")
