import json
import os
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf
from dotenv import load_dotenv

from shared.utils.logger import get_logger

load_dotenv()

logger = get_logger(__name__)

_TIMEOUT = 15
_BASE_URL = "https://www.alphavantage.co/query"
_RATE_LIMIT_SLEEP = 13  # seconds between calls — consistent with free tier (5 req/min)


def get_ohlcv(ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch daily OHLCV bars for a ticker over a date range using yfinance.

    Parameters
    ----------
    ticker : str
        The ticker symbol to fetch (e.g. "NVDA", "SPY").
    start_date : str
        First date to include, in "YYYY-MM-DD" format (inclusive).
    end_date : str
        Last date to include, in "YYYY-MM-DD" format (exclusive — yfinance
        treats this as the day after the last bar you want, matching the
        standard [start, end) convention used by pandas date_range).

    Returns
    -------
    pd.DataFrame
        DataFrame indexed by date with columns: Open, High, Low, Close, Volume.
        All values are floats except Volume (int). Index is timezone-naive.

    Raises
    ------
    ValueError
        If yfinance returns no data — e.g. the ticker is invalid, delisted,
        or no trading days fall within the requested range.

    Example
    -------
    >>> df = get_ohlcv("NVDA", "2026-01-01", "2026-06-01")
    >>> print(df.head())
    """
    raw = yf.download(ticker, start=start_date, end=end_date, auto_adjust=True, progress=False)

    if raw.empty:
        raise ValueError(
            f"No OHLCV data returned for '{ticker}' between {start_date} and {end_date}. "
            "Check that the ticker is valid and that trading days exist in the requested range."
        )

    df = raw[["Open", "High", "Low", "Close", "Volume"]].copy()

    # Flatten MultiIndex columns that yfinance sometimes produces (ticker as second level)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Drop timezone info so callers get a plain DatetimeIndex
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    df.attrs["ticker"] = ticker.upper()
    return df


class MarketDataClient:
    """Thin wrapper intended for future multi-provider support (Alpha Vantage, Polygon).

    Daily bars are fetched via yfinance (no key required).
    Intraday bars and live price use Alpha Vantage TIME_SERIES_INTRADAY (requires
    ALPHA_VANTAGE_API_KEY in environment). If the key is absent, intraday methods
    fall back to yfinance so the pipeline continues without error.
    """

    def __init__(self, config: dict):
        self.config = config
        self.api_key: str | None = os.getenv("ALPHA_VANTAGE_API_KEY")
        self.base_url: str = config.get("api", {}).get("alpha_vantage_base_url", _BASE_URL)
        self._cache_dir = Path("data/raw/intraday")
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        if not self.api_key:
            logger.warning(
                "ALPHA_VANTAGE_API_KEY not set — intraday methods will fall back to yfinance. "
                "Add the key to your .env file for real-time Alpha Vantage data."
            )

    def get_daily_ohlcv(self, ticker: str, period_days: int) -> pd.DataFrame:
        """Return daily OHLCV bars for the given ticker and lookback period."""
        end = pd.Timestamp.today().normalize()
        start = end - pd.Timedelta(days=period_days)
        return get_ohlcv(ticker, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    def get_intraday_ohlcv(self, ticker: str, interval_minutes: int = 5) -> pd.DataFrame:
        """Return intraday OHLCV bars from Alpha Vantage TIME_SERIES_INTRADAY.

        Fetches the 100 most recent bars at the given minute interval for regular
        trading hours (9:30am–4:00pm ET). Results are cached once per
        ticker/interval/calendar-day to avoid burning free-tier quota on repeated runs.

        Falls back to yfinance if ALPHA_VANTAGE_API_KEY is not set.

        Parameters
        ----------
        ticker : str
            Equity symbol (e.g. "NVDA").
        interval_minutes : int
            Bar size in minutes. AV supports: 1, 5, 15, 30, 60.

        Returns
        -------
        pd.DataFrame
            DatetimeIndex (US/Eastern timestamps), columns: Open, High, Low, Close, Volume.

        Raises
        ------
        ValueError
            If AV returns no data or signals a rate-limit error.
        """
        interval_str = f"{interval_minutes}min"

        if not self.api_key:
            return self._yf_intraday_fallback(ticker, interval_minutes)

        today = datetime.utcnow().strftime("%Y-%m-%d")
        cached = self._load_cache(ticker, today, interval_str)
        if cached is not None:
            return cached

        params = {
            "function": "TIME_SERIES_INTRADAY",
            "symbol": ticker.upper(),
            "interval": interval_str,
            "adjusted": "true",
            "extended_hours": "false",
            "outputsize": "compact",  # 100 most recent bars
            "datatype": "json",
            "apikey": self.api_key,
        }

        try:
            resp = requests.get(self.base_url, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            raise ValueError(f"Alpha Vantage intraday request failed for {ticker}: {exc}") from exc

        if "Information" in data:
            raise ValueError(
                f"Alpha Vantage rate limit hit for {ticker}: {data['Information']}"
            )

        series_key = f"Time Series ({interval_str})"
        time_series = data.get(series_key, {})
        if not time_series:
            raise ValueError(
                f"No intraday data returned for {ticker} at {interval_str} interval. "
                f"Keys in response: {list(data.keys())}"
            )

        records = [
            {
                "datetime": pd.Timestamp(ts),
                "Open": float(values["1. open"]),
                "High": float(values["2. high"]),
                "Low": float(values["3. low"]),
                "Close": float(values["4. close"]),
                "Volume": int(values["5. volume"]),
            }
            for ts, values in time_series.items()
        ]

        df = pd.DataFrame(records).set_index("datetime").sort_index()
        df.attrs["ticker"] = ticker.upper()

        self._save_cache(ticker, today, interval_str, df)
        time.sleep(_RATE_LIMIT_SLEEP)
        return df

    def get_current_price(self, ticker: str) -> float:
        """Return the latest trade price for the given ticker.

        Uses the most recent 5-minute bar close from Alpha Vantage intraday feed.
        Falls back to the last daily close via yfinance if the AV key is absent.
        """
        if not self.api_key:
            df = self.get_daily_ohlcv(ticker, period_days=5)
            return float(df["Close"].iloc[-1])

        df = self.get_intraday_ohlcv(ticker, interval_minutes=5)
        return float(df["Close"].iloc[-1])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _cache_path(self, ticker: str, date_str: str, interval: str) -> Path:
        ticker_dir = self._cache_dir / ticker.upper()
        ticker_dir.mkdir(parents=True, exist_ok=True)
        return ticker_dir / f"{date_str}_{interval}.json"

    def _save_cache(self, ticker: str, date_str: str, interval: str, df: pd.DataFrame) -> None:
        records = df.reset_index()
        records["datetime"] = records["datetime"].astype(str)
        with open(self._cache_path(ticker, date_str, interval), "w") as f:
            json.dump(records.to_dict("records"), f)

    def _load_cache(self, ticker: str, date_str: str, interval: str) -> pd.DataFrame | None:
        path = self._cache_path(ticker, date_str, interval)
        if not path.exists():
            return None
        with open(path) as f:
            records = json.load(f)
        df = pd.DataFrame(records)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime").sort_index()
        df.attrs["ticker"] = ticker.upper()
        return df

    def _yf_intraday_fallback(self, ticker: str, interval_minutes: int) -> pd.DataFrame:
        """Fetch intraday bars from yfinance when no AV key is available."""
        valid_intervals = {1: "1m", 2: "2m", 5: "5m", 15: "15m", 30: "30m", 60: "60m"}
        yf_interval = valid_intervals.get(interval_minutes, "5m")
        raw = yf.download(ticker, period="1d", interval=yf_interval, progress=False)
        if raw.empty:
            raise ValueError(f"No intraday data returned for {ticker} via yfinance fallback")
        df = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df.attrs["ticker"] = ticker.upper()
        return df
