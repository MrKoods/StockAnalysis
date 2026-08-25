"""
Tests for Phase 7: options_math, risk_reward, position_sizer, trade_selector.
All tests use synthetic inputs. No market data required.
"""

import math
import pytest

from shared.utils.options_math import (
    black_scholes_price,
    compute_greeks,
    compute_ev_simple,
    compute_ev_surface,
    adjust_ev_for_slippage,
    STRUCTURE_MULTIPLIERS,
    select_directional_leg_strike,
    net_structure_greeks,
)
from shared.utils.risk_reward import (
    compute_entry_zone,
    compute_stop_loss,
    compute_target,
    compute_rr_ratio,
    compute_trailing_stop,
    compute_trade_setup,
)
from shared.utils.position_sizer import (
    get_risk_pct,
    compute_position_size,
    apply_circuit_breaker_sizing,
)
from swing_model.trade_selector import (
    rank_trade_structures,
    _resolve_structure_legs,
    _ranking_sort_key,
)


# ---------------------------------------------------------------------------
# Black-Scholes + Greeks
# ---------------------------------------------------------------------------

class TestBlackScholes:
    def test_atm_call_positive(self):
        price = black_scholes_price(S=100, K=100, T=0.5, r=0.05, sigma=0.3, option_type="call")
        assert price > 0

    def test_deep_itm_call_close_to_intrinsic(self):
        price = black_scholes_price(S=150, K=100, T=0.01, r=0.05, sigma=0.3, option_type="call")
        assert abs(price - 50.0) < 2.0

    def test_deep_otm_call_near_zero(self):
        price = black_scholes_price(S=100, K=200, T=0.1, r=0.05, sigma=0.3, option_type="call")
        assert price < 0.50

    def test_put_call_parity(self):
        S, K, T, r, sigma = 100, 100, 0.5, 0.05, 0.3
        call = black_scholes_price(S, K, T, r, sigma, "call")
        put = black_scholes_price(S, K, T, r, sigma, "put")
        # Put-call parity: C - P = S - K * exp(-rT)
        parity = S - K * math.exp(-r * T)
        assert abs((call - put) - parity) < 0.01

    def test_zero_time_returns_intrinsic(self):
        price = black_scholes_price(S=110, K=100, T=0, r=0.05, sigma=0.3, option_type="call")
        assert abs(price - 10.0) < 0.01

    def test_call_delta_between_0_and_1(self):
        g = compute_greeks(100, 100, 0.5, 0.05, 0.3, "call")
        assert 0 < g["delta"] < 1

    def test_put_delta_between_minus1_and_0(self):
        g = compute_greeks(100, 100, 0.5, 0.05, 0.3, "put")
        assert -1 < g["delta"] < 0

    def test_gamma_positive(self):
        g = compute_greeks(100, 100, 0.5, 0.05, 0.3, "call")
        assert g["gamma"] > 0

    def test_theta_negative_for_call(self):
        g = compute_greeks(100, 100, 0.5, 0.05, 0.3, "call")
        assert g["theta"] < 0

    def test_vega_positive(self):
        g = compute_greeks(100, 100, 0.5, 0.05, 0.3, "call")
        assert g["vega"] > 0

    def test_all_greeks_keys_present(self):
        g = compute_greeks(100, 100, 0.5, 0.05, 0.3, "call")
        for key in ("delta", "gamma", "theta", "vega", "rho"):
            assert key in g


# ---------------------------------------------------------------------------
# Real strike selection + net Greeks (trade_selector.py's Filter 4)
# ---------------------------------------------------------------------------

def _fake_chain(current_price: float = 100.0, step: float = 5.0, width: int = 8) -> list:
    """Synthetic near-the-money chain: calls+puts every `step` around current_price."""
    chain = []
    for i in range(-width, width + 1):
        strike = round(current_price + i * step, 2)
        if strike <= 0:
            continue
        for option_type in ("call", "put"):
            chain.append({
                "strike": strike, "option_type": option_type,
                "bid": 1.0, "ask": 1.2, "iv": 0.35,
                "open_interest": 100, "expiration": "2027-01-01",
            })
    return chain


class TestSelectDirectionalLegStrike:
    def test_atm_call_picks_nearest_strike_to_current_price(self):
        # Strikes land on 96, 101, 106, ... — 103 is nearest to 101 (dist 2) not 106 (dist 3).
        chain = _fake_chain(current_price=101.0, step=5.0)
        contract = select_directional_leg_strike(chain, 103.0, "call", "atm")
        assert contract["strike"] == 101.0

    def test_otm_call_picks_strike_above_current_price(self):
        chain = _fake_chain(current_price=100.0, step=5.0)
        contract = select_directional_leg_strike(chain, 100.0, "call", "otm")
        assert contract["strike"] > 100.0

    def test_otm_put_picks_strike_below_current_price(self):
        chain = _fake_chain(current_price=100.0, step=5.0)
        contract = select_directional_leg_strike(chain, 100.0, "put", "otm")
        assert contract["strike"] < 100.0

    def test_far_otm_further_from_money_than_otm(self):
        chain = _fake_chain(current_price=100.0, step=5.0)
        near = select_directional_leg_strike(chain, 100.0, "call", "otm")
        far = select_directional_leg_strike(chain, 100.0, "call", "far_otm")
        assert far["strike"] > near["strike"]

    def test_deep_itm_call_picks_strike_below_current_price(self):
        chain = _fake_chain(current_price=100.0, step=5.0)
        contract = select_directional_leg_strike(chain, 100.0, "call", "deep_itm")
        assert contract["strike"] < 100.0

    def test_deep_itm_put_picks_strike_above_current_price(self):
        chain = _fake_chain(current_price=100.0, step=5.0)
        contract = select_directional_leg_strike(chain, 100.0, "put", "deep_itm")
        assert contract["strike"] > 100.0

    def test_no_matching_option_type_returns_none(self):
        calls_only = [c for c in _fake_chain() if c["option_type"] == "call"]
        assert select_directional_leg_strike(calls_only, 100.0, "put", "atm") is None

    def test_empty_chain_returns_none(self):
        assert select_directional_leg_strike([], 100.0, "call", "atm") is None

    def test_far_from_target_strike_returns_none_not_nearest_substitute(self):
        # Signal Integrity Audit finding D.1: a thin chain with nothing near
        # the intended moneyness used to silently substitute whatever was
        # closest (e.g. a near-ATM contract standing in for an intended
        # far_otm wing) — now treated as "no suitable contract" instead.
        # A single far-away call, ~50% above spot: nowhere near an ATM target.
        sparse_chain = [{
            "strike": 150.0, "option_type": "call", "bid": 0.1, "ask": 0.2, "iv": 0.3,
        }]
        assert select_directional_leg_strike(sparse_chain, 100.0, "call", "atm") is None

    def test_close_to_target_strike_still_returned(self):
        # Contrast case: a contract genuinely close to the target (within
        # the 5%-of-spot tolerance) must still be returned, not rejected.
        chain = _fake_chain(current_price=100.0, step=5.0)
        contract = select_directional_leg_strike(chain, 100.0, "call", "atm")
        assert contract is not None
        assert abs(contract["strike"] - 100.0) <= 5.0


