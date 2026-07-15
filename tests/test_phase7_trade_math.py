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

    def test_slippage_reduces_ev(self):
        ev_raw = 100.0
        ev_adj = adjust_ev_for_slippage(ev_raw, "long_call", bid_ask_spread=0.50, num_legs=1)
        assert ev_adj < ev_raw

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
    def test_tier_90_92_returns_1pct(self):
        assert get_risk_pct(90) == pytest.approx(0.010)
        assert get_risk_pct(91) == pytest.approx(0.010)
        assert get_risk_pct(92) == pytest.approx(0.010)

    def test_tier_93_95_returns_1_5pct(self):
        assert get_risk_pct(93) == pytest.approx(0.015)
        assert get_risk_pct(95) == pytest.approx(0.015)

    def test_tier_96_98_returns_2pct(self):
        assert get_risk_pct(96) == pytest.approx(0.020)
        assert get_risk_pct(98) == pytest.approx(0.020)

    def test_tier_99_100_returns_2_5pct(self):
        assert get_risk_pct(99) == pytest.approx(0.025)
        assert get_risk_pct(100) == pytest.approx(0.025)

    def test_below_90_returns_zero(self):
        assert get_risk_pct(89) == 0.0
        assert get_risk_pct(0) == 0.0

    def test_sizing_tiers_cover_all_valid_scores(self):
        for score in range(90, 101):
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
        # $15k account, 5% max = $750; capital_required=$500 → approved
        result = compute_position_size(
            confidence_score=93, account_equity=15000,
            circuit_breaker_state="normal", capital_required=500.0
        )
        assert result["capital_approved"] is True
        assert result["dollar_risk"] == pytest.approx(15000 * 0.015)
        assert result["max_capital"] == pytest.approx(750.0)

    def test_compute_position_size_capital_denied(self):
        result = compute_position_size(
            confidence_score=90, account_equity=15000,
            circuit_breaker_state="normal", capital_required=900.0
        )
        assert result["capital_approved"] is False

    def test_position_size_required_keys(self):
        result = compute_position_size(90, 15000, "normal", 500.0)
        for key in ("risk_pct", "dollar_risk", "circuit_breaker_state",
                    "size_multiplier", "capital_required", "capital_approved", "max_capital"):
            assert key in result


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
        result = rank_trade_structures(
            self._candidate(), account_equity=15000,
            options_approval_level=2, iv_percentile=30.0
        )
        evs = [s["ev_per_dollar_risked"] for s in result["ranked_structures"]]
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
                    "exclusion_summary"):
            assert key in result

    def test_top_ranked_is_recommended(self):
        result = rank_trade_structures(
            self._candidate(), account_equity=15000,
            options_approval_level=2, iv_percentile=30.0
        )
        if result["ranked_structures"]:
            assert result["ranked_structures"][0]["recommended"] is True
            # Others should not be recommended
            for s in result["ranked_structures"][1:]:
                assert s["recommended"] is False
