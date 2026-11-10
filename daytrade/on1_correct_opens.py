"""One-off data correction of the ON1 paper ledger, declared 2026-11-09 (user's decision). Rules are unchanged.

    python -m daytrade.on1_correct_opens            # dry run: print before/after, write nothing
    python -m daytrade.on1_correct_opens --apply    # back up the ledger, then write

Why: `_score` took next_open from Yahoo at 09:45 ET, while that session was still running, and never revisited it.
Many of those opens were wrong (FIS 2026-11-04: ledger 40.62, Webull minute bars 30.43). This replaces close and
next_open on every already-scored row with Yahoo's settled daily bars, and recomputes bps the same way as before.
Picks, days, the cost and verdict() are untouched. Rows Yahoo no longer returns keep their original numbers.
"""
from __future__ import annotations

import logging
import sys

import numpy as np
import pandas as pd
import yfinance as yf

from .on1_paper import COST_BPS, LEDGER, verdict

BACKUP = LEDGER.with_name("on1_paper_ledger_before_open_correction_2026-11-09.csv")
CHANGES = LEDGER.with_name("on1_open_corrections_2026-11-09.csv")
QUOTES = LEDGER.parents[2].parent / "StockAnalysis-Team" / "paper" / "quotes.csv"
MAX_MISSING = 0.02


def corrected(old: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    led = old.copy()
    done = led["bps"].notna() & led["next_day"].notna()
    tick = sorted(led.loc[done, "ticker"].unique())
    first = pd.to_datetime(led.loc[done, "day"]).min()
    raw = yf.download(tick, start=(first - pd.Timedelta(days=3)).strftime("%Y-%m-%d"), interval="1d",
                      group_by="ticker", auto_adjust=False, progress=False, threads=True)
    missing = 0
    for i in np.flatnonzero(done.to_numpy()):
        t = led.at[i, "ticker"]
        if t not in raw.columns.get_level_values(0):
            missing += 1
            continue
        df = raw[t].dropna(subset=["Open", "Close"])
        a, b = pd.Timestamp(led.at[i, "day"]), pd.Timestamp(led.at[i, "next_day"])
        if a not in df.index or b not in df.index:
            missing += 1
            continue
        c, o = float(df.at[a, "Close"]), float(df.at[b, "Open"])
        led.at[i, "close"], led.at[i, "next_open"] = round(c, 4), round(o, 4)
        led.at[i, "bps"] = round((o / c - 1) * 1e4 - 2 * COST_BPS, 1)
    return led, missing


def check_against_quotes(led: pd.DataFrame, old: pd.DataFrame) -> None:
    """Independent check: Webull's mid quote ~1 minute into the session vs each version of the open."""
    q = pd.read_csv(QUOTES)
    q = q[q["when"] == "open"].drop_duplicates(["date", "ticker"], keep="last")
    q["mid"] = (q["bid"] + q["ask"]) / 2
    for name, d in (("original", old), ("corrected", led)):
        m = d.merge(q, left_on=["next_day", "ticker"], right_on=["date", "ticker"])
        off = ((m["mid"] / m["next_open"] - 1) * 1e4).abs()
        print(f"  {name}: {len(m)} trades vs Webull 9:31 mid | median miss {off.median():.0f} bps | mean {off.mean():.0f} | "
              f"over 500 bps: {int((off > 500).sum())}")


def main(apply: bool) -> int:
    old = pd.read_csv(LEDGER)
    old["next_day"] = old["next_day"].astype(object)
    led, missing = corrected(old)
    scored = int(old["bps"].notna().sum())
    moved = (led["bps"] - old["bps"]).abs() > 0.05
    closes = ((led["close"] / old["close"] - 1).abs() * 1e4 > 5).sum()
    print(f"scored rows {scored} | changed {int(moved.sum())} | no settled bar {missing} | closes moved >5 bps {int(closes)}")
    for name, d in (("before", old), ("after ", led)):
        x = d.dropna(subset=["bps"])
        print(f"  {name}: {x['bps'].mean():+.1f} bps/trade, {x['day'].nunique()} days | {verdict(x)}"
              f" | day-t {x.groupby('day')['bps'].mean().pipe(lambda s: s.mean() / (s.std(ddof=1) / np.sqrt(len(s)))):.2f}")
    check_against_quotes(led, old)
    if missing > MAX_MISSING * scored:
        print(f"REFUSED: {missing} rows without settled bars (> {MAX_MISSING:.0%}) - Yahoo throttled? Nothing written.")
        return 1
    if apply:
        if BACKUP.exists():
            print(f"REFUSED: {BACKUP.name} already exists - the correction was already applied. Nothing written.")
            return 1
        old.to_csv(BACKUP, index=False)
        ch = old.loc[moved, ["day", "ticker", "close", "next_open", "bps"]].join(
            led.loc[moved, ["close", "next_open", "bps"]], rsuffix="_corrected")
        ch.to_csv(CHANGES, index=False)
        led.to_csv(LEDGER, index=False)
        print(f"written; original saved as {BACKUP.name}, changes in {CHANGES.name}")
    else:
        print("dry run - nothing written")
    return 0


if __name__ == "__main__":
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    sys.exit(main("--apply" in sys.argv))
