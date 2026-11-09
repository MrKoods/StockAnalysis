"""The team's daily-bar archive (data/daily) - script only, zero Claude tokens.

    python tools/daily_bars.py [--force]

research_data.daily() reads this. It started as a copy of V3's data/intraday/daily_max, which was a one-off
yfinance pull (2026-10-06) that nothing refreshed. The team keeps its own copy instead of writing into V3's folder
(hard limit 2). The dispatcher runs this every Saturday, after the week's last close.

Full re-download from 1999, split- and dividend-adjusted (yfinance auto_adjust). Not appended: an adjustment
re-scales the whole history, so a pasted-on week would mix bases. A ticker's file is replaced only when the new
pull ends later and is at least as long as before (minus 5 rows of slack). So a throttled or partial download
never overwrites good history, and a delisted name keeps its old bars.
"""
from __future__ import annotations

import logging
import shutil
import sys
from datetime import date, timedelta

import pandas as pd

from common import TEAM, load_json, log, save_json

V3_DAILY = TEAM.parent / "StockAnalysis-V3" / "data" / "intraday" / "daily_max"
OUT = TEAM / "data" / "daily"
STATEF = TEAM / "state" / "daily_bars.json"
START = "1999-01-01"
BATCH = 100
MIN_ROWS = 250
STALE_DAYS = 6       # skip a run if the last full refresh is newer than this (one refresh a week)...
MAX_BAR_AGE = 3      # ...unless its newest bar is older than this (a midweek manual run must not skip Saturday's)


def seed() -> int:
    """First run: copy V3's archive (the ticker list and the files' format come from it)."""
    OUT.mkdir(parents=True, exist_ok=True)
    n = 0
    for p in V3_DAILY.glob("*"):
        if p.suffix in (".parquet", ".csv") and not (OUT / p.name).exists():
            shutil.copy2(p, OUT / p.name)
            n += 1
    return n


def tickers() -> list[str]:
    return sorted(p.stem for p in OUT.glob("*.parquet"))


def fetch(batch: list[str]) -> dict[str, pd.DataFrame]:
    import yfinance as yf
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    raw = yf.download(batch, start=START, interval="1d", group_by="ticker", auto_adjust=True,
                      progress=False, threads=True)
    out = {}
    for t in batch:
        if t not in raw.columns.get_level_values(0):
            continue
        df = raw[t].rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])
        if len(df) > MIN_ROWS:
            df.index = pd.DatetimeIndex(df.index).tz_localize(None)
            df.index.name = "Date"
            out[t] = df
    return out


def better(new: pd.DataFrame, path) -> bool:
    if not path.exists():
        return True
    old = pd.read_parquet(path)
    return new.index.max() > pd.Timestamp(old.index.max()) and len(new) >= len(old) - 5


def fresh(st: dict, today: date) -> bool:
    return (st.get("date", "") > str(today - timedelta(days=STALE_DAYS))
            and st.get("through", "") >= str(today - timedelta(days=MAX_BAR_AGE)))


def run(force: bool = False) -> str:
    st = load_json(STATEF, {})
    seeded = seed()
    if not force and fresh(st, date.today()):
        return f"daily bars: up to date (refreshed {st['date']}, through {st.get('through')})"
    names = tickers()
    saved, kept = 0, []
    for i in range(0, len(names), BATCH):
        batch = names[i:i + BATCH]
        try:
            got = fetch(batch)
        except Exception as e:  # noqa: BLE001 - one bad batch must not stop the rest
            log(f"daily bars: batch {i // BATCH} failed: {e}", "dispatch")
            got = {}
        for t in batch:
            if t in got and better(got[t], OUT / f"{t}.parquet"):
                got[t].to_parquet(OUT / f"{t}.parquet")
                saved += 1
            else:
                kept.append(t)
    through = str(pd.read_parquet(OUT / "SPY.parquet").index.max().date())
    save_json(STATEF, {"date": str(date.today()), "through": through, "saved": saved, "kept_old": len(kept),
                       "kept_examples": kept[:20]})
    msg = (f"daily bars: {saved}/{len(names)} refreshed through {through}"
           + (f"; {len(kept)} kept their old file (not returned or shorter)" if kept else "")
           + (f"; seeded {seeded} files from V3" if seeded else ""))
    if saved < 0.9 * len(names):
        raise RuntimeError(msg + " - fewer than 90% refreshed (Yahoo throttled?)")
    return msg


if __name__ == "__main__":
    print(run(force="--force" in sys.argv))