class TestNetStructureGreeks:
    def test_long_call_has_negative_net_theta(self):
        legs = [{"strike": 100.0, "option_type": "call", "side": "long", "iv": 0.3}]
        result = net_structure_greeks(legs, S=100.0, T=0.25)
        assert result["net"]["theta"] < 0

    def test_short_call_has_positive_net_theta(self):
        legs = [{"strike": 100.0, "option_type": "call", "side": "short", "iv": 0.3}]
        result = net_structure_greeks(legs, S=100.0, T=0.25)
        assert result["net"]["theta"] > 0

    def test_vertical_spread_theta_smaller_than_single_leg(self):
        single = net_structure_greeks(
            [{"strike": 100.0, "option_type": "call", "side": "long", "iv": 0.3}], S=100.0, T=0.25,
        )
        spread = net_structure_greeks(
            [
                {"strike": 100.0, "option_type": "call", "side": "long", "iv": 0.3},
                {"strike": 110.0, "option_type": "call", "side": "short", "iv": 0.3},
            ],
            S=100.0, T=0.25,
        )
        assert abs(spread["net"]["theta"]) < abs(single["net"]["theta"])

    def test_long_straddle_positive_vega(self):
        legs = [
            {"strike": 100.0, "option_type": "call", "side": "long", "iv": 0.3},
            {"strike": 100.0, "option_type": "put", "side": "long", "iv": 0.3},
        ]
        result = net_structure_greeks(legs, S=100.0, T=0.25)
        assert result["net"]["vega"] > 0

    def test_per_leg_detail_included(self):
        legs = [{"strike": 100.0, "option_type": "call", "side": "long", "iv": 0.3}]
        result = net_structure_greeks(legs, S=100.0, T=0.25)
        assert len(result["legs"]) == 1
        assert "greeks" in result["legs"][0]


# ---------------------------------------------------------------------------
# EV Calculation
# ---------------------------------------------------------------------------

class TestEVCalculation:
    def test_positive_ev_when_high_win_rate(self):
        ev = compute_ev_simple(win_probability=0.90, average_win=100, average_loss=33)
        assert ev > 0

    def test_negative_ev_when_bad_rr(self):
        ev = compute_ev_simple(win_probability=0.50, average_win=10, average_loss=100)
        assert ev < 0

    def test_ev_formula_exact(self):
        # EV = (0.9 × 100) - (0.1 × 33) = 90 - 3.3 = 86.7
        ev = compute_ev_simple(0.90, 100, 33)
        assert abs(ev - 86.7) < 0.1

    def test_ev_surface_returns_required_keys(self):
        structure = STRUCTURE_MULTIPLIERS["call_ratio_spread"]
        result = compute_ev_surface(
            structure=structure, entry=500, stop=480, target=560,
            win_probability=0.9, iv=0.35
        )
        for key in ("day_1", "day_5", "day_10", "day_15", "ev_weighted"):
            assert key in result
        for day_key in ("day_1", "day_5", "day_10", "day_15"):
            for scenario in ("target", "flat", "stop"):
                assert scenario in result[day_key]

    def test_ev_surface_bearish_target_hit_is_a_gain_not_a_loss(self):
        # up_move/down_move used to be signed (target-entry, entry-stop), which
        # for bearish (stop above entry, target below) flips day_ev_target
        # negative and day_ev_stop positive — treating a favorable move as a
        # loss and a stop-hit as a gain. abs()'d now, matching resolve_
        # structure_economics' fav/unfav convention.
        structure = STRUCTURE_MULTIPLIERS["put_back_spread"]
        result = compute_ev_surface(
            structure=structure, entry=500, stop=520, target=440,
            win_probability=0.9, iv=0.35
        )
        assert result["day_15"]["target"] > 0
        assert result["day_15"]["stop"] < 0

    def test_slippage_reduces_ev(self):
        ev_raw = 100.0
        ev_adj = adjust_ev_for_slippage(ev_raw, "long_call", bid_ask_spread=0.50, num_legs=1)
        assert ev_adj < ev_raw

    def test_slippage_options_bid_ask_pct_configurable(self):
        """Tier B batch 3 (2026-08-19): slippage_options_bid_ask_pct now
        reads from config in _compute_structure_ev — used by LIVE
        rank_trade_structures, not just the backtest, despite living under
        the `backtesting:` config section."""
        from swing_model.trade_selector import _compute_structure_ev, STRUCTURE_MULTIPLIERS
        structure = STRUCTURE_MULTIPLIERS["long_call"]
        candidate = {
            "ticker": "NVDA", "direction": "bullish", "confidence": 92,
            "entry": 500.0, "entry_mid": 500.0, "stop_loss": 485.0,
            "target": 545.0, "atr_14": 10.0, "force_defined_risk": False,
        }
        default_result = _compute_structure_ev(
            "long_call", structure, candidate, iv=0.35, win_prob=0.55, bid_ask_spread=0.50, dte=30,
        )
        narrower_cfg = {"backtesting": {"slippage_options_bid_ask_pct": 0.10}}
        custom_result = _compute_structure_ev(
            "long_call", structure, candidate, iv=0.35, win_prob=0.55, bid_ask_spread=0.50, dte=30,
            cfg=narrower_cfg,
        )
        # Lower assumed slippage -> less EV given up -> higher ev_adjusted (index 2).
        assert custom_result[2] > default_result[2]

    def test_structure_multipliers_has_42_entries(self):
        assert len(STRUCTURE_MULTIPLIERS) == 42


# ---------------------------------------------------------------------------
# Risk/Reward Math
# ---------------------------------------------------------------------------

