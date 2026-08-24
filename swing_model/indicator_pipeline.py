"""
Orchestrates all data pulls + indicator calculations for the semiconductor watchlist.
Produces a normalized output table per ticker — one row per ticker with all indicator
values needed by scoring.py. Runs 2-3x daily (pre-market, mid-session, post-close).

Fundamental data is refreshed on a staggered per-ticker cadence (see
fetch_fundamental_data) and cached in data/processed/fundamental_state.json. On days
a given ticker isn't due, its cached data is loaded so fundamental scores are
available every scan without API calls.
"""

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
import yaml
import yfinance as yf

from shared.api_clients.market_data_client import fetch_ohlcv, fetch_ohlcv_batch
from shared.indicators.technical_common import compute_technical_indicators
from shared.utils.logger import get_logger, write_validation_entry
from shared.api_clients.fundamental_client import FundamentalClient
from swing_model.fundamental_layer import FundamentalScorer
from shared.api_clients.positioning_client import (
    fetch_all_positioning, compute_iv_percentile,
    compute_put_call_ratio_percentile, compute_iv_skew_percentile,
)
from swing_model.positioning_layer import compute_positioning_score
from shared.utils.data_validator import validate_ohlcv, validate_positioning_data

logger = get_logger(__name__)

_ET = ZoneInfo("America/New_York")
_FUNDAMENTAL_STATE_PATH = Path("data/processed/fundamental_state.json")
_FUNDAMENTAL_HISTORY_DIR = Path("data/processed/fundamental_history")
_POSITIONING_STATE_PATH = Path("data/processed/positioning_state.json")
_MAX_IV_HISTORY_DAYS = 252  # ~1 trading year — bounds iv_history/put_call_ratio_history/iv_skew_history's growth, oldest dropped first

# Delay before the single retry fetch on a Phase 9 OHLCV validation failure —
# long enough to give a transient vendor-side settlement race a real chance to
# resolve, short enough that a scan already excluding this rare a ticker
# (roughly 1/day historically) doesn't stall meaningfully waiting on it.
_OHLCV_RETRY_DELAY_SECONDS = 15

# Fundamental refresh is staggered rather than bursting the whole watchlist on one
# day. eps_growth_trend (the one figure that used to require Alpha Vantage) now
# comes from yfinance's earnings-date history instead (see
# fundamental_client.get_eps_growth_trend) — this pipeline no longer touches Alpha
# Vantage's budget at all. It still only fires for a cold-start ticker or one near
# its own earnings date, not on routine rotation refresh (see get_all_fundamentals's
# fetch_eps_growth_trend parameter), but that's now about avoiding redundant yfinance
# lookups for a figure that can't change between quarterly reports, not budget.
#
# Raised 5 -> 25 (2026-08-06): the healthcare starvation this comment used to
# describe (4 of 6 tickers stuck at fundamental_score=0/as_of=never for a week after
# v2.2.24) recurred identically for consumer_discretionary — HD/NKE/SBUX/TGT (last
# sector processed, last 4 tickers in its list) never won a bootstrap slot against
# the 3 earlier sectors' daily rotation/bootstrap needs sharing the same cap. The
# AV-budget rationale this cap was sized for no longer applies (fundamental_client.py
# is fully off Alpha Vantage — yfinance + Finnhub only, neither with a meaningful
# daily quota at 23 tickers), so there's no longer a real constraint to ration
# against. Set above the full watchlist size (23) so a cold-start day can bootstrap
# every ticker in one pass instead of starving whichever sector is processed last.
_FUNDAMENTAL_MAX_TICKERS_PER_DAY = 25
_FUNDAMENTAL_ROTATION_WINDOW_DAYS = 7
_FUNDAMENTAL_EARNINGS_LOOKAHEAD_DAYS = 3

# Figures sourced from the same quarterly filing as eps_growth_trend — none of
# these can change mid-quarter, so a plain rotation refresh (fetch_growth=False)
# carries the last-known value forward instead of re-fetching it.
_QUARTERLY_CARRY_FORWARD_KEYS = (
    "eps_growth_trend",
    "revenue_yoy_growth",
    "gross_margin_latest",
    "gross_margin_prior",
)


