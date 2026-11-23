"""Option Chain Recorder - a free daily record of real option bid/ask, so any options idea is judged at real spreads.

    python tools/option_chains.py capture            # what the Scan Operator runs (first weekday tick 12:30-12:54 PT)
    python tools/option_chains.py capture --force    # capture now, even outside the window / if today's file exists
    python tools/option_chains.py status             # what has been recorded

Why: free option HISTORY with bid/ask doesn't exist (Webull's option quotes need a paid data add-on; CBOE sells
history). CBOE's website serves today's full chains free, delayed ~15 min, with bid/ask, IV, greeks and open
interest. Recording them every afternoon builds our own history from 2026-11-23 on. Plain Python, zero tokens.

What is kept (per underlying per day, paper/options/<YYYY-MM-DD>_<SYM>.csv.gz - committed, irreplaceable):
expiries 0-60 calendar days out, strikes within 20% of spot (SPX: 0-45 days, 10% - it lists ~4x more strikes and
dailies; ~1/2 of the size budget). Underlyings: SPY, QQQ, IWM, SPX (CBOE "_SPX"). About 0.7 MB/day in git.
XSP is deliberately left out: its spreads were 12-15% of mid on 2026-11-22 vs 2-4% for SPY.
A day whose underlying last traded on another day (holiday / stale page) is not saved.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import date, datetime, time

import pandas as pd

from common import TEAM, log, now_pt

OUT = TEAM / "paper" / "options"
UNDERLYINGS = {"SPY": "SPY", "QQQ": "QQQ", "IWM": "IWM", "SPX": "_SPX"}
URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{}.json"
CAPTURE_FROM, CAPTURE_UNTIL = time(12, 30), time(12, 54)      # PT = 3:30-3:54 PM ET (quotes ~15 min delayed)
LIMITS = {"SPX": (45, 0.10)}                                  # (max days to expiry, max |strike/spot - 1|)
DEFAULT_LIMITS = (60, 0.20)
KEEP = ["option", "bid", "bid_size", "ask", "ask_size", "iv", "delta", "gamma", "vega", "theta", "theo",
        "open_interest", "volume", "last_trade_price", "last_trade_time"]


def fetch(cboe_sym: str) -> dict:
    req = urllib.request.Request(URL.format(cboe_sym), headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json",
        "Referer": "https://www.cboe.com/"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def tidy(payload: dict, today: date, sym: str = "") -> tuple[pd.DataFrame, str]:
    """CBOE payload -> trimmed chain. Returns (rows, cboe timestamp)."""
    d = payload["data"]
    # The page's own "timestamp" is when CBOE generated it (fresh even on a holiday); the underlying's last trade
    # is what says whether these are today's quotes.
    stamp = str(d.get("last_trade_time") or "")
    spot = float(d.get("current_price") or d.get("close"))
    o = pd.DataFrame(d["options"])
    parts = o["option"].str.extract(r"(?P<exp>\d{6})(?P<cp>[CP])(?P<k>\d{8})$")
    o["expiry"] = pd.to_datetime(parts["exp"], format="%y%m%d").dt.date
    o["type"] = parts["cp"]
    o["strike"] = parts["k"].astype(int) / 1000
    o["dte"] = [(e - today).days for e in o["expiry"]]
    max_dte, max_m = LIMITS.get(sym, DEFAULT_LIMITS)
    o = o[(o["dte"] >= 0) & (o["dte"] <= max_dte) & ((o["strike"] / spot - 1).abs() <= max_m)]
    o = o[["expiry", "dte", "type", "strike"] + [c for c in KEEP if c in o.columns]].copy()
    o.insert(0, "spot", spot)
    o.insert(0, "page_time_utc", payload.get("timestamp", ""))
    return o.sort_values(["expiry", "type", "strike"]), stamp


def due(now: datetime) -> bool:
    """First weekday Scan Operator tick in the window without today's files."""
    if now.weekday() >= 5 or not (CAPTURE_FROM <= now.time() <= CAPTURE_UNTIL):
        return False
    return not all((OUT / f"{now.date()}_{s}.csv.gz").exists() for s in UNDERLYINGS)


def capture(today: date | None = None, force: bool = False) -> str:
    today = today or now_pt().date()
    OUT.mkdir(parents=True, exist_ok=True)
    done, notes = [], []
    for sym, cboe in UNDERLYINGS.items():
        path = OUT / f"{today}_{sym}.csv.gz"
        if path.exists() and not force:
            continue
        try:
            rows, stamp = tidy(fetch(cboe), today, sym)
        except Exception as e:  # noqa: BLE001 - one bad underlying must not lose the others
            notes.append(f"{sym} failed ({str(e)[:80]})")
            continue
        if stamp[:10] != str(today):
            notes.append(f"{sym} stale (last trade {stamp or '?'}) - market closed? not saved")
            continue
        rows.to_csv(path, index=False, compression="gzip")
        done.append(f"{sym} {len(rows)}")
    return f"option chains {today}: saved {', '.join(done) or 'nothing'}" + (f"; {'; '.join(notes)}" if notes else "")


def status() -> str:
    files = sorted(OUT.glob("*.csv.gz")) if OUT.exists() else []
    days = sorted({f.name[:10] for f in files})
    size = sum(f.stat().st_size for f in files) / 1e6
    return (f"{len(days)} day(s) recorded ({days[0]} .. {days[-1]}), {len(files)} files, {size:.1f} MB"
            if days else "nothing recorded yet")


if __name__ == "__main__":
    if sys.argv[1:2] == ["capture"]:
        msg = capture(force="--force" in sys.argv)
        log(msg, "option_chains")
        print(msg)
    else:
        print(status() if sys.argv[1:2] == ["status"] else __doc__)
