"""
Sentiment scoring layer — StockTwits crowd sentiment + Seeking Alpha engagement
proxy, replacing the earlier Reddit-based design.

StockTwits messages carry an explicit entities.sentiment.basic tag, so no
keyword/NLP inference or cross-subreddit consistency/spike-detection logic is
needed (unlike the old Reddit design, where sentiment had to be inferred from
free text and validated against manufactured-spike risk). Seeking Alpha's
contribution is an explicit engagement proxy (commentCount velocity), not true
community sentiment — this RapidAPI subscription has no ticker-searchable
community-blog feed, only editorial news with a comment count.

Output used by scoring.py for the Sentiment component (max 15 points):
  ratio_score       (0-7) — StockTwits bullish/bearish ratio, z-scored vs. own history
  velocity_score    (0-5) — StockTwits sentiment/volume velocity
  engagement_score  (0-3) — Seeking Alpha commentCount engagement velocity (proxy)
"""

import statistics
from datetime import datetime, timezone
from typing import Optional

from shared.utils.temporal_alignment import (
    compute_sentiment_trajectory,
    compute_sentiment_velocity,
    detect_price_sentiment_divergence,
)

# Sentiment offline cap: if both StockTwits and Seeking Alpha are unavailable, cap confidence at 70
SENTIMENT_OFFLINE_CAP = 70

RATIO_MAX = 7.0
VELOCITY_MAX = 5.0
ENGAGEMENT_MAX = 3.0
SENTIMENT_MAX = RATIO_MAX + VELOCITY_MAX + ENGAGEMENT_MAX  # 15


def compute_sentiment_score(
    stocktwits_messages: list[dict],
    seeking_alpha_items: list[dict],
    ticker: str,
    price_data: dict,
    cfg: Optional[dict] = None,
) -> dict:
    """
    Compute the full sentiment score bundle for a ticker.

    stocktwits_messages: output of sentiment_client.fetch_stocktwits(ticker)
    seeking_alpha_items:  output of sentiment_client.fetch_seeking_alpha_engagement(ticker)

    Scoring spec (sum = 15):
    - ratio_score:      0-7  (bullish/bearish ratio, z-scored vs. own trailing history)
    - velocity_score:   0-5  (sentiment/volume acceleration)
    - engagement_score: 0-3  (Seeking Alpha comment-count velocity — weak proxy)

    Returns dict with all fields required by scoring.py.
    """
    if cfg is None:
        cfg = {}
    stocktwits_messages = stocktwits_messages or []
    seeking_alpha_items = seeking_alpha_items or []

    stocktwits_offline = not stocktwits_messages
    sa_offline = not seeking_alpha_items
    sentiment_offline = stocktwits_offline and sa_offline

    daily_ratios, daily_totals = _build_daily_bullish_ratios(stocktwits_messages, days=5)
    trajectory = compute_sentiment_trajectory(daily_ratios) if not stocktwits_offline else 0.0

    ratio_score, ratio_dq = _score_ratio(stocktwits_messages, daily_ratios, daily_totals)
    velocity_score, velocity_dq = _score_velocity(stocktwits_messages, daily_ratios)
    engagement_score, engagement_dq = _score_engagement(seeking_alpha_items)

    sentiment_score_total = ratio_score + velocity_score + engagement_score
    sentiment_score_total = round(min(SENTIMENT_MAX, max(0.0, sentiment_score_total)), 2)

    bullish_count = sum(1 for m in stocktwits_messages if m.get("sentiment") == "bullish")
    bearish_count = sum(1 for m in stocktwits_messages if m.get("sentiment") == "bearish")
    total_tagged = bullish_count + bearish_count
    bullish_ratio_stocktwits = (bullish_count / total_tagged) if total_tagged > 0 else 0.5

    if bullish_ratio_stocktwits > 0.55:
        dominant_sentiment = "bullish"
    elif bullish_ratio_stocktwits < 0.45:
        dominant_sentiment = "bearish"
    else:
        dominant_sentiment = "neutral"

    price_change = float(price_data.get("price_change_5d_pct", 0.0))
    divergence_flag = detect_price_sentiment_divergence(price_change, trajectory)

    return {
        # Sub-scores
        "ratio_score": round(ratio_score, 2),
        "velocity_score": round(velocity_score, 2),
        "engagement_score": round(engagement_score, 2),
        "sentiment_score_total": sentiment_score_total,

        # Metadata
        "sentiment_trajectory": round(trajectory, 4),
        "sentiment_lead_lag": "neutral",  # Requires backtested baseline — populated in Phase 12
        "divergence_flag": divergence_flag,
        "dominant_sentiment": dominant_sentiment,
        "bullish_ratio_stocktwits": round(bullish_ratio_stocktwits, 3),
        "mention_volume_stocktwits": len(stocktwits_messages),
        "engagement_item_count": len(seeking_alpha_items),
        "sentiment_offline": sentiment_offline,
        "sentiment_offline_cap": SENTIMENT_OFFLINE_CAP if sentiment_offline else None,
        "sub_signal_data_quality": {
            "ratio": ratio_dq,
            "velocity": velocity_dq,
            "engagement": engagement_dq,
        },
    }


_RATIO_MIN_BASELINE_MESSAGES = 5  # across the trailing baseline days, not just today


