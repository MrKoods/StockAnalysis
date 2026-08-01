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
"""

from typing import Optional



# Minimum final score to surface a trade recommendation
CONFIDENCE_THRESHOLD = 90

# Category maximums (updated for 5-category system)
TECHNICAL_MAX = 40
POSITIONING_MAX = 20
SENTIMENT_MAX = 15
NEWS_MAX = 15
FUNDAMENTAL_MAX = 10
FUNDAMENTAL_INTERNAL_MAX = 15  # FundamentalScorer's own -15..+15 scale, unchanged


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

    Returns full score breakdown dict for audit_log and Discord alert.
    """
    if cfg is None:
        cfg = {}
    if fundamental is None:
        fundamental = {}
    if positioning is None:
        positioning = {}

    # ---------------------------------------------------------------------------
    # Step 1: Technical sub-scores (0-40)
    # ---------------------------------------------------------------------------
    tech_sub = compute_technical_sub_scores(technical, cfg, volume_profile_score)
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
    #   live_weights (from feedback_loop.py's holdout-validated calibration) redistributes
    #   the combined technical+sentiment+news pool (points unchanged, TECHNICAL_MAX +
    #   SENTIMENT_MAX + NEWS_MAX) according to calibrated fractions instead of the fixed
    #   40/15/15 split. Positioning and fundamental are untouched — feedback_loop.py only
    #   tracks these three sub-signals. When live_weights is None (the default, and what
    #   every current caller passes), this is a no-op — previously this parameter was
    #   accepted and documented but never actually read anywhere in this function.
    # ---------------------------------------------------------------------------
    if live_weights:
        pool = technical_total + sentiment_total + news_total
        w_sum = sum(float(v) for v in (
            live_weights.get("technical", 0.0),
            live_weights.get("sentiment", 0.0),
            live_weights.get("news", 0.0),
        ))
        if w_sum > 0 and pool > 0:
            technical_total = pool * (float(live_weights.get("technical", 0.0)) / w_sum)
            sentiment_total = pool * (float(live_weights.get("sentiment", 0.0)) / w_sum)
            news_total = pool * (float(live_weights.get("news", 0.0)) / w_sum)

    # ---------------------------------------------------------------------------
    # Step 5: Fundamental contribution
    #   fundamental_score is on FundamentalScorer's internal -15..+15 scale.
    #   Rescaled here to a -10..+10 contribution (FUNDAMENTAL_MAX / FUNDAMENTAL_INTERNAL_MAX).
    #   data_quality == 'unavailable' → score was already set to 0 by scorer.
    # ---------------------------------------------------------------------------
    fundamental_score_raw = float(fundamental.get("fundamental_score", 0.0))
    fundamental_score_raw = max(-float(FUNDAMENTAL_INTERNAL_MAX), min(float(FUNDAMENTAL_INTERNAL_MAX), fundamental_score_raw))
    fundamental_contribution = fundamental_score_raw * (FUNDAMENTAL_MAX / FUNDAMENTAL_INTERNAL_MAX)
    fundamental_contribution = max(-float(FUNDAMENTAL_MAX), min(float(FUNDAMENTAL_MAX), fundamental_contribution))
    fundamental_data_quality = fundamental.get("data_quality", "unavailable")
    fundamental_data_as_of = fundamental.get("data_as_of")

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

    total_modifier = r_mod + sr_mod + e_mod + ct_mod + seas_mod + mac_mod

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

    direction = determine_direction(technical, sentiment)
    # Event Severity Gate is advisory, not a veto — the signal still surfaces on
    # its own merits; event_gate_blocked/event_gate_trigger are carried through
    # below so the caller can flag the active event alongside the signal.
    meets_threshold = final_score >= CONFIDENCE_THRESHOLD

    return {
        # Technical sub-scores
        "breakout_score": tech_sub["breakout_score"],
        "trend_score": tech_sub["trend_score"],
        "rs_score": tech_sub["rs_score"],
        "rsi_score": tech_sub["rsi_score"],
        "volume_profile_score": tech_sub["volume_profile_score"],
        "technical_total": round(technical_total, 2),

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

        # News sub-scores
        "credibility_score": float(news.get("credibility_weighted_score", 0.0)),
        "theme_score": float(news.get("theme_alignment_score", 0.0)),
        "clustering_score": float(news.get("clustering_score", 0.0)),
        "decay_score": float(news.get("decay_score", 0.0)),
        "news_total": round(news_total, 2),

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
        "fundamental_breakdown": {
            "earnings": fundamental.get("earnings_breakdown", {}),
            "valuation": fundamental.get("valuation_breakdown", {}),
            "sector_averages": fundamental.get("sector_averages", {}),
        },

        # Scoring breakdown
        "base_score": round(base_score, 2),
        "regime_modifier": r_mod,
        "sector_rotation_modifier": sr_mod,
        "earnings_modifier": e_mod,
        "cross_ticker_modifier": ct_mod,
        "seasonality_modifier": seas_mod,
        "macro_modifier": mac_mod,
        "total_modifier": round(total_modifier, 2),
        "final_score": round(final_score, 2),
        "direction": direction,
        "meets_threshold": meets_threshold,

        # Event Severity Gate
        "event_gate_blocked": event_gate_blocked,
        "event_gate_trigger": event_gate_trigger,
    }


