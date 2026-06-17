# SHARED: Core technical indicator math — moving averages, breakout detection, and relative strength.
# Both swing and day models import from here; the same formulas are fed different timeframe data
# (daily bars for swing, intraday bars for day). No model-specific logic lives here.

import pandas as pd


def moving_average(df: pd.DataFrame, window: int, column: str = "Close") -> pd.Series:
    """Compute the simple moving average (SMA) of a DataFrame column.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV DataFrame as returned by market_data_client.get_ohlcv.
    window : int
        Number of periods to average over.
    column : str, optional
        Column name to apply the SMA to. Defaults to "Close".

    Returns
    -------
    pd.Series
        SMA values indexed identically to df. The first (window - 1) values are NaN.

    Example
    -------
    >>> ma20 = moving_average(df, window=20)
    """
    return df[column].rolling(window=window).mean()


def rolling_high(df: pd.DataFrame, window: int, column: str = "High") -> pd.Series:
    """Compute the rolling maximum over a given window (used for breakout detection).

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV DataFrame as returned by market_data_client.get_ohlcv.
    window : int
        Number of periods to look back.
    column : str, optional
        Column name to apply the rolling max to. Defaults to "High".

    Returns
    -------
    pd.Series
        Rolling maximum values indexed identically to df.

    Example
    -------
    >>> highs = rolling_high(df, window=20)
    """
    return df[column].rolling(window=window).max()


def rolling_low(df: pd.DataFrame, window: int, column: str = "Low") -> pd.Series:
    """Compute the rolling minimum over a given window.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV DataFrame as returned by market_data_client.get_ohlcv.
    window : int
        Number of periods to look back.
    column : str, optional
        Column name to apply the rolling min to. Defaults to "Low".

    Returns
    -------
    pd.Series
        Rolling minimum values indexed identically to df.

    Example
    -------
    >>> lows = rolling_low(df, window=20)
    """
    return df[column].rolling(window=window).min()


def average_volume(df: pd.DataFrame, window: int) -> pd.Series:
    """Compute the rolling average of the Volume column.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV DataFrame as returned by market_data_client.get_ohlcv.
    window : int
        Number of periods to average over.

    Returns
    -------
    pd.Series
        Rolling average volume indexed identically to df.

    Example
    -------
    >>> avg_vol = average_volume(df, window=20)
    """
    return df["Volume"].rolling(window=window).mean()


def is_breakout(
    df: pd.DataFrame,
    lookback_window: int = 20,
    volume_multiplier: float = 1.5,
) -> pd.Series:
    """Detect volume-confirmed breakout days.

    A breakout is True on any day where today's Close is strictly greater than
    the rolling high of the PRIOR lookback_window days (today excluded), AND
    today's Volume is strictly greater than volume_multiplier times the rolling
    average volume of the same prior window.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV DataFrame as returned by market_data_client.get_ohlcv.
    lookback_window : int, optional
        Number of prior trading days to evaluate. Defaults to 20.
    volume_multiplier : float, optional
        Volume threshold multiplier relative to the rolling average. Defaults to 1.5.

    Returns
    -------
    pd.Series
        Boolean Series (True = breakout day) indexed identically to df.

    Example
    -------
    >>> breakouts = is_breakout(df, lookback_window=20, volume_multiplier=1.5)
    """
    # Shift by 1 so today's bar is excluded from the lookback window
    prior_high = df["High"].rolling(window=lookback_window).max().shift(1)
    prior_avg_vol = df["Volume"].rolling(window=lookback_window).mean().shift(1)

    price_break = df["Close"] > prior_high
    volume_break = df["Volume"] > volume_multiplier * prior_avg_vol

    return (price_break & volume_break).rename("is_breakout")


def relative_strength(
    ticker_df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    window: int = 20,
) -> pd.Series:
    """Compute the ticker's trailing return minus the benchmark's trailing return.

    For each date, calculates the percent return of the ticker's Close over the
    prior `window` trading days, then subtracts the same calculation for the
    benchmark. This measures relative outperformance or underperformance.

    Both DataFrames are aligned on the intersection of their date indices before
    calculation. Dates present in one but not the other are silently dropped;
    the returned Series is indexed to this intersection only.

    Parameters
    ----------
    ticker_df : pd.DataFrame
        OHLCV DataFrame for the ticker (e.g. NVDA).
    benchmark_df : pd.DataFrame
        OHLCV DataFrame for the benchmark (e.g. SMH or SPY).
    window : int, optional
        Number of trading days for the trailing return calculation. Defaults to 20.

    Returns
    -------
    pd.Series
        Relative strength values (ticker return minus benchmark return) on the
        intersection of both DataFrames' date indices. Values in the first
        `window` rows will be NaN.

    Example
    -------
    >>> rs = relative_strength(nvda_df, smh_df, window=20)
    """
    common_dates = ticker_df.index.intersection(benchmark_df.index)
    ticker_close = ticker_df.loc[common_dates, "Close"]
    bench_close = benchmark_df.loc[common_dates, "Close"]

    ticker_return = ticker_close.pct_change(periods=window)
    bench_return = bench_close.pct_change(periods=window)

    return (ticker_return - bench_return).rename("relative_strength")


