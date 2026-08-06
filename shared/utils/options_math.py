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
# Real per-structure economics (v2.2.36)
# ---------------------------------------------------------------------------
# STRUCTURE_MULTIPLIERS' profit_mult/loss_mult were, for 35 of the 42
# structures below, descriptive placeholder strings ("leverage",
# "spread_width_minus_debit", "put_premium", "theta_decay", ...) that read
# like they were meant to become real formulas but never did.
# _compute_structure_ev's isinstance guard (trade_selector.py) silently
# converted every one of them to 1.0, making 35 structures' modeled EV
# indistinguishable from plain long/short stock regardless of their actual
# leverage, defined-risk cap, or premium cost. Separately, protective_put's
# capital estimate (entry * 0.3) was a special-cased shortcut its economically
# near-identical siblings married_put/collar didn't get (they fell through to
# a generic default ~15-30x larger) — the real reason protective_put won every
# real ranking evaluation observed live, not genuine economic merit.
#
# resolve_structure_economics() replaces both: real Black-Scholes-derived
# avg_win/avg_loss AND a capital estimate that's actually consistent with them,
# computed together so a structure can't get an artificially cheap capital
# figure paired with an EV that assumes real economics. Strike conventions
# reuse this module's own select_directional_leg_strike() offsets (otm=6%,
# far_otm=12%, deep_itm=15%) for consistency with the Greeks filter elsewhere
# in this project.
#
# Scaling convention: results are per-100-share/1-contract lot (x100) for
# every options-involving structure, matching how real contracts trade and
# how this module's capital filter (max_capital, $750 at $15k) is meant to be
# read. The 3 pure-stock structures (long_stock, short_stock,
# long_stock_trailing_stop) stay per-share, unchanged — they were already
# correctly modeled and their own numerator/denominator are self-consistent;
# ev_per_dollar_risked is scale-invariant as long as each structure's own
# avg_win/avg_loss and capital share the same basis, which is the only
# property cross-structure ranking actually depends on.
#
# fav/unfav below are abs(target-entry)/abs(entry-stop) — this project's
# direction handling defaults every observed live signal to bullish (see
# scoring.py's determine_direction docstring: "Default to bullish per system
# bias"), and this function has no reliable way to re-derive bullish/bearish
# sign conventions for entry/stop/target that this module doesn't itself set —
# option-side conventions (which strike is "otm", which direction is
# protective) are chosen by each structure's own option_type instead, which
# doesn't depend on that assumption.
#
# The 4 ratio/back-spread structures (call_ratio_spread, put_ratio_spread,
# call_back_spread, put_back_spread) are deliberately not handled here — they
# already route through compute_ev_surface() via their ev_method="surface"
# key, a real (if simplified) multi-scenario P&L model, not a broken
# placeholder. Calendar/diagonal spreads (2 different expirations) and the
# wheel (a repeating CSP/CC cycle) are modeled here as clearly-documented
# single-snapshot approximations, not full multi-expiry/multi-cycle surfaces —
# still a large improvement on a silent 1.0 default, but flagged as the
# least-precise formulas in this set for future refinement.
# ---------------------------------------------------------------------------

_DEFAULT_DTE_IF_UNKNOWN = 10  # midpoint of this project's 5-15 day holding period
_LEAPS_MIN_DAYS = 270         # LEAPS are long-dated; ~9 months out is typical
_MIN_IV = 0.05                # Black-Scholes is undefined at iv<=0; near-zero is never realistic
_STOCK_MARGIN_FRACTION = 0.5  # Reg-T initial margin assumption for a marginable long stock leg
# Floor for net-debit/net-credit-width type formulas below, proportional to
# entry rather than a fixed tiny absolute number. A fixed floor (e.g. 0.01)
# produced an artificial ~$1 "capital required" for diagonal_call/diagonal_put
# whenever the far leg's longer time-to-expiry didn't outweigh its OTM strike
# discount enough to keep the near-short-leg-minus-far-long-leg debit
# comfortably positive -- the ratio (real EV / near-zero capital) exploded to
# an absurd ev_per_dollar_risked that briefly ranked diagonal_call #1 above
# everything else. Scaling the floor to the stock's own price keeps it a
# plausible minimum real-world premium instead of an arbitrary constant that
# can be tiny relative to whatever price level a given ticker trades at.
_MIN_PREMIUM_FLOOR_FRACTION = 0.005

