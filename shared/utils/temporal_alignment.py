"""
SHARED: Timestamp alignment, news decay weighting, leading/lagging classification,
price-sentiment divergence detection.
All timestamps must be UTC before entering this module.
"""

import math
from datetime import datetime, timezone, timedelta
from typing import Optional

import pandas as pd


def news_decay_weight(
    article_timestamp_utc: datetime,
    now_utc: Optional[datetime] = None,
    halflife_hours: float = 24.0,
    zero_at_days: float = 5.0,
) -> float:
    """
    Exponential decay weight for a news article based on age.
    weight = exp(-age_hours / halflife_hours), floored to 0 after zero_at_days.
    Returns value in [0, 1].
    """
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    if article_timestamp_utc.tzinfo is None:
        article_timestamp_utc = article_timestamp_utc.replace(tzinfo=timezone.utc)

    age_hours = (now_utc - article_timestamp_utc).total_seconds() / 3600.0
    if age_hours < 0:
        return 1.0  # Future-dated articles (clock skew) treated as fresh
    if age_hours >= zero_at_days * 24:
        return 0.0
    return math.exp(-age_hours / halflife_hours)


def classify_timezone_window(timestamp_utc: datetime) -> str:
    """
    Classify a UTC timestamp into one of the four trading session windows.
    Returns: 'asian_pre_market' | 'european' | 'us_session' | 'us_after_hours'

    Windows in Eastern Time:
      Asian pre-market: 20:00-04:00 ET (01:00-09:00 UTC next day)
      European:         04:00-09:30 ET (09:00-14:30 UTC)
      US session:       09:30-16:00 ET (14:30-21:00 UTC)
      After hours:      16:00-20:00 ET (21:00-01:00 UTC)
    """
    if timestamp_utc.tzinfo is None:
        timestamp_utc = timestamp_utc.replace(tzinfo=timezone.utc)

    # Use UTC hour for classification (approximate — ignores DST)
    h = timestamp_utc.hour
    m = timestamp_utc.minute
    hm = h * 60 + m  # minutes since midnight UTC

    if 870 <= hm < 1260:    # 14:30-21:00 UTC
        return "us_session"
    if 540 <= hm < 870:     # 09:00-14:30 UTC
        return "european"
    if 1260 <= hm or hm < 60:  # 21:00+ or 00:00-01:00 UTC
        return "us_after_hours"
    return "asian_pre_market"   # 01:00-09:00 UTC


def classify_lead_lag(
    signal_timestamp_utc: datetime,
    price_move_timestamp_utc: datetime,
) -> str:
    """
    Classify whether a signal appeared before or after a significant price move.
    Returns 'leading' (signal before move) or 'lagging' (signal after move).
    """
    if signal_timestamp_utc.tzinfo is None:
        signal_timestamp_utc = signal_timestamp_utc.replace(tzinfo=timezone.utc)
    if price_move_timestamp_utc.tzinfo is None:
        price_move_timestamp_utc = price_move_timestamp_utc.replace(tzinfo=timezone.utc)

    if signal_timestamp_utc < price_move_timestamp_utc:
        return "leading"
    return "lagging"


def detect_price_sentiment_divergence(
    price_change_pct: float,
    sentiment_trajectory: float,
    window_days: int = 5,
) -> str:
    """
    Detect divergence between price direction and sentiment direction.

    Returns:
    - 'bullish_setup': sentiment building (+), price flat/down → potential setup
    - 'bearish_warning': price up strong (+), sentiment flat/declining → warning
    - 'aligned': both moving in same direction
    - 'neutral': insufficient signal in either direction
    """
    STRONG = 0.03   # 3% price move threshold
    SIG = 0.05      # significant sentiment slope threshold

    if sentiment_trajectory > SIG and price_change_pct < STRONG:
        return "bullish_setup"
    if price_change_pct > STRONG and sentiment_trajectory < -SIG:
        return "bearish_warning"
    if (sentiment_trajectory > SIG and price_change_pct > 0) or \
       (sentiment_trajectory < -SIG and price_change_pct < 0):
        return "aligned"
    return "neutral"


def compute_sentiment_trajectory(
    bullish_ratios: list[float],
    window_days: int = 5,
) -> float:
    """
    First derivative of sentiment: rolling slope of bullish ratio over window_days.
    Positive = building bullish sentiment; negative = declining.
    Returns slope (not bounded to 0-1).
    Uses linear regression over provided window.
    """
    if len(bullish_ratios) < 2:
        return 0.0
    n = min(window_days, len(bullish_ratios))
    vals = bullish_ratios[-n:]
    x = list(range(n))
    x_mean = sum(x) / n
    y_mean = sum(vals) / n
    num = sum((x[i] - x_mean) * (vals[i] - y_mean) for i in range(n))
    den = sum((x[i] - x_mean) ** 2 for i in range(n))
    if den == 0:
        return 0.0
    return num / den


def compute_sentiment_velocity(
    bullish_ratios: list[float],
    window_days: int = 5,
) -> float:
    """
    Second derivative of sentiment: rate of change of the trajectory.
    Computes trajectory for the first half and second half of the window, returns delta.
    Positive velocity = acceleration of bullish sentiment building.
    """
    n = min(window_days, len(bullish_ratios))
    if n < 4:
        return 0.0
    half = n // 2
    first_half = bullish_ratios[-n:-half] if n - half > 1 else bullish_ratios[-n:]
    second_half = bullish_ratios[-half:] if half > 1 else bullish_ratios[-n:]
    t1 = compute_sentiment_trajectory(first_half)
    t2 = compute_sentiment_trajectory(second_half)
    return t2 - t1


def align_signals_to_price_bars(
    signals: list[dict],
    price_index: pd.DatetimeIndex,
) -> pd.DataFrame:
    """
    Align timestamped signals (sentiment posts, news articles) to daily price bars.
    Each price bar gets aggregated signal fields for that trading day.
    Returns DataFrame indexed by price_index with aggregated signal fields.

    Expected fields per signal: timestamp_utc (str or datetime), sentiment (bullish/bearish/None)
    """
    rows = {}
    for idx in price_index:
        rows[idx] = {"bullish_count": 0, "bearish_count": 0, "neutral_count": 0, "total": 0}

    for sig in signals:
        ts = sig.get("timestamp_utc")
        if ts is None:
            continue
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts)
            except ValueError:
                continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        # Snap to the nearest price bar date
        sig_date = ts.date()
        for bar_ts in price_index:
            if bar_ts.date() == sig_date:
                sentiment = sig.get("sentiment")
                rows[bar_ts]["total"] += 1
                if sentiment == "bullish":
                    rows[bar_ts]["bullish_count"] += 1
                elif sentiment == "bearish":
                    rows[bar_ts]["bearish_count"] += 1
                else:
                    rows[bar_ts]["neutral_count"] += 1
                break

    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index = pd.DatetimeIndex(df.index)
    df["bullish_ratio"] = df.apply(
        lambda r: r["bullish_count"] / r["total"] if r["total"] > 0 else 0.5, axis=1
    )
    return df
