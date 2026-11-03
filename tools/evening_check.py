"""Evening check (Mon-Fri, from the first Scan Operator tick at/after 18:00 PT) - script only, zero Claude tokens.

    python tools/evening_check.py [--dry-run] [--force]

The daily report goes out ~2:51 PM; this covers what runs after it, mainly the V4 EPRE earnings calendar (17:15).
A refresh can "succeed" with bad data: on 2026-11-02 Yahoo's placeholder time moved with the DST change and the
share of report times taken from company history fell from 52% to 0.4% with no error anywhere. So besides "did
it run" this compares the new calendar with the last good one and says plainly when it moved too much.
Posts one short message to #agent-ops: 🌙 all OK, or 🛑 with what to look at.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, time

import pandas as pd

from common import LIVE_V4, STATE, load_json, log, now_pt, post, save_json
from ops_monitor import Findings, check_tasks, last_due, scheduled_tasks

STATEF = STATE / "evening_check.json"
CALENDAR = LIVE_V4 / "data" / "calendar" / "earnings_calendar.csv"
CAL_LOG = LIVE_V4 / "data" / "logs" / "epre_calendar_task.log"
CAL_TASK = "StockAnalysis_V4_EPRE_Calendar"
START, LAST_TICK = time(18, 0), time(18, 45)   # ScanOps runs every 10 min to 18:50
MAX_HISTORY_SHIFT = 0.15                       # share of times from company history, day to day
MAX_EVENT_DROP = 0.25                          # upcoming events, day to day
USER = "Team - Evening Check"


def calendar_stats(cal: pd.DataFrame) -> dict:
    return {"refreshed": str(cal["refreshed"].max()) if len(cal) else None, "events": len(cal),
            "history_share": round(float((cal["time_source"] == "history").mean()), 3) if len(cal) else 0.0}


def compare(new: dict, prev: dict | None, today: str) -> list[str]:
    """Problems with tonight's calendar compared with the last good one."""
    out = []
    if not new["refreshed"] or new["refreshed"] < today:   # V4 dates it in ET, so a late PT run reads tomorrow
        out.append(f"EPRE calendar was NOT refreshed today (last refresh {new['refreshed']}) - tomorrow's and later "
                   "trades may be missed or mistimed. Check StockAnalysis-V4/data/logs/epre_calendar_task.log")
    if prev and prev.get("events"):
        if new["events"] < (1 - MAX_EVENT_DROP) * prev["events"]:
            out.append(f"EPRE calendar shrank {prev['events']:,} -> {new['events']:,} upcoming reports "
                       f"(> {MAX_EVENT_DROP:.0%} drop) - Yahoo throttled or changed?")
        shift = new["history_share"] - prev["history_share"]
        if abs(shift) > MAX_HISTORY_SHIFT:
            out.append(f"EPRE calendar: share of report times taken from company history moved "
                       f"{prev['history_share']:.0%} -> {new['history_share']:.0%} in one night. Yahoo probably changed "
                       "its time format (as at the DST change 2026-11-02) - before/after-close timing may be wrong. "
                       "Ask Claude to compare tonight's calendar with yesterday's before the 12:38 PM signals.")
    return out


def calendar_errors(today: str) -> int | None:
    if not CAL_LOG.exists():
        return None
    hits = [m for line in CAL_LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
            if line.startswith(today) and (m := re.search(r"calendar: \d+ upcoming events, (\d+) errors", line))]
    return int(hits[-1].group(1)) if hits else None


def run(dry_run: bool = False, force: bool = False) -> str | None:
    now = now_pt()
    today = now.date().isoformat()
    st = load_json(STATEF, {})
    if not force and (now.weekday() >= 5 or now.time() < START or st.get("date") == today):
        return None
    tasks = scheduled_tasks()
    cal_task = next((t for t in tasks if t["Name"] == CAL_TASK), {})
    if cal_task.get("State") == "Running" and now.time() < LAST_TICK and not force:
        log("evening check: calendar refresh still running - next tick", "evening")
        return None
    problems: list[str] = []
    # Jobs due since the daily report (~14:51) - the earlier ones were in that report.
    f = Findings()
    since = datetime.combine(now.date(), time(14, 51))
    late = [t for t in tasks if t["Name"] != "StockAnalysis_Team_ScanOps"   # ScanOps = this run itself
            and (due := last_due(t.get("Triggers"), now)) is not None and due >= since]
    check_tasks(late, now, f)
    problems += f.alerts
    if cal_task.get("State") == "Running":
        problems.append("EPRE calendar refresh was still running at 18:45 - check it finished tonight")
    info = []
    if CALENDAR.exists():
        new = calendar_stats(pd.read_csv(CALENDAR))
        prev = st.get("last_good")
        cal_problems = compare(new, prev, today)
        problems += cal_problems
        errs = calendar_errors(today)
        was = f" (previous {prev['history_share']:.0%})" if prev else ""
        info.append(f"• EPRE calendar refreshed · {new['events']:,} upcoming reports · "
                    f"{new['history_share']:.0%} timed from company history{was}"
                    + (f" · {errs} Yahoo errors" if errs else ""))
        if not cal_problems:
            st["last_good"] = new          # a bad night is never the baseline for the next one
    else:
        problems.append("EPRE calendar file is missing")
    head = (f"🛑 **Evening check {now:%a %m-%d}** - {len(problems)} problem(s)" if problems
            else f"🌙 **Evening check {now:%a %m-%d}** - all OK, ready for tomorrow")
    text = "\n".join([head] + [f"• {p}" for p in problems] + info)
    post("ops", text, USER, dry_run)
    if not dry_run:
        st["date"] = today
        save_json(STATEF, st)
    log(f"evening check: {len(problems)} problem(s)", "evening")
    return text


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv, force="--force" in sys.argv)
