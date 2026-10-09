"""Polite, resumable downloader for Dukascopy's free historical 1-minute data (no account).

Dukascopy publishes BID 1-minute candles per instrument per UTC day as LZMA-compressed binary
(.bi5): 24-byte records of (seconds-from-midnight, open, close, low, high, volume[float]). US stock
and ETF CFDs are named "<SYMBOL>USUSD" with prices x1000. Only regular US hours are kept.
Volume is Dukascopy's own CFD volume, NOT exchange volume.

    python -m daytrade.dukascopy SPY QQQ ...      # download 2018-01-01 .. yesterday, resumable
"""

from __future__ import annotations

import logging
import lzma
import struct
import sys
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests

from .config import DATA_DIR, TZ

OUT = DATA_DIR / "duka_1m"
URL = "https://datafeed.dukascopy.com/datafeed/{inst}/{y}/{m:02d}/{d:02d}/BID_candles_min_1.bi5"
START = date(2018, 1, 1)
PAUSE = 1.0
log = logging.getLogger("duka")


def _fetch(inst: str, day: date, session: requests.Session):
    url = URL.format(inst=inst, y=day.year, m=day.month - 1, d=day.day)
    for k in range(6):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 200:
                return r.content
            if r.status_code == 404:
                return b""
        except requests.RequestException:
            pass
        time.sleep(min(60, 3 * 2 ** k))
    return None


def _parse(blob: bytes, day: date) -> pd.DataFrame:
    if not blob:
        return pd.DataFrame()
    raw = lzma.decompress(blob)
    rows = [struct.unpack(">5if", raw[i * 24:(i + 1) * 24]) for i in range(len(raw) // 24)]
    df = pd.DataFrame(rows, columns=["sec", "open", "close", "low", "high", "volume"])
    df[["open", "close", "low", "high"]] = df[["open", "close", "low", "high"]] / 1000.0
    ts = pd.Timestamp(day, tz="UTC") + pd.to_timedelta(df["sec"], unit="s")
    df.index = ts.dt.tz_convert(TZ)
    df.index.name = "ts"
    t = df.index.time
    from datetime import time as dtime
    df = df[(t >= dtime(9, 30)) & (t <= dtime(15, 59)) & (df.index.date == day)]
    return df[["open", "high", "low", "close", "volume"]]


def _month_path(sym: str, y: int, m: int):
    return OUT / sym / f"{y}-{m:02d}.parquet"


def download(sym: str, start: date = START, end: date | None = None) -> None:
    end = end or (date.today() - timedelta(days=1))
    inst = f"{sym}USUSD"
    s = requests.Session()
    s.headers["User-Agent"] = "Mozilla/5.0 (research; personal use)"
    month = date(start.year, start.month, 1)
    while month <= end:
        nxt = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
        path = _month_path(sym, month.year, month.month)
        last_day = min(end, nxt - timedelta(days=1))
        complete = path.exists() and (last_day < date.today() - timedelta(days=3))
        if complete and path.with_suffix(".done").exists():
            month = nxt
            continue
        frames, missing = [], 0
        d = max(month, start)
        while d <= last_day:
            if d.weekday() < 5:
                blob = _fetch(inst, d, s)
                if blob is None:
                    missing += 1
                else:
                    frames.append(_parse(blob, d))
                time.sleep(PAUSE)
            d += timedelta(days=1)
        path.parent.mkdir(parents=True, exist_ok=True)
        df = pd.concat([f for f in frames if len(f)]) if any(len(f) for f in frames) else pd.DataFrame()
        df.to_parquet(path)
        if missing == 0 and last_day < date.today() - timedelta(days=3):
            path.with_suffix(".done").touch()
        log.info("%s %s-%02d: %d bars, %d days failed", sym, month.year, month.month, len(df), missing)
        month = nxt


def load(sym: str) -> pd.DataFrame:
    parts = sorted((OUT / sym).glob("*.parquet"))
    frames = [pd.read_parquet(p) for p in parts]
    frames = [f for f in frames if len(f)]
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames).sort_index()
    df.index = pd.DatetimeIndex(df.index).tz_convert(TZ)
    df = df[~df.index.duplicated()]
    # Dukascopy also serves flat candles on US market holidays: keep only sessions that traded
    moving = (df["high"] != df["low"]).groupby(df.index.date).sum()
    live = set(moving[moving >= 100].index)
    return df[[d in live for d in df.index.date]]


def _pid_alive(pid: int) -> bool:
    """Read-only liveness check. NOTE: os.kill(pid, 0) is NOT safe here - on Windows it terminates
    the process. Use OpenProcess + GetExitCodeProcess instead."""
    import ctypes
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
    k32.CloseHandle(h)
    return bool(ok) and code.value == 259            # STILL_ACTIVE


def _other_instance_running() -> bool:
    """True if another downloader (per the PID lock file) is still alive; otherwise take the lock."""
    import os
    lock = DATA_DIR / "duka.lock"
    if lock.exists():
        try:
            pid = int(lock.read_text().strip())
            if pid != os.getpid() and _pid_alive(pid):
                return True
        except ValueError:
            pass
    lock.write_text(str(os.getpid()))
    return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s",
                        handlers=[logging.FileHandler(DATA_DIR / "duka_download.log"), logging.StreamHandler()])
    if _other_instance_running():
        log.info("another downloader is running; exiting")
        sys.exit(0)
    log.info("start %s", datetime.now())
    for sym in sys.argv[1:]:
        download(sym)
    log.info("ALL DONE %s", datetime.now())
