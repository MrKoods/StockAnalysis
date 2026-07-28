"""
EV-based trade ranker — evaluates all 42 trade structures simultaneously.
Runs standard EV formula for simple structures; full P&L surface for complex ones.

Filters (applied before ranking):
1. Undefined risk: exclude at $15k unless account > $50k + Level 3
2. Capital: max 5% of account = $750 at $15k
3. R:R: ≥ configured min_rr_ratio (default 1:3), evaluated on the shared
   entry/stop/target setup — same for every structure since it doesn't depend
   on per-structure option pricing.
4. Greeks: applied when a real option chain is supplied (`option_chain` param,
   from positioning_client.py's fetch_option_chain_metrics) AND the structure
   has a resolvable options-only leg composition — see _GREEKS_RESOLVABLE_LEGS.
   Real strikes are picked from the chain (options_math.py's
   select_directional_leg_strike, a fixed strike-offset convention, not
   iterative delta-solving) and net theta/vega computed (net_structure_greeks)
   against config-driven bounds (swing_config.yaml's greeks_filter block).
   Structures needing multiple expirations (calendars/diagonals), margin-based
   synthetics, or 3+ leg wing structures (condors/butterflies/ratio spreads)
   are deliberately left un-filtered — modeling their legs from one fetched
   expiration and a fixed offset convention would misrepresent their actual
   risk rather than measure it. `greeks_filter_status` in the result reports
   which applied. No `option_chain` supplied at all → same as before this
   filter existed, reported as 'not_implemented_no_options_chain_data'.
5. Liquidity: excluded when the slippage cost (half the bid/ask spread × legs ×
   100, per adjust_ev_for_slippage) consumes >=50% of the structure's raw EV —
   i.e., a wide bid/ask is eating most of the edge the R:R filter is meant to protect.
   `bid_ask_spreads` is now populated from the real chain when not explicitly
   passed by the caller (previously always empty in production, making this
   filter inert — see CHANGELOG v2.2.22).
6. Account type: options approval level from swing_config.yaml
7. Direction: exclude misaligned structures
8. 0DTE: always excluded (also enforced upstream — fetch_option_chain_metrics'
   min_dte skips 0DTE/weekly expirations before a chain ever reaches here)
"""

from typing import Optional

