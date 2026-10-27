"""Research job runner + Holdout Keeper - scripts, no Claude. Called by the dispatcher.

    python tools/jobs.py advance [--dry-run]     # move every idea along the pipeline from the files on disk
    python tools/jobs.py check <id>              # validate a plan + static-scan its test script, run nothing

Pipeline moves made here (TEAM.md):
  queued  + committed plan.json/PLAN.md/test.py  -> planned
  planned -> TRAIN run (data cut at train_end)    -> awaiting_review   (crash: stays planned, train_error.txt)
  awaiting_review + skeptic.json PASS/FAIL        -> skeptic_pass / dead
  skeptic_pass -> HOLDOUT run, exactly once       -> holdout_done / dead
The test script never computes its own statistics: it returns per-trade GROSS bps, the harness subtracts the
plan's cost and clusters by day or week.

research/<id>/plan.json:
  {"family", "train_start", "train_end", "holdout_start", "holdout_end", "cost_bps", "cluster": "day"|"week",
   "max_variants", "metric": "raw"|"hedged"}
research/<id>/test.py:
  def run(start: str, end: str, phase: "train"|"holdout", chosen: str|None) -> dict
      {"variants": <int, configs evaluated>, "chosen": <config name to carry to the holdout (train only)>,
       "trades": {config_name: DataFrame/list of {"date": exit date, "gross_bps": float}}}
  In the holdout phase evaluate ONLY `chosen`.  Data ONLY via `import research_data as rd`.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
from datetime import date, timedelta

import budget
import ideas
from common import PYTHON, TEAM, commit, git, load_json, log, post, save_json

RESEARCH = TEAM / "research"
TIMEOUT_MIN = 45
PLAN_KEYS = ("family", "train_start", "train_end", "holdout_start", "holdout_end", "cost_bps", "cluster",
             "max_variants")
# Research scripts reach data only through research_data (which enforces the cutoff). This is a guard
# against accidents, not a sandbox - the Skeptic reviews the code too.
FORBIDDEN = [r"\byfinance\b", r"\brequests\b", r"\burllib\b", r"\bhttp\b", r"\bsocket\b", r"\bsubprocess\b",
             r"\bos\.environ\b", r"\bputenv\b", r"read_parquet", r"read_csv", r"read_pickle", r"\bopen\(",
             r"StockAnalysis", r"\bimportlib\b", r"__import__", r"\beval\(", r"\bexec\(", r"\bPath\(",
             r"TEAM_DATA_END", r"\bshutil\b", r"\bpickle\b"]


def plan_problems(iid: str) -> list[str]:
    d = RESEARCH / iid
    p = load_json(d / "plan.json", None)
    probs = [f"missing {f}" for f in ("PLAN.md", "plan.json", "test.py") if not (d / f).exists()]
    if p is None:
        return probs or ["plan.json unreadable"]
    probs += [f"plan.json missing {k}" for k in PLAN_KEYS if k not in p]
    if probs:
        return probs
    try:
        ts, te, hs, he = (date.fromisoformat(p[k]) for k in ("train_start", "train_end", "holdout_start",
                                                             "holdout_end"))
    except ValueError as e:
        return [f"bad date in plan.json: {e}"]
    if not ts < te < hs <= he:
        probs.append("need train_start < train_end < holdout_start <= holdout_end")
    if he > date.today():
        probs.append("holdout_end is in the future")
    if p["cluster"] not in ("day", "week"):
        probs.append("cluster must be day or week")
    idea = ideas.get(iid)
    if idea and idea["family"] and p["family"] != idea["family"]:
        probs.append(f"plan family {p['family']} != idea family {idea['family']}")
    return probs + static_problems(d / "test.py")


def static_problems(path) -> list[str]:
    if not path.exists():
        return []
    code = path.read_text(encoding="utf-8", errors="replace")
    hits = [rx for rx in FORBIDDEN if re.search(rx, code)]
    return [f"test.py uses forbidden {h} - load data only via research_data" for h in hits]


# ---------- statistics (harness-owned) ----------

def stats(trades, cost_bps: float, cluster: str, start: str, end: str) -> dict:
    import pandas as pd
    df = pd.DataFrame(trades)
    if df.empty:
        return {"n_trades": 0, "n_periods": 0, "mean_bps": 0.0, "t": 0.0, "outside_window": 0}
    d = pd.to_datetime(df["date"])
    if d.dt.tz is not None:
        d = d.dt.tz_convert("America/New_York").dt.tz_localize(None)
    df["date"] = d
    inside = (df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))
    outside = int((~inside).sum())
    df = df[inside]
    df["net"] = df["gross_bps"].astype(float) - float(cost_bps)
    key = df["date"].dt.normalize() if cluster == "day" else df["date"].dt.to_period("W")
    per = df.groupby(key)["net"].mean()
    n = len(per)
    mean = float(per.mean()) if n else 0.0
    sd = float(per.std(ddof=1)) if n > 1 else 0.0
    t = mean / (sd / math.sqrt(n)) if sd > 0 else 0.0
    return {"n_trades": int(len(df)), "n_periods": n, "mean_bps": round(mean, 2), "t": round(t, 2),
            "trade_mean_bps": round(float(df["net"].mean()), 2) if len(df) else 0.0,
            "outside_window": outside}


def luck_t(n_variants: int) -> float:
    """Rough best-of-N t under no edge (independent tests): sqrt(2 ln N). Correlated variants => lower."""
    return round(math.sqrt(2 * math.log(n_variants)), 2) if n_variants > 1 else 0.0


# ---------- running a script (child process) ----------

def child(iid: str, phase: str) -> None:
    """Runs inside the subprocess with TEAM_DATA_END already set. Prints one JSON line."""
    sys.path.insert(0, str(TEAM / "tools"))
    plan = load_json(RESEARCH / iid / "plan.json", {})
    start, end = {"train": (plan["train_start"], plan["train_end"]),
                  "smoke": (plan["train_start"], os.environ["TEAM_DATA_END"]),
                  "holdout": (plan["holdout_start"], plan["holdout_end"])}[phase]
    chosen = (load_json(RESEARCH / iid / "train_result.json", {}).get("chosen") if phase == "holdout" else None)
    spec = importlib.util.spec_from_file_location(f"research_{iid}", RESEARCH / iid / "test.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = mod.run(start, end, "train" if phase == "smoke" else phase, chosen)
    trades = out.get("trades", {})
    res = {"phase": phase, "start": start, "end": end, "variants": int(out.get("variants", len(trades))),
           "chosen": out.get("chosen") if phase == "train" else chosen, "configs": {}}
    for name, tr in trades.items():
        if hasattr(tr, "to_dict"):
            tr = tr.to_dict("records")
        res["configs"][str(name)] = stats(tr, plan["cost_bps"], plan["cluster"], start, end)
    print("@@RESULT@@" + json.dumps(res, default=str))


def run_phase(iid: str, phase: str) -> tuple[dict | None, str]:
    plan = load_json(RESEARCH / iid / "plan.json", {})
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "ANTHROPIC"))}
    if phase == "smoke":  # first year of the train window only - can never reach the holdout
        first_year = date.fromisoformat(plan["train_start"]) + timedelta(days=365)
        env["TEAM_DATA_END"] = str(min(first_year, date.fromisoformat(plan["train_end"])))
    else:
        env["TEAM_DATA_END"] = plan["train_end"] if phase == "train" else plan["holdout_end"]
    try:
        r = subprocess.run([PYTHON, str(TEAM / "tools" / "jobs.py"), "_child", iid, phase], cwd=TEAM, env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=TIMEOUT_MIN * 60)
    except subprocess.TimeoutExpired:
        return None, f"timed out after {TIMEOUT_MIN} min"
    line = next((x for x in r.stdout.splitlines()[::-1] if x.startswith("@@RESULT@@")), None)
    if r.returncode or not line:
        return None, (r.stderr or r.stdout)[-2500:]
    return json.loads(line[len("@@RESULT@@"):]), ""


# ---------- pipeline ----------

def plan_hash(iid: str) -> str:
    import hashlib
    return hashlib.sha256((RESEARCH / iid / "plan.json").read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:16]


def plan_changed(iid: str) -> bool:
    """plan.lock is written when the plan is committed; windows/variants/costs may not move after that."""
    lock = RESEARCH / iid / "plan.lock"
    return lock.exists() and lock.read_text().strip() != plan_hash(iid)


def bury(iid: str, why: str) -> None:
    ideas.set_stage(iid, "dead", why)
    with open(TEAM / "registry" / "graveyard.md", "a", encoding="utf-8") as f:
        f.write(f"- **{iid}** ({date.today()}): {why}\n")
    post("research", f"⚰️ **{iid}** is dead: {why}", "Team - Research Pipeline")


def do_train(iid: str, dry_run: bool) -> None:
    d = RESEARCH / iid
    plan = load_json(d / "plan.json", {})
    res, err = (None, "dry run") if dry_run else run_phase(iid, "train")
    if res is None:
        if not dry_run:
            (d / "train_error.txt").write_text(err, encoding="utf-8")
            ideas.set_stage(iid, "planned", "train run FAILED - see train_error.txt (Researcher will fix)")
        log(f"train {iid}: {err[:300]}", "jobs")
        return
    (d / "train_error.txt").unlink(missing_ok=True)
    chosen = res.get("chosen")
    problems = []
    if res["variants"] > int(plan["max_variants"]):
        problems.append(f"{res['variants']} variants > plan max {plan['max_variants']}")
    if chosen not in res["configs"]:
        problems.append(f"chosen config {chosen!r} not among results")
    best = max(res["configs"].values(), key=lambda c: c["t"], default={"t": 0})
    res |= {"luck_t_best_of_n": luck_t(res["variants"]), "best_t": best["t"],
            "chosen_stats": res["configs"].get(chosen), "problems": problems}
    if len(res["configs"]) > 50:  # keep the file readable; top 50 by t
        res["configs"] = dict(sorted(res["configs"].items(), key=lambda kv: -kv[1]["t"])[:50])
    save_json(d / "train_result.json", res)
    budget.append({"date": str(date.today()), "idea_id": iid, "family": plan["family"], "stage": "search",
                   "variants": res["variants"], "data": f"{plan['train_start']}..{plan['train_end']}",
                   "result_t": (res.get("chosen_stats") or {}).get("t", ""),
                   "result_bps": (res.get("chosen_stats") or {}).get("mean_bps", ""), "note": "team train run"})
    ideas.set_stage(iid, "awaiting_review", f"train done: chosen {chosen} t {(res.get('chosen_stats') or {}).get('t')}")
    cs = res.get("chosen_stats") or {}
    post("research", f"🧪 **{iid}** train result: chosen `{chosen}` mean {cs.get('mean_bps')} bps, t {cs.get('t')} "
                     f"over {cs.get('n_periods')} {plan['cluster']}s; {res['variants']} variants "
                     f"(best-of-N luck t ~{res['luck_t_best_of_n']}). Skeptic reviews next.",
         "Team - Research Pipeline")


def do_holdout(iid: str, dry_run: bool) -> None:
    d = RESEARCH / iid
    if (d / "holdout_result.json").exists():   # the holdout is used exactly once - never re-run
        passed = load_json(d / "holdout_result.json", {}).get("passed")
        ideas.set_stage(iid, "holdout_done" if passed else "dead", "holdout already on file - not re-run")
        return
    plan = load_json(d / "plan.json", {})
    bar = budget.holdout_bar(plan["family"], extra=1)
    if dry_run:
        log(f"[dry-run] would run holdout {iid} (bar {bar:.2f})", "jobs")
        return
    # Record the attempt BEFORE running, so a crash still counts as the one look.
    save_json(d / "holdout_result.json", {"runs": 1, "status": "running", "bar": bar})
    res, err = run_phase(iid, "holdout")
    cs = (res or {}).get("configs", {}).get((res or {}).get("chosen"), {}) if res else {}
    passed = bool(res) and cs.get("t", 0) >= bar and cs.get("mean_bps", 0) > 0
    save_json(d / "holdout_result.json", {"runs": 1, "status": "done" if res else "crashed", "bar": round(bar, 2),
                                          "t": cs.get("t", 0), "mean_bps": cs.get("mean_bps", 0),
                                          "n_trades": cs.get("n_trades", 0), "n_periods": cs.get("n_periods", 0),
                                          "passed": passed, "chosen": (res or {}).get("chosen"),
                                          "error": err[-1500:] if err else ""})
    budget.append({"date": str(date.today()), "idea_id": iid, "family": plan["family"], "stage": "holdout",
                   "variants": 1, "data": f"{plan['holdout_start']}..{plan['holdout_end']}",
                   "result_t": cs.get("t", ""), "result_bps": cs.get("mean_bps", ""),
                   "verdict": "pass" if passed else "fail", "note": "team holdout (one look)"})
    if passed:
        ideas.set_stage(iid, "holdout_done", f"HOLDOUT PASS t {cs['t']} >= bar {bar:.2f}, {cs['mean_bps']} bps")
        post("research", f"🎯 **{iid}** PASSED its holdout: t {cs['t']} (bar {bar:.2f}), {cs['mean_bps']} bps net "
                         f"over {cs['n_periods']} {plan['cluster']}s. Director decides on a paper test.",
             "Team - Holdout Keeper")
    else:
        why = (f"holdout crashed (counts as the one look): {err[-200:]}" if not res else
               f"holdout FAIL: t {cs.get('t')} vs bar {bar:.2f}, {cs.get('mean_bps')} bps")
        bury(iid, why)


def advance(dry_run: bool = False) -> list[str]:
    """One pass over the pipeline. Returns a list of what happened (for the dispatcher's context)."""
    done = []
    for r in ideas.load():
        iid, stage = r["id"], r["stage"]
        d = RESEARCH / iid
        if stage == "queued" and (d / "plan.json").exists():
            probs = plan_problems(iid)
            committed = all(git("log", "--format=%H", "--", f"research/{iid}/{f}")
                            for f in ("plan.json", "PLAN.md", "test.py"))
            if probs:
                if not dry_run:
                    (d / "plan_problems.txt").write_text("\n".join(probs), encoding="utf-8")
                done.append(f"{iid}: plan has problems: {probs[:3]}")
            elif committed:
                (d / "plan_problems.txt").unlink(missing_ok=True)
                if not dry_run:
                    (d / "plan.lock").write_text(plan_hash(iid), encoding="utf-8")
                    ideas.set_stage(iid, "planned", "plan committed")
                stage = "planned"
        if stage in ("planned", "awaiting_review", "skeptic_pass") and plan_changed(iid):
            if not dry_run:
                bury(iid, "plan.json changed after it was committed (pre-registration broken)")
            done.append(f"{iid}: plan changed - dead")
            continue
        if stage == "planned" and not (d / "train_result.json").exists():
            probs = plan_problems(iid)
            if probs:
                done.append(f"{iid}: plan problems {probs[:3]}")
                continue
            do_train(iid, dry_run)
            done.append(f"{iid}: train run")
        elif stage == "awaiting_review" and (d / "skeptic.json").exists():
            v = load_json(d / "skeptic.json", {}).get("verdict")
            if v == "PASS":
                ideas.set_stage(iid, "skeptic_pass", "Skeptic PASS")
                stage = "skeptic_pass"
            elif v == "FAIL":
                bury(iid, "Skeptic FAIL: " + str(load_json(d / "skeptic.json", {}).get("summary", ""))[:300])
                done.append(f"{iid}: skeptic FAIL")
        if stage == "skeptic_pass":
            do_holdout(iid, dry_run)
            done.append(f"{iid}: holdout run")
    if done and not dry_run:
        commit("team-runner: research pipeline " + "; ".join(done)[:150])
    return done


def main(argv: list[str]) -> int:
    if argv[:1] == ["_child"]:
        child(argv[1], argv[2])
        return 0
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["advance", "check", "smoke"])
    ap.add_argument("iid", nargs="?")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.action in ("check", "smoke"):
        probs = plan_problems(a.iid)
        print("\n".join(probs) or "plan OK")
        if probs or a.action == "check":
            return 1 if probs else 0
        res, err = run_phase(a.iid, "smoke")   # Researcher's debug run: summary only, nothing saved
        if res is None:
            print("SMOKE RUN FAILED:\n" + err)
            return 1
        print(f"smoke OK ({res['start']}..{res['end']}): {res['variants']} variants, chosen {res['chosen']}")
        for name, c in list(res["configs"].items())[:5]:
            print(f"  {name}: {c['n_trades']} trades, {c['n_periods']} periods")
        return 0
    print("\n".join(advance(a.dry_run)) or "nothing to do")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
