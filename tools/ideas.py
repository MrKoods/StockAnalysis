"""The idea pipeline (registry/ideas.csv). Agents change it ONLY through this script (Edit is denied), so
stage moves are checked here.

    python tools/ideas.py list [stage]
    python tools/ideas.py add --id <slug> --family <f> --horizon <h> --summary "..." --mechanism "..."
                              --data "..." --cost <bps> --gross <bps> [--source "..."] [--notes "..."]  (Scout)

Cost hurdle (user's decision 2026-11-23): an idea is refused unless its stated gross edge per trade (--gross, bps,
from a paper/screen - say where on the card) is at least HURDLE x its round-trip cost (--cost), and --cost is not
below the cheapest real round trip at the user's broker (team/fill_costs.json, S&P 500 close->close). 19 ideas
averaged t -0.2 = no edge minus cost; edges under ~3x cost never survived the winner's curse plus real spreads.
    python tools/ideas.py set <id> <stage> --note "..."                                         (Director)

Roles may only make these moves; every later stage is set by the scripts from the files on disk
(tools/jobs.py, tools/gate.py):
    idea -> queued | dropped          queued -> dropped | idea          paper -> (gate.py retire only)
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from datetime import date

from common import TEAM

IDEAS = TEAM / "registry" / "ideas.csv"
FIELDS = ["id", "date", "source", "family", "horizon", "stage", "summary", "mechanism", "data_needed",
          "est_cost_bps", "notes", "est_gross_bps"]
HURDLE = 3.0
STAGES = ["idea", "queued", "planned", "awaiting_review", "skeptic_pass", "holdout_done", "paper", "passed",
          "dead", "dropped"]
ROLE_MOVES = {("idea", "queued"), ("idea", "dropped"), ("queued", "dropped"), ("queued", "idea")}


def load() -> list[dict]:
    if not IDEAS.exists():
        return []
    with open(IDEAS, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save(rows: list[dict]) -> None:
    tmp = IDEAS.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})
    tmp.replace(IDEAS)


def get(iid: str) -> dict | None:
    return next((r for r in load() if r["id"] == iid), None)


def set_stage(iid: str, stage: str, note: str = "", by_script: bool = True) -> None:
    """Scripts call this directly; the CLI path below is the role path and checks ROLE_MOVES."""
    rows = load()
    for r in rows:
        if r["id"] == iid:
            if not by_script and (r["stage"], stage) not in ROLE_MOVES:
                raise SystemExit(f"refused: {iid} {r['stage']} -> {stage} is not a role move "
                                 f"(allowed: {sorted(ROLE_MOVES)})")
            r["stage"] = stage
            if note:
                r["notes"] = (r.get("notes", "") + f" | {date.today()} {stage}: {note}").strip(" |")[-1500:]
            save(rows)
            return
    raise SystemExit(f"no idea with id {iid}")


def cost_hurdle(gross, cost) -> str | None:
    """None if the idea clears the hurdle, else why not."""
    try:
        g, c = float(gross), float(cost)
    except (TypeError, ValueError):
        return "--gross and --cost must be numbers (bps per trade)"
    try:
        import fill_costs
        floor = fill_costs.floor_bps("close", "close", ["sp500"])
    except Exception:  # noqa: BLE001
        floor = 6.6
    if c < floor:
        return (f"--cost {c:g} bps is below the cheapest real round trip at the user's broker ({floor:g} bps, "
                f"S&P 500 close->close, team/fill_costs.json) - use the real cost for this idea's fills")
    if g < HURDLE * c:
        return (f"gross edge {g:g} bps < {HURDLE:g} x round-trip cost {c:g} bps = {HURDLE * c:g} - too thin to "
                f"survive the winner's curse and real spreads (cost hurdle, 2026-11-23)")
    return None


def add(a) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,40}", a.id):
        raise SystemExit("id must be a lowercase slug (a-z 0-9 _ -), 3-41 chars")
    if why := cost_hurdle(a.gross, a.cost):
        raise SystemExit(f"refused: {why}")
    rows = load()
    if any(r["id"] == a.id for r in rows):
        raise SystemExit(f"id {a.id} already exists")
    rows.append({"id": a.id, "date": str(date.today()), "source": a.source, "family": a.family,
                 "horizon": a.horizon, "stage": "idea", "summary": a.summary, "mechanism": a.mechanism,
                 "data_needed": a.data, "est_cost_bps": a.cost, "notes": a.notes, "est_gross_bps": a.gross})
    save(rows)
    print(f"added {a.id}")


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("stage", nargs="?")
    ad = sub.add_parser("add")
    for k in ("id", "family", "horizon", "summary", "mechanism", "data", "cost", "gross"):
        ad.add_argument(f"--{k}", required=True)
    ad.add_argument("--source", default="")
    ad.add_argument("--notes", default="")
    st = sub.add_parser("set")
    st.add_argument("id")
    st.add_argument("stage", choices=STAGES)
    st.add_argument("--note", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "list":
        for r in load():
            if not a.stage or r["stage"] == a.stage:
                print(f"{r['id']:<30} {r['stage']:<16} {r['family']:<22} {r['horizon']:<8} {r['summary'][:90]}")
    elif a.cmd == "add":
        add(a)
    else:
        set_stage(a.id, a.stage, a.note, by_script=False)
        print(f"{a.id} -> {a.stage}")


if __name__ == "__main__":
    main(sys.argv[1:])
