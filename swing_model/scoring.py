"""
Master confidence scorer — combines all inputs + applies all modifiers.
Formula (exact per scope — updated for 5-category system):

  Base Score = (Technical Score × 40%) + (Positioning Score × 20%)
             + (Sentiment Score × 15%) + (News Score × 15%) + (Fundamental Score × 10%)
  Final Score = Base Score + Sum(all applicable modifiers)
  Final Score = min(100, max(0, Final Score))

Technical max:    40 (5 sub-signals × 8 each)
Positioning max:  20 (options 0-6, institutional 0-5, short interest 0-4, insider 0-3, analyst 0-2)
Sentiment max:    15 (StockTwits ratio 0-7, StockTwits velocity 0-5, Seeking Alpha engagement 0-3)
News max:         15 (credibility 0-6, theme 0-4, clustering 0-3, decay 0-2)
Fundamental max:  10 (earnings_momentum -9..+9 + valuation -6..+6, combined -15..+15 internally
                      in fundamental_layer.py, then rescaled to a -10..+10 contribution here;
                      0 when data unavailable)

Note on fundamental contribution: FundamentalScorer computes on its own internal -15..+15
scale (unchanged, so its sub-signal thresholds don't need retuning); scoring.py rescales
that raw value by (FUNDAMENTAL_MAX / FUNDAMENTAL_INTERNAL_MAX) to fit its 10-point share of
the 5-category base score. The base score is clamped 0-100 after summing all five categories.

Insider transactions are scored as a Positioning sub-signal (0-3 pts, via
positioning_layer.py) rather than as a standalone confidence modifier — the two would
otherwise double-count the same Form 4 data, so the old insider_modifier parameter has
been removed from this function's signature.

Modifier bounds (applied after base score):
  Regime:          -15 to +10
  Sector rotation: -15 to +5
  Earnings:        -20 to 0
  Cross-ticker:    -10 to +5
  Seasonality:     -5  to +5
  Macro overlay:   -10 to +3

Regime and sector rotation are both derived from the same underlying SMH
price action (regime: SMH vs. its own SMA trend; sector rotation: SMH return
vs. SPY) — when their clamped values agree in sign, only the larger-magnitude
one counts toward total_modifier (not their sum), since that's one real
observation counted once, not two independent corroborating signals. See
regime_sector_rotation_combined in the returned dict for the exact value used.
"""

from datetime import date
from typing import Optional

from swing_model.win_probability_calibration import calibrate_win_probability



# Minimum final score to surface a trade recommendation.
#
# Lowered 90 -> 70 (2026-08-06): confirmed live that 90 was structurally
# unreachable, not just a rough patch — 750 real logged scans across 23
# tickers never once exceeded 79.84 (see paper_trading/score_distribution_
# diagnostic.py). The backtest's own "90 clears the go-live gate" reading
# (backtesting/threshold_optimization_analysis.py) turned out not to be a
# fair comparison: backtesting/simulation.py hardcodes sector_rotation_
# modifier/earnings_modifier/cross_ticker_modifier to 0.0 for every
# simulated bar (no historical archive exists yet to compute them) and uses
# a fixed neutral Positioning score plus a price-momentum Sentiment proxy —
# live pays real penalties (e.g. -15 sector_rotation during an active
# tariff event, hit every semiconductor ticker on 2026-08-06) that the
# backtest never simulates for any historical bar. 70 sits just below the
# real live max ever observed, keeping this genuinely selective (~1.7% of
# real scans clear it) while no longer requiring a combination of
# conditions the current model has never once produced live. Revisit
# upward once enough live/paper-trading history accumulates to build the
# missing modifier/positioning/sentiment archives the backtest needs to
# simulate a fair comparison.
#
# Update: sector_rotation_modifier was wired in for real in v2.2.47, and
# cross_ticker_modifier followed in v2.2.60 — the "hardcoded to 0.0" claim
# above no longer applies to either. earnings_modifier remains hardcoded
# 0.0 (no historical earnings-date archive exists; see backtesting/
# simulation.py's own comment at its compute_confidence_score() call).
CONFIDENCE_THRESHOLD = 70

# Category maximums (updated for 5-category system)
TECHNICAL_MAX = 40
POSITIONING_MAX = 20
SENTIMENT_MAX = 15
NEWS_MAX = 15
FUNDAMENTAL_MAX = 10
FUNDAMENTAL_INTERNAL_MAX = 15  # FundamentalScorer's own -15..+15 scale, unchanged

# Fundamental staleness discount — fundamental_data_as_of routinely lags the
# scan date by 1-13+ days (Alpha Vantage's own fetch cadence/rate limits, not
# a bug — see fundamental_layer.py), yet fundamental_contribution was being
# summed at full weight regardless of age, as if a same-day technical signal
# and a two-week-old fundamental snapshot were equally current. No discount
# inside _FULL_WEIGHT_MAX_DAYS (normal refresh cadence); linear ramp down to
# a floor (not to zero) by _STALENESS_FLOOR_DAYS — earnings/EPS-growth facts
# don't actually go stale as fast as a same-day price-derived valuation ratio
# would, so a floor avoids over-punishing data that's still largely valid.
_FUNDAMENTAL_FULL_WEIGHT_MAX_DAYS = 3
_FUNDAMENTAL_STALENESS_FLOOR_DAYS = 15
_FUNDAMENTAL_STALENESS_WEIGHT_FLOOR = 0.5


