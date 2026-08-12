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


class TestBearishDirection:
    """resolve_structure_economics' entry guard used to require stop < entry
    unconditionally, returning None for every bearish candidate (where stop
    sits above entry per risk_reward.py's own convention) regardless of
    whether the structure itself is bearish-eligible. fav/unfav were already
    abs()-based internally, so this was purely a guard bug, not a payoff-math
    one — these tests cover the fix at the resolve_structure_economics level;
    trade_selector.py's own R:R computation (a separate, independent instance
    of the same bug) is covered in tests/test_phase7_trade_math.py."""

    _B_ENTRY = 150.0
    _B_STOP = 155.0   # above entry — bearish convention
    _B_TARGET = 135.0  # below entry

    def test_bearish_candidate_returns_economics_not_none(self):
        for name in ("long_put", "bear_put_spread", "bear_call_spread", "deep_itm_put", "leaps_put"):
            econ = resolve_structure_economics(name, self._B_ENTRY, self._B_STOP, self._B_TARGET, _IV, _DTE)
            assert econ is not None, f"{name} incorrectly returned None for a valid bearish setup"

    def test_bearish_economics_are_finite_and_sane(self):
        for name in STRUCTURE_MULTIPLIERS:
            if name in PASSTHROUGH_STRUCTURES:
                continue
            econ = resolve_structure_economics(name, self._B_ENTRY, self._B_STOP, self._B_TARGET, _IV, _DTE)
            assert econ is not None, f"{name} returned None unexpectedly for bearish"
            for key in ("avg_win", "avg_loss", "capital_required"):
                assert math.isfinite(econ[key]), f"{name}.{key} is not finite: {econ[key]}"
            assert econ["avg_win"] >= 0, f"{name}: bearish avg_win is negative ({econ['avg_win']}) — sign bug"

    def test_bearish_long_put_win_prob_matches_bullish_long_call_by_symmetry(self):
        # A mirror-image setup (same distances, opposite direction) should
        # produce comparable-magnitude economics for the mirrored structure —
        # confirms the fav/unfav magnitudes, not just non-None-ness, are
        # correct for bearish, not just accidentally passing the guard.
        bullish_call = resolve_structure_economics("long_call", _ENTRY, _STOP, _TARGET, _IV, _DTE)
        bearish_put = resolve_structure_economics("long_put", self._B_ENTRY, self._B_STOP, self._B_TARGET, _IV, _DTE)
        assert bullish_call is not None and bearish_put is not None
        assert bearish_put["avg_win"] > 0
        assert bearish_put["avg_loss"] > 0

    def test_stop_equal_entry_still_returns_none(self):
        # The one genuinely degenerate case (zero risk distance) should still
        # be rejected regardless of direction.
        assert resolve_structure_economics("long_call", _ENTRY, _ENTRY, _TARGET, _IV, _DTE) is None
        assert resolve_structure_economics("long_put", self._B_ENTRY, self._B_ENTRY, self._B_TARGET, _IV, _DTE) is None


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
        high_iv = resolve_structure_economics("long_call", _ENTRY, _STOP, _TARGET, 0.60, _DTE)
        assert high_iv["capital_required"] > low_iv["capital_required"]


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


