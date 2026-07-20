"""
SQLite persistence for the desktop app UI (see App_UI_Scope.md). Stores scan
results, layer breakdowns, and notification history so the UI has something to
show on launch without needing a scan to have just run.

Each function opens its own short-lived connection rather than sharing one
across calls — writes happen from a background QThread (scan_worker.py) while
reads happen from the Qt main thread, and sqlite3 connections aren't safe to
share across threads. At this app's scale (a handful of tickers, a few scans a
day) the per-call connection overhead is irrelevant.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

DEFAULT_DB_PATH = Path("stockanalysis_history.db")

# Categories a ticker_results row can fall into — see App_UI_Scope.md §3.1
CATEGORY_TRADE_RECOMMENDED = "trade_recommended"
CATEGORY_PASSED_NO_TRADE = "passed_no_trade"
CATEGORY_NEAR_MISS = "near_miss"
CATEGORY_NO_SIGNAL = "no_signal"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_runs (
    run_id INTEGER PRIMARY KEY,
    run_timestamp TEXT NOT NULL,
    scan_type TEXT NOT NULL,
    config_snapshot TEXT
);

CREATE TABLE IF NOT EXISTS ticker_results (
    result_id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES scan_runs(run_id),
    ticker TEXT NOT NULL,
    category TEXT NOT NULL,
    composite_score REAL,
    trade_structure TEXT,
    expected_value REAL,
    event_gate_blocked INTEGER NOT NULL DEFAULT 0,
    event_gate_trigger TEXT,
    sector TEXT
);
CREATE INDEX IF NOT EXISTS idx_ticker_results_run_id ON ticker_results(run_id);

CREATE TABLE IF NOT EXISTS layer_scores (
    layer_score_id INTEGER PRIMARY KEY,
    result_id INTEGER NOT NULL REFERENCES ticker_results(result_id),
    layer_name TEXT NOT NULL,
    score REAL,
    detail_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_layer_scores_result_id ON layer_scores(result_id);

CREATE TABLE IF NOT EXISTS notifications (
    notification_id INTEGER PRIMARY KEY,
    run_id INTEGER REFERENCES scan_runs(run_id),
    ticker TEXT,
    alert_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    payload_json TEXT,
    discord_status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notifications_run_id ON notifications(run_id);
"""


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open a connection with row access by column name and the schema ensured to exist."""
    path = db_path or DEFAULT_DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """
    Schema changes to existing DB files that CREATE TABLE IF NOT EXISTS can't
    apply on its own (that's a no-op once the table already exists). Each
    migration checks column presence first — sqlite3 has no
    "ADD COLUMN IF NOT EXISTS" — so this is safe to run on every connection.
    """
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(ticker_results)")}
    if "sector" not in cols:
        # Added v2.2.10 for multi-sector result grouping (App_UI_Scope.md §3.1) —
        # existing rows from before this migration get sector=NULL, shown under
        # an "Unknown Sector" bucket in results_tab.py rather than dropped.
        conn.execute("ALTER TABLE ticker_results ADD COLUMN sector TEXT")
        conn.commit()


def create_scan_run(
    scan_type: str,
    config_snapshot: str,
    db_path: Optional[Path] = None,
) -> int:
    """Insert a new scan_runs row. Returns the new run_id."""
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO scan_runs (run_timestamp, scan_type, config_snapshot) VALUES (?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), scan_type, config_snapshot),
        )
        return int(cur.lastrowid)


def insert_ticker_result(
    run_id: int,
    ticker: str,
    category: str,
    composite_score: Optional[float] = None,
    trade_structure: Optional[str] = None,
    expected_value: Optional[float] = None,
    event_gate_blocked: bool = False,
    event_gate_trigger: Optional[str] = None,
    sector: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Insert a ticker_results row for one ticker in one scan run. Returns the new result_id.

    sector: which watchlist.sectors entry `ticker` belongs to (e.g.
    "semiconductors", "regional_banks") — None for callers that haven't
    threaded sector through yet, shown under "Unknown Sector" in results_tab.py.
    """
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO ticker_results
                (run_id, ticker, category, composite_score, trade_structure,
                 expected_value, event_gate_blocked, event_gate_trigger, sector)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, ticker, category, composite_score, trade_structure,
                expected_value, int(bool(event_gate_blocked)), event_gate_trigger, sector,
            ),
        )
        return int(cur.lastrowid)


def insert_layer_score(
    result_id: int,
    layer_name: str,
    score: Optional[float],
    detail: Optional[dict] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Insert one layer/modifier score row for a ticker result. Returns the new layer_score_id."""
    detail_json = json.dumps(detail) if detail is not None else None
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO layer_scores (result_id, layer_name, score, detail_json) VALUES (?, ?, ?, ?)",
            (result_id, layer_name, score, detail_json),
        )
        return int(cur.lastrowid)


def insert_notification(
    alert_type: str,
    discord_status: str,
    run_id: Optional[int] = None,
    ticker: Optional[str] = None,
    payload: Optional[dict] = None,
    timestamp: Optional[str] = None,
    db_path: Optional[Path] = None,
) -> int:
    """Insert a notifications row. Returns the new notification_id."""
    payload_json = json.dumps(payload) if payload is not None else None
    ts = timestamp or datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO notifications (run_id, ticker, alert_type, timestamp, payload_json, discord_status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, ticker, alert_type, ts, payload_json, discord_status),
        )
        return int(cur.lastrowid)


def list_scan_runs(limit: int = 100, db_path: Optional[Path] = None) -> list[dict]:
    """Most recent scan runs first, for the Results screen's run-date selector."""
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT run_id, run_timestamp, scan_type FROM scan_runs ORDER BY run_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_latest_run_id(db_path: Optional[Path] = None) -> Optional[int]:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT run_id FROM scan_runs ORDER BY run_id DESC LIMIT 1").fetchone()
        return int(row["run_id"]) if row else None


def get_scan_run(run_id: int, db_path: Optional[Path] = None) -> Optional[dict]:
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM scan_runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None


def get_ticker_results(run_id: int, db_path: Optional[Path] = None) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM ticker_results WHERE run_id = ? ORDER BY ticker", (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_layer_scores(result_id: int, db_path: Optional[Path] = None) -> list[dict]:
    with get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM layer_scores WHERE result_id = ?", (result_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_notifications(
    run_id: Optional[int] = None,
    ticker: Optional[str] = None,
    alert_type: Optional[str] = None,
    limit: int = 500,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Notification feed, newest first, optionally filtered by run/ticker/type."""
    clauses = []
    params: list = []
    if run_id is not None:
        clauses.append("run_id = ?")
        params.append(run_id)
    if ticker is not None:
        clauses.append("ticker = ?")
        params.append(ticker)
    if alert_type is not None:
        clauses.append("alert_type = ?")
        params.append(alert_type)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM notifications {where} ORDER BY notification_id DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