def _fundamental_staleness_weight(data_as_of: Optional[str], today: Optional[date] = None) -> float:
    """
    1.0 (no discount) when data_as_of is missing/unparseable/within the normal
    refresh window, linearly ramping down to _FUNDAMENTAL_STALENESS_WEIGHT_FLOOR
    as age grows from _FUNDAMENTAL_FULL_WEIGHT_MAX_DAYS to
    _FUNDAMENTAL_STALENESS_FLOOR_DAYS, held at the floor beyond that (never
    fully zeroed — see module-level comment for why).

    today: injectable for deterministic tests / backtest replay; defaults to
    the real current date for live scans.
    """
    if not data_as_of:
        return 1.0
    try:
        as_of_date = date.fromisoformat(str(data_as_of)[:10])
    except (ValueError, TypeError):
        return 1.0

    reference = today if today is not None else date.today()
    age_days = (reference - as_of_date).days
    if age_days <= _FUNDAMENTAL_FULL_WEIGHT_MAX_DAYS:
        return 1.0
    if age_days >= _FUNDAMENTAL_STALENESS_FLOOR_DAYS:
        return _FUNDAMENTAL_STALENESS_WEIGHT_FLOOR

    span_days = _FUNDAMENTAL_STALENESS_FLOOR_DAYS - _FUNDAMENTAL_FULL_WEIGHT_MAX_DAYS
    progress = (age_days - _FUNDAMENTAL_FULL_WEIGHT_MAX_DAYS) / span_days
    return 1.0 - progress * (1.0 - _FUNDAMENTAL_STALENESS_WEIGHT_FLOOR)


# Data-sufficiency proxy — NOT a statistical confidence interval on
# final_score. A real CI would need repeated-sampling variance estimates per
# sub-signal, which this codebase has no infrastructure to produce for a
# single live score. This instead counts how many of the sub-signals that
# ALREADY self-report a data_quality flag (sentiment_layer.py's ratio/
# velocity/engagement, positioning_layer.py's options/institutional/
# short_interest/insider/analyst, plus fundamental's own top-level
# data_quality) actually had real data behind them, so two scores landing on
# the same final number aren't treated as equally trustworthy when one is
# backed by degraded/missing inputs (e.g. sentiment estimated from as few as
# 30 StockTwits messages, or an "insufficient_baseline" ratio read) and the
# other isn't.
_FULLY_AVAILABLE_DATA_QUALITY = {"complete"}


def compute_data_sufficiency(
    positioning: dict, sentiment: dict, fundamental: dict, technical: Optional[dict] = None
) -> dict:
    """
    Returns {"degraded_sub_signal_count", "total_sub_signals_checked",
    "data_confidence"}. data_confidence is "high" (0 degraded), "medium"
    (1-2 degraded), or "low" (3+ degraded) — a coarse, honestly-labeled
    heuristic, not a precision statistical bound.

    technical: optional (defaults to {}) — Technical previously reported no
    data-quality signal at all despite being the largest single scoring
    category (40 of 100 points), so a ticker whose sma_50/atr/macd silently
    fell back to substitute values (insufficient history) looked exactly as
    trustworthy here as one with a full, real indicator set. Optional so
    existing callers that don't pass it still get a result, just without
    Technical's contribution counted.
    """
    technical = technical or {}
    sub_signal_quality: dict = {}
    sub_signal_quality.update(sentiment.get("sub_signal_data_quality", {}) or {})
    sub_signal_quality.update(positioning.get("sub_signal_data_quality", {}) or {})
    sub_signal_quality.update(technical.get("sub_signal_data_quality", {}) or {})

    degraded = sum(1 for v in sub_signal_quality.values() if v not in _FULLY_AVAILABLE_DATA_QUALITY)
    total = len(sub_signal_quality)

    fundamental_quality = fundamental.get("data_quality", "unavailable")
    if fundamental_quality not in _FULLY_AVAILABLE_DATA_QUALITY:
        degraded += 1
    total += 1

    if degraded == 0:
        confidence = "high"
    elif degraded <= 2:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "degraded_sub_signal_count": degraded,
        "total_sub_signals_checked": total,
        "data_confidence": confidence,
    }


