"""
SHARED: Logging setup for all modules.
Provides structured logging to console + rotating file handler.
audit_log.csv is the forensic CSV log of every scan decision — written by this module.
"""

import csv
import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


_loggers: dict[str, logging.Logger] = {}

# Module-level defaults for the CSV log writers below. Referenced by name at
# call time (not baked into the function signatures as default arg values,
# which Python evaluates once at import time) specifically so
# tests/conftest.py's autouse fixture can monkeypatch these and redirect every
# write_*_entry call into an isolated tmp_path — without this indirection,
# any test that exercises a real error path (a mocked API failure, a data
# validator edge case, etc.) silently appends synthetic entries to the actual
# production CSV logs under data/logs/.
_AUDIT_LOG_PATH = Path("data/logs/audit_log.csv")
_VALIDATION_LOG_PATH = Path("data/logs/validation_log.csv")
_OVERRIDE_LOG_PATH = Path("data/logs/override_log.csv")


_FMT = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s — %(message)s")

# Referenced by name (not a default arg) so tests/conftest.py can monkeypatch
# it — same reasoning as the CSV log paths above — and redirect app.log
# writes for loggers created before the test session's isolation fixture runs.
_LOG_DIR = Path("data/logs")


class _SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """
    RotatingFileHandler whose rollover can't take logging down with it.

    On Windows a file can't be renamed while any other handle has it open —
    e.g. a second scan process (paper_updater runs inside paper_runner's
    window, and a manual run can overlap a scheduled one). Stock
    RotatingFileHandler then raises PermissionError from inside emit(), so the
    record is dropped, a "--- Logging error ---" traceback goes to stderr, and
    the same thing repeats on EVERY later record, since the file stays over
    maxBytes. Here a failed rename just keeps appending to the current file
    and retries no sooner than _RETRY_SECONDS later.
    """

    _RETRY_SECONDS = 60.0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._next_rollover_attempt = 0.0

    def shouldRollover(self, record) -> bool:
        import time
        if time.monotonic() < self._next_rollover_attempt:
            return False
        return bool(super().shouldRollover(record))

    def doRollover(self) -> None:
        import time
        try:
            super().doRollover()
        except PermissionError:
            self._next_rollover_attempt = time.monotonic() + self._RETRY_SECONDS
            # super() closed the stream before the rename failed — reopen it
            # so this record (and the ones after it) still land in the file.
            if self.stream is None:
                self.stream = self._open()


# One handler per log file per process, shared by every named logger.
# Previously get_logger() built a NEW RotatingFileHandler for each module's
# logger — dozens of open handles on the same app.log in one process — so
# once the file reached maxBytes the rename in doRollover could never
# succeed (the process's own other handles held the file), every record
# after that was dropped with a traceback, and app.log silently stopped
# growing at 5,001,013 bytes on 2026-09-28 05:54 while the task logs filled
# with ~1,300 "--- Logging error ---" blocks.
_FILE_HANDLERS: dict[Path, logging.handlers.RotatingFileHandler] = {}


def _make_file_handler(log_dir: Path) -> logging.handlers.RotatingFileHandler:
    log_path = (log_dir / "app.log").resolve()
    fh = _FILE_HANDLERS.get(log_path)
    if fh is None:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = _SafeRotatingFileHandler(log_path, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(_FMT)
        _FILE_HANDLERS[log_path] = fh
    return fh


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Return (or create) a named logger with console + file handlers."""
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        ch = logging.StreamHandler()
        ch.setFormatter(_FMT)
        logger.addHandler(ch)
        logger.addHandler(_make_file_handler(_LOG_DIR))

    _loggers[name] = logger
    return logger


# ---------------------------------------------------------------------------
# Structured CSV audit log
# ---------------------------------------------------------------------------

_AUDIT_COLUMNS = [
    "timestamp_utc", "model_version", "scan_type", "ticker",
    "technical_score", "positioning_score", "sentiment_score", "news_score", "base_score",
    "regime_modifier", "sector_rotation_modifier", "earnings_modifier",
    "cross_ticker_modifier", "seasonality_modifier",
    "macro_modifier", "final_score",
    "signal_surfaced", "direction", "structure_recommended",
    "ev_per_dollar", "rr_ratio", "entry_lower", "entry_upper",
    "stop_loss", "target", "notes",
    "event_gate_blocked", "event_gate_trigger",
]


def write_audit_entry(entry: dict, audit_log_path: Optional[str] = None) -> None:
    """
    Append one row to audit_log.csv. Creates file with headers if it doesn't exist.
    Called by run_swing_model.py after every ticker is scored.
    """
    path = Path(audit_log_path) if audit_log_path is not None else _AUDIT_LOG_PATH
    write_header = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_AUDIT_COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        entry.setdefault("timestamp_utc", datetime.now(timezone.utc).isoformat())
        writer.writerow(entry)


def write_validation_entry(
    ticker: str, failure_type: str, detail: str,
    log_path: Optional[str] = None
) -> None:
    """Append a data validation failure to validation_log.csv."""
    path = Path(log_path) if log_path is not None else _VALIDATION_LOG_PATH
    write_header = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["timestamp_utc", "ticker", "failure_type", "detail"],
            extrasaction="ignore",
        )
        if write_header:
            writer.writeheader()
        writer.writerow({
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "ticker": ticker,
            "failure_type": failure_type,
            "detail": detail,
        })


def write_override_entry(
    ticker: str, system_recommendation: str, action_taken: str, reason: str,
    log_path: Optional[str] = None
) -> None:
    """Append a manual override to override_log.csv."""
    path = Path(log_path) if log_path is not None else _OVERRIDE_LOG_PATH
    write_header = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["timestamp_utc", "ticker", "system_recommendation", "action_taken", "reason"],
            extrasaction="ignore",
        )
        if write_header:
            writer.writeheader()
        writer.writerow({
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "ticker": ticker,
            "system_recommendation": system_recommendation,
            "action_taken": action_taken,
            "reason": reason,
        })
