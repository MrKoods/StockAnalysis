"""
Market Positioning data client for the semiconductor swing trading model.

Fetches options positioning, short interest, institutional ownership, and
analyst rating trend via yfinance (no API key needed — unlike Sentiment,
this entire category degrades gracefully without any paid subscription).
Insider transactions are re-exported from market_data_client.py, which
already fetches SEC Form 4 data for the insider_tracker.py modifier.

Institutional ownership change (QoQ-style) requires comparing against a
prior snapshot since yfinance only exposes a current point-in-time holder
list — the previous snapshot is supplied by the caller (loaded from
data/processed/positioning_state.json), same pattern as fundamental_client.py's
weekly cache comparison.
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import yfinance as yf

from shared.utils.logger import get_logger, write_validation_entry
from shared.api_clients.market_data_client import fetch_insider_transactions  # re-exported

logger = get_logger(__name__)

_BACKOFF_DELAYS = [30, 60, 120]

__all__ = [
    "fetch_option_chain_metrics",
    "fetch_institutional_ownership",
    "fetch_short_interest",
    "fetch_analyst_rating_trend",
    "fetch_insider_transactions",
    "fetch_all_positioning",
]


def fetch_option_chain_metrics(ticker: str, current_price: Optional[float] = None) -> dict:
    """
    Fetch the nearest-expiration option chain and derive put/call ratio + IV skew.

    current_price (if supplied by the caller, e.g. from already-fetched OHLCV close)
    is used to restrict IV averaging to a near-the-money band (+/-10%) rather than
    the full chain, which is skewed by far-OTM contracts. Falls back to the full
    chain average when current_price is not supplied.

    Returns dict:
      put_call_ratio  — total put volume / total call volume (None if no volume)
      avg_call_iv     — mean implied volatility of near-the-money calls
      avg_put_iv      — mean implied volatility of near-the-money puts
      iv_skew         — avg_put_iv - avg_call_iv (positive = puts richer = bearish skew)
      expiration      — expiration date used (str, YYYY-MM-DD)
      suspect_fields
    """
    result = {
        "put_call_ratio": None, "avg_call_iv": None, "avg_put_iv": None,
        "iv_skew": None, "expiration": None, "suspect_fields": [],
    }

    def _fetch():
        t = yf.Ticker(ticker)
        expirations = t.options
        if not expirations:
            raise ValueError(f"No option expirations listed for {ticker}")
        expiration = expirations[0]
        chain = t.option_chain(expiration)
        return expiration, chain.calls, chain.puts

    fetched = _fetch_with_backoff(_fetch, label=f"fetch_option_chain_metrics({ticker})")
    if fetched is None:
        write_validation_entry(ticker, "positioning_options_error", "option chain unavailable")
        return result

    expiration, calls, puts = fetched
    result["expiration"] = str(expiration)

    try:
        call_vol = float(calls["volume"].fillna(0).sum())
        put_vol = float(puts["volume"].fillna(0).sum())
        if call_vol > 0:
            result["put_call_ratio"] = round(put_vol / call_vol, 4)
        else:
            result["suspect_fields"].append("put_call_ratio")

        if current_price is not None and current_price > 0:
            band_calls = calls[(calls["strike"] >= current_price * 0.90) & (calls["strike"] <= current_price * 1.10)]
            band_puts = puts[(puts["strike"] >= current_price * 0.90) & (puts["strike"] <= current_price * 1.10)]
        else:
            band_calls, band_puts = calls, puts

        call_ivs = band_calls["impliedVolatility"].dropna()
        put_ivs = band_puts["impliedVolatility"].dropna()

        if len(call_ivs) > 0:
            result["avg_call_iv"] = round(float(call_ivs.mean()), 4)
        else:
            result["suspect_fields"].append("avg_call_iv")

        if len(put_ivs) > 0:
            result["avg_put_iv"] = round(float(put_ivs.mean()), 4)
        else:
            result["suspect_fields"].append("avg_put_iv")

        if result["avg_call_iv"] is not None and result["avg_put_iv"] is not None:
            result["iv_skew"] = round(result["avg_put_iv"] - result["avg_call_iv"], 4)
    except Exception as exc:
        logger.warning(f"{ticker}: option chain metric computation failed — {exc}")
        write_validation_entry(ticker, "positioning_options_error", str(exc))

    return result


def fetch_institutional_ownership(ticker: str) -> dict:
    """
    Fetch current institutional ownership snapshot via yfinance.

    Returns dict:
      held_percent_institutions — float 0-1, or None
      top_holders               — list of {holder, shares, pct_out, date_reported}
      as_of_utc                 — ISO timestamp this snapshot was taken
    """
    result = {"held_percent_institutions": None, "top_holders": [], "as_of_utc": None}

    def _fetch():
        t = yf.Ticker(ticker)
        info = t.info
        held_pct = info.get("heldPercentInstitutions")
        holders_df = t.institutional_holders
        top_holders = []
        if holders_df is not None and not holders_df.empty:
            for _, row in holders_df.head(10).iterrows():
                top_holders.append({
                    "holder": row.get("Holder", ""),
                    "shares": row.get("Shares", None),
                    "pct_out": row.get("pctHeld", row.get("% Out", None)),
                    "date_reported": str(row.get("Date Reported", "")),
                })
        return held_pct, top_holders

    fetched = _fetch_with_backoff(_fetch, label=f"fetch_institutional_ownership({ticker})")
    if fetched is None:
        write_validation_entry(ticker, "positioning_institutional_error", "institutional holders unavailable")
        return result

    held_pct, top_holders = fetched
    result["held_percent_institutions"] = float(held_pct) if held_pct is not None else None
    result["top_holders"] = top_holders
    result["as_of_utc"] = datetime.now(timezone.utc).isoformat()
    return result


def fetch_short_interest(ticker: str) -> dict:
    """
    Fetch short interest data via yfinance Ticker.info.

    Returns dict:
      shares_short              — current shares sold short
      shares_short_prior_month  — shares short as of the prior month
      short_ratio               — days-to-cover
      short_percent_of_float    — float 0-1
      trend                     — 'declining' | 'increasing' | 'flat' | None
      suspect_fields
    """
    result = {
        "shares_short": None, "shares_short_prior_month": None,
        "short_ratio": None, "short_percent_of_float": None,
        "trend": None, "suspect_fields": [],
    }

    def _fetch():
        return yf.Ticker(ticker).info

    info = _fetch_with_backoff(_fetch, label=f"fetch_short_interest({ticker})")
    if info is None:
        write_validation_entry(ticker, "positioning_short_interest_error", "info unavailable")
        return result

    shares_short = info.get("sharesShort")
    shares_short_prior = info.get("sharesShortPriorMonth")
    short_ratio = info.get("shortRatio")
    short_pct_float = info.get("shortPercentOfFloat")

    result["shares_short"] = float(shares_short) if shares_short is not None else None
    result["shares_short_prior_month"] = float(shares_short_prior) if shares_short_prior is not None else None
    result["short_ratio"] = float(short_ratio) if short_ratio is not None else None
    result["short_percent_of_float"] = float(short_pct_float) if short_pct_float is not None else None

    if result["shares_short"] is not None and result["shares_short_prior_month"] not in (None, 0):
        change = (result["shares_short"] - result["shares_short_prior_month"]) / result["shares_short_prior_month"]
        if change <= -0.05:
            result["trend"] = "declining"
        elif change >= 0.05:
            result["trend"] = "increasing"
        else:
            result["trend"] = "flat"
    else:
        result["suspect_fields"].append("trend")

    return result


def fetch_analyst_rating_trend(ticker: str, lookback_days: int = 30) -> dict:
    """
    Fetch recent analyst rating *changes* (upgrades/downgrades) via yfinance
    Ticker.upgrades_downgrades — distinct from the static recommendationMean
    level already scored by the Fundamental layer's analyst_consensus_score.

    Returns dict:
      recent_upgrades   — count of upgrade actions in lookback window
      recent_downgrades — count of downgrade actions in lookback window
      net_action        — 'upgrade' | 'downgrade' | 'mixed' | 'none'
      suspect_fields
    """
    result = {"recent_upgrades": 0, "recent_downgrades": 0, "net_action": "none", "suspect_fields": []}

    def _fetch():
        t = yf.Ticker(ticker)
        df = getattr(t, "upgrades_downgrades", None)
        return df

    df = _fetch_with_backoff(_fetch, label=f"fetch_analyst_rating_trend({ticker})")
    if df is None or df.empty:
        result["suspect_fields"].append("upgrades_downgrades")
        return result

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    try:
        idx = df.index
        if not hasattr(idx, "tz") or idx.tz is None:
            recent = df[idx.tz_localize("UTC") >= cutoff] if hasattr(idx, "tz_localize") else df
        else:
            recent = df[idx >= cutoff]
    except Exception:
        recent = df.head(20)  # fallback: most recent N rows if date filtering fails

    upgrades = 0
    downgrades = 0
    for _, row in recent.iterrows():
        action = str(row.get("Action", "")).lower()
        if action == "up":
            upgrades += 1
        elif action == "down":
            downgrades += 1

    result["recent_upgrades"] = upgrades
    result["recent_downgrades"] = downgrades
    if upgrades > 0 and downgrades == 0:
        result["net_action"] = "upgrade"
    elif downgrades > 0 and upgrades == 0:
        result["net_action"] = "downgrade"
    elif upgrades > 0 and downgrades > 0:
        result["net_action"] = "mixed"
    else:
        result["net_action"] = "none"

    return result


def fetch_all_positioning(ticker: str, current_price: Optional[float] = None) -> dict:
    """
    Orchestrate all Market Positioning fetches for one ticker.

    Never raises — each sub-fetch is caught and logged independently so a
    single source's failure doesn't take down the whole category.
    """
    result = {
        "ticker": ticker,
        "options": None,
        "institutional": None,
        "short_interest": None,
        "analyst_trend": None,
        "insider_transactions": None,
    }

    try:
        result["options"] = fetch_option_chain_metrics(ticker, current_price)
    except Exception as exc:
        logger.error(f"{ticker}: fetch_option_chain_metrics failed — {exc}")
        write_validation_entry(ticker, "positioning_options_error", str(exc))

    try:
        result["institutional"] = fetch_institutional_ownership(ticker)
    except Exception as exc:
        logger.error(f"{ticker}: fetch_institutional_ownership failed — {exc}")
        write_validation_entry(ticker, "positioning_institutional_error", str(exc))

    try:
        result["short_interest"] = fetch_short_interest(ticker)
    except Exception as exc:
        logger.error(f"{ticker}: fetch_short_interest failed — {exc}")
        write_validation_entry(ticker, "positioning_short_interest_error", str(exc))

    try:
        result["analyst_trend"] = fetch_analyst_rating_trend(ticker)
    except Exception as exc:
        logger.error(f"{ticker}: fetch_analyst_rating_trend failed — {exc}")
        write_validation_entry(ticker, "positioning_analyst_error", str(exc))

    try:
        result["insider_transactions"] = fetch_insider_transactions(ticker)
    except Exception as exc:
        logger.error(f"{ticker}: fetch_insider_transactions failed — {exc}")
        write_validation_entry(ticker, "positioning_insider_error", str(exc))

    return result


def _fetch_with_backoff(fn, retries: int = 3, label: str = ""):
    """Execute fn() with exponential backoff. Schedule: 30s -> 60s -> 120s -> None."""
    last_exc = None
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt < len(_BACKOFF_DELAYS):
                delay = _BACKOFF_DELAYS[attempt]
                logger.warning(f"[{label}] Attempt {attempt + 1} failed: {exc}. Retrying in {delay}s.")
                time.sleep(delay)
    logger.error(f"[{label}] All {retries} retries exhausted. Last error: {last_exc}")
    return None
