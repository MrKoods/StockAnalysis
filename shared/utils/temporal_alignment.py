"""
SHARED: Timestamp alignment, news decay weighting, leading/lagging classification,
price-sentiment divergence detection.
All timestamps must be UTC before entering this module.
"""

import math
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

_ET = ZoneInfo("America/New_York")


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
      Asian pre-market: 20:00-04:00 ET
      European:         04:00-09:30 ET
      US session:       09:30-16:00 ET
      After hours:      16:00-20:00 ET

    Classification converts to REAL Eastern time via zoneinfo (DST-aware)
    rather than a hardcoded UTC offset — the previous version assumed a
    fixed UTC-5 (EST) year-round, which is off by an hour for roughly 8
    months a year during EDT (UTC-4, in effect mid-March to early
    November): true 9:30am ET market open (13:30 UTC in EDT) used to
    classify as "european" instead of "us_session" for most of the year.
    """
    if timestamp_utc.tzinfo is None:
        timestamp_utc = timestamp_utc.replace(tzinfo=timezone.utc)

    et = timestamp_utc.astimezone(_ET)
    hm = et.hour * 60 + et.minute  # minutes since midnight ET

    if 570 <= hm < 960:      # 09:30-16:00 ET
        return "us_session"
    if 240 <= hm < 570:      # 04:00-09:30 ET
        return "european"
    if 960 <= hm < 1200:     # 16:00-20:00 ET
        return "us_after_hours"
    return "asian_pre_market"  # 20:00-24:00 ET or 00:00-04:00 ET (wraps midnight)


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


def _assign_trading_day(ts: datetime, price_index: pd.DatetimeIndex) -> Optional[pd.Timestamp]:
    """
    Map a signal's timestamp to the trading-day bar its reaction actually
    belongs to — same-calendar-day if published before/during market close
    (european/us_session windows), the NEXT trading day if published after
    close or overnight (us_after_hours/asian_pre_market), mirroring how a
    real trader can't act on after-hours news until the next session opens.
    Also forward-fills to the next available bar in price_index for a
    signal date that isn't itself a trading day (weekend/holiday) instead of
    matching nothing. Returns None only if price_index has no bar on or
    after the signal's assigned date at all (nothing to attribute it to yet).
    """
    window = classify_timezone_window(ts)
    sig_date = pd.Timestamp(ts.date())
    if window in ("us_after_hours", "asian_pre_market"):
        sig_date = sig_date + pd.Timedelta(days=1)

    candidates = price_index[price_index.normalize() >= sig_date.normalize()]
    if len(candidates) == 0:
        return None
    return candidates[0]


def align_signals_to_price_bars(
    signals: list[dict],
    price_index: pd.DatetimeIndex,
) -> pd.DataFrame:
    """
    Align timestamped signals (sentiment posts, news articles) to daily price bars.
    Each price bar gets aggregated signal fields for that trading day.
    Returns DataFrame indexed by price_index with aggregated signal fields.

    Expected fields per signal: timestamp_utc (str or datetime), sentiment (bullish/bearish/None)

    Uses _assign_trading_day (session-aware, via classify_timezone_window)
    rather than a same-UTC-calendar-date exact match — the previous version
    matched only an exact date_index.date() == signal.date() comparison,
    which (a) attributed after-hours news (a very common corporate-release
    window, including after-close earnings) to the day that already closed
    instead of the next session, and (b) silently dropped any signal dated
    on a non-trading day (weekend/holiday) instead of forward-filling it to
    the next open bar.
    """
    rows = {idx: {"bullish_count": 0, "bearish_count": 0, "neutral_count": 0, "total": 0} for idx in price_index}

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

        bar_ts = _assign_trading_day(ts, price_index)
        if bar_ts is None:
            continue  # no trading day on/after this signal exists yet

        sentiment = sig.get("sentiment")
        rows[bar_ts]["total"] += 1
        if sentiment == "bullish":
            rows[bar_ts]["bullish_count"] += 1
        elif sentiment == "bearish":
            rows[bar_ts]["bearish_count"] += 1
        else:
            rows[bar_ts]["neutral_count"] += 1

    df = pd.DataFrame.from_dict(rows, orient="index")
    df.index = pd.DatetimeIndex(df.index)
    df["bullish_ratio"] = df.apply(
        lambda r: r["bullish_count"] / r["total"] if r["total"] > 0 else 0.5, axis=1
    )
    return df
