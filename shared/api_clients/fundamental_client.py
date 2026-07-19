"""
Fundamental data client for the semiconductor swing trading model.

Fetches valuation metrics, earnings history, and estimate revisions for each watchlist
ticker using yfinance (no API key needed) and Alpha Vantage (ALPHA_VANTAGE_API_KEY from .env).

Update cadence: weekly (Monday at 17:00 ET) — 2 Alpha Vantage calls per ticker
(EARNINGS + OVERVIEW). Alpha Vantage's free-tier limit is a single per-account daily
cap, not partitioned by "scan type" — these calls share data/processed/av_call_count.json
with shared/api_clients/news_client.py's scan-time AV usage (previously this client
fired AV calls without checking or incrementing that counter at all, so a Monday
refresh landing on the same day as scan-time news calls could silently exceed the
real daily budget while every individual counter still looked fine).

Data sources:
  - yfinance Ticker.info    — valuation metrics (P/E, EV/EBITDA, analyst consensus)
  - Alpha Vantage EARNINGS  — historical EPS actuals vs. estimates (4 quarters)
  - Alpha Vantage OVERVIEW  — analyst target price, additional consensus fields
"""

import os
import time
from typing import Optional

import requests
import yfinance as yf

from shared.utils.logger import get_logger, write_validation_entry
from shared.api_clients.news_client import check_av_budget, increment_av_call_count

logger = get_logger(__name__)

_AV_BASE_URL = "https://www.alphavantage.co/query"
_BACKOFF_DELAYS = [30, 60, 120]
_MAX_TOTAL_BACKOFF_SECONDS = 90  # caps worst-case stall per AV call (see _with_backoff)


