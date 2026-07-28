"""
Tests for paper_trading/score_distribution_diagnostic.py — quantifies how far
real logged composite scores land from the 90-point go-live threshold and how
much headroom each scoring category has left unused.
"""

import pandas as pd
import pytest

from app_ui import db as app_db
from paper_trading.score_distribution_diagnostic import (
    collect_category_scores,
    collect_composite_scores,
    joint_peak_rate,
    threshold_qualification_rates,
)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_history.db"


def _log_result(db_path, ticker, composite_score, category_scores, sector="semiconductors"):
    run_id = app_db.create_scan_run("post_close", "", db_path=db_path)
    result_id = app_db.insert_ticker_result(
        run_id, ticker, "no_signal", composite_score, sector=sector, db_path=db_path
    )
    for layer_name, score in category_scores.items():
        app_db.insert_layer_score(result_id, layer_name, score, db_path=db_path)
    return result_id


class TestCollectCompositeScores:
    def test_empty_db_returns_empty_dataframe(self, db_path):
        df = collect_composite_scores(db_path)
        assert df.empty

    def test_pulls_composite_score_and_sector(self, db_path):
        _log_result(db_path, "NVDA", 42.5, {"technical": 20.0}, sector="semiconductors")
        df = collect_composite_scores(db_path)
        assert len(df) == 1
        row = df.iloc[0]
        assert row["ticker"] == "NVDA"
        assert row["composite_score"] == pytest.approx(42.5)
        assert row["sector"] == "semiconductors"


class TestCollectCategoryScores:
    def test_missing_category_is_nan_not_dropped(self, db_path):
        # Only technical logged — the row should still appear, other categories NaN.
        _log_result(db_path, "NVDA", 30.0, {"technical": 20.0})
        df = collect_category_scores(db_path)
        assert len(df) == 1
        assert df.iloc[0]["technical"] == pytest.approx(20.0)
        assert pd_isna(df.iloc[0]["sentiment"])

    def test_all_five_categories_pulled(self, db_path):
        _log_result(db_path, "NVDA", 90.0, {
            "technical": 36.0, "market_positioning": 18.0,
            "sentiment": 14.0, "news": 13.0, "fundamental": 9.0,
        })
        df = collect_category_scores(db_path)
        row = df.iloc[0]
        assert row["technical"] == pytest.approx(36.0)
        assert row["market_positioning"] == pytest.approx(18.0)
        assert row["sentiment"] == pytest.approx(14.0)
        assert row["news"] == pytest.approx(13.0)
        assert row["fundamental"] == pytest.approx(9.0)


class TestJointPeakRate:
    def test_no_rows_returns_zero(self, db_path):
        df = collect_category_scores(db_path)
        assert joint_peak_rate(df) == 0.0

    def test_all_categories_always_high_gives_full_joint_rate(self, db_path):
        for i in range(10):
            _log_result(db_path, "NVDA", 95.0, {
                "technical": 38.0, "market_positioning": 19.0,
                "sentiment": 14.5, "news": 14.0, "fundamental": 9.5,
            })
        df = collect_category_scores(db_path)
        assert joint_peak_rate(df, quantile=0.8, min_categories=5) == pytest.approx(1.0)

    def test_categories_never_jointly_peak_gives_low_rate(self, db_path):
        # Only one category is ever high on a given row, cycling through —
        # no row has 2+ simultaneously in their own top quantile.
        cats = ["technical", "market_positioning", "sentiment", "news", "fundamental"]
        low = {"technical": 5.0, "market_positioning": 2.0, "sentiment": 1.0, "news": 1.0, "fundamental": 1.0}
        for i in range(20):
            scores = dict(low)
            scores[cats[i % len(cats)]] = 100.0
            _log_result(db_path, "NVDA", 20.0, scores)
        df = collect_category_scores(db_path)
        assert joint_peak_rate(df, quantile=0.8, min_categories=2) < 0.3


def pd_isna(value) -> bool:
    import pandas as pd
    return bool(pd.isna(value))


class TestThresholdQualificationRates:
    def test_empty_scores_returns_empty_dataframe(self):
        df = threshold_qualification_rates(pd.DataFrame(columns=["composite_score"]))
        assert df.empty

    def test_none_ever_qualify_at_any_threshold(self):
        scores_df = pd.DataFrame({"composite_score": [40.0, 55.0, 71.72, 68.0]})
        df = threshold_qualification_rates(scores_df, thresholds=[85, 90, 95])
        assert (df["qualifying_rows"] == 0).all()
        assert (df["qualification_rate"] == 0.0).all()

    def test_lower_threshold_qualifies_more_rows(self):
        scores_df = pd.DataFrame({"composite_score": [72.0, 78.0, 83.0, 91.0]})
        df = threshold_qualification_rates(scores_df, thresholds=[70, 80, 90])
        rates = dict(zip(df["threshold"], df["qualifying_rows"]))
        assert rates[70] == 4
        assert rates[80] == 2
        assert rates[90] == 1

    def test_default_thresholds_match_backtest_sensitivity_defaults(self):
        scores_df = pd.DataFrame({"composite_score": [90.0]})
        df = threshold_qualification_rates(scores_df)
        assert list(df["threshold"]) == [85, 87, 90, 92, 95]
