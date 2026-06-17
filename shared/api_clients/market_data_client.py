import pandas as pd
import yfinance as yf


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

    For now, delegate to the module-level get_ohlcv() for daily bars.
    """

    def __init__(self, config: dict):
        self.config = config

    def get_daily_ohlcv(self, ticker: str, period_days: int) -> pd.DataFrame:
        """Return daily OHLCV bars for the given ticker and lookback period."""
        end = pd.Timestamp.today().normalize()
        start = end - pd.Timedelta(days=period_days)
        return get_ohlcv(ticker, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    def get_intraday_ohlcv(self, ticker: str, interval_minutes: int) -> dict:
        """Return intraday OHLCV bars at the specified minute interval for today's session."""
        pass

    def get_current_price(self, ticker: str) -> float:
        """Return the latest trade price for the given ticker."""
        pass
