"""The team's search playbook and the monthly Strategist's evidence pack (user 2026-11-24: "if I left for a year,
I'd come back to a better model"). Plain Python, zero tokens.

    python tools/playbook.py pack      # write state/review_pack.md (the dispatcher does this before the Strategist)
    python tools/playbook.py guard     # put the user's fixed section back if it was edited
    python tools/playbook.py due       # is the monthly review due this Saturday?

Why: without this the loop only DISCARDS ideas - the Scout's instructions, the research methods and the search
priorities stay what a user session last wrote. playbook/PLAYBOOK.md is the team's own living strategy: the
Strategist (Opus, first Saturday a month) reads every result so far (the pack below), changes the priorities,
the methods guidance and the areas to stop, and logs each change with its evidence. The Scout, Director and
Researcher read it every run.

What it can't change: the pass/fail machinery is code (gate, holdout wall, cost hurdle in ideas.py, luck bar in
jobs.py, frozen paper rules) and the user's decisions sit in a FIXED section that guard() rewrites from FIXED
below after every Strategist run - an edit there is undone and reported.
"""
from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from datetime import date, timedelta

from common import STATE, TEAM, log

PLAYBOOK = TEAM / "playbook" / "PLAYBOOK.md"
PACK = STATE / "review_pack.md"
EVERY_DAYS = 27                       # first Saturday on/after 4 weeks since the last review
START, END = "<!-- FIXED BY THE USER - START (tools/playbook.py rewrites this; edits are undone) -->", \
             "<!-- FIXED BY THE USER - END -->"
FIXED = """## Fixed by the user (the Strategist cannot change this section)
- Goal: make money trading, reached through this team running and improving itself (2026-11-14).
- No real money until a pre-registered test passes its frozen rule. Agents never place orders.
- Account $20k (< $25k pattern-day-trader line): real money only for rules that hold overnight or longer.
- Options are allowed (defined-risk), forward-recorded only (paper/options) - no free option history.
- Costs are real Webull spreads (team/fill_costs.json); an idea needs gross edge >= 3x its round-trip cost
  (code-enforced in tools/ideas.py). Holdouts are used once; luck bars count every variant ever tried.
- Ask the user before paying for any data or service. Cadence (Scout Mondays to 5 ideas, 1 idea in research at a
  time) is the user's setting in tools/dispatch.py - propose changes, don't assume them."""


def _reports(role: str) -> list:
    return sorted((TEAM / "reports").glob(f"*-{role}.md"))


def last_review() -> str | None:
    r = _reports("strategist")
    return r[-1].name[:10] if r else None


def due(today: date) -> bool:
    last = last_review()
    return today.weekday() == 5 and (last is None or (today - date.fromisoformat(last)).days >= EVERY_DAYS)


def why_due(today: date) -> str:
    last = last_review()
    return (f"monthly self-review (last {last or 'never'}): read state/review_pack.md and revise "
            f"playbook/PLAYBOOK.md from all results so far")


# ---------- the guard ----------

def guard() -> str:
    """Rewrite the fixed section from FIXED. Returns what it did (logged by the dispatcher)."""
    if not PLAYBOOK.exists():
        return "no playbook"
    text = PLAYBOOK.read_text(encoding="utf-8")
    block = f"{START}\n{FIXED}\n{END}"
    m = re.search(re.escape(START) + r".*?" + re.escape(END), text, re.S)
    if m and m.group(0) == block:
        return "fixed section intact"
    new = text.replace(m.group(0), block) if m else re.sub(r"\A(# [^\n]*\n)", rf"\1\n{block}\n", text, count=1) \
        if text.startswith("# ") else f"{block}\n\n{text}"
    PLAYBOOK.write_text(new, encoding="utf-8")
    log("playbook: the fixed section had been edited - restored", "dispatch")
    return "fixed section RESTORED (it had been edited)"


# ---------- the evidence pack ----------

def _ideas() -> list[dict]:
    p = TEAM / "registry" / "ideas.csv"
    return list(csv.DictReader(open(p, encoding="utf-8"))) if p.exists() else []


def _t(rx: str, text: str) -> float | None:
    m = re.findall(rx, text or "")
    return float(m[-1]) if m else None