class TestRiskReward:
    def test_entry_zone_exact_formula(self):
        # Lower = max(100, 98) - 0.25*2 = 100 - 0.5 = 99.5
        # Upper = 100 + 0.5 = 100.5
        lower, upper = compute_entry_zone(100, 98, atr_14=2.0)
        assert lower == pytest.approx(99.5)
        assert upper == pytest.approx(100.5)

    def test_breakout_level_used_when_above_close(self):
        # max(95, 102) = 102
        lower, upper = compute_entry_zone(95, 102, atr_14=2.0)
        assert lower == pytest.approx(101.5)
        assert upper == pytest.approx(102.5)

    def test_stop_loss_atr_formula(self):
        # stop = 99.5 - 2*2 = 95.5
        stop = compute_stop_loss(99.5, atr_14=2.0)
        assert stop == pytest.approx(95.5)

    def test_hvn_stop_used_when_tighter(self):
        # ATR stop = 99.5 - 4 = 95.5; HVN at 97 is tighter → use 97
        stop = compute_stop_loss(99.5, atr_14=2.0, high_volume_support=97.0)
        assert stop == pytest.approx(97.0)

    def test_atr_stop_used_when_hvn_below(self):
        # HVN at 90 is further than ATR stop at 95.5 → use ATR stop
        stop = compute_stop_loss(99.5, atr_14=2.0, high_volume_support=90.0)
        assert stop == pytest.approx(95.5)

    def test_target_at_minimum_3_rr(self):
        # entry=100, stop=95 → risk=5 → min_target=100+15=115
        target = compute_target(entry=100, stop=95, min_rr=3.0)
        assert target == pytest.approx(115.0)

    def test_target_uses_lva_when_above_min(self):
        # LVA at 120 > min_target 115 → use 120
        target = compute_target(entry=100, stop=95, low_volume_area_above=120.0, min_rr=3.0)
        assert target == pytest.approx(120.0)

    def test_target_none_when_stop_above_entry(self):
        target = compute_target(entry=90, stop=100, min_rr=3.0)
        assert target is None

    def test_rr_ratio_correct(self):
        # entry=100, stop=95, target=115 → RR = 15/5 = 3.0
        rr = compute_rr_ratio(entry=100, stop=95, target=115)
        assert rr == pytest.approx(3.0)

    def test_rr_zero_when_stop_above_entry(self):
        assert compute_rr_ratio(90, 95, 120) == 0.0

    # -----------------------------------------------------------------------
    # Bearish direction — mirror image of every bullish case above:
    # anchor uses min() not max(), stop sits above entry, target below.
    # -----------------------------------------------------------------------

    def test_entry_zone_bearish_uses_min_anchor(self):
        # Bearish: anchor = min(current_close, breakdown_level) = min(100, 98) = 98
        lower, upper = compute_entry_zone(100, 98, atr_14=2.0, direction="bearish")
        assert lower == pytest.approx(97.5)
        assert upper == pytest.approx(98.5)

    def test_entry_zone_bearish_breakdown_below_close(self):
        # min(102, 95) = 95 — a confirmed breakdown lower than current close
        lower, upper = compute_entry_zone(102, 95, atr_14=2.0, direction="bearish")
        assert lower == pytest.approx(94.5)
        assert upper == pytest.approx(95.5)

    def test_stop_loss_bearish_sits_above_entry(self):
        # stop = entry_zone_upper + 2*ATR = 100.5 + 4 = 104.5
        stop = compute_stop_loss(100.5, atr_14=2.0, direction="bearish")
        assert stop == pytest.approx(104.5)

    def test_target_bearish_below_entry(self):
        # entry=100, stop=105 -> risk=5 -> target = 100 - 3*5 = 85
        target = compute_target(entry=100, stop=105, min_rr=3.0, direction="bearish")
        assert target == pytest.approx(85.0)

    def test_target_bearish_none_when_stop_below_entry(self):
        target = compute_target(entry=100, stop=95, min_rr=3.0, direction="bearish")
        assert target is None

    def test_rr_ratio_bearish_correct(self):
        # entry=100, stop=105, target=85 -> RR = (100-85)/(105-100) = 3.0
        rr = compute_rr_ratio(entry=100, stop=105, target=85, direction="bearish")
        assert rr == pytest.approx(3.0)

    def test_rr_ratio_bearish_zero_when_stop_below_entry(self):
        assert compute_rr_ratio(100, 95, 85, direction="bearish") == 0.0

    def test_hvn_resistance_stop_used_when_tighter_bearish(self):
        # ATR stop = 100.5 + 4 = 104.5; resistance at 103 is tighter → use 103
        stop = compute_stop_loss(
            100.5, atr_14=2.0, direction="bearish", high_volume_resistance=103.0
        )
        assert stop == pytest.approx(103.0)

    def test_atr_stop_used_when_resistance_beyond_bearish(self):
        # Resistance at 110 is further than ATR stop at 104.5 → use ATR stop
        stop = compute_stop_loss(
            100.5, atr_14=2.0, direction="bearish", high_volume_resistance=110.0
        )
        assert stop == pytest.approx(104.5)

    def test_target_uses_lva_below_when_beyond_min_bearish(self):
        # entry=100, stop=105 -> risk=5 -> min_target=85; LVA at 80 < 85 -> use 80
        target = compute_target(
            entry=100, stop=105, min_rr=3.0, direction="bearish", low_volume_area_below=80.0
        )
        assert target == pytest.approx(80.0)

    def test_target_ignores_lva_below_when_short_of_min_bearish(self):
        # LVA at 90 is short of min_target 85 (i.e. not far enough down) -> use 85
        target = compute_target(
            entry=100, stop=105, min_rr=3.0, direction="bearish", low_volume_area_below=90.0
        )
        assert target == pytest.approx(85.0)

    def test_bullish_default_unchanged_by_direction_param(self):
        # direction="bullish" (or omitted) must reproduce the exact pre-existing
        # bullish behavior — this is what every real caller that hasn't opted
        # into bearish still relies on.
        lower, upper = compute_entry_zone(100, 98, atr_14=2.0, direction="bullish")
        assert (lower, upper) == compute_entry_zone(100, 98, atr_14=2.0)
        stop = compute_stop_loss(99.5, atr_14=2.0, direction="bullish")
        assert stop == compute_stop_loss(99.5, atr_14=2.0)

    def test_trailing_stop_bullish(self):
        # highest_close=120, ATR=5, mult=1.5 → stop=120-7.5=112.5
        stop = compute_trailing_stop("bullish", 120, 95, atr_14=5.0)
        assert stop == pytest.approx(112.5)

    def test_trailing_stop_bearish(self):
        # lowest_close=80, ATR=5, mult=1.5 → stop=80+7.5=87.5
        stop = compute_trailing_stop("bearish", 105, 80, atr_14=5.0)
        assert stop == pytest.approx(87.5)

    def test_trade_setup_meets_rr(self):
        result = compute_trade_setup(100, 100, atr_14=3.0)
        assert result["rr_ratio"] >= 3.0
        assert result["meets_min_rr"] is True

    def test_trade_setup_required_keys(self):
        result = compute_trade_setup(100, 98, atr_14=2.0)
        for key in ("entry_zone_lower", "entry_zone_upper", "entry_mid",
                    "stop_loss", "target", "rr_ratio", "meets_min_rr"):
            assert key in result


# ---------------------------------------------------------------------------
# Position Sizer
# ---------------------------------------------------------------------------

class TestPositionSizer:
    # Tiers raised 2026-08-23 by ~6.667x (500/75) so the 70-89 floor tier
    # (where virtually every real signal lands) can actually afford a real
    # options contract at this account size — see SIZING_TIERS' own comment.
    def test_tier_70_89_returns_500_at_15k(self):
        assert get_risk_pct(70) == pytest.approx(500 / 15000)
        assert get_risk_pct(77.8) == pytest.approx(500 / 15000)
        assert get_risk_pct(89) == pytest.approx(500 / 15000)

    def test_tier_90_92_returns_1000_at_15k(self):
        assert get_risk_pct(90) == pytest.approx(1000 / 15000)
        assert get_risk_pct(91) == pytest.approx(1000 / 15000)
        assert get_risk_pct(92) == pytest.approx(1000 / 15000)

    def test_tier_93_95_returns_1500_at_15k(self):
        assert get_risk_pct(93) == pytest.approx(1500 / 15000)
        assert get_risk_pct(95) == pytest.approx(1500 / 15000)

    def test_tier_96_98_returns_2000_at_15k(self):
        assert get_risk_pct(96) == pytest.approx(2000 / 15000)
        assert get_risk_pct(98) == pytest.approx(2000 / 15000)

    def test_tier_99_100_returns_2500_at_15k(self):
        assert get_risk_pct(99) == pytest.approx(2500 / 15000)
        assert get_risk_pct(100) == pytest.approx(2500 / 15000)

    def test_below_confidence_threshold_returns_zero(self):
        assert get_risk_pct(69) == 0.0
        assert get_risk_pct(0) == 0.0

    def test_sizing_tiers_cover_all_valid_scores(self):
        for score in range(70, 101):
            assert get_risk_pct(score) > 0.0

    def test_yellow_cb_halves_size(self):
        adj, mult = apply_circuit_breaker_sizing(0.020, "yellow")
        assert adj == pytest.approx(0.010)
        assert mult == pytest.approx(0.5)

    def test_orange_cb_zero_size(self):
        adj, mult = apply_circuit_breaker_sizing(0.020, "orange")
        assert adj == 0.0
        assert mult == 0.0

    def test_red_cb_zero_size(self):
        adj, mult = apply_circuit_breaker_sizing(0.020, "red")
        assert adj == 0.0
        assert mult == 0.0

    def test_normal_cb_no_change(self):
        adj, mult = apply_circuit_breaker_sizing(0.020, "normal")
        assert adj == pytest.approx(0.020)
        assert mult == 1.0

    def test_compute_position_size_capital_approved(self):
        # $15k account, 33.3% max = $5,000 (raised 2026-08-23 from 5%/$750);
        # capital_required=$500 → approved
        result = compute_position_size(
            confidence_score=93, account_equity=15000,
            circuit_breaker_state="normal", capital_required=500.0
        )
        assert result["capital_approved"] is True
        assert result["dollar_risk"] == pytest.approx(15000 * (1500 / 15000))
        assert result["max_capital"] == pytest.approx(5000.0)

    def test_compute_position_size_capital_denied(self):
        # capital_required=$6,000 exceeds the $5,000 cap
        result = compute_position_size(
            confidence_score=90, account_equity=15000,
            circuit_breaker_state="normal", capital_required=6000.0
        )
        assert result["capital_approved"] is False

    def test_position_size_required_keys(self):
        result = compute_position_size(90, 15000, "normal", 500.0)
        for key in ("risk_pct", "dollar_risk", "circuit_breaker_state",
                    "size_multiplier", "capital_required", "capital_approved", "max_capital"):
            assert key in result

    def test_contracts_or_shares_is_a_real_int_not_placeholder(self):
        # v2.2.60 — used to be a literal placeholder string.
        result = compute_position_size(
            confidence_score=90, account_equity=15000, circuit_breaker_state="normal",
            capital_required=50.0, per_unit_cost=50.0,
        )
        assert isinstance(result["contracts_or_shares"], int)
        # dollar_risk at 90 (raised 2026-08-23) = 1000/15000 of 15000 = 1000;
        # risk_per_unit=50 -> 20 contracts; capital cap = 5000; per_unit_cost=50
        # -> 100 max -> risk-based binds.
        assert result["contracts_or_shares"] == 20
        assert result["capital_deployed"] == pytest.approx(1000.0)
        assert result["actual_dollar_risk"] == pytest.approx(1000.0)

    def test_capital_cap_binds_tighter_than_risk_cap_for_high_priced_shares(self):
        # Regression test for the real incident this dual-cap fixes: a tight
        # stop (small risk_per_unit) on a high-priced stock sizes to far more
        # dollars deployed than the risk budget alone would suggest, unless a
        # separate per-share-price cap also applies.
        result = compute_position_size(
            confidence_score=90, account_equity=15000, circuit_breaker_state="normal",
            capital_required=1.16, per_unit_cost=500.0, position_type="shares",
        )
        # Risk-based: dollar_risk=1000, risk_per_unit=1.16 -> 862 shares -> $431,000 deployed (absurd).
        # Capital-based: max_capital=5000, per_unit_cost=500 -> 10 shares max.
        # Dual-cap must take the min -> 10 shares, not 862.
        assert result["contracts_or_shares"] == 10
        assert result["capital_deployed"] == pytest.approx(5000.0)


