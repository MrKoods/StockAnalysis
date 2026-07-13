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

from shared.utils.insider_tracker import classify_transactions

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
) -> dict:
    """
    Compute the full Market Positioning score bundle for one ticker.

    positioning_data: output of positioning_client.fetch_all_positioning(ticker)
    previous_snapshot: this ticker's positioning_data from the last cached scan
                       (data/processed/positioning_state.json), or None on first run

    Returns dict with all fields required by scoring.py.
    """
    if cfg is None:
        cfg = {}
    positioning_data = positioning_data or {}

    options_score, options_dq = _score_options(positioning_data.get("options"))
    institutional_score, institutional_dq = _score_institutional(
        positioning_data.get("institutional"),
        (previous_snapshot or {}).get("institutional"),
    )
    short_interest_score, short_interest_dq = _score_short_interest(positioning_data.get("short_interest"))
    insider_score, insider_dq = _score_insider(positioning_data.get("insider_transactions"))
    analyst_score, analyst_dq = _score_analyst_trend(positioning_data.get("analyst_trend"))

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
    }


def _score_options(options: Optional[dict]) -> tuple[float, str]:
    """Score put/call ratio + IV skew. Neutral midpoint = 3.0 (of 0-6)."""
    if not options:
        return 0.0, "unavailable"

    ratio = options.get("put_call_ratio")
    skew = options.get("iv_skew")

    if ratio is None and skew is None:
        return 0.0, "unavailable"

    components = []
    if ratio is not None:
        # ratio=1.0 (balanced) -> 3.0; ratio=0.4 (call-heavy, bullish) -> 6.0; ratio=1.6+ (put-heavy) -> 0.0
        ratio_component = 3.0 - (ratio - 1.0) * 5.0
        components.append(max(0.0, min(6.0, ratio_component)))
    if skew is not None:
        # skew=0 (balanced) -> 3.0; skew=-0.06 (calls richer, bullish) -> 6.0; skew=+0.06 (puts richer) -> 0.0
        skew_component = 3.0 - skew * 50.0
        components.append(max(0.0, min(6.0, skew_component)))

    score = sum(components) / len(components)
    dq = "complete" if len(components) == 2 else "partial"
    return score, dq


def _score_institutional(current: Optional[dict], previous: Optional[dict]) -> tuple[float, str]:
    """Score institutional ownership change vs. prior snapshot. Neutral midpoint = 2.5 (of 0-5)."""
    if not current or current.get("held_percent_institutions") is None:
        return 0.0, "unavailable"

    current_pct = current["held_percent_institutions"]
    previous_pct = (previous or {}).get("held_percent_institutions")

    if previous_pct is None:
        # First scan for this ticker — a current value exists but no trend yet
        return INSTITUTIONAL_MAX / 2.0, "partial"

    delta = current_pct - previous_pct
    # +2pp institutional accumulation -> 5.0; -2pp distribution -> 0.0; flat -> 2.5
    score = 2.5 + delta * (2.5 / 0.02)
    return max(0.0, min(INSTITUTIONAL_MAX, score)), "complete"


def _score_short_interest(short_interest: Optional[dict]) -> tuple[float, str]:
    """Score shares-short trend. Neutral midpoint = 2.0 (of 0-4)."""
    if not short_interest or short_interest.get("trend") is None:
        return 0.0, "unavailable"

    trend = short_interest["trend"]
    if trend == "declining":
        return 4.0, "complete"  # shorts covering -> bullish
    if trend == "increasing":
        return 0.0, "complete"  # shorts building -> bearish
    return 2.0, "complete"  # flat


def _score_insider(transactions: Optional[list]) -> tuple[float, str]:
    """
    Score insider transactions by reusing insider_tracker.py's classification
    logic (classify_transactions), rescaled to a 0-3 sub-signal (midpoint 1.5 =
    no signal, matching insider_tracker's 'neutral' classification).
    """
    if transactions is None:
        return 0.0, "unavailable"
    if len(transactions) == 0:
        return INSIDER_MAX / 2.0, "partial"

    signal = classify_transactions(transactions, window_days=10)
    if signal == "selling_cluster":
        return 0.0, "complete"
    if signal == "buying":
        buyers = set(
            tx.get("insider") or tx.get("name", "x") for tx in transactions
            if "purchase" in str(tx.get("transaction", "")).lower()
            or "buy" in str(tx.get("transaction", "")).lower()
        )
        return (INSIDER_MAX if len(buyers) >= 2 else 2.25), "complete"  # 2+ buyers -> max; single buyer -> partial credit
    return INSIDER_MAX / 2.0, "complete"  # neutral


def _score_analyst_trend(analyst_trend: Optional[dict]) -> tuple[float, str]:
    """Score recent upgrade/downgrade actions. Neutral midpoint = 1.0 (of 0-2)."""
    if not analyst_trend or "net_action" not in analyst_trend:
        return 0.0, "unavailable"

    net_action = analyst_trend["net_action"]
    if net_action == "upgrade":
        return 2.0, "complete"
    if net_action == "downgrade":
        return 0.0, "complete"
    if net_action in ("mixed", "none"):
        return 1.0, "partial" if net_action == "none" else "complete"
    return 1.0, "partial"
