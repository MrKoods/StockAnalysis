"""
Tests for app_ui/db.py — SQLite persistence layer backing the desktop app UI.
Each test uses its own tmp_path db file; no shared state between tests.
"""

import sqlite3

from app_ui import db


class TestScanRuns:
    def test_create_and_fetch(self, tmp_path):
        path = tmp_path / "history.db"
        run_id = db.create_scan_run("post_close", "watchlist: {}", db_path=path)
        run = db.get_scan_run(run_id, db_path=path)
        assert run["scan_type"] == "post_close"
        assert run["config_snapshot"] == "watchlist: {}"

    def test_list_runs_newest_first(self, tmp_path):
        path = tmp_path / "history.db"
        first = db.create_scan_run("pre_market", "cfg1", db_path=path)
        second = db.create_scan_run("post_close", "cfg2", db_path=path)
        runs = db.list_scan_runs(db_path=path)
        assert [r["run_id"] for r in runs] == [second, first]

    def test_get_latest_run_id(self, tmp_path):
        path = tmp_path / "history.db"
        assert db.get_latest_run_id(db_path=path) is None
        db.create_scan_run("post_close", "cfg", db_path=path)
        second = db.create_scan_run("post_close", "cfg", db_path=path)
        assert db.get_latest_run_id(db_path=path) == second


class TestTickerResultsAndLayerScores:
    def test_insert_and_fetch_result(self, tmp_path):
        path = tmp_path / "history.db"
        run_id = db.create_scan_run("post_close", "cfg", db_path=path)
        result_id = db.insert_ticker_result(
            run_id, "NVDA", db.CATEGORY_TRADE_RECOMMENDED,
            composite_score=92.5, trade_structure="bull_call_spread",
            expected_value=0.03, event_gate_blocked=True, event_gate_trigger="tariff",
            db_path=path,
        )
        results = db.get_ticker_results(run_id, db_path=path)
        assert len(results) == 1
        row = results[0]
        assert row["result_id"] == result_id
        assert row["ticker"] == "NVDA"
        assert row["category"] == db.CATEGORY_TRADE_RECOMMENDED
        assert row["event_gate_blocked"] == 1
        assert row["event_gate_trigger"] == "tariff"

    def test_layer_scores_roundtrip(self, tmp_path):
        path = tmp_path / "history.db"
        run_id = db.create_scan_run("post_close", "cfg", db_path=path)
        result_id = db.insert_ticker_result(run_id, "AMD", db.CATEGORY_NO_SIGNAL, db_path=path)
        db.insert_layer_score(result_id, "technical", 28.0, detail={"breakout": 8}, db_path=path)
        db.insert_layer_score(result_id, "regime", -10.0, db_path=path)
        scores = db.get_layer_scores(result_id, db_path=path)
        assert len(scores) == 2
        technical = next(s for s in scores if s["layer_name"] == "technical")
        assert technical["score"] == 28.0
        assert technical["detail_json"] == '{"breakout": 8}'

    def test_results_scoped_to_run(self, tmp_path):
        path = tmp_path / "history.db"
        run_a = db.create_scan_run("post_close", "cfg", db_path=path)
        run_b = db.create_scan_run("post_close", "cfg", db_path=path)
        db.insert_ticker_result(run_a, "NVDA", db.CATEGORY_NO_SIGNAL, db_path=path)
        db.insert_ticker_result(run_b, "AMD", db.CATEGORY_NO_SIGNAL, db_path=path)
        assert [r["ticker"] for r in db.get_ticker_results(run_a, db_path=path)] == ["NVDA"]
        assert [r["ticker"] for r in db.get_ticker_results(run_b, db_path=path)] == ["AMD"]

    def test_sector_roundtrip(self, tmp_path):
        path = tmp_path / "history.db"
        run_id = db.create_scan_run("post_close", "cfg", db_path=path)
        db.insert_ticker_result(run_id, "NVDA", db.CATEGORY_NO_SIGNAL, sector="semiconductors", db_path=path)
        db.insert_ticker_result(run_id, "ZION", db.CATEGORY_NO_SIGNAL, sector="regional_banks", db_path=path)
        results = {r["ticker"]: r["sector"] for r in db.get_ticker_results(run_id, db_path=path)}
        assert results["NVDA"] == "semiconductors"
        assert results["ZION"] == "regional_banks"

    def test_sector_defaults_to_none_when_not_passed(self, tmp_path):
        path = tmp_path / "history.db"
        run_id = db.create_scan_run("post_close", "cfg", db_path=path)
        db.insert_ticker_result(run_id, "NVDA", db.CATEGORY_NO_SIGNAL, db_path=path)
        results = db.get_ticker_results(run_id, db_path=path)
        assert results[0]["sector"] is None

    def test_migration_adds_sector_column_to_pre_existing_db(self, tmp_path):
        """A DB file created before the sector column existed must not break —
        get_connection()'s migration should add it transparently."""
        path = tmp_path / "history.db"
        # Simulate a pre-v2.2.10 DB: create ticker_results without the sector column.
        conn = sqlite3.connect(str(path))
        conn.execute("""
            CREATE TABLE ticker_results (
                result_id INTEGER PRIMARY KEY,
                run_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                category TEXT NOT NULL,
                composite_score REAL,
                trade_structure TEXT,
                expected_value REAL,
                event_gate_blocked INTEGER NOT NULL DEFAULT 0,
                event_gate_trigger TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE scan_runs (
                run_id INTEGER PRIMARY KEY,
                run_timestamp TEXT NOT NULL,
                scan_type TEXT NOT NULL,
                config_snapshot TEXT
            )
        """)
        conn.commit()
        conn.close()

        # A fresh get_connection() call (e.g. via create_scan_run) must migrate
        # the old table in place, not error and not lose existing behavior.
        run_id = db.create_scan_run("post_close", "cfg", db_path=path)
        result_id = db.insert_ticker_result(run_id, "NVDA", db.CATEGORY_NO_SIGNAL, sector="semiconductors", db_path=path)
        assert result_id is not None
        results = db.get_ticker_results(run_id, db_path=path)
        assert results[0]["sector"] == "semiconductors"


