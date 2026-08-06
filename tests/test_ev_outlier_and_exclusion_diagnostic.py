"""
Tests for paper_trading/ev_outlier_and_exclusion_diagnostic.py — mining the
exclusion_summary/ev_outlier_z columns fixes #2 and #6 started persisting,
instead of the data sitting there unused.
"""

import pytest

from app_ui import db as app_db
from paper_trading.ev_outlier_and_exclusion_diagnostic import (
    collect_exclusion_rows,
    collect_ev_outlier_rows,
    aggregate_exclusion_reasons,
    find_zero_eligible_repeat_offenders,
    summarize_ev_outliers,
)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test_history.db"


def _log_exclusion(db_path, ticker, sector, exclusion_summary, structures_eligible=0, trade_structure=None):
    run_id = app_db.create_scan_run("post_close", "", db_path=db_path)
    return app_db.insert_ticker_result(
        run_id, ticker, "no_signal", 65.0,
        trade_structure=trade_structure, sector=sector,
        structures_eligible_after_filters=structures_eligible,
        exclusion_summary=exclusion_summary,
        db_path=db_path,
    )


def _log_ev_outlier(db_path, ticker, trade_structure, expected_value, ev_outlier_z):
    run_id = app_db.create_scan_run("post_close", "", db_path=db_path)
    return app_db.insert_ticker_result(
        run_id, ticker, "no_signal", 65.0,
        trade_structure=trade_structure, expected_value=expected_value,
        ev_outlier_z=ev_outlier_z, db_path=db_path,
    )


class TestCollectExclusionRows:
    def test_empty_db_returns_empty(self, db_path):
        assert collect_exclusion_rows(db_path).empty

    def test_only_pulls_rows_with_exclusion_summary(self, db_path):
        _log_exclusion(db_path, "TSM", "semiconductors", "42 structures excluded — capital exceeds 5pct")
        run_id = app_db.create_scan_run("post_close", "", db_path=db_path)
        app_db.insert_ticker_result(run_id, "LLY", "no_signal", 30.0, db_path=db_path)  # below threshold, no ranking
        df = collect_exclusion_rows(db_path)
        assert len(df) == 1
        assert df.iloc[0]["ticker"] == "TSM"


class TestAggregateExclusionReasons:
    def test_sums_counts_across_rows(self, db_path):
        _log_exclusion(db_path, "TSM", "semiconductors",
                        "20 structures excluded — capital exceeds 5pct; 10 structures excluded — direction mismatch bearish")
        _log_exclusion(db_path, "AMZN", "consumer_discretionary",
                        "15 structures excluded — capital exceeds 5pct")
        df = collect_exclusion_rows(db_path)
        agg = aggregate_exclusion_reasons(df)
        capital_row = agg[agg["reason"] == "capital exceeds 5pct"].iloc[0]
        assert capital_row["count"] == 35

    def test_group_by_sector_keeps_reasons_separate(self, db_path):
        _log_exclusion(db_path, "TSM", "semiconductors", "20 structures excluded — capital exceeds 5pct")
        _log_exclusion(db_path, "PFE", "healthcare", "5 structures excluded — capital exceeds 5pct")
        df = collect_exclusion_rows(db_path)
        agg = aggregate_exclusion_reasons(df, group_by="sector")
        semis = agg[agg["sector"] == "semiconductors"]
        health = agg[agg["sector"] == "healthcare"]
        assert semis.iloc[0]["count"] == 20
        assert health.iloc[0]["count"] == 5

    def test_empty_dataframe_returns_empty(self):
        import pandas as pd
        result = aggregate_exclusion_reasons(pd.DataFrame())
        assert result.empty

    def test_all_structures_eligible_string_parses_to_no_rows(self, db_path):
        _log_exclusion(db_path, "NVDA", "semiconductors", "All structures eligible.", trade_structure="long_strangle")
        df = collect_exclusion_rows(db_path)
        agg = aggregate_exclusion_reasons(df)
        assert agg.empty


class TestFindZeroEligibleRepeatOffenders:
    def test_flags_ticker_at_or_above_min_occurrences(self, db_path):
        for _ in range(3):
            _log_exclusion(db_path, "TSM", "semiconductors", "42 structures excluded — capital exceeds 5pct",
                            structures_eligible=0)
        df = collect_exclusion_rows(db_path)
        offenders = find_zero_eligible_repeat_offenders(df, min_occurrences=3)
        assert "TSM" in offenders["ticker"].values
        assert offenders[offenders["ticker"] == "TSM"].iloc[0]["zero_eligible_count"] == 3

    def test_does_not_flag_below_min_occurrences(self, db_path):
        _log_exclusion(db_path, "TSM", "semiconductors", "42 structures excluded — capital exceeds 5pct",
                        structures_eligible=0)
        df = collect_exclusion_rows(db_path)
        offenders = find_zero_eligible_repeat_offenders(df, min_occurrences=3)
        assert offenders.empty

    def test_ignores_rows_with_eligible_structures(self, db_path):
        for _ in range(5):
            _log_exclusion(db_path, "NVDA", "semiconductors", "10 structures excluded — direction mismatch bearish",
                            structures_eligible=32, trade_structure="long_strangle")
        df = collect_exclusion_rows(db_path)
        offenders = find_zero_eligible_repeat_offenders(df, min_occurrences=3)
        assert offenders.empty


class TestSummarizeEvOutliers:
    def test_empty_db_returns_empty(self, db_path):
        assert collect_ev_outlier_rows(db_path).empty

    def test_counts_flagged_vs_total_per_structure(self, db_path):
        _log_ev_outlier(db_path, "MU", "long_strangle", 12.0, 8.2)     # flagged
        _log_ev_outlier(db_path, "AVGO", "long_strangle", 1.5, 0.3)   # not flagged
        _log_ev_outlier(db_path, "NVDA", "long_strangle", 1.6, 0.1)   # not flagged
        df = collect_ev_outlier_rows(db_path)
        summary = summarize_ev_outliers(df, threshold=3.5)
        row = summary[summary["trade_structure"] == "long_strangle"].iloc[0]
        assert row["total_readings"] == 3
        assert row["flagged_count"] == 1
        assert row["max_abs_z"] == pytest.approx(8.2)

    def test_sorted_by_flagged_count_descending(self, db_path):
        _log_ev_outlier(db_path, "MU", "long_strangle", 12.0, 8.2)
        _log_ev_outlier(db_path, "HBAN", "diagonal_call", 0.3, 0.1)
        df = collect_ev_outlier_rows(db_path)
        summary = summarize_ev_outliers(df, threshold=3.5)
        assert summary.iloc[0]["trade_structure"] == "long_strangle"
