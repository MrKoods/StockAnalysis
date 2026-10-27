"""Trial budget - every test the team (or the user, before the team) ever ran, and the bar a new result must clear.

    python tools/budget.py                  # totals per family + current holdout bar for each
    python tools/budget.py bar <family>     # the t a holdout in <family> must clear right now

Rule (fixed, see TEAM.md): a holdout result in family F must reach
    t >= max(3.0, z(1 - 0.025 / K))
where K = number of holdout tests ever run in F, counting this one. Search-stage variant counts don't set
the holdout bar (the holdout is one pre-registered test of a shortlist) - the Skeptic uses them to judge
whether the TRAIN result is distinguishable from the best-of-N luck baseline.
"""
from __future__ import annotations

import csv
import sys

from scipy.stats import norm

from common import TEAM

TRIALS = TEAM / "registry" / "trials.csv"
FIELDS = ["date", "idea_id", "family", "stage", "variants", "data", "result_t", "result_bps", "verdict", "note"]
FLOOR_T = 3.0


def rows() -> list[dict]:
    if not TRIALS.exists():
        return []
    with open(TRIALS, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append(row: dict) -> None:
    new = not TRIALS.exists()
    with open(TRIALS, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in FIELDS})


def holdouts_in(family: str) -> int:
    return sum(1 for r in rows() if r["family"] == family and r["stage"] == "holdout")


def holdout_bar(family: str, extra: int = 1) -> float:
    """t a NEW holdout in `family` must clear (extra=1 counts the test about to run)."""
    k = max(1, holdouts_in(family) + extra)
    return max(FLOOR_T, float(norm.ppf(1 - 0.025 / k)))


def totals() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in rows():
        t = out.setdefault(r["family"], {"search_variants": 0, "holdouts": 0, "paper": 0})
        if r["stage"] == "search":
            t["search_variants"] += int(float(r["variants"] or 0))
        elif r["stage"] == "holdout":
            t["holdouts"] += 1
        elif r["stage"] == "paper":
            t["paper"] += 1
    return out


def main(argv: list[str]) -> None:
    if len(argv) >= 2 and argv[0] == "bar":
        print(f"{holdout_bar(argv[1]):.2f}")
        return
    tot = totals()
    print(f"{'family':<28}{'search variants':>16}{'holdouts':>10}{'paper':>7}{'next bar t':>12}")
    for fam, t in sorted(tot.items(), key=lambda kv: -kv[1]["search_variants"]):
        print(f"{fam:<28}{t['search_variants']:>16,}{t['holdouts']:>10}{t['paper']:>7}{holdout_bar(fam):>12.2f}")
    print(f"\nALL: {sum(t['search_variants'] for t in tot.values()):,} search variants, "
          f"{sum(t['holdouts'] for t in tot.values())} holdout tests")


if __name__ == "__main__":
    main(sys.argv[1:])
