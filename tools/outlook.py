"""Outlook arithmetic for the live tests' next decision - script only, read-only.

    python tools/outlook.py

What each frozen rule still needs from the remaining days/trades (the old review agent worked this out by hand in
its weekly research). The Ops Monitor appends `lines()` to state/snapshot.txt, so the Scorekeeper and Director
quote these numbers instead of computing them; the daily report uses `short()`. Plain arithmetic on the means; it
is not a forecast of what will happen.
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


def v3_numbers(per_day: pd.Series) -> dict | None:
    """Per-day averages the remaining days need for 'not FAIL' (mean >= 0) and PASS at the next checkpoint."""
    n, total = len(per_day), float(per_day.sum())
    target = next((d for d in CHECK_DAYS if d > n), None)
    if target is None:
        return None
    left = target - n
    sd = float(per_day.std(ddof=1)) if n > 1 else float("nan")
    # PASS needs mean >= +5 AND day-t >= 2; if the day-to-day sd stays where it is, t >= 2 means mean >= 2 sd/sqrt(N)
    pass_mean = max(PASS_BPS, 2 * sd / target ** 0.5)
    return {"n": n, "target": target, "left": left, "mean": total / n, "sd": sd, "pass_mean": pass_mean,
            "need_zero": -total / left, "need_pass": (pass_mean * target - total) / left, "best": float(per_day.max())}


def _need(x: float) -> str:
    return f"must average {x:+.1f}" if x > 0 else f"can average as low as {x:+.1f}"


def v3_line(label: str, per_day: pd.Series) -> str:
    v = v3_numbers(per_day)
    if v is None:
        return f"{label}: {len(per_day)} days - past the last checkpoint, rule decides on the scored days"
    return (f"{label}: day {v['n']}/{v['target']}, mean {v['mean']:+.1f} bps/day (sd {v['sd']:.0f}). For day "
            f"{v['target']}: not FAIL (mean >= 0) -> the next {v['left']} day(s) {_need(v['need_zero'])} bps/day; "
            f"PASS (mean >= +5 and day-t >= 2, at this sd = mean >= {v['pass_mean']:+.1f}) -> {_need(v['need_pass'])} "
            f"bps/day. Best single day so far {v['best']:+.1f}.")


def v3_short(per_day: pd.Series) -> str:
    """One phrase for the daily report: the requirement that decides the next checkpoint."""
    v = v3_numbers(per_day)
    if v is None:
        return "past the last checkpoint"
    if v["need_zero"] > v["best"]:
        return f"FAIL at day {v['target']} unless +{v['need_zero']:.0f} bps/day for {v['left']} days (best day ever +{v['best']:.0f})"
    if v["need_pass"] <= 0:
        return f"on track to PASS at day {v['target']} (holds even at {v['need_pass']:+.0f} bps/day)"
    return f"PASS at day {v['target']} needs {v['need_pass']:+.0f} bps/day over the next {v['left']} days"


# "COLLECTING (88/100 ...)" until 100 trades, then "KEEP COLLECTING (105/200 ...)" up to the final verdict at 200.
V2_RX = r"COLLECTING \((\d+)/(\d+) closed trades[^)]*\)\s+mean R after costs ([+-][\d.]+)"


def _v2(snapshot: str) -> tuple[int, float, int] | None:
    m = re.search(V2_RX, snapshot)
    return (int(m.group(1)), float(m.group(3)), int(m.group(2))) if m else None


def v2_line(snapshot: str) -> str | None:
    v = _v2(snapshot)
    if not v:
        return None
    n, mean, target = v
    left = max(1, target - n)
    end = "final verdict" if target > 100 else "go/no-go"
    return (f"V2 rank {end}: {n}/{target}, mean {mean:+.3f}R after costs. To reach GO (+0.15) the last {left} trade(s) "
            f"must average {(0.15 * target - mean * n) / left:+.3f}R; to avoid NO-GO (< 0) {(-mean * n) / left:+.3f}R.")


def v2_short(snapshot: str) -> str | None:
    v = _v2(snapshot)
    if not v:
        return None
    n, mean, target = v
    left = max(1, target - n)
    return (f"GO needs {(0.15 * target - mean * n) / left:+.2f}R/trade for the last {left}; "
            f"NO-GO if they average below {(-mean * n) / left:+.2f}R")


def _per_day() -> dict[str, pd.Series]:
    out = {}
    for label, (rel, col) in V3_PAPER.items():
        p = LIVE_V3 / rel
        if p.exists():
            d = pd.read_csv(p).dropna(subset=[col])
            if len(d):
                out[label] = d.groupby("day")[col].mean()
    return out


def lines(snapshot: str = "") -> list[str]:
    return [x for x in [v2_line(snapshot)] if x] + [v3_line(k, s) for k, s in _per_day().items()]


def short(snapshot: str = "") -> dict[str, str]:
    """{test label: one-phrase requirement} for the daily report."""
    out = {k: v3_short(s) for k, s in _per_day().items()}
    if (v := v2_short(snapshot)):
        out["V2 rank"] = v
    return out


if __name__ == "__main__":
    from common import STATE
    snap = STATE / "snapshot.txt"
    text = snap.read_text(encoding="utf-8") if snap.exists() else ""
    print("\n".join(lines(text)))
    print("\n".join(f"{k}: {v}" for k, v in short(text).items()))
