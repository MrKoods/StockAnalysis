"""Integrity checks on the live V2/V3/V4 paper ledgers - script only, read-only, never calls Claude.

    python tools/integrity.py            # print every problem found (known ones too)

Took over the data checks the old review agent's LLM used to do by eye every day: duplicate rows, impossible
values (exit before fill, R far outside the stop/target range, non-positive prices, absurd bps), and a ledger
that stopped updating. The Ops Monitor runs `check()` daily; only problems NOT seen on an earlier day go to the
Scorekeeper (state/integrity_seen.json), so an old, already-explained row never wakes a Claude role twice.
"""
from __future__ import annotations

import sys
from datetime import date

import pandas as pd

from common import LIVE_V2, LIVE_V3, LIVE_V4, STATE, load_json, save_json

SEEN = STATE / "integrity_seen.json"

# Gap-through losses of -1.3..-1.8R are real (stop gapped over) - only flag what no stop/target can produce.
R_MIN, R_MAX = -3.0, 8.0
BPS_MAX = 5000          # a 50% move in one trade = a data error, not a result
STALE_BDAYS = 3         # a ledger whose newest row is older than this many business days stopped updating

V2_LEDGERS = {"V2 threshold": "paper_trades.csv", "V2 rank": "rank_trades.csv", "V2 random": "random_trades.csv"}
V3_LEDGERS = {  # label: (path, key columns, value column, date column)
    "V3 ON1 paper": ("data/paper/on1_paper_ledger.csv", ["day", "ticker"], "bps", "day"),
    # G2 forward left out: G2 retired 2026-11-08 and its forward ledger stopped 2026-11-13 (user's decision).
    # no ticker column: several trades per day per index are normal, so no duplicate key
    "V3 ON1 forward": ("data/forward/on1_forward_trades.csv", [], "bps", "day"),
}


def _dupes(d: pd.DataFrame, keys: list[str], label: str) -> list[str]:
    if not keys:
        return []
    n = int(d.duplicated(subset=keys).sum())
    return [f"{label}: {n} duplicate row(s) on {'+'.join(keys)}"] if n else []


def _stale(newest, label: str, today: date) -> list[str]:
    if pd.isna(newest):
        return []
    lag = len(pd.bdate_range(pd.Timestamp(newest) + pd.Timedelta(days=1), pd.Timestamp(today))) - 1
    return [f"{label}: newest row is {pd.Timestamp(newest):%Y-%m-%d} ({lag} business days old) - "
            "ledger stopped updating?"] if lag > STALE_BDAYS else []


def v2_checks(d: pd.DataFrame, label: str, today: date) -> list[str]:
    out = _dupes(d, ["signal_date", "ticker", "direction"], label)
    fill, exit_ = pd.to_datetime(d["fill_date"], errors="coerce"), pd.to_datetime(d["exit_date"], errors="coerce")
    bad = d[exit_ < fill]
    if len(bad):
        out.append(f"{label}: {len(bad)} trade(s) exit before fill ({', '.join(bad['ticker'].astype(str)[:5])})")
    rr = pd.to_numeric(d["achieved_rr"], errors="coerce")
    bad = d[(rr < R_MIN) | (rr > R_MAX)]
    if len(bad):
        out.append(f"{label}: {len(bad)} trade(s) with R outside {R_MIN}..{R_MAX} "
                   f"({', '.join(f'{t} {r:+.2f}R' for t, r in zip(bad['ticker'], rr[bad.index]))})"[:300])
    for col in ("entry_price", "fill_price", "exit_price", "stop_loss"):
        if col in d:
            px = pd.to_numeric(d[col], errors="coerce")
            n = int((px <= 0).sum())
            if n:
                out.append(f"{label}: {n} row(s) with {col} <= 0")
    return out + _stale(pd.to_datetime(d["signal_date"], errors="coerce").max(), label, today)


def v3_checks(d: pd.DataFrame, label: str, keys: list[str], val: str | None, day_col: str, today: date) -> list[str]:
    out = _dupes(d, [k for k in keys if k in d], label)
    if val and val in d:
        v = pd.to_numeric(d[val], errors="coerce")
        n = int((v.abs() > BPS_MAX).sum())
        if n:
            out.append(f"{label}: {n} row(s) with |{val}| > {BPS_MAX} bps")
    return out + _stale(pd.to_datetime(d[day_col], errors="coerce").max(), label, today)


def v4_checks(d: pd.DataFrame, today: date) -> list[str]:
    label = "V4 EPRE"
    out = _dupes(d, ["entry_day", "ticker"], label)
    if "report_day" in d:  # a second trade on the same report from another entry day (2026-11-02 DST bug)
        out += _dupes(d, ["ticker", "report_day"], label)
    entry, exit_ = pd.to_datetime(d["entry_day"], errors="coerce"), pd.to_datetime(d["exit_day"], errors="coerce")
    n = int((exit_ <= entry).sum())
    if n:
        out.append(f"{label}: {n} trade(s) exit on/before entry day")
    for col in ("ret_bps", "net_bps", "hedged_bps"):
        v = pd.to_numeric(d[col], errors="coerce") if col in d else pd.Series(dtype=float)
        if n := int((v.abs() > BPS_MAX).sum()):
            out.append(f"{label}: {n} row(s) with |{col}| > {BPS_MAX} bps")
    for col in ("entry_close", "exit_close"):
        v = pd.to_numeric(d[col], errors="coerce") if col in d else pd.Series(dtype=float)
        if n := int((v <= 0).sum()):
            out.append(f"{label}: {n} row(s) with {col} <= 0")
    return out + _stale(entry.max(), label, today)


def scan(today: date | None = None) -> list[str]:
    """Every problem in every live ledger today (known ones included)."""
    today = today or date.today()
    out: list[str] = []
    for label, name in V2_LEDGERS.items():
        p = LIVE_V2 / "paper_trading" / name
        if p.exists():
            out += v2_checks(pd.read_csv(p), label, today)
    on1_retired = (STATE / "on1_retired.json").exists()     # tools/dispatch.retire_on1: its ledgers stop growing
    for label, (rel, keys, val, day_col) in V3_LEDGERS.items():
        p = LIVE_V3 / rel
        if p.exists() and not (on1_retired and "ON1" in label):
            out += v3_checks(pd.read_csv(p), label, keys, val, day_col, today)
    p = LIVE_V4 / "data" / "paper" / "epre_ledger.csv"
    if p.exists():
        out += v4_checks(pd.read_csv(p), today)
    return out


def check(today: date | None = None) -> tuple[list[str], list[str]]:
    """(new problems, already-known problems). New ones are remembered so they are reported once."""
    found = scan(today)
    seen = set(load_json(SEEN, []))
    new = [x for x in found if x not in seen]
    # Forget problems that went away, so a recurrence is reported again.
    save_json(SEEN, sorted(set(found)))
    return new, [x for x in found if x in seen]


if __name__ == "__main__":
    problems = scan()
    print("\n".join(problems) if problems else "integrity: no problems in any live ledger")
    sys.exit(0)
