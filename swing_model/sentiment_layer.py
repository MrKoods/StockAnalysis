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
from shared.utils.data_validator import validate_sentiment_data
from shared.utils.logger import get_logger

logger = get_logger(__name__)

# Sentiment offline cap: if both StockTwits and Seeking Alpha are unavailable, cap confidence at 70
SENTIMENT_OFFLINE_CAP = 70

RATIO_MAX = 7.0
VELOCITY_MAX = 5.0
ENGAGEMENT_MAX = 3.0
SENTIMENT_MAX = RATIO_MAX + VELOCITY_MAX + ENGAGEMENT_MAX  # 15

# Neutral midpoint of each sub-score, used when that sub-signal has no data
# (2026-08-26, v2.2.108). All three are SYMMETRIC measures — a bullish/bearish
# ratio, a sentiment/volume velocity, and a comment-count velocity — so 0 is
# not "no information", it is the maximally-opposing end of each scale. Each
# previously forfeited to 0 on missing data, which scored a ticker nobody
# posts about exactly like one whose chatter is unanimously against the thesis,
# across 15 of the 100 composite points.
#
# Same correction News received in v2.2.103, and consistent with
# _score_engagement's own existing behaviour: it already returns the neutral
# midpoint when it has ONE item ("partial") and only forfeited to 0 at zero —
# an internal inconsistency this removes.
#
# SENTIMENT_OFFLINE_CAP still applies on top. The two answer different
# questions: the neutral score says "no evidence either way", the cap says
# "be less confident overall when this signal is missing". Scoring absence as
# maximally bearish AND capping confidence was double-counting the same gap.
RATIO_NEUTRAL = RATIO_MAX / 2.0            # 3.5
VELOCITY_NEUTRAL = VELOCITY_MAX / 2.0      # 2.5
ENGAGEMENT_NEUTRAL = ENGAGEMENT_MAX / 2.0  # 1.5
SENTIMENT_NEUTRAL_TOTAL = RATIO_NEUTRAL + VELOCITY_NEUTRAL + ENGAGEMENT_NEUTRAL  # 7.5


def compute_sentiment_score(
    stocktwits_messages: list[dict],
    seeking_alpha_items: list[dict],
    ticker: str,
    price_data: dict,
    cfg: Optional[dict] = None,
    direction: str = "bullish",
) -> dict:
    """
    Compute the full sentiment score bundle for a ticker.

    stocktwits_messages: output of sentiment_client.fetch_stocktwits(ticker)
    seeking_alpha_items:  output of sentiment_client.fetch_seeking_alpha_engagement(ticker)

    Scoring spec (sum = 15):
    - ratio_score:      0-7  (bullish/bearish ratio, z-scored vs. own trailing history)
    - velocity_score:   0-5  (sentiment/volume acceleration)
    - engagement_score: 0-3  (Seeking Alpha comment-count velocity — weak proxy)

    direction: "bullish" (default) or "bearish". ratio_score/velocity_score
    mirror around their neutral midpoints for "bearish" — a strongly bearish
    StockTwits tilt/velocity confirms a bearish thesis the same way a strongly
    bullish one confirms a bullish thesis. engagement_score is direction-
    neutral (a pure attention-velocity proxy, not a polarity read) — unchanged.

    Returns dict with all fields required by scoring.py.
    """
    if cfg is None:
        cfg = {}
    stocktwits_messages = stocktwits_messages or []
    seeking_alpha_items = seeking_alpha_items or []

    # Log-only visibility, not a hard gate — an unexpected sentiment value or
    # future-dated message previously flowed straight into scoring with no
    # logged trace at all (Signal Integrity Audit finding E.1).
    _sentiment_valid, _sentiment_failures = validate_sentiment_data(ticker, stocktwits_messages)
    if not _sentiment_valid:
        logger.warning(f"{ticker}: Phase 9 sentiment validation flagged {_sentiment_failures}")

    # "We have 30 messages" is not the same as "we have data". A ticker whose
    # entire returned window predates the scoring window has no usable
    # sentiment, and treating it as online produced a real-looking score from
    # nothing (ONB scored 6.0/15 on 2026-08-26 with no post newer than
    # 2026-07-22). Offline is the honest state, and the layer already has a
    # well-tested path for it.
    stocktwits_messages = _recent_messages(stocktwits_messages)
    stocktwits_offline = not stocktwits_messages
    sa_offline = not seeking_alpha_items
    sentiment_offline = stocktwits_offline and sa_offline

    daily_ratios, daily_totals = _build_daily_bullish_ratios(stocktwits_messages, days=5)
    trajectory = compute_sentiment_trajectory(daily_ratios) if not stocktwits_offline else 0.0

    ratio_score, ratio_dq = _score_ratio(stocktwits_messages, daily_ratios, daily_totals, direction=direction)
    velocity_score, velocity_dq = _score_velocity(
        stocktwits_messages, daily_ratios, direction=direction, daily_totals=daily_totals,
    )
    engagement_score, engagement_dq = _score_engagement(seeking_alpha_items)

    sentiment_score_total = ratio_score + velocity_score + engagement_score
    sentiment_score_total = round(min(SENTIMENT_MAX, max(0.0, sentiment_score_total)), 2)

    dom = classify_dominant_sentiment(stocktwits_messages)
    dominant_sentiment = dom["dominant_sentiment"]
    bullish_ratio_stocktwits = dom["bullish_ratio_stocktwits"]

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

