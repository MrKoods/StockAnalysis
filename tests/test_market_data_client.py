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
import pytest

from shared.api_clients.market_data_client import (
    _trim_incomplete_last_bar,
    fetch_ohlcv,
    fetch_ohlcv_batch,
    fetch_vix_pct_change,
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


class TestFetchVixPctChange:
    """
    fetch_vix() only ever returned the latest level and discarded the prior
    close needed to compute a % change — the input black_swan_detector.
    check_black_swan() actually needs for its vix spike check. This covers
    the new fetch_vix_pct_change() that fixes that gap.
    """

    def _vix_df(self, closes):
        return pd.DataFrame({"Close": closes}, index=pd.date_range("2026-01-01", periods=len(closes), freq="B"))

    def test_computes_pct_change_from_last_two_closes(self):
        with patch("shared.api_clients.market_data_client.yf.download", return_value=self._vix_df([20.0, 28.0])):
            result = fetch_vix_pct_change()
        assert result == pytest.approx((28.0 - 20.0) / 20.0)

    def test_none_on_empty_response(self):
        with patch("shared.api_clients.market_data_client.yf.download", return_value=pd.DataFrame()):
            result = fetch_vix_pct_change(retries=1)
        assert result is None

    def test_none_when_fewer_than_two_bars(self):
        with patch("shared.api_clients.market_data_client.yf.download", return_value=self._vix_df([20.0])):
            result = fetch_vix_pct_change()
        assert result is None
