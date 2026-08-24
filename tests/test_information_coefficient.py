"""
Tests for backtesting.metrics.compute_information_coefficient — the rank
correlation between a raw per-bar score and its forward outcome, computed on
the FULL scored population (see backtest_engine.py's `all_outcomes`) rather
than just the confidence>=CONFIDENCE_THRESHOLD qualifying subset win_rate/
bootstrap_expectancy_ci operate on. Pure-math tests only; no historical data
needed.
"""

import pytest

from backtesting.metrics import compute_information_coefficient


def _outcomes(scores: list[float], returns: list[float]) -> list[dict]:
    return [{"confidence": s, "achieved_rr": r} for s, r in zip(scores, returns)]


class TestKnownRelationships:
    def test_perfect_monotonic_relationship_gives_ic_near_one(self):
        # Strictly increasing score, strictly increasing return -> perfect
        # rank agreement regardless of the actual (nonlinear) shape.
        scores = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        returns = [s**1.3 for s in scores]  # nonlinear but monotonic
        result = compute_information_coefficient(_outcomes(scores, returns))
        assert result["ic"] == pytest.approx(1.0, abs=1e-9)
        assert result["p_value"] < 0.01
        assert result["n"] == 10

    def test_perfect_inverse_relationship_gives_ic_near_negative_one(self):
        scores = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        returns = [-s for s in scores]
        result = compute_information_coefficient(_outcomes(scores, returns))
        assert result["ic"] == pytest.approx(-1.0, abs=1e-9)
        assert result["p_value"] < 0.01

    def test_no_relationship_gives_ic_near_zero_not_significant(self):
        # Scores in one fixed order, returns shuffled to break any rank
        # relationship — real financial noise, not a contrived degenerate case.
        scores = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        returns = [0.5, -0.3, 0.1, -0.8, 0.4, -0.1, 0.6, -0.5, 0.2, -0.4]
        result = compute_information_coefficient(_outcomes(scores, returns))
        assert abs(result["ic"]) < 0.5
        assert result["p_value"] > 0.05  # not statistically significant


class TestEdgeCases:
    def test_empty_outcomes_returns_neutral_zero(self):
        result = compute_information_coefficient([])
        assert result == {"ic": 0.0, "p_value": 1.0, "n": 0, "method": "spearman", "score_field": "confidence"}

    def test_fewer_than_three_pairs_returns_neutral_zero(self):
        result = compute_information_coefficient(_outcomes([10, 20], [1.0, 2.0]))
        assert result["ic"] == 0.0
        assert result["p_value"] == 1.0
        assert result["n"] == 2

    def test_missing_fields_are_excluded_not_treated_as_zero(self):
        outcomes = [
            {"confidence": 10, "achieved_rr": 1.0},
            {"confidence": 20},  # missing achieved_rr entirely
            {"confidence": 30, "achieved_rr": 3.0},
            {"confidence": 40, "achieved_rr": 4.0},
        ]
        result = compute_information_coefficient(outcomes)
        assert result["n"] == 3  # the incomplete row is excluded, not zero-filled

    def test_constant_score_returns_neutral_not_nan(self):
        # Zero variance in the score series -> scipy returns NaN; must be
        # normalized to a neutral read, never leak NaN to a caller (which
        # would break f-string formatting/round() in run_backtest.py's report).
        outcomes = _outcomes([50, 50, 50, 50, 50], [1.0, -2.0, 0.5, 3.0, -1.0])
        result = compute_information_coefficient(outcomes)
        assert result["ic"] == 0.0
        assert result["p_value"] == 1.0
        assert result["n"] == 5

    def test_custom_score_and_return_fields(self):
        outcomes = [
            {"technical_total": s, "pnl_pct": s / 100.0}
            for s in [5, 10, 15, 20, 25, 30]
        ]
        result = compute_information_coefficient(outcomes, score_field="technical_total", return_field="pnl_pct")
        assert result["ic"] == pytest.approx(1.0, abs=1e-9)
        assert result["score_field"] == "technical_total"

    def test_pearson_method_selectable(self):
        outcomes = _outcomes([10, 20, 30, 40, 50], [1, 2, 3, 4, 5])
        result = compute_information_coefficient(outcomes, method="pearson")
        assert result["method"] == "pearson"
        assert result["ic"] == pytest.approx(1.0, abs=1e-9)
