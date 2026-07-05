"""
Master confidence scorer — combines all inputs + applies all modifiers.
Formula (exact per scope — updated for 4-category system):

  Base Score = (Technical Score × 50%) + (Sentiment Score × 20%)
             + (News Score × 15%) + (Fundamental Score × 15%)
  Final Score = Base Score + Sum(all applicable modifiers)
  Final Score = min(100, max(0, Final Score))

Technical max:    50 (5 sub-signals × 10 each)
Sentiment max:    20 (trajectory 0-8, velocity 0-4, consistency 0-4, spike 0-4)
News max:         15 (credibility 0-6, theme 0-4, clustering 0-3, decay 0-2)
Fundamental max:  15 (earnings_momentum -9..+9 + valuation -6..+6, combined -15..+15,
                      scaled to -15..+15 contribution; 0 when data unavailable)

Note on fundamental contribution: the fundamental_score from FundamentalScorer is already
on a -15..+15 scale, so it is added directly to the base score (contributing up to +15 or
as low as -15). The base score is clamped 0-100 after summing all four categories.

Modifier bounds (applied after base score):
  Regime:          -15 to +10
  Sector rotation: -15 to +5
  Earnings:        -20 to 0
  Cross-ticker:    -10 to +5
  Insider:         -8  to +8
  Seasonality:     -5  to +5
  Macro overlay:   -10 to +3
"""

from typing import Optional

import yaml


# Minimum final score to surface a trade recommendation
CONFIDENCE_THRESHOLD = 90

# Category maximums (updated for 4-category system)
TECHNICAL_MAX = 50
SENTIMENT_MAX = 20
NEWS_MAX = 15
FUNDAMENTAL_MAX = 15