def run_pipeline(
    tickers: list[str],
    benchmark: str = "SMH",
    scan_type: str = "post_close",
    cfg: Optional[dict] = None,
) -> dict[str, Optional[dict]]:
    """
    Run the full technical indicator pipeline for all tickers in the watchlist.

    Steps:
    1. Fetch OHLCV for all tickers + benchmark (batch call)
    2. Run basic validation on each ticker's data
    3. Compute technical indicators for each valid ticker
    4. Fetch or load cached fundamental data (weekly cadence)
    5. Score fundamental data for all tickers
    6. Attach fundamental scores to indicator output
    7. Return dict mapping ticker → indicator_dict (or None if excluded)

    Returns dict: {ticker → indicator_dict or None}
    Tickers excluded by validation are logged to validation_log.csv.
    Sentiment/news layers are called downstream in run_swing_model.py (not here).
    """
    if cfg is None:
        cfg = load_config()

    all_tickers = tickers + [benchmark]
    logger.info(f"[{scan_type}] Fetching OHLCV for: {all_tickers}")

    # 1. Batch fetch OHLCV
    raw_data = fetch_ohlcv_batch(all_tickers, period="6mo", interval="1d")
    if raw_data is None:
        logger.error("Batch OHLCV fetch returned None — invoking data-unavailable mode.")
        return {t: None for t in tickers}

    # 2. Validate and compute indicators per ticker
    benchmark_df = raw_data.get(benchmark)
    if benchmark_df is None or benchmark_df.empty:
        logger.error(f"Benchmark {benchmark} data unavailable — cannot compute RS. Proceeding without RS.")
        benchmark_close = None
    else:
        benchmark_close = benchmark_df["Close"]

    results: dict[str, Optional[dict]] = {}
    for ticker in tickers:
        df = raw_data.get(ticker)
        if df is None or df.empty:
            logger.warning(f"{ticker}: OHLCV data unavailable — excluded from scan.")
            write_validation_entry(ticker, "ohlcv_unavailable", "yfinance returned None or empty DataFrame")
            results[ticker] = None
            continue

        # Basic OHLCV sanity check (bar count, all-NaN) before the richer
        # Phase 9 checks below, which assume a non-empty, mostly-populated frame.
        if not _basic_validate(ticker, df):
            results[ticker] = None
            continue

        # Phase 9 validation (data_validator.py) — gap detection, extreme
        # single-day-move/split detection, and Open-price-range checking on
        # top of _basic_validate's cheaper checks. This function's own
        # docstring already claimed this ran here; it never actually did
        # (Signal Integrity Audit finding E.1) — a >50% single-day move (bad
        # print, unadjusted split) or a multi-day data gap flowed straight
        # into indicator computation with zero validation.
        ohlcv_valid, ohlcv_failures = validate_ohlcv(ticker, df, cfg=cfg)
        if not ohlcv_valid:
            # One short-delay retry before excluding — some OHLC inconsistencies
            # are a transient vendor-side settlement race rather than genuine
            # corruption (observed live: AMD 2026-08-24 failed validation at
            # scan time but the same trading-day bar was internally consistent
            # when re-checked later that day). fetch_ohlcv is a fresh
            # single-ticker call, not fetch_ohlcv_batch's cache, so this
            # actually re-fetches rather than re-validating the same stale frame.
            logger.info(
                f"{ticker}: Phase 9 validation failed ({ohlcv_failures}) — "
                f"retrying fetch once in {_OHLCV_RETRY_DELAY_SECONDS}s"
            )
            time.sleep(_OHLCV_RETRY_DELAY_SECONDS)
            retry_df = fetch_ohlcv(ticker, period="6mo", interval="1d")
            if retry_df is not None and not retry_df.empty:
                retry_valid, ohlcv_failures = validate_ohlcv(ticker, retry_df, cfg=cfg)
                if retry_valid:
                    logger.info(f"{ticker}: retry fetch passed validation — using refreshed data")
                    df = retry_df
                    ohlcv_valid = True
            if not ohlcv_valid:
                logger.warning(f"{ticker}: Phase 9 OHLCV validation failed ({ohlcv_failures}) — excluded.")
                results[ticker] = None
                continue

        # Use benchmark close aligned to ticker index, or flat series if unavailable
        if benchmark_close is not None:
            bench_aligned = benchmark_close.reindex(df.index, method="ffill")
        else:
            bench_aligned = pd.Series(100.0, index=df.index)

        try:
            indicators = compute_technical_indicators(df, bench_aligned, cfg)
            indicators["ticker"] = ticker
            indicators["scan_type"] = scan_type
            indicators["computed_at_utc"] = datetime.now(timezone.utc).isoformat()
            indicators["data_bars"] = len(df)
            results[ticker] = indicators
            logger.info(f"{ticker}: indicators computed (close={indicators['close']:.2f}, "
                        f"rsi={indicators['rsi_14']:.1f}, atr={indicators['atr_14']:.2f})")
        except Exception as exc:
            logger.error(f"{ticker}: indicator computation failed — {exc}")
            write_validation_entry(ticker, "indicator_error", str(exc))
            results[ticker] = None

    # Today's live closes, shared by both the fundamental (implied-upside
    # recompute) and positioning layers below — computed once here rather
    # than twice.
    current_prices = {
        t: results[t].get("close") for t in tickers if results.get(t) is not None
    }

    # 4-6. Fundamental data fetch + scoring
    try:
        fundamental_state = fetch_fundamental_data(tickers, cfg)
        scorer = FundamentalScorer(cfg)
        fundamental_scores = scorer.score_all_tickers(tickers, fundamental_state, current_prices=current_prices)
    except Exception as exc:
        logger.error(f"Fundamental layer failed — {exc}. Proceeding with neutral scores.")
        write_validation_entry("ALL", "fundamental_layer_error", str(exc))
        scorer = FundamentalScorer(cfg)
        fundamental_scores = {t: scorer._unavailable_score(t) for t in tickers}

    # Attach fundamental scores to each ticker's indicator dict
    for ticker in tickers:
        if results.get(ticker) is not None:
            fs = fundamental_scores.get(ticker, scorer._unavailable_score(ticker))
            results[ticker]["fundamental_score"] = fs.get("fundamental_score", 0)
            results[ticker]["earnings_momentum_score"] = fs.get("earnings_momentum_score", 0)
            results[ticker]["valuation_score"] = fs.get("valuation_score", 0)
            results[ticker]["fundamental_data_quality"] = fs.get("data_quality", "unavailable")
            results[ticker]["fundamental_data_as_of"] = fs.get("data_as_of")
            results[ticker]["_fundamental_full"] = fs

    # 7-8. Market Positioning data fetch + scoring (daily cadence — free yfinance data only)
    #
    # Scored for both directions here (cheap — same cached raw data, direction
    # only changes which side of each sub-formula scores high, no extra I/O)
    # since a ticker's real trade direction isn't known until the per-ticker
    # scoring loop runs later (run_swing_model.py/paper_runner.py) — direction
    # depends on that day's technical/sentiment reading, not on anything fetched
    # here. _positioning_full stays the bullish score (unchanged field, for
    # every existing caller); _positioning_full_bearish is the new bearish
    # mirror, selected by direction once it's known.
    try:
        positioning_state = fetch_positioning_data(tickers, current_prices, cfg)
        previous_tickers = positioning_state.get("previous_tickers", {})
        positioning_scores = {
            t: compute_positioning_score(
                t, positioning_state.get("tickers", {}).get(t), previous_tickers.get(t), cfg, direction="bullish"
            )
            for t in tickers
        }
        positioning_scores_bearish = {
            t: compute_positioning_score(
                t, positioning_state.get("tickers", {}).get(t), previous_tickers.get(t), cfg, direction="bearish"
            )
            for t in tickers
        }
    except Exception as exc:
        logger.error(f"Positioning layer failed — {exc}. Proceeding with neutral scores.")
        write_validation_entry("ALL", "positioning_layer_error", str(exc))
        positioning_scores = {t: compute_positioning_score(t, None, None, cfg, direction="bullish") for t in tickers}
        positioning_scores_bearish = {
            t: compute_positioning_score(t, None, None, cfg, direction="bearish") for t in tickers
        }

    # Attach positioning scores to each ticker's indicator dict
    for ticker in tickers:
        if results.get(ticker) is not None:
            ps = positioning_scores.get(ticker) or compute_positioning_score(ticker, None, None, cfg, direction="bullish")
            ps_bearish = positioning_scores_bearish.get(ticker) or compute_positioning_score(
                ticker, None, None, cfg, direction="bearish"
            )
            results[ticker]["positioning_score"] = ps.get("positioning_score_total", 0)
            results[ticker]["positioning_data_quality"] = ps.get("data_quality", "unavailable")
            results[ticker]["_positioning_full"] = ps
            results[ticker]["_positioning_full_bearish"] = ps_bearish

    valid_count = sum(1 for v in results.values() if v is not None)
    logger.info(f"Pipeline complete: {valid_count}/{len(tickers)} tickers processed successfully.")
    return results


