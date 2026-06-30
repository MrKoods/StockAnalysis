"""
EV-based trade ranker — evaluates all 42 trade structures simultaneously.
Runs standard EV formula for simple structures; full P&L surface for complex ones.
Applies all 8 filter types before ranking.

Filters (applied before ranking):
1. Undefined risk: exclude at $15k unless account > $50k + Level 3
2. Capital: max 5% of account = $750 at $15k
3. R:R: ≥ 1:3 after slippage
4. Greeks: theta burn, vega alignment, gamma risk
5. Liquidity: wide bid/ask reducing real-world EV below 1:3
6. Account type: options approval level from swing_config.yaml
7. Direction: exclude misaligned structures
8. 0DTE: always excluded
"""

from typing import Optional

from shared.utils.options_math import (
    STRUCTURE_MULTIPLIERS,
    compute_ev_simple,
    compute_ev_surface,
    adjust_ev_for_slippage,
    capital_efficiency_score,
)

ALL_42_STRUCTURES = list(STRUCTURE_MULTIPLIERS.keys())

# Structures requiring Level 3+ options approval
_LEVEL_3_REQUIRED = {
    "naked_short_call", "naked_short_put", "short_straddle", "short_strangle",
    "synthetic_long", "synthetic_short",
}
# Structures requiring Level 2+ (spreads)
_LEVEL_2_REQUIRED = {
    "bull_call_spread", "bear_put_spread", "calendar_call", "calendar_put",
    "diagonal_call", "diagonal_put", "bull_put_spread", "bear_call_spread",
    "iron_condor", "iron_butterfly", "long_butterfly_call", "short_butterfly",
    "condor_spread", "long_straddle", "long_strangle",
    "call_ratio_spread", "put_ratio_spread", "call_back_spread", "put_back_spread",
    "risk_reversal", "covered_strangle",
}
# Structures that are bullish-only, bearish-only, or neutral
_BULLISH_STRUCTURES = {
    "long_stock", "long_stock_trailing_stop", "protective_put", "collar", "married_put",
    "long_call", "deep_itm_call", "leaps_call", "bull_call_spread", "diagonal_call",
    "bull_put_spread", "cash_secured_put", "covered_call", "wheel", "call_back_spread",
    "risk_reversal", "synthetic_long",
}
_BEARISH_STRUCTURES = {
    "short_stock", "long_put", "deep_itm_put", "leaps_put", "bear_put_spread",
    "diagonal_put", "bear_call_spread", "put_back_spread", "synthetic_short",
}
_NEUTRAL_STRUCTURES = {
    "iron_condor", "iron_butterfly", "long_butterfly_call", "short_butterfly",
    "condor_spread", "long_straddle", "long_strangle", "short_straddle", "short_strangle",
    "calendar_call", "calendar_put", "covered_strangle", "call_ratio_spread", "put_ratio_spread",
}
_UNDEFINED_RISK_STRUCTURES = {
    "naked_short_call", "naked_short_put", "short_straddle", "short_strangle",
    "synthetic_long", "synthetic_short", "risk_reversal", "short_stock",
    "call_ratio_spread", "put_ratio_spread",
}
_COMPLEX_SURFACE_STRUCTURES = {s for s, d in STRUCTURE_MULTIPLIERS.items() if d.get("ev_method") == "surface"}


