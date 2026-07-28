"""
Tests for paper_trading/live_collinearity_diagnostic.py — the live counterpart
to backtesting/collinearity_diagnostic.py (v2.2.16), extended to real
paper-trading scan history per the v2.2.16 extension.
"""

import pytest

from app_ui import db as app_db
from paper_trading.live_collinearity_diagnostic import collect_score_pairs


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

    def test_ignores_other_layer_scores(self, db_path):
        _log_result(db_path, "NVDA", technical=20.0, sentiment=5.0)
        df = collect_score_pairs(db_path)
        assert set(df.columns) == {"ticker", "result_id", "technical_total", "sentiment_total"}

    def test_drops_rows_missing_either_score(self, db_path):
        # A result with only a technical layer logged (e.g. partial layer-write
        # failure) shouldn't crash the join — it should just be excluded.
        run_id = app_db.create_scan_run("post_close", "", db_path=db_path)
        result_id = app_db.insert_ticker_result(run_id, "NVDA", "no_signal", 30.0, db_path=db_path)
        app_db.insert_layer_score(result_id, "technical", 20.0, db_path=db_path)
        # no sentiment layer inserted

        _log_result(db_path, "AMD", technical=15.0, sentiment=8.0)  # complete row

        df = collect_score_pairs(db_path)
        assert len(df) == 1
        assert df.iloc[0]["ticker"] == "AMD"

    def test_multiple_scans_all_included(self, db_path):
        for i in range(5):
            _log_result(db_path, "NVDA", technical=10.0 + i, sentiment=5.0 + i)
        df = collect_score_pairs(db_path)
        assert len(df) == 5


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