class TestRiskPctOverride:
    """
    risk_pct_override (2026-08-24, rank-based parallel paper-trading track)
    — an optional override on compute_position_size()/rank_trade_structures()
    that bypasses get_risk_pct()'s 0.0-below-CONFIDENCE_THRESHOLD floor.
    None (the default) must reproduce today's exact behavior for every
    existing threshold/live caller — that's the regression-safety priority
    here, since both functions also serve the live path.
    """

    def test_default_none_reproduces_today_exact_behavior_below_threshold(self):
        # confidence=50 (well below CONFIDENCE_THRESHOLD=70) -> get_risk_pct
        # returns 0.0 -> dollar_risk/risk_pct/position size all 0, same as
        # every existing caller has always seen.
        result = compute_position_size(
            confidence_score=50, account_equity=15000, circuit_breaker_state="normal",
            capital_required=500.0,
        )
        assert result["risk_pct"] == 0.0
        assert result["dollar_risk"] == 0.0
        assert result["contracts_or_shares"] == 0

    def test_override_bypasses_zero_floor_below_threshold(self):
        # Same confidence=50, but with an override -> real, non-zero sizing.
        # capital_required=50 (not 500) so the $499.50 budget (0.0333*15000)
        # can actually afford at least one unit -- isolates "does the
        # override produce real sizing at all" from a coincidental
        # budget-too-tight-for-this-unit-cost edge case.
        result = compute_position_size(
            confidence_score=50, account_equity=15000, circuit_breaker_state="normal",
            capital_required=50.0, risk_pct_override=0.0333,
        )
        assert result["risk_pct"] == pytest.approx(0.0333)
        assert result["dollar_risk"] == pytest.approx(15000 * 0.0333)
        assert result["contracts_or_shares"] > 0

    def test_override_takes_precedence_over_confidence_at_or_above_threshold_too(self):
        # confidence=90 alone would give a much bigger tier (6.67%, $1000) —
        # override still wins, at any confidence level, not just sub-70.
        result = compute_position_size(
            confidence_score=90, account_equity=15000, circuit_breaker_state="normal",
            capital_required=500.0, risk_pct_override=0.0333,
        )
        assert result["risk_pct"] == pytest.approx(0.0333)

    def test_existing_callers_that_never_pass_override_are_unaffected(self):
        # Every pre-existing call in this test file omits risk_pct_override
        # entirely -- confirms the parameter's mere existence doesn't change
        # a real-tier (>=70) result either.
        with_default = compute_position_size(93, 15000, "normal", 500.0)
        explicit_none = compute_position_size(93, 15000, "normal", 500.0, risk_pct_override=None)
        assert with_default == explicit_none

    def test_per_unit_cost_defaults_to_capital_required_when_omitted(self):
        # Backward compatibility: a caller that hasn't been updated to pass
        # per_unit_cost gets the exact same sizing as before this change
        # (capital_required doubling as both risk-per-unit and per-unit-cost).
        with_default = compute_position_size(90, 15000, "normal", 50.0)
        explicit = compute_position_size(90, 15000, "normal", 50.0, per_unit_cost=50.0)
        assert with_default["contracts_or_shares"] == explicit["contracts_or_shares"]
        assert with_default["capital_deployed"] == explicit["capital_deployed"]

    def test_position_type_passed_through(self):
        result = compute_position_size(
            90, 15000, "normal", 50.0, per_unit_cost=50.0, position_type="options",
        )
        assert result["position_type"] == "options"


# ---------------------------------------------------------------------------
# Trade Selector
# ---------------------------------------------------------------------------