def compute_confidence_score(
    technical: dict,
    positioning: Optional[dict],
    sentiment: dict,
    news: dict,
    regime_modifier: float,
    sector_rotation_modifier: float,
    earnings_modifier: float,
    cross_ticker_modifier: float,
    seasonality_modifier: float,
    macro_modifier: float,
    cfg: Optional[dict] = None,
    live_weights: Optional[dict] = None,
    volume_profile_score: Optional[float] = None,
    regime: Optional[str] = None,
    fundamental: Optional[dict] = None,
    event_gate_blocked: bool = False,
    event_gate_trigger: Optional[str] = None,
    as_of_date: Optional[date] = None,
    win_probability_calibration: Optional[list] = None,
    direction_override: Optional[str] = None,
) -> dict:
    """
    Compute final confidence score for one ticker.

    technical:    output from technical_common.compute_technical_indicators()
    positioning:  output from positioning_layer.compute_positioning_score(); pass None
                  to use neutral 0 contribution (data unavailable behavior)
    sentiment:    output from sentiment_layer.compute_sentiment_score()
    news:         output from news_layer.compute_news_score()
    fundamental:  output from FundamentalScorer.compute_fundamental_score(); pass None
                  to use neutral 0 contribution (data unavailable behavior)
    live_weights: calibrated weights, e.g. from
                  swing_model.feedback_loop.load_live_weights_if_calibrated()
                  (reads data/processed/calibrated_weights.json — only returns
                  non-None once a real calibration has passed holdout); if
                  None (the default, and today's actual state), uses spec weights
    event_gate_blocked:  True if data/processed/event_gate_state.json has an active
                  block covering this ticker (checked by the caller before this call
                  via shared/utils/event_gate.py). Advisory only — does not affect
                  meets_threshold or the score itself; the caller surfaces the
                  signal normally and attaches this as a warning flag so the user
                  can make their own call on a ticker with an active critical event.
    event_gate_trigger:  the trigger headline/keyword reference to attach alongside
                  the score, when event_gate_blocked is True.
    as_of_date:   reference date for judging fundamental_data_as_of's staleness
                  (see _fundamental_staleness_weight) — injectable for
                  deterministic tests/backtest replay; defaults to the real
                  current date for live scans.
    win_probability_calibration: real (threshold -> historical win rate)
                  points from win_probability_calibration.fit_calibration_curve()
                  — used to compute calibrated_win_probability in the return
                  dict. CONFIDENCE_THRESHOLD itself is deliberately left
                  untouched here: once final_score maps to a real probability,
                  the fixed composite cutoff stops being the natural gate,
                  but changing what actually gates a trade is a live-behavior
                  decision, not a
                  calibration bug — see backtesting/threshold_optimization_
                  analysis.py for what the data suggests instead of silently
                  swapping this constant. None (the default) leaves
                  calibrated_win_probability as final_score/100, unchanged.
    direction_override: pre-determined direction ("bullish"/"bearish") from
                  the caller, when it already hoisted determine_direction()
                  earlier in its own pipeline (see run_swing_model.py/
                  paper_runner.py) to score sentiment/news/positioning with
                  the correct direction-aware sub-signal formulas before this
                  function ever runs. None (the default) recomputes direction
                  internally from technical/sentiment, same as before this
                  param existed — existing callers/tests are unaffected.

    Returns full score breakdown dict for audit_log and Discord alert.
    """
    if cfg is None:
        cfg = {}
    if fundamental is None:
        fundamental = {}
    if positioning is None:
        positioning = {}

    # Direction must be known before Step 1, since bearish candidates use the
    # mirrored bearish technical sub-score formulas (compute_technical_sub_scores'
    # direction param) — computed here (or accepted pre-computed via
    # direction_override) rather than after base_score like before, but from
    # the exact same inputs (technical's raw booleans, sentiment's
    # dominant_sentiment), so this reordering doesn't change what direction
    # resolves to for any existing caller.
    direction = direction_override if direction_override is not None else determine_direction(technical, sentiment, cfg)

    # ---------------------------------------------------------------------------
    # Step 1: Technical sub-scores (0-40)
    # ---------------------------------------------------------------------------
    tech_sub = compute_technical_sub_scores(technical, cfg, volume_profile_score, direction=direction)
    technical_total = tech_sub["technical_total"]  # 0-40

    # ---------------------------------------------------------------------------
    # Step 2: Positioning total (already 0-20 from positioning_layer)
    # ---------------------------------------------------------------------------
    positioning_total = float(positioning.get("positioning_score_total", 0.0))
    positioning_total = min(float(POSITIONING_MAX), max(0.0, positioning_total))

    # ---------------------------------------------------------------------------
    # Step 3: Sentiment total (already 0-15 from sentiment_layer)
    # ---------------------------------------------------------------------------
    sentiment_total = float(sentiment.get("sentiment_score_total", 0.0))
    sentiment_total = min(float(SENTIMENT_MAX), max(0.0, sentiment_total))

    # ---------------------------------------------------------------------------
    # Step 4: News total (already 0-15 from news_layer)
    # ---------------------------------------------------------------------------
    news_total = float(news.get("news_score_total", 0.0))
    news_total = min(float(NEWS_MAX), max(0.0, news_total))

    # ---------------------------------------------------------------------------
    # Step 4b: Apply calibrated live_weights, if provided.
    #   live_weights (from feedback_loop.py's holdout-validated calibration) reweights
    #   Technical/Sentiment/News by calibrated importance instead of the fixed 40/15/15
    #   point-budget split. Positioning and fundamental are untouched — feedback_loop.py
    #   only tracks these three sub-signals.
    #
    #   Bug fixed 2026-08-15: this used to redistribute pool = technical_total +
    #   sentiment_total + news_total by weight fraction (pool * w_i/w_sum). Since
    #   sum_i(w_i/w_sum) == 1 by construction, that redistribution always summed back
    #   to the exact same `pool` no matter what the weights were — a mathematical
    #   no-op on base_score. Calibration had been live at this call site for over a
    #   week (see CHANGELOG v2.2.42) without ever influencing a single scoring
    #   decision; it only relabeled the three fields' internal split.
    #
    #   Fixed by weighting each sub-score's own PERCENTAGE of its max (0-1), not its
    #   raw point value — using the raw value would let Technical's larger 40-point
    #   budget go on mechanically dominating regardless of the calibrated weight,
    #   defeating the point of calibration. A ticker's combined quality is the
    #   weighted average of the three percentages, rescaled to the fixed 0-70 pool;
    #   each field then reports its own share of that combined total, so
    #   technical_total + sentiment_total + news_total still equals what base_score
    #   uses below (every downstream consumer — layer_scores DB rows, Discord
    #   alerts, audit_log — reads these three fields expecting that invariant).
    #   Deliberately NOT re-clamped to each field's own original max here: doing so
    #   would silently break that sum invariant whenever a clamp actually engaged
    #   (e.g. calibration weighting sentiment heavily while it's already maxed would
    #   get clipped back to 15, quietly discarding points instead of redistributing
    #   them — worse than the pre-existing, already-known "a field can read above
    #   its nominal max" cosmetic quirk this shares with the original code). The
    #   combined three-field sum is still bounded by the fixed 70-point pool
    #   either way, and base_score's own [0,100] clamp below is the real backstop.
    #   When live_weights is None (the default), this whole block is skipped and
    #   behavior is unchanged from before this fix.
    # ---------------------------------------------------------------------------
    # technical_max/sentiment_max/news_max: the cap each of these three fields
    # is actually operating under right now, for callers that display a score
    # as "X/max" (paper_runner.py's scan log, discord_alerts.py's embeds).
    # Nominal (40/15/15) unless live_weights is active, in which case a
    # category's real ceiling shifts with its calibrated weight fraction of
    # the shared 70-point pool — e.g. consumer_discretionary's sentiment=0.4
    # weight raises sentiment's real cap to 28, not 15. Without this, a
    # reweighted score above its nominal max (by design — see the "Deliberately
    # NOT re-clamped" note above) reads as a scoring bug in any "X/15"-style
    # display instead of the deliberate redistribution it actually is.
    technical_max = float(TECHNICAL_MAX)
    sentiment_max = float(SENTIMENT_MAX)
    news_max = float(NEWS_MAX)

    if live_weights:
        w_tech = float(live_weights.get("technical", 0.0))
        w_sent = float(live_weights.get("sentiment", 0.0))
        w_news = float(live_weights.get("news", 0.0))
        w_sum = w_tech + w_sent + w_news
        if w_sum > 0:
            pool = float(TECHNICAL_MAX + SENTIMENT_MAX + NEWS_MAX)
            tech_pct = technical_total / TECHNICAL_MAX if TECHNICAL_MAX else 0.0
            sent_pct = sentiment_total / SENTIMENT_MAX if SENTIMENT_MAX else 0.0
            news_pct = news_total / NEWS_MAX if NEWS_MAX else 0.0
            technical_total = pool * (tech_pct * w_tech / w_sum)
            sentiment_total = pool * (sent_pct * w_sent / w_sum)
            news_total = pool * (news_pct * w_news / w_sum)
            technical_max = pool * (w_tech / w_sum)
            sentiment_max = pool * (w_sent / w_sum)
            news_max = pool * (w_news / w_sum)

    # ---------------------------------------------------------------------------
    # Step 5: Fundamental contribution
    #   fundamental_score is on FundamentalScorer's internal -15..+15 scale.
    #   Rescaled here to a -10..+10 contribution (FUNDAMENTAL_MAX / FUNDAMENTAL_INTERNAL_MAX).
    #   data_quality == 'unavailable' → score was already set to 0 by scorer.
    #
    #   fundamental_layer.py computes a direction-agnostic fact about the
    #   company (strong/weak earnings & valuation) — it has no notion of
    #   which way the trade is pointed. Good fundamentals should SUPPORT a
    #   bullish thesis and OPPOSE a bearish one (and vice versa for weak
    #   fundamentals), so the sign is flipped here, at the one place
    #   direction is already known and this raw fact gets turned into a
    #   trade-direction-relative contribution — same mirroring the other
    #   directional inputs (regime/rotation/macro/seasonality) apply at
    #   their own consumption points. Previously unmirrored: a bearish
    #   candidate with genuinely deteriorating fundamentals (which should
    #   confirm the short thesis) was instead being penalized by them, and a
    #   bearish candidate with strong fundamentals was rewarded — backwards
    #   in both cases (Signal Integrity Audit finding B.1).
    # ---------------------------------------------------------------------------
    fundamental_score_raw = float(fundamental.get("fundamental_score", 0.0))
    fundamental_score_raw = max(-float(FUNDAMENTAL_INTERNAL_MAX), min(float(FUNDAMENTAL_INTERNAL_MAX), fundamental_score_raw))
    if direction == "bearish":
        fundamental_score_raw = -fundamental_score_raw
    fundamental_contribution = fundamental_score_raw * (FUNDAMENTAL_MAX / FUNDAMENTAL_INTERNAL_MAX)
    fundamental_contribution = max(-float(FUNDAMENTAL_MAX), min(float(FUNDAMENTAL_MAX), fundamental_contribution))
    fundamental_data_quality = fundamental.get("data_quality", "unavailable")
    fundamental_data_as_of = fundamental.get("data_as_of")
    fundamental_staleness_weight = _fundamental_staleness_weight(fundamental_data_as_of, today=as_of_date)
    fundamental_contribution *= fundamental_staleness_weight

    # ---------------------------------------------------------------------------
    # Step 6: Base Score = technical + positioning + sentiment + news + fundamental
    #   technical [0,40] + positioning [0,20] + sentiment [0,15] + news [0,15] = [0,90].
    #   fundamental [-10,+10] shifts the total to [-10,100].
    #   Clamped to [0,100] after summing.
    # ---------------------------------------------------------------------------
    base_score = technical_total + positioning_total + sentiment_total + news_total + fundamental_contribution
    base_score = min(100.0, max(0.0, base_score))

    # ---------------------------------------------------------------------------
    # Step 7: Clamp each modifier to its spec bounds before summing
    # ---------------------------------------------------------------------------
    r_mod = max(-15.0, min(10.0, float(regime_modifier)))
    sr_mod = max(-15.0, min(5.0, float(sector_rotation_modifier)))
    e_mod = max(-20.0, min(0.0, float(earnings_modifier)))
    ct_mod = max(-10.0, min(5.0, float(cross_ticker_modifier)))
    seas_mod = max(-5.0, min(5.0, float(seasonality_modifier)))
    mac_mod = max(-10.0, min(3.0, float(macro_modifier)))

    # regime_modifier (SMH vs. its own SMA trend) and sector_rotation_modifier
    # (SMH return vs. SPY) are both derived from the same underlying SMH price
    # action. When they agree in sign, that's one real observation ("SMH is
    # weak"/"SMH is strong") being counted twice, not two independent
    # corroborating signals — take whichever has the larger magnitude instead
    # of summing both. Opposite signs are left summed unchanged: that's a real
    # disagreement between the two lenses (SMH's own trend vs. SMH's relative
    # return), not a double-count. r_mod/sr_mod themselves are left untouched
    # in the returned breakdown below so the raw per-modifier values (and the
    # collinearity/NOTE detection that reads them) stay visible — only the
    # bottom-line total_modifier reflects the dedup.
    if (r_mod < 0 and sr_mod < 0) or (r_mod > 0 and sr_mod > 0):
        regime_sector_combined = max(r_mod, sr_mod, key=abs)
    else:
        regime_sector_combined = r_mod + sr_mod

    total_modifier = regime_sector_combined + e_mod + ct_mod + seas_mod + mac_mod

    # ---------------------------------------------------------------------------
    # Step 8: Final Score = Base Score + Sum(modifiers), clamped [0, 100]
    # ---------------------------------------------------------------------------
    final_score = base_score + total_modifier
    final_score = min(100.0, max(0.0, final_score))

    # Apply high-vol regime cap (forces score ≤ 70 → structure must be spreads)
    if regime is not None:
        final_score = apply_high_vol_regime_cap(final_score, regime)

    # Sentiment offline cap: if offline, cap at 70
    if sentiment.get("sentiment_offline", False):
        final_score = min(final_score, sentiment.get("sentiment_offline_cap", 70))

    # Positioning offline cap: if offline, cap at 70 (mirrors sentiment's degradation rule).
    # Also fires on an empty positioning dict (from the positioning=None default above, or
    # any future caller passing {} directly) — .get("positioning_offline", False) alone
    # reads False when the key is simply absent, silently skipping the degradation cap
    # for exactly the "no positioning data at all" case it exists to catch.
    if positioning.get("positioning_offline", False) or not positioning:
        final_score = min(final_score, positioning.get("positioning_offline_cap", 70))

    # Event Severity Gate is advisory, not a veto — the signal still surfaces on
    # its own merits; event_gate_blocked/event_gate_trigger are carried through
    # below so the caller can flag the active event alongside the signal.
    meets_threshold = final_score >= CONFIDENCE_THRESHOLD

    data_sufficiency = compute_data_sufficiency(positioning, sentiment, fundamental, technical)

    if win_probability_calibration:
        calibrated_win_probability = calibrate_win_probability(final_score, win_probability_calibration)
        win_prob_calibrated = True
    else:
        calibrated_win_probability = final_score / 100.0
        win_prob_calibrated = False

    return {
        # Technical sub-scores
        "breakout_score": tech_sub["breakout_score"],
        "trend_score": tech_sub["trend_score"],
        "rs_score": tech_sub["rs_score"],
        "rsi_score": tech_sub["rsi_score"],
        "volume_profile_score": tech_sub["volume_profile_score"],
        "technical_total": round(technical_total, 2),
        "technical_max": round(technical_max, 2),

        # Positioning sub-scores
        "options_score": float(positioning.get("options_score", 0.0)),
        "institutional_score": float(positioning.get("institutional_score", 0.0)),
        "short_interest_score": float(positioning.get("short_interest_score", 0.0)),
        "insider_score": float(positioning.get("insider_score", 0.0)),
        "analyst_score": float(positioning.get("analyst_score", 0.0)),
        "positioning_total": round(positioning_total, 2),

        # Sentiment sub-scores
        "ratio_score": float(sentiment.get("ratio_score", 0.0)),
        "velocity_score": float(sentiment.get("velocity_score", 0.0)),
        "engagement_score": float(sentiment.get("engagement_score", 0.0)),
        "sentiment_total": round(sentiment_total, 2),
        "sentiment_max": round(sentiment_max, 2),
        # Advisory only — not a scoring input. Was computed by sentiment_layer.py
        # every scan but never read by anything downstream (confirmed via
        # repo-wide search); passed through here so it's at least reachable
        # by any caller holding the full score dict instead of being silently
        # discarded.
        "divergence_flag": sentiment.get("divergence_flag", "neutral"),

        # News sub-scores
        "credibility_score": float(news.get("credibility_weighted_score", 0.0)),
        "theme_score": float(news.get("theme_alignment_score", 0.0)),
        "clustering_score": float(news.get("clustering_score", 0.0)),
        "decay_score": float(news.get("decay_score", 0.0)),
        "news_total": round(news_total, 2),
        "news_max": round(news_max, 2),

        # Fundamental sub-scores
        "fundamental_score": round(fundamental_contribution, 2),
        "earnings_momentum_score": fundamental.get("earnings_momentum_score", 0),
        "valuation_score": fundamental.get("valuation_score", 0),
        "eps_growth_score": fundamental.get("eps_growth_score", 0),
        "estimate_revisions_score": fundamental.get("estimate_revisions_score", 0),
        "earnings_surprise_score": fundamental.get("earnings_surprise_score", 0),
        "analyst_consensus_score": fundamental.get("analyst_consensus_score", 0),
        "pe_vs_sector_score": fundamental.get("pe_vs_sector_score", 0),
        "forward_vs_trailing_pe_score": fundamental.get("forward_vs_trailing_pe_score", 0),
        "ev_ebitda_vs_peers_score": fundamental.get("ev_ebitda_vs_peers_score", 0),
        "fundamental_data_quality": fundamental_data_quality,
        "fundamental_data_as_of": fundamental_data_as_of,
        "fundamental_staleness_weight": round(fundamental_staleness_weight, 3),
        "fundamental_breakdown": {
            "earnings": fundamental.get("earnings_breakdown", {}),
            "valuation": fundamental.get("valuation_breakdown", {}),
            "sector_averages": fundamental.get("sector_averages", {}),
        },

        # Scoring breakdown
        "base_score": round(base_score, 2),
        "regime_modifier": r_mod,
        "sector_rotation_modifier": sr_mod,
        "regime_sector_rotation_combined": round(regime_sector_combined, 2),
        "earnings_modifier": e_mod,
        "cross_ticker_modifier": ct_mod,
        "seasonality_modifier": seas_mod,
        "macro_modifier": mac_mod,
        "total_modifier": round(total_modifier, 2),
        "final_score": round(final_score, 2),
        "direction": direction,
        "meets_threshold": meets_threshold,

        # Data-sufficiency proxy — see compute_data_sufficiency's docstring
        # for why this is a heuristic, not a statistical confidence interval.
        "data_confidence": data_sufficiency["data_confidence"],
        "degraded_sub_signal_count": data_sufficiency["degraded_sub_signal_count"],
        "total_sub_signals_checked": data_sufficiency["total_sub_signals_checked"],

        # Calibrated win probability — see win_probability_calibration param's
        # docstring above for why final_score/100 alone was never a real
        # probability, and why CONFIDENCE_THRESHOLD itself isn't changed here.
        "calibrated_win_probability": round(calibrated_win_probability, 4),
        "win_prob_calibrated": win_prob_calibrated,

        # Event Severity Gate
        "event_gate_blocked": event_gate_blocked,
        "event_gate_trigger": event_gate_trigger,
    }


