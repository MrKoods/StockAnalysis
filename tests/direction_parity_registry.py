"""
Registry of every scoring/modifier "producer" — a function in swing_model/
or shared/utils/ that contributes a directional confidence sub-score or
modifier to a candidate's final score.

Two full-model audits (2026-08-19) found the same recurring shape repeatedly:
a new scoring signal correctly handles the bullish case but is bullish-only
or incompletely mirrored for bearish, sometimes for years before being
noticed (e.g. narrative_tracker.theme_alignment_modifier's supply_chain/
memory_cycle branches, fixed the same day this registry was built).
test_direction_parity.py walks both directories for any function matching
the producer naming convention and asserts it's classified here — MIRRORS
(verified to branch/flip correctly on `direction`) or NEUTRAL with a reason
(a deliberate, documented call that direction doesn't apply). A brand-new
producer that isn't classified fails the build until someone makes that
call — not a silent bullish-only ship.

This registry does NOT re-verify correctness (that's each producer's own
unit tests' job) — it only enforces that every producer has been looked at
and classified, so a gap can't just go unnoticed.
"""

MIRRORS = "mirrors"


def NEUTRAL(reason: str) -> str:
    return f"neutral: {reason}"


# Keyed by "module.dotted.path.function_name" (module path relative to the
# repo root, dots for package separators — e.g. "swing_model.scoring" for
# swing_model/scoring.py).
REGISTRY: dict[str, str] = {
    # --- swing_model/scoring.py ---
    "swing_model.scoring.compute_technical_sub_scores": MIRRORS,
    "swing_model.scoring.compute_confidence_score": MIRRORS,

    # --- swing_model/positioning_layer.py ---
    "swing_model.positioning_layer.compute_positioning_score": MIRRORS,
    "swing_model.positioning_layer._score_options": MIRRORS,
    "swing_model.positioning_layer._score_from_percentile": MIRRORS,
    "swing_model.positioning_layer._score_institutional": MIRRORS,
    "swing_model.positioning_layer._score_short_interest": MIRRORS,
    "swing_model.positioning_layer._score_insider": MIRRORS,
    "swing_model.positioning_layer._score_analyst_trend": MIRRORS,

    # --- swing_model/sentiment_layer.py ---
    "swing_model.sentiment_layer.compute_sentiment_score": MIRRORS,
    "swing_model.sentiment_layer._score_ratio": MIRRORS,
    "swing_model.sentiment_layer._score_velocity": MIRRORS,
    "swing_model.sentiment_layer._score_engagement": NEUTRAL(
        "Seeking Alpha commentCount velocity is a pure attention/engagement "
        "proxy — how much a stock is being talked about carries no inherent "
        "bullish/bearish lean, unlike the bullish/bearish ratio and velocity "
        "sub-signals it sits alongside."
    ),

    # --- swing_model/news_layer.py ---
    "swing_model.news_layer.compute_news_score": MIRRORS,
    "swing_model.news_layer.score_news_credibility": MIRRORS,
    "swing_model.news_layer._score_credibility_weighted": MIRRORS,
    "swing_model.news_layer.count_independent_cluster": MIRRORS,

    # --- swing_model/fundamental_layer.py ---
    "swing_model.fundamental_layer._score_premium": NEUTRAL(
        "fundamental_layer.py computes a direction-agnostic fact about the "
        "company (valuation premium vs. peers) — direction is applied once, "
        "at the single point the whole fundamental_score gets consumed "
        "(scoring.py's Step 5, which flips its sign for a bearish candidate), "
        "not inside each individual sub-scorer."
    ),

    # --- swing_model/feedback_loop.py ---
    "swing_model.feedback_loop._score_outcomes": NEUTRAL(
        "calibration-quality metric over a whole holdout set (how well a "
        "candidate weight vector separates historical wins from losses) — "
        "not a per-candidate score and has no notion of one candidate's "
        "trade direction."
    ),

    # --- swing_model/cross_ticker_analysis.py ---
    "swing_model.cross_ticker_analysis.analyze_cross_ticker": NEUTRAL(
        "raw ticker-dispersion computation over the sector watchlist's 5-day "
        "returns — direction-unaware by design; all direction handling lives "
        "in the get_cross_ticker_modifier_for_direction wrapper below, which "
        "is the function every call site actually uses."
    ),
    "swing_model.cross_ticker_analysis.get_cross_ticker_modifier_for_direction": MIRRORS,
    "swing_model.cross_ticker_analysis._get_modifier": NEUTRAL(
        "generic config-value accessor (reads a modifier's configured "
        "min/max bound from state), not itself a directional scorer."
    ),

    # --- shared/utils/narrative_tracker.py ---
    "shared.utils.narrative_tracker.theme_alignment_modifier": MIRRORS,

    # --- shared/utils/regime_detection.py ---
    "shared.utils.regime_detection.get_regime_modifiers": MIRRORS,

    # --- shared/utils/sector_rotation.py ---
    "shared.utils.sector_rotation.get_rotation_modifier": MIRRORS,
    "shared.utils.sector_rotation._rotation_modifier": MIRRORS,
    "shared.utils.sector_rotation.dampen_rotation_penalty_for_leader": MIRRORS,

    # --- shared/utils/macro_overlay.py ---
    "shared.utils.macro_overlay.get_macro_modifier": MIRRORS,
    "shared.utils.macro_overlay.compute_macro_state": MIRRORS,

    # --- shared/utils/seasonality.py ---
    "shared.utils.seasonality.get_seasonality_modifier": MIRRORS,

    # --- shared/utils/earnings_calendar.py ---
    "shared.utils.earnings_calendar.get_earnings_modifier": NEUTRAL(
        "IV-crush / earnings-gap event-timing risk applies to an open "
        "position regardless of which side of the trade it's on — the "
        "penalty is about proximity to an unpredictable-direction event, "
        "not a bullish or bearish lean."
    ),

    # --- shared/utils/volume_profile.py ---
    "shared.utils.volume_profile.score_volume_profile_position": MIRRORS,

    # --- shared/utils/insider_tracker.py ---
    "shared.utils.insider_tracker.get_insider_signal": MIRRORS,
    "shared.utils.insider_tracker._signal_to_modifier": MIRRORS,

    # --- shared/utils/source_credibility.py ---
    "shared.utils.source_credibility.score_news_outlet": NEUTRAL(
        "outlet credibility (e.g. Reuters vs. an unknown blog) is a fixed "
        "property of the source, not the candidate's trade direction."
    ),
}
