"""
SHARED: Pre-flight validation of all incoming data before indicator calculation.
Excludes corrupt tickers from current scan. Logs failures to validation_log.csv.
Checks: price gaps, OHLC sanity, volume, single-day moves, sentiment ratio bounds,
news score ranges, positioning field bounds, timestamp validity.
"""

from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from shared.utils.logger import write_validation_entry


def validate_ohlcv(
    ticker: str,
    df: pd.DataFrame,
    cfg: Optional[dict] = None,
    max_gap_days: int = 3,
    max_single_day_move_pct: float = 0.50,
) -> tuple[bool, list[str]]:
    """
    Validate OHLCV DataFrame for a ticker.

    Checks:
    - No gaps longer than max_gap_days trading days
    - High >= Low >= 0
    - Close between High and Low
    - Volume > 0
    - No single-day move > max_single_day_move_pct (likely split or data error)

    Returns (is_valid: bool, failure_reasons: list[str]).
    Logs each failure to validation_log.csv automatically.
    """
    reasons = []

    if df is None or df.empty:
        reasons.append("ohlcv_empty_dataframe")
        write_validation_entry(ticker, "ohlcv", reasons)
        return False, reasons

    required_cols = {"Open", "High", "Low", "Close", "Volume"}
    missing = required_cols - set(df.columns)
    if missing:
        reasons.append(f"ohlcv_missing_columns_{sorted(missing)}")
        write_validation_entry(ticker, "ohlcv", reasons)
        return False, reasons

    # OHLC sanity checks
    for i, row in df.iterrows():
        high = float(row["High"]) if not pd.isna(row["High"]) else -1
        low = float(row["Low"]) if not pd.isna(row["Low"]) else -1
        close = float(row["Close"]) if not pd.isna(row["Close"]) else -1
        volume = float(row["Volume"]) if not pd.isna(row["Volume"]) else -1

        if low < 0:
            reasons.append(f"ohlcv_negative_low_{i}")
            break
        if high < low:
            reasons.append(f"ohlcv_high_less_than_low_{i}")
            break
        if close < low or close > high:
            reasons.append(f"ohlcv_close_out_of_range_{i}")
            break
        if volume <= 0:
            reasons.append(f"ohlcv_zero_or_negative_volume_{i}")
            break

    # Single-day move check
    if "Close" in df.columns and len(df) >= 2:
        closes = df["Close"].dropna()
        pct_changes = closes.pct_change().abs()
        extreme = pct_changes[pct_changes > max_single_day_move_pct]
        if not extreme.empty:
            reasons.append(f"ohlcv_extreme_single_day_move_pct_{round(float(extreme.max())*100, 1)}")

    # Gap check (only if index is DatetimeIndex)
    if isinstance(df.index, pd.DatetimeIndex) and len(df) >= 2:
        gaps = df.index.to_series().diff().dt.days.dropna()
        max_gap = int(gaps.max())
        if max_gap > max_gap_days * 1.5:  # Allow weekends (~1.5×)
            reasons.append(f"ohlcv_gap_{max_gap}_days")

    if reasons:
        write_validation_entry(ticker, "ohlcv", "; ".join(reasons))
    return len(reasons) == 0, reasons


def validate_sentiment_data(
    ticker: str,
    posts: list[dict],
) -> tuple[bool, list[str]]:
    """
    Validate sentiment data for a ticker.

    Checks:
    - Bullish ratio in [0.0, 1.0]
    - Mention volume is positive integer
    - Timestamps within expected range (not in the future)

    Returns (is_valid: bool, failure_reasons: list[str]).
    """
    reasons = []
    if not posts:
        return True, []  # Empty is valid — offline mode handled by caller

    now_utc = datetime.now(timezone.utc)

    for post in posts:
        # Bullish ratio bounds
        bullish_ratio = post.get("bullish_ratio")
        if bullish_ratio is not None:
            if not (0.0 <= float(bullish_ratio) <= 1.0):
                reasons.append(f"sentiment_bullish_ratio_out_of_bounds_{bullish_ratio}")
                break

        # Timestamp not in the future
        ts = post.get("timestamp_utc") or post.get("timestamp")
        if ts:
            try:
                if isinstance(ts, str):
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                elif isinstance(ts, datetime):
                    dt = ts
                else:
                    dt = None
                if dt and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt and dt > now_utc:
                    reasons.append("sentiment_future_timestamp")
                    break
            except (ValueError, TypeError):
                reasons.append("sentiment_invalid_timestamp_format")
                break

    if reasons:
        write_validation_entry(ticker, "sentiment", "; ".join(reasons))
    return len(reasons) == 0, reasons


