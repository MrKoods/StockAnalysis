"""Tests for backtesting/modifier_calibration_diagnostic.py — measures whether
regime/seasonality/macro modifiers' real bucket-level outcomes track their
configured magnitudes, using synthetic outcome dicts (no historical CSVs
needed for these unit tests)."""

import pandas as pd

from backtesting.modifier_calibration_diagnostic import (
    bucket_outcomes_by_modifier_sign,
    _NEVER_EXERCISED_IN_BACKTEST,
    _EXERCISED_MODIFIERS,
)


def _outcome(outcome_type, regime_modifier=0.0, achieved_rr=1.0):
    return {"outcome": outcome_type, "achieved_rr": achieved_rr, "regime_modifier": regime_modifier}


class TestBucketOutcomesByModifierSign:
    def test_splits_into_three_buckets(self):
        outcomes = [
            _outcome("win", regime_modifier=-10),
            _outcome("loss", regime_modifier=-5),
            _outcome("win", regime_modifier=0),
            _outcome("win", regime_modifier=5),
            _outcome("loss", regime_modifier=10),
        ]
        df = bucket_outcomes_by_modifier_sign(outcomes, "regime_modifier")
        assert set(df["bucket"]) == {"negative", "zero", "positive"}
        neg = df[df["bucket"] == "negative"].iloc[0]
        assert neg["n_trades"] == 2

    def test_win_rate_computed_per_bucket(self):
        outcomes = [
            _outcome("win", regime_modifier=-10),
            _outcome("win", regime_modifier=-10),
            _outcome("loss", regime_modifier=10),
            _outcome("loss", regime_modifier=10),
        ]
        df = bucket_outcomes_by_modifier_sign(outcomes, "regime_modifier")
        neg = df[df["bucket"] == "negative"].iloc[0]
        pos = df[df["bucket"] == "positive"].iloc[0]
        assert neg["win_rate"] == 1.0
        assert pos["win_rate"] == 0.0

    def test_empty_bucket_gets_none_win_rate_not_zero(self):
        outcomes = [_outcome("win", regime_modifier=5)]
        df = bucket_outcomes_by_modifier_sign(outcomes, "regime_modifier")
        neg = df[df["bucket"] == "negative"].iloc[0]
        assert neg["n_trades"] == 0
        # pandas upcasts a mixed None/float column to NaN, not None
        assert pd.isna(neg["win_rate"])

    def test_missing_modifier_key_excluded_from_all_buckets(self):
        outcomes = [{"outcome": "win", "achieved_rr": 1.0}]  # no regime_modifier key
        df = bucket_outcomes_by_modifier_sign(outcomes, "regime_modifier")
        assert df["n_trades"].sum() == 0

    def test_never_exercised_and_exercised_lists_are_disjoint_and_complete(self):
        all_six = {
            "regime_modifier", "sector_rotation_modifier", "earnings_modifier",
            "cross_ticker_modifier", "seasonality_modifier", "macro_modifier",
        }
        assert set(_NEVER_EXERCISED_IN_BACKTEST) | set(_EXERCISED_MODIFIERS) == all_six
        assert set(_NEVER_EXERCISED_IN_BACKTEST) & set(_EXERCISED_MODIFIERS) == set()
