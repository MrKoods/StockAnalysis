"""
Tests for shared/api_clients/market_data_client.py's incomplete-bar trimming.

yfinance includes an in-progress bar for the current calendar day whenever a
daily-interval request is made during market hours (including pre-market) —
Open/Volume may already have partial prints, but Close stays NaN until the
session actually closes. fetch_ohlcv() and fetch_ohlcv_batch() must trim any
such trailing row so downstream indicators never see a NaN close.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from shared.api_clients.market_data_client import (
    _trim_incomplete_last_bar,
    fetch_ohlcv,
    fetch_ohlcv_batch,
)


def _ohlcv_df(n=65, nan_last_close=False):
    close = np.linspace(100, 110, n)
    df = pd.DataFrame({
        "Open": close * 0.99,
        "High": close * 1.01,
        "Low": close * 0.98,
        "Close": close,
        "Volume": [1_000_000] * n,
    }, index=pd.date_range("2025-01-01", periods=n, freq="B"))
    if nan_last_close:
        df.loc[df.index[-1], "Close"] = float("nan")
    return df


class TestTrimIncompleteLastBar:
    def test_drops_trailing_nan_close_row(self):
        df = _ohlcv_df(nan_last_close=True)
        trimmed = _trim_incomplete_last_bar(df)
        assert len(trimmed) == len(df) - 1
        assert not pd.isna(trimmed["Close"].iloc[-1])

    def test_leaves_complete_data_untouched(self):
        df = _ohlcv_df(nan_last_close=False)
        trimmed = _trim_incomplete_last_bar(df)
        assert len(trimmed) == len(df)

    def test_empty_input_returns_empty(self):
        df = _ohlcv_df(n=0)
        trimmed = _trim_incomplete_last_bar(df)
        assert trimmed.empty

    def test_all_nan_close_returns_empty(self):
        df = _ohlcv_df(n=3)
        df["Close"] = float("nan")
        trimmed = _trim_incomplete_last_bar(df)
        assert trimmed.empty


class TestFetchOhlcvTrimsIncompleteBar:
    def test_single_ticker_fetch_trims_nan_close(self):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value = _ohlcv_df(nan_last_close=True)
        with patch("shared.api_clients.market_data_client.yf.Ticker", return_value=mock_ticker):
            df = fetch_ohlcv("NVDA")
        assert df is not None
        assert not pd.isna(df["Close"].iloc[-1])

    def test_batch_fetch_trims_nan_close(self):
        tickers = ["NVDA", "AMD"]
        raw = pd.concat(
            {t: _ohlcv_df(nan_last_close=True) for t in tickers},
            axis=1,
        )
        with patch("shared.api_clients.market_data_client.yf.download", return_value=raw):
            result = fetch_ohlcv_batch(tickers)
        for t in tickers:
            assert result[t] is not None
            assert not pd.isna(result[t]["Close"].iloc[-1])
