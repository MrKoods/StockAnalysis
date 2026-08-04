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

import pandas as pd
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
    "compute_iv_percentile",
]

_MIN_IV_HISTORY_SAMPLES = 10


def _pick_expiration(expirations: tuple, min_dte: int) -> str:
    """
    Pick the first listed expiration at least `min_dte` days out — the nearest
    expiration (expirations[0]) is frequently a 0DTE/weekly contract, which
    trade_selector.py's own Filter 8 always excludes from live trading anyway,
    so building the chain/Greeks data off it would pick strikes for expiries
    that can never actually be recommended. Falls back to the last available
    expiration (the longest-dated one on offer) if none clear the floor.
    """
    today = datetime.now(timezone.utc).date()
    for exp in expirations:
        try:
            exp_date = datetime.strptime(exp, "%Y-%m-%d").date()
        except ValueError:
            continue
        if (exp_date - today).days >= min_dte:
            return exp
    return expirations[-1]


def fetch_option_chain_metrics(ticker: str, current_price: Optional[float] = None, min_dte: int = 5) -> dict:
    """
    Fetch an option chain at least `min_dte` days out and derive put/call ratio,
    IV skew, and a normalized near-the-money contract list for Greeks/structure-
    leg selection (see shared/utils/options_math.py::select_directional_leg_strike,
    swing_model/trade_selector.py's Filter 4).

    current_price (if supplied by the caller, e.g. from already-fetched OHLCV close)
    is used to restrict IV averaging to a near-the-money band (+/-10%) rather than
    the full chain, which is skewed by far-OTM contracts. Falls back to the full
    chain average when current_price is not supplied. The `chain` field uses a
    wider +/-20% band since spread/collar legs can sit further from the money
    than the aggregate IV metrics need.

    Returns dict:
      put_call_ratio  — total put volume / total call volume (None if no volume)
      avg_call_iv     — mean implied volatility of near-the-money calls
      avg_put_iv      — mean implied volatility of near-the-money puts
      iv_skew         — avg_put_iv - avg_call_iv (positive = puts richer = bearish skew)
      expiration      — expiration date used (str, YYYY-MM-DD)
      dte             — days to that expiration (int, or None if unavailable)
      atm_iv          — mean(avg_call_iv, avg_put_iv), or whichever is available —
                         a single blended reading used by compute_iv_percentile()
                         to build a rolling IV-percentile history over time
      chain           — list of {strike, option_type, bid, ask, iv, open_interest,
                         expiration} within +/-20% of current_price, real contracts
                         only (used for Greeks/leg selection, not scoring)
      suspect_fields

    avg_call_iv/avg_put_iv (and therefore iv_skew/atm_iv) are only computed from
    contracts with a real two-sided quote (bid>0 AND ask>0) — yfinance's free-tier
    chain has been observed to return bid=ask=0.0 (not NaN) across an entire
    near-the-money band even alongside genuinely live volume/lastPrice, with a
    non-NaN but degenerate impliedVolatility riding along, so the IV column alone
    can't be trusted as the signal that data is missing. `chain` excludes those
    same void bid=ask=0.0 contracts too (see _build_chain_list) so Greeks/leg
    selection never treats an absent quote as a real $0.00-wide market.
    """
    result = {
        "put_call_ratio": None, "avg_call_iv": None, "avg_put_iv": None,
        "iv_skew": None, "expiration": None, "dte": None, "atm_iv": None, "chain": [],
        "suspect_fields": [],
    }

    def _fetch():
        t = yf.Ticker(ticker)
        expirations = t.options
        if not expirations:
            raise ValueError(f"No option expirations listed for {ticker}")
        expiration = _pick_expiration(expirations, min_dte)
        chain = t.option_chain(expiration)
        return expiration, chain.calls, chain.puts

    fetched = _fetch_with_backoff(_fetch, label=f"fetch_option_chain_metrics({ticker})")
    if fetched is None:
        write_validation_entry(ticker, "positioning_options_error", "option chain unavailable")
        return result

    expiration, calls, puts = fetched
    result["expiration"] = str(expiration)
    try:
        result["dte"] = (datetime.strptime(str(expiration), "%Y-%m-%d").date() - datetime.now(timezone.utc).date()).days
    except ValueError:
        pass

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

        # yfinance's free-tier option chain has been observed to return a real,
        # live `volume`/`lastPrice` alongside a completely void bid/ask surface —
        # bid=0.0 and ask=0.0 (not NaN) on every near-the-money contract, even for
        # NVDA at min_dte>=5 with tens of thousands of contracts traded per strike
        # (confirmed live 2026-08-03, also true for ZION/ASML/HD/TGT/SBUX). The
        # impliedVolatility column can't be trusted as the tell here — it holds
        # non-NaN, suspiciously round placeholder values (0.0625, 0.125, 0.25)
        # in exactly this scenario, not NaN. Trust IV only when at least one
        # near-the-money contract has a real two-sided quote (bid>0 AND ask>0)
        # backing it; average across just that quotable subset so one bad
        # placeholder row can't corrupt the mean.
        quotable_calls = band_calls[(band_calls["bid"] > 0) & (band_calls["ask"] > 0)]
        quotable_puts = band_puts[(band_puts["bid"] > 0) & (band_puts["ask"] > 0)]

        call_ivs = quotable_calls["impliedVolatility"].dropna()
        put_ivs = quotable_puts["impliedVolatility"].dropna()

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
            result["atm_iv"] = round((result["avg_call_iv"] + result["avg_put_iv"]) / 2.0, 4)
        elif result["avg_call_iv"] is not None:
            result["atm_iv"] = result["avg_call_iv"]
        elif result["avg_put_iv"] is not None:
            result["atm_iv"] = result["avg_put_iv"]

        result["chain"] = _build_chain_list(calls, puts, current_price, str(expiration))
    except Exception as exc:
        logger.warning(f"{ticker}: option chain metric computation failed — {exc}")
        write_validation_entry(ticker, "positioning_options_error", str(exc))

    return result


