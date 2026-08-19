"""
Market Positioning scoring layer for the semiconductor swing trading model.

Computes a positioning_score_total (0-20) per ticker from five sub-signals,
all sourced from free yfinance data (no paid subscription required for this
category, unlike Sentiment):

  options_score        (0-6) — put/call ratio + IV skew, near-the-money
  institutional_score   (0-5) — institutional ownership change vs. prior snapshot
  short_interest_score  (0-4) — shares-short trend (declining = bullish/covering)
  insider_score         (0-3) — Form 4 buy/sell clusters (reuses insider_tracker.py logic)
  analyst_score         (0-2) — recent upgrade/downgrade actions (trend, not level —
                                the static recommendationMean level is already scored
                                by the Fundamental layer's analyst_consensus_score)

Each available sub-signal scores around its own midpoint when neutral (matching
the Technical layer's convention: neutral z-score -> midpoint of the 0-max range).
An unavailable sub-signal forfeits its points to 0 rather than defaulting to the
midpoint — the category never hard-fails to zero unless every source is down
simultaneously, matching the graceful-degradation pattern used by Market
Positioning's design predecessor documents and by sentiment_layer.py.

Institutional ownership change requires a *previous* snapshot (supplied by the
caller, cached in data/processed/positioning_state.json) since yfinance only
exposes a current point-in-time holder list — on the first scan for a ticker,
no comparison is possible and institutional_score falls back to its neutral
midpoint rather than 0 (a real current value exists, just no trend yet).
"""

from typing import Optional

from shared.utils.insider_tracker import classify_transactions, count_distinct_traders

OPTIONS_MAX = 6.0
INSTITUTIONAL_MAX = 5.0
SHORT_INTEREST_MAX = 4.0
INSIDER_MAX = 3.0
ANALYST_MAX = 2.0
POSITIONING_MAX = OPTIONS_MAX + INSTITUTIONAL_MAX + SHORT_INTEREST_MAX + INSIDER_MAX + ANALYST_MAX  # 20


def compute_positioning_score(
    ticker: str,
    positioning_data: dict,
    previous_snapshot: Optional[dict] = None,
    cfg: Optional[dict] = None,
    direction: str = "bullish",
) -> dict:
    """
    Compute the full Market Positioning score bundle for one ticker.

    positioning_data: output of positioning_client.fetch_all_positioning(ticker)
    previous_snapshot: this ticker's positioning_data from the last cached scan
                       (data/processed/positioning_state.json), or None on first run
    direction: "bullish" (default) or "bearish". Each sub-signal mirrors around
    its own neutral midpoint for "bearish": put-heavy options positioning,
    institutional distribution, short interest building, insider selling, and
    analyst downgrades each score high instead of their bullish-favorable
    opposites. "unavailable" (no data) always forfeits to 0 regardless of
    direction — missing data confirms neither thesis.

    Returns dict with all fields required by scoring.py.
    """
    if cfg is None:
        cfg = {}
    positioning_data = positioning_data or {}

    options_score, options_dq = _score_options(positioning_data.get("options"), direction=direction)
    institutional_score, institutional_dq = _score_institutional(
        positioning_data.get("institutional"),
        (previous_snapshot or {}).get("institutional"),
        direction=direction,
    )
    short_interest_score, short_interest_dq = _score_short_interest(
        positioning_data.get("short_interest"), direction=direction
    )
    insider_score, insider_dq = _score_insider(positioning_data.get("insider_transactions"), direction=direction)
    analyst_score, analyst_dq = _score_analyst_trend(positioning_data.get("analyst_trend"), direction=direction)

    positioning_score_total = (
        options_score + institutional_score + short_interest_score + insider_score + analyst_score
    )
    positioning_score_total = round(min(POSITIONING_MAX, max(0.0, positioning_score_total)), 2)

    all_unavailable = all(
        dq == "unavailable" for dq in (options_dq, institutional_dq, short_interest_dq, insider_dq, analyst_dq)
    )
    positioning_offline = all_unavailable

    dq_values = [options_dq, institutional_dq, short_interest_dq, insider_dq, analyst_dq]
    if all(dq == "complete" for dq in dq_values):
        data_quality = "complete"
    elif all_unavailable:
        data_quality = "unavailable"
    else:
        data_quality = "partial"

    return {
        "options_score": round(options_score, 2),
        "institutional_score": round(institutional_score, 2),
        "short_interest_score": round(short_interest_score, 2),
        "insider_score": round(insider_score, 2),
        "analyst_score": round(analyst_score, 2),
        "positioning_score_total": positioning_score_total,
        "positioning_offline": positioning_offline,
        "positioning_offline_cap": 70 if positioning_offline else None,
        "data_quality": data_quality,
        "sub_signal_data_quality": {
            "options": options_dq,
            "institutional": institutional_dq,
            "short_interest": short_interest_dq,
            "insider": insider_dq,
            "analyst": analyst_dq,
        },
        # Raw passthrough (not a scoring input) — trade_selector.py's Greeks
        # filter needs the real chain/dte/iv_percentile positioning_client.py
        # fetched, not just the 0-6 points _score_options() derived from it.
        # Same "_full passthrough" pattern as indicator_pipeline.py's
        # _fundamental_full/_positioning_full.
        "_options_raw": positioning_data.get("options"),
    }


