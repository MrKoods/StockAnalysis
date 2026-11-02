"""Outlook arithmetic for the live tests' next decision - script only, read-only.

    python tools/outlook.py

What each frozen rule still needs from the remaining days/trades (the old review agent worked this out by hand in
its weekly research). The Ops Monitor appends it to state/snapshot.txt, so the Scorekeeper and Director quote these
numbers instead of computing them. Plain arithmetic on the means; it is not a forecast of what will happen.
"""
from __future__ import annotations

import re

import pandas as pd

from common import LIVE_V3

V3_PAPER = {  # label: (ledger, value column); rule (both): from day 20 PASS if mean >= +5 bps & day-t >= 2,
    "G2 paper": ("data/paper/g2_paper_ledger.csv", "bps_at_0932_entry"),   # FAIL if mean < 0; day 40 decides
    "ON1 paper": ("data/paper/on1_paper_ledger.csv", "bps"),
}
PASS_BPS, CHECK_DAYS = 5.0, (20, 40)


def v3_line(label: str, per_day: pd.Series) -> str:
    n, total = len(per_day), float(per_day.sum())
    target = next((d for d in CHECK_DAYS if d > n), None)
    if target is None:
        return f"{label}: {n} days - past the last checkpoint, rule decides on the scored days"
    left = target - n
    sd = float(per_day.std(ddof=1)) if n > 1 else float("nan")
    # PASS needs mean >= +5 AND day-t >= 2; if the day-to-day sd stays where it is, t >= 2 means mean >= 2 sd/sqrt(N)
    pass_mean = max(PASS_BPS, 2 * sd / target ** 0.5)

    def need(final_mean: float) -> str:
        x = (final_mean * target - total) / left
        return f"must average {x:+.1f}" if x > 0 else f"can average as low as {x:+.1f}"

    return (f"{label}: day {n}/{target}, mean {total / n:+.1f} bps/day (sd {sd:.0f}). For day {target}: not FAIL "
            f"(mean >= 0) -> the next {left} day(s) {need(0)} bps/day; PASS (mean >= +5 and day-t >= 2, at this sd "
            f"= mean >= {pass_mean:+.1f}) -> {need(pass_mean)} bps/day. Best single day so far {per_day.max():+.1f}.")


def v2_line(snapshot: str) -> str | None:
    m = re.search(r"COLLECTING \((\d+)/100 closed trades\)\s+mean R after costs ([+-][\d.]+)", snapshot)
    if not m:
        return None
    n, mean = int(m.group(1)), float(m.group(2))
    left = 100 - n
    return (f"V2 rank go/no-go: {n}/100, mean {mean:+.3f}R after costs. To reach GO (+0.15) the last {left} trade(s) "
            f"must average {(0.15 * 100 - mean * n) / left:+.3f}R; to avoid NO-GO (< 0) {(-mean * n) / left:+.3f}R.")


def lines(snapshot: str = "") -> list[str]:
    out = [x for x in [v2_line(snapshot)] if x]
    for label, (rel, col) in V3_PAPER.items():
        p = LIVE_V3 / rel
        if p.exists():
            d = pd.read_csv(p).dropna(subset=[col])
            if len(d):
                out.append(v3_line(label, d.groupby("day")[col].mean()))
    return out


if __name__ == "__main__":
    from common import STATE
    snap = STATE / "snapshot.txt"
    print("\n".join(lines(snap.read_text(encoding="utf-8") if snap.exists() else "")))