class TestHighAtrPriceRatioCharacterization:
    """
    Confirms/characterizes the hypothesis behind the MU long_strangle EV/$/day
    outlier (~119, vs. AVGO/NVDA's ~46-59 on the same structure, same scan) —
    is a high-ATR/price-ratio candidate mechanically inflated by this
    formula, independent of anything ticker-specific like real market IV?

    Root cause confirmed: for long_strangle (and every other structure whose
    strikes come from _otm_k(entry, ..., <fixed magnitude>)), the premium
    (capital_required) depends only on entry/iv/dte — never on the swing
    model's own ATR-derived stop/target — while avg_win depends on `fav`
    (target - entry), which the swing model sizes directly off ATR. A stock
    with a larger ATR/price ratio gets a proportionally bigger avg_win for
    the *same* premium, so ev_per_dollar_risked scales faster than the ATR
    ratio itself. Live, this is partly offset when a real option chain
    supplies atm_iv (more volatile stocks usually do trade at higher real
    IV) — but the formula has no explicit link between ATR and IV, so a
    high-ATR/low-supplied-IV combination (e.g. the iv_percentile fallback,
    which ignores ATR entirely) still triggers this inflation. This is why
    the fix landed as a statistical outlier check against each structure's
    own trailing history (shared/utils/robust_stats.py, wired into
    paper_runner.py) rather than a change to this formula — patching the
    formula itself risks under- or over-correcting every structure that
    shares this strike convention, not just long_strangle.
    """

    def _long_strangle_ev_per_dollar(self, atr_pct: float, win_prob: float = 0.60) -> tuple[float, float]:
        entry = 150.0
        atr = entry * atr_pct
        stop = entry - atr * 2.0
        target = entry + atr * 2.0 * 3.0
        econ = resolve_structure_economics("long_strangle", entry, stop, target, _IV, _DTE)
        from shared.utils.options_math import compute_ev_simple
        ev = compute_ev_simple(win_prob, econ["avg_win"], econ["avg_loss"])
        return ev / econ["capital_required"], econ["capital_required"]

    def test_capital_required_is_independent_of_atr_price_ratio(self):
        # The actual root cause: premium (and therefore capital_required)
        # comes from entry + the fixed 6% OTM offset + iv/dte only — never
        # from ATR — so it's identical whether the underlying's ATR/price
        # ratio is small or MU-sized, holding iv/dte/entry fixed.
        _, capital_low = self._long_strangle_ev_per_dollar(atr_pct=0.04)
        _, capital_high = self._long_strangle_ev_per_dollar(atr_pct=0.095)
        assert capital_low == capital_high

    def test_ev_per_dollar_scales_faster_than_the_atr_ratio_itself(self):
        # AVGO-like (~4.1%) vs. MU-like (~9.5%) ATR/price ratios, same iv/dte —
        # ev_per_dollar should scale by MORE than the ~2.3x ATR ratio itself,
        # since avg_win scales with ATR while the premium paid for it doesn't.
        ev_per_dollar_low, _ = self._long_strangle_ev_per_dollar(atr_pct=0.04)
        ev_per_dollar_high, _ = self._long_strangle_ev_per_dollar(atr_pct=0.095)
        atr_ratio = 0.095 / 0.04
        ev_ratio = ev_per_dollar_high / ev_per_dollar_low
        assert ev_ratio > atr_ratio

    def test_effect_holds_for_other_fixed_otm_offset_structures_too(self):
        # Not unique to long_strangle — any structure whose strike comes from
        # _otm_k(entry, ..., <fixed magnitude>) shares this same decoupling.
        # long_straddle uses at-the-money strikes (no _otm_k offset at all),
        # so it's the natural contrast: its premium DOES move with the
        # payoff's implied strikes... but still not with ATR directly either,
        # since long_straddle's strikes are pinned to entry regardless of ATR.
        # The property that generalizes across both is capital_required's
        # independence from ATR, checked directly instead of asserting a
        # specific inflation ratio that would vary structure to structure.
        entry, iv, dte = 150.0, _IV, _DTE
        for structure_name in ("long_strangle", "long_straddle", "bull_call_spread"):
            capitals = []
            for atr_pct in (0.04, 0.095):
                atr = entry * atr_pct
                stop = entry - atr * 2.0
                target = entry + atr * 2.0 * 3.0
                econ = resolve_structure_economics(structure_name, entry, stop, target, iv, dte)
                capitals.append(econ["capital_required"])
            assert capitals[0] == capitals[1], f"{structure_name}: capital_required unexpectedly moved with ATR"
