"""
Fundamental data client for the semiconductor swing trading model.

Fetches valuation metrics, earnings history, and estimate revisions for each watchlist
ticker using yfinance (no API key needed) and Finnhub (FINNHUB_API_KEY). No longer
touches Alpha Vantage at all as of the eps_growth_trend migration below — this client
used to be the last consumer of the shared data/processed/av_call_count.json budget
outside news_client.py; it no longer draws from that pool.

Update cadence: staggered per-ticker (see indicator_pipeline.fetch_fundamental_data).
eps_growth_trend (the 8-quarter YoY EPS comparison) is still only fetched near a
ticker's own earnings date or on first-ever fetch, not on routine weekly refresh,
since that figure can't change between quarterly reports — that gating is about
avoiding wasted work, not budget, now that the source is free.

Data sources:
  - yfinance Ticker.info              — valuation metrics (P/E, EV/EBITDA) + analyst
                                         target price
  - Finnhub /stock/earnings           — actual vs. estimated EPS, last 4 quarters (feeds
                                         earnings_surprises/consecutive_beats)
  - yfinance Ticker.get_earnings_dates — up to 24 quarters of reported EPS (confirmed
                                         live across mega-cap, regional-bank, and ADR
                                         tickers), used to compute eps_growth_trend (YoY).
                                         Replaced the prior Alpha Vantage EARNINGS call —
                                         Finnhub's free tier and yfinance's quarterly
                                         income-statement both cap out at 4-5 quarters,
                                         not deep enough for a YoY comparison, but this
                                         endpoint (Yahoo's earnings-calendar history, via
                                         pandas.read_html — requires the lxml package)
                                         goes back multiple years for every ticker tested.
  - Finnhub /stock/recommendation     — analyst rating breakdown (replaced Alpha Vantage
                                         OVERVIEW here — AV's own prior docstring already
                                         noted that call was low-value on the free tier:
                                         current target price only, no revision history —
                                         Finnhub gives the same rating-snapshot depth for
                                         zero AV budget)
"""

import os
import time
from typing import Optional

import requests
import yfinance as yf

from shared.utils.logger import get_logger, write_validation_entry

logger = get_logger(__name__)

_FINNHUB_BASE_URL = "https://finnhub.io/api/v1"
_BACKOFF_DELAYS = [30, 60, 120]
_MAX_TOTAL_BACKOFF_SECONDS = 90  # caps worst-case stall per Finnhub call (see _with_backoff)


