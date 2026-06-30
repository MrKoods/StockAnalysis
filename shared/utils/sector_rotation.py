"""
SHARED: Tracks SMH vs. SPY flows across 5/20/60-day windows.
Outputs rotation state (inflow/neutral/outflow) + confidence modifier.
Semiconductor outflow → all ticker confidence scores reduced by up to -15 points.
"""

from typing import Optional

import pandas as pd

ROTATION_INFLOW = "inflow"
ROTATION_NEUTRAL = "neutral"
ROTATION_OUTFLOW = "outflow"


def compute_rotation_state(
    smh_close: pd.Series,
    spy_close: pd.Series,
    windows: list[int] = [5, 20, 60],
) -> dict:
    """
    Compute sector rotation state for semiconductors vs. broad market.

    Compares SMH return vs. SPY return over each window.
    Positive relative return = inflow (semis outperforming).
    Negative relative return = outflow.

    Aggregation: if 2+ of 3 windows show outflow → outflow state;
    if 2+ show inflow → inflow state; otherwise neutral.

    Returns dict:
    {
        rotation_state, smh_vs_spy_5d, smh_vs_spy_20d, smh_vs_spy_60d,
        confidence_modifier
    }
    """
    relative: dict[int, float] = {}
    for w in windows:
        if len(smh_close) < w + 1 or len(spy_close) < w + 1:
            relative[w] = 0.0
            continue
        smh_ret = (smh_close.iloc[-1] / smh_close.iloc[-(w + 1)] - 1)
        spy_ret = (spy_close.iloc[-1] / spy_close.iloc[-(w + 1)] - 1)
        relative[w] = float(smh_ret - spy_ret)

    outflow_count = sum(1 for v in relative.values() if v < -0.02)
    inflow_count = sum(1 for v in relative.values() if v > 0.02)

    if outflow_count >= 2:
        state = ROTATION_OUTFLOW
    elif inflow_count >= 2:
        state = ROTATION_INFLOW
    else:
        state = ROTATION_NEUTRAL

    return {
        "rotation_state": state,
        "smh_vs_spy_5d": relative.get(5, 0.0),
        "smh_vs_spy_20d": relative.get(20, 0.0),
        "smh_vs_spy_60d": relative.get(60, 0.0),
        "confidence_modifier": _rotation_modifier(state),
    }


def _rotation_modifier(state: str) -> float:
    """Map rotation state to confidence modifier (-15 / 0 / +5)."""
    return {ROTATION_OUTFLOW: -15.0, ROTATION_NEUTRAL: 0.0, ROTATION_INFLOW: 5.0}.get(state, 0.0)


def get_rotation_modifier(rotation_state: str, cfg: dict) -> float:
    """
    Map rotation state to confidence modifier using cfg values.
    Falls back to hardcoded defaults if cfg is missing.
    """
    m = cfg.get("modifiers", {}).get("sector_rotation", {})
    if rotation_state == ROTATION_OUTFLOW:
        return float(m.get("outflow_penalty", -15))
    if rotation_state == ROTATION_INFLOW:
        return float(m.get("inflow_boost", 5))
    return 0.0
