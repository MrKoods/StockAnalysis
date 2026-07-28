"""Tests for shared/utils/tail_dependence.py."""

import pandas as pd
import pytest

from shared.utils.tail_dependence import conditional_top_quantile_rate


class TestConditionalTopQuantileRate:
    def test_empty_dataframe_returns_zeros(self):
        df = pd.DataFrame({"a": [], "b": []})
        result = conditional_top_quantile_rate(df, "a", "b")
        assert result["n"] == 0
        assert result["lift"] == 0.0

    def test_missing_column_returns_zeros(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        result = conditional_top_quantile_rate(df, "a", "b")
        assert result["n"] == 0

    def test_perfectly_aligned_tails_give_high_lift(self):
        # Top 25% of both columns are exactly the same 25 rows — perfect tail dependence.
        a = [1.0] * 75 + [10.0] * 25
        b = [1.0] * 75 + [10.0] * 25
        df = pd.DataFrame({"a": a, "b": b})
        result = conditional_top_quantile_rate(df, "a", "b", quantile=0.75)
        assert result["conditional_rate"] == pytest.approx(1.0)
        assert result["unconditional_rate"] == pytest.approx(0.25, abs=0.02)
        assert result["lift"] > 3.5  # ~4x: conditioning on a's top tail always catches b's top tail

    def test_independent_tails_give_lift_near_one(self):
        # b's top-25% rows are evenly spread across a's low and high halves —
        # conditioning on a tells you nothing about b.
        n = 100
        a = [1.0] * 75 + [10.0] * 25
        b = [10.0 if i % 4 == 0 else 1.0 for i in range(n)]
        df = pd.DataFrame({"a": a, "b": b})
        result = conditional_top_quantile_rate(df, "a", "b", quantile=0.75)
        assert result["lift"] == pytest.approx(1.0, abs=0.3)

    def test_rows_missing_either_column_are_dropped(self):
        df = pd.DataFrame({
            "a": [1.0, 2.0, None, 4.0],
            "b": [1.0, None, 3.0, 4.0],
        })
        result = conditional_top_quantile_rate(df, "a", "b")
        assert result["n"] == 2  # only rows 0 and 3 have both columns present
