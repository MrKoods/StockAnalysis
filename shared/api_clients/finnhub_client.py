"""
SHARED: Finnhub free-tier endpoints beyond the /company-news feed the News
layer already uses (that stays in news_client.py).

Finnhub has no daily cap (only 60 req/min, paced by the shared rate limiter),
so these are cheap to add. Not wired into scoring yet — the phase-2 layer
re-routing reads from here:
  - Positioning:  get_recommendation_trend (analyst upgrades/downgrades, a
      clean structured series replacing the flaky yfinance .upgrades_downgrades),
      get_insider_mspr (aggregated monthly insider buy/sell pressure)
  - Fundamental:  get_peers (real peer set for valuation-vs-peers, replacing
      the hardcoded config constituent list), get_metric (60+ ratios as an
      AV OVERVIEW fallback)
  - Technical:    get_quote (day OHLC + prev close — a last-bar cross-check
      that catches the bad prints already failing validation)

Everything is cached and paced. Never raises — None/[]/{} on failure.
"""

import os
from datetime import date, timedelta
from typing import Optional

import requests

from shared.api_clients import cache, rate_limiter
from shared.api_clients._http_backoff import retry_with_backoff
from shared.utils.logger import get_logger

logger = get_logger(__name__)

_BASE = "https://finnhub.io/api/v1"


def _key() -> str:
    return os.environ.get("FINNHUB_API_KEY", "")


def _get(path: str, params: dict, label: str):
    key = _key()
    if not key:
        logger.warning(f"FINNHUB_API_KEY not set — {label} unavailable.")
        return None

    def _fetch():
        rate_limiter.acquire("finnhub.io")
        resp = requests.get(f"{_BASE}{path}", params={**params, "token": key}, timeout=30)
        resp.raise_for_status()
        rate_limiter.note_remaining("finnhub.io", _int(resp.headers.get("X-Ratelimit-Remaining")))
        return resp.json()

    return retry_with_backoff(
        _fetch, max_total_seconds=90, label=f"finnhub {label}",
        redact=lambda t: t.replace(key, "***") if key else t,
    )


# ---------------------------------------------------------------------------
# Positioning
# ---------------------------------------------------------------------------

def get_recommendation_trend(ticker: str) -> list[dict]:
    """
    Monthly analyst rating breakdown, most-recent-first. Cached ~7d.
    Returns [{"period": "YYYY-MM-01", "strongBuy","buy","hold","sell",
    "strongSell": int}, ...]. [] on failure.
    """
    def _fetch():
        data = _get("/stock/recommendation", {"symbol": ticker}, "recommendation")
        if not isinstance(data, list):
            return []
        return [
            {k: _int(row.get(k)) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")}
            | {"period": row.get("period")}
            for row in data
        ]

    return cache.cached_call("finnhub_recommendation", f"rec_{ticker}", cache.TTL["finnhub_recommendation"], _fetch)


def get_insider_mspr(ticker: str, months: int = 6) -> list[dict]:
    """
    Monthly aggregated insider Share Purchase Ratio (MSPR, -100..+100 — positive
    = net buying) plus net share change. Cached ~7d.
    Returns [{"year","month": int, "mspr": float, "change": float}, ...]
    most-recent-first. [] on failure.
    """
    def _fetch():
        frm = (date.today() - timedelta(days=months * 31)).isoformat()
        data = _get("/stock/insider-sentiment", {"symbol": ticker, "from": frm, "to": date.today().isoformat()}, "insider-sentiment")
        rows = (data or {}).get("data") or []
        out = [
            {"year": r.get("year"), "month": r.get("month"),
             "mspr": _num(r.get("mspr")), "change": _num(r.get("change"))}
            for r in rows
        ]
        return sorted(out, key=lambda r: (r["year"] or 0, r["month"] or 0), reverse=True)

    return cache.cached_call("finnhub_recommendation", f"mspr_{ticker}", cache.TTL["finnhub_recommendation"], _fetch)


# ---------------------------------------------------------------------------
# Fundamental
# ---------------------------------------------------------------------------

def get_peers(ticker: str) -> list[str]:
    """Finnhub's peer list for `ticker` (includes the ticker itself). Cached ~30d. [] on failure."""
    def _fetch():
        data = _get("/stock/peers", {"symbol": ticker}, "peers")
        return [str(s) for s in data] if isinstance(data, list) else []

    return cache.cached_call("finnhub_peers", f"peers_{ticker}", cache.TTL["finnhub_peers"], _fetch)


def get_profile(ticker: str) -> dict:
    """
    Company profile — shares outstanding, market cap, industry, IPO date.
    Cached ~30d. {} on failure.
    """
    def _fetch():
        data = _get("/stock/profile2", {"symbol": ticker}, "profile2")
        if not isinstance(data, dict) or not data:
            return {}
        return {
            "shares_outstanding_m": _num(data.get("shareOutstanding")),
            "market_cap_m": _num(data.get("marketCapitalization")),
            "industry": data.get("finnhubIndustry"),
            "ipo": data.get("ipo"),
        }

    return cache.cached_call("finnhub_profile", f"profile_{ticker}", cache.TTL["finnhub_profile"], _fetch)


def get_metric(ticker: str) -> dict:
    """60+ valuation/quality metrics (peTTM, pbAnnual, netProfitMarginTTM, roeTTM,
    beta, 52-week, price returns, epsGrowthTTMYoy, ...). Cached ~10d. {} on failure."""
    def _fetch():
        data = _get("/stock/metric", {"symbol": ticker, "metric": "all"}, "metric")
        return (data or {}).get("metric") or {}

    return cache.cached_call("fundamental_overview", f"fh_metric_{ticker}", cache.TTL["fundamental_overview"], _fetch)


# ---------------------------------------------------------------------------
# Technical cross-check
# ---------------------------------------------------------------------------

def get_quote(ticker: str) -> dict:
    """
    Current-day quote — {"current","high","low","open","prev_close": float,
    "ts": int}. Cached ~4h. {} on failure. No volume (Finnhub's free tier
    dropped candle/volume), so this is a last-bar sanity check, not a bar
    source.
    """
    def _fetch():
        data = _get("/quote", {"symbol": ticker}, "quote")
        if not isinstance(data, dict) or data.get("c") in (None, 0):
            return {}
        return {
            "current": _num(data.get("c")), "high": _num(data.get("h")),
            "low": _num(data.get("l")), "open": _num(data.get("o")),
            "prev_close": _num(data.get("pc")), "ts": data.get("t"),
        }

    return cache.cached_call("vix", f"fh_quote_{ticker}", cache.TTL["vix"], _fetch)


def _num(v) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None


def _int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