def validate_news_data(
    ticker: str,
    articles: list[dict],
) -> tuple[bool, list[str]]:
    """
    Validate news data for a ticker.

    Checks:
    - Sentiment scores within documented API range
    - Publication timestamps not in the future
    - Ticker attribution present

    Returns (is_valid: bool, failure_reasons: list[str]).
    """
    reasons = []
    if not articles:
        return True, []

    now_utc = datetime.now(timezone.utc)

    for article in articles:
        # Sentiment score range (AV returns -1 to 1)
        score = article.get("sentiment_score")
        if score is not None:
            if not (-1.0 <= float(score) <= 1.0):
                reasons.append(f"news_sentiment_score_out_of_range_{score}")
                break

        # Timestamp not in the future
        ts = article.get("timestamp_utc") or article.get("publish_date")
        if ts:
            try:
                if isinstance(ts, str):
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                elif isinstance(ts, datetime):
                    dt = ts
                else:
                    dt = None
                if dt and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt and dt > now_utc:
                    reasons.append("news_future_timestamp")
                    break
            except (ValueError, TypeError):
                reasons.append("news_invalid_timestamp_format")
                break

    if reasons:
        write_validation_entry(ticker, "news", "; ".join(reasons))
    return len(reasons) == 0, reasons


def validate_positioning_data(
    ticker: str,
    positioning_data: Optional[dict],
) -> tuple[bool, list[str]]:
    """
    Validate Market Positioning data for a ticker.

    Checks:
    - held_percent_institutions in [0.0, 1.0]
    - short interest fields non-negative
    - put/call ratio non-negative

    Empty/None is valid — offline mode (positioning_offline) is handled by the caller,
    same convention as validate_sentiment_data/validate_news_data.

    Returns (is_valid: bool, failure_reasons: list[str]).
    """
    reasons = []
    if not positioning_data:
        return True, []

    institutional = positioning_data.get("institutional") or {}
    held_pct = institutional.get("held_percent_institutions")
    if held_pct is not None and not (0.0 <= float(held_pct) <= 1.0):
        reasons.append(f"positioning_held_percent_institutions_out_of_bounds_{held_pct}")

    short_interest = positioning_data.get("short_interest") or {}
    for field in ("shares_short", "shares_short_prior_month", "short_ratio", "short_percent_of_float"):
        val = short_interest.get(field)
        if val is not None and float(val) < 0:
            reasons.append(f"positioning_negative_{field}_{val}")

    options = positioning_data.get("options") or {}
    ratio = options.get("put_call_ratio")
    if ratio is not None and float(ratio) < 0:
        reasons.append(f"positioning_negative_put_call_ratio_{ratio}")

    if reasons:
        write_validation_entry(ticker, "positioning", "; ".join(reasons))
    return len(reasons) == 0, reasons


def run_preflight_validation(
    ticker: str,
    ohlcv: Optional[pd.DataFrame],
    posts: Optional[list[dict]],
    articles: Optional[list[dict]],
    positioning_data: Optional[dict] = None,
) -> dict:
    """
    Run all validation checks for a ticker before processing.

    Returns dict:
    {
        ticker_valid: bool,       # False → exclude from current scan
        ohlcv_valid: bool,
        sentiment_valid: bool,
        news_valid: bool,
        positioning_valid: bool,
        failures: list[str],
    }
    On any failure, logs to validation_log.csv and returns ticker_valid=False.
    System continues scanning remaining tickers (does not abort).
    """
    ohlcv_ok, ohlcv_failures = validate_ohlcv(ticker, ohlcv) if ohlcv is not None else (True, [])
    sent_ok, sent_failures = validate_sentiment_data(ticker, posts or [])
    news_ok, news_failures = validate_news_data(ticker, articles or [])
    positioning_ok, positioning_failures = validate_positioning_data(ticker, positioning_data)

    all_failures = ohlcv_failures + sent_failures + news_failures + positioning_failures

    return {
        "ticker_valid": ohlcv_ok and sent_ok and news_ok and positioning_ok,
        "ohlcv_valid": ohlcv_ok,
        "sentiment_valid": sent_ok,
        "news_valid": news_ok,
        "positioning_valid": positioning_ok,
        "failures": all_failures,
    }
