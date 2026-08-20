"""
Detects sector-wide moves vs. genuine individual divergence across the 6-ticker watchlist.
Prevents over-trading correlated names. Ensures confidence scores reflect stock-specific
evidence rather than just sector tailwinds.
Modifier bounds per spec: -10 to +5.
"""

from typing import Optional

import pandas as pd

CORRELATION_SECTOR_WIDE = "sector_wide"
CORRELATION_NEUTRAL = "neutral"
CORRELATION_INDIVIDUAL_DIVERGENCE = "individual_divergence"

# Fallback divergence bar for a ticker whose own volatility can't be
# estimated (insufficient OHLCV history) — the original fixed value, kept as
# a floor/fallback rather than removed outright.
_DEFAULT_DIVERGENCE_THRESHOLD = 0.03
# A move needs to be at least this many multiples of a ticker's own typical
# 5-day swing to count as genuine individual divergence, not routine noise.
_DIVERGENCE_VOLATILITY_MULTIPLIER = 1.5
_DIVERGENCE_MIN_VOL_HISTORY_DAYS = 21


def _estimate_five_day_volatility(df: Optional[pd.DataFrame]) -> Optional[float]:
    """
    Estimate a ticker's typical 5-day return magnitude from its own trailing
    daily volatility (std of daily % changes over the last 20 days), scaled
    by sqrt(5) — the standard random-walk approximation for how single-day
    variance compounds over a 5-day window.

    A fixed 3% divergence bar treats a volatile semiconductor name (which can
    routinely move 3%+ in 5 days) the same as a much calmer one — over-firing
    "individual divergence" on the volatile name's routine noise while under-
    detecting genuine divergence on the calmer one. Returns None (caller
    falls back to _DEFAULT_DIVERGENCE_THRESHOLD) when there isn't enough
    history to estimate volatility from.
    """
    if df is None or len(df) < _DIVERGENCE_MIN_VOL_HISTORY_DAYS:
        return None
    daily_returns = df["Close"].pct_change().dropna().iloc[-20:]
    if len(daily_returns) < 20:
        return None
    daily_std = float(daily_returns.std())
    if daily_std != daily_std:  # NaN guard (e.g. a constant price series)
        return None
    return daily_std * (5.0 ** 0.5)

# NOTE: the "max 1 position from a correlated pair/group" rule is enforced
# by swing_model/portfolio_manager.py's can_open_new_position(), driven by
# config/swing_config.yaml's portfolio.sectors.<name>.correlated_groups —
# a real, sector-scoped, actively-used implementation. A duplicate
# _CORRELATED_PAIRS = [("NVDA", "AMD")] constant used to live here,
# unreferenced anywhere in this file or the rest of the codebase — leftover
# from before portfolio_manager.py's more complete version existed.