# Baseline DAYS that must contain real messages before any "vs. own history"
# comparison is trusted (2026-08-26, v2.2.110). _build_daily_bullish_ratios
# fills empty days with a neutral 0.5 PLACEHOLDER so the buckets are always
# `days` long — but a placeholder is a fabricated observation, and both the
# ratio z-score and the fallback velocity were treating them as real history.
#
# The endpoint returns a fixed 30 messages however much activity a ticker has,
# so how many days those 30 span varies enormously (measured live 2026-08-26:
# NVDA 0.1 hours, ABBV 31 hours, PNFP 233 days). A dense, narrow sample
# therefore lands almost entirely in ONE bucket with the rest placeholder —
# and scored HIGHER than a genuinely broad sample, which is backwards:
#
#   NVDA shape  [0,0,0,0,30]  -> ratio 5.6/7, velocity 5.0/5 (max)
#   ABBV shape  [0,0,0,7,23]  -> ratio 7.0/7 (max), velocity 5.0/5 (max)
#   spread over 5 real days   -> ratio 4.5/7, velocity 0.0/5
#
# _RATIO_MIN_BASELINE_MESSAGES alone did not catch it: it counts baseline
# MESSAGES (ABBV: 7, comfortably over the bar) without checking how many
# baseline DAYS those messages actually came from (ABBV: 1 of 4). pstdev over
# [0.5, 0.5, 0.5, 0.14] is then tiny, so the z-score explodes and saturates.
_MIN_REAL_BASELINE_BUCKETS = 2


def _real_bucket_count(daily_totals: Optional[list[int]], exclude_last: bool = True) -> int:
    """How many daily buckets hold at least one real message (not a placeholder)."""
    if not daily_totals:
        return 0
    buckets = daily_totals[:-1] if exclude_last and len(daily_totals) > 1 else daily_totals
    return sum(1 for t in buckets if t > 0)

# Age window every StockTwits consumer must agree on (2026-08-26, v2.2.107).
# _build_daily_bullish_ratios has always bucketed to `0 <= age_days < days`, so
# the POINT score was protected from stale messages — but
# classify_dominant_sentiment read the raw list with no age filter at all, and
# that function feeds scoring.determine_direction(), which decides whether a
# trade is taken long or short. The most consequential output in the pipeline
# was the one input nothing was filtering.
#
# It matters because the StockTwits endpoint returns a fixed 30 messages
# regardless of how much real activity a ticker has, so 30 messages means
# wildly different things per ticker. Measured live 2026-08-26: NVDA's 30
# messages spanned 0.1 HOURS, ABBV's 31 hours, PNFP's 233 days, and ONB's 364
# days — with ONB's newest message already 5 weeks old on the day it was
# scored. ONB's trade direction was being decided partly by year-old posts.
_STOCKTWITS_MAX_AGE_DAYS = 5


