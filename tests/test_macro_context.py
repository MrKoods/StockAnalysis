"""
Tests for Phase 3 macro context layer:
  - shared/utils/regime_detection.py
  - shared/utils/sector_rotation.py
  - shared/utils/earnings_calendar.py
  - shared/utils/seasonality.py
  - shared/utils/macro_overlay.py
All tests use synthetic deterministic series.
"""

from datetime import datetime, timezone

import pandas as pd

from shared.utils.regime_detection import (
    classify_regime,
    get_regime_modifiers,
    REGIME_TRENDING_UP,
    REGIME_TRENDING_DOWN,
    REGIME_CHOPPY,
    REGIME_HIGH_VOL,
)
from shared.utils.sector_rotation import (
    compute_rotation_state,
    get_rotation_modifier,
    dampen_rotation_penalty_for_leader,
    ROTATION_INFLOW,
    ROTATION_NEUTRAL,
    ROTATION_OUTFLOW,
)
from shared.utils.earnings_calendar import get_earnings_modifier
from shared.utils.seasonality import get_seasonality_modifier
from shared.utils.macro_overlay import (
    compute_macro_state,
    dampen_news_china_theme_if_macro_confirmed,
    get_macro_modifier,
    load_macro_state,
    save_macro_state,
    MACRO_ADVERSE,
    MACRO_FAVORABLE,
    MACRO_NEUTRAL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(closes: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-02", periods=len(closes), freq="B")
    closes = pd.Series(closes, index=dates)
    return pd.DataFrame({
        "Open": closes * 0.99,
        "High": closes * 1.01,
        "Low": closes * 0.98,
        "Close": closes,
        "Volume": [1_000_000] * len(closes),
    })


def _make_series(values: list[float]) -> pd.Series:
    dates = pd.date_range("2024-01-02", periods=len(values), freq="B")
    return pd.Series(values, index=dates)


# ---------------------------------------------------------------------------
# Regime Detection
# ---------------------------------------------------------------------------

class TestRegimeDetection:
    def test_high_vix_triggers_high_vol(self):
        closes = list(range(100, 125))  # 25 bars
        smh = _make_ohlcv(closes)
        result = classify_regime(vix=35.0, smh_ohlcv=smh)
        assert result == REGIME_HIGH_VOL

    def test_trending_up_when_price_above_rising_sma(self):
        # Strong uptrend: +2 per bar for 30 bars
        closes = [100 + i * 2 for i in range(30)]
        smh = _make_ohlcv(closes)
        result = classify_regime(vix=15.0, smh_ohlcv=smh)
        assert result == REGIME_TRENDING_UP

    def test_trending_down_when_price_below_falling_sma(self):
        # Strong downtrend: -2 per bar for 30 bars
        closes = [200 - i * 2 for i in range(30)]
        smh = _make_ohlcv(closes)
        result = classify_regime(vix=18.0, smh_ohlcv=smh)
        assert result == REGIME_TRENDING_DOWN

    def test_choppy_with_insufficient_bars(self):
        closes = [100, 101, 102]  # too few
        smh = _make_ohlcv(closes)
        result = classify_regime(vix=15.0, smh_ohlcv=smh)
        assert result == REGIME_CHOPPY

    def test_choppy_with_flat_price(self):
        closes = [100.0] * 30
        smh = _make_ohlcv(closes)
        result = classify_regime(vix=15.0, smh_ohlcv=smh)
        # SMA == close == flat, no trend → choppy
        assert result in (REGIME_CHOPPY, REGIME_TRENDING_UP, REGIME_TRENDING_DOWN)

    def test_regime_modifier_high_vol_has_score_cap(self):
        mods = get_regime_modifiers(REGIME_HIGH_VOL, {})
        assert mods["score_cap"] == 70
        assert mods["regime_modifier"] == -15.0

    def test_regime_modifier_trending_up_no_cap(self):
        mods = get_regime_modifiers(REGIME_TRENDING_UP, {})
        assert mods["score_cap"] is None
        assert mods["regime_modifier"] > 0

    def test_regime_modifier_trending_down_negative(self):
        mods = get_regime_modifiers(REGIME_TRENDING_DOWN, {})
        assert mods["regime_modifier"] < 0

    def test_regime_modifier_choppy_negative(self):
        mods = get_regime_modifiers(REGIME_CHOPPY, {})
        assert mods["regime_modifier"] < 0

    def test_bearish_direction_mirrors_trending_up_and_down(self):
        # A short thesis is penalized by an uptrend and rewarded by a
        # downtrend — the mirror of a bullish candidate's treatment.
        up_bearish = get_regime_modifiers(REGIME_TRENDING_UP, {}, direction="bearish")
        down_bearish = get_regime_modifiers(REGIME_TRENDING_DOWN, {}, direction="bearish")
        assert up_bearish["regime_modifier"] < 0
        assert down_bearish["regime_modifier"] > 0
        up_bullish = get_regime_modifiers(REGIME_TRENDING_UP, {}, direction="bullish")
        down_bullish = get_regime_modifiers(REGIME_TRENDING_DOWN, {}, direction="bullish")
        assert up_bearish["regime_modifier"] == -up_bullish["regime_modifier"]
        assert down_bearish["regime_modifier"] == -down_bullish["regime_modifier"]

    def test_bearish_direction_leaves_choppy_and_high_vol_unchanged(self):
        assert (get_regime_modifiers(REGIME_CHOPPY, {}, direction="bearish")["regime_modifier"]
                == get_regime_modifiers(REGIME_CHOPPY, {}, direction="bullish")["regime_modifier"])
        assert (get_regime_modifiers(REGIME_HIGH_VOL, {}, direction="bearish")["regime_modifier"]
                == get_regime_modifiers(REGIME_HIGH_VOL, {}, direction="bullish")["regime_modifier"])


# ---------------------------------------------------------------------------
# Sector Rotation
# ---------------------------------------------------------------------------

class TestSectorRotation:
    def _make_rotation_series(self, smh_vals, spy_vals):
        return _make_series(smh_vals), _make_series(spy_vals)

    def test_outflow_when_smh_underperforms(self):
        # SMH flat, SPY up 10% → outflow
        smh = _make_series([100.0] * 65)
        spy = _make_series([100.0 + i * 0.15 for i in range(65)])
        result = compute_rotation_state(smh, spy)
        assert result["rotation_state"] == ROTATION_OUTFLOW
        assert result["confidence_modifier"] == -15.0

    def test_inflow_when_smh_outperforms(self):
        # SMH up 10%, SPY flat → inflow
        smh = _make_series([100.0 + i * 0.15 for i in range(65)])
        spy = _make_series([100.0] * 65)
        result = compute_rotation_state(smh, spy)
        assert result["rotation_state"] == ROTATION_INFLOW
        assert result["confidence_modifier"] == 5.0

    def test_neutral_when_both_move_together(self):
        # Both move identically → 0 relative return
        vals = [100.0 + i * 0.1 for i in range(65)]
        smh = _make_series(vals)
        spy = _make_series(vals)
        result = compute_rotation_state(smh, spy)
        assert result["rotation_state"] == ROTATION_NEUTRAL
        assert result["confidence_modifier"] == 0.0

    def test_result_contains_required_keys(self):
        vals = [100.0] * 65
        result = compute_rotation_state(_make_series(vals), _make_series(vals))
        for key in ("rotation_state", "smh_vs_spy_5d", "smh_vs_spy_20d", "smh_vs_spy_60d", "confidence_modifier"):
            assert key in result

    def test_insufficient_data_returns_neutral(self):
        smh = _make_series([100.0, 101.0])
        spy = _make_series([100.0, 99.0])
        result = compute_rotation_state(smh, spy)
        # With only 2 bars all windows return 0 relative → neutral
        assert result["rotation_state"] == ROTATION_NEUTRAL

    def test_get_rotation_modifier_bounds(self):
        assert get_rotation_modifier(ROTATION_OUTFLOW, {}) == -15.0
        assert get_rotation_modifier(ROTATION_INFLOW, {}) == 5.0
        assert get_rotation_modifier(ROTATION_NEUTRAL, {}) == 0.0

    def test_cfg_recalibration_actually_reaches_confidence_modifier(self):
        """
        compute_rotation_state() used to always use the hardcoded +5 inflow
        boost regardless of what config said — get_rotation_modifier() (the
        config-aware path) existed but was never actually called from
        compute_rotation_state() or any production caller. Per CHANGELOG
        v2.2.47, real backtest calibration (544 pooled outcomes) found +5
        was backwards (inflow trades won 53.9% vs. 63.7% for neutral) and
        config/swing_config.yaml's inflow_boost was deliberately set to 0 —
        but without cfg threaded through, that recalibration never reached
        live scoring. Passing cfg here must now actually change the result,
        not just get silently ignored.
        """
        smh = _make_series([100.0 + i * 0.15 for i in range(65)])
        spy = _make_series([100.0] * 65)
        cfg = {"modifiers": {"sector_rotation": {"outflow_penalty": -15, "inflow_boost": 0}}}
        result = compute_rotation_state(smh, spy, cfg=cfg)
        assert result["rotation_state"] == ROTATION_INFLOW
        assert result["confidence_modifier"] == 0.0  # not the stale hardcoded 5.0

    def test_no_cfg_preserves_hardcoded_default_for_backward_compatibility(self):
        """cfg=None (the default) must still return the old hardcoded +5 —
        callers that don't pass cfg (e.g. standalone unit tests of the raw
        rotation-state classification) shouldn't change behavior."""
        smh = _make_series([100.0 + i * 0.15 for i in range(65)])
        spy = _make_series([100.0] * 65)
        result = compute_rotation_state(smh, spy)
        assert result["confidence_modifier"] == 5.0

    def test_dampen_rotation_penalty_leaves_neutral_and_positive_untouched(self):
        assert dampen_rotation_penalty_for_leader(0.0, 5.0) == 0.0
        assert dampen_rotation_penalty_for_leader(5.0, 5.0) == 5.0

    def test_dampen_rotation_penalty_below_threshold_unchanged(self):
        assert dampen_rotation_penalty_for_leader(-15.0, 0.0) == -15.0
        assert dampen_rotation_penalty_for_leader(-15.0, 1.4) == -15.0

    def test_dampen_rotation_penalty_scales_to_50pct_cap(self):
        assert dampen_rotation_penalty_for_leader(-15.0, 1.5) == -15.0
        assert dampen_rotation_penalty_for_leader(-15.0, 2.25) == -11.25
        assert dampen_rotation_penalty_for_leader(-15.0, 3.0) == -7.5
        # Beyond the anchor, dampening stays capped at 50% — never over-dampens
        assert dampen_rotation_penalty_for_leader(-15.0, 5.0) == -7.5

    def test_get_rotation_modifier_mirrors_for_bearish(self):
        # Outflow (money leaving the sector) confirms a bearish thesis instead
        # of penalizing it; inflow penalizes a bearish thesis instead of
        # boosting it — the mirror of the bullish-default mapping.
        assert get_rotation_modifier(ROTATION_OUTFLOW, {}, direction="bearish") == 15.0
        assert get_rotation_modifier(ROTATION_INFLOW, {}, direction="bearish") == -5.0
        assert get_rotation_modifier(ROTATION_NEUTRAL, {}, direction="bearish") == 0.0

    def test_dampen_rotation_penalty_for_bearish_downside_leader(self):
        # Mirror of the bullish leader-dampening tests above: a strongly
        # underperforming ticker (very negative rs_zscore, "leading the
        # decline") dampens the penalty an adverse (inflow) modifier applies
        # to a bearish thesis, using the mirrored threshold/cap.
        assert dampen_rotation_penalty_for_leader(-15.0, 0.0, direction="bearish") == -15.0
        assert dampen_rotation_penalty_for_leader(-15.0, -1.4, direction="bearish") == -15.0
        assert dampen_rotation_penalty_for_leader(-15.0, -1.5, direction="bearish") == -15.0
        assert dampen_rotation_penalty_for_leader(-15.0, -2.25, direction="bearish") == -11.25
        assert dampen_rotation_penalty_for_leader(-15.0, -3.0, direction="bearish") == -7.5
        assert dampen_rotation_penalty_for_leader(-15.0, -5.0, direction="bearish") == -7.5
        # Positive rs_zscore (an outperformer, not a downside leader) gets no
        # dampening on the bearish side — the mirror-image threshold, not the
        # bullish one.
        assert dampen_rotation_penalty_for_leader(-15.0, 3.0, direction="bearish") == -15.0

    def test_modifier_bounds_clamp_a_retuned_penalty(self):
        """Tier B batch 3 (2026-08-19): outflow_penalty/inflow_boost were
        previously unenforced against modifier_bounds — a retuned value could
        silently exceed its own documented bound. Now genuinely clamped."""
        cfg = {"modifiers": {"sector_rotation": {"outflow_penalty": -50}}}
        assert get_rotation_modifier(ROTATION_OUTFLOW, cfg) == -15.0  # clamped to default bound

        wider_cfg = {
            "modifiers": {"sector_rotation": {"outflow_penalty": -50}},
            "modifier_bounds": {"sector_rotation": {"min": -30, "max": 5}},
        }
        assert get_rotation_modifier(ROTATION_OUTFLOW, wider_cfg) == -30.0  # clamped to the new bound


# ---------------------------------------------------------------------------
# Earnings Calendar
# ---------------------------------------------------------------------------

class TestEarningsCalendar:
    def _today(self):
        return datetime(2024, 5, 15, tzinfo=timezone.utc)

    def test_no_earnings_returns_zero_modifier(self):
        result = get_earnings_modifier("NVDA", None, today=self._today())
        assert result["confidence_modifier"] == 0.0
        assert not result["force_defined_risk"]
        assert result["days_to_earnings"] is None

    def test_within_5_days_triggers_max_penalty(self):
        earnings = datetime(2024, 5, 18, tzinfo=timezone.utc)  # 3 days out
        result = get_earnings_modifier("NVDA", earnings, today=self._today())
        assert result["confidence_modifier"] == -20.0
        assert result["force_defined_risk"]
        assert result["days_to_earnings"] == 3

    def test_on_earnings_day_no_new_trades(self):
        earnings = datetime(2024, 5, 15, tzinfo=timezone.utc)
        result = get_earnings_modifier("NVDA", earnings, today=self._today())
        assert result["no_new_trades"]
        assert result["confidence_modifier"] == -20.0

    def test_post_earnings_within_3_days(self):
        earnings = datetime(2024, 5, 13, tzinfo=timezone.utc)  # 2 days ago
        result = get_earnings_modifier("NVDA", earnings, today=self._today())
        assert result["post_earnings_settling"]

    def test_post_earnings_settling_applies_a_partial_penalty(self):
        """
        The bug being fixed: post_earnings_settling was computed and returned
        but never actually changed confidence_modifier — the day after a
        report jumped straight from -20 to 0.0, identical to 19+ days out,
        contradicting the module's own "tentative restore" docstring. Days
        -3 through -1 should now carry a real, smaller-than-near-earnings
        penalty instead of a full overnight reset to neutral.
        """
        for days_ago in (1, 2, 3):
            earnings = datetime(2024, 5, 15 - days_ago, tzinfo=timezone.utc)
            result = get_earnings_modifier("NVDA", earnings, today=self._today())
            assert result["post_earnings_settling"]
            assert result["confidence_modifier"] == -5.0
            assert not result["force_defined_risk"]

    def test_4_days_after_earnings_is_fully_restored(self):
        # Outside the 3-day settling window — back to the normal 0.0 floor.
        earnings = datetime(2024, 5, 11, tzinfo=timezone.utc)  # 4 days ago
        result = get_earnings_modifier("NVDA", earnings, today=self._today())
        assert not result["post_earnings_settling"]
        assert result["confidence_modifier"] == 0.0

    def test_beyond_18_days_no_penalty(self):
        earnings = datetime(2024, 6, 10, tzinfo=timezone.utc)  # 26 days out
        result = get_earnings_modifier("NVDA", earnings, today=self._today())
        assert result["confidence_modifier"] == 0.0
        assert not result["force_defined_risk"]

    def test_modifier_clamped_to_negative(self):
        earnings = datetime(2024, 5, 16, tzinfo=timezone.utc)  # 1 day out
        result = get_earnings_modifier("NVDA", earnings, today=self._today())
        assert result["confidence_modifier"] <= 0.0

    def test_6_to_18_days_partial_penalty(self):
        earnings = datetime(2024, 5, 25, tzinfo=timezone.utc)  # 10 days out
        result = get_earnings_modifier("NVDA", earnings, today=self._today())
        assert result["confidence_modifier"] < 0.0
        assert not result["force_defined_risk"]

    def test_modifier_bounds_clamp_a_retuned_penalty(self):
        """Tier B batch 3 (2026-08-19): the clamp now reads from
        config.modifier_bounds.earnings_proximity instead of a bare [-20, 0]."""
        earnings = datetime(2024, 5, 16, tzinfo=timezone.utc)  # 1 day out
        cfg = {"modifiers": {"earnings": {"within_5_days_penalty": -50}}}
        result = get_earnings_modifier("NVDA", earnings, today=self._today(), cfg=cfg)
        assert result["confidence_modifier"] == -20.0  # clamped to default bound

        wider_cfg = {
            "modifiers": {"earnings": {"within_5_days_penalty": -50}},
            "modifier_bounds": {"earnings_proximity": {"min": -40, "max": 0}},
        }
        result = get_earnings_modifier("NVDA", earnings, today=self._today(), cfg=wider_cfg)
        assert result["confidence_modifier"] == -40.0  # clamped to the new bound


# ---------------------------------------------------------------------------
# Seasonality
# ---------------------------------------------------------------------------

class TestSeasonality:
    def test_december_is_weakest(self):
        # Sign flipped 2026-08-15: real sector-pure semiconductor outcomes
        # (backtesting/modifier_calibration_diagnostic.py, after fixing the
        # backtest's own sector-scoping bug) showed the original "Q4 is
        # strong" calendar was backwards — "seasonally strong" months won
        # 38.9% (n=72) vs. "seasonally weak" months at 70.7% (n=82). See
        # config/swing_config.yaml's monthly_modifiers comment.
        dec = datetime(2024, 12, 1, tzinfo=timezone.utc)
        result = get_seasonality_modifier(date=dec)
        assert result["confidence_modifier"] == -5.0
        assert result["seasonality_state"] == "weak"
        assert result["month"] == 12

    def test_january_is_strong(self):
        jan = datetime(2024, 1, 1, tzinfo=timezone.utc)
        result = get_seasonality_modifier(date=jan)
        assert result["confidence_modifier"] > 0
        assert result["seasonality_state"] == "strong"

    def test_result_clamped_to_spec_bounds(self):
        for month in range(1, 13):
            dt = datetime(2024, month, 1, tzinfo=timezone.utc)
            result = get_seasonality_modifier(date=dt)
            assert -5.0 <= result["confidence_modifier"] <= 5.0

    def test_required_keys_present(self):
        result = get_seasonality_modifier()
        for key in ("month", "quarter", "seasonality_state", "confidence_modifier", "rationale"):
            assert key in result

    def test_non_semiconductor_sector_is_neutralized(self):
        """
        This monthly profile is semiconductor-specific (PC/server build cycles,
        NVDA/AMD product-cycle ordering) — applying it to a bank or healthcare
        ticker is actively misleading, not just imprecise. December (real
        modifier -5.0, sign-flipped 2026-08-15 — see class docstring on
        test_december_is_weakest) should resolve to a neutral 0.0 for a
        different sector.
        """
        dec = datetime(2024, 12, 1, tzinfo=timezone.utc)
        semis_result = get_seasonality_modifier(date=dec, sector="semiconductors")
        banks_result = get_seasonality_modifier(date=dec, sector="regional_banks")

        assert semis_result["confidence_modifier"] == -5.0
        assert semis_result["sector_scoped"] is False

        assert banks_result["confidence_modifier"] == 0.0
        assert banks_result["seasonality_state"] == "neutral"
        assert banks_result["sector_scoped"] is True
        # month/quarter still reported for observability
        assert banks_result["month"] == 12

    def test_no_sector_arg_preserves_original_behavior(self):
        dec = datetime(2024, 12, 1, tzinfo=timezone.utc)
        result = get_seasonality_modifier(date=dec)
        assert result["confidence_modifier"] == -5.0
        assert result["sector_scoped"] is False

    def test_config_override(self):
        # Key must match swing_config.yaml's actual schema (modifiers.seasonality.
        # monthly_modifiers) — this test previously used "monthly_adjustments",
        # silently matching the code's pre-fix key mismatch instead of catching it.
        cfg = {"modifiers": {"seasonality": {"monthly_modifiers": {"12": -1.0}}}}
        dec = datetime(2024, 12, 1, tzinfo=timezone.utc)
        result = get_seasonality_modifier(date=dec, cfg=cfg)
        assert result["confidence_modifier"] == -1.0

    def test_q4_is_weak(self):
        for month in [10, 11, 12]:
            dt = datetime(2024, month, 1, tzinfo=timezone.utc)
            result = get_seasonality_modifier(date=dt)
            assert result["quarter"] == 4
            assert result["confidence_modifier"] <= -3.0

    def test_config_override_int_keys(self):
        # yaml.safe_load() parses swing_config.yaml's unquoted numeric keys
        # (e.g. `12: -1.0`) as int, not str — a string-keyed test dict like
        # test_config_override's above can pass even when the real int-keyed
        # lookup is broken. This test uses int keys to match real YAML parsing.
        cfg = {"modifiers": {"seasonality": {"monthly_modifiers": {12: -1.0}}}}
        dec = datetime(2024, 12, 1, tzinfo=timezone.utc)
        result = get_seasonality_modifier(date=dec, cfg=cfg)
        assert result["confidence_modifier"] == -1.0

    def test_real_config_file_august(self):
        # End-to-end: load the actual swing_config.yaml (not a hand-built test
        # dict) and confirm August resolves to its real configured value (0),
        # not the hardcoded quarterly fallback (+1.0 for Q3) a broken int/str
        # key lookup would silently substitute instead.
        import yaml
        from pathlib import Path
        cfg = yaml.safe_load(Path("config/swing_config.yaml").read_text(encoding="utf-8"))
        aug = datetime(2026, 8, 1, tzinfo=timezone.utc)
        result = get_seasonality_modifier(date=aug, cfg=cfg)
        assert result["confidence_modifier"] == 0.0


# ---------------------------------------------------------------------------
# Macro Overlay
# ---------------------------------------------------------------------------

class TestMacroOverlay:
    def _flat_series(self, n=25, value=4.0):
        return pd.Series([value] * n)

    def test_adverse_when_tnx_and_dxy_rising(self):
        # Window=20: _period_pct_change reads iloc[-21] as "past", iloc[-1] as "current".
        # Series of 26 elements: first 6 at old value, last 20 at new (higher) value.
        # iloc[-21] = index 5 = 4.0 (old); iloc[-1] = index 25 = 4.21 (new) → +5% → adverse.
        tnx = pd.Series([4.0] * 6 + [4.0 * 1.05] * 20)
        dxy = pd.Series([100.0] * 6 + [100.0 * 1.03] * 20)
        result = compute_macro_state(tnx, dxy, china_keyword_count_5d=0)
        assert result["macro_state"] == MACRO_ADVERSE
        assert result["confidence_modifier"] == -10.0

    def test_favorable_when_tnx_and_dxy_falling(self):
        # iloc[-21] = old high value, iloc[-1] = new low value → falling → favorable
        tnx = pd.Series([4.0] * 6 + [4.0 * 0.95] * 20)
        dxy = pd.Series([100.0] * 6 + [100.0 * 0.97] * 20)
        result = compute_macro_state(tnx, dxy, china_keyword_count_5d=0)
        assert result["macro_state"] == MACRO_FAVORABLE
        assert result["confidence_modifier"] == 3.0

    def test_neutral_when_mixed_signals(self):
        tnx = self._flat_series(25, 4.0)
        dxy = self._flat_series(25, 100.0)
        # China high = 1 adverse signal → neutral
        result = compute_macro_state(tnx, dxy, china_keyword_count_5d=10)
        assert result["macro_state"] == MACRO_NEUTRAL

    def test_adverse_with_china_tension_and_rising_tnx(self):
        tnx = pd.Series([4.0] * 6 + [4.0 * 1.05] * 20)
        dxy = self._flat_series(26, 100.0)
        result = compute_macro_state(tnx, dxy, china_keyword_count_5d=10)
        assert result["macro_state"] == MACRO_ADVERSE

    def test_result_keys_present(self):
        tnx = self._flat_series(25, 4.0)
        dxy = self._flat_series(25, 100.0)
        result = compute_macro_state(tnx, dxy, china_keyword_count_5d=0)
        for key in ("macro_state", "tnx_trend", "dxy_trend", "china_tension_level",
                    "confidence_modifier", "computed_at_utc", "adverse_signal_count"):
            assert key in result

    def test_modifier_bounds(self):
        assert get_macro_modifier(MACRO_ADVERSE) == -10.0
        assert get_macro_modifier(MACRO_FAVORABLE) == 3.0
        assert get_macro_modifier(MACRO_NEUTRAL) == 0.0

    def test_modifier_bounds_clamp_a_retuned_penalty(self):
        """Tier B batch 3 (2026-08-19): adverse_penalty/favorable_boost were
        previously unenforced against modifier_bounds — now genuinely
        clamped, on the bullish scale, before the bearish sign-flip."""
        cfg = {"modifiers": {"macro_overlay": {"adverse_penalty": -50}}}
        assert get_macro_modifier(MACRO_ADVERSE, cfg) == -10.0  # clamped to default bound
        assert get_macro_modifier(MACRO_ADVERSE, cfg, direction="bearish") == 10.0

        wider_cfg = {
            "modifiers": {"macro_overlay": {"adverse_penalty": -50}},
            "modifier_bounds": {"macro_overlay": {"min": -25, "max": 3}},
        }
        assert get_macro_modifier(MACRO_ADVERSE, wider_cfg) == -25.0  # clamped to the new bound

    def test_insufficient_data_returns_neutral_signals(self):
        tnx = pd.Series([4.0, 4.1])  # too short for 20-day window
        dxy = pd.Series([100.0, 100.5])
        result = compute_macro_state(tnx, dxy, china_keyword_count_5d=0)
        # Both TNX and DXY fall back to neutral → overall favorable or neutral
        assert result["macro_state"] in (MACRO_NEUTRAL, MACRO_FAVORABLE)

    def test_non_semiconductor_sector_is_neutralized_even_with_adverse_signals(self):
        """
        TNX-hawkish-is-adverse and DXY-strength-is-adverse are semiconductor-
        specific rationale (growth-stock discount rate sensitivity; TSM/ASML
        foreign-ADR currency exposure) — applying them to a regional bank,
        where rising rates typically widen net interest margin, would be
        backwards, not just imprecise. A clearly-adverse reading for
        semiconductors must resolve neutral for a different sector.
        """
        tnx = pd.Series([4.0] * 6 + [4.0 * 1.05] * 20)  # rising → adverse for semis
        dxy = pd.Series([100.0] * 6 + [100.0 * 1.03] * 20)  # rising → adverse for semis

        semis_result = compute_macro_state(tnx, dxy, china_keyword_count_5d=0, sector="semiconductors")
        assert semis_result["macro_state"] == MACRO_ADVERSE
        assert semis_result["confidence_modifier"] == -10.0
        assert semis_result["sector_scoped"] is False

        banks_result = compute_macro_state(tnx, dxy, china_keyword_count_5d=0, sector="regional_banks")
        assert banks_result["macro_state"] == MACRO_NEUTRAL
        assert banks_result["confidence_modifier"] == 0.0
        assert banks_result["sector_scoped"] is True
        # Trend readings are still real/observable even though neutralized
        assert banks_result["tnx_trend"] == "rising"
        assert banks_result["dxy_trend"] == "rising"

    def test_no_sector_arg_preserves_original_behavior(self):
        tnx = pd.Series([4.0] * 6 + [4.0 * 1.05] * 20)
        dxy = pd.Series([100.0] * 6 + [100.0 * 1.03] * 20)
        result = compute_macro_state(tnx, dxy, china_keyword_count_5d=0)
        assert result["macro_state"] == MACRO_ADVERSE
        assert result["sector_scoped"] is False


class TestChinaThemeDoubleCountDampening:
    """macro_overlay's china_tension_level and news_layer's china_export
    theme both scan the same headlines — dampen_news_china_theme_if_macro_confirmed
    zeroes the redundant News contribution when both agree, same pattern as
    cross_ticker's sector_wide_discount dedup."""

    def _news(self, dominant_theme="china_export", theme_alignment_score=4.0, news_total=10.0):
        return {
            "dominant_narrative_theme": dominant_theme,
            "theme_alignment_score": theme_alignment_score,
            "news_score_total": news_total,
        }

    def test_dampens_when_macro_high_and_news_agrees(self):
        news = self._news()
        result = dampen_news_china_theme_if_macro_confirmed(news, "high")
        assert result["theme_alignment_score"] == 0.0
        assert result["news_score_total"] == 6.0
        assert result["china_tension_double_count_dampened"] is True

    def test_no_op_when_macro_not_high(self):
        news = self._news()
        result = dampen_news_china_theme_if_macro_confirmed(news, "normal")
        assert result == news
        assert "china_tension_double_count_dampened" not in result

    def test_no_op_when_news_theme_disagrees(self):
        news = self._news(dominant_theme="ai_demand")
        result = dampen_news_china_theme_if_macro_confirmed(news, "high")
        assert result == news

    def test_does_not_mutate_input(self):
        news = self._news()
        dampen_news_china_theme_if_macro_confirmed(news, "high")
        assert news["theme_alignment_score"] == 4.0  # original untouched


class TestMacroStatePersistence:
    """
    save_macro_state/load_macro_state are observability-only — nothing in the
    scoring path reads the file back (run_swing_model.py/paper_runner.py
    recompute macro state fresh every scan via _compute_macro_safe and pass it
    directly into compute_confidence_score). This just confirms the round-trip
    itself works, now that the live pipeline actually calls save_macro_state()
    after every scan instead of leaving data/processed/macro_state.json stale.
    """

    def test_save_then_load_round_trips(self, tmp_path, monkeypatch):
        import shared.utils.macro_overlay as macro_overlay_module

        state_file = tmp_path / "macro_state.json"
        monkeypatch.setattr(macro_overlay_module, "_MACRO_STATE_FILE", state_file)

        tnx = pd.Series([4.0] * 6 + [4.0 * 1.05] * 20)
        dxy = pd.Series([100.0] * 6 + [100.0 * 1.03] * 20)
        computed = compute_macro_state(tnx, dxy, china_keyword_count_5d=0)

        save_macro_state(computed)
        assert state_file.exists()

        loaded = load_macro_state()
        assert loaded["macro_state"] == computed["macro_state"] == MACRO_ADVERSE
        assert loaded["confidence_modifier"] == computed["confidence_modifier"]

    def test_load_missing_file_returns_neutral_default(self, tmp_path, monkeypatch):
        import shared.utils.macro_overlay as macro_overlay_module

        monkeypatch.setattr(macro_overlay_module, "_MACRO_STATE_FILE", tmp_path / "does_not_exist.json")
        result = load_macro_state()
        assert result["macro_state"] == MACRO_NEUTRAL
        assert result["confidence_modifier"] == 0.0