def compute_technical_sub_scores(
    technical: dict,
    cfg: Optional[dict] = None,
    volume_profile_score_override: Optional[float] = None,
    direction: str = "bullish",
) -> dict:
    """
    Map raw technical indicator values to 0-8 sub-scores.

    5 sub-signals × 8 points max = 40 total (updated from 5×10=50):
    - breakout_score:       volume z-score × 8 (clamped 0-8)
    - trend_score:          MA alignment + price positioning (0-8)
    - rs_score:             RS vs. SMH z-score (0-8)
    - rsi_score:            RSI position mapping (0-8)
    - volume_profile_score: supplied from volume_profile.py (0-8)

    direction: "bullish" (default) or "bearish". For "bearish", breakout_score/
    trend_score/rsi_score/volume_profile_score use their mirrored bearish
    counterparts (breakdown_confirmed instead of breakout_confirmed,
    downtrend_intact instead of trend_intact, an oversold RSI band instead of
    the overbought-friendly bullish one, and the bearish volume-profile
    resistance read). rs_score is reused unchanged — rs_zscore is already
    signed, so a strongly negative reading (underperforming the benchmark)
    scores high for a bearish candidate the same formula already does for a
    strongly positive reading on a bullish one.
    """
    if cfg is None:
        cfg = {}
    is_bearish = direction == "bearish"

    # ---------------------------------------------------------------------------
    # Breakout score (0-8): volume z-score signals unusual activity at the
    # breakout (bullish) or breakdown (bearish) bar.
    # Clamp z-score to [-3, +3] range, then scale to 0-8
    # z=0 (average volume) → 4; z=+2 (strong conviction volume) → 6.7; z=+3 → 8
    # ---------------------------------------------------------------------------
    vol_z = float(technical.get("breakout_volume_zscore", 0.0))
    vol_z_clamp = max(-3.0, min(3.0, vol_z))
    breakout_raw = 4.0 + vol_z_clamp * (4.0 / 3.0)  # z=0→4, z=+3→8, z=-3→0
    confirmed_key = "breakdown_confirmed" if is_bearish else "breakout_confirmed"
    if not bool(technical.get(confirmed_key, False)):
        breakout_raw = min(breakout_raw, 4.0)  # Cap at neutral if no breakout/breakdown
    breakout_score = round(max(0.0, min(8.0, breakout_raw)), 2)

    # ---------------------------------------------------------------------------
    # Trend score (0-8): 3-tier scoring (scaled from 0-10 to 0-8)
    #   Bullish: sma20 > sma50 AND close > sma50 AND MACD bullish → 8
    #            sma20 > sma50 AND close > sma50 → 6
    #            close > sma50 only → 3.2
    #            close < sma50 → 1.2
    #   Bearish: mirror image using downtrend_intact/macd_bearish and the
    #            inverse of sma_20_above_sma_50/price_above_sma_50.
    # ---------------------------------------------------------------------------
    macd_data_available = bool(technical.get("macd_data_available", True))

    if is_bearish:
        trend_broken = bool(technical.get("downtrend_intact", False))
        sma20_below_50 = not bool(technical.get("sma_20_above_sma_50", False))
        price_below_50 = not bool(technical.get("price_above_sma_50", False))
        macd_bearish = bool(technical.get("macd_bearish", False))
        macd_agrees = macd_bearish or not macd_data_available
        secondary = sma20_below_50 and price_below_50
        tertiary = price_below_50
    else:
        trend_broken = bool(technical.get("trend_intact", False))
        macd_agrees = bool(technical.get("macd_bullish", False)) or not macd_data_available
        secondary = bool(technical.get("sma_20_above_sma_50", False)) and bool(technical.get("price_above_sma_50", False))
        tertiary = bool(technical.get("price_above_sma_50", False))

    if trend_broken and macd_agrees:
        trend_score = 8.0
    elif trend_broken:
        trend_score = 6.0
    elif secondary:
        trend_score = 4.64
    elif tertiary:
        trend_score = 3.2
    else:
        trend_score = 1.2
    trend_score = round(trend_score, 2)

    # ---------------------------------------------------------------------------
    # RS score (0-8): RS z-score maps relative strength vs. SMH — reused as-is
    # for both directions. Already signed/symmetric: rs_z=+1.5 → 8 (strongly
    # outperforming, bullish-favorable), rs_z=-1.5 → 0 (strongly
    # underperforming). A bearish candidate's thesis is confirmed by
    # underperformance, so a bearish evaluation reflects the same z-score
    # around its midpoint instead of re-deriving a separate formula.
    # Anchor history: 3.0 (original) -> 2.0 (v2.2.29, real improvement over 3.0
    # once the small-sample artifact was ruled out) -> 1.5 (v2.2.33, re-tested
    # against the 3-sector pooled backtest: 1.5 beat both its neighbors, 1.0 and
    # 2.0/2.5, on Sharpe — 3.21 vs 3.14/3.10/3.08 respectively).
    # ---------------------------------------------------------------------------
    rs_z = float(technical.get("rs_zscore", 0.0))
    rs_z_for_scoring = -rs_z if is_bearish else rs_z
    rs_z_clamp = max(-1.5, min(1.5, rs_z_for_scoring))
    rs_score = round(max(0.0, min(8.0, 4.0 + rs_z_clamp * (4.0 / 1.5))), 2)

    # ---------------------------------------------------------------------------
    # RSI score (0-8): RSI position mapping (scaled from 0-10 to 0-8)
    # ---------------------------------------------------------------------------
    # Sweet-spot band widened 55-65 -> 50-70 (v2.2.33): re-tested against the
    # 3-sector pooled backtest alongside neighbors 52-68 (Sharpe 3.33) and 48-74
    # (Sharpe 3.17, worse on every axis — confirms 48-74 overshoots). 50-70 and
    # 52-68 were statistically tied (Sharpe 3.34 vs 3.33); kept 50-70 for +8 more
    # trades at the same Sharpe/drawdown.
    #
    # Bearish uses the same ladder applied to (100 - rsi_val) — an oversold
    # momentum mirror of the bullish sweet spot (e.g. bullish 50-70 becomes
    # bearish 30-50), starting as a direct reflection pending its own backtest
    # re-validation the same way the bullish band's boundaries were re-tested
    # rather than assumed.
    rsi_val = float(technical.get("rsi_14", 50.0))
    rsi_val_for_scoring = 100.0 - rsi_val if is_bearish else rsi_val
    if 50 <= rsi_val_for_scoring <= 70:
        rsi_score = 8.0
    elif 45 <= rsi_val_for_scoring < 50:
        rsi_score = 6.0
    elif 70 < rsi_val_for_scoring <= 72:
        rsi_score = 4.64
    elif 72 < rsi_val_for_scoring <= 80:
        rsi_score = 3.36
    elif rsi_val_for_scoring > 80:
        rsi_score = 1.36
    elif 35 <= rsi_val_for_scoring < 45:
        rsi_score = 2.0
    else:
        rsi_score = 0.64
    rsi_score = round(rsi_score, 2)

    # ---------------------------------------------------------------------------
    # Volume profile score (0-8): supplied by volume_profile.py, or neutral=4
    # ---------------------------------------------------------------------------
    if volume_profile_score_override is not None:
        vp_score = round(max(0.0, min(8.0, float(volume_profile_score_override))), 2)
    else:
        vp_field = "volume_profile_score_bearish" if is_bearish else "volume_profile_score"
        vp_score = float(technical.get(vp_field, 4.0))
        vp_score = round(max(0.0, min(8.0, vp_score)), 2)

    technical_total = round(breakout_score + trend_score + rs_score + rsi_score + vp_score, 2)
    technical_total = min(float(TECHNICAL_MAX), technical_total)

    return {
        "breakout_score": breakout_score,
        "trend_score": trend_score,
        "rs_score": rs_score,
        "rsi_score": rsi_score,
        "volume_profile_score": vp_score,
        "technical_total": technical_total,
    }