def _recent_messages(messages: list[dict], days: int = _STOCKTWITS_MAX_AGE_DAYS) -> list[dict]:
    """
    Messages within the last `days` days. Same window and same age arithmetic
    _build_daily_bullish_ratios uses for its buckets, so the direction path and
    the point-score path can no longer disagree about which messages are real.
    An unparseable timestamp is dropped rather than kept: _parse_ts falls back
    to now() on failure, which would make undated messages look maximally fresh
    — precisely backwards for a staleness filter.
    """
    now = datetime.now(timezone.utc)
    out = []
    for msg in messages or []:
        raw = msg.get("timestamp_utc", "")
        if not raw:
            continue
        age_days = (now - _parse_ts(raw)).days
        if 0 <= age_days < days:
            out.append(msg)
    return out


def classify_dominant_sentiment(messages: list[dict]) -> dict:
    """
    Classify the dominant StockTwits sentiment lean from raw tagged messages.

    Extracted out of compute_sentiment_score() so the pipeline can determine
    a candidate's trade direction (see scoring.py::determine_direction())
    before running the full sentiment/news/positioning scoring, which need
    direction as an input — this only depends on raw message tags, not on
    any of those later point-scores.

    Same minimum-sample bar _score_ratio() applies before trusting this ratio
    for the point score (see _RATIO_MIN_BASELINE_MESSAGES) — dominant_sentiment
    feeds determine_direction(), deciding the trade's actual bullish/bearish
    DIRECTION, which is more consequential than a point score. A single tagged
    message (e.g. 1 bullish, 0 bearish → ratio 1.0) must not flip the whole
    trade's direction with no sample-size protection.
    """
    # Recency filter FIRST — see _STOCKTWITS_MAX_AGE_DAYS. Without it a ticker
    # whose newest post is weeks old still produced a confident bullish/bearish
    # lean here, and that lean sets the trade's direction.
    messages = _recent_messages(messages)
    bullish_count = sum(1 for m in messages if m.get("sentiment") == "bullish")
    bearish_count = sum(1 for m in messages if m.get("sentiment") == "bearish")
    total_tagged = bullish_count + bearish_count
    bullish_ratio_stocktwits = (bullish_count / total_tagged) if total_tagged > 0 else 0.5

    if total_tagged < _RATIO_MIN_BASELINE_MESSAGES:
        dominant_sentiment = "neutral"
    elif bullish_ratio_stocktwits > 0.55:
        dominant_sentiment = "bullish"
    elif bullish_ratio_stocktwits < 0.45:
        dominant_sentiment = "bearish"
    else:
        dominant_sentiment = "neutral"

    return {
        "dominant_sentiment": dominant_sentiment,
        "bullish_ratio_stocktwits": round(bullish_ratio_stocktwits, 3),
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
    }