class FundamentalClient:
    """
    Retrieves fundamental data for semiconductor watchlist tickers.

    Methods:
      get_valuation_metrics(ticker)  — P/E, EV/EBITDA, analyst consensus via yfinance
      get_earnings_history(ticker)   — EPS actuals/estimates (4Q) via Alpha Vantage
      get_estimate_revisions(ticker) — analyst target price/upside via Alpha Vantage OVERVIEW
      get_all_fundamentals(ticker)   — orchestrates all three; logs failures gracefully
    """

    def __init__(self):
        self._av_key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
        if not self._av_key:
            logger.warning("ALPHA_VANTAGE_API_KEY not set — earnings/overview calls will fail gracefully.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_valuation_metrics(self, ticker: str) -> dict:
        """
        Pull valuation metrics from yfinance Ticker.info.

        Returns dict with keys:
          trailingPE, forwardPE, enterpriseToEbitda, enterpriseToRevenue,
          recommendationMean, targetMeanPrice, suspect_fields

        Missing or None fields are returned as None — never raises on missing data.
        Extreme or negative values are flagged in 'suspect_fields' list.
        Suspect fields still return their raw value so callers can decide how to use them.
        """
        fields = [
            "trailingPE",
            "forwardPE",
            "enterpriseToEbitda",
            "enterpriseToRevenue",
            "recommendationMean",
            "targetMeanPrice",
        ]
        result: dict = {f: None for f in fields}
        result["suspect_fields"] = []

        try:
            info = yf.Ticker(ticker).info
        except Exception as exc:
            logger.warning(f"{ticker}: yfinance info fetch failed — {exc}")
            write_validation_entry(ticker, "yfinance_info_error", str(exc))
            return result

        for field in fields:
            val = info.get(field)
            if val is None:
                continue
            try:
                val = float(val)
            except (TypeError, ValueError):
                continue
            result[field] = val

        # Flag suspect values
        suspect = []
        for pe_field in ("trailingPE", "forwardPE"):
            v = result.get(pe_field)
            if v is not None:
                if v < 0:
                    suspect.append(pe_field)
                elif v == 0:
                    suspect.append(pe_field)
                elif v > 1000:
                    suspect.append(pe_field)
        for ratio_field in ("enterpriseToEbitda", "enterpriseToRevenue"):
            v = result.get(ratio_field)
            if v is not None and (v < 0 or v > 1000):
                suspect.append(ratio_field)

        result["suspect_fields"] = suspect
        logger.debug(f"{ticker}: valuation_metrics fetched — suspect={suspect}")
        return result

    def get_earnings_history(self, ticker: str) -> Optional[dict]:
        """
        Fetch the last 4 quarters of EPS actuals vs. estimates via Alpha Vantage EARNINGS.

        Computes:
          eps_growth_trend     — list of 4 YoY EPS growth rates (most-recent-first)
          earnings_surprises   — list of 4 (reported - estimated) / abs(estimated) values
          consecutive_beats    — count of consecutive quarters (from most recent) where
                                 reported > estimated

        Uses exponential backoff (30s → 60s → 120s). Returns None if all retries fail.

        Alpha Vantage free tier has a single 25-call/day limit shared across this
        client and shared/api_clients/news_client.py — see module docstring.
        """
        if not self._av_key:
            logger.warning(f"{ticker}: skipping earnings history — no AV key")
            return None
        if not check_av_budget():
            logger.warning(f"{ticker}: AV daily budget exhausted — skipping earnings history")
            return None

        def _fetch_earnings():
            params = {
                "function": "EARNINGS",
                "symbol": ticker,
                "apikey": self._av_key,
            }
            resp = requests.get(_AV_BASE_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if "quarterlyEarnings" not in data:
                raise ValueError(f"No quarterlyEarnings key in response: {list(data.keys())}")
            return data

        data = self._with_backoff(_fetch_earnings, ticker, "earnings_history")
        increment_av_call_count()
        if data is None:
            return None

        quarterly = data["quarterlyEarnings"]
        if not quarterly:
            logger.warning(f"{ticker}: quarterlyEarnings list is empty")
            return None

        # Take up to 8 quarters so we can compute 4 YoY growth rates
        recent = quarterly[:8]

        eps_growth_trend = []
        earnings_surprises = []

        for i, q in enumerate(recent[:4]):
            reported = _safe_float(q.get("reportedEPS"))
            estimated = _safe_float(q.get("estimatedEPS"))

            # YoY growth: compare quarter i to quarter i+4 (same quarter prior year)
            if i + 4 < len(recent):
                prior_year_q = recent[i + 4]
                prior_eps = _safe_float(prior_year_q.get("reportedEPS"))
                if prior_eps is not None and prior_eps != 0 and reported is not None:
                    growth = (reported - prior_eps) / abs(prior_eps)
                    eps_growth_trend.append(round(growth, 4))
                else:
                    eps_growth_trend.append(None)
            else:
                eps_growth_trend.append(None)

            # Earnings surprise: (reported - estimated) / abs(estimated)
            if reported is not None and estimated is not None and estimated != 0:
                surprise = (reported - estimated) / abs(estimated)
                earnings_surprises.append(round(surprise, 4))
            else:
                earnings_surprises.append(None)

        # Consecutive beats from most recent quarter
        consecutive_beats = 0
        for surprise in earnings_surprises:
            if surprise is None:
                break
            if surprise > 0:
                consecutive_beats += 1
            else:
                break

        return {
            "eps_growth_trend": eps_growth_trend,
            "earnings_surprises": earnings_surprises,
            "consecutive_beats": consecutive_beats,
        }

    def get_estimate_revisions(self, ticker: str) -> dict:
        """
        Fetch analyst target price and consensus data via Alpha Vantage OVERVIEW.

        Note on data limitations: Alpha Vantage free tier does not provide a dedicated
        estimate-revisions endpoint (no historical sequence of analyst price targets).
        This method returns the current analyst target price and computes implied upside
        vs. the current price from yfinance. A 'data_limitations' field documents this.

        Returns dict with:
          analyst_target_price  — from OVERVIEW AnalystTargetPrice field
          current_price         — from yfinance (last close)
          implied_upside_pct    — (target - current) / current; None if either unavailable
          analyst_rating        — from OVERVIEW AnalystRatingStrongBuy etc. if present
          data_limitations      — note about what's not available on free tier
        """
        result = {
            "analyst_target_price": None,
            "current_price": None,
            "implied_upside_pct": None,
            "analyst_rating": None,
            "data_limitations": (
                "Alpha Vantage free tier does not provide historical estimate revision "
                "sequences. This endpoint returns current analyst target price only. "
                "Revision direction (upgrades vs. downgrades vs. 30 days ago) cannot be "
                "determined without a paid tier or a secondary data source."
            ),
        }

        if not self._av_key:
            logger.warning(f"{ticker}: skipping estimate revisions — no AV key")
            return result
        if not check_av_budget():
            logger.warning(f"{ticker}: AV daily budget exhausted — skipping estimate revisions")
            return result

        def _fetch_overview():
            params = {
                "function": "OVERVIEW",
                "symbol": ticker,
                "apikey": self._av_key,
            }
            resp = requests.get(_AV_BASE_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if not data or "Symbol" not in data:
                raise ValueError(f"OVERVIEW response missing Symbol: {list(data.keys())}")
            return data

        overview = self._with_backoff(_fetch_overview, ticker, "estimate_revisions")
        increment_av_call_count()
        if overview is None:
            return result

        result["analyst_target_price"] = _safe_float(overview.get("AnalystTargetPrice"))

        # Analyst rating fields available in OVERVIEW (not all tickers have these)
        for rating_field in ("AnalystRatingStrongBuy", "AnalystRatingBuy",
                             "AnalystRatingHold", "AnalystRatingSell",
                             "AnalystRatingStrongSell"):
            val = _safe_float(overview.get(rating_field))
            if val is not None:
                result.setdefault("analyst_rating_breakdown", {})[rating_field] = val

        # Current price from yfinance
        try:
            info = yf.Ticker(ticker).info
            current = _safe_float(info.get("regularMarketPrice") or info.get("previousClose"))
            result["current_price"] = current
        except Exception:
            pass

        if result["analyst_target_price"] and result["current_price"]:
            upside = (result["analyst_target_price"] - result["current_price"]) / result["current_price"]
            result["implied_upside_pct"] = round(upside, 4)

        return result

    def get_all_fundamentals(self, ticker: str) -> dict:
        """
        Orchestrate calls to all three fundamental methods.

        Returns combined dict with keys: valuation, earnings, revisions.
        Any sub-call failure is caught and logged to validation_log.csv.
        Never raises — always returns a dict (fields may be None on failure).
        """
        result = {
            "ticker": ticker,
            "valuation": None,
            "earnings": None,
            "revisions": None,
        }

        try:
            result["valuation"] = self.get_valuation_metrics(ticker)
        except Exception as exc:
            logger.error(f"{ticker}: get_valuation_metrics failed — {exc}")
            write_validation_entry(ticker, "fundamental_valuation_error", str(exc))

        try:
            result["earnings"] = self.get_earnings_history(ticker)
        except Exception as exc:
            logger.error(f"{ticker}: get_earnings_history failed — {exc}")
            write_validation_entry(ticker, "fundamental_earnings_error", str(exc))

        try:
            result["revisions"] = self.get_estimate_revisions(ticker)
        except Exception as exc:
            logger.error(f"{ticker}: get_estimate_revisions failed — {exc}")
            write_validation_entry(ticker, "fundamental_revisions_error", str(exc))

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _redact(self, text: str) -> str:
        """
        Strip the Alpha Vantage API key out of an error message before it's logged
        or written to validation_log.csv. requests' HTTPError embeds the full
        request URL (apikey is a query param), so an unredacted 429/403/5xx would
        otherwise write the live key to disk in plaintext.
        """
        if self._av_key:
            text = text.replace(self._av_key, "***REDACTED***")
        return text

    def _with_backoff(self, fn, ticker: str, label: str):
        """
        Call fn() with exponential backoff (30s → 60s → 120s → None), capped at
        _MAX_TOTAL_BACKOFF_SECONDS of total sleep. Logs each failure to
        validation_log.csv. Returns None after all retries or once the cap is hit.

        Without the cap, a full retry ladder (30+60+120=210s) on both AV calls
        (EARNINGS + OVERVIEW) across all 6 watchlist tickers is a ~42-minute worst
        case, run synchronously inside the pipeline with no overall timeout — an AV
        outage on refresh day could stall whatever else shares that process for
        most of an hour. Capping bounds it to _MAX_TOTAL_BACKOFF_SECONDS per call.
        """
        last_exc = None
        elapsed = 0.0
        for attempt, delay in enumerate(_BACKOFF_DELAYS, start=1):
            try:
                return fn()
            except Exception as exc:
                last_exc = exc
                if elapsed + delay > _MAX_TOTAL_BACKOFF_SECONDS:
                    logger.warning(
                        f"{ticker}: {label} attempt {attempt} failed — {self._redact(str(exc))} — "
                        f"backoff cap ({_MAX_TOTAL_BACKOFF_SECONDS}s) reached, giving up early"
                    )
                    break
                logger.warning(f"{ticker}: {label} attempt {attempt} failed — {self._redact(str(exc))} — retrying in {delay}s")
                time.sleep(delay)
                elapsed += delay

        logger.error(f"{ticker}: {label} failed after all retries — {self._redact(str(last_exc))}")
        write_validation_entry(ticker, f"fundamental_{label}_error", self._redact(str(last_exc)))
        return None


def _safe_float(val) -> Optional[float]:
    """Convert val to float; return None on failure."""
    if val is None:
        return None
    try:
        f = float(val)
        return f if f == f else None  # NaN guard
    except (TypeError, ValueError):
        return None
