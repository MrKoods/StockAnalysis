"""
SHARED: Black-Scholes pricing, Greeks, EV calculation, bid/ask spread adjustment,
capital efficiency scoring.
Handles all 42 trade structures — simple terminal EV for most;
full P&L surface for complex structures (ratio/back spreads, items 36-39).
Standalone module testable with known inputs independent of the rest of the system.
"""

import math
from typing import Optional


# ---------------------------------------------------------------------------
# Black-Scholes core
# ---------------------------------------------------------------------------

def black_scholes_price(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str = "call",
) -> float:
    """
    Black-Scholes option price.
    S: underlying price, K: strike, T: time to expiry (years),
    r: risk-free rate, sigma: implied volatility (annualized).
    Returns 0.0 if T <= 0 or sigma <= 0.

    Note: assumes European exercise and constant IV. Real semiconductor options
    are American-style with volatility skew — always cross-check against market quotes.
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        if option_type == "call":
            return max(0.0, S - K)
        return max(0.0, K - S)

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    if option_type == "call":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    # put via put-call parity
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def compute_greeks(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: str = "call",
) -> dict:
    """
    Compute option Greeks: delta, gamma, theta, vega, rho.
    theta is returned in daily terms (annual theta ÷ 365).
    Returns dict: {delta, gamma, theta, vega, rho}
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}

    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    nd1 = _norm_pdf(d1)
    sqrt_T = math.sqrt(T)
    exp_rT = math.exp(-r * T)

    gamma = nd1 / (S * sigma * sqrt_T)
    vega = S * nd1 * sqrt_T / 100  # per 1% IV move

    if option_type == "call":
        delta = _norm_cdf(d1)
        theta = (-(S * nd1 * sigma) / (2 * sqrt_T) - r * K * exp_rT * _norm_cdf(d2)) / 365
        rho = K * T * exp_rT * _norm_cdf(d2) / 100
    else:
        delta = _norm_cdf(d1) - 1
        theta = (-(S * nd1 * sigma) / (2 * sqrt_T) + r * K * exp_rT * _norm_cdf(-d2)) / 365
        rho = -K * T * exp_rT * _norm_cdf(-d2) / 100

    return {
        "delta": round(delta, 4),
        "gamma": round(gamma, 6),
        "theta": round(theta, 4),
        "vega": round(vega, 4),
        "rho": round(rho, 4),
    }


def _norm_cdf(x: float) -> float:
    """Standard normal CDF using math.erfc for numerical precision."""
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _norm_pdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


# ---------------------------------------------------------------------------
# Real strike selection + net Greeks — trade_selector.py's Filter 4
# ---------------------------------------------------------------------------

_DEFAULT_RISK_FREE_RATE = 0.04  # fixed approximation (~short-term Treasury) —
# Greeks are far less sensitive to r than to strike/IV/DTE for short-dated
# swing-trade structures, so a live rate feed isn't worth the added dependency.

# Magnitude only — direction (ITM vs. OTM side) is resolved separately below,
# since it depends on both moneyness bucket and option_type.
_MONEYNESS_MAGNITUDE = {"atm": 0.0, "otm": 0.06, "far_otm": 0.12, "deep_itm": 0.15}


def select_directional_leg_strike(
    chain: list,
    current_price: float,
    option_type: str,
    moneyness: str = "atm",
) -> Optional[dict]:
    """
    Pick the real contract from `chain` (see positioning_client.py's
    fetch_option_chain_metrics 'chain' field) closest to a target strike for
    one structure leg. Uses a fixed strike-offset convention rather than
    iteratively solving for a target delta — simple and honest about being an
    approximation, not fabricated delta-targeting precision (the project's own
    prior stance on this filter: "rather than fabricate ... from assumed
    strikes/DTE" — this at least uses real, currently-quoted strikes).

    moneyness:
      "atm"       — target strike == current_price
      "otm"       — ~6% out of the money (calls: above current_price;
                    puts: below) — e.g. a single-leg sold option, or the
                    near/short leg of a 2-leg spread
      "far_otm"   — ~12% out of the money, same direction as "otm" — the
                    further, protective/long wing of a 2-leg spread
      "deep_itm"  — ~15% in the money (calls: below current_price;
                    puts: above)

    Returns the chain contract (dict, unmodified) whose strike is closest to
    the target, restricted to `option_type`, or None if `chain` has no
    contracts of that type.
    """
    magnitude = _MONEYNESS_MAGNITUDE.get(moneyness, 0.0)
    if moneyness == "deep_itm":
        # ITM direction is the opposite side of current_price from OTM.
        sign = -1.0 if option_type == "call" else 1.0
    else:
        # atm (magnitude 0 — sign irrelevant), otm, far_otm: OTM direction.
        sign = 1.0 if option_type == "call" else -1.0
    target = current_price * (1 + sign * magnitude)

    candidates = [c for c in (chain or []) if c.get("option_type") == option_type]
    if not candidates:
        return None
    return min(candidates, key=lambda c: abs(c["strike"] - target))


