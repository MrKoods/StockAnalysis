"""
Tests for paper_trading/live_collinearity_diagnostic.py — the live counterpart
to backtesting/collinearity_diagnostic.py (v2.2.16), generalized from a single
hardcoded pair (technical_total, sentiment_total) to every pair of the 5
categories + 6 modifiers paper_runner.py logs to layer_scores.
"""

import pytest

from app_ui import db as app_db
from paper_trading.live_collinearity_diagnostic import (
    collect_score_pairs,
    compute_pairwise_collinearity,
)
from shared.utils.tail_dependence import conditional_top_quantile_rate


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_history.db"


def _log_result(db_path, ticker, technical, sentiment, other_layers=True):
    run_id = app_db.create_scan_run("post_close", "", db_path=db_path)
    result_id = app_db.insert_ticker_result(run_id, ticker, "qualifying", 90.0, db_path=db_path)
    app_db.insert_layer_score(result_id, "technical", technical, db_path=db_path)
    app_db.insert_layer_score(result_id, "sentiment", sentiment, db_path=db_path)
    if other_layers:
        app_db.insert_layer_score(result_id, "news", 5.0, db_path=db_path)
        app_db.insert_layer_score(result_id, "market_positioning", 8.0, db_path=db_path)
    return result_id


class TestCollectScorePairs:
    def test_empty_db_returns_empty_dataframe(self, db_path):
        df = collect_score_pairs(db_path)
        assert df.empty

    def test_pulls_technical_and_sentiment_for_each_result(self, db_path):
        _log_result(db_path, "NVDA", technical=20.0, sentiment=5.0)
        _log_result(db_path, "AMD", technical=15.0, sentiment=8.0)
        df = collect_score_pairs(db_path)
        assert len(df) == 2
        nvda = df[df["ticker"] == "NVDA"].iloc[0]
        assert nvda["technical_total"] == pytest.approx(20.0)
        assert nvda["sentiment_total"] == pytest.approx(5.0)

    def test_includes_every_logged_layer_renamed_to_its_scoring_field(self, db_path):
        _log_result(db_path, "NVDA", technical=20.0, sentiment=5.0)
        df = collect_score_pairs(db_path)
        # market_positioning/news were also logged by _log_result — the point of
        # generalizing beyond the original technical/sentiment-only pull.
        assert set(df.columns) == {
            "result_id", "ticker", "technical_total", "sentiment_total",
            "news_total", "positioning_total",
        }

    def test_keeps_rows_with_partial_layers_as_nan_instead_of_dropping(self, db_path):
        # A result with only a technical layer logged (e.g. partial layer-write
        # failure) should still appear, with NaN for the missing layer — dropping
        # it outright would remove data other pairs (that don't involve
        # sentiment) could otherwise use.
        run_id = app_db.create_scan_run("post_close", "", db_path=db_path)
        result_id = app_db.insert_ticker_result(run_id, "NVDA", "no_signal", 30.0, db_path=db_path)
        app_db.insert_layer_score(result_id, "technical", 20.0, db_path=db_path)
        # no sentiment layer inserted

        _log_result(db_path, "AMD", technical=15.0, sentiment=8.0)  # complete row

        df = collect_score_pairs(db_path)
        assert len(df) == 2
        nvda = df[df["ticker"] == "NVDA"].iloc[0]
        assert nvda["technical_total"] == pytest.approx(20.0)
        assert pd_isna(nvda["sentiment_total"])

    def test_multiple_scans_all_included(self, db_path):
        for i in range(5):
            _log_result(db_path, "NVDA", technical=10.0 + i, sentiment=5.0 + i)
        df = collect_score_pairs(db_path)
        assert len(df) == 5

    def test_unmapped_layer_name_kept_under_its_raw_name(self, db_path):
        run_id = app_db.create_scan_run("post_close", "", db_path=db_path)
        result_id = app_db.insert_ticker_result(run_id, "NVDA", "no_signal", 30.0, db_path=db_path)
        app_db.insert_layer_score(result_id, "some_future_layer", 42.0, db_path=db_path)
        df = collect_score_pairs(db_path)
        assert "some_future_layer" in df.columns
        assert df.iloc[0]["some_future_layer"] == pytest.approx(42.0)


class TestCorrelationComputation:
    def test_perfectly_correlated_scores_give_r_near_one(self, db_path):
        for i in range(10):
            _log_result(db_path, "NVDA", technical=float(i), sentiment=float(i) * 2)
        df = collect_score_pairs(db_path)
        r = df["technical_total"].corr(df["sentiment_total"])
        assert r == pytest.approx(1.0, abs=0.01)

    def test_uncorrelated_scores_give_low_r(self, db_path):
        technical_vals = [10, 20, 15, 25, 12, 22, 18, 30, 5, 28]
        sentiment_vals = [3, 7, 1, 9, 4, 2, 8, 5, 6, 0]
        for t, s in zip(technical_vals, sentiment_vals):
            _log_result(db_path, "NVDA", technical=float(t), sentiment=float(s))
        df = collect_score_pairs(db_path)
        r = df["technical_total"].corr(df["sentiment_total"])
        assert abs(r) < 0.5


