"""
Orchestrates all data pulls + indicator calculations for the semiconductor watchlist.
Produces a normalized output table per ticker — one row per ticker with all indicator
values needed by scoring.py. Runs 2-3x daily (pre-market, mid-session, post-close).
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

from shared.api_clients.market_data_client import fetch_ohlcv_batch, fetch_vix
from shared.indicators.technical_common import compute_technical_indicators
from shared.utils.logger import get_logger, write_validation_entry

logger = get_logger(__name__)


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
    4. Return dict mapping ticker → indicator_dict (or None if excluded)

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

    valid_count = sum(1 for v in results.values() if v is not None)
    logger.info(f"Pipeline complete: {valid_count}/{len(tickers)} tickers processed successfully.")
    return results


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