def family_table(ideas: list[dict]) -> list[str]:
    """Per family: ideas, how far they got, best train t, holdout t (from the stage notes the pipeline writes)."""
    fam: dict[str, list[dict]] = defaultdict(list)
    for r in ideas:
        fam[r["family"]].append(r)
    rows = ["| family | ideas | stages | train t (chosen) | holdout t |", "|---|---|---|---|---|"]
    for f, rs in sorted(fam.items(), key=lambda kv: -len(kv[1])):
        stages = defaultdict(int)
        for r in rs:
            stages[r["stage"]] += 1
        tr = [x for r in rs if (x := _t(r"train done: chosen \S+ t (-?[\d.]+)", r["notes"])) is not None]
        ho = [x for r in rs if (x := _t(r"holdout \w+: t (-?[\d.]+)", r["notes"])) is not None]
        rows.append(f"| {f} | {len(rs)} | {', '.join(f'{k} {v}' for k, v in sorted(stages.items()))} | "
                    f"{', '.join(f'{x:.1f}' for x in tr) or '-'} | {', '.join(f'{x:.1f}' for x in ho) or '-'} |")
    return rows


def shrinkage(ideas: list[dict]) -> str:
    pairs = [(a, b) for r in ideas
             if (a := _t(r"train done: chosen \S+ t (-?[\d.]+)", r["notes"])) is not None
             and (b := _t(r"holdout \w+: t (-?[\d.]+)", r["notes"])) is not None]
    if not pairs:
        return "no idea has both a train and a holdout t yet"
    tr, ho = sum(a for a, _ in pairs) / len(pairs), sum(b for _, b in pairs) / len(pairs)
    return (f"{len(pairs)} ideas reached a holdout: mean chosen train t {tr:.2f} -> holdout t {ho:.2f} "
            f"(holdout keeps {ho / tr:.0%} of the train t)" if tr else "")


def usage(days: int, today: date) -> list[str]:
    p = STATE / "usage.csv"
    if not p.exists():
        return []
    cut = str(today - timedelta(days=days))
    by: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    for r in csv.DictReader(open(p, encoding="utf-8")):
        if r["date"] >= cut:
            by[r["role"]][0] += 1
            try:
                by[r["role"]][1] += float(r.get("cost_equiv_usd") or 0)
            except ValueError:
                pass
    return [f"- {k}: {int(v[0])} runs, ~${v[1]:.0f} plan-equivalent" for k, v in sorted(by.items())]


def _section(path, heading: str) -> str:
    if not path.exists():
        return "(none)"
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(rf"^##\s*{re.escape(heading)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip()[:2500] if m else "(none)"


def write_pack(today: date) -> str:
    import autonomy
    ideas = _ideas()
    since = last_review() or "2026-10-23"
    new = [r for r in ideas if r["date"] >= since]
    snap = (STATE / "snapshot.txt").read_text(encoding="utf-8", errors="replace") if (STATE / "snapshot.txt").exists() else ""
    live = [l.strip() for l in snap.splitlines() if re.match(r"\s*\[(EPRE paper|ON1 paper|rank|threshold|random)\]", l)]
    lines = [f"# Review pack {today} - written by tools/playbook.py (facts only; numbers are fresh)", "",
             f"Last review: {last_review() or 'never'}. Ideas registered since then: {len(new)} "
             f"({', '.join(r['id'] + ' [' + r['stage'] + ']' for r in new) or 'none'}).", "",
             "## Every family so far (registry/ideas.csv)", *family_table(ideas), "",
             "## Train -> holdout", shrinkage(ideas), "",
             "## Live and paper tests (state/snapshot.txt)", *([f"- {l[:200]}" for l in live] or ["- none found"]), "",
             "## Self-running (tools/autonomy.py)", *autonomy.summary(today), "",
             "## Claude usage, last 30 days (state/usage.csv)", *usage(30, today), "",
             "## Scout's 'Needs data' list (notes/scout.md)", _section(TEAM / "notes" / "scout.md", "Needs data"), "",
             "## Latest Auditor recommendations",
             _section(_reports("auditor")[-1], "Recommendations") if _reports("auditor") else "(none)", "",
             "Read further only where a decision needs it: registry/ideas.csv notes, registry/trials.csv, "
             "registry/graveyard.md, research/<id>/ (PLAN.md, *_result.json, review.md), reports/."]
    PACK.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f"review pack: {len(ideas)} ideas, {len(new)} new since {since}"


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "pack":
        print(write_pack(date.today()))
    elif cmd == "guard":
        print(guard())
    elif cmd == "due":
        print(due(date.today()), why_due(date.today()))
    else:
        print(__doc__)