class TestTailDependenceIntegration:
    def test_conditional_top_quantile_rate_runs_against_collected_scores(self, db_path):
        # Regression check that collect_score_pairs' output shape (column names,
        # dtypes) is what conditional_top_quantile_rate expects — not re-testing
        # the math itself (see tests/test_tail_dependence.py for that).
        for i in range(20):
            _log_result(db_path, "NVDA", technical=float(i), sentiment=float(i % 5))
        df = collect_score_pairs(db_path)
        result = conditional_top_quantile_rate(df, "technical_total", "sentiment_total", quantile=0.75)
        assert result["n"] == 20
        assert 0.0 <= result["conditional_rate"] <= 1.0
        assert 0.0 <= result["unconditional_rate"] <= 1.0


class TestPairwiseCollinearity:
    def test_checks_every_unique_pair_of_columns(self, db_path):
        for i in range(15):
            _log_result(db_path, "NVDA", technical=float(i), sentiment=float(i % 5))
        df = collect_score_pairs(db_path)
        # 4 score columns (technical, sentiment, news, positioning) -> C(4,2) = 6 pairs.
        pairwise = compute_pairwise_collinearity(df)
        assert len(pairwise) == 6
        assert {"col_a", "col_b", "n", "pearson_r", "spearman_rho", "tail_lift", "flagged"} <= set(pairwise.columns)

    def test_flags_a_pair_that_is_really_the_same_signal_twice(self, db_path):
        # Mirrors the actual live bug this generalization exists to catch:
        # regime_modifier and sector_rotation_modifier both derived from SMH
        # price action and summed as if independent. Here two logged layers
        # move in lockstep — the tool should flag that pair.
        for i in range(20):
            run_id = app_db.create_scan_run("post_close", "", db_path=db_path)
            result_id = app_db.insert_ticker_result(run_id, "NVDA", "no_signal", 50.0, db_path=db_path)
            app_db.insert_layer_score(result_id, "regime", float(-i), db_path=db_path)
            app_db.insert_layer_score(result_id, "sector_rotation", float(-i) * 0.9, db_path=db_path)

        df = collect_score_pairs(db_path)
        pairwise = compute_pairwise_collinearity(df)
        row = pairwise[
            ((pairwise["col_a"] == "regime_modifier") & (pairwise["col_b"] == "sector_rotation_modifier"))
            | ((pairwise["col_a"] == "sector_rotation_modifier") & (pairwise["col_b"] == "regime_modifier"))
        ].iloc[0]
        assert abs(row["pearson_r"]) >= 0.9
        assert bool(row["flagged"]) is True

    def test_does_not_flag_genuinely_independent_pair(self, db_path):
        technical_vals = [10, 20, 15, 25, 12, 22, 18, 30, 5, 28, 14, 19]
        sentiment_vals = [3, 7, 1, 9, 4, 2, 8, 5, 6, 0, 9, 3]
        for t, s in zip(technical_vals, sentiment_vals):
            _log_result(db_path, "NVDA", technical=float(t), sentiment=float(s))
        df = collect_score_pairs(db_path)
        pairwise = compute_pairwise_collinearity(df, columns=["technical_total", "sentiment_total"])
        row = pairwise.iloc[0]
        assert row["flagged"] == (abs(row["pearson_r"]) >= 0.5 or row["tail_lift"] >= 1.5)

    def test_uses_pairwise_dropna_not_whole_row_dropna(self, db_path):
        # NVDA's row is missing "news" entirely — a pair not involving news
        # should still use NVDA's data; only pairs involving news should drop it.
        run_id = app_db.create_scan_run("post_close", "", db_path=db_path)
        result_id = app_db.insert_ticker_result(run_id, "NVDA", "no_signal", 50.0, db_path=db_path)
        app_db.insert_layer_score(result_id, "technical", 20.0, db_path=db_path)
        app_db.insert_layer_score(result_id, "sentiment", 5.0, db_path=db_path)
        _log_result(db_path, "AMD", technical=15.0, sentiment=8.0, other_layers=True)

        df = collect_score_pairs(db_path)
        pairwise = compute_pairwise_collinearity(df)
        tech_sent = pairwise[
            (pairwise["col_a"] == "sentiment_total") & (pairwise["col_b"] == "technical_total")
        ].iloc[0]
        tech_news = pairwise[
            (pairwise["col_a"] == "news_total") & (pairwise["col_b"] == "technical_total")
        ].iloc[0]
        assert tech_sent["n"] == 2  # both rows have technical + sentiment
        assert tech_news["n"] == 1  # only AMD has news logged

    def test_empty_dataframe_returns_empty_result(self):
        import pandas as pd
        assert compute_pairwise_collinearity(pd.DataFrame()).empty


def pd_isna(value) -> bool:
    import pandas as pd
    return bool(pd.isna(value))