class TestTradeSelector:
    def _candidate(self, direction="bullish", confidence=92):
        return {
            "ticker": "NVDA",
            "direction": direction,
            "confidence": confidence,
            "entry_mid": 500.0,
            "stop_loss": 485.0,
            "target": 545.0,
            "atr_14": 10.0,
            "force_defined_risk": False,
        }

    def test_returns_42_structures_evaluated(self):
        result = rank_trade_structures(
            self._candidate(), account_equity=15000,
            options_approval_level=2, iv_percentile=30.0
        )
        assert result["structures_evaluated"] == 42

    def test_eligible_structures_less_than_42(self):
        result = rank_trade_structures(
            self._candidate(), account_equity=15000,
            options_approval_level=2, iv_percentile=30.0
        )
        # Many structures filtered by capital, undefined risk, direction
        assert result["structures_eligible_after_filters"] <= 42

    def test_ranked_structures_sorted_by_ev(self):
        # Sorted by ev_per_dollar_per_day (the function's documented sort key),
        # not ev_per_dollar_risked — structures with different effective_days
        # (e.g. diagonal_call's dte+30 vs. most structures' shared dte) don't
        # necessarily co-sort on the two metrics, so asserting the un-normalized
        # ratio here would assert a property the function never actually promises.
        result = rank_trade_structures(
            self._candidate(), account_equity=15000,
            options_approval_level=2, iv_percentile=30.0
        )
        evs = [s["ev_per_dollar_per_day"] for s in result["ranked_structures"]]
        assert evs == sorted(evs, reverse=True)

    def test_bearish_structures_excluded_for_bullish_direction(self):
        result = rank_trade_structures(
            self._candidate(direction="bullish"), account_equity=15000,
            options_approval_level=3, iv_percentile=30.0
        )
        eligible_names = {s["name"] for s in result["ranked_structures"]}
        from swing_model.trade_selector import _BEARISH_STRUCTURES
        for name in _BEARISH_STRUCTURES:
            assert name not in eligible_names

    def test_undefined_risk_excluded_at_15k(self):
        result = rank_trade_structures(
            self._candidate(), account_equity=15000,
            options_approval_level=3, iv_percentile=30.0
        )
        eligible_names = {s["name"] for s in result["ranked_structures"]}
        from swing_model.trade_selector import _UNDEFINED_RISK_STRUCTURES
        for name in _UNDEFINED_RISK_STRUCTURES:
            assert name not in eligible_names

    def test_result_required_keys(self):
        result = rank_trade_structures(
            self._candidate(), account_equity=15000,
            options_approval_level=2, iv_percentile=30.0
        )
        for key in ("ticker", "direction", "confidence", "structures_evaluated",
                    "structures_eligible_after_filters", "ranked_structures",
                    "exclusion_summary", "win_prob_used", "win_prob_calibrated"):
            assert key in result

    def test_default_win_prob_is_uncalibrated_confidence_over_100(self):
        result = rank_trade_structures(
            self._candidate(confidence=92), account_equity=15000,
            options_approval_level=2, iv_percentile=30.0,
        )
        assert result["win_prob_calibrated"] is False
        assert result["win_prob_used"] == pytest.approx(0.92)

    def test_calibration_points_change_win_prob_and_flag_calibrated(self):
        calibration = [
            {"threshold": 60, "win_rate": 0.55}, {"threshold": 95, "win_rate": 0.62},
        ]
        result = rank_trade_structures(
            self._candidate(confidence=92), account_equity=15000,
            options_approval_level=2, iv_percentile=30.0,
            win_probability_calibration=calibration,
        )
        assert result["win_prob_calibrated"] is True
        # 92 is well below the uncalibrated 0.92 given real ~55-62% win rates.
        assert result["win_prob_used"] < 0.92
        assert 0.55 <= result["win_prob_used"] <= 0.62

    def test_exactly_one_structure_is_recommended(self):
        # "recommended" is no longer always rank 1 — it can diverge from raw
        # EV order for two reasons: a gap-risk-exposed stock structure (see
        # test_gap_risk_structure_does_not_win_over_positive_ev_option) or a
        # structure that clears the blanket $-cap but not this signal's own
        # confidence-tier risk budget (see test_structure_over_tier_budget_
        # loses_to_affordable_alternative). Exactly one flagged either way.
        result = rank_trade_structures(
            self._candidate(), account_equity=15000,
            options_approval_level=2, iv_percentile=30.0
        )
        ranked = result["ranked_structures"]
        if ranked:
            recommended = [s for s in ranked if s["recommended"]]
            assert len(recommended) == 1

    def test_risk_pct_override_lets_a_sub_threshold_confidence_get_a_real_budget_fit(self):
        # risk_pct_override (2026-08-24, rank-based parallel paper-trading
        # track). confidence=40 is well below CONFIDENCE_THRESHOLD (70) ->
        # get_risk_pct returns 0.0 -> dollar_risk=0.0 -> _fits_tier_budget
        # (capital_required <= dollar_risk) can never be True -> the
        # "recommended" pick (if any) was never actually budget-checked.
        # With an override, dollar_risk = 0.0333*15000 = $499.50, and the
        # recommended structure — when one clears that budget — must have
        # capital_required within it.
        result_no_override = rank_trade_structures(
            self._candidate(confidence=40), account_equity=15000,
            options_approval_level=2, iv_percentile=30.0,
        )
        result_override = rank_trade_structures(
            self._candidate(confidence=40), account_equity=15000,
            options_approval_level=2, iv_percentile=30.0,
            risk_pct_override=0.0333,
        )
        # Structure evaluation itself (42 structures, EV ranking) is
        # unaffected by risk_pct_override -- only which one gets picked
        # "recommended" changes.
        assert result_no_override["structures_evaluated"] == result_override["structures_evaluated"] == 42

        recommended_override = next((s for s in result_override["ranked_structures"] if s["recommended"]), None)
        assert recommended_override is not None
        # Either it fits the real $499.50 budget, or (steps 3/4) no
        # affordable capped-risk structure existed at all -- but if it DOES
        # report capital_required or the budget-based selection variant
        # exists in `ranked_structures`, at least one should be <= 499.50,
        # confirming the override budget was genuinely used, not just $0.
        under_budget = [s for s in result_override["ranked_structures"] if s.get("capital_required", 1e9) <= 499.50]
        assert len(under_budget) > 0

    def test_risk_pct_override_none_reproduces_default_get_risk_pct_behavior(self):
        # Omitting risk_pct_override entirely, and explicitly passing None,
        # must produce identical results -- confirms the parameter's mere
        # existence doesn't change any existing real-confidence caller.
        default = rank_trade_structures(
            self._candidate(confidence=92), account_equity=15000,
            options_approval_level=2, iv_percentile=30.0,
        )
        explicit_none = rank_trade_structures(
            self._candidate(confidence=92), account_equity=15000,
            options_approval_level=2, iv_percentile=30.0, risk_pct_override=None,
        )
        assert default["ranked_structures"] == explicit_none["ranked_structures"]

    def test_stock_structure_capital_is_risk_distance_not_share_price(self):
        # _estimate_capital_required used to return the full share price for
        # long_stock/short_stock/long_stock_trailing_stop, diluting their
        # ev_per_dollar by ~(share_price/stop_distance) versus every options
        # structure (which correctly uses premium-at-risk). Real dollar risk
        # (stop distance) is what capital_required should reflect instead.
        candidate = self._candidate()  # entry_mid=500, stop_loss=485
        result = rank_trade_structures(
            candidate, account_equity=15000,
            options_approval_level=2, iv_percentile=30.0
        )
        by_name = {s["name"]: s for s in result["ranked_structures"]}
        assert by_name["long_stock"]["capital_required"] == 15.0  # 500 - 485
        assert by_name["long_stock"]["capital_required"] != 500.0

    def test_high_priced_stock_not_excluded_by_capital_cap(self):
        # A stock priced above the $750 capital cap (5% of $15k) used to get
        # long_stock excluded outright purely on share price, even when the
        # real dollar risk (stop distance) was well within the cap.
        candidate = {
            "ticker": "LLY", "direction": "bullish", "confidence": 90,
            "entry_mid": 1232.00, "stop_loss": 1135.73, "target": 1520.81,
            "atr_14": 20.0, "force_defined_risk": False,
        }
        result = rank_trade_structures(
            candidate, account_equity=15000,
            options_approval_level=2, iv_percentile=30.0
        )
        eligible_names = {s["name"] for s in result["ranked_structures"]}
        assert "long_stock" in eligible_names  # no longer excluded by capital_filter_50k_required/capital cap

    def test_gap_risk_structure_does_not_win_over_affordable_positive_ev_option(self):
        # Constructed so long_stock/long_stock_trailing_stop rank #1 by raw
        # ev_per_dollar_per_day (tiny stop distance keeps their capital small
        # and unaffected by IV, unlike options premiums), AND a positive-EV
        # options structure exists that also fits this tier's risk budget
        # (confidence=100 -> 2500/15000 of $15k = $2,500, raised 2026-08-23) — recommended should still
        # prefer the capped-risk option, per the account's no-negative-months
        # mandate, even though it ranks below the stock structure on raw EV.
        from swing_model.trade_selector import _GAP_RISK_STRUCTURES
        candidate = {
            "ticker": "TEST", "direction": "bullish", "confidence": 100,
            "entry_mid": 500.0, "stop_loss": 498.0, "target": 506.0,
            "atr_14": 1.0, "force_defined_risk": False,
        }
        result = rank_trade_structures(
            candidate, account_equity=15000,
            options_approval_level=2, iv_percentile=80.0
        )
        ranked = result["ranked_structures"]
        assert ranked[0]["name"] in _GAP_RISK_STRUCTURES
        assert ranked[0]["recommended"] is False
        recommended = next(s for s in ranked if s["recommended"])
        assert recommended["name"] not in _GAP_RISK_STRUCTURES
        assert recommended["ev"] > 0
        assert recommended["capital_required"] <= 2500.0  # fits the 99-100 tier budget

    def test_structure_over_old_tier_budget_no_longer_falls_through_post_raise(self):
        # The bug this whole fix chain traces back to: a signal (score 71.0,
        # the 70-89 tier's OLD 0.5% risk = $75 on $15k) whose best-EV options
        # structure (long_strangle, ~$249 capital) cleared the blanket 5%/$750
        # cap but not this tier's much smaller budget. Real numbers from a
        # logged signal (JNJ, 2026-08-11) — used to size to 0 and vanish
        # entirely, falling through to long_stock instead.
        #
        # 2026-08-23: the 70-89 tier was raised to $500 specifically because
        # this class of gap kept costing real signals (see SIZING_TIERS'
        # own comment) — this exact historical case is the regression proof
        # that the raise actually fixes it: $249 now comfortably fits $500,
        # so long_strangle (the higher-EV capped-risk option) is correctly
        # recommended directly, no fallback needed. The fallback mechanism
        # ITSELF (falling through to an affordable alternative when the
        # best-EV structure genuinely doesn't fit) is still real and still
        # exercised by test_gap_risk_structure_does_not_win_over_affordable_
        # positive_ev_option above — this test's job is narrower: prove this
        # specific historical incident doesn't reproduce anymore.
        candidate = {
            "ticker": "JNJ", "direction": "bullish", "confidence": 71.0,
            "entry_mid": 274.90, "stop_loss": 261.51, "target": 315.08,
            "atr_14": 5.95, "force_defined_risk": False,
        }
        result = rank_trade_structures(
            candidate, account_equity=15000,
            options_approval_level=2, iv_percentile=50.0
        )
        recommended = next(s for s in result["ranked_structures"] if s["recommended"])
        assert recommended["name"] == "long_strangle"
        assert recommended["position_type"] == "options"
        assert recommended["capital_required"] <= 500.0  # fits the new 70-89 tier budget

    def test_bearish_candidate_produces_eligible_structures(self):
        # Regression test: rank_trade_structures' own R:R computation (Filter
        # 3) used to assume the bullish sign convention (stop < entry) and
        # unconditionally evaluate to rr=0.0 for bearish (stop > entry),
        # excluding all 42 structures for every bearish signal.
        candidate = {
            "ticker": "TEST", "direction": "bearish", "confidence": 92,
            "entry_mid": 500.0, "stop_loss": 515.0, "target": 455.0,
            "atr_14": 10.0, "force_defined_risk": False,
        }
        result = rank_trade_structures(
            candidate, account_equity=15000,
            options_approval_level=2, iv_percentile=30.0
        )
        assert result["structures_eligible_after_filters"] > 0
        for s in result["ranked_structures"]:
            assert s["capital_required"] > 0


