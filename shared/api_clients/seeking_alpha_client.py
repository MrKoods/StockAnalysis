"""
SHARED: Seeking Alpha (RapidAPI apidojo) data endpoints beyond the editorial
news feed the Sentiment layer already uses.

The subscription is a Pro plan (10,000 calls/month, ~25% used) — this is the
headroom the API audit found going to waste. These endpoints feed:
  - Fundamental layer:  get_factor_grades (SA Quant Rating + the 30-day vs
      90-day analyst rating counts, which is the estimate-revision trend
      signal), get_fundamentals (statement lines), get_analyst_price_target
  - Technical layer:     get_chart — full daily OHLCV WITH volume, a keyed
      price source that removes yfinance as a single point of failure

Not wired into scoring yet. Everything here goes through the shared rate
limiter (400/day cap for this host) and cache. Never raises — returns None /
[] / {} on any failure so a caller can fall back.
"""

import os
from typing import Optional

from shared.api_clients import cache, rate_limiter
from shared.api_clients._http_backoff import http_get_with_backoff
from shared.utils.logger import get_logger

logger = get_logger(__name__)

_HOST = "seeking-alpha.p.rapidapi.com"
_BASE = f"https://{_HOST}"
# StockTwits/SA behind Cloudflare bot protection block the default requests UA.
_UA = "curl/8.4.0"


def _sa_get(path: str, params: Optional[dict] = None) -> Optional[dict]:
    api_key = os.environ.get("RAPIDAPI_KEY", "")
    if not api_key:
        logger.warning("RAPIDAPI_KEY not set — Seeking Alpha data unavailable.")
        return None
    try:
        rate_limiter.acquire(_HOST)
    except rate_limiter.BudgetExhausted as exc:
        logger.warning(f"Seeking Alpha: {exc} — skipping {path}")
        return None
    headers = {"x-rapidapi-key": api_key, "x-rapidapi-host": _HOST, "User-Agent": _UA}
    data = http_get_with_backoff(f"{_BASE}{path}", params=params, headers=headers, label=f"SA {path}")
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# Price — get_chart returns adjusted daily OHLCV with volume
# ---------------------------------------------------------------------------

def get_daily_ohlcv(ticker: str, period: str = "1Y") -> list[dict]:
    """
    Adjusted daily bars for `ticker` from SA's get-chart. period one of
    1D/5D/1M/6M/1Y/5Y/MAX (1Y => ~252 bars). Cached ~8h (cache.TTL["ohlcv"]).

    Returns [{"date": "YYYY-MM-DD", "open","high","low","close","volume",
    "adj"}, ...] oldest-first, regular-session bars only. [] on failure.
    """
    def _fetch():
        data = _sa_get("/symbols/get-chart", {"symbol": ticker.lower(), "period": period})
        attrs = (data or {}).get("attributes") or {}
        rows = []
        for ts, bar in attrs.items():
            if not isinstance(bar, dict):
                continue
            if bar.get("session") not in (None, "market"):
                continue  # skip blended pre/post-market points
            rows.append({
                "date": ts[:10],
                "open": bar.get("open"),
                "high": bar.get("high"),
                "low": bar.get("low"),
                "close": bar.get("close"),
                "volume": bar.get("volume"),
                "adj": bar.get("adj"),
            })
        return sorted(rows, key=lambda r: r["date"])

    return cache.cached_call("ohlcv", f"sa_chart_{ticker}_{period}", cache.TTL["ohlcv"], _fetch)


# ---------------------------------------------------------------------------
# Ratings — get_factor_grades carries the Quant Rating + rating-count trend
# ---------------------------------------------------------------------------

def get_factor_grades(ticker: str) -> dict:
    """
    SA's proprietary ratings for `ticker` as a quarterly time series, most
    recent first. Cached ~20h (cache.TTL["sa_factor_grades"]).

    Returns {"as_of": "YYYY-MM-DD", "quant_rating": float|None,
    "sell_side_rating": float|None, "authors_rating": float|None,
    "buy_count_30d","buy_count_90d","hold_count_30d","hold_count_90d",
    "sell_count_30d","sell_count_90d", "history": [<same keys per period>]}.
    Empty dict on failure.

    Ratings are 1-5 (5 = Strong Buy). The 30d/90d buy/hold/sell counts are the
    revision-trend signal the Fundamental layer's own docstring calls "not
    available on any free tier": if the 30-day buy count is a larger share of
    total than the 90-day, ratings are being upgraded.
    """
    def _fetch():
        data = _sa_get("/symbols/get-factor-grades", {"symbol": ticker.lower()})
        rows = (data or {}).get("data") or []
        history = []
        for row in rows:
            attrs = row.get("attributes") or {}
            r = attrs.get("ratings") or {}
            history.append({
                "as_of": attrs.get("asDate"),
                "quant_rating": _num(r.get("quantRating")),
                "sell_side_rating": _num(r.get("sellSideRating")),
                "authors_rating": _num(r.get("authorsRating")),
                "buy_count_30d": _num(r.get("authorsRatingBuyCount30Day")),
                "buy_count_90d": _num(r.get("authorsRatingBuyCount90Day")),
                "hold_count_30d": _num(r.get("authorsRatingHoldCount30Day")),
                "hold_count_90d": _num(r.get("authorsRatingHoldCount90Day")),
                "sell_count_30d": _num(r.get("authorsRatingSellCount30Day")),
                "sell_count_90d": _num(r.get("authorsRatingSellCount90Day")),
            })
        if not history:
            return {}
        latest = dict(history[0])
        latest["history"] = history
        return latest

    return cache.cached_call("sa_factor_grades", f"grades_{ticker}", cache.TTL["sa_factor_grades"], _fetch)