# Structures already correctly modeled (pure stock, per-share, numeric
# multipliers) or handled by compute_ev_surface() — resolve_structure_economics
# is a no-op passthrough signal for these; callers should keep using the
# existing profit_mult/loss_mult/_estimate_capital_required path for them.
PASSTHROUGH_STRUCTURES = frozenset({
    "long_stock", "short_stock", "long_stock_trailing_stop",
    "call_ratio_spread", "put_ratio_spread", "call_back_spread", "put_back_spread",
})


def _otm_k(entry: float, option_type: str, magnitude: float) -> float:
    """Strike `magnitude` fraction OTM of `entry` for a call (above) or put (below)."""
    sign = 1.0 if option_type == "call" else -1.0
    return entry * (1 + sign * magnitude)


def _itm_k(entry: float, option_type: str, magnitude: float) -> float:
    """Strike `magnitude` fraction ITM of `entry` for a call (below) or put (above)."""
    sign = -1.0 if option_type == "call" else 1.0
    return entry * (1 + sign * magnitude)


def resolve_structure_economics(
    structure_name: str,
    entry: float,
    stop: float,
    target: float,
    iv: float,
    dte: Optional[int],
    r: float = 0.04,
) -> Optional[dict]:
    """
    Real avg_win/avg_loss/capital_required for one structure. Returns None for
    PASSTHROUGH_STRUCTURES (caller should fall back to the existing
    profit_mult/loss_mult/_estimate_capital_required path) or if entry/stop/
    target aren't usable (mirrors _compute_structure_ev's own guard).

    Returns {"avg_win": float, "avg_loss": float, "capital_required": float,
    "effective_days": float} — avg_win/avg_loss/capital_required already
    x100-scaled per the module-level convention above, ready to feed straight
    into compute_ev_simple() and the capital filter. effective_days is how
    many days of time-exposure this structure's own EV was actually computed
    against — max(dte, 1) for most structures, but leaps_call/leaps_put use
    _LEAPS_MIN_DAYS-scale exposure and calendar_*/diagonal_* use dte+30 for
    their longer-dated leg (see those branches below) — a caller comparing EV
    per dollar risked across structures without dividing by this would be
    comparing a ~10-day trade's edge against a ~270-day trade's edge as if
    they tied up capital for the same length of time.
    """
    if structure_name in PASSTHROUGH_STRUCTURES:
        return None
    if entry <= 0 or stop <= 0 or target <= 0 or stop >= entry:
        return None

    fav = abs(target - entry)
    unfav = abs(entry - stop)
    iv = max(iv, _MIN_IV)
    effective_days = max(dte if dte is not None else _DEFAULT_DTE_IF_UNKNOWN, 1)
    T = effective_days / 365.0

    def bs(S: float, K: float, T_: float, opt: str) -> float:
        return black_scholes_price(S, K, T_, r, iv, opt)

    def single_leg_long(option_type: str, k: float, T_: float) -> tuple[float, float, float]:
        """avg_win, avg_loss, premium for one long call/put at strike k."""
        premium = bs(entry, k, T_, option_type)
        s_fav = entry + fav if option_type == "call" else entry - fav
        s_unfav = entry - unfav if option_type == "call" else entry + unfav
        val_fav = bs(s_fav, k, T_, option_type)
        val_unfav = bs(s_unfav, k, T_, option_type)
        return (val_fav - premium) * 100, (premium - val_unfav) * 100, premium

    # --- Category 1: Equity + protective (100-share lot + option leg(s)) ---
    if structure_name in ("protective_put", "married_put"):
        k = _otm_k(entry, "put", 0.06)
        premium = bs(entry, k, T, "put")
        avg_win = (fav - premium) * 100
        avg_loss = (unfav + premium) * 100
        capital = (entry * _STOCK_MARGIN_FRACTION + premium) * 100
        return {"avg_win": avg_win, "avg_loss": avg_loss, "capital_required": capital, "effective_days": effective_days}

    if structure_name == "collar":
        put_k, call_k = _otm_k(entry, "put", 0.06), _otm_k(entry, "call", 0.06)
        put_premium, call_premium = bs(entry, put_k, T, "put"), bs(entry, call_k, T, "call")
        net_premium = put_premium - call_premium  # negative = net credit
        capped_upside = min(fav, call_k - entry)
        avg_win = (capped_upside - net_premium) * 100
        avg_loss = (unfav + net_premium) * 100
        capital = (entry * _STOCK_MARGIN_FRACTION + max(0.0, net_premium)) * 100
        return {"avg_win": avg_win, "avg_loss": avg_loss, "capital_required": capital, "effective_days": effective_days}

    # --- Category 2: Long premium, single leg (real leveraged option payoff) ---
    if structure_name in ("long_call", "long_put"):
        opt = "call" if structure_name == "long_call" else "put"
        avg_win, avg_loss, premium = single_leg_long(opt, entry, T)
        return {"avg_win": avg_win, "avg_loss": avg_loss, "capital_required": premium * 100, "effective_days": effective_days}

    if structure_name in ("deep_itm_call", "deep_itm_put"):
        opt = "call" if structure_name == "deep_itm_call" else "put"
        k = _itm_k(entry, opt, 0.15)
        avg_win, avg_loss, premium = single_leg_long(opt, k, T)
        return {"avg_win": avg_win, "avg_loss": avg_loss, "capital_required": premium * 100, "effective_days": effective_days}

    if structure_name in ("leaps_call", "leaps_put"):
        opt = "call" if structure_name == "leaps_call" else "put"
        leaps_days = max(dte if dte is not None else _LEAPS_MIN_DAYS, _LEAPS_MIN_DAYS)
        T_leaps = leaps_days / 365.0
        avg_win, avg_loss, premium = single_leg_long(opt, entry, T_leaps)
        return {"avg_win": avg_win, "avg_loss": avg_loss, "capital_required": premium * 100, "effective_days": leaps_days}

    # --- Category 3: Debit spreads (2 legs, defined risk = net debit) ---
    if structure_name in ("bull_call_spread", "bear_put_spread"):
        opt = "call" if structure_name == "bull_call_spread" else "put"
        long_k = entry
        short_k = _otm_k(entry, opt, 0.12)
        long_premium, short_premium = bs(entry, long_k, T, opt), bs(entry, short_k, T, opt)
        net_debit = long_premium - short_premium
        width = abs(short_k - long_k)
        avg_win = (min(fav, width) - net_debit) * 100
        avg_loss = net_debit * 100
        floor = entry * _MIN_PREMIUM_FLOOR_FRACTION
        return {"avg_win": avg_win, "avg_loss": avg_loss, "capital_required": max(net_debit, floor) * 100, "effective_days": effective_days}

    if structure_name in ("calendar_call", "calendar_put", "diagonal_call", "diagonal_put"):
        # Approximation, documented above: single-snapshot, not a true 2-expiry
        # surface. Calendars/diagonals profit mainly from time decay near the
        # short strike, not large directional moves — damped participation
        # (0.4x) reflects that a big move away from the strike hurts a
        # calendar's P&L even in the "favorable" direction, unlike a plain
        # directional option. Max loss bounded at the net debit, as in reality.
        opt = "call" if "call" in structure_name else "put"
        is_diagonal = "diagonal" in structure_name
        near_k = entry
        far_k = _otm_k(entry, opt, 0.06) if is_diagonal else entry
        short_premium = bs(entry, near_k, T, opt)
        diagonal_days = effective_days + 30
        long_T = diagonal_days / 365.0
        long_premium = bs(entry, far_k, long_T, opt)
        floor = entry * _MIN_PREMIUM_FLOOR_FRACTION
        net_debit = max(long_premium - short_premium, floor)
        avg_win = (fav * 0.4 - net_debit) * 100
        avg_loss = net_debit * 100
        # effective_days uses the long (back) leg's expiration, not the near
        # leg's — the position isn't fully closed, and this structure's own
        # capital (net_debit) isn't freed, until that longer-dated leg is
        # closed, so that's the exposure this structure's EV is really priced
        # against, not the shared short-leg dte every other structure uses.
        return {"avg_win": avg_win, "avg_loss": avg_loss, "capital_required": net_debit * 100, "effective_days": diagonal_days}

    # --- Category 4: Credit spreads (2 legs, defined risk = width - credit) ---
    if structure_name in ("bull_put_spread", "bear_call_spread"):
        opt = "put" if structure_name == "bull_put_spread" else "call"
        short_k = _otm_k(entry, opt, 0.06)
        long_k = _otm_k(entry, opt, 0.12)
        short_premium, long_premium = bs(entry, short_k, T, opt), bs(entry, long_k, T, opt)
        net_credit = short_premium - long_premium
        width = abs(long_k - short_k)
        avg_win = net_credit * 100
        avg_loss = max(width - net_credit, 0.0) * 100
        floor = entry * _MIN_PREMIUM_FLOOR_FRACTION
        return {"avg_win": avg_win, "avg_loss": avg_loss, "capital_required": max(width - net_credit, floor) * 100, "effective_days": effective_days}

    # --- Category 5: Undefined risk (excluded under $50k by Filter 1 regardless;
    #     still given a real, bounded-tail-risk formula for correctness) ---
    if structure_name in ("naked_short_call", "naked_short_put"):
        opt = "call" if structure_name == "naked_short_call" else "put"
        k = _otm_k(entry, opt, 0.06)
        premium = bs(entry, k, T, opt)
        # True risk is unlimited (call) / bounded by stock-to-zero (put) — use a
        # 2-standard-deviation move as a finite tail-risk proxy for ranking
        # purposes only; the $50k+Level 3 filter is what actually gates this,
        # not this estimate.
        two_sigma_move = entry * iv * math.sqrt(T) * 2
        avg_win = premium * 100
        avg_loss = max(two_sigma_move - premium, 0.0) * 100
        return {"avg_win": avg_win, "avg_loss": avg_loss, "capital_required": entry * 0.20 * 100, "effective_days": effective_days}

    # --- Category 6: Income (require real share ownership/cash-securing) ---
    if structure_name == "cash_secured_put":
        k = _otm_k(entry, "put", 0.06)
        premium = bs(entry, k, T, "put")
        avg_win = premium * 100
        avg_loss = max((k - stop) - premium, 0.0) * 100 if stop < k else 0.0
        return {"avg_win": avg_win, "avg_loss": avg_loss, "capital_required": k * 100, "effective_days": effective_days}

    if structure_name == "covered_call":
        k = _otm_k(entry, "call", 0.06)
        premium = bs(entry, k, T, "call")
        avg_win = (min(fav, k - entry) + premium) * 100
        avg_loss = max(unfav - premium, 0.0) * 100
        return {"avg_win": avg_win, "avg_loss": avg_loss, "capital_required": entry * 100, "effective_days": effective_days}

    if structure_name == "covered_strangle":
        call_k, put_k = _otm_k(entry, "call", 0.06), _otm_k(entry, "put", 0.06)
        call_premium, put_premium = bs(entry, call_k, T, "call"), bs(entry, put_k, T, "put")
        total_premium = call_premium + put_premium
        avg_win = (min(fav, call_k - entry) + total_premium) * 100
        # Short the put too, on top of owning stock — doubles downside exposure
        # below the put strike relative to a plain covered call.
        avg_loss = max(unfav * 2 - total_premium, 0.0) * 100
        return {"avg_win": avg_win, "avg_loss": avg_loss, "capital_required": entry * 100 + max(put_k - entry, 0) * 100, "effective_days": effective_days}

    if structure_name == "wheel":
        # Single-cycle approximation of a repeating CSP->assignment->CC cycle:
        # modeled as one cash-secured put snapshot, documented above as one of
        # the least-precise formulas here.
        k = _otm_k(entry, "put", 0.06)
        premium = bs(entry, k, T, "put")
        avg_win = premium * 100
        avg_loss = max((k - stop) - premium, 0.0) * 100 if stop < k else 0.0
        return {"avg_win": avg_win, "avg_loss": avg_loss, "capital_required": k * 100, "effective_days": effective_days}

    # --- Category 7: Neutral/volatility (multi-leg) ---
    if structure_name in ("iron_condor", "iron_butterfly", "short_butterfly", "condor_spread"):
        # 4-leg (condor/iron_condor) or 3-leg (butterfly) credit structure,
        # modeled as a put-side + call-side credit spread pair. Iron butterfly/
        # short butterfly use ATM short strikes (narrower, higher credit);
        # condor/iron condor use OTM short strikes (wider, lower credit).
        at_money = structure_name in ("iron_butterfly", "short_butterfly")
        put_short_k = entry if at_money else _otm_k(entry, "put", 0.06)
        put_long_k = _otm_k(entry, "put", 0.12)
        call_short_k = entry if at_money else _otm_k(entry, "call", 0.06)
        call_long_k = _otm_k(entry, "call", 0.12)
        credit = (
            bs(entry, put_short_k, T, "put") - bs(entry, put_long_k, T, "put")
            + bs(entry, call_short_k, T, "call") - bs(entry, call_long_k, T, "call")
        )
        width = min(put_short_k - put_long_k, call_long_k - call_short_k)
        avg_win = credit * 100
        avg_loss = max(width - credit, 0.0) * 100
        floor = entry * _MIN_PREMIUM_FLOOR_FRACTION
        return {"avg_win": avg_win, "avg_loss": avg_loss, "capital_required": max(width - credit, floor) * 100, "effective_days": effective_days}

    if structure_name == "long_butterfly_call":
        k_low, k_mid, k_high = _itm_k(entry, "call", 0.06), entry, _otm_k(entry, "call", 0.06)
        premium = (
            bs(entry, k_low, T, "call") + bs(entry, k_high, T, "call") - 2 * bs(entry, k_mid, T, "call")
        )
        max_profit = (k_mid - k_low) - premium
        avg_win = min(fav, max_profit) * 100 if max_profit > 0 else 0.0
        avg_loss = max(premium, 0.0) * 100
        floor = entry * _MIN_PREMIUM_FLOOR_FRACTION
        return {"avg_win": avg_win, "avg_loss": avg_loss, "capital_required": max(premium, floor) * 100, "effective_days": effective_days}

    if structure_name in ("long_straddle", "long_strangle"):
        call_k = entry if structure_name == "long_straddle" else _otm_k(entry, "call", 0.06)
        put_k = entry if structure_name == "long_straddle" else _otm_k(entry, "put", 0.06)
        call_premium, put_premium = bs(entry, call_k, T, "call"), bs(entry, put_k, T, "put")
        total_premium = call_premium + put_premium
        # Profits from a big move either direction; "fav" proxies the size of
        # whichever move materializes, "unfav" (flat/small move) is this
        # structure's real loss scenario since both legs decay together.
        call_val_at_fav = bs(entry + fav, call_k, T, "call")
        put_val_at_fav = bs(entry - fav, put_k, T, "put")
        avg_win = (max(call_val_at_fav, put_val_at_fav) - total_premium) * 100
        avg_loss = total_premium * 100
        return {"avg_win": avg_win, "avg_loss": avg_loss, "capital_required": total_premium * 100, "effective_days": effective_days}

    if structure_name in ("short_straddle", "short_strangle"):
        call_k = entry if structure_name == "short_straddle" else _otm_k(entry, "call", 0.06)
        put_k = entry if structure_name == "short_straddle" else _otm_k(entry, "put", 0.06)
        call_premium, put_premium = bs(entry, call_k, T, "call"), bs(entry, put_k, T, "put")
        total_credit = call_premium + put_premium
        two_sigma_move = entry * iv * math.sqrt(T) * 2
        avg_win = total_credit * 100
        avg_loss = max(two_sigma_move - total_credit, 0.0) * 100
        return {"avg_win": avg_win, "avg_loss": avg_loss, "capital_required": entry * 0.20 * 100, "effective_days": effective_days}

    # --- Category 9: Synthetic (stock-replacement combos) ---
    if structure_name in ("risk_reversal", "synthetic_long", "synthetic_short"):
        is_synthetic = "synthetic" in structure_name
        call_k = entry if is_synthetic else _otm_k(entry, "call", 0.06)
        put_k = entry if is_synthetic else _otm_k(entry, "put", 0.06)
        call_premium, put_premium = bs(entry, call_k, T, "call"), bs(entry, put_k, T, "put")
        if structure_name == "synthetic_short":
            net_cost = put_premium - call_premium
            avg_win, avg_loss = (unfav - net_cost) * 100, (fav + net_cost) * 100
        else:
            net_cost = call_premium - put_premium
            avg_win, avg_loss = (fav - net_cost) * 100, (unfav + net_cost) * 100
        return {"avg_win": avg_win, "avg_loss": avg_loss, "capital_required": entry * 0.25 * 100, "effective_days": effective_days}

    return None


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
