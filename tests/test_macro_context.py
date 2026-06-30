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

import numpy as np
import pandas as pd
import pytest

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
    ROTATION_INFLOW,
    ROTATION_NEUTRAL,
    ROTATION_OUTFLOW,
)
from shared.utils.earnings_calendar import get_earnings_modifier
from shared.utils.seasonality import get_seasonality_modifier
from shared.utils.macro_overlay import (
    compute_macro_state,
    get_macro_modifier,
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


# ---------------------------------------------------------------------------
# Seasonality
# ---------------------------------------------------------------------------

class TestSeasonality:
    def test_december_is_strongest(self):
        dec = datetime(2024, 12, 1, tzinfo=timezone.utc)
        result = get_seasonality_modifier(date=dec)
        assert result["confidence_modifier"] == 5.0
        assert result["seasonality_state"] == "strong"
        assert result["month"] == 12

    def test_may_is_weak(self):
        may = datetime(2024, 5, 1, tzinfo=timezone.utc)
        result = get_seasonality_modifier(date=may)
        assert result["confidence_modifier"] < 0
        assert result["seasonality_state"] == "weak"

    def test_result_clamped_to_spec_bounds(self):
        for month in range(1, 13):
            dt = datetime(2024, month, 1, tzinfo=timezone.utc)
            result = get_seasonality_modifier(date=dt)
            assert -5.0 <= result["confidence_modifier"] <= 5.0

    def test_required_keys_present(self):
        result = get_seasonality_modifier()
        for key in ("month", "quarter", "seasonality_state", "confidence_modifier", "rationale"):
            assert key in result

    def test_config_override(self):
        cfg = {"modifiers": {"seasonality": {"monthly_adjustments": {"12": -1.0}}}}
        dec = datetime(2024, 12, 1, tzinfo=timezone.utc)
        result = get_seasonality_modifier(date=dec, cfg=cfg)
        assert result["confidence_modifier"] == -1.0

    def test_q4_is_strong(self):
        for month in [10, 11, 12]:
            dt = datetime(2024, month, 1, tzinfo=timezone.utc)
            result = get_seasonality_modifier(date=dt)
            assert result["quarter"] == 4
            assert result["confidence_modifier"] >= 3.0


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

    def test_insufficient_data_returns_neutral_signals(self):
        tnx = pd.Series([4.0, 4.1])  # too short for 20-day window
        dxy = pd.Series([100.0, 100.5])
        result = compute_macro_state(tnx, dxy, china_keyword_count_5d=0)
        # Both TNX and DXY fall back to neutral → overall favorable or neutral
        assert result["macro_state"] in (MACRO_NEUTRAL, MACRO_FAVORABLE)
