"""The idea pipeline (registry/ideas.csv). Agents change it ONLY through this script (Edit is denied), so
stage moves are checked here.

    python tools/ideas.py list [stage]
    python tools/ideas.py add --id <slug> --family <f> --horizon <h> --summary "..." --mechanism "..."
                              --data "..." --cost <bps> [--source "..."] [--notes "..."]          (Scout)
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
          "est_cost_bps", "notes"]
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


def add(a) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,40}", a.id):
        raise SystemExit("id must be a lowercase slug (a-z 0-9 _ -), 3-41 chars")
    rows = load()
    if any(r["id"] == a.id for r in rows):
        raise SystemExit(f"id {a.id} already exists")
    rows.append({"id": a.id, "date": str(date.today()), "source": a.source, "family": a.family,
                 "horizon": a.horizon, "stage": "idea", "summary": a.summary, "mechanism": a.mechanism,
                 "data_needed": a.data, "est_cost_bps": a.cost, "notes": a.notes})
    save(rows)
    print(f"added {a.id}")


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("stage", nargs="?")
    ad = sub.add_parser("add")
    for k in ("id", "family", "horizon", "summary", "mechanism", "data", "cost"):
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
