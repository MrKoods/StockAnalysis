"""
Sentiment trajectory + velocity; leading/lagging classification; divergence
flagging; cross-subreddit consistency; spike detection.
Reddit (PRAW) is the sole sentiment source — timezone-aware windowing.
Output used by scoring.py for the Sentiment component (max 25 points).
"""

from datetime import datetime, timezone
from typing import Optional

from shared.utils.temporal_alignment import (
    compute_sentiment_trajectory,
    compute_sentiment_velocity,
    detect_price_sentiment_divergence,
)

# Sentiment offline cap: if Reddit is unavailable, cap confidence at 70
SENTIMENT_OFFLINE_CAP = 70

# "Hype" subreddit vs. the rest — used for cross-subreddit consistency below
_HYPE_SUBREDDITS = {"wallstreetbets"}


def compute_sentiment_score(
    reddit_posts: list[dict],
    ticker: str,
    price_data: dict,
    cfg: Optional[dict] = None,
) -> dict:
    """
    Compute the full sentiment score bundle for a ticker.

    Scoring spec (sum = 25):
    - trajectory_score:        0-10  (building vs. declining)
    - velocity_score:          0-5   (acceleration)
    - cross_platform_score:    0-5   (WSB vs. other subreddits agreement)
    - spike_score:             0-5   (organic vs. manufactured)

    Returns dict with all fields required by scoring.py.
    """
    if cfg is None:
        cfg = {}

    sentiment_offline = not reddit_posts

    # ---------------------------------------------------------------------------
    # 1. Reddit — simple keyword sentiment (no credibility weights — author data limited)
    # ---------------------------------------------------------------------------
    reddit_bull = sum(1 for p in reddit_posts if p.get("sentiment") == "bullish")
    reddit_bear = sum(1 for p in reddit_posts if p.get("sentiment") == "bearish")
    reddit_total = len(reddit_posts)
    bullish_ratio_reddit = (reddit_bull / reddit_total) if reddit_total > 0 else 0.5

    # Split by subreddit: WSB (hype/degen) vs. the rest (measured communities)
    wsb_posts = [p for p in reddit_posts if p.get("subreddit") in _HYPE_SUBREDDITS]
    other_posts = [p for p in reddit_posts if p.get("subreddit") not in _HYPE_SUBREDDITS]
    bullish_ratio_wsb = _bullish_ratio(wsb_posts)
    bullish_ratio_other_subs = _bullish_ratio(other_posts)

    post_timestamps = [_parse_ts(p.get("timestamp_utc", "")).timestamp() for p in reddit_posts]
    author_ids = [str(p.get("author_name", "")) for p in reddit_posts]

    # ---------------------------------------------------------------------------
    # 2. Trajectory (0-10): slope of bullish ratio from daily aggregation
    #    Approximate with a 5-point series decayed over time buckets
    # ---------------------------------------------------------------------------
    daily_ratios = _build_daily_bullish_ratios(reddit_posts, days=5)
    trajectory = compute_sentiment_trajectory(daily_ratios)
    velocity = compute_sentiment_velocity(daily_ratios)

    # Scale trajectory to 0-10: trajectory of 0 → 5 (neutral); max +0.1/day → 10
    trajectory_score = min(10.0, max(0.0, 5.0 + trajectory * 50.0))

    # ---------------------------------------------------------------------------
    # 3. Velocity (0-5)
    # ---------------------------------------------------------------------------
    velocity_score = min(5.0, max(0.0, 2.5 + velocity * 25.0))

    # ---------------------------------------------------------------------------
    # 4. Cross-subreddit consistency (0-5): does WSB hype agree with the more
    #    measured subreddits, or is it isolated to one echo chamber?
    # ---------------------------------------------------------------------------
    cross_consistency = compute_cross_platform_consistency(bullish_ratio_wsb, bullish_ratio_other_subs)
    cross_platform_score = round(cross_consistency * 5.0, 2)

    # ---------------------------------------------------------------------------
    # 5. Spike classification (0-5): organic buildup > manufactured spike
    # ---------------------------------------------------------------------------
    spike_type = detect_spike_type(daily_ratios, post_timestamps, author_ids)
    if spike_type == "organic":
        spike_score = 5.0
    elif spike_type == "manufactured":
        spike_score = 1.0
    else:
        spike_score = 3.0

    # ---------------------------------------------------------------------------
    # 6. Aggregate
    # ---------------------------------------------------------------------------
    sentiment_score_total = trajectory_score + velocity_score + cross_platform_score + spike_score

    # Divergence detection
    price_change = float(price_data.get("price_change_5d_pct", 0.0))
    divergence_flag = detect_price_sentiment_divergence(price_change, trajectory)

    # Dominant sentiment
    if bullish_ratio_reddit > 0.55:
        dominant_sentiment = "bullish"
    elif bullish_ratio_reddit < 0.45:
        dominant_sentiment = "bearish"
    else:
        dominant_sentiment = "neutral"

    return {
        # Sub-scores
        "trajectory_score": round(trajectory_score, 2),
        "velocity_score": round(velocity_score, 2),
        "cross_platform_score": round(cross_platform_score, 2),
        "spike_score": round(spike_score, 2),
        "sentiment_score_total": round(min(25.0, sentiment_score_total), 2),

        # Metadata
        "sentiment_trajectory": round(trajectory, 4),
        "sentiment_velocity": round(velocity, 4),
        "sentiment_lead_lag": "neutral",  # Requires backtested baseline — populated in Phase 12
        "divergence_flag": divergence_flag,
        "cross_platform_consistency_score": round(cross_consistency, 3),
        "spike_type": spike_type,
        "dominant_sentiment": dominant_sentiment,
        "bullish_ratio_wsb": round(bullish_ratio_wsb, 3),
        "bullish_ratio_other_subs": round(bullish_ratio_other_subs, 3),
        "bullish_ratio_reddit": round(bullish_ratio_reddit, 3),
        "mention_volume_reddit": len(reddit_posts),
        "sentiment_offline": sentiment_offline,
        "sentiment_offline_cap": SENTIMENT_OFFLINE_CAP if sentiment_offline else None,
        "timezone_window_signals": {},  # Populated per-window if needed by scoring.py
    }


