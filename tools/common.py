"""Shared paths and helpers for the agent team. Scripts only - no Claude calls here."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

TEAM = Path(__file__).resolve().parents[1]
LIVE_V2 = Path(r"C:\Users\user\Documents\Git\StockAnalysis")
LIVE_V3 = Path(r"C:\Users\user\Documents\Git\StockAnalysis-V3")
LIVE_V4 = Path(r"C:\Users\user\Documents\Git\StockAnalysis-V4")
SNAPSHOT = LIVE_V2 / "agent" / "tools" / "snapshot.py"   # authoritative V2/V3/V4 numbers (read-only)
PYTHON = r"C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe"

STATE = TEAM / "state"        # untracked: run state, caches, logs
LOGS = STATE / "logs"
OUTBOX = TEAM / "outbox"      # each role writes <role>.txt; the dispatcher posts it
STOP_FILE = TEAM / "STOP"     # kill switch: present = no Claude roles, no new paper signals
# Headless Claude's answer when its login is gone (dispatch.run_role, quotes.capture). Not a bare "401": that once
# matched normal output and raised a false alarm.
LOGGED_OUT_RX = r"Not logged in|Please run /login|authentication_error|OAuth token"
LOGIN_HELP = "Claude is LOGGED OUT - open a terminal on the PC, run `claude`, then `/login`."

# Channel -> .env key, then fallbacks. Never the general scan channel (DISCORD_WEBHOOK_URL).
CHANNELS = {
    "ops": ["DISCORD_OPS_WEBHOOK_URL", "DISCORD_AGENT_WEBHOOK_URL"],
    "research": ["DISCORD_RESEARCH_WEBHOOK_URL", "DISCORD_AGENT_WEBHOOK_URL"],
    "director": ["DISCORD_DIRECTOR_WEBHOOK_URL", "DISCORD_AGENT_WEBHOOK_URL"],
}

for d in (STATE, LOGS, OUTBOX):
    d.mkdir(parents=True, exist_ok=True)

# Task Scheduler consoles are cp1252; an emoji in a print would crash the run.
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")


def now_pt() -> datetime:
    return datetime.now()  # the machine runs on Pacific time


def log(msg: str, name: str = "team") -> None:
    line = f"{now_pt():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    with open(LOGS / f"{now_pt():%Y-%m-%d}-{name}.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_env() -> dict[str, str]:
    """Webhooks live in the V2 .env (read-only). The team has no secrets of its own."""
    out: dict[str, str] = {}
    env = LIVE_V2 / ".env"
    if env.exists():
        for raw in env.read_text(encoding="utf-8", errors="replace").splitlines():
            if "=" in raw and not raw.lstrip().startswith("#"):
                k, v = raw.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def post(channel: str, text: str, username: str, dry_run: bool = False) -> bool:
    if dry_run or os.environ.get("TEAM_DRY_RUN"):
        print(f"--- [dry-run] {channel} as {username} ---\n{text}\n---")
        return True
    env = read_env()
    url = next((env[k] for k in CHANNELS[channel] if env.get(k)), None)
    if not url:
        log(f"no webhook configured for channel {channel}")
        return False
    if len(text) > 1950:
        text = text[:1950] + "..."
    body = json.dumps({"username": username, "content": text}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                          "User-Agent": "StockAnalysis-Team"})
    try:
        urllib.request.urlopen(req, timeout=20).read()
        return True
    except Exception as e:  # noqa: BLE001 - a failed post must never stop the run
        log(f"discord post to {channel} failed: {e}")
        return False


def stopped() -> bool:
    return STOP_FILE.exists()


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, data) -> None:
    """Atomic write. The temp name is per-process (two writers never share one), and the final rename is retried:
    on Windows it fails with PermissionError while another process has the target open for reading."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    for attempt in range(10):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == 9:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.2)


class LockBusy(Exception):
    """Another live process holds the lock (see state_lock)."""


@contextmanager
def state_lock(name: str, wait_s: float = 60, stale_s: float = 900):
    """Exclusive lock on STATE/<name>.lock around a read-modify-write of shared state.
    Waits up to wait_s for the holder to finish; a lock older than stale_s is from a crashed run and is taken over.
    Raises LockBusy when it can't get the lock - the caller skips this run rather than overwrite another's update."""
    lock = STATE / f"{name}.lock"
    deadline = time.monotonic() + wait_s
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{os.getpid()} {now_pt().isoformat(timespec='seconds')}".encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > stale_s:
                    lock.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                holder = lock.read_text(errors="replace") if lock.exists() else "?"
                raise LockBusy(f"{lock.name} held by {holder}")
            time.sleep(1)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def git(*args: str) -> str:
    r = subprocess.run(["git", *args], cwd=TEAM, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (r.stdout + r.stderr).strip()


def commit(message: str) -> None:
    """Only the dispatcher commits (agents have no git access), so every commit time is trustworthy."""
    git("add", "-A")
    if git("status", "--porcelain"):
        git("commit", "-q", "-m", message)