def _build_chain_list(calls, puts, current_price: Optional[float], expiration: str) -> list[dict]:
    """
    Normalize yfinance's calls/puts DataFrames into a flat list of real contracts
    within +/-20% of current_price (or the full chain if current_price is
    unavailable) — used by options_math.py to pick real strikes for a structure's
    legs and compute real Greeks, instead of the filter being skipped entirely.
    """
    if current_price is not None and current_price > 0:
        lo, hi = current_price * 0.80, current_price * 1.20
        band_calls = calls[(calls["strike"] >= lo) & (calls["strike"] <= hi)]
        band_puts = puts[(puts["strike"] >= lo) & (puts["strike"] <= hi)]
    else:
        band_calls, band_puts = calls, puts

    contracts = []
    for df, option_type in ((band_calls, "call"), (band_puts, "put")):
        for _, row in df.iterrows():
            iv = row.get("impliedVolatility")
            bid = row.get("bid")
            ask = row.get("ask")
            # A missing value in a pandas numeric column reads back as NaN, not
            # None — yfinance leaves bid/ask/IV blank (NaN) for illiquid strikes
            # routinely, so an `is None` check alone would silently let those
            # through as if they were real, tradeable quotes.
            if pd.isna(iv) or pd.isna(bid) or pd.isna(ask):
                continue
            # bid=0.0 AND ask=0.0 together (not NaN) is a separate failure mode:
            # a void/unquoted contract, not a real two-sided market where both
            # sides happen to be worthless — confirmed live (2026-08-03) across
            # every ticker tested, including highly-liquid NVDA with real,
            # current `volume`. Left in, this would look like a perfect $0.00-
            # wide spread to the Greeks filter and leg selection below instead
            # of the absent quote it actually is — the most dangerous shape of
            # bad data because it doesn't look broken.
            if bid == 0 and ask == 0:
                continue
            contracts.append({
                "strike": float(row["strike"]),
                "option_type": option_type,
                "bid": float(bid),
                "ask": float(ask),
                "iv": float(iv),
                "open_interest": float(row.get("openInterest", 0.0) or 0.0),
                "expiration": expiration,
            })
    return contracts


def compute_iv_percentile(current_iv: Optional[float], iv_history: list) -> dict:
    """
    Percentile rank of `current_iv` within `iv_history` (prior daily `atm_iv`
    readings, oldest-first — see indicator_pipeline.py::fetch_positioning_data,
    which appends one reading per ticker per day). Used to prefer premium-selling
    structures when IV is rich and premium-buying structures when IV is cheap,
    instead of always assuming a neutral 50th percentile.

    Requires at least _MIN_IV_HISTORY_SAMPLES prior readings before reporting a
    real percentile — same "accumulates going forward, not backtestable yet"
    caveat already accepted for Positioning/Sentiment (see PROJECT_OVERVIEW.md
    §13). Below that floor, returns a neutral 50.0 with data_quality flagged so
    callers can tell "genuinely mid-range" apart from "not enough history yet."

    Returns {"iv_percentile": float, "data_quality": "sufficient_history" |
    "insufficient_history" | "unavailable"}.
    """
    if current_iv is None:
        return {"iv_percentile": 50.0, "data_quality": "unavailable"}

    history = [v for v in (iv_history or []) if v is not None]
    if len(history) < _MIN_IV_HISTORY_SAMPLES:
        return {"iv_percentile": 50.0, "data_quality": "insufficient_history"}

    rank = sum(1 for v in history if v <= current_iv)
    percentile = round(100.0 * rank / len(history), 2)
    return {"iv_percentile": percentile, "data_quality": "sufficient_history"}


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


def fetch_all_positioning(ticker: str, current_price: Optional[float] = None, min_dte: int = 5) -> dict:
    """
    Orchestrate all Market Positioning fetches for one ticker.

    Never raises — each sub-fetch is caught and logged independently so a
    single source's failure doesn't take down the whole category.

    min_dte: passed through to fetch_option_chain_metrics — swing_config.yaml's
    greeks_filter.min_dte, so the chain built here uses the same DTE floor
    trade_selector.py's Greeks filter expects.
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
        result["options"] = fetch_option_chain_metrics(ticker, current_price, min_dte=min_dte)
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