def _score_ratio(
    messages: list[dict],
    daily_ratios: list[float],
    daily_totals: Optional[list[int]] = None,
    direction: str = "bullish",
) -> tuple[float, str]:
    """
    Score the current bullish/bearish ratio z-scored against the ticker's own
    trailing daily-bucket history. Neutral midpoint = 3.5 (of 0-7), and that is also what it returns
    when no messages are available — see RATIO_NEUTRAL.

    Requires at least _RATIO_MIN_BASELINE_MESSAGES real messages spread across
    at least _MIN_REAL_BASELINE_BUCKETS real baseline DAYS before trusting the
    z-score — message count alone let a single dense day z-score against three
    placeholder days and saturate (see _MIN_REAL_BASELINE_BUCKETS). Without this gate, a single
    message on a low-volume ticker (with prior days at the 0.5 neutral
    placeholder — see _build_daily_bullish_ratios) computes pstdev([0.5]*4)==0,
    falls back to a tiny std_baseline=0.15, and can max the 0-7 score off n=1 —
    not a real "vs. own history" comparison.

    direction="bearish": mirrors the score around its neutral midpoint — a
    ratio z-scored BELOW its own baseline (unusually bearish-tilted messaging)
    scores high, confirming a bearish thesis the same way an above-baseline
    ratio confirms a bullish one.
    """
    if not messages:
        return RATIO_NEUTRAL, "unavailable"

    baseline = daily_ratios[:-1] if len(daily_ratios) > 1 else []
    current_ratio = daily_ratios[-1] if daily_ratios else 0.5
    baseline_sample_size = sum(daily_totals[:-1]) if daily_totals and len(daily_totals) > 1 else 0
    sign = -1.0 if direction == "bearish" else 1.0

    real_baseline_buckets = _real_bucket_count(daily_totals)
    if (
        len(baseline) >= 2
        and baseline_sample_size >= _RATIO_MIN_BASELINE_MESSAGES
        and real_baseline_buckets >= _MIN_REAL_BASELINE_BUCKETS
    ):
        mean_baseline = statistics.mean(baseline)
        std_baseline = statistics.pstdev(baseline) or 0.15
        z = (current_ratio - mean_baseline) / std_baseline
        score = 3.5 + (sign * z) * 1.75
        return max(0.0, min(RATIO_MAX, score)), "complete"

    # Not enough baseline history to z-score meaningfully — scale today's raw
    # ratio linearly onto [0, RATIO_MAX] instead of fabricating a z-score against
    # a mostly-placeholder baseline. Bearish: scale the bearish fraction
    # (1 - current_ratio) instead, the mirror of the bullish fraction.
    ratio_for_scoring = (1.0 - current_ratio) if direction == "bearish" else current_ratio
    score = ratio_for_scoring * RATIO_MAX
    return max(0.0, min(RATIO_MAX, score)), "insufficient_baseline"