def analyze_cross_ticker(
    ticker_scores: dict[str, dict],
    ohlcv_data: dict[str, pd.DataFrame],
    cfg: Optional[dict] = None,
) -> dict[str, dict]:
    """
    Run cross-ticker correlation analysis for all watchlist tickers.

    For each ticker, determines whether its signal reflects a sector-wide move
    or genuine individual divergence, and applies the appropriate modifier.

    Returns dict: ticker → {
        correlation_state, confidence_modifier, sector_signal_count, divergence_direction
    }
    """
    if cfg is None:
        cfg = {}

    tickers = list(ticker_scores.keys())
    if not tickers:
        return {}

    # Compute 5-day returns for all tickers
    ticker_returns: dict[str, float] = {}
    for ticker in tickers:
        df = ohlcv_data.get(ticker)
        if df is not None and len(df) >= 6:
            ret = float(df["Close"].iloc[-1] / df["Close"].iloc[-6] - 1)
            ticker_returns[ticker] = ret
        else:
            ticker_returns[ticker] = 0.0

    # Determine signal directions from indicator data (trend_intact + breakout)
    signal_directions: dict[str, Optional[str]] = {}
    for ticker, ind in ticker_scores.items():
        if ind is None:
            signal_directions[ticker] = None
            continue
        trend = ind.get("trend_intact", False)
        breakout = ind.get("breakout_confirmed", False)
        if trend and breakout:
            signal_directions[ticker] = "bullish"
        elif not trend:
            signal_directions[ticker] = "bearish"
        else:
            signal_directions[ticker] = None

    # Per-ticker divergence bar, scaled to each ticker's own typical 5-day
    # move — see _estimate_five_day_volatility. Falls back to the fixed
    # _DEFAULT_DIVERGENCE_THRESHOLD for a ticker whose own volatility can't
    # be estimated yet (insufficient OHLCV history).
    divergence_thresholds: dict[str, float] = {}
    for ticker in tickers:
        vol = _estimate_five_day_volatility(ohlcv_data.get(ticker))
        divergence_thresholds[ticker] = (
            max(vol * _DIVERGENCE_VOLATILITY_MULTIPLIER, _DEFAULT_DIVERGENCE_THRESHOLD * 0.5)
            if vol is not None else _DEFAULT_DIVERGENCE_THRESHOLD
        )

    correlation_state = compute_sector_correlation_state(
        ticker_returns, signal_directions, divergence_thresholds=divergence_thresholds
    )

    results: dict[str, dict] = {}
    for ticker in tickers:
        ticker_ret = ticker_returns.get(ticker, 0.0)
        peer_returns = [v for t, v in ticker_returns.items() if t != ticker]
        peer_avg = sum(peer_returns) / len(peer_returns) if peer_returns else 0.0

        divergence_direction = None
        if abs(ticker_ret - peer_avg) > divergence_thresholds[ticker]:
            divergence_direction = "outperforming" if ticker_ret > peer_avg else "underperforming"

        # Sector-wide → reduce confidence (sector tailwind, not stock-specific).
        # Deliberately dampened to 0 by default (see swing_config.yaml comment):
        # regime and sector_rotation modifiers are both already derived from the
        # same SMH price action that drives this sector-wide state, so applying
        # a third penalty here would triple-count one underlying signal.
        # Individual divergence + outperforming → increase confidence
        if correlation_state == CORRELATION_SECTOR_WIDE:
            modifier = _get_modifier(cfg, "sector_wide_discount", -5.0)
        elif correlation_state == CORRELATION_INDIVIDUAL_DIVERGENCE and divergence_direction == "outperforming":
            modifier = _get_modifier(cfg, "divergence_boost", 5.0)
        elif correlation_state == CORRELATION_INDIVIDUAL_DIVERGENCE and divergence_direction == "underperforming":
            modifier = _get_modifier(cfg, "underperforming", -10.0)
        else:
            modifier = 0.0

        # Clamp to spec bounds [-10, +5]
        modifier = max(-10.0, min(5.0, modifier))

        bull_count = sum(1 for d in signal_directions.values() if d == "bullish")
        bear_count = sum(1 for d in signal_directions.values() if d == "bearish")
        sector_signal_count = max(bull_count, bear_count)

        results[ticker] = {
            "correlation_state": correlation_state,
            "confidence_modifier": modifier,
            "sector_signal_count": sector_signal_count,
            "divergence_direction": divergence_direction,
            "ticker_5d_return": round(ticker_ret, 4),
            "peer_avg_5d_return": round(peer_avg, 4),
        }

    return results


