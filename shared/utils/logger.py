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


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Return (or create) a named logger with console + file handlers."""
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(level)

    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s — %(message)s")

        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        logger.addHandler(ch)

        log_dir = Path("data/logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_dir / "app.log", maxBytes=5_000_000, backupCount=3
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    _loggers[name] = logger
    return logger


# ---------------------------------------------------------------------------
# Structured CSV audit log
# ---------------------------------------------------------------------------

_AUDIT_COLUMNS = [
    "timestamp_utc", "model_version", "scan_type", "ticker",
    "technical_score", "sentiment_score", "news_score", "base_score",
    "regime_modifier", "sector_rotation_modifier", "earnings_modifier",
    "cross_ticker_modifier", "insider_modifier", "seasonality_modifier",
    "macro_modifier", "final_score",
    "signal_surfaced", "direction", "structure_recommended",
    "ev_per_dollar", "rr_ratio", "entry_lower", "entry_upper",
    "stop_loss", "target", "notes",
]


def write_audit_entry(entry: dict, audit_log_path: str = "data/logs/audit_log.csv") -> None:
    """
    Append one row to audit_log.csv. Creates file with headers if it doesn't exist.
    Called by run_swing_model.py after every ticker is scored.
    """
    path = Path(audit_log_path)
    write_header = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_AUDIT_COLUMNS, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        entry.setdefault("timestamp_utc", datetime.now(timezone.utc).isoformat())
        writer.writerow(entry)


def write_validation_entry(
    ticker: str, failure_type: str, detail: str,
    log_path: str = "data/logs/validation_log.csv"
) -> None:
    """Append a data validation failure to validation_log.csv."""
    path = Path(log_path)
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
    log_path: str = "data/logs/override_log.csv"
) -> None:
    """Append a manual override to override_log.csv."""
    path = Path(log_path)
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
