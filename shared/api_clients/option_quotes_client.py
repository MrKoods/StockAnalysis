"""
Real option quotes for pricing paper options positions (paper_trading/options_pricer.py).

Separate from positioning_client.fetch_option_chain_metrics, which builds
scoring features from ONE expiration picked for today; pricing an open
position needs the exact expirations and strikes it was opened at, days
later. Same data source (yfinance, 15-min delayed), same backoff, same
cross-process rate limiter as every other yfinance call.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
import yfinance as yf

from shared.api_clients import rate_limiter
from shared.api_clients._http_backoff import retry_with_backoff


def list_expirations(ticker: str) -> list[str]:
    """Listed option expirations (YYYY-MM-DD), nearest first. Empty on failure."""
    def _fetch():
        rate_limiter.acquire("yfinance")
        return list(yf.Ticker(ticker).options or [])
    return retry_with_backoff(_fetch, retries=2, delays=(5,), label=f"{ticker}: list_expirations") or []


def fetch_quotes(ticker: str, expiration: str) -> Optional[pd.DataFrame]:
    """
    One expiration's chain as rows [option_type, strike, bid, ask, last],
    calls and puts together. None on failure.
    """
    def _fetch():
        rate_limiter.acquire("yfinance")
        chain = yf.Ticker(ticker).option_chain(expiration)
        parts = []
        for kind, df in (("call", chain.calls), ("put", chain.puts)):
            part = df[["strike", "bid", "ask", "lastPrice"]].rename(columns={"lastPrice": "last"}).copy()
            part.insert(0, "option_type", kind)
            parts.append(part)
        return pd.concat(parts, ignore_index=True)
    return retry_with_backoff(_fetch, retries=2, delays=(5,), label=f"{ticker}: fetch_quotes({expiration})")


def fetch_spot(ticker: str) -> Optional[float]:
    """Latest trade price (15-min delayed intraday). None on failure."""
    def _fetch():
        rate_limiter.acquire("yfinance")
        px = yf.Ticker(ticker).fast_info["last_price"]
        return float(px) if px and px > 0 else None
    return retry_with_backoff(_fetch, retries=2, delays=(5,), label=f"{ticker}: fetch_spot")