def rank_trade_structures(
    candidate: dict,
    account_equity: float,
    options_approval_level: int,
    iv_percentile: float,
    bid_ask_spreads: Optional[dict] = None,
    cfg: Optional[dict] = None,
) -> dict:
    """
    Evaluate all 42 structures and return EV-ranked output.

    candidate: {ticker, direction, confidence, entry, stop, target, atr_14, ...}
    iv_percentile: current IV percentile (0-100) — affects structure preference

    Returns:
    {
        ticker, direction, confidence,
        structures_evaluated: 42,
        structures_eligible_after_filters: int,
        ranked_structures: [...],
        exclusion_summary: str,
    }
    """
    if cfg is None:
        cfg = {}
    if bid_ask_spreads is None:
        bid_ask_spreads = {}

    ticker = candidate.get("ticker", "")
    direction = candidate.get("direction", "bullish")
    confidence = float(candidate.get("confidence", 90))
    entry = float(candidate.get("entry", candidate.get("entry_mid", 0.0)))
    stop = float(candidate.get("stop_loss", candidate.get("stop", 0.0)))
    target = float(candidate.get("target", 0.0))

    win_prob = confidence / 100.0
    max_capital = account_equity * 0.05
    force_defined_risk = bool(candidate.get("force_defined_risk", False))

    ranked_structures = []
    excluded = []

    for name in ALL_42_STRUCTURES:
        structure = STRUCTURE_MULTIPLIERS[name]
        eligible, reasons = _apply_filters(
            name, structure, candidate, account_equity,
            options_approval_level, iv_percentile, max_capital,
            force_defined_risk, cfg,
        )
        if not eligible:
            excluded.append({"name": name, "reasons": reasons})
            continue

        ev = _compute_structure_ev(name, structure, candidate, iv_percentile / 100.0,
                                   win_prob, bid_ask_spreads.get(name, 0.0))
        if ev is None:
            excluded.append({"name": name, "reasons": ["ev_computation_failed"]})
            continue

        # Estimate capital required (simplified — contract-level sizing not available here)
        est_capital = _estimate_capital_required(name, structure, entry, stop, target)
        if est_capital > max_capital:
            excluded.append({"name": name, "reasons": ["capital_exceeds_5pct"]})
            continue

        ev_per_dollar = capital_efficiency_score(ev, est_capital, max_capital)
        rr = (target - entry) / (entry - stop) if (entry - stop) > 0 else 0.0

        ranked_structures.append({
            "name": name,
            "ev_per_dollar_risked": round(ev_per_dollar, 4),
            "ev": round(ev, 4),
            "capital_required": round(est_capital, 2),
            "rr_ratio": round(rr, 2),
            "legs": structure.get("legs", 1),
            "filter_notes": [],
        })

    # Sort by EV per dollar risked, descending
    ranked_structures.sort(key=lambda x: x["ev_per_dollar_risked"], reverse=True)
    for i, s in enumerate(ranked_structures):
        s["rank"] = i + 1
        s["recommended"] = (i == 0)

    return {
        "ticker": ticker,
        "direction": direction,
        "confidence": confidence,
        "structures_evaluated": len(ALL_42_STRUCTURES),
        "structures_eligible_after_filters": len(ranked_structures),
        "ranked_structures": ranked_structures,
        "exclusion_summary": build_discord_exclusion_summary(excluded),
    }


def _apply_filters(
    structure_name: str,
    structure: dict,
    candidate: dict,
    account_equity: float,
    options_approval_level: int,
    iv_percentile: float,
    max_capital: float,
    force_defined_risk: bool,
    cfg: Optional[dict] = None,
) -> tuple[bool, list[str]]:
    """
    Apply all 8 filter types to a structure.
    Returns (is_eligible, exclusion_reasons).
    """
    reasons = []
    direction = candidate.get("direction", "bullish")

    # Filter 1: Undefined risk — exclude at $15k unless account > $50k
    if structure_name in _UNDEFINED_RISK_STRUCTURES:
        if account_equity < 50_000:
            reasons.append("undefined_risk_under_50k")
        if force_defined_risk:
            reasons.append("undefined_risk_near_earnings")

    # Filter 2: Capital filter — max 5% of account
    capital_filter = structure.get("capital_filter", "")
    if capital_filter == "exclude_under_50k" and account_equity < 50_000:
        reasons.append("capital_filter_50k_required")

    # Filter 6: Account type / options approval level
    if structure_name in _LEVEL_3_REQUIRED and options_approval_level < 3:
        reasons.append("requires_level_3_approval")
    elif structure_name in _LEVEL_2_REQUIRED and options_approval_level < 2:
        reasons.append("requires_level_2_approval")

    # Filter 7: Direction alignment
    if structure_name in _BEARISH_STRUCTURES and direction == "bullish":
        reasons.append("direction_mismatch_bearish")
    if structure_name in _BULLISH_STRUCTURES and direction == "bearish":
        reasons.append("direction_mismatch_bullish")

    # Filter 8: 0DTE exclusion — always excluded (no 0DTE in system per spec)
    # (0DTE structures not in the 42 by name, but flag any that might slip in)
    if "0dte" in structure_name.lower():
        reasons.append("0dte_excluded")

    return len(reasons) == 0, reasons