def compute_confidence_score(
    technical: dict,
    sentiment: dict,
    news: dict,
    regime_modifier: float,
    sector_rotation_modifier: float,
    earnings_modifier: float,
    cross_ticker_modifier: float,
    insider_modifier: float,
    seasonality_modifier: float,
    macro_modifier: float,
    cfg: Optional[dict] = None,
    live_weights: Optional[dict] = None,
    volume_profile_score: Optional[float] = None,
    regime: Optional[str] = None,
    fundamental: Optional[dict] = None,
) -> dict:
    """
    Compute final confidence score for one ticker.

    technical:   output from technical_common.compute_technical_indicators()
    sentiment:   output from sentiment_layer.compute_sentiment_score()
    news:        output from news_layer.compute_news_score()
    fundamental: output from FundamentalScorer.compute_fundamental_score(); pass None
                 to use neutral 0 contribution (data unavailable behavior)
    live_weights: calibrated weights from data/processed/live_weights.json;
                  if None, uses spec weights

    Returns full score breakdown dict for audit_log and Discord alert.
    """
    if cfg is None:
        cfg = {}
    if fundamental is None:
        fundamental = {}

    # ---------------------------------------------------------------------------
    # Step 1: Technical sub-scores (0-50)
    # ---------------------------------------------------------------------------
    tech_sub = compute_technical_sub_scores(technical, cfg, volume_profile_score)
    technical_total = tech_sub["technical_total"]  # 0-50

    # ---------------------------------------------------------------------------
    # Step 2: Sentiment total (already 0-20 from sentiment_layer)
    # ---------------------------------------------------------------------------
    sentiment_total = float(sentiment.get("sentiment_score_total", 0.0))
    sentiment_total = min(float(SENTIMENT_MAX), max(0.0, sentiment_total))

    # ---------------------------------------------------------------------------
    # Step 3: News total (already 0-15 from news_layer)
    # ---------------------------------------------------------------------------
    news_total = float(news.get("news_score_total", 0.0))
    news_total = min(float(NEWS_MAX), max(0.0, news_total))

    # ---------------------------------------------------------------------------
    # Step 4: Fundamental contribution
    #   fundamental_score is on -15..+15 scale from FundamentalScorer.
    #   data_quality == 'unavailable' → score was already set to 0 by scorer.
    #   We add it directly; base_score is clamped 0-100 after summing.
    # ---------------------------------------------------------------------------
    fundamental_score_raw = float(fundamental.get("fundamental_score", 0.0))
    fundamental_score_raw = max(-float(FUNDAMENTAL_MAX), min(float(FUNDAMENTAL_MAX), fundamental_score_raw))
    fundamental_data_quality = fundamental.get("data_quality", "unavailable")

    # ---------------------------------------------------------------------------
    # Step 5: Base Score = technical + sentiment + news + fundamental
    #   technical [0,50] + sentiment [0,20] + news [0,15] = [0,85] before fundamental.
    #   fundamental [-15,+15] shifts the total to [-15,100].
    #   Clamped to [0,100] after summing.
    # ---------------------------------------------------------------------------
    base_score = technical_total + sentiment_total + news_total + fundamental_score_raw
    base_score = min(100.0, max(0.0, base_score))

    # ---------------------------------------------------------------------------
    # Step 6: Clamp each modifier to its spec bounds before summing
    # ---------------------------------------------------------------------------
    r_mod = max(-15.0, min(10.0, float(regime_modifier)))
    sr_mod = max(-15.0, min(5.0, float(sector_rotation_modifier)))
    e_mod = max(-20.0, min(0.0, float(earnings_modifier)))
    ct_mod = max(-10.0, min(5.0, float(cross_ticker_modifier)))
    ins_mod = max(-8.0, min(8.0, float(insider_modifier)))
    seas_mod = max(-5.0, min(5.0, float(seasonality_modifier)))
    mac_mod = max(-10.0, min(3.0, float(macro_modifier)))

    total_modifier = r_mod + sr_mod + e_mod + ct_mod + ins_mod + seas_mod + mac_mod

    # ---------------------------------------------------------------------------
    # Step 7: Final Score = Base Score + Sum(modifiers), clamped [0, 100]
    # ---------------------------------------------------------------------------
    final_score = base_score + total_modifier
    final_score = min(100.0, max(0.0, final_score))

    # Apply high-vol regime cap (forces score ≤ 70 → structure must be spreads)
    if regime is not None:
        final_score = apply_high_vol_regime_cap(final_score, regime)

    # Sentiment offline cap: if offline, cap at 70
    if sentiment.get("sentiment_offline", False):
        final_score = min(final_score, sentiment.get("sentiment_offline_cap", 70))

    direction = determine_direction(technical, sentiment)
    meets_threshold = final_score >= CONFIDENCE_THRESHOLD

    return {
        # Technical sub-scores
        "breakout_score": tech_sub["breakout_score"],
        "trend_score": tech_sub["trend_score"],
        "rs_score": tech_sub["rs_score"],
        "rsi_score": tech_sub["rsi_score"],
        "volume_profile_score": tech_sub["volume_profile_score"],
        "technical_total": round(technical_total, 2),

        # Sentiment sub-scores
        "trajectory_score": float(sentiment.get("trajectory_score", 0.0)),
        "velocity_score": float(sentiment.get("velocity_score", 0.0)),
        "cross_platform_score": float(sentiment.get("cross_platform_score", 0.0)),
        "spike_score": float(sentiment.get("spike_score", 0.0)),
        "sentiment_total": round(sentiment_total, 2),

        # News sub-scores
        "credibility_score": float(news.get("credibility_weighted_score", 0.0)),
        "theme_score": float(news.get("theme_alignment_score", 0.0)),
        "clustering_score": float(news.get("clustering_score", 0.0)),
        "decay_score": float(news.get("decay_score", 0.0)),
        "news_total": round(news_total, 2),

        # Fundamental sub-scores
        "fundamental_score": round(fundamental_score_raw, 2),
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
        "insider_modifier": ins_mod,
        "seasonality_modifier": seas_mod,
        "macro_modifier": mac_mod,
        "total_modifier": round(total_modifier, 2),
        "final_score": round(final_score, 2),
        "direction": direction,
        "meets_threshold": meets_threshold,
    }


