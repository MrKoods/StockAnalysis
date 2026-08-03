"""
Tests for shared/utils/options_math.py's resolve_structure_economics() (v2.2.36) —
real Black-Scholes-derived avg_win/avg_loss/capital_required for the 35 trade
structures whose profit_mult/loss_mult were previously descriptive placeholder
strings ("leverage", "put_premium", ...) that silently defaulted to 1.0 in
trade_selector.py, making their modeled EV indistinguishable from plain stock.

These are invariant/property tests (bounded loss for defined-risk structures,
no absurd capital-vs-EV ratios, real premium-based figures rather than a fixed
multiplier) rather than exact-dollar-figure tests — the formulas are
approximations of real options payoffs, not a pricing engine being verified
against a known-correct reference.
"""

import math

from shared.utils.options_math import (
    resolve_structure_economics,
    PASSTHROUGH_STRUCTURES,
    black_scholes_price,
    STRUCTURE_MULTIPLIERS,
)

_ENTRY = 150.0
_STOP = 145.0
_TARGET = 165.0
_IV = 0.30
_DTE = 10


class TestPassthroughStructures:
    def test_pure_stock_structures_return_none(self):
        for name in ("long_stock", "short_stock", "long_stock_trailing_stop"):
            assert resolve_structure_economics(name, _ENTRY, _STOP, _TARGET, _IV, _DTE) is None

    def test_surface_structures_return_none(self):
        for name in ("call_ratio_spread", "put_ratio_spread", "call_back_spread", "put_back_spread"):
            assert resolve_structure_economics(name, _ENTRY, _STOP, _TARGET, _IV, _DTE) is None

    def test_passthrough_set_matches_the_7_unhandled_structures(self):
        # 42 total - 35 covered by resolve_structure_economics = 7 passthrough
        assert len(PASSTHROUGH_STRUCTURES) == 7

    def test_invalid_price_inputs_return_none(self):
        assert resolve_structure_economics("long_call", 0.0, _STOP, _TARGET, _IV, _DTE) is None
        assert resolve_structure_economics("long_call", _ENTRY, _ENTRY, _TARGET, _IV, _DTE) is None  # stop >= entry


class TestAllCoveredStructuresProduceSaneOutput:
    """Broad sweep: every one of the 35 structures should return a real dict
    with finite, non-degenerate values — catches the class of bug found live
    (diagonal_call's capital collapsing to ~$1 due to an unscaled floor)
    without needing a bespoke assertion per structure."""

    def test_every_non_passthrough_structure_returns_valid_economics(self):
        for name in STRUCTURE_MULTIPLIERS:
            if name in PASSTHROUGH_STRUCTURES:
                continue
            econ = resolve_structure_economics(name, _ENTRY, _STOP, _TARGET, _IV, _DTE)
            assert econ is not None, f"{name} returned None unexpectedly"
            for key in ("avg_win", "avg_loss", "capital_required"):
                val = econ[key]
                assert math.isfinite(val), f"{name}.{key} is not finite: {val}"
            # The bug this guards against: capital collapsing to a token
            # amount while avg_win/avg_loss stay at a real dollar scale,
            # producing an ev_per_dollar_risked that swamps every other
            # structure for no real economic reason. $10 (spread-adjusted per
            # 100-share lot) is comfortably below any realistic structure's
            # true capital at a $150 stock price, so anything under it is
            # almost certainly the same class of unscaled-floor bug.
            assert econ["capital_required"] >= 10.0, (
                f"{name} capital_required={econ['capital_required']:.2f} looks like an "
                "unscaled-floor artifact, not a real premium/margin figure"
            )

    def test_no_structure_has_a_capital_to_ev_ratio_over_50(self):
        # A loose sanity ceiling, not a precision check: ev_per_dollar_risked
        # this large for any of these formulas indicates a scale bug (this is
        # exactly how the diagonal_call bug first surfaced — ev_per_dollar of
        # 364 vs. every other structure's single-digit range).
        for name in STRUCTURE_MULTIPLIERS:
            if name in PASSTHROUGH_STRUCTURES:
                continue
            econ = resolve_structure_economics(name, _ENTRY, _STOP, _TARGET, _IV, _DTE)
            ratio = abs(econ["avg_win"]) / econ["capital_required"]
            assert ratio < 50.0, f"{name}: avg_win/capital ratio {ratio:.1f} looks like a scale bug"


class TestProtectivePutFamily:
    """The structures whose capital estimate was the actual root cause of
    protective_put dominating every live ranking evaluation observed
    (entry*0.3, a special-cased shortcut married_put/collar didn't get)."""

    def test_protective_put_capital_reflects_real_share_ownership(self):
        econ = resolve_structure_economics("protective_put", _ENTRY, _STOP, _TARGET, _IV, _DTE)
        # Real capital for 100 shares + a put, even at 50% margin, is large
        # relative to the stock price -- nowhere near the old entry*0.3 (~$45).
        assert econ["capital_required"] > _ENTRY * 40  # >> the old ~0.3x estimate

    def test_married_put_and_protective_put_have_comparable_capital(self):
        # These are economically the same position (100 shares + 1 long put) --
        # the bug was that only protective_put got a cheap shortcut. Now both
        # should land in the same ballpark.
        econ_pp = resolve_structure_economics("protective_put", _ENTRY, _STOP, _TARGET, _IV, _DTE)
        econ_mp = resolve_structure_economics("married_put", _ENTRY, _STOP, _TARGET, _IV, _DTE)
        assert econ_pp["capital_required"] == econ_mp["capital_required"]

    def test_protective_put_avg_loss_exceeds_plain_stock_by_the_premium_cost(self):
        # Insurance costs money -- protective_put's avg_loss should be worse
        # than a plain long_stock's unfav move by roughly the put premium,
        # not identical to it (which is what the old loss_mult="put_premium"
        # string-default-to-1.0 bug produced).
        econ = resolve_structure_economics("protective_put", _ENTRY, _STOP, _TARGET, _IV, _DTE)
        plain_stock_loss = (_ENTRY - _STOP) * 100
        assert econ["avg_loss"] > plain_stock_loss

    def test_these_structures_excluded_at_15k_account_for_a_150_stock(self):
        # The real-world consequence of the fix: a $15k account genuinely
        # cannot afford 100 real shares of a $150 stock plus options at a 5%
        # ($750) per-trade cap. This is what should exclude them now, not an
        # artificially generous capital shortcut.
        max_capital_15k = 15000 * 0.05
        for name in ("protective_put", "married_put", "collar"):
            econ = resolve_structure_economics(name, _ENTRY, _STOP, _TARGET, _IV, _DTE)
            assert econ["capital_required"] > max_capital_15k