_PERCENTILE_MIN_DQ = "sufficient_history"


def _score_options(options: Optional[dict], direction: str = "bullish") -> tuple[float, str]:
    """
    Score put/call ratio + IV skew. Neutral midpoint = 3.0 (of 0-6).

    direction="bearish": mirrors each component around its 3.0 midpoint —
    a put-heavy ratio/skew (high percentile) scores high instead of a
    call-heavy one, confirming a bearish thesis the same way a call-heavy
    reading confirms a bullish one.

    Prefers each metric's own trailing-history percentile (see
    indicator_pipeline.fetch_positioning_data / positioning_client.
    compute_put_call_ratio_percentile / compute_iv_skew_percentile) over a
    fixed absolute constant — different tickers run structurally different
    baseline put/call ratios depending on their investor base, and real
    equities carry a structural put-skew most of the time (crash-hedging
    demand is a market-wide feature, not stock-specific bearishness), so
    "ratio=1.0"/"skew=0.0" was never really a universal neutral baseline.
    A LOW percentile (today's reading is unusually low vs. this ticker's own
    history) is bullish for both metrics — a call-heavy ratio or a call-rich
    skew relative to normal. Falls back to the old absolute-constant formula
    per-metric while that metric's own history is still accumulating (cold
    start), same graceful-degradation shape used elsewhere in this layer.
    """
    if not options:
        return 0.0, "unavailable"

    ratio = options.get("put_call_ratio")
    skew = options.get("iv_skew")

    if ratio is None and skew is None:
        return 0.0, "unavailable"

    components = []
    if ratio is not None:
        if options.get("put_call_ratio_percentile_data_quality") == _PERCENTILE_MIN_DQ:
            components.append(_score_from_percentile(options["put_call_ratio_percentile"], direction))
        else:
            # ratio=1.0 (balanced) -> 3.0; ratio=0.4 (call-heavy, bullish) -> 6.0; ratio=1.6+ (put-heavy) -> 0.0
            ratio_component = 3.0 - (ratio - 1.0) * 5.0
            ratio_component = max(0.0, min(6.0, ratio_component))
            if direction == "bearish":
                ratio_component = OPTIONS_MAX - ratio_component
            components.append(ratio_component)
    if skew is not None:
        if options.get("iv_skew_percentile_data_quality") == _PERCENTILE_MIN_DQ:
            components.append(_score_from_percentile(options["iv_skew_percentile"], direction))
        else:
            # skew=0 (balanced) -> 3.0; skew=-0.06 (calls richer, bullish) -> 6.0; skew=+0.06 (puts richer) -> 0.0
            skew_component = 3.0 - skew * 50.0
            skew_component = max(0.0, min(6.0, skew_component))
            if direction == "bearish":
                skew_component = OPTIONS_MAX - skew_component
            components.append(skew_component)

    score = sum(components) / len(components)
    dq = "complete" if len(components) == 2 else "partial"
    return score, dq


def _score_from_percentile(percentile: float, direction: str = "bullish") -> float:
    """
    Bullish: percentile=0 (today's reading is the lowest/most call-favoring
    ever seen for this ticker) -> 6.0 (max bullish); percentile=100 (highest/
    most put-favoring ever) -> 0.0; percentile=50 -> 3.0 (neutral midpoint).
    Bearish: mirror image — a high (put-favoring) percentile scores high.
    """
    score = max(0.0, min(6.0, 6.0 * (1.0 - percentile / 100.0)))
    if direction == "bearish":
        score = OPTIONS_MAX - score
    return score


def _score_institutional(
    current: Optional[dict], previous: Optional[dict], direction: str = "bullish"
) -> tuple[float, str]:
    """
    Score institutional ownership change vs. prior snapshot. Neutral midpoint = 2.5 (of 0-5).
    Bearish: mirrors around 2.5 — distribution (outflow) scores high instead of accumulation.
    """
    if not current or current.get("held_percent_institutions") is None:
        return 0.0, "unavailable"

    current_pct = current["held_percent_institutions"]
    previous_pct = (previous or {}).get("held_percent_institutions")

    if previous_pct is None:
        # First scan for this ticker — a current value exists but no trend yet
        # (self-symmetric midpoint — same for both directions).
        return INSTITUTIONAL_MAX / 2.0, "partial"

    delta = current_pct - previous_pct
    # +2pp institutional accumulation -> 5.0; -2pp distribution -> 0.0; flat -> 2.5
    score = 2.5 + delta * (2.5 / 0.02)
    score = max(0.0, min(INSTITUTIONAL_MAX, score))
    if direction == "bearish":
        score = INSTITUTIONAL_MAX - score
    return score, "complete"