def _bullish_ratio(posts: list[dict]) -> float:
    """Fraction of posts labeled bullish. Neutral (0.5) if empty."""
    total = len(posts)
    if total == 0:
        return 0.5
    bull = sum(1 for p in posts if p.get("sentiment") == "bullish")
    return bull / total


def detect_spike_type(
    bullish_ratios: list[float],
    post_timestamps: list[float],
    author_ids: list[str],
) -> str:
    """
    Classify spike as 'organic', 'manufactured', or 'none'.
    Organic: gradual build over days from diverse accounts.
    Manufactured: sudden spike in final time bucket from small author set.
    """
    if not bullish_ratios:
        return "none"

    # Check for sudden spike in most recent bucket
    if len(bullish_ratios) >= 3:
        recent_jump = bullish_ratios[-1] - bullish_ratios[-3]
        if recent_jump > 0.25:  # Sudden jump > 25% in 2 days
            # Check account diversity
            unique_authors = len(set(author_ids))
            total_posts = len(author_ids)
            if total_posts > 0 and unique_authors / total_posts < 0.30:
                return "manufactured"

    # Gradual positive trend = organic
    trajectory = compute_sentiment_trajectory(bullish_ratios)
    if trajectory > 0.01 and len(bullish_ratios) >= 3:
        return "organic"

    return "none"


def compute_cross_platform_consistency(
    bullish_ratio_st: float,
    bullish_ratio_reddit: float,
    threshold: float = 0.20,
) -> float:
    """
    Cross-platform consistency score (0.0-1.0).
    Both bullish (both > 0.55) → 1.0.
    Both bearish (both < 0.45) → 1.0.
    Diverging by > threshold → reduced score.
    """
    diff = abs(bullish_ratio_st - bullish_ratio_reddit)
    direction_match = (
        (bullish_ratio_st > 0.55 and bullish_ratio_reddit > 0.55) or
        (bullish_ratio_st < 0.45 and bullish_ratio_reddit < 0.45)
    )

    if direction_match and diff < threshold:
        return 1.0
    if diff > threshold * 2:
        return max(0.0, 1.0 - diff * 2)
    return max(0.0, 1.0 - diff / threshold * 0.5)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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


def _build_daily_bullish_ratios(posts: list[dict], days: int = 5) -> list[float]:
    """
    Aggregate posts into daily bullish ratios over last `days` days.
    Returns list of ratios (oldest to newest), length = days.
    """
    from datetime import timedelta

    now = datetime.now(timezone.utc)
    buckets: list[dict] = [{"bull": 0, "bear": 0, "total": 0} for _ in range(days)]

    for post in posts:
        ts = _parse_ts(post.get("timestamp_utc", ""))
        age_days = (now - ts).days
        if 0 <= age_days < days:
            bucket_idx = days - 1 - age_days
            sentiment = post.get("sentiment")
            buckets[bucket_idx]["total"] += 1
            if sentiment == "bullish":
                buckets[bucket_idx]["bull"] += 1
            elif sentiment == "bearish":
                buckets[bucket_idx]["bear"] += 1

    ratios = []
    for b in buckets:
        if b["total"] > 0:
            ratios.append(b["bull"] / b["total"])
        else:
            ratios.append(0.5)  # neutral when no data
    return ratios