def _rotation_weekday(ticker: str) -> int:
    """Stable Mon-Fri (0-4) weekly refresh slot for a ticker, spreading the
    watchlist's fundamental refreshes across the week instead of one burst day.
    Uses a stable hash (not builtin hash(), which is randomized per-process) so
    the assignment doesn't drift between runs."""
    digest = hashlib.sha256(ticker.encode()).hexdigest()
    return int(digest, 16) % 5


def _get_upcoming_earnings_date(ticker: str):
    """Free (yfinance) lookup of a ticker's next known earnings date, used only to
    prioritize refresh timing — never consumes Alpha Vantage budget. Returns None
    if unavailable rather than raising, since this is a scheduling hint, not a
    required input.

    Normalizes yfinance's calendar shape the same way
    market_data_client.fetch_earnings_calendar already has to (it can return
    a bare date, or — on newer yfinance versions — a dict with raw/fmt keys).
    Previously this returned whatever `cal.get("Earnings Date")[0]` was
    unmodified; when that was a dict rather than a date, the caller's
    `abs((earnings_date - today_date).days)` raised an uncaught TypeError
    that propagated out of fetch_fundamental_data's per-ticker loop and
    zeroed out fundamental scoring for the ENTIRE batch that run, not just
    this one ticker's odd calendar shape (Signal Integrity Audit finding
    E.2). Returns a plain date (not datetime) to match the `date_obj -
    today_date` arithmetic callers already do.
    """
    try:
        cal = yf.Ticker(ticker).calendar or {}
        dates = cal.get("Earnings Date") or []
        if not dates:
            return None
        first = dates[0] if hasattr(dates, "__getitem__") else None
        if first is None:
            return None
        if isinstance(first, dict):
            raw = first.get("raw") or first.get("timestamp")
            fmt = first.get("fmt") or first.get("date")
            if raw:
                return pd.Timestamp(raw, unit="s").date()
            if fmt:
                return pd.Timestamp(fmt).date()
            return None
        return pd.Timestamp(first).date()
    except Exception:
        return None


