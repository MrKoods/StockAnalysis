"""
SHARED: Atomic file writes for JSON/text/CSV state files.

A plain write_text()/open(path, "w") read-modify-write can leave a truncated or
half-written file behind if the process is interrupted mid-write (crash, disk full,
Ctrl+C, or two scans running concurrently) — corrupting or losing whatever state
that file held (open positions, trade history, calibration weights, call counters).
Writing to a temp file in the same directory and rename()-ing it into place is
atomic on both POSIX and Windows: readers either see the old complete file or the
new complete file, never a partial one.
"""

import contextlib
import json
import os
import time
from pathlib import Path
from typing import Any, Optional


def atomic_write_text(path: Path, text: str, newline: Optional[str] = None) -> None:
    """
    Write text to `path` atomically via a same-directory temp file + rename.
    `newline` is forwarded to Path.write_text — pass newline="" when `text`
    already contains explicit line terminators (e.g. a csv.writer's \\r\\n) so
    Python's universal-newline translation on write doesn't double them up.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline=newline)
    tmp.replace(path)


def atomic_write_json(path: Path, data: Any, indent: int = 2) -> None:
    """Write `data` as JSON to `path` atomically via a same-directory temp file + rename."""
    atomic_write_text(Path(path), json.dumps(data, indent=indent, default=str))


@contextlib.contextmanager
def exclusive_lock(path: Path, timeout: float = 10.0, poll_interval: float = 0.05):
    """
    Blocking cross-process mutex via atomic exclusive file creation
    (O_CREAT|O_EXCL — the create itself fails if the file already exists,
    atomically, on both POSIX and Windows).

    atomic_write_json/atomic_write_text only make a single WRITE atomic —
    they guarantee no reader ever sees a half-written file, but do nothing to
    serialize a read-modify-write sequence built on top of them (e.g. "load
    a counter, increment it, save it back"). Two processes can both read the
    same starting value and both write back the same incremented result,
    silently losing one of the increments. This closes that gap for call
    sites doing exactly that read-modify-write pattern on a shared file.

    Distinct from scan_lock.py's acquire_scan_lock, which SKIPS (yields
    False) if another instance already holds the lock — appropriate for a
    whole scan that shouldn't double-run. This BLOCKS with a short
    retry/backoff until the lock is free or `timeout` elapses, since a fast
    read-modify-write critical section should eventually succeed, not be
    skipped.

    A lock file older than `timeout` is treated as abandoned (the holder
    crashed without cleaning up) and reclaimed rather than waited on forever.
    Raises TimeoutError if the lock still can't be acquired after that.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    acquired = False

    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            acquired = True
            break
        # PermissionError alongside FileExistsError: on Windows, two threads/
        # processes racing O_CREAT|O_EXCL on the same path can have the loser
        # surface WinError 5 (Access Denied) instead of the expected
        # "file exists" errno, depending on exact timing — confirmed via a
        # real concurrent-thread test, not a hypothetical. Both mean the same
        # thing here: someone else has (or just got) the lock.
        except (FileExistsError, PermissionError):
            if time.monotonic() >= deadline:
                try:
                    if time.time() - path.stat().st_mtime > timeout:
                        path.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                raise TimeoutError(f"Could not acquire lock {path} within {timeout}s")
            time.sleep(poll_interval)

    try:
        yield
    finally:
        if acquired:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
