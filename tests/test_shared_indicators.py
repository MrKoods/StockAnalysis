import pandas as pd
import pytest

from shared.indicators.technical_common import (
    average_volume,
    is_breakout,
    macd,
    moving_average,
    relative_strength,
    rsi,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(closes, highs=None, lows=None, volumes=None):
    n = len(closes)
    return pd.DataFrame(
        {
            "Open": closes,
            "High": [c + 1.0 for c in closes] if highs is None else highs,
            "Low": [c - 1.0 for c in closes] if lows is None else lows,
            "Close": closes,
            "Volume": [1_000_000] * n if volumes is None else volumes,
        },
        index=pd.date_range("2020-01-01", periods=n, freq="B"),
    )


# ---------------------------------------------------------------------------
# moving_average
# ---------------------------------------------------------------------------

def test_compute_moving_average_basic():
    closes = [10.0, 12.0, 14.0, 16.0, 18.0]
    df = _make_df(closes)
    ma = moving_average(df, window=3)
    expected = (14.0 + 16.0 + 18.0) / 3
    assert abs(ma.iloc[-1] - expected) < 1e-9


def test_compute_moving_average_period_longer_than_series():
    df = _make_df([10.0, 20.0])
    ma = moving_average(df, window=5)
    assert ma.isna().all()


# ---------------------------------------------------------------------------
# is_breakout
# ---------------------------------------------------------------------------

def test_compute_breakout_confirmed_with_volume():
    # 20 quiet days then a breakout close with double the avg volume
    closes = [100.0] * 20 + [115.0]
    highs = [101.0] * 20 + [116.0]
    volumes = [1_000_000] * 20 + [2_500_000]  # well above 1.5× avg
    df = _make_df(closes, highs=highs, volumes=volumes)
    result = is_breakout(df, lookback_window=20, volume_multiplier=1.5)
    assert result.iloc[-1] is True or result.iloc[-1] == True  # noqa: E712


def test_compute_breakout_rejected_without_volume():
    closes = [100.0] * 20 + [115.0]  # price breaks out
    highs = [101.0] * 20 + [116.0]
    volumes = [1_000_000] * 21  # volume flat — no confirmation
    df = _make_df(closes, highs=highs, volumes=volumes)
    result = is_breakout(df, lookback_window=20, volume_multiplier=1.5)
    assert result.iloc[-1] is False or result.iloc[-1] == False  # noqa: E712


# ---------------------------------------------------------------------------
# relative_strength
# ---------------------------------------------------------------------------

def test_compute_relative_strength_outperforms():
    # Ticker gains ~20 % over 20 days; benchmark gains ~5 %
    ticker_closes = [100.0] * 5 + [120.0] * 16
    bench_closes = [100.0] * 5 + [105.0] * 16
    rs = relative_strength(_make_df(ticker_closes), _make_df(bench_closes), window=20)
    assert rs.dropna().iloc[-1] > 0


def test_compute_relative_strength_underperforms():
    ticker_closes = [100.0] * 5 + [92.0] * 16
    bench_closes = [100.0] * 5 + [108.0] * 16
    rs = relative_strength(_make_df(ticker_closes), _make_df(bench_closes), window=20)
    assert rs.dropna().iloc[-1] < 0


# ---------------------------------------------------------------------------
# Uptrend / downtrend using moving_average
# ---------------------------------------------------------------------------

def test_is_uptrend_true():
    # Steadily rising prices → close > MA20 and MA20 > MA50
    closes = [float(100 + i) for i in range(60)]
    df = _make_df(closes)
    ma20 = moving_average(df, 20)
    ma50 = moving_average(df, 50)
    assert df["Close"].iloc[-1] > ma20.iloc[-1]
    assert ma20.iloc[-1] > ma50.iloc[-1]


def test_is_uptrend_false():
    # Steadily falling prices → close < MA20 and MA20 < MA50
    closes = [float(200 - i) for i in range(60)]
    df = _make_df(closes)
    ma20 = moving_average(df, 20)
    ma50 = moving_average(df, 50)
    assert df["Close"].iloc[-1] < ma20.iloc[-1]
    assert ma20.iloc[-1] < ma50.iloc[-1]
