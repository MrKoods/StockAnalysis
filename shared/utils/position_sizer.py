"""
SHARED: Calculates trade size based on account equity, confidence tier,
circuit breaker state, and structure capital requirement.
Position sizing: confidence-scaled fixed fractional (1.0-2.5% risk per tier).
Max capital per trade: 5% of account equity ($750 at $15k).
"""

from typing import Optional


SIZING_TIERS = [
    (90, 92, 0.010),   # 1.0% risk
    (93, 95, 0.015),   # 1.5% risk
    (96, 98, 0.020),   # 2.0% risk
    (99, 100, 0.025),  # 2.5% risk
]

CB_NORMAL = "normal"
CB_YELLOW = "yellow"
CB_ORANGE = "orange"
CB_RED = "red"


def get_risk_pct(confidence_score: float) -> float:
    """
    Return risk % for the given confidence score tier.
    90-92 → 1.0%; 93-95 → 1.5%; 96-98 → 2.0%; 99-100 → 2.5%.
    Returns 0.0 if score below 90 (no trade should be surfaced).
    """
    score = int(confidence_score)
    for lo, hi, pct in SIZING_TIERS:
        if lo <= score <= hi:
            return pct
    return 0.0


def compute_position_size(
    confidence_score: float,
    account_equity: float,
    circuit_breaker_state: str,
    capital_required: float,
    max_capital_pct: float = 0.05,
    cfg: Optional[dict] = None,
) -> dict:
    """
    Compute final position sizing for a trade recommendation.

    Returns dict:
    {
        risk_pct, dollar_risk, circuit_breaker_state, size_multiplier,
        capital_required, capital_approved, max_capital, contracts_or_shares
    }
    """
    if cfg is None:
        cfg = {}

    base_risk_pct = get_risk_pct(confidence_score)
    adjusted_risk_pct, size_multiplier = apply_circuit_breaker_sizing(
        base_risk_pct, circuit_breaker_state, cfg
    )

    dollar_risk = adjusted_risk_pct * account_equity
    max_capital = max_capital_pct * account_equity
    capital_approved = capital_required <= max_capital

    # Zero out risk_pct/dollar_risk when the 5% cap is exceeded rather than
    # returning full sizing and relying on every caller to remember to check
    # capital_approved before acting on it — trade_selector.py already hard-excludes
    # over-capital structures at the ranking stage; this keeps the same cap
    # structurally enforced here too, not just advisory.
    if not capital_approved:
        adjusted_risk_pct = 0.0
        dollar_risk = 0.0

    return {
        "risk_pct": round(adjusted_risk_pct, 4),
        "dollar_risk": round(dollar_risk, 2),
        "circuit_breaker_state": circuit_breaker_state,
        "size_multiplier": size_multiplier,
        "capital_required": round(capital_required, 2),
        "capital_approved": capital_approved,
        "max_capital": round(max_capital, 2),
        "contracts_or_shares": "compute at execution time using dollar_risk / risk_per_unit",
    }


def apply_circuit_breaker_sizing(
    base_risk_pct: float,
    circuit_breaker_state: str,
    cfg: Optional[dict] = None,
) -> tuple[float, float]:
    """
    Apply circuit breaker reduction to base risk %.
    Normal:  × 1.0 (no change)
    Yellow:  × 0.5 (half size)
    Orange:  × 0.0 (no new positions)
    Red:     × 0.0 (full stop — no new positions)
    Returns (adjusted_risk_pct, size_multiplier).
    """
    if cfg is None:
        cfg = {}
    cb_cfg = cfg.get("circuit_breakers", {})

    if circuit_breaker_state == CB_YELLOW:
        mult = float(cb_cfg.get("yellow", {}).get("position_size_multiplier", 0.5))
    elif circuit_breaker_state in (CB_ORANGE, CB_RED):
        mult = 0.0
    else:
        mult = 1.0

    return round(base_risk_pct * mult, 4), mult