def _get_last_reported_earnings_date(ticker: str):
    """Free (yfinance) lookup of a ticker's most recently ACTUALLY reported
    earnings date — deliberately separate from _get_upcoming_earnings_date's
    forward-looking calendar value.

    Confirmed live (2026-08-13): once a company reports, yfinance's calendar
    flips to the NEXT quarter almost immediately — AMD's calendar already
    showed Nov 3 the same week it reported on Aug 4. That means the
    ±_FUNDAMENTAL_EARNINGS_LOOKAHEAD_DAYS window around "next earnings" can
    only ever really fire BEFORE a report, not after, even though it reads as
    symmetric. Without this second check, a report landing on a ticker's
    routine rotation day (fetch_growth=False) leaves eps_growth_trend stuck on
    the prior quarter until ~3 days before the NEXT report, since a plain
    rotation refresh doesn't request it (see get_all_fundamentals's
    fetch_eps_growth_trend gating below).

    Returns None if unavailable rather than raising, since this is a
    scheduling hint, not a required input."""
    try:
        df = yf.Ticker(ticker).get_earnings_dates(limit=4)
    except Exception:
        return None
    if df is None or df.empty or "Reported EPS" not in df.columns:
        return None
    reported = df["Reported EPS"].dropna()
    if reported.empty:
        return None
    return reported.sort_index(ascending=False).index[0].date()


def _days_since(date_str: Optional[str], today) -> Optional[int]:
    if not date_str:
        return None
    try:
        return (today - datetime.strptime(date_str, "%Y-%m-%d").date()).days
    except Exception:
        return None


