"""
SHARED: Pre-flight validation of all incoming data before indicator calculation.
Excludes corrupt tickers from current scan. Logs failures to validation_log.csv.
Checks: price gaps, OHLC sanity, volume, single-day moves, sentiment ratio bounds,
news score ranges, positioning field bounds, timestamp validity.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd

from shared.utils.logger import write_validation_entry


def validate_ohlcv(
    ticker: str,
    df: pd.DataFrame,
    cfg: Optional[dict] = None,
    max_gap_days: int = 3,
    max_single_day_move_pct: float = 0.50,
    open_range_tolerance_pct: float = 0.003,
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

    cfg: when supplied, config/swing_config.yaml's data_validation.max_price_gap_days/
    max_single_day_move_pct/open_range_tolerance_pct override the defaults above —
    previously max_price_gap_days/max_single_day_move_pct were accepted but never read
    (the one production call site passed no cfg at all), so those two config keys had
    zero effect regardless of what a user set them to (Signal Integrity Audit follow-up
    finding).
    """
    reasons = []

    if cfg:
        dv_cfg = cfg.get("data_validation", {})
        max_gap_days = int(dv_cfg.get("max_price_gap_days", max_gap_days))
        max_single_day_move_pct = float(dv_cfg.get("max_single_day_move_pct", max_single_day_move_pct))
        open_range_tolerance_pct = float(dv_cfg.get("open_range_tolerance_pct", open_range_tolerance_pct))

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
        open_px = float(row["Open"]) if not pd.isna(row["Open"]) else -1
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
        # Open was previously never checked — only High/Low/Close/Volume were —
        # so a corrupted Open (decimal-shift error, stale print) passed pre-flight
        # validation undetected even though entry-zone/stop-loss math elsewhere
        # can key off the day's Open.
        #
        # A small tolerance band, not an exact boundary — a real decimal-shift
        # error (e.g. $304.70 mis-printed as $30.47) blows past any reasonable
        # tolerance instantly, but vendor rounding/consolidation noise on the
        # order of a few cents (observed live: RF 2026-08-24 printed Open
        # $30.47 vs. Low $30.50, a 0.1% gap, in yfinance's own finalized EOD
        # data — not a transient fetch-timing artifact) was tripping this
        # exact-boundary check and excluding the ticker from the whole scan
        # over noise, not corruption.
        open_tolerance = max(high, low, abs(open_px)) * open_range_tolerance_pct
        if open_px < low - open_tolerance or open_px > high + open_tolerance:
            reasons.append(f"ohlcv_open_out_of_range_{i}")
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


def _future_timestamp_reason(ts, now_utc: datetime, prefix: str) -> Optional[str]:
    """
    Parse a post/article timestamp (str or datetime) and return a failure
    reason string if it's malformed or newer than now_utc; None if valid or
    absent. Shared by validate_sentiment_data/validate_news_data — both
    need "reject any item whose timestamp is malformed or in the future,"
    differing only in their failure-reason prefix.
    """
    if not ts:
        return None
    try:
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        elif isinstance(ts, datetime):
            dt = ts
        else:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt > now_utc:
            return f"{prefix}_future_timestamp"
    except (ValueError, TypeError):
        return f"{prefix}_invalid_timestamp_format"
    return None


_VALID_SENTIMENT_VALUES = {"bullish", "bearish", None}


