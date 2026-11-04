"""Claude plan limit: when a role hits it, the roles still waiting run as soon as it resets (not tomorrow).

The dispatcher stops launching roles on the first "You've hit your session limit · resets 5:50pm" answer,
saves what is left to state/resume.json and starts a detached waiter (`dispatch.py --resume --wait`) that
sleeps until the reset and runs them. Backup: the Scan Operator tick (every 10 min, 05:00-18:50) starts the
resume itself if the waiter died - and the next normal dispatch supersedes a resume that never happened.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from datetime import datetime, timedelta

from common import LOGS, PYTHON, STATE, TEAM, load_json, now_pt, save_json

RESUME = STATE / "resume.json"
LOCK = STATE / "resume.lock"
LIMIT_RX = re.compile(r"hit your (?:\w+[ -])?limit|usage limit reached|rate_limit_error", re.I)
RESET_RX = re.compile(r"resets\s+(?:(?P<pre>[A-Za-z]{3,9}\.?\s*\d{0,2},?)\s+)?(?:at\s+)?"
                      r"(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ap>[ap]m)", re.I)
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
GRACE = timedelta(minutes=2)        # the waiter starts this long after the reset
BACKUP_GRACE = timedelta(minutes=8)  # the Scan Operator only steps in if the waiter hasn't
MAX_ATTEMPTS = 4                    # resumes that hit the limit again before we give up for the day
FALLBACK = timedelta(minutes=60)    # reset time unreadable -> try again in an hour
LOCK_STALE = timedelta(hours=5)     # longer than every role's timeout added up


def is_limited(raw: str, res: dict) -> bool:
    return res.get("api_error_status") == 429 or bool(LIMIT_RX.search(raw))


def reset_time(raw: str, now: datetime) -> datetime:
    """'resets 5:50pm', 'resets Fri 9am', 'resets Nov 7, 9:00am' -> when (local = PT). Unreadable -> now + 1 h."""
    m = RESET_RX.search(raw)
    if not m:
        return now + FALLBACK
    hour = int(m["h"]) % 12 + (12 if m["ap"].lower() == "pm" else 0)
    at = now.replace(hour=hour, minute=int(m["m"] or 0), second=0, microsecond=0)
    pre = (m["pre"] or "").lower().strip(" ,.")
    word = pre[:3]
    if word in MONTHS and re.search(r"\d", pre):
        at = at.replace(month=MONTHS.index(word) + 1, day=int(re.search(r"\d+", pre)[0]))
        if at < now - timedelta(days=180):
            at = at.replace(year=at.year + 1)
    elif word in WEEKDAYS:
        at += timedelta(days=(WEEKDAYS.index(word) - at.weekday()) % 7)
        if at < now:
            at += timedelta(days=7)
    elif at < now - timedelta(minutes=5):
        at += timedelta(days=1)    # a bare clock time already past = tomorrow
    return at


def save(today: str, resets_at: datetime, roles: dict[str, str], attempts: int) -> None:
    save_json(RESUME, {"date": today, "resets_at": resets_at.isoformat(timespec="minutes"),
                       "roles": roles, "attempts": attempts})


def pending() -> dict | None:
    r = load_json(RESUME, None)
    return r if r and r.get("roles") else None


def clear() -> None:
    RESUME.unlink(missing_ok=True)


def due(grace: timedelta = GRACE) -> bool:
    r = pending()
    return bool(r) and now_pt() >= datetime.fromisoformat(r["resets_at"]) + grace


def wait_until_due() -> bool:
    """Sleep in short steps (wall clock, so a sleeping laptop wakes up late, not never). False = cancelled."""
    while True:
        r = pending()
        if not r:
            return False
        left = (datetime.fromisoformat(r["resets_at"]) + GRACE - now_pt()).total_seconds()
        if left <= 0:
            return True
        time.sleep(min(60.0, left))


def take_lock() -> bool:
    """Atomic, so the waiter and the Scan Operator backup can never both run the held roles."""
    if LOCK.exists() and not running():
        LOCK.unlink(missing_ok=True)     # left by a crashed resume
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    os.write(fd, f"{now_pt():%Y-%m-%d %H:%M:%S} pid {os.getpid()}".encode())
    os.close(fd)
    return True


def drop_lock() -> None:
    LOCK.unlink(missing_ok=True)


def running() -> bool:
    return LOCK.exists() and now_pt() - datetime.fromtimestamp(LOCK.stat().st_mtime) < LOCK_STALE


def spawn(wait: bool) -> None:
    """Start `dispatch.py --resume [--wait]` detached, so it outlives the task that started it."""
    args = [PYTHON, str(TEAM / "tools" / "dispatch.py"), "--resume"] + (["--wait"] if wait else [])
    out = open(LOGS / "resume_task.log", "a", encoding="utf-8")
    base = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    for flags in (base | subprocess.CREATE_BREAKAWAY_FROM_JOB, base):  # breakaway is refused in some jobs
        try:
            subprocess.Popen(args, cwd=TEAM, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                             creationflags=flags, close_fds=True)
            return
        except OSError:
            continue
    raise RuntimeError("could not start the resume process")
