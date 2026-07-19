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

import json
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