from shared.utils.options_math import (
    STRUCTURE_MULTIPLIERS,
    compute_ev_simple,
    compute_ev_surface,
    adjust_ev_for_slippage,
    capital_efficiency_score,
    select_directional_leg_strike,
    net_structure_greeks,
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

# Structures with a real, single-expiration, options-only (or options-leg-of-a-
# mixed-structure) composition — Filter 4 (Greeks) is applied to these when a
# real option_chain is supplied. Stock legs of mixed structures (covered_call,
# protective_put, married_put, collar, covered_strangle) are omitted here since
# stock contributes zero gamma/theta/vega and a constant delta — irrelevant to
# the theta/vega bounds this filter checks. Deliberately excludes: LEAPS (needs
# a long-dated expiry our single near-term chain fetch doesn't provide — using
# near-term theta/vega for a LEAPS position would misrepresent it, not measure
# it), calendars/diagonals (need two expirations), pure equity structures (no
# options legs), and 3+ leg / synthetic / ratio structures (see module docstring).
# Each value: list of (option_type, side, moneyness) — moneyness keys defined in
# shared/utils/options_math.py's select_directional_leg_strike.
_GREEKS_RESOLVABLE_LEGS: dict = {
    "long_call": [("call", "long", "atm")],
    "long_put": [("put", "long", "atm")],
    "deep_itm_call": [("call", "long", "deep_itm")],
    "deep_itm_put": [("put", "long", "deep_itm")],
    "naked_short_call": [("call", "short", "otm")],
    "naked_short_put": [("put", "short", "otm")],
    "cash_secured_put": [("put", "short", "otm")],
    "covered_call": [("call", "short", "otm")],
    "protective_put": [("put", "long", "otm")],
    "married_put": [("put", "long", "otm")],
    "collar": [("put", "long", "otm"), ("call", "short", "otm")],
    "covered_strangle": [("call", "short", "otm"), ("put", "short", "otm")],
    "bull_call_spread": [("call", "long", "atm"), ("call", "short", "far_otm")],
    "bear_put_spread": [("put", "long", "atm"), ("put", "short", "far_otm")],
    "bull_put_spread": [("put", "short", "otm"), ("put", "long", "far_otm")],
    "bear_call_spread": [("call", "short", "otm"), ("call", "long", "far_otm")],
    "long_straddle": [("call", "long", "atm"), ("put", "long", "atm")],
    "long_strangle": [("call", "long", "otm"), ("put", "long", "otm")],
    "short_straddle": [("call", "short", "atm"), ("put", "short", "atm")],
    "short_strangle": [("call", "short", "otm"), ("put", "short", "otm")],
}


def _resolve_structure_legs(
    structure_name: str,
    option_chain: list,
    current_price: float,
) -> Optional[list]:
    """
    Pick real contracts for `structure_name`'s legs from `option_chain` (see
    _GREEKS_RESOLVABLE_LEGS). Returns None if the structure isn't in the
    resolvable set, no chain was supplied, or any required leg has no matching
    contract in the chain (e.g. a thin chain missing a far-OTM strike) — callers
    treat None as "Greeks not evaluated for this structure", never as "passed."
    """
    spec = _GREEKS_RESOLVABLE_LEGS.get(structure_name)
    if not spec or not option_chain or current_price <= 0:
        return None

    legs = []
    for option_type, side, moneyness in spec:
        contract = select_directional_leg_strike(option_chain, current_price, option_type, moneyness)
        if contract is None:
            return None
        legs.append({
            "strike": contract["strike"], "option_type": option_type,
            "side": side, "iv": contract["iv"],
            "bid": contract["bid"], "ask": contract["ask"],
        })
    return legs


def rank_trade_structures(
    candidate: dict,
    account_equity: float,
    options_approval_level: int,
    iv_percentile: float,
    bid_ask_spreads: Optional[dict] = None,
    cfg: Optional[dict] = None,
    option_chain: Optional[list] = None,
    dte: Optional[int] = None,
) -> dict:
    """
    Evaluate all 42 structures and return EV-ranked output.

    candidate: {ticker, direction, confidence, entry, stop, target, atr_14, ...}
    iv_percentile: current IV percentile (0-100) — affects structure preference
    option_chain: real near-the-money contracts from positioning_client.py's
      fetch_option_chain_metrics ('chain' field) — enables Filter 4 (Greeks) for
      structures in _GREEKS_RESOLVABLE_LEGS, and (when bid_ask_spreads isn't
      explicitly supplied) real per-structure bid/ask spreads for Filter 5.
      None (the default) reproduces the prior behavior exactly — both filters
      stay as inert as they were before this parameter existed.
    dte: days to option_chain's expiration — required alongside option_chain for
      Filter 4 to run (Greeks need a real time-to-expiry, not an assumed one).

    Returns:
    {
        ticker, direction, confidence,
        structures_evaluated: 42,
        structures_eligible_after_filters: int,
        ranked_structures: [...],
        exclusion_summary: str,
        greeks_filter_status: "applied" | "not_implemented_no_options_chain_data",
        structures_greeks_evaluated: int,
    }
    """
    if cfg is None:
        cfg = {}
    # Copied, not aliased — real spreads resolved from option_chain below get
    # written into this dict, and a caller-supplied dict shouldn't be mutated
    # as a side effect of calling this function.
    bid_ask_spreads = dict(bid_ask_spreads) if bid_ask_spreads else {}
    greeks_cfg = cfg.get("greeks_filter", {})
    max_daily_theta_pct = float(greeks_cfg.get("max_daily_theta_pct_of_capital", 0.05))
    max_vega_pct = float(greeks_cfg.get("max_vega_pct_of_capital", 0.15))
    greeks_available = bool(option_chain) and dte is not None

    ticker = candidate.get("ticker", "")
    direction = candidate.get("direction", "bullish")
    confidence = float(candidate.get("confidence", 90))
    entry = float(candidate.get("entry", candidate.get("entry_mid", 0.0)))
    stop = float(candidate.get("stop_loss", candidate.get("stop", 0.0)))
    target = float(candidate.get("target", 0.0))

    win_prob = confidence / 100.0
    max_capital = account_equity * 0.05
    force_defined_risk = bool(candidate.get("force_defined_risk", False))

    # Filter 3 input: R:R of the shared entry/stop/target setup. Identical for every
    # structure (none of them change the underlying's own price levels), so it's
    # computed once here rather than per-structure.
    rr = (target - entry) / (entry - stop) if (entry - stop) > 0 else 0.0
    min_rr = float((cfg or {}).get("risk_reward", {}).get("min_rr_ratio", 3.0))

    ranked_structures = []
    excluded = []
    structures_greeks_evaluated = 0

    for name in ALL_42_STRUCTURES:
        structure = STRUCTURE_MULTIPLIERS[name]
        eligible, reasons = _apply_filters(
            name, structure, candidate, account_equity,
            options_approval_level, iv_percentile, max_capital,
            force_defined_risk, cfg, rr, min_rr,
        )
        if not eligible:
            excluded.append({"name": name, "reasons": reasons})
            continue

        # Resolve real legs (if the structure/chain allow it) once per structure —
        # feeds both Filter 5's real bid/ask spread and Filter 4's Greeks check.
        legs = _resolve_structure_legs(name, option_chain, entry) if option_chain else None
        if legs is not None and name not in bid_ask_spreads:
            bid_ask_spreads[name] = sum(c["ask"] - c["bid"] for c in legs) / len(legs)

        ev_result = _compute_structure_ev(name, structure, candidate, iv_percentile / 100.0,
                                          win_prob, bid_ask_spreads.get(name, 0.0))
        if ev_result is None:
            excluded.append({"name": name, "reasons": ["ev_computation_failed"]})
            continue
        ev, ev_raw, ev_adjusted = ev_result

        # Filter 5: Liquidity — a wide bid/ask can consume most of a structure's
        # edge on multi-leg fills. Exclude when slippage eats >=50% of the raw EV
        # (only meaningful when there's actually an edge to protect and spread
        # data was supplied — a missing/zero spread is "unknown", not "tight").
        if ev_raw > 0 and bid_ask_spreads.get(name, 0.0) > 0:
            slippage_fraction = (ev_raw - ev_adjusted) / ev_raw
            if slippage_fraction >= 0.50:
                excluded.append({"name": name, "reasons": ["wide_bid_ask_liquidity"]})
                continue

        # Estimate capital required (simplified — contract-level sizing not available here)
        est_capital = _estimate_capital_required(name, structure, entry, stop, target)
        if est_capital > max_capital:
            excluded.append({"name": name, "reasons": ["capital_exceeds_5pct"]})
            continue

        # Filter 4: Greeks — theta/vega bounded as a % of this structure's own
        # capital-at-risk, so a small defined-risk spread and a large one are held
        # to the same relative standard rather than the same dollar one.
        greeks_detail = None
        if legs is not None and greeks_available:
            T = max(dte, 1) / 365.0
            net = net_structure_greeks(legs, S=entry, T=T)["net"]
            # compute_greeks returns per-share values; x100 for the contract multiplier
            # to match est_capital's already-per-contract dollar units.
            daily_theta_pct = abs(net["theta"]) * 100 / est_capital if est_capital > 0 else 0.0
            vega_pct = abs(net["vega"]) * 100 / est_capital if est_capital > 0 else 0.0
            structures_greeks_evaluated += 1
            if daily_theta_pct > max_daily_theta_pct:
                excluded.append({"name": name, "reasons": ["greeks_theta_exceeds_bound"]})
                continue
            if vega_pct > max_vega_pct:
                excluded.append({"name": name, "reasons": ["greeks_vega_exceeds_bound"]})
                continue
            greeks_detail = {
                "net_greeks": net,
                "daily_theta_pct_of_capital": round(daily_theta_pct, 4),
                "vega_pct_of_capital": round(vega_pct, 4),
            }

        ev_per_dollar = capital_efficiency_score(ev, est_capital, max_capital)

        ranked_structures.append({
            "name": name,
            "ev_per_dollar_risked": round(ev_per_dollar, 4),
            "ev": round(ev, 4),
            "capital_required": round(est_capital, 2),
            "rr_ratio": round(rr, 2),
            "legs": structure.get("legs", 1),
            "greeks": greeks_detail,
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
        # "applied": a real option_chain + dte were supplied, so Filter 4 ran for
        # every structure in _GREEKS_RESOLVABLE_LEGS (see structures_greeks_evaluated
        # for how many actually had a usable chain match — 0 is possible on a thin
        # chain and is still an honest "applied," not a failure).
        # "not_implemented_no_options_chain_data": no chain/dte supplied at all —
        # identical to this filter's behavior before it existed.
        "greeks_filter_status": "applied" if greeks_available else "not_implemented_no_options_chain_data",
        "structures_greeks_evaluated": structures_greeks_evaluated,
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
    rr: float = 0.0,
    min_rr: float = 3.0,
) -> tuple[bool, list[str]]:
    """
    Apply filters 1-3/6-8 to a structure. Filters 4 (Greeks) and 5 (liquidity)
    are applied separately in rank_trade_structures' main loop — both need
    values (resolved legs, EV) that aren't available until after this function
    runs, same reason Filter 5 was already handled outside it. Returns
    (is_eligible, exclusion_reasons).
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

    # Filter 3: R:R — the underlying entry/stop/target setup must clear the
    # configured minimum (default 1:3) before any structure is even considered.
    if rr < min_rr:
        reasons.append("rr_below_min_threshold")

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
) -> Optional[tuple[float, float, float]]:
    """
    Compute EV for a structure. Uses surface method for complex structures.
    Returns (ev_per_dollar_risked, ev_raw, ev_adjusted) or None if insufficient data.
    ev_raw/ev_adjusted (pre/post slippage) let the liquidity filter (filter 5)
    measure how much of the edge a wide bid/ask consumes.
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
    return ev_adjusted / capital, ev, ev_adjusted


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
