"""Real fill costs at Webull, measured from the Quote Clerk's bid/ask captures (paper/quotes.csv).

    python tools/fill_costs.py        # rewrite team/fill_costs.json (the dispatcher does this every run)

Webull retail has no opening/closing auction orders (market/limit-on-open/close are "institutional only" in
Webull's API docs), so a trade "at the open" really pays the ~9:31 spread and one "at the close" the ~3:56
spread. Research uses these as a FLOOR under a plan's cost_bps (tools/jobs.py): an idea can't pass on a cost
it could never get. Mean (not median) half-spread: the expected cost of one fill.
"""
from __future__ import annotations

import json
from datetime import date

import pandas as pd

from common import LIVE_V4, TEAM, load_json, now_pt, save_json

QUOTES = TEAM / "paper" / "quotes.csv"
OUT = TEAM / "team" / "fill_costs.json"
INDEXES = ("sp500", "sp400", "sp600")
MIN_QUOTES = 30
# Measured 2026-11-02..04 (~1,400 quotes) - used until a cell has MIN_QUOTES of its own, and as a sanity floor.
DEFAULT_HALF_BPS = {"open": {"sp500": 40.0, "sp400": 93.0, "sp600": 126.0},
                    "close": {"sp500": 3.3, "sp400": 6.2, "sp600": 10.8}}


def index_of() -> dict[str, str]:
    out: dict[str, str] = {}
    for name in INDEXES:
        f = LIVE_V4 / "data" / "universe" / f"{name}.csv"
        if f.exists():
            for t in pd.read_csv(f)["ticker"]:
                out.setdefault(str(t), name)
    return out


def measure() -> dict:
    half = {w: dict(v) for w, v in DEFAULT_HALF_BPS.items()}
    counts = {w: {i: 0 for i in INDEXES} for w in half}
    days = []
    if QUOTES.exists():
        q = pd.read_csv(QUOTES)
        q = q[(q["bid"] > 0) & (q["ask"] > q["bid"])]
        q["half_bps"] = (q["ask"] - q["bid"]) / ((q["ask"] + q["bid"]) / 2) * 1e4 / 2
        q["index"] = q["ticker"].astype(str).map(index_of())
        q = q.dropna(subset=["index"])
        days = sorted(q["date"].astype(str).unique())
        for (w, i), g in q.groupby(["when", "index"]):
            if w in half and len(g) >= MIN_QUOTES:
                half[w][i], counts[w][i] = round(float(g["half_bps"].mean()), 1), int(len(g))
            elif w in half:
                counts[w][i] = int(len(g))
    return {"_doc": "Mean HALF-spread (bps) paid per fill at Webull, by fill time and index (tools/fill_costs.py). "
                    "A round trip costs entry half + exit half. Cells with < 30 quotes use the 2026-11-04 defaults.",
            "updated": f"{now_pt():%Y-%m-%d %H:%M}", "quote_days": len(days),
            "first_day": days[0] if days else None, "last_day": days[-1] if days else None,
            "half_spread_bps": half, "quotes": counts}


def write() -> str:
    m = measure()
    save_json(OUT, m)
    h = m["half_spread_bps"]
    return (f"fill costs ({m['quote_days']} quote days): round trip open->open sp500/400/600 "
            f"{2 * h['open']['sp500']:.0f}/{2 * h['open']['sp400']:.0f}/{2 * h['open']['sp600']:.0f} bps, "
            f"close->close {2 * h['close']['sp500']:.0f}/{2 * h['close']['sp400']:.0f}/{2 * h['close']['sp600']:.0f}")


def floor_bps(entry_at: str, exit_at: str, universe: list[str], costs: dict | None = None) -> float:
    """Round-trip cost floor for a plan: the worst (most expensive) index it trades, at its fill times."""
    h = (costs or load_json(OUT, None) or {"half_spread_bps": DEFAULT_HALF_BPS})["half_spread_bps"]
    idx = [i for i in universe if i in INDEXES] or list(INDEXES)
    return round(max(h[entry_at][i] + h[exit_at][i] for i in idx), 1)


if __name__ == "__main__":
    print(write())