def net_structure_greeks(
    legs: list,
    S: float,
    T: float,
    r: float = _DEFAULT_RISK_FREE_RATE,
) -> dict:
    """
    Sum Greeks across a structure's legs, signed by side.

    legs: list of {strike, option_type, side ("long"|"short"), iv} — as returned
    by select_directional_leg_strike(), with "side" added by the caller.
    T: time to expiry in years, shared across legs (same expiration chain).

    Returns {"net": {delta, gamma, theta, vega, rho}, "legs": [per-leg detail]}.
    """
    net = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    leg_detail = []
    for leg in legs:
        sign = 1.0 if leg.get("side") == "long" else -1.0
        g = compute_greeks(S, leg["strike"], T, r, leg["iv"], leg.get("option_type", "call"))
        for key in net:
            net[key] += sign * g[key]
        leg_detail.append({**leg, "greeks": g})
    return {"net": {k: round(v, 4) for k, v in net.items()}, "legs": leg_detail}


# ---------------------------------------------------------------------------
# EV calculation — simple structures
# ---------------------------------------------------------------------------

def compute_ev_simple(
    win_probability: float,
    average_win: float,
    average_loss: float,
) -> float:
    """
    Core EV formula (exact per scope):
    EV = (win_probability × average_win) - ((1 - win_probability) × average_loss)

    win_probability = confidence_score / 100
    average_win = price_move_to_target × structure_profit_multiplier
    average_loss = price_move_to_stop × structure_loss_multiplier
    """
    loss_probability = 1.0 - win_probability
    return (win_probability * average_win) - (loss_probability * average_loss)


def compute_ev_surface(
    structure: dict,
    entry: float,
    stop: float,
    target: float,
    win_probability: float,
    iv: float,
    r: float = 0.05,
) -> dict:
    """
    Full P&L surface EV for complex structures (ratio spreads, back spreads).
    Estimates P&L across Day 1, 5, 10, 15 × target_hit/flat/stop_hit scenarios.

    For complex structures we model relative price moves:
    - target_hit: price reaches target, option value increases by estimated delta × move
    - flat: price unchanged, theta decay applied
    - stop_hit: price reaches stop, option value decreases

    Returns dict:
    {
        day_1, day_5, day_10, day_15: each {target: pnl, flat: pnl, stop: pnl}
        ev_weighted: float  — probability-weighted EV across all scenarios
    }
    """
    loss_prob = 1.0 - win_probability
    up_move = target - entry
    down_move = entry - stop

    # Approximate theta decay per structure — 3 legs typical for ratio spreads
    legs = structure.get("legs", 3)
    daily_theta_est = 0.0  # theta is net positive for ratio spreads (sellers)

    surface = {}
    ev_components = []

    for day in [1, 5, 10, 15]:
        # Scale probability of reaching target/stop by time (simplified linear)
        t_scale = min(1.0, day / 15.0)
        day_ev_target = win_probability * up_move * t_scale
        day_ev_flat = 0.0 - (daily_theta_est * day * legs)
        day_ev_stop = -loss_prob * down_move * t_scale

        surface[f"day_{day}"] = {
            "target": round(day_ev_target, 2),
            "flat": round(day_ev_flat, 2),
            "stop": round(day_ev_stop, 2),
        }
        # day_ev_target already carries win_probability and day_ev_stop already
        # carries loss_prob — both are probability-weighted expected contributions.
        # Multiplying day_ev_target by win_probability again here squared its
        # probability weight, systematically understating EV for every complex/
        # surface structure (ratio spreads, back spreads).
        ev_components.append(day_ev_target + day_ev_flat + day_ev_stop)

    ev_weighted = sum(ev_components) / len(ev_components)

    return {**surface, "ev_weighted": round(ev_weighted, 4)}


