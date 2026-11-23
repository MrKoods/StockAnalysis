"""CBOE index history (free, daily) -> data/cboe/<SYM>.csv, for research_data.cboe(). Plain Python, zero tokens.

    python tools/cboe_history.py          # refresh all (the dispatcher's data refresh runs this every dispatch)

Volatility indexes and CBOE's option-strategy benchmark indexes (mid-price, before trading costs):
  VIX (30-day implied vol of the S&P 500, 1990+), VIX9D (9-day, 2011+), VIX3M (3-month, 2009+), SKEW (1990+),
  PUT (sell 1-month ATM puts, 1991+), WPUT (weekly puts, 2006+), BXM (buy-write, 2002+ in this file),
  CNDR (iron condor, 1986+), BFLY (iron butterfly, 1986+).
"""
from __future__ import annotations

import io
import urllib.request

import pandas as pd

from common import TEAM

OUT = TEAM / "data" / "cboe"
SYMBOLS = ["VIX", "VIX9D", "VIX3M", "SKEW", "PUT", "WPUT", "BXM", "CNDR", "BFLY"]
URL = "https://cdn.cboe.com/api/global/us_indices/daily_prices/{}_History.csv"


def fetch(sym: str) -> pd.DataFrame:
    req = urllib.request.Request(URL.format(sym), headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode("utf-8")
    df = pd.read_csv(io.StringIO(raw))
    df.columns = [c.strip().lower() for c in df.columns]
    df["date"] = pd.to_datetime(df["date"], format="%m/%d/%Y")
    val = "close" if "close" in df.columns else [c for c in df.columns if c != "date"][-1]
    return df[["date", val]].rename(columns={val: "close"}).dropna().sort_values("date")


def run() -> str:
    OUT.mkdir(parents=True, exist_ok=True)
    done, bad = [], []
    for s in SYMBOLS:
        try:
            df = fetch(s)
            if len(df) < 100:
                raise ValueError(f"only {len(df)} rows")
            df.to_csv(OUT / f"{s}.csv", index=False)
            done.append(s)
        except Exception as e:  # noqa: BLE001 - keep yesterday's file for that symbol
            bad.append(f"{s} ({str(e)[:60]})")
    return f"cboe history: {len(done)}/{len(SYMBOLS)} refreshed" + (f"; failed {', '.join(bad)}" if bad else "")


if __name__ == "__main__":
    print(run())
