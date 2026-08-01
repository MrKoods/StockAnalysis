"""
SHARED: MA, breakout, RS, RSI, ATR, MACD + z-score normalization.
All indicators computed on daily OHLCV DataFrames. Z-score normalization
puts all indicator values on a comparable scale (std devs from own mean)
before they are combined in scoring.py.
"""

import numpy as np
import pandas as pd

from shared.utils.volume_profile import compute_volume_profile, score_volume_profile_position


# ---------------------------------------------------------------------------
# Z-Score normalization
# ---------------------------------------------------------------------------

def zscore(series: pd.Series, window: int = 60) -> pd.Series:
    """
    Rolling z-score: (value - rolling_mean) / rolling_std over `window` bars.
    Returns series of z-scores aligned to the input index.
    Windows where std == 0 return 0.0 instead of NaN.
    """
    roll = series.rolling(window=window, min_periods=window)
    mean = roll.mean()
    std = roll.std(ddof=1)
    z = (series - mean) / std.replace(0, np.nan)
    return z.fillna(0.0)


def zscore_current(series: pd.Series, window: int = 60) -> float:
    """Return z-score of the most recent value in `series` relative to the prior `window` bars."""
    if len(series) < window + 1:
        return 0.0
    hist = series.iloc[-(window + 1):-1]
    current = series.iloc[-1]
    mu = hist.mean()
    sigma = hist.std(ddof=1)
    if sigma == 0 or pd.isna(sigma):
        return 0.0
    return float((current - mu) / sigma)


# ---------------------------------------------------------------------------
# Moving averages
# ---------------------------------------------------------------------------

def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple moving average over `period` bars."""
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average over `period` bars."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


# ---------------------------------------------------------------------------
# Breakout detection
# ---------------------------------------------------------------------------

def rolling_high(series: pd.Series, period: int = 20) -> pd.Series:
    """Rolling maximum over `period` bars — used as the breakout level."""
    return series.rolling(window=period, min_periods=period).max()


def is_breakout(close: pd.Series, high: pd.Series, period: int = 20) -> pd.Series:
    """
    Returns boolean Series: True where close exceeds the prior `period`-bar high.
    Uses the rolling high of the prior period (shift by 1 to avoid look-ahead bias).
    Volume confirmation expected by caller (see volume_zscore).
    """
    prior_high = rolling_high(high, period=period).shift(1)
    return close > prior_high


# ---------------------------------------------------------------------------
# Relative Strength
# ---------------------------------------------------------------------------

def relative_strength(ticker_close: pd.Series, benchmark_close: pd.Series, period: int = 20) -> pd.Series:
    """
    Relative strength of ticker vs. benchmark over rolling `period`.
    RS = ticker_return_period - benchmark_return_period.
    Positive values indicate ticker outperforming benchmark (SMH).
    """
    ticker_ret = ticker_close.pct_change(period)
    bench_ret = benchmark_close.pct_change(period)
    return ticker_ret - bench_ret


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    Relative Strength Index via Wilder smoothing (ewm with alpha=1/period).
    Returns series of RSI values (0-100).
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    alpha = 1.0 / period
    avg_gain = gain.ewm(alpha=alpha, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=alpha, adjust=False, min_periods=period).mean()

    # When avg_loss == 0: RSI = 100 (all gains). When avg_gain == 0: RSI = 0.
    rsi_series = pd.Series(index=close.index, dtype=float)
    both_zero = (avg_gain == 0) & (avg_loss == 0)
    all_gain = (avg_loss == 0) & (avg_gain > 0)
    all_loss = (avg_gain == 0) & (avg_loss > 0)
    normal = ~(both_zero | all_gain | all_loss)

    rsi_series[all_gain] = 100.0
    rsi_series[all_loss] = 0.0
    rsi_series[both_zero] = 50.0
    rs = avg_gain[normal] / avg_loss[normal]
    rsi_series[normal] = 100 - (100 / (1 + rs))
    return rsi_series.fillna(50.0)  # neutral fill for warmup period


# ---------------------------------------------------------------------------
# ATR
# ---------------------------------------------------------------------------

def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """
    Average True Range over `period` bars.
    TR = max(H-L, |H-prev_C|, |L-prev_C|). ATR = Wilder smoothed mean of TR.
    """
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    alpha = 1.0 / period
    return tr.ewm(alpha=alpha, adjust=False, min_periods=period).mean()


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------

def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    MACD line, signal line, and histogram.
    Returns (macd_line, signal_line, histogram).
    """
    ema_fast = ema(close, fast)
    ema_slow = ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