def fetch_fundamental_data(tickers: list[str], cfg: Optional[dict] = None) -> dict:
    """
    Fetch or load fundamental data for the given tickers.

    Cadence logic (tracked per ticker via state["fetched_dates"], not one
    file-wide last_updated — a file-wide timestamp meant a sector processed
    later in the same run would see an earlier sector's fetch and conclude its
    own tickers were "already refreshed today" when they'd never been fetched
    at all). Refreshes are staggered rather than bursting the whole watchlist
    on one day, since fundamental data shares the AV budget with post-close
    news — see _FUNDAMENTAL_MAX_TICKERS_PER_DAY.
    On each call, a ticker is a refresh candidate if:
      - it has never been fetched (cold start), highest priority; or
      - it's within _FUNDAMENTAL_EARNINGS_LOOKAHEAD_DAYS of its next known
        earnings date (free yfinance calendar lookup) — the one event that
        actually invalidates cached fundamentals, so it jumps the queue; or
      - it actually reported earnings more recently than growth data was last
        PULLED for it (see _get_last_reported_earnings_date and
        growth_fetched_dates, tracked separately from fetched_dates since a
        plain rotation touch can update fetched_dates without ever
        re-pulling growth) — catches a report that landed after the "next
        earnings" calendar had already flipped forward past it, which
        happens almost immediately once a company reports; or
      - today is its stable assigned weekday (_rotation_weekday) and it's been
        >= _FUNDAMENTAL_ROTATION_WINDOW_DAYS since its last fetch.
    Only bootstrap/earnings-priority tickers actually spend an Alpha Vantage
    call (for eps_growth_trend) — a plain rotation refresh reuses the last
    known value instead, since that figure can't change between quarterly
    reports. earnings_surprises/consecutive_beats (Finnhub, free) refresh
    every time regardless. See get_all_fundamentals's fetch_eps_growth_trend
    parameter.
    At most _FUNDAMENTAL_MAX_TICKERS_PER_DAY tickers actually fetch per calendar
    day in total (in that priority order), counted across every call today —
    every scan x every sector shares this one state file, so the budget is
    tracked globally via how many tickers already show today's date in
    fetched_dates, not reset per call. Anything past the day's remaining budget
    waits for its next due day.

    Writes fresh data to fundamental_state.json when fetched.
    Logs any fetch failures to validation_log.csv without crashing.

    Returns dict with structure:
      {"last_updated": ..., "tickers": {ticker: data},
       "fetched_dates": {ticker: "YYYY-MM-DD"},
       "growth_fetched_dates": {ticker: "YYYY-MM-DD"}}
    """
    if cfg is None:
        cfg = {}

    state = _load_fundamental_state()
    now_et = datetime.now(_ET)
    today_str = now_et.strftime("%Y-%m-%d")
    today_date = now_et.date()
    fetched_dates = state.setdefault("fetched_dates", {})
    # Tracks when eps_growth_trend/revenue were actually last PULLED
    # (fetch_growth=True), separate from fetched_dates (which also includes
    # plain rotation touches that skip them). Comparing a missed-report check
    # against fetched_dates alone would self-defeat: a rotation refresh that
    # happens to land after a report still updates fetched_dates without
    # actually re-pulling growth data, permanently masking the staleness this
    # check exists to catch.
    growth_fetched_dates = state.setdefault("growth_fetched_dates", {})
    state.setdefault("tickers", {})

    bootstrap, earnings_priority, rotation_due = [], [], []
    for t in tickers:
        # Wrapped per-ticker: previously an uncaught exception anywhere in
        # this body (e.g. the earnings-date TypeError E.2 fixed above)
        # propagated out of this whole function, which fetch_fundamental_data's
        # own caller treats as "fetch failed" for the ENTIRE watchlist that
        # run — one ticker's odd data shape shouldn't zero out every other
        # ticker's fundamental scoring (Signal Integrity Audit finding E.2).
        try:
            if fetched_dates.get(t) == today_str:
                continue  # already refreshed today

            last_fetch = fetched_dates.get(t)
            if last_fetch is None:
                bootstrap.append(t)
                continue

            earnings_date = _get_upcoming_earnings_date(t)
            if earnings_date is not None and abs((earnings_date - today_date).days) <= _FUNDAMENTAL_EARNINGS_LOOKAHEAD_DAYS:
                earnings_priority.append(t)
                continue

            # Only checked when not already near the next scheduled date (saves a
            # yfinance call in the common case) — catches a report that happened
            # since growth data was last actually pulled, even though the
            # forward-looking calendar has already rolled past it (see
            # _get_last_reported_earnings_date). Compared against
            # growth_fetched_dates, NOT last_fetch — a plain rotation refresh can
            # touch fetched_dates without ever re-pulling growth data (see above).
            # A ticker with no growth_fetched_dates entry at all (pre-existing
            # cache from before this field existed) is treated as needing one
            # baseline refresh, not assumed current.
            last_reported = _get_last_reported_earnings_date(t)
            last_growth_fetch = growth_fetched_dates.get(t)
            last_growth_fetch_date = (
                datetime.strptime(last_growth_fetch, "%Y-%m-%d").date() if last_growth_fetch else None
            )
            if last_reported is not None and (last_growth_fetch_date is None or last_reported > last_growth_fetch_date):
                earnings_priority.append(t)
                continue

            days_stale = _days_since(last_fetch, today_date)
            if today_date.weekday() == _rotation_weekday(t) and (days_stale is None or days_stale >= _FUNDAMENTAL_ROTATION_WINDOW_DAYS):
                rotation_due.append(t)
        except Exception as exc:
            logger.warning(f"{t}: fundamental refresh categorization failed — {exc}")
            continue

    # The cap is per calendar day across ALL calls (every scan x every sector shares
    # this one state file), not per call — fetch_fundamental_data runs once per scan
    # (3x/day) per sector, so capping only within a single call let the day's total
    # balloon past the intended ceiling (e.g. 3 calls x 3 candidates = up to 9/day/
    # sector, which is exactly what happened: 6 tickers fetched in one day before
    # this fix). already_fetched_today counts every ticker any prior call today
    # already fetched, regardless of which sector's call did it.
    already_fetched_today = sum(1 for v in fetched_dates.values() if v == today_str)
    remaining_budget = max(0, _FUNDAMENTAL_MAX_TICKERS_PER_DAY - already_fetched_today)
    to_fetch = (bootstrap + earnings_priority + rotation_due)[:remaining_budget]

    if not to_fetch:
        logger.info(f"Loading cached fundamental data (last_updated: {state.get('last_updated')})")
        return state

    logger.info(f"Fetching fundamental data for: {to_fetch}")
    client = FundamentalClient()
    bootstrap_or_earnings = set(bootstrap) | set(earnings_priority)
    # Save after every ticker, not just once at the end — a full refresh can take
    # several minutes (each sub-call retries on rate limits), and a mid-batch
    # interruption (manual Ctrl+C, crash, hitting the AV budget cap) must not
    # discard tickers that already completed. fetched_dates is updated per-ticker
    # as each one succeeds, so a crash mid-loop leaves completed tickers correctly
    # marked "fetched today" and only the remainder gets retried next opportunity.
    for ticker in to_fetch:
        # Alpha Vantage's eps_growth_trend only gets refreshed for a cold-start
        # ticker or one near its own earnings date — a plain weekly rotation
        # refresh reuses the last known value instead of spending an AV call to
        # get back the same answer (see get_all_fundamentals's docstring).
        fetch_growth = ticker in bootstrap_or_earnings
        old_record = state["tickers"].get(ticker) or {}
        try:
            new_data = client.get_all_fundamentals(ticker, fetch_eps_growth_trend=fetch_growth)
            if not fetch_growth:
                old_earnings = old_record.get("earnings") or {}
                if new_data.get("earnings") is None:
                    new_data["earnings"] = {}
                # Same "can't change mid-quarter" reasoning as eps_growth_trend
                # applies to the revenue/margin figures — both come from the
                # same quarterly filing and are gated by the same fetch_growth
                # flag in get_all_fundamentals.
                for key in _QUARTERLY_CARRY_FORWARD_KEYS:
                    old_val = old_earnings.get(key)
                    if old_val is not None:
                        new_data["earnings"].setdefault(key, old_val)

            # Stash the PRIOR analyst target price before it's overwritten below
            # — fundamental_layer.py's estimate_revisions_score uses the two
            # snapshots to measure whether analysts actually raised/lowered
            # their number, instead of reading a single snapshot's price-vs-
            # target gap (which moves with the stock price, not with revisions).
            old_target = (old_record.get("revisions") or {}).get("analyst_target_price")
            if old_target is not None and new_data.get("revisions") is not None:
                new_data["revisions"]["prior_analyst_target_price"] = old_target
                new_data["revisions"]["prior_target_as_of"] = fetched_dates.get(ticker)

            state["tickers"][ticker] = new_data
            state["fetched_dates"][ticker] = today_str
            if fetch_growth:
                state["growth_fetched_dates"][ticker] = today_str
            suffix = "" if fetch_growth else " (EPS growth trend carried forward, not AV-refreshed)"
            logger.info(f"  {ticker}: fundamental data fetched OK{suffix}")
        except Exception as exc:
            logger.error(f"  {ticker}: fundamental fetch failed — {exc}")
            write_validation_entry(ticker, "fundamental_fetch_error", str(exc))
            state["tickers"][ticker] = None
        _save_fundamental_state(state)

    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    _save_fundamental_state(state)
    _archive_fundamental_snapshot(state)
    return state