def _score_ratio(
    messages: list[dict],
    daily_ratios: list[float],
    daily_totals: Optional[list[int]] = None,
) -> tuple[float, str]:
    """
    Score the current bullish/bearish ratio z-scored against the ticker's own
    trailing daily-bucket history. Neutral midpoint = 3.5 (of 0-7).
    Forfeits to 0 when no messages are available.

    Requires at least _RATIO_MIN_BASELINE_MESSAGES real messages across the
    baseline days before trusting the z-score. Without this gate, a single
    message on a low-volume ticker (with prior days at the 0.5 neutral
    placeholder — see _build_daily_bullish_ratios) computes pstdev([0.5]*4)==0,
    falls back to a tiny std_baseline=0.15, and can max the 0-7 score off n=1 —
    not a real "vs. own history" comparison.
    """
    if not messages:
        return 0.0, "unavailable"

    baseline = daily_ratios[:-1] if len(daily_ratios) > 1 else []
    current_ratio = daily_ratios[-1] if daily_ratios else 0.5
    baseline_sample_size = sum(daily_totals[:-1]) if daily_totals and len(daily_totals) > 1 else 0

    if len(baseline) >= 2 and baseline_sample_size >= _RATIO_MIN_BASELINE_MESSAGES:
        mean_baseline = statistics.mean(baseline)
        std_baseline = statistics.pstdev(baseline) or 0.15
        z = (current_ratio - mean_baseline) / std_baseline
        score = 3.5 + z * 1.75
        return max(0.0, min(RATIO_MAX, score)), "complete"

    # Not enough baseline history to z-score meaningfully — scale today's raw
    # ratio linearly onto [0, RATIO_MAX] instead of fabricating a z-score against
    # a mostly-placeholder baseline.
    score = current_ratio * RATIO_MAX
    return max(0.0, min(RATIO_MAX, score)), "insufficient_baseline"


def _score_velocity(messages: list[dict], daily_ratios: list[float]) -> tuple[float, str]:
    """
    Score sentiment/volume velocity. Prefers StockTwits' native per-message
    sentiment_change/volume_change fields (seeds the calc directly per the
    RapidAPI response); falls back to a trajectory-derived velocity when those
    fields aren't present. Neutral midpoint = 2.5 (of 0-5).
    Forfeits to 0 when no messages are available.
    """
    if not messages:
        return 0.0, "unavailable"

    sent_changes = [_as_float(m.get("sentiment_change")) for m in messages]
    sent_changes = [v for v in sent_changes if v is not None]
    vol_changes = [_as_float(m.get("volume_change")) for m in messages]
    vol_changes = [v for v in vol_changes if v is not None]

    if sent_changes or vol_changes:
        avg_sent = statistics.mean(sent_changes) if sent_changes else 0.0
        avg_vol = statistics.mean(vol_changes) if vol_changes else 0.0
        combined = (avg_sent + avg_vol) / 2.0
        score = 2.5 + combined * 10.0
        return max(0.0, min(VELOCITY_MAX, score)), "complete"

    # Fallback: derive velocity from the daily bullish-ratio trajectory
    velocity = compute_sentiment_velocity(daily_ratios)
    score = 2.5 + velocity * 25.0
    return max(0.0, min(VELOCITY_MAX, score)), "partial"


def _score_engagement(items: list[dict]) -> tuple[float, str]:
    """
    Score Seeking Alpha commentCount engagement velocity: compares the average
    comment count of the more-recent half of items to the older half.
    Neutral midpoint = 1.5 (of 0-3). Forfeits to 0 when no items are available.
    """
    if not items:
        return 0.0, "unavailable"
    if len(items) < 2:
        return ENGAGEMENT_MAX / 2.0, "partial"

    sorted_items = sorted(items, key=lambda i: i.get("timestamp_utc", ""))
    mid = len(sorted_items) // 2
    older = sorted_items[:mid]
    recent = sorted_items[mid:]

    older_avg = statistics.mean(i.get("comment_count", 0) or 0 for i in older)
    recent_avg = statistics.mean(i.get("comment_count", 0) or 0 for i in recent)

    if older_avg > 0:
        relative_change = (recent_avg - older_avg) / older_avg
    else:
        relative_change = 1.0 if recent_avg > 0 else 0.0

    score = 1.5 + relative_change * 3.0
    return max(0.0, min(ENGAGEMENT_MAX, score)), "complete"


def _as_float(val) -> Optional[float]:
    """Best-effort conversion of a StockTwits sentiment_change/volume_change field to float."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _build_daily_bullish_ratios(messages: list[dict], days: int = 5) -> tuple[list[float], list[int]]:
    """
    Aggregate StockTwits messages into daily bullish ratios over last `days` days.
    Returns (ratios, totals) — both oldest-to-newest, length = days. `totals` (real
    message count per bucket) lets callers tell a genuine trailing history apart
    from days with zero messages that were filled with the neutral 0.5 placeholder —
    a z-score computed against an all-placeholder baseline is meaningless, not a
    real "vs. own history" comparison.
    """
    now = datetime.now(timezone.utc)
    buckets: list[dict] = [{"bull": 0, "bear": 0, "total": 0} for _ in range(days)]

    for msg in messages:
        ts = _parse_ts(msg.get("timestamp_utc", ""))
        age_days = (now - ts).days
        if 0 <= age_days < days:
            bucket_idx = days - 1 - age_days
            sentiment = msg.get("sentiment")
            buckets[bucket_idx]["total"] += 1
            if sentiment == "bullish":
                buckets[bucket_idx]["bull"] += 1
            elif sentiment == "bearish":
                buckets[bucket_idx]["bear"] += 1

    ratios = []
    totals = []
    for b in buckets:
        if b["total"] > 0:
            ratios.append(b["bull"] / b["total"])
        else:
            ratios.append(0.5)  # neutral when no data
        totals.append(b["total"])
    return ratios, totals


def _parse_ts(ts_str: str) -> datetime:
    """Parse ISO timestamp string to UTC datetime."""
    if not ts_str:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(ts_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return datetime.now(timezone.utc)
