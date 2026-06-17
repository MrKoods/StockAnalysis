import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from shared.api_clients.market_data_client import get_ohlcv

df = get_ohlcv("NVDA", "2026-01-01", "2026-06-01")

print(f"Ticker: {df.attrs['ticker']}")
print(f"Total rows: {len(df)}\n")
print("First 5 rows:")
print(df.head())
print("\nLast 5 rows:")
print(df.tail())
