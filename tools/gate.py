"""Promotion gate - the ONLY code that changes strategies/registry.json. Agents are denied editing it.

    python tools/gate.py check <id>                    # print every requirement, PASS/FAIL
    python tools/gate.py promote <id> --reason "..."   # start a paper test (only if check passes)
    python tools/gate.py retire <id> --reason "..."    # stop a paper test (rule FAIL, or Director reason)
    python tools/gate.py list

A strategy may start paper trading only if ALL of these hold (TEAM.md "Hard limits"):
  1. research/<id>/PLAN.md was committed BEFORE any result file in research/<id>/ (git history -
     only the dispatcher commits, so the order can't be faked by an agent);
  2. research/<id>/skeptic.json says {"verdict": "PASS"} (written by the Skeptic role only);
  3. research/<id>/holdout_result.json exists, runs == 1, and its t clears the trial-budget bar for its family;
  4. strategies/<id>/strategy.py + spec.json exist, spec has a complete frozen rule, and a smoke test
     (signals on the last 5 sessions, truncated data) runs without error;
  5. fewer than max_active (registry, default 5) paper tests are active;
  6. the team isn't STOPped.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, datetime

import budget
from common import TEAM, git, load_json, now_pt, post, save_json, stopped

REGISTRY = TEAM / "strategies" / "registry.json"
DECISIONS = TEAM / "registry" / "decisions.csv"
RULE_KEYS = ("min_days", "max_days", "pass_mean_bps", "pass_t")
RESULT_FILES = ("train_result.json", "skeptic.json", "holdout_result.json")


def first_commit(path) -> str | None:
    """Hash of the commit that first added `path`."""
    out = git("log", "--diff-filter=A", "--format=%H", "--", str(path.relative_to(TEAM)).replace("\\", "/"))
    lines = [x for x in out.splitlines() if x.strip()]
    return lines[-1] if lines else None


def strictly_before(a: str, b: str) -> bool:
    """Commit a is an ancestor of commit b and not the same commit (order, not clock time)."""
    if a == b:
        return False
    r = subprocess.run(["git", "merge-base", "--is-ancestor", a, b], cwd=TEAM, capture_output=True)
    return r.returncode == 0


def checks(sid: str, smoke: bool = True) -> list[tuple[str, bool, str]]:
    res = TEAM / "research" / sid
    strat = TEAM / "strategies" / sid
    out: list[tuple[str, bool, str]] = []

    plan_t = first_commit(res / "PLAN.md") if (res / "PLAN.md").exists() else None
    result_ts = [(f, first_commit(res / f)) for f in RESULT_FILES if (res / f).exists()]
    early = [f for f, t in result_ts if t is None or plan_t is None or not strictly_before(plan_t, t)]
    out.append(("plan committed before results", bool(plan_t) and not early,
                f"plan {plan_t[:8] if plan_t else 'NOT COMMITTED'}" + (f"; not after plan: {early}" if early else "")))

    sk = load_json(res / "skeptic.json", {})
    out.append(("skeptic PASS", sk.get("verdict") == "PASS", sk.get("verdict", "no skeptic.json")))

    ho = load_json(res / "holdout_result.json", {})
    spec = load_json(strat / "spec.json", {})
    fam = spec.get("family", "")
    bar = budget.holdout_bar(fam, extra=0) if fam else budget.FLOOR_T
    ok_ho = ho.get("runs") == 1 and float(ho.get("t", 0)) >= bar and float(ho.get("mean_bps", 0)) > 0
    out.append(("holdout passed once, clears budget bar", ok_ho,
                f"t {ho.get('t', '-')} vs bar {bar:.2f} (family {fam or '?'}), runs {ho.get('runs', 0)}"))

    rule = spec.get("rule", {})
    ok_spec = (strat / "strategy.py").exists() and all(k in rule for k in RULE_KEYS) and "cost_bps" in spec
    out.append(("strategy + frozen rule", ok_spec, f"rule keys {sorted(rule)}"))
    if smoke and ok_spec:
        out.append(smoke_test(sid))

    reg = load_json(REGISTRY, {"strategies": {}})
    active = sum(m.get("status") == "active" for m in reg["strategies"].values())
    cap = int(reg.get("max_active", 5))
    out.append(("active slot free", active < cap, f"{active}/{cap} active"))
    out.append(("team not stopped", not stopped(), "STOP file present" if stopped() else "ok"))
    return out


def smoke_test(sid: str) -> tuple[str, bool, str]:
    import paper_runner as pr
    try:
        mod, spec = pr.load_strategy(sid)
        uni = list(mod.universe())
        today = datetime.now().date()
        bars = pr.download(uni, today)
        sessions = sorted(bars["SPY"].index)[-5:]
        n = 0
        for d in sessions:
            n += len(pr.validate_signals(mod.signals(d, pr.truncate(bars, d)), set(uni), 10_000))
        return ("smoke test (5 sessions)", True, f"{len(uni)} tickers, {n} signals")
    except Exception as e:  # noqa: BLE001
        return ("smoke test (5 sessions)", False, repr(e)[:300])


def log_decision(action: str, sid: str, reason: str) -> None:
    new = not DECISIONS.exists()
    DECISIONS.parent.mkdir(parents=True, exist_ok=True)
    with open(DECISIONS, "a", encoding="utf-8", newline="") as f:
        if new:
            f.write("time,action,strategy,reason\n")
        f.write(f"{now_pt():%Y-%m-%d %H:%M},{action},{sid},\"{reason.replace(chr(34), chr(39))}\"\n")


def promote(sid: str, reason: str) -> int:
    res = checks(sid)
    for name, ok, why in res:
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {why}")
    if not all(ok for _, ok, _ in res):
        print("NOT PROMOTED")
        return 1
    reg = load_json(REGISTRY, {"max_active": 5, "strategies": {}})
    spec = load_json(TEAM / "strategies" / sid / "spec.json", {})
    import ideas
    import paper_runner
    reg["strategies"][sid] = {"status": "active", "family": spec.get("family"), "started": str(date.today()),
                              "reason": reason, "fingerprint": paper_runner.fingerprint(sid)}
    if ideas.get(sid):
        ideas.set_stage(sid, "paper", "paper test started via gate")
    save_json(REGISTRY, reg)
    budget.append({"date": str(date.today()), "idea_id": sid, "family": spec.get("family"), "stage": "paper",
                   "variants": 1, "verdict": "started", "note": reason[:200]})
    log_decision("promote", sid, reason)
    post("director", f"🟢 **Paper test started: {sid}**\n{reason}\nRule: {spec.get('rule')}", "Team - Director")
    print("PROMOTED")
    return 0


def retire(sid: str, reason: str) -> int:
    reg = load_json(REGISTRY, {"strategies": {}})
    if reg["strategies"].get(sid, {}).get("status") != "active":
        print(f"{sid} is not an active paper test")
        return 1
    status = load_json(TEAM / "paper" / f"{sid}_status.json", {})
    reg["strategies"][sid].update(status="retired", retired=str(date.today()), retire_reason=reason,
                                  final=status)
    save_json(REGISTRY, reg)
    import ideas
    if ideas.get(sid):
        ideas.set_stage(sid, "passed" if status.get("verdict") == "PASS" else "dead", f"retired: {reason}")
    log_decision("retire", sid, reason)
    post("director", f"⚪ **Paper test stopped: {sid}** - {reason}\nFinal: {status}", "Team - Director")
    print("RETIRED")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["check", "promote", "retire", "list"])
    ap.add_argument("sid", nargs="?")
    ap.add_argument("--reason", default="")
    a = ap.parse_args(argv)
    if a.action == "list":
        for sid, m in load_json(REGISTRY, {"strategies": {}})["strategies"].items():
            print(sid, m.get("status"), m.get("started"), m.get("family"))
        return 0
    if not a.sid:
        ap.error("strategy id required")
    if a.action == "check":
        res = checks(a.sid)
        for name, ok, why in res:
            print(f"{'PASS' if ok else 'FAIL'}  {name}: {why}")
        return 0 if all(ok for _, ok, _ in res) else 1
    if not a.reason:
        ap.error("--reason is required (it is posted to #agent-director)")
    return promote(a.sid, a.reason) if a.action == "promote" else retire(a.sid, a.reason)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