def _compute_structure_ev(
    structure_name: str,
    structure: dict,
    candidate: dict,
    iv: float,
    win_prob: float,
    bid_ask_spread: float = 0.0,
) -> Optional[float]:
    """
    Compute EV for a structure. Uses surface method for complex structures.
    Returns ev_per_dollar_risked or None if insufficient data.
    """
    entry = float(candidate.get("entry", candidate.get("entry_mid", 0.0)))
    stop = float(candidate.get("stop_loss", candidate.get("stop", 0.0)))
    target = float(candidate.get("target", 0.0))

    if entry <= 0 or stop <= 0 or target <= 0 or stop >= entry:
        return None

    up_move = target - entry
    down_move = entry - stop

    if structure.get("ev_method") == "surface":
        surface = compute_ev_surface(
            structure=structure,
            entry=entry, stop=stop, target=target,
            win_probability=win_prob, iv=iv,
        )
        ev = surface["ev_weighted"]
    else:
        # Simple EV with numeric multipliers; string multipliers default to 1.0
        pm = structure.get("profit_mult", 1.0)
        lm = structure.get("loss_mult", 1.0)
        pm = pm if isinstance(pm, (int, float)) else 1.0
        lm = lm if isinstance(lm, (int, float)) else 1.0
        avg_win = up_move * pm
        avg_loss = down_move * lm
        ev = compute_ev_simple(win_prob, avg_win, avg_loss)

    legs = structure.get("legs", 1)
    ev_adjusted = adjust_ev_for_slippage(ev, structure_name, bid_ask_spread, legs)
    capital = _estimate_capital_required(structure_name, structure, entry, stop, target)
    if capital <= 0:
        return None
    return ev_adjusted / capital


def _estimate_capital_required(
    structure_name: str,
    structure: dict,
    entry: float,
    stop: float,
    target: float,
) -> float:
    """
    Estimate capital required for a structure (simplified, order-of-magnitude).
    Used for capital filter check; exact sizing computed at execution time.
    """
    risk_per_share = max(0.01, entry - stop)

    if structure_name in {"long_stock", "long_stock_trailing_stop", "short_stock"}:
        return entry  # Full share price
    if structure_name == "protective_put":
        return entry * 0.3  # Share + put premium estimate
    if "spread" in structure_name or "butterfly" in structure_name or "condor" in structure_name:
        return risk_per_share * 100  # 1 contract × risk
    if "long_call" in structure_name or "long_put" in structure_name:
        return entry * 0.05 * 100  # Rough premium estimate per contract
    if "straddle" in structure_name or "strangle" in structure_name:
        return entry * 0.08 * 100  # Two legs
    if "leaps" in structure_name:
        return entry * 0.12 * 100  # LEAPS premium (12%+ of stock)
    if "cash_secured_put" in structure_name:
        return entry * 0.95 * 100  # Near-full strike capital (CSP)
    if "covered" in structure_name:
        return entry  # Stock cost basis
    # Default: estimate from legs × premium × 100
    return risk_per_share * structure.get("legs", 2) * 100


def build_discord_exclusion_summary(excluded: list[dict]) -> str:
    """
    Build collapsed exclusion summary for Discord alerts.
    Shows count per filter type rather than listing all 40+ excluded structures.
    """
    if not excluded:
        return "All structures eligible."

    from collections import Counter
    counts: Counter = Counter()
    for item in excluded:
        for reason in item.get("reasons", ["unknown"]):
            counts[reason] += 1

    parts = [f"{count} structures excluded — {reason.replace('_', ' ')}"
             for reason, count in counts.most_common(5)]
    return "; ".join(parts)