def compute_technical_sub_scores(
    technical: dict,
    cfg: Optional[dict] = None,
    volume_profile_score_override: Optional[float] = None,
) -> dict:
    """
    Map raw technical indicator values to 0-8 sub-scores.

    5 sub-signals × 8 points max = 40 total (updated from 5×10=50):
    - breakout_score:       volume z-score × 8 (clamped 0-8)
    - trend_score:          MA alignment + price positioning (0-8)
    - rs_score:             RS vs. SMH z-score (0-8)
    - rsi_score:            RSI position mapping (0-8)
    - volume_profile_score: supplied from volume_profile.py (0-8)
    """
    if cfg is None:
        cfg = {}

    # ---------------------------------------------------------------------------
    # Breakout score (0-8): volume z-score signals unusual activity at breakout
    # Clamp z-score to [-3, +3] range, then scale to 0-8
    # z=0 (average volume) → 4; z=+2 (strong breakout volume) → 6.7; z=+3 → 8
    # ---------------------------------------------------------------------------
    vol_z = float(technical.get("breakout_volume_zscore", 0.0))
    vol_z_clamp = max(-3.0, min(3.0, vol_z))
    breakout_raw = 4.0 + vol_z_clamp * (4.0 / 3.0)  # z=0→4, z=+3→8, z=-3→0
    breakout_confirmed = bool(technical.get("breakout_confirmed", False))
    if not breakout_confirmed:
        breakout_raw = min(breakout_raw, 4.0)  # Cap at neutral if no breakout
    breakout_score = round(max(0.0, min(8.0, breakout_raw)), 2)

    # ---------------------------------------------------------------------------
    # Trend score (0-8): 3-tier scoring (scaled from 0-10 to 0-8)
    #   sma20 > sma50 AND close > sma50 AND MACD bullish → 8
    #   sma20 > sma50 AND close > sma50 → 6
    #   close > sma50 only → 3.2
    #   close < sma50 → 1.2
    # ---------------------------------------------------------------------------
    trend_intact = bool(technical.get("trend_intact", False))
    sma20_above_50 = bool(technical.get("sma_20_above_sma_50", False))
    price_above_50 = bool(technical.get("price_above_sma_50", False))
    macd_bullish = bool(technical.get("macd_bullish", False))
    # Default True: callers/tests that don't set this key are asserting a real
    # macd_bullish value themselves, same as before this field existed. Only
    # compute_technical_indicators sets it False for a genuine NaN (insufficient
    # history) — that case shouldn't silently cap trend_score as if MACD had
    # actively disagreed with an otherwise-intact SMA trend.
    macd_data_available = bool(technical.get("macd_data_available", True))

    if trend_intact and (macd_bullish or not macd_data_available):
        trend_score = 8.0
    elif trend_intact:
        trend_score = 6.0
    elif sma20_above_50 and price_above_50:
        trend_score = 4.64
    elif price_above_50:
        trend_score = 3.2
    else:
        trend_score = 1.2
    trend_score = round(trend_score, 2)

    # ---------------------------------------------------------------------------
    # RS score (0-8): RS z-score maps relative strength vs. SMH
    # rs_z=+3 → 8 (strongly outperforming), rs_z=-3 → 0 (underperforming)
    # ---------------------------------------------------------------------------
    rs_z = float(technical.get("rs_zscore", 0.0))
    rs_z_clamp = max(-2.0, min(2.0, rs_z))
    rs_score = round(max(0.0, min(8.0, 4.0 + rs_z_clamp * (4.0 / 2.0))), 2)

    # ---------------------------------------------------------------------------
    # RSI score (0-8): RSI position mapping (scaled from 0-10 to 0-8)
    # ---------------------------------------------------------------------------
    rsi_val = float(technical.get("rsi_14", 50.0))
    if 55 <= rsi_val <= 65:
        rsi_score = 8.0
    elif 50 <= rsi_val < 55:
        rsi_score = 6.0
    elif 65 < rsi_val <= 72:
        rsi_score = 4.64
    elif 72 < rsi_val <= 80:
        rsi_score = 3.36
    elif rsi_val > 80:
        rsi_score = 1.36
    elif 45 <= rsi_val < 50:
        rsi_score = 4.0
    elif 35 <= rsi_val < 45:
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
        vp_score = float(technical.get("volume_profile_score", 4.0))
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


def determine_direction(technical: dict, sentiment: dict) -> str:
    """
    Determine trade direction ('bullish' or 'bearish') from combined signals.
    Requires agreement between technical trend and dominant sentiment.
    Defaults to 'bullish' when mixed/neutral (system is directional-bullish biased per spec).
    """
    tech_bullish = bool(technical.get("trend_intact", False))
    tech_breakout = bool(technical.get("breakout_confirmed", False))
    dom_sentiment = str(sentiment.get("dominant_sentiment", "neutral"))

    if (tech_bullish or tech_breakout) and dom_sentiment in ("bullish", "neutral"):
        return "bullish"
    if not tech_bullish and dom_sentiment == "bearish":
        return "bearish"
    return "bullish"  # Default to bullish per system bias


def apply_high_vol_regime_cap(score: float, regime: str, cap: float = 70.0) -> float:
    """Cap final score at 70 when regime is high_vol — forces structure to defined-risk spreads."""
    from shared.utils.regime_detection import REGIME_HIGH_VOL
    if regime == REGIME_HIGH_VOL:
        return min(score, cap)
    return score