class FundamentalClient:
    """
    Retrieves fundamental data for semiconductor watchlist tickers.

    Methods:
      get_valuation_metrics(ticker)  — P/E, EV/EBITDA via yfinance
      get_eps_growth_trend(ticker)   — EPS actuals (4Q YoY trend) via yfinance
      get_estimate_revisions(ticker) — analyst target price (yfinance) + rating breakdown
                                        (Finnhub)
      get_all_fundamentals(ticker)   — orchestrates all three; logs failures gracefully
    """

    def __init__(self):
        self._finnhub_key = os.getenv("FINNHUB_API_KEY", "")
        if not self._finnhub_key:
            logger.warning("FINNHUB_API_KEY not set — analyst rating call will fail gracefully.")

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

    def get_earnings_surprises(self, ticker: str) -> Optional[dict]:
        """
        Fetch the last 4 quarters of EPS actuals vs. estimates via Finnhub
        /stock/earnings — free tier, no Alpha Vantage budget cost, and already
        in exactly the shape needed (no computation Alpha Vantage's EARNINGS
        endpoint was doing that this doesn't already get directly).

        Computes:
          earnings_surprises   — list of up to 4 (reported - estimated) / abs(estimated)
                                 values, most-recent-first
          consecutive_beats    — count of consecutive quarters (from most recent) where
                                 reported > estimated

        Uses exponential backoff (30s → 60s → 120s). Returns None if all retries fail.
        """
        if not self._finnhub_key:
            logger.warning(f"{ticker}: skipping earnings surprises — no Finnhub key")
            return None

        def _fetch_earnings():
            params = {"symbol": ticker, "token": self._finnhub_key}
            resp = requests.get(f"{_FINNHUB_BASE_URL}/stock/earnings", params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list):
                raise ValueError(f"Unexpected /stock/earnings response shape: {type(data)}")
            return data

        data = self._with_backoff(_fetch_earnings, ticker, "earnings_surprises")
        if not data:
            return None

        # Finnhub returns most-recent-period-first already.
        recent = data[:4]
        earnings_surprises = []
        for q in recent:
            reported = _safe_float(q.get("actual"))
            estimated = _safe_float(q.get("estimate"))
            if reported is not None and estimated is not None and estimated != 0:
                surprise = (reported - estimated) / abs(estimated)
                earnings_surprises.append(round(surprise, 4))
            else:
                earnings_surprises.append(None)

        consecutive_beats = 0
        for surprise in earnings_surprises:
            if surprise is None:
                break
            if surprise > 0:
                consecutive_beats += 1
            else:
                break

        return {
            "earnings_surprises": earnings_surprises,
            "consecutive_beats": consecutive_beats,
        }

    def get_eps_growth_trend(self, ticker: str) -> Optional[dict]:
        """
        Fetch up to 8 quarters of reported EPS via yfinance's earnings-date
        history, used only for the year-over-year growth trend — the one figure
        that genuinely needs history deeper than Finnhub's/yfinance's quarterly
        income-statement 4-5 quarters.

        Computes:
          eps_growth_trend — list of up to 4 YoY EPS growth rates (most-recent-first)

        Replaced the prior Alpha Vantage EARNINGS call (see module docstring) —
        confirmed live across NVDA/AMZN/ZION/LLY/ASML/TSM that this endpoint
        returns 24 quarters of real reported EPS, comfortably past the 8 needed.
        No retry/backoff here (matches get_valuation_metrics's plain try/except
        for yfinance calls elsewhere in this class) — a single transient failure
        just yields None, same as before.

        Callers should still only invoke this near a ticker's own earnings date
        or on first-ever fetch (see indicator_pipeline.fetch_fundamental_data's
        fetch_eps_growth_trend gating) — not because of any budget now, but
        because this figure can't change between a company's quarterly reports,
        so a weekly refresh would just be redoing the same lookup.
        """
        try:
            df = yf.Ticker(ticker).get_earnings_dates(limit=12)
        except Exception as exc:
            logger.warning(f"{ticker}: get_earnings_dates failed — {exc}")
            write_validation_entry(ticker, "fundamental_eps_growth_error", str(exc))
            return None

        if df is None or df.empty or "Reported EPS" not in df.columns:
            logger.warning(f"{ticker}: no Reported EPS in earnings-date history")
            return None

        # Most-recent-first, dropping future/unreported quarters (NaN).
        reported = df["Reported EPS"].sort_index(ascending=False).dropna()
        if reported.empty:
            logger.warning(f"{ticker}: earnings-date history has no reported EPS yet")
            return None

        # Take up to 8 quarters so we can compute 4 YoY growth rates
        recent = list(reported.values)[:8]

        eps_growth_trend = []
        for i in range(min(4, len(recent))):
            reported_eps = recent[i]
            # YoY growth: compare quarter i to quarter i+4 (same quarter prior year)
            if i + 4 < len(recent):
                prior_eps = recent[i + 4]
                if prior_eps is not None and prior_eps != 0 and reported_eps is not None:
                    growth = (reported_eps - prior_eps) / abs(prior_eps)
                    eps_growth_trend.append(round(growth, 4))
                else:
                    eps_growth_trend.append(None)
            else:
                eps_growth_trend.append(None)

        return {"eps_growth_trend": eps_growth_trend}

    def get_estimate_revisions(self, ticker: str) -> dict:
        """
        Fetch analyst target price (yfinance) and rating breakdown (Finnhub
        /stock/recommendation). Replaced the prior Alpha Vantage OVERVIEW call —
        AV's free tier never provided a real revision history there either (current
        target price only), so this drops the second per-ticker AV call entirely
        for the same practical depth, at zero AV budget cost.

        Returns dict with:
          analyst_target_price     — yfinance targetMeanPrice
          current_price            — yfinance last close
          implied_upside_pct       — (target - current) / current; None if either unavailable
          analyst_rating_breakdown — Finnhub's most recent strongBuy/buy/hold/sell/
                                      strongSell counts, if available
          data_limitations         — note about what's not available on free tier
        """
        result = {
            "analyst_target_price": None,
            "current_price": None,
            "implied_upside_pct": None,
            "analyst_rating_breakdown": None,
            "data_limitations": (
                "Neither yfinance nor Finnhub's free tier provides a historical estimate "
                "revision sequence (upgrades vs. downgrades vs. 30 days ago) — only current "
                "target price and the latest rating snapshot are available without a paid tier."
            ),
        }

        try:
            info = yf.Ticker(ticker).info
            result["analyst_target_price"] = _safe_float(info.get("targetMeanPrice"))
            result["current_price"] = _safe_float(
                info.get("regularMarketPrice") or info.get("currentPrice") or info.get("previousClose")
            )
        except Exception as exc:
            logger.warning(f"{ticker}: yfinance target price fetch failed — {exc}")
            write_validation_entry(ticker, "fundamental_revisions_yfinance_error", str(exc))

        if result["analyst_target_price"] and result["current_price"]:
            upside = (result["analyst_target_price"] - result["current_price"]) / result["current_price"]
            result["implied_upside_pct"] = round(upside, 4)

        if not self._finnhub_key:
            logger.warning(f"{ticker}: skipping analyst rating — no Finnhub key")
            return result

        def _fetch_recommendation():
            params = {"symbol": ticker, "token": self._finnhub_key}
            resp = requests.get(f"{_FINNHUB_BASE_URL}/stock/recommendation", params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list):
                raise ValueError(f"Unexpected /stock/recommendation response shape: {type(data)}")
            return data

        data = self._with_backoff(_fetch_recommendation, ticker, "analyst_recommendation")
        if not data:
            return result

        latest = data[0]  # Finnhub returns most-recent-period-first
        result["analyst_rating_breakdown"] = {
            k: latest.get(k) for k in ("strongBuy", "buy", "hold", "sell", "strongSell")
            if latest.get(k) is not None
        } or None

        return result

    def get_all_fundamentals(self, ticker: str, fetch_eps_growth_trend: bool = True) -> dict:
        """
        Orchestrate calls to all fundamental data sources.

        fetch_eps_growth_trend: whether to also call Alpha Vantage for the deeper
        8-quarter YoY trend (get_eps_growth_trend). Callers should only pass True
        near a ticker's own earnings date or on its first-ever fetch — a routine
        weekly refresh doesn't need it, since that figure can't change between
        quarterly reports (see indicator_pipeline.fetch_fundamental_data).
        earnings_surprises/consecutive_beats (Finnhub, free) always refresh
        regardless of this flag.

        Returns combined dict with keys: valuation, earnings, revisions. "earnings"
        merges get_earnings_surprises() (Finnhub) and, when requested,
        get_eps_growth_trend() (Alpha Vantage) into the one dict shape
        fundamental_layer.py expects: {eps_growth_trend, earnings_surprises,
        consecutive_beats}. Any sub-call failure is caught and logged to
        validation_log.csv. Never raises — always returns a dict (fields may be
        None on failure).
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

        earnings: dict = {}

        try:
            surprises = self.get_earnings_surprises(ticker)
            if surprises:
                earnings.update(surprises)
        except Exception as exc:
            logger.error(f"{ticker}: get_earnings_surprises failed — {exc}")
            write_validation_entry(ticker, "fundamental_earnings_surprises_error", str(exc))

        if fetch_eps_growth_trend:
            try:
                growth = self.get_eps_growth_trend(ticker)
                if growth:
                    earnings.update(growth)
            except Exception as exc:
                logger.error(f"{ticker}: get_eps_growth_trend failed — {exc}")
                write_validation_entry(ticker, "fundamental_eps_growth_error", str(exc))

        result["earnings"] = earnings or None

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
        Strip API keys out of an error message before it's logged or written to
        validation_log.csv. requests' HTTPError embeds the full request URL (both
        apikey and token are query params), so an unredacted 429/403/5xx would
        otherwise write the live key to disk in plaintext.
        """
        if self._finnhub_key:
            text = text.replace(self._finnhub_key, "***REDACTED***")
        return text

    def _with_backoff(self, fn, ticker: str, label: str):
        """
        Call fn() with exponential backoff (30s → 60s → 120s → None), capped at
        _MAX_TOTAL_BACKOFF_SECONDS of total sleep. Logs each failure to
        validation_log.csv. Returns None after all retries or once the cap is hit.

        Without the cap, a full retry ladder (30+60+120=210s) on both the AV
        EARNINGS call and the Finnhub recommendation call across the whole
        watchlist is a long worst case, run synchronously inside the pipeline with
        no overall timeout — an outage on refresh day could stall whatever else
        shares that process. Capping bounds it to _MAX_TOTAL_BACKOFF_SECONDS/call.
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