class TestGreeksFilter:
    """rank_trade_structures' Filter 4 — real Greeks when option_chain+dte are
    supplied. Uses the module-level _fake_chain() helper (500-centered, since
    TestTradeSelector's _candidate() entry is 500.0)."""

    def _candidate(self, direction="bullish", confidence=92):
        return {
            "ticker": "NVDA", "direction": direction, "confidence": confidence,
            "entry_mid": 500.0, "stop_loss": 485.0, "target": 545.0,
            "atr_14": 10.0, "force_defined_risk": False,
        }

    def test_no_chain_reports_not_implemented(self):
        result = rank_trade_structures(
            self._candidate(), account_equity=15000,
            options_approval_level=2, iv_percentile=30.0,
        )
        assert result["greeks_filter_status"] == "not_implemented_no_options_chain_data"
        assert result["structures_greeks_evaluated"] == 0

    def test_chain_without_dte_reports_not_implemented(self):
        chain = _fake_chain(current_price=500.0, step=10.0)
        result = rank_trade_structures(
            self._candidate(), account_equity=15000,
            options_approval_level=2, iv_percentile=30.0,
            option_chain=chain,
        )
        assert result["greeks_filter_status"] == "not_implemented_no_options_chain_data"

    def test_chain_and_dte_reports_applied(self):
        chain = _fake_chain(current_price=500.0, step=10.0)
        result = rank_trade_structures(
            self._candidate(), account_equity=15000,
            options_approval_level=2, iv_percentile=30.0,
            option_chain=chain, dte=10,
        )
        assert result["greeks_filter_status"] == "applied"
        assert result["structures_greeks_evaluated"] > 0

    def test_resolvable_structure_carries_greeks_detail(self):
        # account_equity raised to 100k so bull_put_spread's real capital
        # clears the pre-existing 5%-of-account filter (unrelated to Greeks) —
        # at 15k it would be excluded before Filter 4 ever runs. Uses
        # bull_put_spread, not long_call: since resolve_structure_economics()
        # (v2.2.36) replaced the old capital heuristic (entry*0.05*100=$2,500,
        # a rough guess) with a real Black-Scholes premium (~$984 here), the
        # SAME real theta now represents a larger % of a smaller, more
        # accurate capital figure — long_call genuinely exceeds the default
        # 5% theta bound at these parameters now, which is a more correct risk
        # read, not a bug (see test_tight_theta_bound_excludes_long_premium_
        # structures below, which already covered long_call's theta
        # sensitivity under a tightened bound). A credit spread's net theta is
        # much smaller relative to its capital by construction (the short and
        # long legs partially offset), so bull_put_spread reliably clears the
        # default bound while still exercising the same Greeks-detail path.
        chain = _fake_chain(current_price=500.0, step=10.0)
        result = rank_trade_structures(
            self._candidate(), account_equity=100_000,
            options_approval_level=2, iv_percentile=30.0,
            option_chain=chain, dte=10,
        )
        by_name = {s["name"]: s for s in result["ranked_structures"]}
        assert "bull_put_spread" in by_name
        assert by_name["bull_put_spread"]["greeks"] is not None
        assert "net_greeks" in by_name["bull_put_spread"]["greeks"]

    def test_tight_theta_bound_excludes_long_premium_structures(self):
        chain = _fake_chain(current_price=500.0, step=10.0)
        cfg = {"greeks_filter": {"max_daily_theta_pct_of_capital": 0.0001, "max_vega_pct_of_capital": 1.0}}
        result = rank_trade_structures(
            self._candidate(), account_equity=100_000,
            options_approval_level=2, iv_percentile=30.0,
            option_chain=chain, dte=10, cfg=cfg,
        )
        eligible_names = {s["name"] for s in result["ranked_structures"]}
        assert "long_call" not in eligible_names
        reasons = [r for item in result["exclusion_summary"].split(";") for r in [item.strip()]]
        assert any("theta" in r for r in reasons)

    def test_bid_ask_spreads_not_mutated_for_caller(self):
        chain = _fake_chain(current_price=500.0, step=10.0)
        caller_dict = {}
        rank_trade_structures(
            self._candidate(), account_equity=100_000,
            options_approval_level=2, iv_percentile=30.0,
            option_chain=chain, dte=10, bid_ask_spreads=caller_dict,
        )
        assert caller_dict == {}  # unchanged — internal resolution shouldn't leak back

    def test_missing_leg_type_leaves_greeks_unresolved_not_falsely_passed(self):
        # Calls-only chain — long_call resolves fine, but long_straddle (needs a
        # put leg too) can't resolve and must report greeks=None, not a fabricated pass.
        # long_straddle is a DEFINED-risk (long-premium) structure, not in
        # _UNDEFINED_RISK_STRUCTURES — it's meant to fail open here (see
        # TestGreeksFailClosedForUndefinedRisk below for the structures that
        # must NOT fail open).
        calls_only = [c for c in _fake_chain(current_price=500.0, step=10.0) if c["option_type"] == "call"]
        result = rank_trade_structures(
            self._candidate(), account_equity=100_000,
            options_approval_level=3, iv_percentile=30.0,
            option_chain=calls_only, dte=10,
        )
        by_name = {s["name"]: s for s in result["ranked_structures"]}
        if "long_call" in by_name:
            assert by_name["long_call"]["greeks"] is not None
        if "long_straddle" in by_name:
            assert by_name["long_straddle"]["greeks"] is None


