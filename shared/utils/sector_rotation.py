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
    windows: Optional[list[int]] = None,
    cfg: Optional[dict] = None,
) -> dict:
    """
    Compute sector rotation state for semiconductors vs. broad market.

    Compares SMH return vs. SPY return over each window.
    Positive relative return = inflow (semis outperforming).
    Negative relative return = outflow.

    Aggregation: if 2+ of 3 windows show outflow → outflow state;
    if 2+ show inflow → inflow state; otherwise neutral.

    cfg: when supplied, confidence_modifier is computed via
    get_rotation_modifier(state, cfg) — the config-driven path — instead of
    the hardcoded _rotation_modifier() default. Matters in practice: this
    project's own backtest calibration (CHANGELOG v2.2.47, 544 pooled
    outcomes) found the old +5 inflow_boost was backwards — inflow trades
    won 53.9% (n=358) vs. 63.7% for neutral — and config/swing_config.yaml's
    modifiers.sector_rotation.inflow_boost was deliberately changed to 0.
    Without cfg threaded through here, that recalibration never reaches live
    scoring or backtest replay — every caller kept silently applying the
    old, empirically-refuted +5.0 regardless of what config said. None (the
    default) preserves the old hardcoded behavior for any caller that
    doesn't pass cfg.

    Returns dict:
    {
        rotation_state, smh_vs_spy_5d, smh_vs_spy_20d, smh_vs_spy_60d,
        confidence_modifier
    }
    """
    if windows is None:
        windows = [5, 20, 60]
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
        "confidence_modifier": get_rotation_modifier(state, cfg) if cfg is not None else _rotation_modifier(state),
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


def dampen_rotation_penalty_for_leader(base_modifier: float, rs_zscore: float) -> float:
    """
    Soften the sector-wide outflow penalty for an individual ticker with strong
    relative strength vs. its own history.

    rotation_state (this sector's SMH/KRE/XLV-vs-SPY flow) and rs_zscore (this
    stock vs. its own trailing relative-strength history) measure different
    things — a genuine sector leader can keep outperforming its own history
    even while the sector as a whole is in outflow. Applying the full sector
    penalty uniformly to every ticker in the sector, leaders and laggards
    alike, throws away that distinction. Only softens negative modifiers
    (outflow's -15) — never touches a neutral or positive one — and caps the
    reduction at 50%: a leader in a declining sector still carries real
    correlated risk, this tempers the penalty, it doesn't cancel it.

    rs_zscore >= 1.5 (a real, statistically notable outperformance) starts the
    dampening; it scales linearly to the full 50% cap by rs_zscore >= 3.0.
    """
    if base_modifier >= 0.0 or rs_zscore < 1.5:
        return base_modifier
    dampen_fraction = min(1.0, (rs_zscore - 1.5) / 1.5) * 0.5
    return base_modifier * (1.0 - dampen_fraction)