def _append_and_score_history(
    history_by_ticker: dict, ticker: str, current_value, percentile_fn, dq_field_name: str
) -> dict:
    """
    Append today's reading to `history_by_ticker[ticker]` (creating it if
    needed, capped at _MAX_IV_HISTORY_DAYS), then score today's value against
    the PRIOR history only (excluding the just-appended reading — comparing
    today's value against itself would trivially always land near the 50th
    percentile). Shared by atm_iv/put_call_ratio/iv_skew, which all follow
    the same "accumulates going forward" rolling-history shape.

    All three of compute_iv_percentile/compute_put_call_ratio_percentile/
    compute_iv_skew_percentile return their data-quality flag under the same
    generic "data_quality" key — fine standalone, but the caller merges all
    three results into one shared options dict, where each subsequent
    .update() would otherwise silently overwrite the previous metric's
    data_quality under that identical key. Renamed to dq_field_name here so
    all three survive the merge.
    """
    ticker_history = history_by_ticker.setdefault(ticker, [])
    if current_value is not None:
        ticker_history.append(current_value)
        del ticker_history[:-_MAX_IV_HISTORY_DAYS]
    result = percentile_fn(current_value, ticker_history[:-1])
    if "data_quality" in result:
        result[dq_field_name] = result.pop("data_quality")
    return result