def validate_sentiment_data(
    ticker: str,
    posts: list[dict],
) -> tuple[bool, list[str]]:
    """
    Validate sentiment data for a ticker.

    Checks:
    - `sentiment` is one of the values StockTwits' entities.sentiment.basic
      tag actually produces ("bullish"/"bearish"/None — see
      sentiment_client.fetch_stocktwits' docstring)
    - Timestamps within expected range (not in the future)

    Returns (is_valid: bool, failure_reasons: list[str]).

    Was previously checking a `bullish_ratio` field that never exists on a
    real per-message dict — that's an AGGREGATE sentiment_layer.py computes
    from a batch of these messages, not a raw field any client ever
    populates, so this check could never actually fire (Signal Integrity
    Audit finding E.1 follow-up: fixed while wiring this module in for
    real — a validator whose checks are silently inert against real data
    shapes is worse than not having it, since it looks like coverage that
    isn't there).
    """
    reasons = []
    if not posts:
        return True, []  # Empty is valid — offline mode handled by caller

    now_utc = datetime.now(timezone.utc)

    for post in posts:
        sentiment = post.get("sentiment")
        if sentiment not in _VALID_SENTIMENT_VALUES:
            reasons.append(f"sentiment_unexpected_value_{sentiment}")
            break

        # Timestamp not in the future
        ts = post.get("timestamp_utc") or post.get("timestamp")
        reason = _future_timestamp_reason(ts, now_utc, "sentiment")
        if reason:
            reasons.append(reason)
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
        # Sentiment score range (AV returns -1 to 1). Real AV articles carry
        # this under "overall_sentiment_score" (see news_client.py) — this
        # used to check a plain "sentiment_score" key that's never actually
        # populated, so the check could never fire (same field-name-drift
        # bug fixed in validate_sentiment_data above).
        score = article.get("overall_sentiment_score", article.get("sentiment_score"))
        if score is not None:
            if not (-1.0 <= float(score) <= 1.0):
                reasons.append(f"news_sentiment_score_out_of_range_{score}")
                break

        # Timestamp not in the future
        ts = article.get("timestamp_utc") or article.get("publish_date")
        reason = _future_timestamp_reason(ts, now_utc, "news")
        if reason:
            reasons.append(reason)
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


def validate_event_gate_state(state: dict, max_age_trading_days: int = 5) -> dict:
    """
    Validate data/processed/event_gate_state.json content on read.

    - Malformed content (not a dict, missing/non-list 'blocks') is repaired to
      an empty state with a warning — never crashes a scan.
    - Individual malformed block entries (missing required keys, bad
      timestamps) are dropped with a warning rather than failing the whole file.
    - Blocks older than max_age_trading_days (approximated as calendar days,
      same ~1.4x convention used elsewhere for a 5-trading-day window) are
      auto-expired with a warning even if a post-close scan never explicitly
      expired them — a safety net against a stuck block outliving its purpose.

    Returns a repaired {"blocks": [...]} dict. Never raises.
    """
    required_block_keys = {"tickers", "scope", "trigger_match", "event_timestamp_utc", "expired"}

    if not isinstance(state, dict) or not isinstance(state.get("blocks"), list):
        write_validation_entry("_system", "event_gate_state", "malformed_state_repaired_to_empty")
        return {"blocks": []}

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_trading_days * 1.4)
    clean_blocks = []
    for block in state["blocks"]:
        if not isinstance(block, dict) or not required_block_keys.issubset(block.keys()):
            write_validation_entry("_system", "event_gate_state", f"malformed_block_dropped_{block}")
            continue

        ts = block.get("event_timestamp_utc")
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            write_validation_entry("_system", "event_gate_state", f"malformed_timestamp_dropped_{ts}")
            continue

        if not block.get("expired") and dt < cutoff:
            write_validation_entry(
                "_system", "event_gate_state",
                f"stale_block_auto_expired_{block.get('trigger_match')}_{ts}",
            )
            block["expired"] = True
            block["expired_at_utc"] = datetime.now(timezone.utc).isoformat()
            block.setdefault("expiry_condition", "auto_expired_stale")

        clean_blocks.append(block)

    # critical_alerts_sent: {alert_key: sent_at_utc} dedup ledger for
    # open-position critical alerts (see event_gate.was_critical_alert_sent).
    # Carried through here rather than dropped — this function rebuilds the
    # state dict from scratch, so any key it doesn't explicitly preserve is
    # silently discarded on every load, which would reset the dedup ledger
    # every scan and restore the duplicate-alert behaviour it exists to stop.
    # Pruned on the same cutoff as blocks: an entry older than the window
    # can't suppress anything still relevant, and dropping it keeps the map
    # bounded.
    clean_alerts: dict = {}
    raw_alerts = state.get("critical_alerts_sent")
    if isinstance(raw_alerts, dict):
        for key, sent_at in raw_alerts.items():
            try:
                sent_dt = datetime.fromisoformat(str(sent_at))
                if sent_dt.tzinfo is None:
                    sent_dt = sent_dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
            if sent_dt >= cutoff:
                clean_alerts[key] = sent_at

    return {"blocks": clean_blocks, "critical_alerts_sent": clean_alerts}


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
