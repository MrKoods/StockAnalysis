"""How self-running is the team? (the user's goal, 2026-11-14: reach the edge THROUGH a team that runs and improves
itself - every time the user has to step in is a defect to remove). Script only, zero tokens.

    python tools/autonomy.py            # this week vs last week

Counted over a 7-day window, all from records the team already keeps:
  you stepped in  - commits on the team branch made OUTSIDE a dispatch (anything not "team-runner: ..." - the
                    dispatcher is the only other committer), and days the Ops Monitor raised a "needs you" alert
                    (state/autonomy.json, saved by record() every dispatch)
  asked you for   - items under "Data requests" (Director) / "Proposals for the user" (Engineer) in reports/: things
                    the team can't build or buy itself - the gaps that stop it improving on its own
  fixed itself    - Engineer code fixes kept (registry/engineer_log.csv "applied"), Scan Operator re-runs that
                    recovered a failed job (state/scan_ops.json "recovered:")
  couldn't        - Engineer fixes rolled back, Scan Operator give-ups ("gave_up:")
"""
from __future__ import annotations

import csv
import re
import sys
from datetime import date, timedelta

from common import STATE, TEAM, git, load_json, save_json

LEDGER = STATE / "autonomy.json"
ENG_LOG = TEAM / "registry" / "engineer_log.csv"
ASK_HEADINGS = {"director": "Data requests", "engineer": "Proposals for the user"}
KEEP_DAYS = 60


def record(today: date, f) -> None:
    """Save today's 'needs you' alerts (the Ops Monitor findings of this dispatch)."""
    led = load_json(LEDGER, {})
    led[str(today)] = {"alerts": list(f.alerts)}
    cut = str(today - timedelta(days=KEEP_DAYS))
    save_json(LEDGER, {d: v for d, v in led.items() if d >= cut})


def _days(end: date) -> tuple[str, str]:
    return str(end - timedelta(days=6)), str(end)


def user_commits(start: str, end: str) -> list[str]:
    out = git("log", f"--since={start} 00:00", f"--until={end} 23:59", "--date=format:%m-%d", "--format=%ad %s")
    return [l for l in out.splitlines() if l.strip() and not l[6:].startswith("team-runner:")]


def alert_days(start: str, end: str) -> dict[str, list[str]]:
    return {d: v["alerts"] for d, v in load_json(LEDGER, {}).items() if start <= d <= end and v.get("alerts")}


def asks(start: str, end: str) -> list[str]:
    """Numbered items under a role's request heading, from each role's LATEST report in the window (a request
    repeated every week is one open request, not several)."""
    out = []
    for role, heading in ASK_HEADINGS.items():
        files = sorted(p for p in (TEAM / "reports").glob(f"*-{role}.md") if start <= p.name[:10] <= end)
        if not files:
            continue
        text = files[-1].read_text(encoding="utf-8", errors="replace")
        m = re.search(rf"^##\s*{re.escape(heading)}[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
        for item in re.findall(r"^\d+\.\s+(.+)$", m.group(1) if m else "", re.M):
            out.append(f"{role}: {re.sub(r'[*`]', '', item)[:110]}")
    return out


def self_fixes(start: str, end: str) -> tuple[list[str], list[str]]:
    fixed, failed = [], []
    if ENG_LOG.exists():
        with open(ENG_LOG, encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if start <= r["date"] <= end:
                    (fixed if r["result"] == "applied" else failed).append(
                        f"{r['date'][5:]} Engineer {'fix' if r['result'] == 'applied' else 'rolled back'}: "
                        f"{r['files'].split()[0]}")
    st = load_json(STATE / "scan_ops.json", {})
    for d, day in st.items():
        if d[:2] == "20" and start <= d <= end and isinstance(day, dict):
            for k in day:
                job = k.split(":", 1)[-1].removeprefix("StockAnalysis_")
                if k.startswith("recovered:"):
                    fixed.append(f"{d[5:]} Scan Operator re-ran {job} - recovered")
                elif k.startswith("gave_up:"):
                    failed.append(f"{d[5:]} Scan Operator gave up on {job}")
    return fixed, failed


def week(end: date) -> dict:
    s, e = _days(end)
    fixed, failed = self_fixes(s, e)
    return {"commits": user_commits(s, e), "alert_days": alert_days(s, e), "asks": asks(s, e),
            "fixed": fixed, "failed": failed}


def summary(today: date) -> list[str]:
    """Daily-report lines: this week, then last week's numbers for the trend."""
    w, prev = week(today), week(today - timedelta(days=7))
    stepped = len(w["commits"]) + len(w["alert_days"])
    stepped_prev = len(prev["commits"]) + len(prev["alert_days"])
    trend = ("better" if stepped < stepped_prev else "worse" if stepped > stepped_prev else "same")
    lines = [f"• You stepped in **{stepped}×** this week (last week {stepped_prev}× - {trend}): "
             f"{len(w['commits'])} change(s) from your sessions, {len(w['alert_days'])} day(s) with a needs-you alert",
             f"• Team fixed itself **{len(w['fixed'])}×**, couldn't **{len(w['failed'])}×**"
             + (f" ({'; '.join(w['failed'][:3])})" if w["failed"] else "")]
    if w["asks"]:
        lines.append(f"• Open requests the team can't do itself ({len(w['asks'])}): "
                     + " | ".join(a[:90] for a in w["asks"][:3]))
    return lines


def report(today: date) -> str:
    w = week(today)
    out = ["Self-running check (7 days to " + str(today) + ")", *summary(today), "", "Your sessions' changes:"]
    out += [f"  {c}" for c in w["commits"]] or ["  none"]
    out += ["Needs-you alert days:"] + ([f"  {d}: {a[0][:120]}" for d, a in w["alert_days"].items()] or ["  none"])
    out += ["Team fixed itself:"] + ([f"  {x}" for x in w["fixed"]] or ["  none"])
    out += ["Couldn't fix itself:"] + ([f"  {x}" for x in w["failed"]] or ["  none"])
    out += ["Asked you for:"] + ([f"  {x}" for x in w["asks"]] or ["  none"])
    return "\n".join(out)


if __name__ == "__main__":
    day = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    print(report(day))
