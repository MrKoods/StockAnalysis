"""
File-based mutex preventing two instances of the same scan_type from running
concurrently. Built after tracing an actual incident: 2026-08-04's post-close
scan restarted from scratch every ~5 minutes (app.log shows a fresh
"[post_close] Fetching OHLCV for: ['NVDA', ...]" at 13:48:34 and again at
13:53:30, each one re-fetching every sector from the beginning) — almost
certainly an external scheduler (Windows Task Scheduler or similar; nothing
in this repo triggers that cadence) relaunching the job without checking
whether a previous instance was still alive. Because retail tickers
(AMZN/TSLA/HD/NKE/SBUX/TGT) are processed last in ticker order and the
RapidAPI 429 retry storm (see sentiment_client.py) made each earlier ticker
take minutes, every relaunched instance got killed/superseded before it ever
reached them — which is why retail dropped out of that day's post-close
results twice in a row. This doesn't fix the external scheduler (outside this
repo's control) but stops the actual damage: a new invocation now detects a
live prior instance and exits immediately instead of duplicating work and
contending for the same rate-limited APIs.

Usage:
    with acquire_scan_lock("post_close") as acquired:
        if not acquired:
            return 0  # another instance is already running this scan_type
        ... run the scan ...
"""

import contextlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_LOCK_DIR = Path("data/processed/scan_locks")

# Generously longer than any real scan should take, even at today's RapidAPI
# retry-storm pace (~80-100 min worst case) — this only fires on a lock left
# behind by a process that's actually gone (crashed, killed), not a slow-but-
# genuinely-still-running one.
_MAX_LOCK_AGE_SECONDS = 3 * 60 * 60


def _lock_path(scan_type: str, lock_dir: Optional[Path] = None) -> Path:
    return (lock_dir or _LOCK_DIR) / f"{scan_type}.lock"


def _pid_is_alive(pid: int) -> bool:
    """
    os.kill(pid, 0) is a liveness check on both POSIX and Windows — it raises
    OSError (ESRCH on POSIX, WinError 87 on Windows) for a PID that doesn't
    exist, and returns silently for one that does, without actually sending
    a signal.
    """
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:
        # Unsure (e.g. permission denied checking another user's process) —
        # assume alive. Skipping a scan is far cheaper than double-running
        # one and contending for the same rate-limited APIs.
        return True


def _try_claim(path: Path) -> bool:
    """
    Attempt to atomically claim the lock file.

    Content is written to a uniquely-named temp file first, then published
    under the real name via os.link(), which — like O_CREAT|O_EXCL — fails
    atomically if the destination already exists. This matters because the
    previous approach (os.open(O_CREAT|O_EXCL) followed by a separate
    os.write()) left a window where the file existed but was still empty;
    a concurrent reader landing in that window would see unparseable content,
    treat the lock as corrupt-therefore-stale, and steal it out from under
    the actual holder — confirmed via a real concurrent-thread test where up
    to 9 threads ended up inside the critical section at once. Publishing
    the file only once its content is fully on disk closes that window.
    """
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        try:
            os.write(fd, json.dumps({
                "pid": os.getpid(), "started_at_utc": datetime.now(timezone.utc).isoformat(),
            }).encode("utf-8"))
        finally:
            os.close(fd)
        try:
            os.link(tmp_name, str(path))
        except (FileExistsError, PermissionError):
            # PermissionError alongside FileExistsError: on Windows, two
            # threads/processes racing to link the same destination can have
            # the loser surface WinError 5 (Access Denied) instead of the
            # expected "file exists" errno depending on exact timing — both
            # mean the same thing here: someone else has (or just got) the
            # lock.
            return False
        return True
    finally:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass


@contextlib.contextmanager
def acquire_scan_lock(scan_type: str, lock_dir: Optional[Path] = None):
    """
    Context manager yielding True if this call acquired the lock (proceed
    with the scan) or False if another live instance already holds it (the
    caller should skip this run). The lock file is removed on exit only when
    this call was the one that acquired it — never touches a lock some other
    process is actively holding.
    """
    path = _lock_path(scan_type, lock_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    acquired = _try_claim(path)

    if not acquired:
        # Someone already holds it (or held it a moment ago) — check whether
        # it's actually stale before giving up. The reclaim attempt itself
        # goes through the same atomic _try_claim, so two processes racing
        # to reclaim the same stale lock can't both "win" it.
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            existing_pid = int(existing.get("pid", -1))
            started_at = datetime.fromisoformat(existing["started_at_utc"])
            age_seconds = (datetime.now(timezone.utc) - started_at).total_seconds()
        except Exception:
            # Unparseable/corrupt lock file — treat as stale rather than
            # blocking every future scan on a file we can't even read.
            existing_pid, age_seconds = -1, _MAX_LOCK_AGE_SECONDS + 1

        stale = age_seconds > _MAX_LOCK_AGE_SECONDS or not _pid_is_alive(existing_pid)
        if stale:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
            acquired = _try_claim(path)

    if not acquired:
        yield False
        return

    try:
        yield True
    finally:
        if acquired:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
