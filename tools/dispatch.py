"""Dispatcher - the team's single scheduled entry point (StockAnalysis_Team_Dispatch, Mon-Sat 14:50 PT).

    python tools/dispatch.py [--dry-run] [--force <role>] [--no-claude]
    python tools/dispatch.py --resume [--wait]   # roles a Claude plan limit held back (tools/plan_limit.py)

Scripts do the routine work; a Claude role is launched ONLY when it has a reason to run:
  1. paper_runner  - script: fill/exit/score the team's paper tests, log tomorrow's signals; data refresh
                     (EDGAR, catalog) and the free bulk event screen (tools/screen.py -> state/screen.md)
  2. ops_monitor   - script: all checks; a problem is posted to #agent-ops at once
  3. triggers      - script: decide which roles have work (see TRIGGERS below)
  4. roles         - Claude headless, one at a time, each with its own model / turn cap / permission file;
                     Saturday ends with the Auditor (read-only, independent check of the whole project)
  5. commit        - the dispatcher commits after every step (agents have no git access)
  6. daily report  - script: the end-of-day report to #agent-ops, Mon-Fri (tools/daily_report.py)

--dry-run prints posts instead of sending, writes no ledger, launches no Claude.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import date, datetime, timedelta

import budget
import catalog
import daily_bars
import daily_report
import edgar
import fill_costs
import ideas
import jobs
import ops_monitor
import paper_runner
import plan_limit
import quotes
import scan_ops
import screen
from common import (LIVE_V2, LIVE_V3, LIVE_V4, OUTBOX, STATE, TEAM, commit, git, load_json, log, now_pt,
                    post, save_json, stopped)

ROLES = TEAM / "team" / "roles.json"
USAGE = STATE / "usage.csv"
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
IDEA_TARGET = 10          # the Scout runs Mon-Fri until this many ideas wait
MAX_ACTIVE = 2            # ideas in research at once (queued + planned + under review)
ACTIVE_STAGES = ("queued", "planned", "awaiting_review")
PER_DAY = 2               # Researcher / Skeptic runs per dispatch (one idea each)

# Frozen checkpoints of the live V2/V3/V4 tests (from their rules). Crossing one wakes the Scorekeeper.
CHECKPOINTS = {
    "V2 rank go/no-go (closed trades)": (r"go/no-go: COLLECTING \((\d+)/100", [100]),
    "V3 G2 forward (days)": (r"\[G2 forward\] (\d+) days", [40]),
    "V3 ON1 forward (days)": (r"\[ON1 forward\] (\d+) days", [40]),
    "V3 G2 paper (days)": (r"\[G2 paper\] (\d+) days", [20, 40]),
    "V3 ON1 paper (days)": (r"\[ON1 paper\] (\d+) days", [20, 40]),
    "V4 EPRE (closed trades)": (r"\[EPRE paper\] closed (\d+)", [1000, 3000, 6000]),   # void trades never count
}


def metrics(snapshot: str) -> dict[str, int]:
    out = {}
    for name, (rx, _) in CHECKPOINTS.items():
        m = re.search(rx, snapshot)
        if m:
            g = [int(x) for x in m.groups()]
            out[name] = g[0] - g[1] if len(g) == 2 else g[0]
    return out


def crossed(prev: dict[str, int], cur: dict[str, int]) -> list[str]:
    hits = []
    for name, val in cur.items():
        before = prev.get(name)
        for level in CHECKPOINTS[name][1]:
            if before is not None and before < level <= val:
                hits.append(f"{name} reached {level} (now {val})")
    return hits


def runs_this_week() -> int:
    if not USAGE.exists():
        return 0
    monday = (now_pt().date() - timedelta(days=now_pt().weekday())).isoformat()
    # The Quote Clerk has its own cap (tools/quotes.py) - its fixed-time runs must not crowd out the team's.
    # A run refused at once by the plan limit (0-1 turns, no tokens) is not a run.
    return sum(1 for line in USAGE.read_text(encoding="utf-8").splitlines()[1:]
               if line[:10] >= monday and ",quote_clerk," not in line
               and not (line.endswith(",limited") and line.split(",")[3] in ("", "0", "1")))


def in_stage(stage: str) -> list[str]:
    return [r["id"] for r in ideas.load() if r["stage"] == stage]


def open_items(stage: str) -> int:
    return len(in_stage(stage))


def research_work() -> str | None:
    """The next idea the Researcher should work on: fix a broken plan first, then the oldest queued."""
    for iid in in_stage("planned") + in_stage("queued"):
        d = TEAM / "research" / iid
        for f in ("train_error.txt", "plan_problems.txt"):
            if (d / f).exists():
                return f"FIX {iid}: {f} says: " + (d / f).read_text(encoding="utf-8", errors="replace")[-400:]
    for iid in in_stage("queued"):
        if not (TEAM / "research" / iid / "plan.json").exists():
            return f"RESEARCH {iid} (write its plan, test and strategy)"
    return None


def review_work() -> str | None:
    todo = [i for i in in_stage("awaiting_review") if not (TEAM / "research" / i / "skeptic.json").exists()]
    return f"REVIEW {todo[0]}" + (f" (+{len(todo) - 1} more waiting)" if len(todo) > 1 else "") if todo else None


def triggers(today: date, f: ops_monitor.Findings, hits: list[str], paper: dict, prev_paper: dict) -> dict[str, str]:
    """role -> why it should run today. Empty dict = a quiet day with zero Claude usage."""
    day = DAYS[today.weekday()]
    want: dict[str, str] = {}
    verdicts = [f"{sid} verdict {s.get('verdict')}" for sid, s in paper.items()
                if s.get("verdict") in ("PASS", "FAIL", "ERROR")
                and prev_paper.get(sid, {}).get("verdict") != s.get("verdict")]
    # Scorekeeper: diagnose real failures, report checkpoints, weekly scorecard on Friday.
    why = []
    if f.diagnose:
        why.append("diagnose: " + "; ".join(f.diagnose)[:600])
    if hits:
        why.append("checkpoint: " + "; ".join(hits))
    if day == "Fri":
        why.append("weekly scorecard")
    if why:
        want["scorekeeper"] = " | ".join(why)
    if day != "Sat" and open_items("idea") < IDEA_TARGET:
        want["scout"] = f"scouting ({open_items('idea')} ideas waiting, target {IDEA_TARGET})"
    director = (["weekly review"] if day == "Sat" else []) + verdicts
    if open_items("holdout_done"):
        director.append(f"decide on holdout passes: {', '.join(in_stage('holdout_done'))}")
    active = sum(open_items(s) for s in ACTIVE_STAGES)
    if day != "Sat" and open_items("idea") and active < MAX_ACTIVE:
        director.append(f"pipeline has room ({active}/{MAX_ACTIVE} in research) with {open_items('idea')} "
                        f"idea(s) waiting - queue up to {MAX_ACTIVE - active}")
    if director:
        want["director"] = "; ".join(director)
    if day == "Sat":
        want["auditor"] = "weekly audit of the whole project"
    # Researcher and Skeptic are re-checked after the Director (it may queue work) - see main().
    return want


def write_context(today: date, f: ops_monitor.Findings, hits: list[str], paper: dict, want: dict,
                  pipeline: list[str]) -> None:
    lines = [f"# Team context for {today} ({DAYS[today.weekday()]}) - written by the dispatcher", "",
             "## Why you were woken"] + [f"- {r}: {w}" for r, w in want.items()] + [
             "", "## Research pipeline moves today (tools/jobs.py)"] + [f"- {p}" for p in pipeline or ["none"]] + [
             "", "## Ideas by stage (python tools/ideas.py list)"] + [
             f"- {s}: {', '.join(in_stage(s))}" for s in ideas.STAGES if in_stage(s)] + [
             "", "## Ops alerts (already posted to #agent-ops - don't re-alert)"] + [f"- {a}" for a in f.alerts or ["none"]] + [
             "", "## To diagnose"] + [f"- {d}" for d in f.diagnose or ["none"]] + [
             "", "## Checkpoints crossed today"] + [f"- {h}" for h in hits or ["none"]] + [
             "", "## Team paper tests (tools/paper_runner.py)", "```", json.dumps(paper, indent=1), "```",
             "", "## Trial budget (tools/budget.py)", "```"]
    tot = budget.totals()
    lines += [f"{k}: {v}" for k, v in tot.items()] + ["```", "",
              "Full V2/V3/V4 numbers: state/snapshot.txt (from snapshot.py - the only valid source).",
              "What data research can use, and each family's used periods: state/data_catalog.md.",
              "ON1 / EPRE at real Webull bid/ask (Quote Clerk, rules in team/real_price_rules.json): "
              "paper/on1_real_price_status.json, paper/epre_real_price_status.json.",
              "Every scan's schedule and health (Scan Operator): team/schedule.json, state/scan_ops.json "
              "(`issues` = jobs that failed and could not be re-run validly this week)."]
    (STATE / "context.md").write_text("\n".join(lines), encoding="utf-8")


def write_audit_pack(today: date) -> None:
    """What the Auditor can't get itself (it has no git): the week's commits, Claude runs and role statuses."""
    since = (today - timedelta(days=8)).isoformat()
    usage = [l for l in (USAGE.read_text(encoding="utf-8").splitlines()[1:] if USAGE.exists() else [])
             if l[:10] >= since]
    lines = [f"# Audit pack for {today} - written by the dispatcher", "",
             f"## Commits since {since} (order proves plan-before-results)", "```",
             git("log", f"--since={since}", "--date=format:%Y-%m-%d %H:%M", "--format=%h %ad %s") or "none", "```",
             "", "## Claude runs (state/usage.csv: date,role,model,turns,minutes,cost_equiv_usd,status)", "```"]
    lines += usage or ["none"]
    lines += ["```", "", "## Last run per role (state/role_runs.json)", "```",
              json.dumps(load_json(STATE / "role_runs.json", {}), indent=1), "```", "",
              "Raw transcripts of each run: state/logs/<date>-<role>.json (refused commands show there)."]
    (STATE / "audit_pack.md").write_text("\n".join(lines), encoding="utf-8")


def claude_env() -> dict[str, str]:
    """A child of a Claude session inherits CLAUDE*/ANTHROPIC* vars that break a fresh headless login."""
    return {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "ANTHROPIC"))}


def run_role(role: str, cfg: dict, reason: str, today: date, dry_run: bool) -> dict:
    out_file = OUTBOX / f"{role}.txt"
    prompt = (f"Today is {today}. You are the team's {role.upper()}. Read TEAM.md, then prompts/common.md, "
              f"then prompts/{role}.md, and follow them exactly. Why you were woken: {reason}")
    cmd = [shutil.which("claude") or "claude", "-p", prompt, "--permission-mode", "dontAsk",
           "--settings", str(TEAM / "team" / "settings" / f"{role}.json"),
           "--model", cfg["model"], "--effort", cfg.get("effort", "medium"),
           "--max-turns", str(cfg["max_turns"]), "--output-format", "json",
           "--add-dir", str(LIVE_V2), str(LIVE_V3), str(LIVE_V4), "-n", f"team-{role}-{today}"]
    if dry_run:
        print("[dry-run] would launch:", role, "|", reason)
        return {"status": "dry_run"}
    start = time.time()
    stdout = ""
    try:
        r = subprocess.run(cmd, cwd=TEAM, env=claude_env(), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=cfg["timeout_min"] * 60)
        stdout, raw = r.stdout, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        raw = f"TIMEOUT after {cfg['timeout_min']} min"
    (STATE / "logs" / f"{today}-{role}.json").write_text(raw, encoding="utf-8")
    try:
        res = json.loads(stdout) if stdout.strip().startswith("{") else {}
    except json.JSONDecodeError:
        res = {}
    new_usage = not USAGE.exists()
    with open(USAGE, "a", encoding="utf-8") as fh:
        if new_usage:
            fh.write("date,role,model,turns,minutes,cost_equiv_usd,status\n")
        # A finished run (outbox written) is ok whatever its text says; only an unfinished one is checked for
        # a lost login (a bare "401" matched normal output once and raised a false LOGGED OUT alarm).
        finished = out_file.exists() and out_file.stat().st_mtime > start
        status = ("ok" if finished else
                  "logged_out" if re.search(r"Not logged in|Please run /login|authentication_error|OAuth token", raw)
                  else "limited" if plan_limit.is_limited(raw, res) else "failed")
        fh.write(f"{today},{role},{cfg['model']},{res.get('num_turns', '')},{(time.time() - start) / 60:.1f},"
                 f"{res.get('total_cost_usd', '')},{status}\n")
    if status == "limited":   # hold() posts one message for all the roles held back - no per-role alarm
        resets = plan_limit.reset_time(raw, now_pt())
        log(f"{role} hit the Claude plan limit; resets {resets:%m-%d %H:%M}", "dispatch")
        return {"status": status, "date": str(today), "note": raw[-300:], "resets_at": resets.isoformat()}
    if status == "ok":
        channel = cfg["channel"]
        if role == "scorekeeper" and reason.startswith("diagnose") and "checkpoint" not in reason \
                and "weekly" not in reason:
            channel = "ops"
        post(channel, out_file.read_text(encoding="utf-8"), cfg["username"])
    else:
        why = ("Claude is LOGGED OUT - open Claude Code on the computer and log in."
               if status == "logged_out" else f"no report written - see state/logs/{today}-{role}.json")
        post("ops", f"🔴 Team role **{role}** did not finish ({today}): {why}", "Team - Ops Monitor")
    return {"status": status, "date": str(today), "note": raw[-300:] if status != "ok" else ""}


def ran_ok_today(role: str, today: date) -> int:
    if not USAGE.exists():
        return 0
    return sum(1 for line in USAGE.read_text(encoding="utf-8").splitlines()[1:]
               if line.startswith(f"{today},{role},") and line.endswith(",ok"))


def run_roles(today: date, a, cfg: dict, want: dict[str, str], f: ops_monitor.Findings, hits: list[str],
              paper: dict, pipeline: list[str]) -> dict:
    """5. the Claude roles, in order. Returns {"roles": role -> why, "resets_at": iso} for the roles a Claude
    plan limit held back (empty roles = everything that had work ran). After the first limited run nothing
    else is launched - those roles wait for the reset (tools/plan_limit.py)."""
    limit: dict = {"roles": {}, "resets_at": None}
    cap = int(cfg.get("weekly_claude_run_cap", 12))
    role_runs = load_json(STATE / "role_runs.json", {})

    def launch(role: str, why: str, again: bool = False) -> None:
        if limit["roles"]:
            limit["roles"].setdefault(role, why)
            return
        if not cfg["roles"].get(role, {}).get("enabled") and role not in a.force:
            return
        last = role_runs.get(role, {})
        if last.get("date") == str(today) and last.get("status") == "ok" and role not in a.force and not again \
                and role not in ("researcher", "skeptic"):   # those two work per idea, not per day
            log(f"{role} already ran OK today - not relaunched", "dispatch")
            return
        # Exempt: the Auditor (heavy usage is exactly what it should flag) and the Director's Saturday weekly
        # review - one run each a week, and a busy Friday must not be able to crowd them out.
        weekly = role == "auditor" or (role == "director" and "weekly review" in why)
        if not a.dry_run and runs_this_week() >= cap and role not in a.force and not weekly:
            post("ops", f"⚠️ Weekly Claude run cap ({cap}) reached - skipped {role}: {why}", "Team - Ops Monitor")
            return
        write_context(today, f, hits, paper, {role: why}, pipeline)
        role_runs[role] = run_role(role, cfg["roles"][role], why, today, a.dry_run)
        if not a.dry_run:
            save_json(STATE / "role_runs.json", role_runs)
            commit(f"team-runner: {role} {today} ({why[:80]})")
        if role_runs[role]["status"] == "limited":
            limit["roles"][role] = why
            limit["resets_at"] = role_runs[role]["resets_at"]

    # 5. roles. Scout before Director (so it sees today's ideas); Director before Researcher (it may queue one).
    for role in ("scorekeeper", "scout", "director"):
        if role in want:
            launch(role, want[role])
    # Researcher writes a plan -> committed above -> train run -> Skeptic -> holdout, all in this dispatch.
    # Up to PER_DAY ideas each; stop early if the same work comes back (the run didn't move it).
    def research() -> None:
        for role, work in (("researcher", research_work), ("skeptic", review_work)):
            done: list[str] = []
            for _ in range(max(0, PER_DAY - ran_ok_today(role, today))):
                why = work() or (want.get(role) if not done else None)
                if not why or why in done:
                    break
                done.append(why)
                launch(role, why)
                pipeline.extend(jobs.advance(a.dry_run))
                if a.dry_run or limit["roles"]:
                    break

    active_before = sum(open_items(s) for s in ACTIVE_STAGES)
    research()
    # Refill: when this dispatch's Skeptic/holdouts closed ideas, the Director queues more NOW and the new ones
    # get today's remaining Researcher slots - instead of the pipeline sitting empty until tomorrow.
    active = sum(open_items(s) for s in ACTIVE_STAGES)
    if (DAYS[today.weekday()] != "Sat" and not a.dry_run and active < active_before and active < MAX_ACTIVE
            and open_items("idea")):
        launch("director", f"refill: research just closed {active_before - active} idea(s) - pipeline has room "
                           f"({active}/{MAX_ACTIVE}) with {open_items('idea')} idea(s) waiting - queue up to "
                           f"{MAX_ACTIVE - active}", again=True)
        research()
    # Auditor last, so it sees everything the other roles did today.
    if "auditor" in want:
        write_audit_pack(today)
        launch("auditor", want["auditor"])
    return limit


def _clock(at: datetime) -> str:
    return f"{at:%I:%M %p}".lstrip("0") + ("" if at.date() == now_pt().date() else f" {at:%a %m-%d}")


def hold(today: date, limit: dict, attempts: int) -> None:
    """The plan limit stopped the roles: save what is left and start the waiter that runs it at the reset."""
    roles, at = limit["roles"], datetime.fromisoformat(limit["resets_at"])
    if attempts >= plan_limit.MAX_ATTEMPTS:
        plan_limit.clear()
        post("ops", f"🛑 The Claude plan limit stopped the team {attempts + 1} times today - giving up until the "
                    f"next dispatch. Not run: {', '.join(roles)}", "Team - Ops Monitor")
        return
    plan_limit.save(str(today), at, roles, attempts)
    try:
        plan_limit.spawn(wait=True)
        how = "they start on their own then"
    except Exception as e:  # noqa: BLE001 - the Scan Operator tick is the backup
        log(f"resume waiter did not start: {e}", "dispatch")
        how = "the Scan Operator starts them then (the waiter did not start)"
    log(f"held by the plan limit until {at:%m-%d %H:%M}: {', '.join(roles)}", "dispatch")
    post("ops", f"⏸️ Claude plan limit reached (your plan's usage limit, not a bug). Still to run: "
                f"**{', '.join(roles)}** - the limit resets at {_clock(at)} and {how}.", "Team - Ops Monitor")


def resume(a) -> int:
    """Run the roles a plan limit held back (state/resume.json), once it has reset. Started by hold()'s
    detached waiter (--wait) or, as a backup, by the Scan Operator tick."""
    if a.wait and not plan_limit.wait_until_due():
        log("resume cancelled - nothing pending any more (a later dispatch took over)", "dispatch")
        return 0
    r = plan_limit.pending()
    if not r or not plan_limit.due(timedelta(0)) or not plan_limit.take_lock():
        return 0
    try:
        today = now_pt().date()
        log(f"resume start {today}: {', '.join(r['roles'])} (held since {r['date']}, attempt {r['attempts'] + 1})",
            "dispatch")
        if stopped():
            plan_limit.clear()
            post("ops", f"⏸️ Team is STOPped - held roles not resumed: {', '.join(r['roles'])}", "Team - Ops Monitor")
            return 0
        # The roles see what they would have seen at the dispatch: its snapshot and paper status.
        f = ops_monitor.Findings()
        snap = STATE / "snapshot.txt"
        f.snapshot = snap.read_text(encoding="utf-8") if snap.exists() else ""
        paper = load_json(STATE / "paper_status.json", {})
        pipeline: list[str] = []
        limit = run_roles(today, a, load_json(ROLES, {"roles": {}}), r["roles"], f, [], paper, pipeline)
        write_context(today, f, [], paper, {}, pipeline)
        if limit["roles"]:
            hold(today, limit, attempts=r["attempts"] + 1)
        else:
            plan_limit.clear()
            post("ops", "▶️ **Team resumed after the Claude plan limit reset**\n"
                        + "\n".join(daily_report.team_today(today, pipeline)), "Team - Daily Report")
        log(f"resume done; pipeline: {pipeline or 'no moves'}", "dispatch")
        return 0
    finally:
        plan_limit.drop_lock()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-claude", action="store_true")
    ap.add_argument("--force", action="append", default=[], help="run this role regardless of triggers")
    ap.add_argument("--resume", action="store_true", help="run the roles a Claude plan limit held back")
    ap.add_argument("--wait", action="store_true", help="with --resume: sleep until the limit resets first")
    a = ap.parse_args(argv)
    if a.resume:
        return resume(a)
    if a.dry_run:
        os.environ["TEAM_DRY_RUN"] = "1"
    today = now_pt().date()
    log(f"dispatch start {today} dry_run={a.dry_run} stop={stopped()}", "dispatch")
    if today.weekday() == 6:
        log("Sunday - nothing scheduled", "dispatch")
        return 0

    # 1. paper runner (evaluates even when STOPped; STOP only blocks new signals)
    prev_paper = load_json(STATE / "paper_status.json", {})
    paper = {} if today.weekday() == 5 else paper_runner.run(today, dry_run=a.dry_run)
    if not a.dry_run:
        commit(f"team-runner: paper {today}")

    # 1a. ON1 re-priced at the Quote Clerk's real bid/ask (tools/quotes.py) - read by the Scorekeeper/Director.
    if not a.dry_run:
        for name, job in (("on1 real-price", quotes.on1), ("epre real-price", quotes.epre),
                          ("scan operator", scan_ops.run)):
            try:
                log(f"{name}: {job()}", "dispatch")
            except Exception as e:
                log(f"{name} failed: {e}", "dispatch")

    # 1b. research data: EDGAR filings (daily, only companies that filed), splits + daily bars (Saturday),
    #     data catalog.
    #     Plain Python, zero tokens. A failure is reported, never fatal - research can use yesterday's archive.
    #     The bulk event screen (tools/screen.py) re-runs itself every 4 weeks; the catalog then shows its periods.
    if not a.dry_run:
        for name, job in [("edgar update", edgar.update)] + ([("edgar splits", edgar.splits),
                                                               ("daily bars", daily_bars.run)]
                                                              if today.weekday() == 5 else []) + [
                ("screen", screen.run), ("fill costs", fill_costs.write), ("catalog", catalog.write)]:
            try:
                log(job(), "dispatch")
            except Exception as e:
                log(f"{name} failed: {e}", "dispatch")
                post("ops", f"⚠️ Team data refresh **{name}** failed: {str(e)[:300]}", "Team - Ops Monitor")
        commit(f"team-runner: data refresh {today}")

    # 2. ops (script only; Saturday has no market tasks worth a heartbeat)
    f = ops_monitor.run(dry_run=a.dry_run, post_it=today.weekday() < 5)
    pipeline: list[str] = []
    # 6. the end-of-day report (tools/daily_report.py) - in `finally`, so a crashed role can't swallow it
    try:
        state = load_json(STATE / "dispatch_state.json", {})
        cur = metrics(f.snapshot)
        hits = crossed(state.get("metrics", {}), cur)
        for sid, s in paper.items():
            if s.get("verdict") in ("PASS", "FAIL") and prev_paper.get(sid, {}).get("verdict") != s["verdict"]:
                post("director", f"📌 Team paper test **{sid}** reached its rule verdict: **{s['verdict']}** "
                                 f"({s['days']} days, mean {s['mean_bps']} bps, t {s['t']})", "Team - Paper Runner")

        # 3. research pipeline, script part (train runs, Skeptic verdicts, holdouts) - no Claude
        pipeline = [] if stopped() else jobs.advance(a.dry_run)

        # 4. triggers. A resume still pending from an earlier limit is superseded: today's run covers it.
        if not a.dry_run and plan_limit.pending():
            log(f"superseding a pending resume: {plan_limit.pending()['roles']}", "dispatch")
            plan_limit.clear()
        cfg = load_json(ROLES, {"roles": {}})
        want = triggers(today, f, hits, paper, prev_paper)
        for r in a.force:
            want.setdefault(r, "forced by hand")
        if not a.dry_run:
            save_json(STATE / "dispatch_state.json", {"metrics": cur, "date": str(today)})

        paused = stopped() or a.no_claude
        if paused:
            if want and stopped():
                post("ops", f"⏸️ Team is STOPped (delete the STOP file to resume). Skipped: {', '.join(want)}",
                     "Team - Ops Monitor", a.dry_run)
            write_context(today, f, hits, paper, {}, pipeline)
            log("paused - no Claude roles", "dispatch")
            return 0
        limit = run_roles(today, a, cfg, want, f, hits, paper, pipeline)
        if limit["roles"]:
            hold(today, limit, attempts=0)
        write_context(today, f, hits, paper, {}, pipeline)
        log(f"dispatch done; pipeline: {pipeline or 'no moves'}", "dispatch")
        return 0
    finally:
        if today.weekday() < 5:
            try:
                daily_report.send(today, f, pipeline, a.dry_run)
            except Exception as e:  # noqa: BLE001
                log(f"daily report failed: {e}", "dispatch")
                post("ops", f"⚠️ Daily report could not be built: {str(e)[:300]}", "Team - Ops Monitor", a.dry_run)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