def fetch_positioning_data(tickers: list[str], current_prices: dict, cfg: Optional[dict] = None) -> dict:
    """
    Fetch or load Market Positioning data for the given tickers (daily cadence,
    tracked per ticker).

    Cadence logic: each ticker is refreshed at most once per day, tracked via
    state["fetched_dates"] rather than a single file-wide last_updated — a file-wide
    timestamp meant a sector processed later in the same run (e.g. a newly-activated
    sector) would see an earlier sector's fetch and inherit its "already fetched
    today" status without ever being fetched itself. Refreshing a ticker preserves
    its prior snapshot under "previous_tickers" so positioning_layer.py can compute
    the institutional ownership delta — same forward-building-history caveat as
    Fundamental/Sentiment (no deep historical positioning archive exists; it
    accumulates from first live scan).

    Returns dict: {last_updated, tickers, previous_updated, previous_tickers, fetched_dates}
    """
    if cfg is None:
        cfg = {}

    state = _load_positioning_state()
    now_et = datetime.now(_ET)
    today_str = now_et.strftime("%Y-%m-%d")
    fetched_dates = state.setdefault("fetched_dates", {})
    state.setdefault("tickers", {})
    state.setdefault("previous_tickers", {})

    to_fetch = [t for t in tickers if fetched_dates.get(t) != today_str]
    if not to_fetch:
        logger.info(f"Loading cached positioning data (last_updated: {state.get('last_updated')})")
        return state

    logger.info(f"Fetching positioning data for: {to_fetch}")
    iv_history = state.setdefault("iv_history", {})
    put_call_ratio_history = state.setdefault("put_call_ratio_history", {})
    iv_skew_history = state.setdefault("iv_skew_history", {})
    min_dte = int(cfg.get("greeks_filter", {}).get("min_dte", 5))
    for ticker in to_fetch:
        if ticker in state["tickers"]:
            state["previous_tickers"][ticker] = state["tickers"][ticker]
        try:
            fresh = fetch_all_positioning(ticker, current_price=current_prices.get(ticker), min_dte=min_dte, cfg=cfg)
            # Log-only visibility, not a hard gate — positioning_layer.py
            # already defaults each sub-signal to neutral on missing/None
            # fields, so this doesn't change scoring behavior. The gap this
            # closes is that an out-of-bounds field (e.g. a data error
            # producing held_percent_institutions > 1.0) previously flowed
            # into scoring with no logged trace at all (Signal Integrity
            # Audit finding E.1).
            _positioning_valid, _positioning_failures = validate_positioning_data(ticker, fresh)
            if not _positioning_valid:
                logger.warning(f"{ticker}: Phase 9 positioning validation flagged {_positioning_failures}")
            # Percentile scoring needs a rolling history of daily readings, not
            # just today's — build/extend it here (once per ticker per day, same
            # cadence as the rest of Positioning) and attach the computed
            # percentiles to today's options data so they're available wherever
            # _positioning_full is read (scoring, trade_selector.py's structure
            # selection), without every caller re-deriving them from raw history.
            # Same pattern for all three metrics: atm_iv (feeds trade-structure
            # selection), put_call_ratio and iv_skew (feed positioning_layer's
            # options_score — previously scored against fixed absolute constants
            # with no per-ticker baseline; see positioning_layer._score_options).
            options = fresh.get("options") or {}
            if fresh.get("options") is not None:
                fresh["options"].update(_append_and_score_history(
                    iv_history, ticker, options.get("atm_iv"), compute_iv_percentile,
                    "iv_percentile_data_quality",
                ))
                fresh["options"].update(_append_and_score_history(
                    put_call_ratio_history, ticker, options.get("put_call_ratio"),
                    compute_put_call_ratio_percentile, "put_call_ratio_percentile_data_quality",
                ))
                fresh["options"].update(_append_and_score_history(
                    iv_skew_history, ticker, options.get("iv_skew"), compute_iv_skew_percentile,
                    "iv_skew_percentile_data_quality",
                ))
            state["tickers"][ticker] = fresh
            state["fetched_dates"][ticker] = today_str
            logger.info(f"  {ticker}: positioning data fetched OK")
        except Exception as exc:
            logger.error(f"  {ticker}: positioning fetch failed — {exc}")
            write_validation_entry(ticker, "positioning_fetch_error", str(exc))

    state["previous_updated"] = state.get("last_updated")
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    _save_positioning_state(state)
    return state


def _load_positioning_state() -> dict:
    """Load positioning_state.json, returning default structure if missing/corrupt."""
    default = {
        "last_updated": None,
        "update_cadence": "daily",
        "tickers": {},
        "previous_updated": None,
        "previous_tickers": {},
        "fetched_dates": {},
    }
    if not _POSITIONING_STATE_PATH.exists():
        return default
    try:
        with open(_POSITIONING_STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "tickers" not in data:
            data["tickers"] = {}
        if "previous_tickers" not in data:
            data["previous_tickers"] = {}
        if "fetched_dates" not in data:
            # Migrating from the old file-wide last_updated scheme: assume every
            # ticker already holding data was fetched on that date, so this
            # migration doesn't itself trigger a same-day re-fetch of tickers
            # whose data is already fresh.
            last_date = (data.get("last_updated") or "")[:10] or None
            data["fetched_dates"] = {
                t: last_date for t, v in data["tickers"].items() if v is not None
            }
        return data
    except Exception as exc:
        logger.warning(f"Could not load positioning_state.json — {exc}. Using defaults.")
        return default


def _save_positioning_state(state: dict) -> None:
    """Write positioning_state.json atomically."""
    try:
        _POSITIONING_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _POSITIONING_STATE_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)
        tmp.replace(_POSITIONING_STATE_PATH)
        logger.info("positioning_state.json updated.")
    except Exception as exc:
        logger.error(f"Could not save positioning_state.json — {exc}")