def _ema(series: pd.Series, span: int) -> pd.Series:
    """Exponential moving average using the standard span convention (alpha = 2 / (span + 1))."""
    return series.ewm(span=span, adjust=False).mean()


def rsi(df: pd.DataFrame, window: int = 14, column: str = "Close") -> pd.Series:
    """Compute the Relative Strength Index (RSI) using Wilder's smoothing method.

    RSI = 100 - (100 / (1 + avg_gain / avg_loss)), where avg_gain and avg_loss
    are smoothed with Wilder's EMA (alpha = 1 / window). Values above 70 are
    typically considered overbought; values below 30 are typically considered
    oversold.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV DataFrame as returned by market_data_client.get_ohlcv.
    window : int, optional
        Lookback period for the smoothed averages. Defaults to 14.
    column : str, optional
        Column to compute RSI on. Defaults to "Close".

    Returns
    -------
    pd.Series
        RSI values in the range [0, 100] indexed identically to df. The first
        (window) values are NaN due to the warm-up period.

    Example
    -------
    >>> rsi14 = rsi(df, window=14)
    """
    delta = df[column].diff()
    gains = delta.clip(lower=0)
    losses = (-delta).clip(lower=0)

    # Wilder's smoothing: alpha = 1/window, equivalent to com = window - 1
    avg_gain = gains.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    avg_loss = losses.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()

    rs = avg_gain / avg_loss
    return (100.0 - (100.0 / (1.0 + rs))).rename("rsi")


def atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    """Compute the Average True Range (ATR) using Wilder's smoothing method.

    True range for each bar is the greatest of: (High - Low),
    abs(High - previous Close), abs(Low - previous Close). ATR is the
    Wilder's-smoothed rolling average of true range over `window` periods.
    Commonly used to size stop-losses: e.g., stop = entry_price - 2 * ATR
    for a long position.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV DataFrame as returned by market_data_client.get_ohlcv.
    window : int, optional
        Lookback period for smoothing. Defaults to 14.

    Returns
    -------
    pd.Series
        ATR values indexed identically to df. The first value is NaN because
        true range requires a previous close; ATR itself is NaN for the first
        (window) rows during warm-up.

    Example
    -------
    >>> atr14 = atr(df, window=14)
    """
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return tr.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean().rename("atr")


def macd(
    df: pd.DataFrame,
    fast_window: int = 12,
    slow_window: int = 26,
    signal_window: int = 9,
    column: str = "Close",
) -> pd.DataFrame:
    """Compute MACD line, signal line, and histogram.

    MACD line = EMA(fast_window) - EMA(slow_window).
    Signal line = EMA(signal_window) of the MACD line.
    Histogram = MACD line - signal line.
    All EMAs use the standard span convention (alpha = 2 / (span + 1)).

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV DataFrame as returned by market_data_client.get_ohlcv.
    fast_window : int, optional
        Span for the fast EMA. Defaults to 12.
    slow_window : int, optional
        Span for the slow EMA. Defaults to 26.
    signal_window : int, optional
        Span for the signal-line EMA applied to the MACD line. Defaults to 9.
    column : str, optional
        Column to compute MACD on. Defaults to "Close".

    Returns
    -------
    pd.DataFrame
        DataFrame with columns "macd", "signal", and "histogram", indexed
        identically to df. The first (slow_window - 1) rows of "macd" will be
        NaN, and "signal"/"histogram" will have additional NaN rows during
        signal warm-up.

    Example
    -------
    >>> m = macd(df); print(m[["macd", "signal", "histogram"]].tail())
    """
    macd_line = _ema(df[column], fast_window) - _ema(df[column], slow_window)
    signal_line = _ema(macd_line, signal_window)
    histogram = macd_line - signal_line

    return pd.DataFrame(
        {"macd": macd_line, "signal": signal_line, "histogram": histogram},
        index=df.index,
    )