# ---------------------------------------------------------------------------
# Fundamentals — statement lines
# ---------------------------------------------------------------------------

def get_fundamentals(ticker: str, statement: str = "income-statement", period_type: str = "quarterly") -> list[dict]:
    """
    Financial-statement line items for `ticker` from SA's get-fundamentals.
    statement one of income-statement / balance-sheet / cash-flow. Cached ~7d
    (cache.TTL["sa_fundamentals"]).

    Returns [{"field": "total_revenue", "value": float, "year": int,
    "quarter": int|None, "period_end_date": "YYYY-MM-DD"}, ...]. [] on failure.
    """
    def _fetch():
        data = _sa_get(
            "/symbols/get-fundamentals",
            {"symbol": ticker.lower(), "statement_type": statement, "period_type": period_type},
        )
        rows = (data or {}).get("data") or []
        out = []
        for row in rows:
            a = row.get("attributes") or {}
            out.append({
                "field": a.get("field"),
                "value": _num(a.get("value")),
                "year": a.get("year"),
                "quarter": a.get("quarter"),
                "period_end_date": (a.get("period_end_date") or "")[:10] or None,
            })
        return out

    return cache.cached_call("sa_fundamentals", f"fund_{ticker}_{statement}_{period_type}", cache.TTL["sa_fundamentals"], _fetch)


# ---------------------------------------------------------------------------
# Analyst price target + revisions (needs SA's numeric ticker id)
# ---------------------------------------------------------------------------

def resolve_ticker_id(ticker: str) -> Optional[str]:
    """SA's numeric ticker id (NVDA -> "1150"), via get-meta-data. Cached 30d."""
    def _fetch():
        data = _sa_get("/symbols/get-meta-data", {"symbols": ticker.lower()})
        rows = (data or {}).get("data") or []
        for row in rows:
            if str(row.get("attributes", {}).get("name", "")).upper() == ticker.upper():
                return str(row.get("id"))
        return str(rows[0].get("id")) if rows else None

    return cache.cached_call("finnhub_profile", f"sa_id_{ticker}", cache.TTL["finnhub_profile"], _fetch, store_falsy=False)


def get_analyst_price_target(ticker: str, ticker_id: Optional[str] = None) -> dict:
    """
    Analyst price target (low/mean/high) and its recent revision history for
    `ticker`, via get-analyst-price-target. Cached ~7d.

    Returns {"target_mean": float|None, "target_low": float|None,
    "target_high": float|None, "revisions_up": int, "revisions_down": int}.
    Empty dict on failure or if the SA id can't be resolved.
    """
    tid = ticker_id or resolve_ticker_id(ticker)
    if not tid:
        return {}

    def _fetch():
        data = _sa_get(
            "/symbols/get-analyst-price-target",
            {"ticker_ids": tid, "return_window": 3, "group_by_month": "true"},
        )
        est = ((data or {}).get("estimates") or {}).get(str(tid)) or {}
        rev = ((data or {}).get("revisions") or {}).get(str(tid)) or {}

        def _latest(block):
            series = (block or {}).get("0") or []
            if not series:
                return None
            newest = max(series, key=lambda e: e.get("effectivedate", ""))
            return _num(newest.get("dataitemvalue"))

        up = down = 0
        for entries in rev.values():
            for e in (entries.get("0") or []) if isinstance(entries, dict) else []:
                v = _num(e.get("dataitemvalue"))
                if v is None:
                    continue
                up += v > 0
                down += v < 0
        return {
            "target_mean": _latest(est.get("target_price_mean") or est.get("target_price")),
            "target_low": _latest(est.get("target_price_low")),
            "target_high": _latest(est.get("target_price_high")),
            "revisions_up": up,
            "revisions_down": down,
        }

    return cache.cached_call("sa_fundamentals", f"target_{ticker}", cache.TTL["earnings_calendar"], _fetch)


def _num(v) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None
    except (TypeError, ValueError):
        return None