def _load_fundamental_state() -> dict:
    """Load fundamental_state.json, returning default structure if missing/corrupt."""
    default = {
        "last_updated": None,
        "update_cadence": "weekly",
        "update_day": "Monday",
        "tickers": {},
        "fetched_dates": {},
    }
    if not _FUNDAMENTAL_STATE_PATH.exists():
        return default
    try:
        with open(_FUNDAMENTAL_STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Ensure tickers key exists
        if "tickers" not in data:
            data["tickers"] = {}
        if "fetched_dates" not in data:
            # Migrating from the old file-wide last_updated scheme: assume every
            # ticker already holding data was fetched on that date, so this
            # migration doesn't itself trigger a same-day re-fetch.
            last_date = (data.get("last_updated") or "")[:10] or None
            data["fetched_dates"] = {
                t: last_date for t, v in data["tickers"].items() if v is not None
            }
        return data
    except Exception as exc:
        logger.warning(f"Could not load fundamental_state.json — {exc}. Using defaults.")
        return default


def _save_fundamental_state(state: dict) -> None:
    """Write fundamental_state.json atomically."""
    try:
        _FUNDAMENTAL_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _FUNDAMENTAL_STATE_PATH.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)
        tmp.replace(_FUNDAMENTAL_STATE_PATH)
        logger.info("fundamental_state.json updated.")
    except Exception as exc:
        logger.error(f"Could not save fundamental_state.json — {exc}")


def _archive_fundamental_snapshot(state: dict) -> None:
    """
    Append a dated copy of this week's fundamental snapshot to
    data/processed/fundamental_history/. fundamental_state.json only ever holds
    the latest snapshot, so a backtest replaying past dates has no choice but to
    score every historical bar against today's fundamentals (a lookahead-bias
    source — see backtesting/backtest_engine.py's point-in-time lookup). Building
    a dated archive going forward, one file per weekly refresh, lets future
    backtests look up the snapshot that was actually current as of each historical
    bar instead. Same "accumulates from the first live scan onward" tradeoff
    already accepted for the Positioning layer.
    """
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        _FUNDAMENTAL_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        path = _FUNDAMENTAL_HISTORY_DIR / f"{date_str}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"date": date_str, "tickers": state.get("tickers", {})}, f, indent=2, default=str)
        logger.info(f"Archived fundamental snapshot: {path}")
    except Exception as exc:
        logger.error(f"Could not archive fundamental snapshot — {exc}")


def _basic_validate(ticker: str, df: pd.DataFrame) -> bool:
    """
    Cheapest pre-flight checks (bar count, all-NaN) before passing data to
    the richer Phase 9 checks (shared.utils.data_validator.validate_ohlcv —
    gap detection, single-day move size, OHLC/Open range), which the caller
    (run_pipeline) runs immediately after this returns True.
    Returns False and logs if data is obviously corrupt.
    """
    if len(df) < 60:
        write_validation_entry(ticker, "insufficient_bars", f"Only {len(df)} bars (need 60+)")
        logger.warning(f"{ticker}: insufficient bars ({len(df)}) — excluded.")
        return False
    if df[["Open", "High", "Low", "Close"]].isna().all(axis=None):
        write_validation_entry(ticker, "all_nan", "OHLC columns are all NaN")
        logger.warning(f"{ticker}: all OHLC values are NaN — excluded.")
        return False
    if (df["High"] < df["Low"]).any():
        write_validation_entry(ticker, "high_below_low", "High < Low detected")
        logger.warning(f"{ticker}: data integrity issue (High < Low) — excluded.")
        return False
    return True


def build_indicator_table(pipeline_output: dict[str, Optional[dict]]) -> pd.DataFrame:
    """
    Convert pipeline output dict to DataFrame for inspection and logging.
    One row per ticker, all indicator fields as columns. Excludes None entries.
    """
    rows = [v for v in pipeline_output.values() if v is not None]
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index("ticker")


def load_config(config_path: str = "config/swing_config.yaml") -> dict:
    """Load and return swing_config.yaml contents."""
    path = Path(config_path)
    if not path.exists():
        logger.warning(f"Config not found at {config_path} — using defaults.")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}
