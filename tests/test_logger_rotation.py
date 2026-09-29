"""
Tests for app.log rotation (shared/utils/logger.py).

Live 2026-09-28: every named logger had its own RotatingFileHandler on the
same app.log, so once the file hit maxBytes the rollover rename always failed
(the process's own other handles held the file open on Windows). Every record
after that was dropped with a "--- Logging error ---" traceback, and app.log
stopped growing entirely.
"""

import logging

import shared.utils.logger as logger_module


def test_loggers_share_one_file_handler_per_log_dir(tmp_path):
    a = logger_module._make_file_handler(tmp_path)
    b = logger_module._make_file_handler(tmp_path)
    assert a is b


def test_rollover_rotates_when_the_file_is_free(tmp_path):
    fh = logger_module._SafeRotatingFileHandler(tmp_path / "app.log", maxBytes=200, backupCount=2, encoding="utf-8")
    fh.setFormatter(logger_module._FMT)
    log = logging.getLogger("test_rotation_free")
    log.addHandler(fh)
    try:
        for i in range(20):
            log.warning("x" * 40 + str(i))
    finally:
        log.removeHandler(fh)
        fh.close()
    assert (tmp_path / "app.log.1").exists()


def test_failed_rename_keeps_logging_instead_of_dropping_records(tmp_path, monkeypatch, capsys):
    fh = logger_module._SafeRotatingFileHandler(tmp_path / "app.log", maxBytes=200, backupCount=2, encoding="utf-8")
    fh.setFormatter(logger_module._FMT)

    def _locked(source, dest):
        raise PermissionError(32, "The process cannot access the file because it is being used by another process")

    monkeypatch.setattr(fh, "rotate", _locked)
    log = logging.getLogger("test_rotation_locked")
    log.addHandler(fh)
    try:
        for i in range(20):
            log.warning(f"record-{i:02d} " + "x" * 40)
    finally:
        log.removeHandler(fh)
        fh.close()

    text = (tmp_path / "app.log").read_text(encoding="utf-8")
    assert all(f"record-{i:02d}" in text for i in range(20))
    assert "Logging error" not in capsys.readouterr().err