def _score_velocity(
    messages: list[dict],
    daily_ratios: list[float],
    direction: str = "bullish",
    daily_totals: Optional[list[int]] = None,
) -> tuple[float, str]:
    """
    Score sentiment/volume velocity. Prefers StockTwits' native per-message
    sentiment_change/volume_change fields (seeds the calc directly per the
    RapidAPI response); falls back to a trajectory-derived velocity when those
    fields aren't present. Neutral midpoint = 2.5 (of 0-5), and that is also what it returns
    when no messages are available — see VELOCITY_NEUTRAL.

    direction="bearish": mirrors the score around its neutral midpoint — accelerating
    NEGATIVE sentiment/volume velocity scores high, confirming a bearish thesis
    the same way accelerating positive velocity confirms a bullish one.
    """
    if not messages:
        return VELOCITY_NEUTRAL, "unavailable"

    sign = -1.0 if direction == "bearish" else 1.0
    sent_changes = [_as_float(m.get("sentiment_change")) for m in messages]
    sent_changes = [v for v in sent_changes if v is not None]
    vol_changes = [_as_float(m.get("volume_change")) for m in messages]
    vol_changes = [v for v in vol_changes if v is not None]

    if sent_changes or vol_changes:
        avg_sent = statistics.mean(sent_changes) if sent_changes else 0.0
        avg_vol = statistics.mean(vol_changes) if vol_changes else 0.0
        # StockTwits' sentiment_change and volume_change are not on the same scale —
        # confirmed live: sentiment_change stays small (-0.29 to 0.0 observed across
        # several tickers) while volume_change ranges much wider (0.0 to -7.59
        # observed) despite both feeding the same *10 multiplier below. Unclamped,
        # a routine volume_change reading (not even an extreme one) blew straight
        # through the +/-5 range, making velocity_score nearly binary (always 0 or
        # 5) whenever native fields were present — defeating the point of a graded
        # sub-signal. Clamping each to +/-1.0 (+/-100% change) before combining
        # treats them as equally-weighted directional signals once normalized, and
        # anything beyond +/-100% as maximally significant rather than letting it
        # dominate the average.
        avg_sent_clamped = max(-1.0, min(1.0, avg_sent))
        avg_vol_clamped = max(-1.0, min(1.0, avg_vol))
        combined = (avg_sent_clamped + avg_vol_clamped) / 2.0
        score = 2.5 + (sign * combined) * 2.5
        return max(0.0, min(VELOCITY_MAX, score)), "complete"

    # Fallback: derive velocity from the daily bullish-ratio trajectory.
    # velocity is a delta-of-two-half-window trajectory slopes over a bounded
    # [0,1] ratio — with the old x25 multiplier, a swing no bigger than the
    # SIG=0.05 "significant" threshold detect_price_sentiment_divergence uses
    # elsewhere in this file for the same underlying trajectory metric
    # (velocity=0.1) already hit the score's hard ceiling/floor exactly,
    # meaning most real, non-extreme trajectory shifts saturated this
    # sub-signal instead of grading gradually across the 0-5 range. Halved to
    # x12.5: a "significant" 0.05 swing now lands at a modest 3.125 (a real
    # lift, not maxed out), and reaching the ceiling requires a swing twice as
    # large as before (~0.2) — a genuinely large move, not a routine one.
    # Judgment call pending real calibration data, same as this file's other
    # heuristic constants; not derived from a backtest.
    # This fallback reads a trajectory out of daily_ratios, which contains 0.5
    # PLACEHOLDERS for days with no messages. With only one real bucket the
    # "acceleration" it measures is the placeholder->real step itself, not
    # sentiment moving: NVDA's 30-messages-in-6-minutes shape produced
    # [0.5, 0.5, 0.5, 0.5, 0.8] and scored a maxed 5.0/5 off a jump that never
    # happened. A rate of change needs at least two real observations.
    if _real_bucket_count(daily_totals, exclude_last=False) < _MIN_REAL_BASELINE_BUCKETS:
        return VELOCITY_NEUTRAL, "insufficient_baseline"

    velocity = compute_sentiment_velocity(daily_ratios)
    score = 2.5 + (sign * velocity) * 12.5
    return max(0.0, min(VELOCITY_MAX, score)), "partial"


def _score_engagement(items: list[dict]) -> tuple[float, str]:
    """
    Score Seeking Alpha commentCount engagement velocity: compares the average
    comment count of the more-recent half of items to the older half.
    Neutral midpoint = 1.5 (of 0-3), returned whenever engagement velocity
    cannot be measured (no items, or only one) — see ENGAGEMENT_NEUTRAL.
    """
    if not items:
        return ENGAGEMENT_NEUTRAL, "unavailable"
    if len(items) < 2:
        return ENGAGEMENT_NEUTRAL, "partial"

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
        # bull / (bull + bear), not bull / total — total includes untagged
        # messages (StockTwits' entities.sentiment.basic is often absent; confirmed
        # live: 20 of 30 messages for one ticker carried no tag at all). Dividing
        # by total silently treated every untagged message as diluting toward
        # bearish, crushing the ratio toward 0 even when the tagged messages were
        # unanimously bullish (observed live: 10 bullish, 0 bearish, 20 untagged
        # produced a near-zero ratio under the old formula). totals below now
        # tracks tagged-message count specifically, since that's what the ratio
        # is actually built from — _score_ratio's baseline-trust threshold means
        # "5 tagged messages," which is the correct bar now, not "5 messages of
        # any kind including ones that expressed no opinion."
        tagged = b["bull"] + b["bear"]
        if tagged > 0:
            ratios.append(b["bull"] / tagged)
        else:
            ratios.append(0.5)  # neutral when no tagged sentiment that day
        totals.append(tagged)
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