# ---------------------------------------------------------------------------
# Slippage adjustment
# ---------------------------------------------------------------------------

def adjust_ev_for_slippage(
    ev: float,
    structure_type: str,
    bid_ask_spread: float,
    num_legs: int,
    stock_shares: int = 0,
    slippage_pct_of_spread: float = 0.50,
    slippage_per_share: float = 0.02,
) -> float:
    """
    Real-world EV = theoretical EV - slippage estimate.
    Options: 50% of bid/ask spread per leg × 100 (1 contract = 100 shares).
    Stock: $0.02/share.
    """
    options_slippage = bid_ask_spread * slippage_pct_of_spread * num_legs * 100
    stock_slippage = stock_shares * slippage_per_share
    return ev - options_slippage - stock_slippage


# ---------------------------------------------------------------------------
# Capital efficiency scoring
# ---------------------------------------------------------------------------

def capital_efficiency_score(
    ev_per_dollar_risked: float,
    capital_required: float,
    max_capital: float = 750.0,
) -> float:
    """
    Score how efficiently the structure uses capital.
    Returns ev_per_dollar_risked or 0.0 if exceeds max_capital.
    """
    if capital_required > max_capital:
        return 0.0
    return ev_per_dollar_risked


# ---------------------------------------------------------------------------
# Structure multipliers — profit/loss multipliers per structure type
# All 42 structures must have entries here for EV calculation.
# ---------------------------------------------------------------------------

