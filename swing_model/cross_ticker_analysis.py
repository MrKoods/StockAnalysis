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

_CORRELATED_PAIRS = [("NVDA", "AMD")]  # Per spec: max 1 from this pair


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

    correlation_state = compute_sector_correlation_state(ticker_returns, signal_directions)

    results: dict[str, dict] = {}
    for ticker in tickers:
        ticker_ret = ticker_returns.get(ticker, 0.0)
        peer_returns = [v for t, v in ticker_returns.items() if t != ticker]
        peer_avg = sum(peer_returns) / len(peer_returns) if peer_returns else 0.0

        divergence_direction = None
        if abs(ticker_ret - peer_avg) > 0.03:
            divergence_direction = "outperforming" if ticker_ret > peer_avg else "underperforming"

        # Sector-wide → reduce confidence (sector tailwind, not stock-specific)
        # Individual divergence + outperforming → increase confidence
        if correlation_state == CORRELATION_SECTOR_WIDE:
            modifier = _get_modifier(cfg, "sector_wide", -5.0)
        elif correlation_state == CORRELATION_INDIVIDUAL_DIVERGENCE and divergence_direction == "outperforming":
            modifier = _get_modifier(cfg, "individual_divergence", 5.0)
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


def compute_sector_correlation_state(
    ticker_returns: dict[str, float],
    signal_directions: dict[str, Optional[str]],
    divergence_threshold: float = 0.03,
) -> str:
    """
    Determine if current multi-ticker signals represent a sector-wide move.

    sector_wide: 3+ tickers signaling bullish or bearish simultaneously.
    individual_divergence: 1 ticker moving distinctly from peers (>3% divergence from avg).
    neutral: mixed or no clear pattern.
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
            if abs(ret - avg_ret) > divergence_threshold:
                return CORRELATION_INDIVIDUAL_DIVERGENCE

    return CORRELATION_NEUTRAL


def _get_modifier(cfg: dict, state_key: str, default: float) -> float:
    """Read modifier from cfg or return default."""
    m = cfg.get("modifiers", {}).get("cross_ticker", {})
    return float(m.get(state_key, default))
