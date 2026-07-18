"""
Orchestrates all data pulls + indicator calculations for the semiconductor watchlist.
Produces a normalized output table per ticker — one row per ticker with all indicator
values needed by scoring.py. Runs 2-3x daily (pre-market, mid-session, post-close).

Fundamental data is fetched weekly (Monday 17:00 ET) and cached in
data/processed/fundamental_state.json. On non-update days the cached data is loaded
so fundamental scores are available every scan without API calls.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

from shared.api_clients.market_data_client import fetch_ohlcv_batch
from shared.indicators.technical_common import compute_technical_indicators
from shared.utils.logger import get_logger, write_validation_entry
from shared.api_clients.fundamental_client import FundamentalClient
from swing_model.fundamental_layer import FundamentalScorer
from shared.api_clients.positioning_client import fetch_all_positioning
from swing_model.positioning_layer import compute_positioning_score

logger = get_logger(__name__)

_ET = ZoneInfo("America/New_York")
_FUNDAMENTAL_STATE_PATH = Path("data/processed/fundamental_state.json")
_POSITIONING_STATE_PATH = Path("data/processed/positioning_state.json")


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

        # Basic OHLCV sanity check (full validation in Phase 9)
        if not _basic_validate(ticker, df):
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

    # 4-6. Fundamental data fetch + scoring
    try:
        fundamental_state = fetch_fundamental_data(tickers, cfg)
        scorer = FundamentalScorer(cfg)
        fundamental_scores = scorer.score_all_tickers(tickers, fundamental_state)
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
            results[ticker]["_fundamental_full"] = fs

    # 7-8. Market Positioning data fetch + scoring (daily cadence — free yfinance data only)
    try:
        current_prices = {
            t: results[t].get("close") for t in tickers if results.get(t) is not None
        }
        positioning_state = fetch_positioning_data(tickers, current_prices, cfg)
        previous_tickers = positioning_state.get("previous_tickers", {})
        positioning_scores = {
            t: compute_positioning_score(
                t, positioning_state.get("tickers", {}).get(t), previous_tickers.get(t), cfg
            )
            for t in tickers
        }
    except Exception as exc:
        logger.error(f"Positioning layer failed — {exc}. Proceeding with neutral scores.")
        write_validation_entry("ALL", "positioning_layer_error", str(exc))
        positioning_scores = {t: compute_positioning_score(t, None, None, cfg) for t in tickers}

    # Attach positioning scores to each ticker's indicator dict
    for ticker in tickers:
        if results.get(ticker) is not None:
            ps = positioning_scores.get(ticker) or compute_positioning_score(ticker, None, None, cfg)
            results[ticker]["positioning_score"] = ps.get("positioning_score_total", 0)
            results[ticker]["positioning_data_quality"] = ps.get("data_quality", "unavailable")
            results[ticker]["_positioning_full"] = ps

    valid_count = sum(1 for v in results.values() if v is not None)
    logger.info(f"Pipeline complete: {valid_count}/{len(tickers)} tickers processed successfully.")
    return results


def fetch_fundamental_data(tickers: list[str], cfg: Optional[dict] = None) -> dict:
    """
    Fetch or load fundamental data for all watchlist tickers.

    Cadence logic:
    - Load fundamental_state.json to check last_updated timestamp.
    - If last_updated is None OR (today is Monday AND current ET time >= 17:00
      AND last_updated is not today): fetch fresh data from FundamentalClient.
    - Otherwise: return cached data from fundamental_state.json.

    Writes fresh data to fundamental_state.json when fetched.
    Logs any fetch failures to validation_log.csv without crashing.

    Returns dict with structure: {"last_updated": ..., "tickers": {ticker: data}}
    """
    if cfg is None:
        cfg = {}

    state = _load_fundamental_state()
    last_updated_str = state.get("last_updated")
    now_et = datetime.now(_ET)
    today_str = now_et.strftime("%Y-%m-%d")

    # Determine if a fresh fetch is needed
    needs_fetch = False
    if last_updated_str is None:
        needs_fetch = True
        logger.info("Fundamental state has no last_updated — fetching fresh data.")
    else:
        # Parse the stored date
        try:
            last_date = last_updated_str[:10]  # YYYY-MM-DD
        except Exception:
            last_date = None

        if last_date != today_str:
            # Monday after 17:00 ET → scheduled weekly update
            if now_et.weekday() == 0 and now_et.hour >= 17:
                needs_fetch = True
                logger.info("Monday post-17:00 ET — fetching fresh fundamental data.")
        # On same day, no re-fetch needed (data is from earlier today)

    if not needs_fetch:
        logger.info(f"Loading cached fundamental data (last_updated: {last_updated_str})")
        return state

    logger.info(f"Fetching fundamental data for: {tickers}")
    client = FundamentalClient()
    # Save after every ticker, not just once at the end — a full 6-ticker
    # refresh can take several minutes (each sub-call retries on rate limits),
    # and a mid-batch interruption (manual Ctrl+C, crash, hitting the AV
    # budget cap) must not discard tickers that already completed. Deliberately
    # NOT updating last_updated until the whole loop finishes: a partial batch
    # must still read as "not yet refreshed today" so the next opportunity
    # retries it, rather than silently settling for a part-stale, part-fresh
    # snapshot mislabeled as complete.
    for ticker in tickers:
        try:
            state["tickers"][ticker] = client.get_all_fundamentals(ticker)
            logger.info(f"  {ticker}: fundamental data fetched OK")
        except Exception as exc:
            logger.error(f"  {ticker}: fundamental fetch failed — {exc}")
            write_validation_entry(ticker, "fundamental_fetch_error", str(exc))
            state["tickers"][ticker] = None
        _save_fundamental_state(state)

    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    _save_fundamental_state(state)
    return state


def fetch_positioning_data(tickers: list[str], current_prices: dict, cfg: Optional[dict] = None) -> dict:
    """
    Fetch or load Market Positioning data for all watchlist tickers (daily cadence).

    Cadence logic: fetch fresh data once per day; on same-day re-scans (pre-market,
    mid-session), reuse the day's already-fetched snapshot rather than re-hitting
    yfinance. When a new day's fetch happens, the prior day's snapshot is preserved
    under "previous_tickers" so positioning_layer.py can compute the institutional
    ownership delta — same forward-building-history caveat as Fundamental/Sentiment
    (no deep historical positioning archive exists; it accumulates from first live scan).

    Returns dict: {last_updated, tickers, previous_updated, previous_tickers}
    """
    if cfg is None:
        cfg = {}

    state = _load_positioning_state()
    last_updated_str = state.get("last_updated")
    now_et = datetime.now(_ET)
    today_str = now_et.strftime("%Y-%m-%d")

    needs_fetch = last_updated_str is None or last_updated_str[:10] != today_str
    if not needs_fetch:
        logger.info(f"Loading cached positioning data (last_updated: {last_updated_str})")
        return state

    logger.info(f"Fetching positioning data for: {tickers}")
    new_tickers = {}
    for ticker in tickers:
        try:
            new_tickers[ticker] = fetch_all_positioning(ticker, current_price=current_prices.get(ticker))
            logger.info(f"  {ticker}: positioning data fetched OK")
        except Exception as exc:
            logger.error(f"  {ticker}: positioning fetch failed — {exc}")
            write_validation_entry(ticker, "positioning_fetch_error", str(exc))
            new_tickers[ticker] = None

    new_state = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "tickers": new_tickers,
        "previous_updated": state.get("last_updated"),
        "previous_tickers": state.get("tickers", {}),
    }

    _save_positioning_state(new_state)
    return new_state


def _load_positioning_state() -> dict:
    """Load positioning_state.json, returning default structure if missing/corrupt."""
    default = {
        "last_updated": None,
        "update_cadence": "daily",
        "tickers": {t: None for t in ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"]},
        "previous_updated": None,
        "previous_tickers": {},
    }
    if not _POSITIONING_STATE_PATH.exists():
        return default
    try:
        with open(_POSITIONING_STATE_PATH, "r") as f:
            data = json.load(f)
        if "tickers" not in data:
            data["tickers"] = default["tickers"]
        if "previous_tickers" not in data:
            data["previous_tickers"] = {}
        return data
    except Exception as exc:
        logger.warning(f"Could not load positioning_state.json — {exc}. Using defaults.")
        return default


def _save_positioning_state(state: dict) -> None:
    """Write positioning_state.json atomically."""
    try:
        _POSITIONING_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _POSITIONING_STATE_PATH.with_suffix(".tmp")
        with open(tmp, "w") as f:
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
        "tickers": {t: None for t in ["NVDA", "AMD", "AVGO", "TSM", "MU", "ASML"]},
    }
    if not _FUNDAMENTAL_STATE_PATH.exists():
        return default
    try:
        with open(_FUNDAMENTAL_STATE_PATH, "r") as f:
            data = json.load(f)
        # Ensure tickers key exists
        if "tickers" not in data:
            data["tickers"] = default["tickers"]
        return data
    except Exception as exc:
        logger.warning(f"Could not load fundamental_state.json — {exc}. Using defaults.")
        return default


def _save_fundamental_state(state: dict) -> None:
    """Write fundamental_state.json atomically."""
    try:
        _FUNDAMENTAL_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _FUNDAMENTAL_STATE_PATH.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(state, f, indent=2, default=str)
        tmp.replace(_FUNDAMENTAL_STATE_PATH)
        logger.info("fundamental_state.json updated.")
    except Exception as exc:
        logger.error(f"Could not save fundamental_state.json — {exc}")


def _basic_validate(ticker: str, df: pd.DataFrame) -> bool:
    """
    Lightweight pre-flight check before passing data to indicator functions.
    Full validation (gap detection, move size, etc.) implemented in Phase 9 data_validator.py.
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
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}
