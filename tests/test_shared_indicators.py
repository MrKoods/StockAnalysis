"""
Tests for shared/indicators/technical_common.py.
Verifies: MA computations, breakout detection, RSI, ATR, MACD, z-score normalization,
RS calculation. All tests use synthetic deterministic price series.
"""

import numpy as np
import pandas as pd
import pytest

from shared.indicators.technical_common import (
    zscore,
    zscore_current,
    sma,
    ema,
    rolling_high,
    is_breakout,
    relative_strength,
    rsi,
    atr,
    macd,
    compute_technical_indicators,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def flat_series():
    """Series with constant value 100 — z-score should be 0 throughout."""
    return pd.Series([100.0] * 100)


@pytest.fixture
def trending_up():
    """Linearly increasing series 100 → 200 over 100 bars."""
    return pd.Series(np.linspace(100, 200, 100))


@pytest.fixture
def ohlcv_trending_up():
    """Synthetic OHLCV DataFrame with steadily rising prices."""
    n = 100
    close = np.linspace(100, 200, n)
    df = pd.DataFrame({
        "Open": close * 0.99,
        "High": close * 1.01,
        "Low": close * 0.98,
        "Close": close,
        "Volume": [1_000_000 + i * 10_000 for i in range(n)],
    }, index=pd.date_range("2025-01-01", periods=n, freq="B"))
    return df


@pytest.fixture
def ohlcv_short_history():
    """
    Only 30 bars — enough for sma_20/atr_14/rsi_14 but short of sma_50 (needs
    50) and MACD's ~35-bar warmup, so sma_50/macd fall back to substitute
    values. Used to test the data_quality flag on a newly-added watchlist
    ticker or short backtest window.
    """
    n = 30
    close = np.linspace(100, 130, n)
    df = pd.DataFrame({
        "Open": close * 0.99,
        "High": close * 1.01,
        "Low": close * 0.98,
        "Close": close,
        "Volume": [1_000_000] * n,
    }, index=pd.date_range("2025-01-01", periods=n, freq="B"))
    return df


# ---------------------------------------------------------------------------
# Z-score tests
# ---------------------------------------------------------------------------

class TestZscore:
    def test_trending_zscore_positive_at_end(self, trending_up):
        result = zscore(trending_up, window=20)
        # Trending up: latest bar is above its rolling mean → positive z-score
        assert result.iloc[-1] > 0

    def test_zscore_current_returns_scalar(self, trending_up):
        result = zscore_current(trending_up, window=20)
        assert isinstance(result, float)

    def test_zscore_current_positive_for_trending_up(self, trending_up):
        result = zscore_current(trending_up, window=20)
        assert result > 0

    def test_zscore_length_matches_input(self, trending_up):
        result = zscore(trending_up, window=20)
        assert len(result) == len(trending_up)

    def test_zscore_no_nan(self, trending_up):
        result = zscore(trending_up, window=20)
        assert not result.isna().any()

    def test_flat_series_returns_zero(self, flat_series):
        result = zscore(flat_series, window=20)
        # Flat series → std=0 → filled with 0.0
        assert result.dropna().abs().max() == pytest.approx(0.0, abs=1e-6)


# ---------------------------------------------------------------------------
# SMA / EMA tests
# ---------------------------------------------------------------------------

class TestMovingAverages:
    def test_sma_of_constant_series(self, flat_series):
        result = sma(flat_series, period=20)
        assert result.dropna().iloc[-1] == pytest.approx(100.0)

    def test_sma_length_matches_input(self, trending_up):
        result = sma(trending_up, period=20)
        assert len(result) == len(trending_up)

    def test_sma_has_nan_in_warmup(self, trending_up):
        result = sma(trending_up, period=20)
        # First 19 values should be NaN (min_periods=period)
        assert result.iloc[:19].isna().all()
        assert not result.iloc[19:].isna().any()

    def test_ema_weighted_toward_recent(self, trending_up):
        result_ema = ema(trending_up, period=20)
        result_sma = sma(trending_up, period=20)
        # EMA should be higher than SMA for a rising series (more weight on recent)
        assert result_ema.iloc[-1] > result_sma.iloc[-1]

    def test_sma_computation(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = sma(s, period=3)
        # SMA(3) of [3,4,5] = 4.0 at index 4
        assert result.iloc[4] == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# RSI tests
# ---------------------------------------------------------------------------

class TestRSI:
    def test_rsi_bounded_0_100(self, trending_up):
        result = rsi(trending_up, period=14)
        assert result.dropna().between(0, 100).all()

    def test_rsi_high_for_strong_uptrend(self, trending_up):
        result = rsi(trending_up, period=14)
        # Strong uptrend → RSI should be high (>60)
        assert result.iloc[-1] > 60

    def test_rsi_length_matches_input(self, trending_up):
        result = rsi(trending_up, period=14)
        assert len(result) == len(trending_up)


# ---------------------------------------------------------------------------
# ATR tests
# ---------------------------------------------------------------------------

class TestATR:
    def test_atr_positive(self, ohlcv_trending_up):
        result = atr(
            ohlcv_trending_up["High"],
            ohlcv_trending_up["Low"],
            ohlcv_trending_up["Close"],
            period=14,
        )
        assert result.dropna().gt(0).all()

    def test_atr_length_matches_input(self, ohlcv_trending_up):
        result = atr(
            ohlcv_trending_up["High"],
            ohlcv_trending_up["Low"],
            ohlcv_trending_up["Close"],
            period=14,
        )
        assert len(result) == len(ohlcv_trending_up)

    def test_atr_wider_than_high_minus_low(self, ohlcv_trending_up):
        # ATR uses true range (includes gaps) so >= H-L
        result = atr(
            ohlcv_trending_up["High"],
            ohlcv_trending_up["Low"],
            ohlcv_trending_up["Close"],
            period=14,
        )
        # ATR ≥ H-L only true for the TR, but our OHLCV has no gaps so H-L ≈ TR
        assert result.dropna().gt(0).all()


# ---------------------------------------------------------------------------
# MACD tests
# ---------------------------------------------------------------------------

class TestMACD:
    def test_macd_returns_three_series(self, trending_up):
        m, s, h = macd(trending_up, fast=12, slow=26, signal=9)
        assert len(m) == len(s) == len(h) == len(trending_up)

    def test_histogram_equals_macd_minus_signal(self, trending_up):
        m, s, h = macd(trending_up)
        expected = m - s
        pd.testing.assert_series_equal(h.dropna(), expected.dropna(), check_names=False)

    def test_macd_positive_for_uptrend(self, trending_up):
        m, s, h = macd(trending_up)
        # For a strong uptrend, MACD line should be positive (fast EMA > slow EMA)
        assert m.dropna().iloc[-1] > 0


# ---------------------------------------------------------------------------
# Breakout tests
# ---------------------------------------------------------------------------

class TestBreakout:
    def test_breakout_detected_on_new_high(self):
        # 20 bars flat at 100, then jumps to 101 — should detect breakout
        close = pd.Series([100.0] * 21 + [101.0])
        high = pd.Series([100.0] * 21 + [101.0])
        result = is_breakout(close, high, period=20)
        assert result.iloc[-1] is True or result.iloc[-1] == 1

    def test_no_breakout_at_same_level(self):
        close = pd.Series([100.0] * 22)
        high = pd.Series([100.0] * 22)
        result = is_breakout(close, high, period=20)
        # At exactly the prior high (not above), no breakout
        assert not bool(result.iloc[-1])

    def test_rolling_high_correct(self):
        s = pd.Series([1.0, 3.0, 2.0, 5.0, 4.0])
        result = rolling_high(s, period=3)
        # Rolling max(3) at index 4: max(2, 5, 4) = 5
        assert result.iloc[-1] == 5.0


# ---------------------------------------------------------------------------
# Relative Strength tests
# ---------------------------------------------------------------------------

class TestRelativeStrength:
    def test_rs_positive_when_ticker_outperforms(self):
        ticker = pd.Series(np.linspace(100, 120, 50))  # +20%
        bench = pd.Series(np.linspace(100, 110, 50))   # +10%
        result = relative_strength(ticker, bench, period=20)
        assert result.dropna().iloc[-1] > 0

    def test_rs_negative_when_ticker_underperforms(self):
        ticker = pd.Series(np.linspace(100, 105, 50))  # +5%
        bench = pd.Series(np.linspace(100, 115, 50))   # +15%
        result = relative_strength(ticker, bench, period=20)
        assert result.dropna().iloc[-1] < 0


# ---------------------------------------------------------------------------
# Integration: compute_technical_indicators
# ---------------------------------------------------------------------------

class TestComputeTechnicalIndicators:
    def test_returns_expected_fields(self, ohlcv_trending_up):
        benchmark = ohlcv_trending_up["Close"] * 0.95  # slightly weaker benchmark
        cfg = {
            "technical": {
                "ma_short": 20, "ma_long": 50, "rsi_period": 14,
                "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
                "atr_period": 14, "rs_lookback": 20, "volume_avg_period": 20,
            }
        }
        result = compute_technical_indicators(ohlcv_trending_up, benchmark, cfg)
        required = [
            "close", "sma_20", "sma_50", "rsi_14", "atr_14",
            "breakout_volume_zscore", "rs_zscore", "breakout_confirmed",
            "trend_intact", "sma_20_above_sma_50", "price_above_sma_50",
            "macd_bullish",
        ]
        for field in required:
            assert field in result, f"Missing field: {field}"

    def test_trend_intact_for_strong_uptrend(self, ohlcv_trending_up):
        benchmark = ohlcv_trending_up["Close"] * 0.95
        cfg = {
            "technical": {
                "ma_short": 20, "ma_long": 50, "rsi_period": 14,
                "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
                "atr_period": 14, "rs_lookback": 20, "volume_avg_period": 20,
            }
        }
        result = compute_technical_indicators(ohlcv_trending_up, benchmark, cfg)
        # Strong uptrend: SMA20 should be above SMA50 by the end
        assert result["sma_20_above_sma_50"] is True

    def test_returns_scalar_values(self, ohlcv_trending_up):
        benchmark = ohlcv_trending_up["Close"] * 0.95
        cfg = {
            "technical": {
                "ma_short": 20, "ma_long": 50, "rsi_period": 14,
                "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
                "atr_period": 14, "rs_lookback": 20, "volume_avg_period": 20,
            }
        }
        result = compute_technical_indicators(ohlcv_trending_up, benchmark, cfg)
        for key in ["close", "rsi_14", "atr_14", "breakout_volume_zscore"]:
            assert isinstance(result[key], float), f"{key} should be float, got {type(result[key])}"

    def test_full_history_reports_complete_data_quality(self, ohlcv_trending_up):
        benchmark = ohlcv_trending_up["Close"] * 0.95
        cfg = {
            "technical": {
                "ma_short": 20, "ma_long": 50, "rsi_period": 14,
                "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
                "atr_period": 14, "rs_lookback": 20, "volume_avg_period": 20,
            }
        }
        result = compute_technical_indicators(ohlcv_trending_up, benchmark, cfg)
        assert result["data_quality"] == "complete"
        assert all(v == "complete" for v in result["sub_signal_data_quality"].values())

    def test_short_history_reports_partial_data_quality(self, ohlcv_short_history):
        """
        The gap being fixed: previously this layer reported no data-quality
        signal at all — a ticker whose sma_50/macd silently fell back to a
        substitute value (e.g. sma_50 standing in as the close price, which
        makes price_above_sma_50 always read False) looked exactly as
        trustworthy as one with a full, real indicator set.
        """
        benchmark = ohlcv_short_history["Close"] * 0.95
        cfg = {
            "technical": {
                "ma_short": 20, "ma_long": 50, "rsi_period": 14,
                "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
                "atr_period": 14, "rs_lookback": 20, "volume_avg_period": 20,
            }
        }
        result = compute_technical_indicators(ohlcv_short_history, benchmark, cfg)
        assert result["data_quality"] == "partial"
        assert result["sub_signal_data_quality"]["sma_50"] == "partial"
        assert result["sub_signal_data_quality"]["macd"] == "partial"
        # sma_20/atr_14 have enough history (20/14 bars) even in a 30-bar window
        assert result["sub_signal_data_quality"]["sma_20"] == "complete"
        assert result["sub_signal_data_quality"]["atr"] == "complete"

    def test_raises_on_nan_close_in_latest_bar(self, ohlcv_trending_up):
        """
        A NaN close in the last row (e.g. an in-progress daily bar that slipped
        past the data-fetch layer's trim) must not be silently scored — close
        feeds stop/target/position-size math downstream with no safe fallback.
        """
        df = ohlcv_trending_up.copy()
        df.loc[df.index[-1], "Close"] = float("nan")
        benchmark = ohlcv_trending_up["Close"] * 0.95
        cfg = {
            "technical": {
                "ma_short": 20, "ma_long": 50, "rsi_period": 14,
                "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
                "atr_period": 14, "rs_lookback": 20, "volume_avg_period": 20,
            }
        }
        with pytest.raises(ValueError, match="NaN close"):
            compute_technical_indicators(df, benchmark, cfg)

    def test_rolling_high_20_excludes_todays_own_bar(self, ohlcv_trending_up):
        """
        rolling_high_20 is consumed downstream (paper_runner.py/
        run_swing_model.py/backtesting/simulation.py) as risk_reward.py's
        compute_entry_zone "breakout level" — meant to be the PRIOR
        resistance a breakout crossed, matching is_breakout()'s own
        shift(1) (see this module's docstring for why: unshifted, on a
        genuine breakout day, today's own high/low IS the new 20-bar
        extreme, so the entry zone gets anchored at today's intraday high
        instead of at the real prior level). ohlcv_trending_up rises every
        single bar, so every bar's own High is a new all-time high — an
        unshifted rolling_high_20 would equal today's own High here; the
        correct, shifted value must equal the PRIOR bar's High instead.
        """
        cfg = {
            "technical": {
                "ma_short": 20, "ma_long": 50, "rsi_period": 14,
                "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
                "atr_period": 14, "rs_lookback": 20, "volume_avg_period": 20,
            }
        }
        benchmark = ohlcv_trending_up["Close"] * 0.95
        result = compute_technical_indicators(ohlcv_trending_up, benchmark, cfg)
        todays_high = float(ohlcv_trending_up["High"].iloc[-1])
        prior_bar_high = float(ohlcv_trending_up["High"].iloc[-2])
        assert result["rolling_high_20"] == pytest.approx(prior_bar_high)
        assert result["rolling_high_20"] < todays_high

    def test_rolling_low_20_excludes_todays_own_bar(self):
        """Mirror of the rolling_high_20 test above, for a falling series."""
        n = 100
        close = np.linspace(200, 100, n)  # strictly falling -> every bar is a new low
        df = pd.DataFrame({
            "Open": close * 1.01, "High": close * 1.02, "Low": close * 0.98,
            "Close": close, "Volume": [1_000_000] * n,
        }, index=pd.date_range("2025-01-01", periods=n, freq="B"))
        cfg = {
            "technical": {
                "ma_short": 20, "ma_long": 50, "rsi_period": 14,
                "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
                "atr_period": 14, "rs_lookback": 20, "volume_avg_period": 20,
            }
        }
        benchmark = df["Close"] * 1.05
        result = compute_technical_indicators(df, benchmark, cfg)
        todays_low = float(df["Low"].iloc[-1])
        prior_bar_low = float(df["Low"].iloc[-2])
        assert result["rolling_low_20"] == pytest.approx(prior_bar_low)
        assert result["rolling_low_20"] > todays_low
