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
    fetch_vix_and_pct_change,
)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    """Never actually wait for retry_with_backoff's real delays — a failed
    fetch in these tests should fail fast, not burn through the real
    30s/60s/120s backoff ladder (same pattern as test_sentiment_client.py)."""
    monkeypatch.setattr("shared.api_clients._http_backoff.time.sleep", lambda s: None)


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


class TestFetchOhlcvBatchCaching:
    """
    2026-08-23 full model audit: run_pipeline() (period="6mo") and
    _fetch_market_context() (period="3mo") both call fetch_ohlcv_batch() for
    a heavily-overlapping ticker set seconds apart in the same scan — this
    dedups that within one process lifetime. tests/conftest.py's autouse
    _isolate_ohlcv_cache fixture clears _OHLCV_BATCH_CACHE before every test.
    """

    def test_second_call_for_same_ticker_and_period_skips_yfinance(self):
        tickers = ["NVDA", "AMD"]
        raw = pd.concat({t: _ohlcv_df() for t in tickers}, axis=1)
        with patch("shared.api_clients.market_data_client.yf.download", return_value=raw) as mock_dl:
            fetch_ohlcv_batch(tickers, period="6mo")
            fetch_ohlcv_batch(tickers, period="6mo")
        mock_dl.assert_called_once()

    def test_shorter_period_request_is_served_from_a_longer_cached_fetch(self):
        """A 3mo request after a 6mo fetch for the same ticker must be a
        cache hit — 6mo of history already covers whatever a 3mo consumer
        needs, exactly the run_pipeline-then-_fetch_market_context ordering
        in both real pipelines."""
        tickers = ["NVDA"]
        raw_df = _ohlcv_df()
        with patch("shared.api_clients.market_data_client.yf.Ticker") as mock_ticker_cls:
            mock_ticker_cls.return_value.history.return_value = raw_df
            fetch_ohlcv_batch(tickers, period="6mo")
        with patch("shared.api_clients.market_data_client.yf.download") as mock_dl:
            result = fetch_ohlcv_batch(tickers, period="3mo")
        mock_dl.assert_not_called()
        assert result["NVDA"] is not None

    def test_longer_period_request_after_shorter_cached_fetch_refetches(self):
        """The inverse must NOT be a cache hit — 3mo cached data doesn't
        satisfy a later 6mo request, so this must hit yfinance for real.
        Single ticker throughout, so both calls take fetch_ohlcv_batch's
        single-ticker fast path (yf.Ticker), same as the caching hit test
        above — this isolates the period-comparison logic specifically,
        not the multi-vs-single-ticker dispatch (covered separately below)."""
        tickers = ["NVDA"]
        with patch("shared.api_clients.market_data_client.yf.Ticker") as mock_ticker_cls:
            mock_ticker_cls.return_value.history.return_value = _ohlcv_df()
            fetch_ohlcv_batch(tickers, period="3mo")
            assert mock_ticker_cls.call_count == 1
            fetch_ohlcv_batch(tickers, period="6mo")
            assert mock_ticker_cls.call_count == 2  # cache miss -> refetched for real

    def test_different_tickers_do_not_collide_in_the_cache(self):
        """Caching NVDA must not satisfy a later request for AMD/TSM — and
        once NVDA is cached, a mixed request for all three must only fetch
        the two genuinely-uncached tickers, not re-fetch NVDA too."""
        with patch("shared.api_clients.market_data_client.yf.Ticker") as mock_ticker_cls:
            mock_ticker_cls.return_value.history.return_value = _ohlcv_df()
            fetch_ohlcv_batch(["NVDA"], period="6mo")
        raw = pd.concat({t: _ohlcv_df() for t in ("AMD", "TSM")}, axis=1)
        with patch("shared.api_clients.market_data_client.yf.download", return_value=raw) as mock_dl:
            result = fetch_ohlcv_batch(["NVDA", "AMD", "TSM"], period="6mo")
        mock_dl.assert_called_once()
        assert mock_dl.call_args.kwargs["tickers"] == "AMD TSM"  # NVDA excluded — served from cache
        assert result["NVDA"] is not None
        assert result["AMD"] is not None
        assert result["TSM"] is not None

    def test_a_failed_fetch_does_not_populate_the_cache(self):
        with patch("shared.api_clients.market_data_client.yf.download", return_value=pd.DataFrame()):
            first = fetch_ohlcv_batch(["NVDA", "AMD"], period="6mo")
        assert first["NVDA"] is None
        raw = pd.concat({t: _ohlcv_df() for t in ("NVDA", "AMD")}, axis=1)
        with patch("shared.api_clients.market_data_client.yf.download", return_value=raw) as mock_dl:
            second = fetch_ohlcv_batch(["NVDA", "AMD"], period="6mo")
        mock_dl.assert_called_once()  # a prior failure must not be "cached" as a permanent None
        assert second["NVDA"] is not None


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


class TestFetchVixAndPctChange:
    """
    2026-08-23 full model audit: _fetch_market_context() called fetch_vix()
    AND fetch_vix_pct_change() independently — two full yf.download("^VIX")
    round trips every scan for data that's a strict subset of one another.
    fetch_vix_and_pct_change() does one fetch and derives both.
    """

    def _vix_df(self, closes):
        return pd.DataFrame({"Close": closes}, index=pd.date_range("2026-01-01", periods=len(closes), freq="B"))

    def test_one_download_call_returns_both_values(self):
        with patch("shared.api_clients.market_data_client.yf.download", return_value=self._vix_df([20.0, 28.0])) as mock_dl:
            latest, pct_change = fetch_vix_and_pct_change()
        mock_dl.assert_called_once()
        assert latest == pytest.approx(28.0)
        assert pct_change == pytest.approx((28.0 - 20.0) / 20.0)

    def test_single_bar_returns_latest_but_no_pct_change(self):
        with patch("shared.api_clients.market_data_client.yf.download", return_value=self._vix_df([20.0])):
            latest, pct_change = fetch_vix_and_pct_change()
        assert latest == pytest.approx(20.0)
        assert pct_change is None

    def test_empty_response_returns_both_none(self):
        with patch("shared.api_clients.market_data_client.yf.download", return_value=pd.DataFrame()):
            latest, pct_change = fetch_vix_and_pct_change(retries=1)
        assert latest is None
        assert pct_change is None

    def test_zero_prior_close_returns_latest_but_no_pct_change(self):
        with patch("shared.api_clients.market_data_client.yf.download", return_value=self._vix_df([0.0, 15.0])):
            latest, pct_change = fetch_vix_and_pct_change()
        assert latest == pytest.approx(15.0)
        assert pct_change is None