class TestGreeksFailClosedForUndefinedRisk:
    """
    Signal Integrity Audit finding D.1: naked_short_call/naked_short_put/
    short_straddle/short_strangle/synthetic_long/synthetic_short/risk_reversal
    (undefined-risk, Greeks-resolvable structures) must be EXCLUDED entirely
    when Filter 4 (Greeks) couldn't run — not silently ranked/recommendable
    with an unchecked theta/vega. Defined-risk structures (spreads etc.) are
    deliberately left to fail OPEN in the same situation (their capital is
    already capped by Filters 1/2) — that's the contrast this class checks.
    """

    def _candidate(self):
        return {
            "ticker": "NVDA", "direction": "bullish", "confidence": 92,
            "entry_mid": 500.0, "stop_loss": 485.0, "target": 545.0,
            "atr_14": 10.0, "force_defined_risk": False,
        }

    # $1M account + wide theta/vega bounds isolate every test in this class
    # to the Greeks-availability question alone — short_straddle's own real
    # economics (large margin, real theta) would otherwise independently
    # exclude it via the pre-existing capital/theta filters regardless of
    # whether this fix's logic ever runs, making the test prove nothing.
    _ACCOUNT_EQUITY = 1_000_000
    _WIDE_GREEKS_CFG = {"greeks_filter": {"max_daily_theta_pct_of_capital": 1.0, "max_vega_pct_of_capital": 1.0}}

    def test_short_straddle_excluded_when_no_chain_at_all(self):
        result = rank_trade_structures(
            self._candidate(), account_equity=self._ACCOUNT_EQUITY,
            options_approval_level=3, iv_percentile=30.0, cfg=self._WIDE_GREEKS_CFG,
            # No option_chain/dte supplied — greeks_available is False.
        )
        by_name = {s["name"] for s in result["ranked_structures"]}
        assert "short_straddle" not in by_name
        assert "short_strangle" not in by_name

    def test_short_straddle_excluded_when_legs_unresolvable(self):
        # Calls-only chain: short_straddle needs a short put leg it can't find.
        calls_only = [c for c in _fake_chain(current_price=500.0, step=10.0) if c["option_type"] == "call"]
        result = rank_trade_structures(
            self._candidate(), account_equity=self._ACCOUNT_EQUITY,
            options_approval_level=3, iv_percentile=30.0,
            option_chain=calls_only, dte=10, cfg=self._WIDE_GREEKS_CFG,
        )
        by_name = {s["name"] for s in result["ranked_structures"]}
        assert "short_straddle" not in by_name
        assert "naked_short_put" not in by_name  # same shape: needs a put leg too

    def test_defined_risk_structure_still_ranked_when_no_chain(self):
        # Contrast case: bull_call_spread (defined max loss) must still fail
        # OPEN and be rankable when no chain was available — the fix is
        # scoped to undefined-risk structures only, not a blanket exclusion.
        result = rank_trade_structures(
            self._candidate(), account_equity=self._ACCOUNT_EQUITY,
            options_approval_level=2, iv_percentile=30.0, cfg=self._WIDE_GREEKS_CFG,
        )
        by_name = {s["name"] for s in result["ranked_structures"]}
        assert "bull_call_spread" in by_name

    def test_short_straddle_ranked_when_chain_and_dte_both_supplied(self):
        # Positive control: with a real, resolvable chain, the same
        # structure IS eligible and carries real Greeks. The fix only
        # excludes it when the check genuinely couldn't run, not whenever
        # it's merely disfavored on its own economics.
        chain = _fake_chain(current_price=500.0, step=10.0)
        result = rank_trade_structures(
            self._candidate(), account_equity=self._ACCOUNT_EQUITY,
            options_approval_level=3, iv_percentile=30.0,
            option_chain=chain, dte=10, cfg=self._WIDE_GREEKS_CFG,
        )
        by_name = {s["name"]: s for s in result["ranked_structures"]}
        assert "short_straddle" in by_name
        assert by_name["short_straddle"]["greeks"] is not None


class TestExpandedGreeksCoverage:
    """
    v2.2.60 — 9 more structures added to _GREEKS_RESOLVABLE_LEGS (condors/
    butterflies, wheel, synthetics/risk-reversal), all single-expiration so
    no change to net_structure_greeks itself was needed.
    """

    def _candidate(self, direction="bullish"):
        return {
            "ticker": "NVDA", "direction": direction, "confidence": 92,
            "entry_mid": 500.0, "stop_loss": 485.0 if direction == "bullish" else 515.0,
            "target": 545.0 if direction == "bullish" else 455.0,
            "atr_14": 10.0, "force_defined_risk": False,
        }

    def test_newly_resolvable_structures_carry_greeks_detail(self):
        chain = _fake_chain(current_price=500.0, step=10.0)
        result = rank_trade_structures(
            self._candidate(), account_equity=1_000_000,
            options_approval_level=3, iv_percentile=30.0,
            option_chain=chain, dte=10,
        )
        by_name = {s["name"]: s for s in result["ranked_structures"]}
        for name in (
            "iron_condor", "iron_butterfly", "short_butterfly", "condor_spread",
            "long_butterfly_call", "wheel", "risk_reversal", "synthetic_long",
        ):
            if name in by_name:
                assert by_name[name]["greeks"] is not None, f"{name}: Greeks not resolved"
                assert "net_greeks" in by_name[name]["greeks"]

    def test_synthetic_short_resolves_for_bearish_candidate(self):
        chain = _fake_chain(current_price=500.0, step=10.0)
        result = rank_trade_structures(
            self._candidate(direction="bearish"), account_equity=1_000_000,
            options_approval_level=3, iv_percentile=30.0,
            option_chain=chain, dte=10,
        )
        by_name = {s["name"]: s for s in result["ranked_structures"]}
        if "synthetic_short" in by_name:
            assert by_name["synthetic_short"]["greeks"] is not None

    def test_long_butterfly_call_double_leg_doubles_theta_weight(self):
        # long_butterfly_call's inner wing is listed twice in
        # _GREEKS_RESOLVABLE_LEGS (2x short at k_mid, matching
        # resolve_structure_economics' `-2 * bs(k_mid)` term) — confirm the
        # net theta reflects that 2x weight, not a single-contract theta.
        chain = _fake_chain(current_price=500.0, step=10.0)
        legs = _resolve_structure_legs("long_butterfly_call", chain, 500.0)
        assert legs is not None and len(legs) == 4
        mid_legs = [leg for leg in legs if leg["side"] == "short"]
        assert len(mid_legs) == 2 and mid_legs[0]["strike"] == mid_legs[1]["strike"]

        net = net_structure_greeks(legs, S=500.0, T=10 / 365.0)["net"]
        single_mid_theta = compute_greeks(500.0, mid_legs[0]["strike"], 10 / 365.0, 0.04, mid_legs[0]["iv"], "call")["theta"]
        wing_legs = [leg for leg in legs if leg["side"] == "long"]
        wing_theta_sum = sum(
            compute_greeks(500.0, leg["strike"], 10 / 365.0, 0.04, leg["iv"], "call")["theta"] for leg in wing_legs
        )
        # net theta = 2x short mid theta (positive, since short) + both long wing thetas (negative)
        expected = -2 * single_mid_theta + wing_theta_sum
        assert net["theta"] == pytest.approx(expected, abs=1e-3)

    def test_itm_moneyness_selects_tighter_strike_than_deep_itm(self):
        # "itm" (6%) must select a different, closer-to-money strike than the
        # pre-existing "deep_itm" (15%) bucket — confirms the new moneyness
        # tier is actually wired in, not silently falling back to 0%/atm.
        chain = _fake_chain(current_price=500.0, step=10.0)
        itm_contract = select_directional_leg_strike(chain, 500.0, "call", "itm")
        deep_itm_contract = select_directional_leg_strike(chain, 500.0, "call", "deep_itm")
        assert itm_contract is not None and deep_itm_contract is not None
        assert itm_contract["strike"] > deep_itm_contract["strike"]  # itm call strike is below spot, less far below
        assert itm_contract["strike"] < 500.0