# ---------------------------------------------------------------------------
# Volume z-score
# ---------------------------------------------------------------------------

def volume_zscore(volume: pd.Series, period: int = 20) -> pd.Series:
    """
    Z-score of volume relative to its own rolling mean/std over `period` bars.
    Key for breakout confirmation — a breakout with volume z-score > 2 is
    more significant than one barely above average.
    """
    return zscore(volume, window=period)


# ---------------------------------------------------------------------------
# Composite technical score (input to scoring.py)
# ---------------------------------------------------------------------------

def compute_technical_indicators(
    ohlcv: pd.DataFrame,
    benchmark_close: pd.Series,
    cfg: dict,
) -> dict:
    """
    Compute all technical indicators for a single ticker.

    Returns dict with all fields used by scoring.py:
    {
        # Latest scalar values
        close, open, high, low, volume,
        sma_20, sma_50, rsi_14, atr_14,
        macd_line, macd_signal, macd_hist,
        rolling_high_20, volume_sma_20,
        rs_vs_benchmark,

        # Z-scores (normalized, used for sub-scoring)
        breakout_volume_zscore,   # volume z-score at breakout
        rs_zscore,                # RS z-score vs. benchmark
        rsi_zscore,               # RSI z-score
        volume_zscore_current,    # today's volume z-score

        # Boolean signals
        breakout_confirmed,       # close > prior 20-day high
        trend_intact,             # sma_20 > sma_50 AND close > sma_50
        sma_20_above_sma_50,
        price_above_sma_50,
        macd_bullish,             # macd_line > signal_line
    }

    cfg: contents of swing_config.yaml['technical']
    """
    tech_cfg = cfg.get("technical", {})
    ma_short = tech_cfg.get("ma_short", 20)
    ma_long = tech_cfg.get("ma_long", 50)
    rsi_period = tech_cfg.get("rsi_period", 14)
    atr_period = tech_cfg.get("atr_period", 14)
    macd_fast = tech_cfg.get("macd_fast", 12)
    macd_slow = tech_cfg.get("macd_slow", 26)
    macd_sig = tech_cfg.get("macd_signal", 9)
    rs_lookback = tech_cfg.get("rs_lookback", 20)
    vol_period = tech_cfg.get("volume_avg_period", 20)

    close = ohlcv["Close"]
    high = ohlcv["High"]
    low = ohlcv["Low"]
    volume = ohlcv["Volume"]

    sma_20_series = sma(close, ma_short)
    sma_50_series = sma(close, ma_long)
    rsi_series = rsi(close, rsi_period)
    atr_series = atr(high, low, close, atr_period)
    macd_line_s, macd_signal_s, macd_hist_s = macd(close, macd_fast, macd_slow, macd_sig)
    rolling_high_20 = rolling_high(high, ma_short)
    volume_sma = sma(volume.astype(float), vol_period)

    # RS vs. benchmark (align on common index)
    bench_aligned = benchmark_close.reindex(close.index, method="ffill")
    rs_series = relative_strength(close, bench_aligned, rs_lookback)

    # Z-scores
    vol_z_series = volume_zscore(volume.astype(float), vol_period)
    rs_z_series = zscore(rs_series.dropna().reindex(close.index), window=60)
    rsi_z_series = zscore(rsi_series, window=60)

    # Scalar (latest bar)
    latest = -1

    breakout_bool_series = is_breakout(close, high, ma_short)

    c_close = float(close.iloc[latest])
    if pd.isna(c_close):
        # An in-progress daily bar (e.g. pre-market, before the session has a
        # real close) should have been trimmed at the data-fetch layer. Unlike
        # atr/sma/etc. below, there's no safe numeric fallback for a stock's
        # close — it feeds stop/target/position-size math — so raise instead
        # of silently scoring on a fabricated price. Caller already treats
        # this the same as any other indicator-computation failure.
        raise ValueError("Latest bar has a NaN close — cannot compute indicators")
    c_sma20 = float(sma_20_series.iloc[latest]) if not pd.isna(sma_20_series.iloc[latest]) else c_close
    c_sma50 = float(sma_50_series.iloc[latest]) if not pd.isna(sma_50_series.iloc[latest]) else c_close
    c_rsi = float(rsi_series.iloc[latest])
    c_atr = float(atr_series.iloc[latest]) if not pd.isna(atr_series.iloc[latest]) else 0.0
    # MACD needs ~35 bars of history (26-period slow EMA + signal); with less
    # (new watchlist addition, short backtest window) macd_line/signal are NaN.
    # Unguarded, NaN > NaN evaluates False in Python, so macd_bullish silently
    # read as "not bullish" instead of "unknown" — macd_data_available lets
    # scoring.py tell the two apart instead of quietly capping trend_score.
    macd_data_available = not (pd.isna(macd_line_s.iloc[latest]) or pd.isna(macd_signal_s.iloc[latest]))
    c_macd = float(macd_line_s.iloc[latest]) if macd_data_available else 0.0
    c_signal = float(macd_signal_s.iloc[latest]) if macd_data_available else 0.0
    c_hist = float(macd_hist_s.iloc[latest]) if not pd.isna(macd_hist_s.iloc[latest]) else 0.0
    c_rolling_high = float(rolling_high_20.iloc[latest]) if not pd.isna(rolling_high_20.iloc[latest]) else c_close
    c_vol_sma = float(volume_sma.iloc[latest]) if not pd.isna(volume_sma.iloc[latest]) else 0.0
    c_rs = float(rs_series.iloc[latest]) if not pd.isna(rs_series.iloc[latest]) else 0.0
    c_vol_z = float(vol_z_series.iloc[latest])
    c_rs_z = float(rs_z_series.iloc[latest]) if not pd.isna(rs_z_series.iloc[latest]) else 0.0
    c_rsi_z = float(rsi_z_series.iloc[latest])
    c_breakout = bool(breakout_bool_series.iloc[latest]) if not pd.isna(breakout_bool_series.iloc[latest]) else False

    # ---------------------------------------------------------------------------
    # Volume profile score (0-8): previously computed by volume_profile.py but
    # never called from any live call site (run_swing_model.py, paper_runner.py) —
    # scoring.py's compute_technical_sub_scores() always fell back to its neutral
    # 4.0 default for every ticker, every scan. Computed here instead of at each
    # caller so every consumer of this function's output (live pipeline, backtest
    # simulation.py, tests) picks it up automatically. score_volume_profile_position()
    # returns on a 0-12 scale (pre-dates the 5×8-point technical redesign) — rescaled
    # to 0-8 to match volume_profile's current 8-point sub-signal max.
    # ---------------------------------------------------------------------------
    vp_cfg = cfg.get("volume_profile", {})
    try:
        vp_df = compute_volume_profile(
            ohlcv,
            lookback_days=vp_cfg.get("lookback_days", 60),
            price_bucket_pct=vp_cfg.get("price_bucket_pct", 0.005),
        )
        c_volume_profile_score = score_volume_profile_position(c_close, vp_df) * (8.0 / 12.0)
    except Exception:
        c_volume_profile_score = 4.0  # neutral fallback — matches scoring.py's prior default
    c_volume_profile_score = round(max(0.0, min(8.0, c_volume_profile_score)), 2)

    return {
        # Latest bar scalars
        "close": c_close,
        "open": float(ohlcv["Open"].iloc[latest]),
        "high": float(ohlcv["High"].iloc[latest]),
        "low": float(ohlcv["Low"].iloc[latest]),
        "volume": float(ohlcv["Volume"].iloc[latest]),
        "sma_20": c_sma20,
        "sma_50": c_sma50,
        "rsi_14": c_rsi,
        "atr_14": c_atr,
        "macd_line": c_macd,
        "macd_signal": c_signal,
        "macd_hist": c_hist,
        "rolling_high_20": c_rolling_high,
        "volume_sma_20": c_vol_sma,
        "rs_vs_benchmark": c_rs,

        # Z-scores
        "breakout_volume_zscore": c_vol_z,
        "rs_zscore": c_rs_z,
        "rsi_zscore": c_rsi_z,
        "volume_zscore_current": c_vol_z,

        # Boolean signals
        "breakout_confirmed": c_breakout,
        "trend_intact": c_sma20 > c_sma50 and c_close > c_sma50,
        "sma_20_above_sma_50": c_sma20 > c_sma50,
        "price_above_sma_50": c_close > c_sma50,
        "macd_bullish": (c_macd > c_signal) if macd_data_available else False,
        "macd_data_available": macd_data_available,

        "volume_profile_score": c_volume_profile_score,
    }
