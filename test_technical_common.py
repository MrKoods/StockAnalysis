"""Sanity-check script for shared/indicators/technical_common.py.

Pulls NVDA and SMH daily data for 2026-01-01 to 2026-06-01, runs all nine
indicator functions, and prints the last 10 rows of each result.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from shared.api_clients.market_data_client import get_ohlcv
from shared.indicators.technical_common import (
    moving_average,
    rolling_high,
    rolling_low,
    average_volume,
    is_breakout,
    relative_strength,
    rsi,
    atr,
    macd,
)

START = "2026-01-01"
END = "2026-06-01"

print("Fetching NVDA and SMH data...")
nvda = get_ohlcv("NVDA", START, END)
smh = get_ohlcv("SMH", START, END)
print(f"  NVDA: {len(nvda)} bars  |  SMH: {len(smh)} bars\n")

# 1. Moving Average
ma20 = moving_average(nvda, window=20)
print("=" * 60)
print("1. moving_average(nvda, window=20)  [last 10 rows]")
print("   (Compare to Close — should track it with a ~20-day lag)")
combined = nvda[["Close"]].copy()
combined["MA20"] = ma20
print(combined.tail(10).to_string())
print()

# 2. Rolling High
rh20 = rolling_high(nvda, window=20)
print("=" * 60)
print("2. rolling_high(nvda, window=20)  [last 10 rows]")
print("   (Should be >= the High column for all rows)")
combined2 = nvda[["High"]].copy()
combined2["RollingHigh20"] = rh20
print(combined2.tail(10).to_string())
print()

# 3. Rolling Low
rl20 = rolling_low(nvda, window=20)
print("=" * 60)
print("3. rolling_low(nvda, window=20)  [last 10 rows]")
print("   (Should be <= the Low column for all rows)")
combined3 = nvda[["Low"]].copy()
combined3["RollingLow20"] = rl20
print(combined3.tail(10).to_string())
print()

# 4. Average Volume
avg_vol = average_volume(nvda, window=20)
print("=" * 60)
print("4. average_volume(nvda, window=20)  [last 10 rows]")
combined4 = nvda[["Volume"]].copy()
combined4["AvgVol20"] = avg_vol
print(combined4.tail(10).to_string())
print()

# 5. Is Breakout
breakouts = is_breakout(nvda, lookback_window=20, volume_multiplier=1.5)
n_breakouts = breakouts.sum()
print("=" * 60)
print(f"5. is_breakout(nvda, lookback_window=20, volume_multiplier=1.5)")
print(f"   Total breakout days flagged: {n_breakouts} out of {len(breakouts)} bars")
print("   Last 10 rows (True = breakout day):")
combined5 = nvda[["Close", "Volume"]].copy()
combined5["is_breakout"] = breakouts
print(combined5.tail(10).to_string())
if n_breakouts > 0:
    print("\n   All breakout dates:")
    print(combined5[combined5["is_breakout"]].to_string())
print()

# 6. Relative Strength
rs = relative_strength(nvda, smh, window=20)
print("=" * 60)
print("6. relative_strength(nvda, smh, window=20)  [last 10 rows]")
print("   (Positive = NVDA outperformed SMH over trailing 20 days)")
print(rs.tail(10).to_string())
print()
print(f"   Min: {rs.min():.4f}  Max: {rs.max():.4f}  Mean: {rs.mean():.4f}")

# 7. RSI
rsi14 = rsi(nvda, window=14)
print()
print("=" * 60)
print("7. rsi(nvda, window=14)  [last 10 rows]")
print("   (All values must be 0-100; >70 overbought, <30 oversold)")
combined7 = nvda[["Close"]].copy()
combined7["RSI14"] = rsi14
print(combined7.tail(10).to_string())
print(f"\n   Min: {rsi14.min():.2f}  Max: {rsi14.max():.2f}  Current: {rsi14.iloc[-1]:.2f}")

# 8. ATR
atr14 = atr(nvda, window=14)
print()
print("=" * 60)
print("8. atr(nvda, window=14)  [last 10 rows]")
print("   (Should be a small positive number in the same units as price)")
combined8 = nvda[["High", "Low", "Close"]].copy()
combined8["ATR14"] = atr14
print(combined8.tail(10).to_string())
last_close = nvda["Close"].iloc[-1]
last_atr = atr14.iloc[-1]
print(f"\n   Last ATR: {last_atr:.2f}  ({last_atr / last_close * 100:.2f}% of last close ${last_close:.2f})")

# 9. MACD
macd_df = macd(nvda)
print()
print("=" * 60)
print("9. macd(nvda)  [last 10 rows — fast=12, slow=26, signal=9]")
print("   (macd and signal in same units as price spread; histogram = macd - signal)")
print(macd_df.tail(10).to_string())
last = macd_df.iloc[-1]
print(f"\n   Last row — macd: {last['macd']:.4f}  signal: {last['signal']:.4f}  histogram: {last['histogram']:.4f}")