def compute_technical_sub_scores(
    technical: dict,
    cfg: Optional[dict] = None,
    volume_profile_score_override: Optional[float] = None,
) -> dict:
    """
    Map raw technical indicator values to 0-10 sub-scores.

    5 sub-signals × 10 points max = 50 total (updated from 5×12=60):
    - breakout_score:       volume z-score × 10 (clamped 0-10)
    - trend_score:          MA alignment + price positioning (0-10)
    - rs_score:             RS vs. SMH z-score (0-10)
    - rsi_score:            RSI position mapping (0-10)
    - volume_profile_score: supplied from volume_profile.py (0-10)
    """
    if cfg is None:
        cfg = {}

    # ---------------------------------------------------------------------------
    # Breakout score (0-10): volume z-score signals unusual activity at breakout
    # Clamp z-score to [-3, +3] range, then scale to 0-10
    # z=0 (average volume) → 5; z=+2 (strong breakout volume) → 8.3; z=+3 → 10
    # ---------------------------------------------------------------------------
    vol_z = float(technical.get("breakout_volume_zscore", 0.0))
    vol_z_clamp = max(-3.0, min(3.0, vol_z))
    breakout_raw = 5.0 + vol_z_clamp * (5.0 / 3.0)  # z=0→5, z=+3→10, z=-3→0
    breakout_confirmed = bool(technical.get("breakout_confirmed", False))
    if not breakout_confirmed:
        breakout_raw = min(breakout_raw, 5.0)  # Cap at neutral if no breakout
    breakout_score = round(max(0.0, min(10.0, breakout_raw)), 2)

    # ---------------------------------------------------------------------------
    # Trend score (0-10): 3-tier scoring (scaled from 0-12 to 0-10)
    #   sma20 > sma50 AND close > sma50 AND MACD bullish → 10
    #   sma20 > sma50 AND close > sma50 → 7.5
    #   close > sma50 only → 4
    #   close < sma50 → 1.5
    # ---------------------------------------------------------------------------
    trend_intact = bool(technical.get("trend_intact", False))
    sma20_above_50 = bool(technical.get("sma_20_above_sma_50", False))
    price_above_50 = bool(technical.get("price_above_sma_50", False))
    macd_bullish = bool(technical.get("macd_bullish", False))

    if trend_intact and macd_bullish:
        trend_score = 10.0
    elif trend_intact:
        trend_score = 7.5
    elif sma20_above_50 and price_above_50:
        trend_score = 5.8
    elif price_above_50:
        trend_score = 4.0
    else:
        trend_score = 1.5
    trend_score = round(trend_score, 2)

    # ---------------------------------------------------------------------------
    # RS score (0-10): RS z-score maps relative strength vs. SMH
    # rs_z=+3 → 10 (strongly outperforming), rs_z=-3 → 0 (underperforming)
    # ---------------------------------------------------------------------------
    rs_z = float(technical.get("rs_zscore", 0.0))
    rs_z_clamp = max(-3.0, min(3.0, rs_z))
    rs_score = round(max(0.0, min(10.0, 5.0 + rs_z_clamp * (5.0 / 3.0))), 2)

    # ---------------------------------------------------------------------------
    # RSI score (0-10): RSI position mapping (scaled from 0-12 to 0-10)
    # ---------------------------------------------------------------------------
    rsi_val = float(technical.get("rsi_14", 50.0))
    if 55 <= rsi_val <= 65:
        rsi_score = 10.0
    elif 50 <= rsi_val < 55:
        rsi_score = 7.5
    elif 65 < rsi_val <= 72:
        rsi_score = 5.8
    elif 72 < rsi_val <= 80:
        rsi_score = 4.2
    elif rsi_val > 80:
        rsi_score = 1.7
    elif 45 <= rsi_val < 50:
        rsi_score = 5.0
    elif 35 <= rsi_val < 45:
        rsi_score = 2.5
    else:
        rsi_score = 0.8
    rsi_score = round(rsi_score, 2)

    # ---------------------------------------------------------------------------
    # Volume profile score (0-10): supplied by volume_profile.py, or neutral=5
    # ---------------------------------------------------------------------------
    if volume_profile_score_override is not None:
        vp_score = round(max(0.0, min(10.0, float(volume_profile_score_override))), 2)
    else:
        vp_score = float(technical.get("volume_profile_score", 5.0))
        vp_score = round(max(0.0, min(10.0, vp_score)), 2)

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
