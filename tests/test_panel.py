"""
Tests for research/panel.py — Phase 1 data assembly.

No network: the yfinance response shapes are constructed directly, which is the
point. The single-symbol MultiIndex case below is a regression test for a real
bug found by running the download path against live yfinance 1.4.1 during the
Phase 0 review.
"""

import pandas as pd
import pytest

from research import config, panel


def _ohlcv(n=10, start="2024-01-01", close_base=100.0):
    idx = pd.date_range(start, periods=n, freq="B")
    return pd.DataFrame(
        {
            "Open": [close_base] * n,
            "High": [close_base + 1] * n,
            "Low": [close_base - 1] * n,
            "Close": [close_base + i for i in range(n)],
            "Volume": [1_000_000] * n,
        },
        index=idx,
    )


def _multi_frame(symbols, n=10):
    """A yfinance group_by='ticker' response: MultiIndex (symbol, field) columns."""
    frames = {s: _ohlcv(n, close_base=100.0 + 10 * i) for i, s in enumerate(symbols)}
    return pd.concat(frames, axis=1)


class TestExtractSymbol:
    def test_extracts_one_symbol_from_a_multi_symbol_response(self):
        raw = _multi_frame(["AAPL", "MSFT"])
        frame = panel._extract_symbol(raw, "AAPL")
        assert list(frame.columns) == ["Open", "High", "Low", "Close", "Volume"]
        assert frame["Close"].iloc[0] == 100.0

    def test_single_symbol_response_is_still_multiindex(self):
        # Regression: yfinance with group_by="ticker" returns MultiIndex columns
        # even for a batch of one. The original code special-cased len(batch)==1
        # and returned the raw frame, whose ["Close"] raised KeyError.
        raw = _multi_frame(["AAPL"])
        assert isinstance(raw.columns, pd.MultiIndex)
        frame = panel._extract_symbol(raw, "AAPL")
        assert frame is not None
        frame["Close"].dropna()  # must not raise

    def test_flat_columns_are_passed_through(self):
        raw = _ohlcv()
        assert panel._extract_symbol(raw, "AAPL") is raw

    def test_symbol_absent_from_response_returns_none(self):
        raw = _multi_frame(["AAPL", "MSFT"])
        assert panel._extract_symbol(raw, "NVDA") is None


class TestStorageRoundTrip:
    def test_write_then_read_preserves_frame_and_index(self, tmp_path):
        frame = _ohlcv(50)
        path = tmp_path / "t.pkl"
        panel._write_frame(frame, path)
        back = panel._read_frame(path)
        assert back.equals(frame)
        assert back.index.equals(frame.index)


@pytest.fixture
def cached_panel(tmp_path, monkeypatch):
    """A small on-disk panel spanning both sample windows."""
    idx = pd.date_range("2004-06-01", "2026-06-01", freq="BME")
    prices = pd.DataFrame(
        {"AAA": range(len(idx)), "BBB": range(len(idx))}, index=idx, dtype="float64"
    ) + 100.0
    volumes = prices * 1000.0
    context = pd.DataFrame({"SPY": range(len(idx))}, index=idx, dtype="float64") + 400.0

    monkeypatch.setattr(panel, "_PRICE_PANEL", tmp_path / "prices.pkl")
    monkeypatch.setattr(panel, "_VOLUME_PANEL", tmp_path / "dollar_volume.pkl")
    monkeypatch.setattr(panel, "_CONTEXT_PANEL", tmp_path / "context.pkl")
    panel._write_frame(prices, panel._PRICE_PANEL)
    panel._write_frame(volumes, panel._VOLUME_PANEL)
    panel._write_frame(context, panel._CONTEXT_PANEL)
    return prices


class TestLoadPanel:
    def test_defaults_to_the_in_sample_window(self, cached_panel):
        # The safe default matters: a "full" default would quietly hand
        # out-of-sample data to a Phase 2-5 script that forgot to ask.
        loaded = panel.load_panel()
        assert loaded["sample"] == "in"
        assert loaded["prices"].index.max() <= pd.Timestamp(config.IN_SAMPLE_END)

    def test_in_sample_hides_every_out_of_sample_date(self, cached_panel):
        loaded = panel.load_panel("in")
        for key in ("prices", "dollar_volume", "context"):
            assert loaded[key].index.max() <= pd.Timestamp(config.IN_SAMPLE_END)

    def test_in_sample_keeps_pre_start_history_for_formation_warmup(self, cached_panel):
        # Formation windows look back 252 days, so the left edge is deliberately
        # NOT truncated — callers slice signals, not inputs.
        loaded = panel.load_panel("in")
        assert loaded["prices"].index.min() < pd.Timestamp(config.IN_SAMPLE_START)
        assert loaded["signal_start"] == config.IN_SAMPLE_START

    def test_out_of_sample_must_be_asked_for_explicitly(self, cached_panel):
        loaded = panel.load_panel("out")
        assert loaded["prices"].index.max() > pd.Timestamp(config.IN_SAMPLE_END)
        assert loaded["signal_start"] == config.OUT_OF_SAMPLE_START

    def test_unknown_sample_name_raises(self, cached_panel):
        with pytest.raises(ValueError, match="sample must be"):
            panel.load_panel("everything")

    def test_missing_cache_names_the_command_that_builds_it(self, tmp_path, monkeypatch):
        monkeypatch.setattr(panel, "_PRICE_PANEL", tmp_path / "absent.pkl")
        with pytest.raises(FileNotFoundError, match="research.panel --download"):
            panel.load_panel("in")


class TestVerifyPanel:
    def test_reports_shape_coverage_and_alignment(self, cached_panel):
        report = panel.verify_panel()
        assert report["n_tickers"] == 2
        assert report["duplicate_dates"] == 0
        assert report["index_monotonic"] is True
        assert report["non_positive_prices"] == 0
        assert report["volume_panel_index_aligned"] is True
        assert report["volume_panel_columns_aligned"] is True
        assert report["context_leaked_into_prices"] == []
        assert report["median_coverage"] == 1.0

    def test_flags_a_context_ticker_leaking_into_the_tradeable_universe(
        self, cached_panel, monkeypatch, tmp_path
    ):
        leaked = cached_panel.copy()
        leaked["SPY"] = 400.0
        panel._write_frame(leaked, panel._PRICE_PANEL)
        report = panel.verify_panel()
        assert report["context_leaked_into_prices"] == ["SPY"]
        # Columns now disagree between the price and volume panels.
        assert report["volume_panel_columns_aligned"] is False

    def test_flags_unadjusted_split_style_jumps(self, cached_panel):
        broken = cached_panel.copy()
        broken.iloc[10, 0] = broken.iloc[9, 0] * 4  # a 4:1 split left unadjusted
        panel._write_frame(broken, panel._PRICE_PANEL)
        assert panel.verify_panel()["extreme_daily_moves"] > 0

    def test_flags_non_positive_prices(self, cached_panel):
        broken = cached_panel.copy()
        broken.iloc[5, 1] = 0.0
        panel._write_frame(broken, panel._PRICE_PANEL)
        assert panel.verify_panel()["non_positive_prices"] == 1
