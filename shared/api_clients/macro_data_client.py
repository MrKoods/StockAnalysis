"""
SHARED: Macro series for macro_overlay.py, from Alpha Vantage's economic-data
endpoints instead of yfinance index proxies.

MR-4 (2026-08 API audit): the overlay used yf.download("^TNX") as a "Fed rate
direction proxy" and yf.download("DX-Y.NYB") for USD strength. Alpha Vantage
serves the actual 10-year Treasury constant-maturity yield (FRED-sourced) and
FX rates directly, keyed and cached, and — as a follow-up — the actual
Effective Federal Funds Rate and CPI, which the overlay has never had.

Each series is one AV call, cached ~20h (cache.TTL["macro_series"]) since the
overlay only reads a 20-day trend. Returns a pandas Series indexed by date
(oldest-first), or None on failure — macro_overlay.compute_macro_state already
degrades a missing series to a neutral reading for just that signal.
"""

import os
from typing import Optional

import pandas as pd

from shared.api_clients import cache, rate_limiter
from shared.api_clients._http_backoff import http_get_with_backoff
from shared.api_clients.news_client import is_av_throttle_response
from shared.utils.logger import get_logger

logger = get_logger(__name__)

_AV_URL = "https://www.alphavantage.co/query"


def _av_series_call(params: dict, label: str, value_key: str) -> Optional[dict]:
    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
    if not api_key:
        logger.warning(f"ALPHA_VANTAGE_API_KEY not set — {label} unavailable.")
        return None
    try:
        rate_limiter.acquire("alphavantage.co")
    except rate_limiter.BudgetExhausted as exc:
        logger.warning(f"{label}: {exc} — skipping")
        return None
    data = http_get_with_backoff(
        _AV_URL, params={**params, "apikey": api_key},
        redact=lambda t: t.replace(api_key, "***"), label=f"macro {label}",
    )
    if not isinstance(data, dict) or is_av_throttle_response(data):
        if is_av_throttle_response(data):
            logger.warning(f"{label}: AV throttled — using cache/fallback")
        return None
    return data


def _to_series(pairs: list[tuple[str, str]]) -> Optional[pd.Series]:
    """pairs: (date_str, value_str), any order. -> float Series indexed by
    Timestamp, oldest-first, non-numeric points dropped."""
    rows = {}
    for d, v in pairs:
        try:
            rows[pd.Timestamp(d)] = float(v)
        except (ValueError, TypeError):
            continue
    if not rows:
        return None
    return pd.Series(rows).sort_index()


def _series_to_jsonable(s: Optional[pd.Series], n: int) -> Optional[dict]:
    """Last n points as an ISO-date-keyed dict — JSON-serialisable for the
    cache (a Timestamp key is not)."""
    if s is None:
        return None
    return {pd.Timestamp(k).date().isoformat(): float(v) for k, v in s.tail(n).items()}


def _series_from_jsonable(d: Optional[dict]) -> Optional[pd.Series]:
    """Rebuild the datetime-indexed Series written by _series_to_jsonable."""
    if not d:
        return None
    s = pd.Series(d)
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def fetch_treasury_yield_10y() -> Optional[pd.Series]:
    """10-year Treasury constant-maturity yield (percent), daily. Cached ~20h."""
    def _fetch():
        data = _av_series_call(
            {"function": "TREASURY_YIELD", "interval": "daily", "maturity": "10year"},
            "TREASURY_YIELD", "value",
        )
        pts = (data or {}).get("data") or []
        s = _to_series([(p.get("date"), p.get("value")) for p in pts])
        return _series_to_jsonable(s, 120)

    d = cache.cached_call("macro_series", "treasury_10y", cache.TTL["macro_series"], _fetch)
    return _series_from_jsonable(d)


def fetch_usd_strength() -> Optional[pd.Series]:
    """
    USD strength proxy — the USD/EUR daily close (rises when the dollar
    strengthens, same direction as DXY for the overlay's purpose). Cached ~20h.
    """
    def _fetch():
        data = _av_series_call(
            {"function": "FX_DAILY", "from_symbol": "USD", "to_symbol": "EUR", "outputsize": "compact"},
            "FX_DAILY USD/EUR", "4. close",
        )
        ts = (data or {}).get("Time Series FX (Daily)") or {}
        s = _to_series([(d, bar.get("4. close")) for d, bar in ts.items()])
        return _series_to_jsonable(s, 120)

    d = cache.cached_call("macro_series", "usd_eur", cache.TTL["macro_series"], _fetch)
    return _series_from_jsonable(d)


def fetch_federal_funds_rate() -> Optional[pd.Series]:
    """Effective Federal Funds Rate (percent), monthly. Cached ~7d (monthly data)."""
    def _fetch():
        data = _av_series_call(
            {"function": "FEDERAL_FUNDS_RATE", "interval": "monthly"}, "FEDERAL_FUNDS_RATE", "value",
        )
        pts = (data or {}).get("data") or []
        s = _to_series([(p.get("date"), p.get("value")) for p in pts])
        return _series_to_jsonable(s, 36)

    d = cache.cached_call("macro_series_slow", "fed_funds", cache.TTL["macro_series_slow"], _fetch)
    return _series_from_jsonable(d)


def fetch_cpi() -> Optional[pd.Series]:
    """CPI index, monthly. Cached ~7d."""
    def _fetch():
        data = _av_series_call({"function": "CPI", "interval": "monthly"}, "CPI", "value")
        pts = (data or {}).get("data") or []
        s = _to_series([(p.get("date"), p.get("value")) for p in pts])
        return _series_to_jsonable(s, 36)

    d = cache.cached_call("macro_series_slow", "cpi", cache.TTL["macro_series_slow"], _fetch)
    return _series_from_jsonable(d)