class TestNotifications:
    def test_insert_and_fetch(self, tmp_path):
        path = tmp_path / "history.db"
        run_id = db.create_scan_run("post_close", "cfg", db_path=path)
        db.insert_notification(
            "trade", "sent", run_id=run_id, ticker="NVDA",
            payload={"confidence": 92}, db_path=path,
        )
        notes = db.get_notifications(db_path=path)
        assert len(notes) == 1
        assert notes[0]["alert_type"] == "trade"
        assert notes[0]["discord_status"] == "sent"
        assert notes[0]["payload_json"] == '{"confidence": 92}'

    def test_filter_by_ticker_and_type(self, tmp_path):
        path = tmp_path / "history.db"
        run_id = db.create_scan_run("post_close", "cfg", db_path=path)
        db.insert_notification("trade", "sent", run_id=run_id, ticker="NVDA", db_path=path)
        db.insert_notification("near_miss", "sent", run_id=run_id, ticker="AMD", db_path=path)
        db.insert_notification("trade", "failed", run_id=run_id, ticker="AMD", db_path=path)

        assert len(db.get_notifications(ticker="AMD", db_path=path)) == 2
        assert len(db.get_notifications(alert_type="trade", db_path=path)) == 2
        assert len(db.get_notifications(ticker="AMD", alert_type="trade", db_path=path)) == 1

    def test_notification_without_ticker(self, tmp_path):
        """health_check / circuit_breaker alerts aren't per-ticker."""
        path = tmp_path / "history.db"
        run_id = db.create_scan_run("post_close", "cfg", db_path=path)
        db.insert_notification("health_check", "sent", run_id=run_id, db_path=path)
        notes = db.get_notifications(db_path=path)
        assert notes[0]["ticker"] is None

    def test_newest_first(self, tmp_path):
        path = tmp_path / "history.db"
        run_id = db.create_scan_run("post_close", "cfg", db_path=path)
        first = db.insert_notification("trade", "sent", run_id=run_id, db_path=path)
        second = db.insert_notification("near_miss", "sent", run_id=run_id, db_path=path)
        notes = db.get_notifications(db_path=path)
        assert [n["notification_id"] for n in notes] == [second, first]