class TestLongPremiumStructures:
    def test_long_call_premium_matches_black_scholes(self):
        econ = resolve_structure_economics("long_call", _ENTRY, _STOP, _TARGET, _IV, _DTE)
        expected_premium = black_scholes_price(_ENTRY, _ENTRY, _DTE / 365.0, 0.04, _IV, "call")
        assert abs(econ["capital_required"] - expected_premium * 100) < 0.01

    def test_long_call_loss_is_bounded_by_premium_paid(self):
        # Max loss on a long option can never exceed the premium paid.
        econ = resolve_structure_economics("long_call", _ENTRY, _STOP, _TARGET, _IV, _DTE)
        assert econ["avg_loss"] <= econ["capital_required"] + 0.01

    def test_deep_itm_call_costs_more_than_atm_long_call(self):
        atm = resolve_structure_economics("long_call", _ENTRY, _STOP, _TARGET, _IV, _DTE)
        itm = resolve_structure_economics("deep_itm_call", _ENTRY, _STOP, _TARGET, _IV, _DTE)
        assert itm["capital_required"] > atm["capital_required"]

    def test_leaps_call_costs_more_than_short_dated_long_call(self):
        # More time value -- a LEAPS premium should exceed a 10-day option's.
        short_dated = resolve_structure_economics("long_call", _ENTRY, _STOP, _TARGET, _IV, _DTE)
        leaps = resolve_structure_economics("leaps_call", _ENTRY, _STOP, _TARGET, _IV, _DTE)
        assert leaps["capital_required"] > short_dated["capital_required"]

    def test_higher_iv_increases_long_option_premium(self):
        low_iv = resolve_structure_economics("long_call", _ENTRY, _STOP, _TARGET, 0.15, _DTE)
        high_iv = resolve_structure_economics("long_put", _ENTRY, _STOP, _TARGET, 0.15, _DTE)
        low_iv2 = resolve_structure_economics("long_call", _ENTRY, _STOP, _TARGET, 0.60, _DTE)
        assert low_iv2["capital_required"] > low_iv["capital_required"]


class TestDefinedRiskSpreads:
    def test_debit_spread_max_loss_is_the_net_debit_not_the_full_stop_distance(self):
        # The whole point of a defined-risk debit spread: avg_loss should be
        # the (small) net debit, not down_move*1.0 like plain long stock.
        econ = resolve_structure_economics("bull_call_spread", _ENTRY, _STOP, _TARGET, _IV, _DTE)
        plain_stock_loss = (_ENTRY - _STOP) * 100
        assert econ["avg_loss"] < plain_stock_loss

    def test_credit_spread_win_plus_loss_approximately_equals_width(self):
        # avg_win (credit) + avg_loss (width - credit) should sum to the
        # spread width -- a defining property of a real credit spread payoff.
        econ = resolve_structure_economics("bull_put_spread", _ENTRY, _STOP, _TARGET, _IV, _DTE)
        width_est = _ENTRY * (0.12 - 0.06) * 100  # far_otm - otm strike distance, x100
        assert abs((econ["avg_win"] + econ["avg_loss"]) - width_est) < 1.0

    def test_iron_condor_credit_is_positive_and_loss_is_bounded(self):
        econ = resolve_structure_economics("iron_condor", _ENTRY, _STOP, _TARGET, _IV, _DTE)
        assert econ["avg_win"] > 0  # net credit received
        assert econ["avg_loss"] < _ENTRY * 100  # nowhere near unbounded


class TestIncomeStructures:
    def test_covered_call_capital_is_real_share_cost(self):
        econ = resolve_structure_economics("covered_call", _ENTRY, _STOP, _TARGET, _IV, _DTE)
        assert abs(econ["capital_required"] - _ENTRY * 100) < 0.01

    def test_cash_secured_put_capital_is_near_strike_value(self):
        econ = resolve_structure_economics("cash_secured_put", _ENTRY, _STOP, _TARGET, _IV, _DTE)
        assert econ["capital_required"] > _ENTRY * 0.85 * 100  # near the OTM strike x100


class TestUndefinedRiskStructures:
    def test_naked_short_call_has_bounded_tail_risk_estimate(self):
        # True risk is unlimited; this is a finite ranking proxy only -- the
        # real gate is the existing $50k+Level 3 filter, not this number.
        econ = resolve_structure_economics("naked_short_call", _ENTRY, _STOP, _TARGET, _IV, _DTE)
        assert math.isfinite(econ["avg_loss"])
        assert econ["avg_loss"] >= 0

    def test_short_straddle_win_is_the_combined_credit(self):
        econ = resolve_structure_economics("short_straddle", _ENTRY, _STOP, _TARGET, _IV, _DTE)
        assert econ["avg_win"] > 0