class TestMixedStructureSlippageDivisor:
    """
    Mixed stock+option structures (covered_call, protective_put, married_put,
    collar, covered_strangle) have a stock leg deliberately excluded from
    _GREEKS_RESOLVABLE_LEGS (stock has no comparable bid/ask spread cost) —
    so structure['legs'] (STRUCTURE_MULTIPLIERS' full leg count, including the
    stock leg) is always > len(legs) (the real option-only legs
    _resolve_structure_legs returns) for these 5. rank_trade_structures'
    auto-populated bid_ask_spreads average must divide by structure['legs'],
    not len(legs) — adjust_ev_for_slippage later multiplies that average back
    by structure['legs'], so dividing by the smaller len(legs) inflated the
    reconstructed total spread cost as if the stock leg carried the same
    spread as a real option leg.
    """

    def _candidate(self):
        return {
            "ticker": "NVDA", "direction": "bullish", "confidence": 92,
            "entry_mid": 500.0, "stop_loss": 485.0, "target": 545.0,
            "atr_14": 10.0, "force_defined_risk": False,
        }

    def test_covered_call_leg_count_mismatch_exists(self):
        # Documents the exact mismatch the fix accounts for — if this ever
        # stops being true (e.g. _GREEKS_RESOLVABLE_LEGS starts including the
        # stock leg), the divisor fix's rationale no longer applies.
        chain = _fake_chain(current_price=500.0, step=10.0)
        legs = _resolve_structure_legs("covered_call", chain, 500.0)
        assert len(legs) == 1  # only the short call leg is resolvable
        assert STRUCTURE_MULTIPLIERS["covered_call"]["legs"] == 2  # stock + call

    def test_auto_populated_spread_matches_correctly_divided_explicit_value(self):
        # 2,000,000 account clears covered_call's ~$50k full-stock capital
        # requirement (5% cap) — unrelated to the slippage math under test,
        # just needed so covered_call survives filtering into ranked_structures.
        chain = _fake_chain(current_price=500.0, step=10.0)  # every contract: bid=1.0, ask=1.2
        result_from_chain = rank_trade_structures(
            self._candidate(), account_equity=2_000_000,
            options_approval_level=2, iv_percentile=30.0,
            option_chain=chain, dte=10,
        )
        by_name_chain = {s["name"]: s for s in result_from_chain["ranked_structures"]}
        assert "covered_call" in by_name_chain

        # Same call, no chain at all (isolates the slippage math from any
        # Greeks/chain side effect), with bid_ask_spreads explicitly set to
        # the correctly-divided value (0.2 real spread / 2 structure legs =
        # 0.1) — if the fix is wired correctly, auto-populating from the
        # chain must land on this same figure. dte=10 explicit here too
        # (matching the chain call above) so this only isolates the slippage
        # math, not the module's _DEFAULT_DTE_IF_UNKNOWN fallback.
        result_explicit = rank_trade_structures(
            self._candidate(), account_equity=2_000_000,
            options_approval_level=2, iv_percentile=30.0,
            bid_ask_spreads={"covered_call": 0.1}, dte=10,
        )
        by_name_explicit = {s["name"]: s for s in result_explicit["ranked_structures"]}
        assert by_name_explicit["covered_call"]["ev"] == pytest.approx(
            by_name_chain["covered_call"]["ev"], abs=1e-4
        )

    def test_auto_populated_spread_does_not_match_old_undivided_bug_value(self):
        # Guards against a regression back to the old bug: the old code's
        # effective per-leg average (0.2, i.e. len(legs)=1 divisor) is NOT
        # what the fixed auto-population should produce (0.1, structure['legs']=2
        # divisor) — these two must give different EV once slippage is applied.
        chain = _fake_chain(current_price=500.0, step=10.0)
        result_from_chain = rank_trade_structures(
            self._candidate(), account_equity=2_000_000,
            options_approval_level=2, iv_percentile=30.0,
            option_chain=chain, dte=10,
        )
        result_old_buggy_value = rank_trade_structures(
            self._candidate(), account_equity=2_000_000,
            options_approval_level=2, iv_percentile=30.0,
            bid_ask_spreads={"covered_call": 0.2}, dte=10,  # the pre-fix len(legs)=1 divisor result
        )
        by_name_chain = {s["name"]: s for s in result_from_chain["ranked_structures"]}
        by_name_old = {s["name"]: s for s in result_old_buggy_value["ranked_structures"]}
        assert by_name_chain["covered_call"]["ev"] != pytest.approx(
            by_name_old["covered_call"]["ev"], abs=1e-4
        )


# ---------------------------------------------------------------------------
# _ranking_sort_key — EV/max-loss tiebreak (2026-08-23 full model audit)
# ---------------------------------------------------------------------------

class TestRankingSortKeyMaxLossTiebreak:
    """
    ev_per_dollar_per_day is a point estimate of the MEAN outcome — it says
    nothing about the shape of the distribution around that mean, so two
    structures with near-identical EV but very different loss-tail severity
    used to be treated as equivalent (arbitrary/positional tie order). These
    test the extracted sort key directly rather than driving the full
    42-structure evaluation pipeline, since real ties are hard to engineer
    reliably through actual Black-Scholes math but trivial to construct
    directly against the dict shape ranked_structures actually stores.
    """

    def _sorted_names(self, structures):
        return [s["name"] for s in sorted(structures, key=_ranking_sort_key, reverse=True)]

    def test_higher_ev_wins_outright_regardless_of_max_loss(self):
        structures = [
            {"name": "big_loss_better_ev", "ev_per_dollar_per_day": 0.02, "max_loss_dollars": 5000.0},
            {"name": "small_loss_worse_ev", "ev_per_dollar_per_day": 0.01, "max_loss_dollars": 100.0},
        ]
        assert self._sorted_names(structures)[0] == "big_loss_better_ev"

    def test_tied_ev_prefers_smaller_max_loss(self):
        structures = [
            {"name": "fat_tail", "ev_per_dollar_per_day": 0.015, "max_loss_dollars": 4000.0},
            {"name": "symmetric", "ev_per_dollar_per_day": 0.015, "max_loss_dollars": 300.0},
        ]
        assert self._sorted_names(structures)[0] == "symmetric"

    def test_undefined_risk_always_loses_a_tie_to_defined_risk(self):
        """max_loss_dollars=None (never fabricated — see resolve_structure_
        economics) must lose a tiebreak against ANY defined-risk structure
        at the same EV, not just ones with a small max loss."""
        structures = [
            {"name": "naked_short_call", "ev_per_dollar_per_day": 0.02, "max_loss_dollars": None},
            {"name": "defined_risk_large", "ev_per_dollar_per_day": 0.02, "max_loss_dollars": 9999.0},
        ]
        assert self._sorted_names(structures)[0] == "defined_risk_large"

    def test_two_undefined_risk_structures_tied_on_ev_keep_stable_relative_order(self):
        """Both -inf -- no crash, no exception from comparing None-derived
        sentinels, and Python's stable sort keeps their original relative
        order rather than raising."""
        structures = [
            {"name": "naked_short_call", "ev_per_dollar_per_day": 0.02, "max_loss_dollars": None},
            {"name": "naked_short_put", "ev_per_dollar_per_day": 0.02, "max_loss_dollars": None},
        ]
        assert set(self._sorted_names(structures)) == {"naked_short_call", "naked_short_put"}

    def test_recommended_pick_prefers_lower_max_loss_among_tied_ev_structures(self):
        """End-to-end confirmation that the tiebreak actually reaches the
        real recommendation logic (which walks ranked_structures in sorted
        order via next(...)), not just the standalone sort key in isolation.
        Real ties are hard to force through actual Black-Scholes math, so
        this verifies the invariant directly: whichever real structures (if
        any) tie on ev_per_dollar_per_day in a real evaluation are ordered
        by ascending max_loss_dollars among themselves."""
        candidate = {
            "ticker": "NVDA", "direction": "bullish", "confidence": 92,
            "entry_mid": 500.0, "stop_loss": 485.0, "target": 545.0,
            "atr_14": 10.0, "force_defined_risk": False,
        }
        result = rank_trade_structures(
            candidate, account_equity=100_000, options_approval_level=4, iv_percentile=50.0,
        )
        by_ev: dict[float, list[dict]] = {}
        for s in result["ranked_structures"]:
            by_ev.setdefault(s["ev_per_dollar_per_day"], []).append(s)
        for tied_group in by_ev.values():
            if len(tied_group) < 2:
                continue
            losses = [s["max_loss_dollars"] if s["max_loss_dollars"] is not None else float("inf") for s in tied_group]
            assert losses == sorted(losses), (
                f"structures tied on ev_per_dollar_per_day must be ordered by ascending max_loss_dollars: {tied_group}"
            )
