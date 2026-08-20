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
   has a resolvable options-only leg composition — see _GREEKS_RESOLVABLE_LEGS
   (29 of 42 structures, as of v2.2.60 — condors/butterflies, the wheel, and
   the 2-leg synthetics/risk-reversal joined the original 20). Real strikes
   are picked from the chain (options_math.py's select_directional_leg_strike,
   a fixed strike-offset convention, not iterative delta-solving) and net
   theta/vega computed (net_structure_greeks) against config-driven bounds
   (swing_config.yaml's greeks_filter block). Calendars/diagonals (2 different
   expirations — net_structure_greeks takes one shared T, genuinely can't
   represent them), LEAPS (needs a separate long-dated chain fetch nothing in
   this pipeline does yet), and the 4 ratio/back-spread structures (no strike
   convention exists anywhere in their code path — they route through
   compute_ev_surface, not resolve_structure_economics) remain un-filtered —
   each blocked on a different genuine gap, not simply unwired. `greeks_filter_
   status` in the result reports which applied. No `option_chain` supplied at
   all → same as before this filter existed, reported as
   'not_implemented_no_options_chain_data'.
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
    resolve_structure_economics,
    _DEFAULT_DTE_IF_UNKNOWN,
)
from shared.utils.position_sizer import get_risk_pct
from shared.utils.risk_reward import compute_rr_ratio
from swing_model.win_probability_calibration import calibrate_win_probability

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
# Distinct concept from _UNDEFINED_RISK_STRUCTURES above: that set is about
# theoretically unbounded loss (gated by account size in _apply_filters,
# Filter 1 — excluded entirely below $50k). These 3 have a bounded max loss
# (long_stock/long_stock_trailing_stop can't lose more than the full position;
# short_stock is in the set above too, separately, for its unbounded upside
# risk) but are still exposed to real overnight gap risk that a bought
# option isn't — a stop-loss is an instruction, not a guarantee, and can fill
# far worse than planned on a gap. Given this account's no-negative-months
# mandate, that distinction should drive *preference* (see
# rank_trade_structures' recommended-selection step below), not eligibility —
# a stock structure can still be evaluated and ranked, it just shouldn't win
# over a feasible, EV-positive options structure whose max loss is
# contractually capped at the premium paid, no gap exposure possible.
_GAP_RISK_STRUCTURES = {"long_stock", "long_stock_trailing_stop", "short_stock"}
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
    # Added v2.2.60 — single-expiration, multi-leg structures with no
    # multi-expiration/quantity-ratio/new-strike-convention blocker (unlike
    # calendars/diagonals/ratio-back-spreads/LEAPS, still excluded above).
    # Strike tuples mirror resolve_structure_economics' own branches exactly
    # (options_math.py) so Greeks are computed against the same strikes the
    # structure's EV/economics were.
    "iron_condor": [
        ("put", "long", "far_otm"), ("put", "short", "otm"),
        ("call", "short", "otm"), ("call", "long", "far_otm"),
    ],
    "iron_butterfly": [
        ("put", "long", "far_otm"), ("put", "short", "atm"),
        ("call", "short", "atm"), ("call", "long", "far_otm"),
    ],
    "short_butterfly": [
        ("put", "long", "far_otm"), ("put", "short", "atm"),
        ("call", "short", "atm"), ("call", "long", "far_otm"),
    ],
    "condor_spread": [
        ("put", "long", "far_otm"), ("put", "short", "otm"),
        ("call", "short", "otm"), ("call", "long", "far_otm"),
    ],
    # long_butterfly_call's inner wing is a real leg (2x short at k_mid, per
    # resolve_structure_economics' `premium = bs(k_low) + bs(k_high) - 2 *
    # bs(k_mid)`) — listed twice since _GREEKS_RESOLVABLE_LEGS/
    # net_structure_greeks have no per-leg quantity concept, only a flat leg
    # list; two short legs at the same strike nets to the correct 2x weight.
    "long_butterfly_call": [
        ("call", "long", "itm"), ("call", "short", "atm"),
        ("call", "short", "atm"), ("call", "long", "otm"),
    ],
    # Economically identical to cash_secured_put (single short put snapshot,
    # see resolve_structure_economics' wheel branch) — same leg spec.
    "wheel": [("put", "short", "otm")],
    "risk_reversal": [("call", "long", "otm"), ("put", "short", "otm")],
    "synthetic_long": [("call", "long", "atm"), ("put", "short", "atm")],
    "synthetic_short": [("put", "long", "atm"), ("call", "short", "atm")],
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
    atm_iv: Optional[float] = None,
    win_probability_calibration: Optional[list] = None,
) -> dict:
    """
    Evaluate all 42 structures and return EV-ranked output.

    candidate: {ticker, direction, confidence, entry, stop, target, atr_14, ...}
    iv_percentile: current IV percentile (0-100, where today's IV sits relative
      to its own trailing history) — a RANK, not an IV value. Kept as a
      parameter for callers/future use but no longer used as a stand-in for
      real IV in the EV math (see atm_iv below) — iv_percentile/100 was
      previously passed straight into Black-Scholes-adjacent calculations as
      if it were an actual volatility fraction, conflating "IV is unusually
      high for this stock" with "this stock's IV is 80%", two different things
      that can each be true independently of the other.
    atm_iv: the real current at-the-money implied volatility (e.g. 0.35 for
      35% annualized), from positioning_client.py's fetch_option_chain_metrics
      ('atm_iv' field, available via positioning's _options_raw passthrough).
      Used for every real-option-pricing formula in resolve_structure_economics.
      When not supplied, falls back to a mild iv_percentile-scaled estimate
      (0.20-0.50 range) — an approximation for when no live chain was fetched,
      not a substitute for the real figure when it's available.
    option_chain: real near-the-money contracts from positioning_client.py's
      fetch_option_chain_metrics ('chain' field) — enables Filter 4 (Greeks) for
      structures in _GREEKS_RESOLVABLE_LEGS, and (when bid_ask_spreads isn't
      explicitly supplied) real per-structure bid/ask spreads for Filter 5.
      None (the default) reproduces the prior behavior exactly — both filters
      stay as inert as they were before this parameter existed.
    dte: days to option_chain's expiration — required alongside option_chain for
      Filter 4 to run (Greeks need a real time-to-expiry, not an assumed one).
      Also now used by resolve_structure_economics for every structure's own
      option-pricing time-to-expiry, defaulting to a mid-holding-period
      estimate when not supplied.
    win_probability_calibration: real (threshold -> historical win rate) points
      from swing_model.win_probability_calibration.fit_calibration_curve(), used
      to convert `confidence` into every structure's win_prob input instead of
      the literal (and unevidenced) confidence/100 identity — a score of 90
      does not mean a 90% chance of winning; the model's own backtested win
      rate at that threshold is ~60% (see win_probability_calibration.py's
      module docstring). None (the default) falls back to the old
      confidence/100 behavior — see win_prob_calibrated in the return dict for
      whether a call actually used real calibration or that fallback.

    Returns:
    {
        ticker, direction, confidence,
        structures_evaluated: 42,
        structures_eligible_after_filters: int,
        ranked_structures: [...],
        exclusion_summary: str,
        greeks_filter_status: "applied" | "not_implemented_no_options_chain_data",
        structures_greeks_evaluated: int,
        win_prob_used: float,
        win_prob_calibrated: bool,
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

    if win_probability_calibration:
        win_prob = calibrate_win_probability(confidence, win_probability_calibration)
        win_prob_calibrated = True
    else:
        win_prob = confidence / 100.0
        win_prob_calibrated = False
    max_capital = account_equity * 0.05
    force_defined_risk = bool(candidate.get("force_defined_risk", False))
    # Real IV when a live chain supplied one; otherwise a mild iv_percentile-
    # scaled approximation (0.20-0.50) rather than misusing the percentile
    # rank itself as a volatility fraction — see atm_iv's docstring above.
    #
    # This fallback ignores the candidate's own ATR/price ratio entirely —
    # confirmed (see tests/test_structure_economics.py::
    # TestHighAtrPriceRatioCharacterization) that resolve_structure_economics'
    # fixed-OTM-offset structures (long_strangle et al.) price their premium
    # from entry/iv/dte only, never from ATR, while their payoff scales
    # directly with ATR — so a high-ATR-ratio candidate hitting this fallback
    # (no live chain) gets a mechanically inflated ev_per_dollar_per_day
    # regardless of whether that stock's *real* IV is actually elevated to
    # match. A real atm_iv (when available) partially self-corrects this
    # since volatile stocks usually do trade at higher real IV; this
    # approximation has no such link. Deliberately not patched here with an
    # ATR-derived IV floor — that would be a new, uncalibrated formula on top
    # of an already-approximate one. The actual safety net is
    # shared/utils/robust_stats.py's outlier check (paper_runner.py), which
    # flags exactly this shape of anomaly against each structure's own
    # trailing history instead of guessing at a fix with no real data behind it.
    resolved_iv = atm_iv if atm_iv is not None else 0.20 + (iv_percentile / 100.0) * 0.30

    # Filter 3 input: R:R of the shared entry/stop/target setup. Identical for every
    # structure (none of them change the underlying's own price levels), so it's
    # computed once here rather than per-structure.
    #
    # Uses risk_reward.py's own compute_rr_ratio (already 2dp-rounded to avoid
    # the float-noise-at-exact-minimum issue described in CHANGELOG v2.2.48)
    # rather than a bullish-only inline formula — the previous inline version
    # here (`(target-entry)/(entry-stop) if (entry-stop) > 0 else 0.0`) never
    # branched for bearish, where stop sits *above* entry per this module's own
    # convention (see risk_reward.py's compute_stop_loss/compute_target
    # docstrings) — so `entry - stop` was always negative for bearish and this
    # unconditionally evaluated to 0.0, which is always < min_rr. That silently
    # excluded all 42 structures for every bearish signal, before any other
    # filter ever ran (confirmed empirically: zero bearish rows anywhere in
    # paper_trading/paper_trades.csv).
    rr = compute_rr_ratio(entry, stop, target, direction=direction)
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
            # Divide by structure["legs"] (the FULL leg count, e.g. 2 for
            # covered_call's stock+call), not len(legs) (only the option
            # leg(s) _GREEKS_RESOLVABLE_LEGS tracks — stock legs are
            # deliberately omitted there since stock has no comparable bid/ask
            # spread cost). For the 5 mixed stock+option structures
            # (covered_call, protective_put, married_put, collar,
            # covered_strangle), structure["legs"] > len(legs) — dividing by
            # len(legs) instead produced a per-real-leg average that, once
            # _compute_structure_ev's adjust_ev_for_slippage call multiplies
            # it back by structure["legs"], double(ish)-counted the stock
            # leg's spread as if it were a second option leg, systematically
            # overstating slippage (and understating EV) for exactly these 5
            # structures whenever a real option_chain was supplied. Dividing
            # by structure["legs"] here instead means that later
            # multiplication reconstructs the real option legs' summed
            # spread, with the stock leg correctly contributing 0 — for pure-
            # options structures (structure["legs"] == len(legs)), this is a
            # no-op vs. the old divisor.
            bid_ask_spreads[name] = sum(c["ask"] - c["bid"] for c in legs) / structure.get("legs", len(legs))

        ev_result = _compute_structure_ev(name, structure, candidate, resolved_iv,
                                          win_prob, bid_ask_spreads.get(name, 0.0), dte, cfg=cfg)
        if ev_result is None:
            excluded.append({"name": name, "reasons": ["ev_computation_failed"]})
            continue
        (ev, ev_raw, ev_adjusted, est_capital, effective_days,
         max_loss_dollars, max_gain_dollars, theoretical_strikes) = ev_result

        # Real chain strikes (legs, resolved above for Filter 4/5) win over
        # resolve_structure_economics' theoretical Black-Scholes strikes when
        # both exist — real, currently-quoted contracts are more useful to a
        # trader than a fixed-offset estimate. legs carries no leg-role name
        # (just option_type/side per contract), so key by those instead of
        # resolve_structure_economics' own long_k/short_k/put_k/call_k names.
        if legs:
            strikes = {f"{leg['option_type']}_{leg['side']}": leg["strike"] for leg in legs}
            strike_source = "real_chain"
        else:
            strikes = theoretical_strikes
            strike_source = "theoretical" if strikes else None

        # Filter 5: Liquidity — a wide bid/ask can consume most of a structure's
        # edge on multi-leg fills. Exclude when slippage eats >=50% of the raw EV
        # (only meaningful when there's actually an edge to protect and spread
        # data was supplied — a missing/zero spread is "unknown", not "tight").
        if ev_raw > 0 and bid_ask_spreads.get(name, 0.0) > 0:
            slippage_fraction = (ev_raw - ev_adjusted) / ev_raw
            if slippage_fraction >= 0.50:
                excluded.append({"name": name, "reasons": ["wide_bid_ask_liquidity"]})
                continue

        # est_capital already computed above by _compute_structure_ev, from the
        # same resolve_structure_economics() call that produced this
        # structure's EV — guarantees the ranking ratio and this cap check
        # always agree on the same capital figure (see _compute_structure_ev's
        # docstring for why that used to not be true).
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
        elif name in _UNDEFINED_RISK_STRUCTURES and name in _GREEKS_RESOLVABLE_LEGS:
            # Fail CLOSED, not open, for undefined-risk/short-premium
            # structures (naked_short_call/put, short_straddle/strangle,
            # synthetic_long/short, risk_reversal) specifically — Greeks is
            # the one automated check standing between these and a
            # theoretically-unbounded-loss position getting ranked and
            # recommended, so a chain-fetch hiccup (this project has
            # documented feed flakiness before — Seeking Alpha/RapidAPI
            # outages) must not silently let one through unchecked. Defined-
            # risk structures (spreads/condors/etc.) are deliberately left
            # to fail open here — their capital-at-risk is already capped by
            # Filters 1/2, so an un-run Greeks check degrades a refinement,
            # not the only safety net (Signal Integrity Audit finding D.1).
            reason = (
                "greeks_required_no_chain_data" if not greeks_available
                else "greeks_required_legs_unresolvable"
            )
            excluded.append({"name": name, "reasons": [reason]})
            continue

        ev_per_dollar = capital_efficiency_score(ev, est_capital, max_capital)
        # Per-day, not just per-dollar — ev_per_dollar_risked alone compares a
        # ~10-day trade's edge against a leaps_call's ~270-day edge (or a
        # diagonal's dte+30) as if both tied up capital for the same length of
        # time. effective_days is the actual time exposure this structure's
        # own EV was computed against (see resolve_structure_economics'
        # docstring) — dividing by it is what makes structures with very
        # different holding requirements comparable on capital velocity, not
        # just capital-at-risk.
        ev_per_dollar_per_day = ev_per_dollar / max(effective_days, 1)

        ranked_structures.append({
            "name": name,
            "ev_per_dollar_risked": round(ev_per_dollar, 4),
            "ev_per_dollar_per_day": round(ev_per_dollar_per_day, 5),
            "effective_days": round(effective_days, 1),
            "ev": round(ev, 4),
            "capital_required": round(est_capital, 2),
            "rr_ratio": round(rr, 2),
            "legs": structure.get("legs", 1),
            "greeks": greeks_detail,
            "filter_notes": [],
            # "shares" for the 3 plain-stock structures (_GAP_RISK_STRUCTURES),
            "position_type": "shares" if name in _GAP_RISK_STRUCTURES else "options",
            # None for structures whose risk/reward is genuinely unbounded
            # (short stock, naked options, short straddle/strangle,
            # synthetics) — never fabricated, see resolve_structure_economics'
            # own per-branch comments in options_math.py.
            "max_loss_dollars": round(max_loss_dollars, 2) if max_loss_dollars is not None else None,
            "max_gain_dollars": round(max_gain_dollars, 2) if max_gain_dollars is not None else None,
            # "real_chain" when a live option chain supplied actual quoted
            # strikes (preferred), "theoretical" for the Black-Scholes-derived
            # fixed-offset estimate, None for the 3 pure-stock/4 ratio-spread
            # structures that have no strike concept or convention at all.
            "strikes": {k: round(v, 2) for k, v in strikes.items()} if strikes else {},
            "strike_source": strike_source,
        })

    # Sort by EV per dollar risked *per day held* — see ev_per_dollar_per_day's
    # inline comment above for why the un-normalized ratio alone isn't a fair
    # comparison across structures with different time exposure. This order is
    # kept as pure diagnostic/EV ranking (Discord alerts, human review of "what
    # wins on raw economics") — the actual pick is decided separately below.
    ranked_structures.sort(key=lambda x: x["ev_per_dollar_per_day"], reverse=True)
    for i, s in enumerate(ranked_structures):
        s["rank"] = i + 1
        s["recommended"] = False

    # recommended: a priority chain, not just "best EV that isn't gap-risk."
    # Filter 2 (the max_capital check above, 5% of account = $750 at $15k) is
    # a blanket concentration cap — it doesn't know this specific signal's
    # confidence-tier risk budget (get_risk_pct: 0.5% for a 70-89 score, up to
    # 2.5% at 99-100 — as little as $75 on a $15k account). A structure can
    # clear the blanket cap and still cost far more than this trade is
    # actually allowed to risk (this is exactly what happened live: a 71.0-
    # score signal's long_strangle cost $248, well under the $750 cap, but
    # over 3x the $75 the 70-89 tier allows — sized to 0 shares/contracts
    # and the signal was lost entirely, even though long_stock's $13 risk
    # would have fit easily). So "recommended" checks tier-budget fit first,
    # then the gap-risk preference, in priority order:
    #   1. non-gap-risk (capped-risk option), positive EV, fits this tier's
    #      actual dollar-risk budget — the ideal case.
    #   2. gap-risk (shares), positive EV, fits the tier budget — used only
    #      when no capped-risk option does; this is what lets a signal like
    #      the one above still become a real, sized position instead of a
    #      silent zero.
    #   3. non-gap-risk, positive EV, regardless of budget — preserves the
    #      existing diagnostic behavior (structure_recommended/ev_per_dollar
    #      still get logged with a clear "sizes to 0, budget was the binding
    #      constraint" note downstream) when nothing affordable exists at all.
    #   4. the overall top-ranked structure — final fallback.
    # dollar_risk is 0.0 below the real trading threshold (get_risk_pct
    # returns 0.0 under CONFIDENCE_THRESHOLD) — steps 1-2 then never match,
    # which is correct: sub-threshold signals are diagnostic-only and were
    # never going to be sized into a real position regardless.
    dollar_risk = get_risk_pct(confidence) * account_equity

    def _capped_risk_and_positive_ev(s: dict) -> bool:
        return s["name"] not in _GAP_RISK_STRUCTURES and s["ev"] > 0

    def _fits_tier_budget(s: dict) -> bool:
        return dollar_risk > 0 and s["capital_required"] <= dollar_risk

    recommended_structure = (
        next((s for s in ranked_structures if _capped_risk_and_positive_ev(s) and _fits_tier_budget(s)), None)
        or next((s for s in ranked_structures if s["name"] in _GAP_RISK_STRUCTURES and s["ev"] > 0 and _fits_tier_budget(s)), None)
        or next((s for s in ranked_structures if _capped_risk_and_positive_ev(s)), None)
        or (ranked_structures[0] if ranked_structures else None)
    )
    if recommended_structure is not None:
        recommended_structure["recommended"] = True

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
        "win_prob_used": round(win_prob, 4),
        "win_prob_calibrated": win_prob_calibrated,
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
    dte: Optional[int] = None,
    cfg: Optional[dict] = None,
) -> Optional[tuple[float, float, float, float, float, Optional[float], Optional[float], dict]]:
    """
    Compute EV for a structure. Uses surface method for complex (ratio/back
    spread) structures; resolve_structure_economics() (real Black-Scholes-
    derived avg_win/avg_loss/capital, see options_math.py) for the 35
    structures it covers; the original numeric-multiplier path only for the 3
    pure-stock structures neither of those two apply to.
    Returns (ev_per_dollar_risked, ev_raw, ev_adjusted, capital_required,
    effective_days, max_loss_dollars, max_gain_dollars, strikes) or None if
    insufficient data. ev_raw/ev_adjusted (pre/post slippage) let the
    liquidity filter (filter 5) measure how much of the edge a wide bid/ask
    consumes. capital_required is returned (not recomputed separately by the
    caller) so the ranking ratio and the $-cap filter always agree on the
    same number — the two disagreeing was the root cause of protective_put's
    capital estimate (a special-cased shortcut) making it rank far above
    married_put/collar despite near-identical real economics. effective_days
    is resolve_structure_economics' own per-structure time exposure (see its
    docstring — leaps_call/leaps_put and calendar_*/diagonal_* use more days
    than the shared dte) — falls back to the same shared dte/default for the
    surface-method and pure-stock-multiplier paths, which don't have a
    differentiated longer-dated leg to report. max_loss_dollars/
    max_gain_dollars/strikes come straight from resolve_structure_economics()
    (None/{} for the surface-method and pure-stock-multiplier paths, which
    don't compute real strikes at all — the surface path has no strike
    convention, per its own module docstring, and pure stock has no strike
    concept).
    """
    entry = float(candidate.get("entry", candidate.get("entry_mid", 0.0)))
    stop = float(candidate.get("stop_loss", candidate.get("stop", 0.0)))
    target = float(candidate.get("target", 0.0))

    # stop == entry is the only degenerate case — see resolve_structure_
    # economics' matching guard for why this isn't direction-specific
    # (bearish has stop > entry, not < entry, per risk_reward.py).
    if entry <= 0 or stop <= 0 or target <= 0 or stop == entry:
        return None

    # abs(): magnitudes of the favorable/unfavorable move either direction —
    # only used by the pure-stock fallback branch below (long_stock/
    # short_stock/long_stock_trailing_stop, the only structures where
    # resolve_structure_economics returns None) — same reasoning as
    # compute_ev_surface's identical fix in options_math.py.
    up_move = abs(target - entry)
    down_move = abs(entry - stop)
    default_days = max(dte if dte is not None else _DEFAULT_DTE_IF_UNKNOWN, 1)

    max_loss_dollars: Optional[float] = None
    max_gain_dollars: Optional[float] = None
    strikes: dict = {}

    if structure.get("ev_method") == "surface":
        surface = compute_ev_surface(
            structure=structure,
            entry=entry, stop=stop, target=target,
            win_probability=win_prob, iv=iv,
        )
        ev = surface["ev_weighted"]
        capital = _estimate_capital_required(structure_name, structure, entry, stop, target)
        effective_days = default_days
    else:
        econ = resolve_structure_economics(structure_name, entry, stop, target, iv, dte)
        if econ is not None:
            ev = compute_ev_simple(win_prob, econ["avg_win"], econ["avg_loss"])
            capital = econ["capital_required"]
            effective_days = econ.get("effective_days", default_days)
            max_loss_dollars = econ.get("max_loss_dollars")
            max_gain_dollars = econ.get("max_gain_dollars")
            strikes = econ.get("strikes", {})
        else:
            # Pure-stock structures only at this point — numeric multipliers,
            # already correct (see PASSTHROUGH_STRUCTURES in options_math.py).
            pm = structure.get("profit_mult", 1.0)
            lm = structure.get("loss_mult", 1.0)
            pm = pm if isinstance(pm, (int, float)) else 1.0
            lm = lm if isinstance(lm, (int, float)) else 1.0
            avg_win = up_move * pm
            avg_loss = down_move * lm
            ev = compute_ev_simple(win_prob, avg_win, avg_loss)
            capital = _estimate_capital_required(structure_name, structure, entry, stop, target)
            effective_days = default_days

    legs = structure.get("legs", 1)
    # Tier B batch 2/3 (2026-08-19): both slippage assumptions now read from
    # config (defaults match adjust_ev_for_slippage's prior hardcoded values
    # exactly). slippage_options_bid_ask_pct lives under the `backtesting:`
    # config section but is used here, in LIVE options-structure ranking, not
    # just the historical backtest — same shared value
    # backtesting/metrics.py's equity-curve slippage estimate uses for
    # slippage_stock_per_share.
    _slip_cfg = (cfg or {}).get("backtesting", {})
    slippage_per_share = float(_slip_cfg.get("slippage_stock_per_share", 0.02))
    slippage_pct_of_spread = float(_slip_cfg.get("slippage_options_bid_ask_pct", 0.50))
    ev_adjusted = adjust_ev_for_slippage(
        ev, structure_name, bid_ask_spread, legs,
        slippage_pct_of_spread=slippage_pct_of_spread, slippage_per_share=slippage_per_share,
    )
    if capital <= 0:
        return None
    return (ev_adjusted / capital, ev, ev_adjusted, capital, effective_days,
            max_loss_dollars, max_gain_dollars, strikes)


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
    # abs(): bearish stops sit above entry (entry - stop is negative there), not
    # below — the magnitude of the risk is what matters, for every structure
    # this feeds, not just the 3 stock ones below. Before this fix, a bearish
    # candidate floored to the $0.01 minimum here (since entry-stop was always
    # negative), which would have badly under-priced capital_required for
    # put_back_spread once the bearish R:R-filter bug (trade_selector.py's
    # rr computation) was fixed and bearish signals started reaching this far.
    risk_per_share = max(0.01, abs(entry - stop))

    if structure_name in _GAP_RISK_STRUCTURES:
        # Real dollar risk (stop distance), not full share price. Full price
        # was being used as both the EV-ranking denominator and the $-cap
        # filter's capital figure — diluting these 3 structures' ev_per_dollar
        # by roughly (share_price / stop_distance) versus every options
        # structure (which correctly uses premium-at-risk, not notional, as
        # capital_required), and wrongly excluding high-priced/tight-stop
        # names from the $-cap filter based on share price rather than actual
        # risk (e.g. a $1200 stock with a $90 stop was excluded outright for
        # costing more than the $750 cap, even though the real risk didn't).
        return risk_per_share  # Real dollar risk (stop distance), not full share price
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