STRUCTURE_MULTIPLIERS: dict[str, dict] = {
    # Category 1: Equity
    "long_stock": {"profit_mult": 1.0, "loss_mult": 1.0, "max_loss": "unlimited_stop", "legs": 1},
    "short_stock": {"profit_mult": 1.0, "loss_mult": 1.0, "max_loss": "unlimited", "legs": 1},
    "long_stock_trailing_stop": {"profit_mult": 1.0, "loss_mult": 1.0, "max_loss": "stop_based", "legs": 1},
    "protective_put": {"profit_mult": 1.0, "loss_mult": "put_premium", "max_loss": "defined", "legs": 2},
    "collar": {"profit_mult": "capped_call_strike", "loss_mult": "put_premium_net", "max_loss": "defined", "legs": 3},
    "married_put": {"profit_mult": 1.0, "loss_mult": "put_premium", "max_loss": "defined", "legs": 2},
    # Category 2: Long Premium
    "long_call": {"profit_mult": "leverage", "loss_mult": 1.0, "max_loss": "premium", "legs": 1},
    "long_put": {"profit_mult": "leverage", "loss_mult": 1.0, "max_loss": "premium", "legs": 1},
    "deep_itm_call": {"profit_mult": "high_delta", "loss_mult": 1.0, "max_loss": "premium", "legs": 1},
    "deep_itm_put": {"profit_mult": "high_delta", "loss_mult": 1.0, "max_loss": "premium", "legs": 1},
    "leaps_call": {"profit_mult": "leverage_slow_decay", "loss_mult": 1.0, "max_loss": "premium", "legs": 1},
    "leaps_put": {"profit_mult": "leverage_slow_decay", "loss_mult": 1.0, "max_loss": "premium", "legs": 1},
    # Category 3: Debit Spreads
    "bull_call_spread": {"profit_mult": "spread_width_minus_debit", "loss_mult": 1.0, "max_loss": "debit", "legs": 2},
    "bear_put_spread": {"profit_mult": "spread_width_minus_debit", "loss_mult": 1.0, "max_loss": "debit", "legs": 2},
    "calendar_call": {"profit_mult": "theta_decay", "loss_mult": 1.0, "max_loss": "debit", "legs": 2},
    "calendar_put": {"profit_mult": "theta_decay", "loss_mult": 1.0, "max_loss": "debit", "legs": 2},
    "diagonal_call": {"profit_mult": "reduced_cost", "loss_mult": 1.0, "max_loss": "debit", "legs": 2},
    "diagonal_put": {"profit_mult": "reduced_cost", "loss_mult": 1.0, "max_loss": "debit", "legs": 2},
    # Category 4: Credit Spreads
    "bull_put_spread": {"profit_mult": 1.0, "loss_mult": "spread_minus_credit", "max_loss": "spread_minus_credit", "legs": 2},
    "bear_call_spread": {"profit_mult": 1.0, "loss_mult": "spread_minus_credit", "max_loss": "spread_minus_credit", "legs": 2},
    # Category 5: Undefined Risk
    "naked_short_call": {"profit_mult": 1.0, "loss_mult": "unlimited", "max_loss": "unlimited", "legs": 1, "capital_filter": "exclude_under_50k"},
    "naked_short_put": {"profit_mult": 1.0, "loss_mult": "stock_to_zero", "max_loss": "large", "legs": 1, "capital_filter": "exclude_under_50k"},
    # Category 6: Income
    "cash_secured_put": {"profit_mult": 1.0, "loss_mult": "stock_to_zero", "max_loss": "effective_cost", "legs": 1},
    "covered_call": {"profit_mult": "capped", "loss_mult": "stock_loss_minus_premium", "max_loss": "stock_based", "legs": 2},
    "covered_strangle": {"profit_mult": "double_premium", "loss_mult": "double_directional", "max_loss": "large", "legs": 3},
    "wheel": {"profit_mult": "systematic", "loss_mult": "stock_based", "max_loss": "effective_cost", "legs": 1},
    # Category 7: Neutral/Volatility
    "iron_condor": {"profit_mult": "credit", "loss_mult": "spread_minus_credit", "max_loss": "spread_minus_credit", "legs": 4},
    "iron_butterfly": {"profit_mult": "credit", "loss_mult": "spread_minus_credit", "max_loss": "spread_minus_credit", "legs": 4},
    "long_butterfly_call": {"profit_mult": "spread_width_minus_debit", "loss_mult": 1.0, "max_loss": "debit", "legs": 3},
    "short_butterfly": {"profit_mult": "credit", "loss_mult": "spread_minus_credit", "max_loss": "spread_minus_credit", "legs": 3},
    "condor_spread": {"profit_mult": "credit", "loss_mult": "spread_minus_credit", "max_loss": "spread_minus_credit", "legs": 4},
    "long_straddle": {"profit_mult": "leverage", "loss_mult": 1.0, "max_loss": "total_premium", "legs": 2},
    "long_strangle": {"profit_mult": "leverage", "loss_mult": 1.0, "max_loss": "total_premium", "legs": 2},
    "short_straddle": {"profit_mult": 1.0, "loss_mult": "unlimited", "max_loss": "unlimited", "legs": 2, "capital_filter": "exclude_under_50k"},
    "short_strangle": {"profit_mult": 1.0, "loss_mult": "unlimited", "max_loss": "unlimited", "legs": 2, "capital_filter": "exclude_under_50k"},
    # Category 8: Ratio/Back Spreads (COMPLEX — requires full P&L surface)
    "call_ratio_spread": {"profit_mult": "complex", "loss_mult": "complex", "max_loss": "large_upside", "legs": 3, "ev_method": "surface"},
    "put_ratio_spread": {"profit_mult": "complex", "loss_mult": "complex", "max_loss": "large_downside", "legs": 3, "ev_method": "surface"},
    "call_back_spread": {"profit_mult": "complex", "loss_mult": "complex", "max_loss": "defined", "legs": 3, "ev_method": "surface"},
    "put_back_spread": {"profit_mult": "complex", "loss_mult": "complex", "max_loss": "defined", "legs": 3, "ev_method": "surface"},
    # Category 9: Synthetic
    "risk_reversal": {"profit_mult": "stock_like", "loss_mult": "unlimited_put", "max_loss": "undefined", "legs": 2, "capital_filter": "margin_required"},
    "synthetic_long": {"profit_mult": "stock_like", "loss_mult": "unlimited", "max_loss": "undefined", "legs": 2, "capital_filter": "exclude_under_50k"},
    "synthetic_short": {"profit_mult": "stock_like", "loss_mult": "unlimited", "max_loss": "undefined", "legs": 2, "capital_filter": "exclude_under_50k"},
}
