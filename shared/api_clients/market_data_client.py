"""
SHARED: Wraps yfinance — pulls daily OHLCV + earnings calendar data.
Primary price data source. Alpha Vantage daily endpoint is the fallback.
Enforces Alpha Vantage call budget (global_config.yaml).
Implements exponential backoff (30s → 60s → 120s → fallback).
"""

import time
from datetime import datetime, timezone
from typing import Optional

import yfinance as yf
import pandas as pd

from shared.utils.logger import get_logger

logger = get_logger(__name__)

_BACKOFF_DELAYS = [30, 60, 120]


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

    return _fetch_with_backoff(_fetch, retries=retries, label=f"fetch_ohlcv({ticker})")


def fetch_ohlcv_batch(
    tickers: list[str],
    period: str = "6mo",
    interval: str = "1d",
) -> dict[str, Optional[pd.DataFrame]]:
    """
    Fetch OHLCV for multiple tickers in a single yfinance call.
    Returns dict mapping ticker → DataFrame (or None on failure for that ticker).
    """
    def _fetch():
        raw = yf.download(
            tickers=" ".join(tickers),
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

    result: dict[str, Optional[pd.DataFrame]] = {}

    if len(tickers) == 1:
        result[tickers[0]] = fetch_ohlcv(tickers[0], period=period, interval=interval)
        return result

    raw = _fetch_with_backoff(_fetch, retries=3, label="fetch_ohlcv_batch")
    if raw is None:
        return {t: None for t in tickers}

    for ticker in tickers:
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
            else:
                logger.warning(f"Ticker {ticker} not found in batch response.")
                result[ticker] = None
        except Exception as exc:
            logger.error(f"Error extracting {ticker} from batch: {exc}")
            result[ticker] = None

    return result


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

    return _fetch_with_backoff(_fetch, retries=3, label=f"fetch_earnings_calendar({ticker})")


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

    return _fetch_with_backoff(_fetch, retries=retries, label="fetch_vix")


def fetch_treasury_yield(period: str = "3mo") -> Optional[pd.DataFrame]:
    """
    Fetch 10-year US Treasury yield (^TNX) via yfinance.
    Used by macro_overlay.py as a free proxy for Fed rate direction.
    """
    def _fetch():
        df = yf.download("^TNX", period=period, interval="1d", progress=False, auto_adjust=True)
        if df.empty:
            raise ValueError("Empty TNX response")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
        return df[["Open", "High", "Low", "Close", "Volume"]].copy()

    return _fetch_with_backoff(_fetch, retries=3, label="fetch_treasury_yield")


def fetch_dxy(period: str = "3mo") -> Optional[pd.DataFrame]:
    """
    Fetch US Dollar Index (DX-Y.NYB) via yfinance.
    Used by macro_overlay.py for USD strength signal.
    """
    def _fetch():
        df = yf.download("DX-Y.NYB", period=period, interval="1d", progress=False, auto_adjust=True)
        if df.empty:
            raise ValueError("Empty DXY response")
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
        return df[["Open", "High", "Low", "Close", "Volume"]].copy()

    return _fetch_with_backoff(_fetch, retries=3, label="fetch_dxy")


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

    return _fetch_with_backoff(_fetch, retries=3, label=f"fetch_insider_transactions({ticker})")


def _fetch_with_backoff(fn, retries: int = 3, label: str = ""):
    """
    Execute fn() with exponential backoff.
    Schedule: 30s → 60s → 120s → return None.
    """
    last_exc = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt < len(_BACKOFF_DELAYS):
                delay = _BACKOFF_DELAYS[attempt]
                logger.warning(f"[{label}] Attempt {attempt + 1} failed: {exc}. Retrying in {delay}s.")
                time.sleep(delay)
    logger.error(f"[{label}] All {retries} retries exhausted. Last error: {last_exc}")
    return None