def _score_short_interest(short_interest: Optional[dict], direction: str = "bullish") -> tuple[float, str]:
    """
    Score shares-short trend. Neutral midpoint = 2.0 (of 0-4).
    Bearish: shorts building scores high (confirms bearish conviction), shorts
    covering scores low (bearish thesis losing its short-pressure tailwind).
    """
    if not short_interest or short_interest.get("trend") is None:
        return 0.0, "unavailable"

    trend = short_interest["trend"]
    if direction == "bearish":
        if trend == "declining":
            return 0.0, "complete"  # shorts covering -> weakens bearish thesis
        if trend == "increasing":
            return 4.0, "complete"  # shorts building -> confirms bearish
        return 2.0, "complete"  # flat

    if trend == "declining":
        return 4.0, "complete"  # shorts covering -> bullish
    if trend == "increasing":
        return 0.0, "complete"  # shorts building -> bearish
    return 2.0, "complete"  # flat


def _score_insider(transactions: Optional[list], direction: str = "bullish") -> tuple[float, str]:
    """
    Score insider transactions by reusing insider_tracker.py's classification
    logic (classify_transactions), rescaled to a 0-3 sub-signal (midpoint 1.5 =
    no signal, matching insider_tracker's 'neutral' classification).

    Bearish: mirrors the bullish ladder exactly (each pair sums to INSIDER_MAX)
    — insider selling scores high instead of insider buying.
    """
    if transactions is None:
        return 0.0, "unavailable"
    if len(transactions) == 0:
        return INSIDER_MAX / 2.0, "partial"

    signal = classify_transactions(transactions, window_days=10)

    if direction == "bearish":
        if signal == "selling_cluster":
            return INSIDER_MAX, "complete"  # 2+ sellers -> max bearish confirmation
        if signal == "selling":
            return INSIDER_MAX - INSIDER_MAX / 4.0, "complete"  # single seller -> partial credit (2.25)
        if signal == "buying":
            buy_insiders, _ = count_distinct_traders(transactions, window_days=10)
            return (0.0 if len(buy_insiders) >= 2 else INSIDER_MAX - 2.25), "complete"
        return INSIDER_MAX / 2.0, "complete"  # neutral

    if signal == "selling_cluster":
        return 0.0, "complete"
    if signal == "selling":
        # Single seller — previously fell through to "neutral" (classify_
        # transactions had no branch for it at all), scoring a lone insider
        # sale identically to having zero insider data. Mirrors "buying"'s
        # single-buyer partial credit (2.25, i.e. 1.5 + MAX/4) on the bearish
        # side: 1.5 - MAX/4 = 0.75.
        return INSIDER_MAX / 4.0, "complete"
    if signal == "buying":
        # Reuse the same windowed buy_insiders count classify_transactions used to
        # decide "buying" in the first place — this used to re-derive its own
        # buyer count from text-match only, with no date window, which could
        # diverge from the classification above (e.g. a buy detected via shares
        # sign with no matching text yielded 0 local buyers and only partial
        # credit; a stale out-of-window buy could inflate it to full credit).
        buy_insiders, _ = count_distinct_traders(transactions, window_days=10)
        return (INSIDER_MAX if len(buy_insiders) >= 2 else 2.25), "complete"  # 2+ buyers -> max; single buyer -> partial credit
    return INSIDER_MAX / 2.0, "complete"  # neutral


def _score_analyst_trend(analyst_trend: Optional[dict], direction: str = "bullish") -> tuple[float, str]:
    """
    Score recent upgrade/downgrade actions. Neutral midpoint = 1.0 (of 0-2).
    Bearish: downgrade trend scores high instead of upgrade trend.
    """
    if not analyst_trend or "net_action" not in analyst_trend:
        return 0.0, "unavailable"

    net_action = analyst_trend["net_action"]
    if direction == "bearish":
        if net_action == "downgrade":
            return ANALYST_MAX, "complete"
        if net_action == "upgrade":
            return 0.0, "complete"
        if net_action in ("mixed", "none"):
            return 1.0, "partial" if net_action == "none" else "complete"
        return 1.0, "partial"

    if net_action == "upgrade":
        return 2.0, "complete"
    if net_action == "downgrade":
        return 0.0, "complete"
    if net_action in ("mixed", "none"):
        return 1.0, "partial" if net_action == "none" else "complete"
    return 1.0, "partial"