def get_cross_ticker_modifier_for_direction(
    result: dict,
    direction: str,
    cfg: Optional[dict] = None,
) -> float:
    """
    Direction-aware cross-ticker modifier.

    analyze_cross_ticker() itself has no notion of a candidate's trade
    direction — its own confidence_modifier field always assumes bullish:
    outperforming peers confirms (divergence_boost, +5), underperforming
    opposes (underperforming penalty, -10). For a bearish candidate the
    confirming condition is the mirror — a stock declining faster than its
    peers is what confirms a short thesis, and outperformance opposes it —
    so which value each divergence_direction maps to is swapped, not just
    sign-negated (the two magnitudes aren't symmetric). correlation_state ==
    CORRELATION_SECTOR_WIDE's discount is direction-neutral (a sector-wide
    tailwind dilutes stock-specific evidence regardless of which way the
    trade points) and unaffected.

    Call this instead of reading result["confidence_modifier"] directly once
    the candidate's real trade direction is known — previously every live
    bearish candidate got the bullish-shaped mapping applied unmodified
    (Signal Integrity Audit follow-up finding: analyze_cross_ticker was not
    among the 4 components already fixed for direction-mirroring on
    2026-08-19, since it has no direction parameter at all to begin with).

    result: one ticker's entry from analyze_cross_ticker()'s return dict —
    needs "correlation_state" and "divergence_direction".
    """
    if cfg is None:
        cfg = {}
    if direction != "bearish":
        return float(result.get("confidence_modifier", 0.0))

    correlation_state = result.get("correlation_state")
    divergence_direction = result.get("divergence_direction")

    if correlation_state == CORRELATION_SECTOR_WIDE:
        modifier = _get_modifier(cfg, "sector_wide_discount", -5.0)
    elif correlation_state == CORRELATION_INDIVIDUAL_DIVERGENCE and divergence_direction == "underperforming":
        modifier = _get_modifier(cfg, "divergence_boost", 5.0)
    elif correlation_state == CORRELATION_INDIVIDUAL_DIVERGENCE and divergence_direction == "outperforming":
        modifier = _get_modifier(cfg, "underperforming", -10.0)
    else:
        modifier = 0.0

    return max(-10.0, min(5.0, modifier))


def compute_sector_correlation_state(
    ticker_returns: dict[str, float],
    signal_directions: dict[str, Optional[str]],
    divergence_threshold: float = 0.03,
    divergence_thresholds: Optional[dict[str, float]] = None,
) -> str:
    """
    Determine if current multi-ticker signals represent a sector-wide move.

    sector_wide: 3+ tickers signaling bullish or bearish simultaneously.
    individual_divergence: 1 ticker moving distinctly from peers (more than
    its own divergence bar away from the peer average).
    neutral: mixed or no clear pattern.

    divergence_thresholds: optional per-ticker bar (see analyze_cross_ticker's
    _estimate_five_day_volatility) — a volatile name and a calm one shouldn't
    share one fixed percentage. Falls back to the flat divergence_threshold
    (default 0.03, the original fixed value) for any ticker not present in
    the dict, or when divergence_thresholds itself isn't supplied at all —
    callers with only returns/directions (no OHLCV history to estimate
    volatility from) keep the original behavior unchanged.
    """
    if not signal_directions:
        return CORRELATION_NEUTRAL

    bull_count = sum(1 for d in signal_directions.values() if d == "bullish")
    bear_count = sum(1 for d in signal_directions.values() if d == "bearish")

    if bull_count >= 3 or bear_count >= 3:
        return CORRELATION_SECTOR_WIDE

    # Check for individual divergence: one ticker's return >> peer average
    if ticker_returns:
        returns = list(ticker_returns.values())
        avg_ret = sum(returns) / len(returns)
        for ticker, ret in ticker_returns.items():
            threshold = (divergence_thresholds or {}).get(ticker, divergence_threshold)
            if abs(ret - avg_ret) > threshold:
                return CORRELATION_INDIVIDUAL_DIVERGENCE

    return CORRELATION_NEUTRAL


def _get_modifier(cfg: dict, state_key: str, default: float) -> float:
    """Read modifier from cfg or return default."""
    m = cfg.get("modifiers", {}).get("cross_ticker", {})
    return float(m.get(state_key, default))
