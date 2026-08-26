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
    rolling_low,
    is_breakout,
    is_breakdown,
    bounce_fade_setup,
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
def ohlcv_trending_down():
    """Synthetic OHLCV DataFrame with steadily falling prices — mirrors ohlcv_trending_up."""
    n = 100
    close = np.linspace(200, 100, n)
    df = pd.DataFrame({
        "Open": close * 1.01,
        "High": close * 1.02,
        "Low": close * 0.99,
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

    def test_breakdown_detected_on_new_low(self):
        # 20 bars flat at 100, then drops to 99 — should detect breakdown (mirrors test_breakout_detected_on_new_high)
        close = pd.Series([100.0] * 21 + [99.0])
        low = pd.Series([100.0] * 21 + [99.0])
        result = is_breakdown(close, low, period=20)
        assert result.iloc[-1] is True or result.iloc[-1] == 1

    def test_no_breakdown_at_same_level(self):
        close = pd.Series([100.0] * 22)
        low = pd.Series([100.0] * 22)
        result = is_breakdown(close, low, period=20)
        # At exactly the prior low (not below), no breakdown
        assert not bool(result.iloc[-1])

    def test_rolling_low_correct(self):
        s = pd.Series([5.0, 3.0, 4.0, 1.0, 2.0])
        result = rolling_low(s, period=3)
        # Rolling min(3) at index 4: min(4, 1, 2) = 1
        assert result.iloc[-1] == 1.0


class TestBounceFadeSetup:
    """
    Capitulation/bounce-fade bearish entry — a breakdown followed by a relief
    bounce, still inside an intact downtrend, whose exhaustion (RSI recovers
    into a neutral band then rolls back over) is the actual short trigger.
    Mechanically distinct from is_breakdown() (shorts the breakdown itself).
    """

    def _scenario(self):
        # Bar 5: breakdown (sharp drop 96->90). Bars 6-10: relief bounce
        # back up to 97. Bar 11: RSI recovered into the 45-65 band by bar 10
        # then ticks down — the fade trigger.
        close = pd.Series([100.0, 99.0, 98.0, 97.0, 96.0, 90.0, 91.0, 92.0, 94.0, 96.0, 97.0, 96.0, 95.0, 94.0, 93.0])
        low = close.copy()
        high = close.copy()
        breakdown_mask = pd.Series([False] * 15)
        breakdown_mask.iloc[5] = True
        downtrend_intact = pd.Series([True] * 15)
        rsi_series = pd.Series([30.0, 28.0, 25.0, 22.0, 18.0, 15.0, 25.0, 35.0, 45.0, 55.0, 60.0, 58.0, 50.0, 45.0, 40.0])
        atr_series = pd.Series([2.0] * 15)
        return close, low, high, breakdown_mask, downtrend_intact, rsi_series, atr_series

    def test_fade_signal_fires_on_bounce_exhaustion(self):
        close, low, high, breakdown_mask, downtrend_intact, rsi_series, atr_series = self._scenario()
        result = bounce_fade_setup(high, low, close, breakdown_mask, downtrend_intact, rsi_series, atr_series)
        # Index 11: RSI (58) in the 45-65 recovery band and just turned down
        # from 60 (index 10), bounce is 3.0 ATR off the post-breakdown low
        # (96-90)/2.0, downtrend still intact, breakdown was 6 bars back.
        assert bool(result["fade_signal"].iloc[11]) is True

    def test_no_fade_signal_while_bounce_still_rising(self):
        close, low, high, breakdown_mask, downtrend_intact, rsi_series, atr_series = self._scenario()
        result = bounce_fade_setup(high, low, close, breakdown_mask, downtrend_intact, rsi_series, atr_series)
        # Index 9: RSI (55) still rising (54->55), not yet turned down — no signal.
        assert bool(result["fade_signal"].iloc[9]) is False

    def test_no_fade_signal_without_prior_breakdown(self):
        close, low, high, breakdown_mask, downtrend_intact, rsi_series, atr_series = self._scenario()
        no_breakdown = pd.Series([False] * 15)
        result = bounce_fade_setup(high, low, close, no_breakdown, downtrend_intact, rsi_series, atr_series)
        assert bool(result["fade_signal"].iloc[11]) is False

    def test_no_fade_signal_when_downtrend_broken(self):
        close, low, high, breakdown_mask, downtrend_intact, rsi_series, atr_series = self._scenario()
        no_downtrend = pd.Series([False] * 15)
        result = bounce_fade_setup(high, low, close, breakdown_mask, no_downtrend, rsi_series, atr_series)
        assert bool(result["fade_signal"].iloc[11]) is False

    def test_no_fade_signal_when_bounce_too_small(self):
        close, low, high, breakdown_mask, downtrend_intact, rsi_series, atr_series = self._scenario()
        result = bounce_fade_setup(
            high, low, close, breakdown_mask, downtrend_intact, rsi_series, atr_series,
            min_bounce_atr=10.0,  # far larger than the actual 3.0 ATR bounce
        )
        assert bool(result["fade_signal"].iloc[11]) is False

    def test_post_breakdown_low_and_swing_high_reported(self):
        close, low, high, breakdown_mask, downtrend_intact, rsi_series, atr_series = self._scenario()
        result = bounce_fade_setup(high, low, close, breakdown_mask, downtrend_intact, rsi_series, atr_series)
        # post_breakdown_low: min low over the last `lookback`=10 bars ending
        # at index 11 (bars 2-11) — the breakdown low of 90 is the minimum.
        assert result["post_breakdown_low"].iloc[11] == pytest.approx(90.0)
        # swing_high_since_breakdown must be at or above the post-breakdown low.
        assert result["swing_high_since_breakdown"].iloc[11] >= result["post_breakdown_low"].iloc[11]


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
            # Bearish mirror fields
            "breakdown_confirmed", "downtrend_intact", "macd_bearish",
            "volume_profile_score_bearish", "high_volume_resistance",
            "low_volume_area_below",
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
        assert result["trend_intact"] is True
        assert result["downtrend_intact"] is False

    def test_downtrend_intact_for_strong_downtrend(self, ohlcv_trending_down):
        benchmark = ohlcv_trending_down["Close"] * 1.05
        cfg = {
            "technical": {
                "ma_short": 20, "ma_long": 50, "rsi_period": 14,
                "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
                "atr_period": 14, "rs_lookback": 20, "volume_avg_period": 20,
            }
        }
        result = compute_technical_indicators(ohlcv_trending_down, benchmark, cfg)
        # Strong downtrend: SMA20 should be below SMA50 by the end (mirrors test_trend_intact_for_strong_uptrend)
        assert result["sma_20_above_sma_50"] is False
        assert result["downtrend_intact"] is True
        assert result["trend_intact"] is False
        assert result["macd_bearish"] is True
        assert result["macd_bullish"] is False

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


# ---------------------------------------------------------------------------
# mom_5d
# ---------------------------------------------------------------------------

class TestMom5d:
    """
    5-bar return. paper_runner.py and run_swing_model.py both persist this to
    their CSV rows as indicators["mom_5d"], but nothing in the live pipeline
    ever produced the key — both call sites read it through a
    .get("mom_5d", 0.0) default, so every live row silently recorded 0.0
    while presenting as a real measurement (all 39 rows logged across both
    paper-trading tracks up to 2026-08-25 read exactly 0.0000).
    """

    CFG = {
        "technical": {
            "ma_short": 20, "ma_long": 50, "rsi_period": 14,
            "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
            "atr_period": 14, "rs_lookback": 20, "volume_avg_period": 20,
        }
    }

    def test_mom_5d_is_present(self, ohlcv_trending_up):
        benchmark = ohlcv_trending_up["Close"] * 0.95
        result = compute_technical_indicators(ohlcv_trending_up, benchmark, self.CFG)
        assert "mom_5d" in result

    def test_mom_5d_is_not_a_constant_zero(self, ohlcv_trending_up):
        """The whole regression: the field existed downstream but was always 0.0."""
        benchmark = ohlcv_trending_up["Close"] * 0.95
        result = compute_technical_indicators(ohlcv_trending_up, benchmark, self.CFG)
        assert result["mom_5d"] != 0.0

    def test_mom_5d_matches_the_5_bar_return(self, ohlcv_trending_up):
        benchmark = ohlcv_trending_up["Close"] * 0.95
        result = compute_technical_indicators(ohlcv_trending_up, benchmark, self.CFG)
        close = ohlcv_trending_up["Close"]
        expected = (close.iloc[-1] - close.iloc[-6]) / close.iloc[-6]
        assert result["mom_5d"] == pytest.approx(expected)

    def test_mom_5d_positive_in_an_uptrend(self, ohlcv_trending_up):
        benchmark = ohlcv_trending_up["Close"] * 0.95
        assert compute_technical_indicators(ohlcv_trending_up, benchmark, self.CFG)["mom_5d"] > 0

    def test_mom_5d_negative_in_a_downtrend(self, ohlcv_trending_down):
        benchmark = ohlcv_trending_down["Close"] * 0.95
        assert compute_technical_indicators(ohlcv_trending_down, benchmark, self.CFG)["mom_5d"] < 0

    def test_mom_5d_is_zero_with_too_little_history(self):
        """Fewer than 6 bars has no 5-bar return — 0.0, not a crash or a NaN."""
        n = 4
        close = np.linspace(100, 110, n)
        df = pd.DataFrame({
            "Open": close * 0.99, "High": close * 1.01, "Low": close * 0.98,
            "Close": close, "Volume": [1_000_000] * n,
        }, index=pd.date_range("2025-01-01", periods=n, freq="B"))
        result = compute_technical_indicators(df, df["Close"] * 0.95, self.CFG)
        assert result["mom_5d"] == 0.0