def determine_direction(technical: dict, sentiment: dict, cfg: Optional[dict] = None) -> str:
    """
    Determine trade direction ('bullish' or 'bearish') from combined signals.
    Requires agreement between technical trend and dominant sentiment.
    Defaults to 'bullish' when mixed/neutral or when neither side clearly agrees.

    cfg: swing_config.yaml contents. The bearish branch only fires when
    cfg["enable_bearish_signals"] is explicitly True — the kill-switch for
    live/paper trading. cfg=None (the default) allows bearish, matching the
    behavior backtesting/calibration callers need (they pass their own
    explicit direction/mask logic upstream of this function, or no cfg at
    all, and must be able to exercise the bearish path to validate it) —
    only real live/paper callers (run_swing_model.py, paper_runner.py) pass
    the real cfg with the flag defaulting False.
    """
    tech_bullish = bool(technical.get("trend_intact", False))
    tech_breakout = bool(technical.get("breakout_confirmed", False))
    tech_bearish = bool(technical.get("downtrend_intact", False))
    tech_breakdown = bool(technical.get("breakdown_confirmed", False))
    dom_sentiment = str(sentiment.get("dominant_sentiment", "neutral"))

    if (tech_bullish or tech_breakout) and dom_sentiment in ("bullish", "neutral"):
        return "bullish"

    bearish_enabled = bool((cfg or {}).get("enable_bearish_signals", False)) if cfg is not None else True
    if bearish_enabled and (tech_bearish or tech_breakdown) and dom_sentiment in ("bearish", "neutral"):
        return "bearish"

    return "bullish"  # Default to bullish per system bias


def apply_high_vol_regime_cap(score: float, regime: str, cap: float = 70.0) -> float:
    """Cap final score at 70 when regime is high_vol — forces structure to defined-risk spreads."""
    from shared.utils.regime_detection import REGIME_HIGH_VOL
    if regime == REGIME_HIGH_VOL:
        return min(score, cap)
    return score
