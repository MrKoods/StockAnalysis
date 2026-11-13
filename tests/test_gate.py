"""The promotion gate (tools/gate.py) - the only writer of strategies/registry.json - had no tests until the
2026-11-13 audit. Each check is exercised in a throwaway git repo, because "plan committed before results" is
proven by commit order."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import budget  # noqa: E402
import gate  # noqa: E402

SID = "idea-x"
RULE = {"min_days": 20, "max_days": 40, "pass_mean_bps": 5, "pass_t": 2, "metric": "real_bps"}


def sh(repo, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True,
                   capture_output=True)


def commit(repo, msg):
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", msg)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    sh(tmp_path, "init", "-q")
    monkeypatch.setattr(gate, "TEAM", tmp_path)
    monkeypatch.setattr(gate, "REGISTRY", tmp_path / "strategies" / "registry.json")
    monkeypatch.setattr(gate, "git", lambda *a: subprocess.run(["git", *a], cwd=tmp_path, capture_output=True,
                                                               text=True).stdout.strip())
    monkeypatch.setattr(gate, "stopped", lambda: False)
    monkeypatch.setattr(budget, "TRIALS", tmp_path / "trials.csv")      # no holdouts yet: bar = 3.0
    return tmp_path


def build(repo, plan_family="fam", spec_family="fam", holdout_t=3.5, runs=1, skeptic="PASS",
          results_first=False):
    res, strat = repo / "research" / SID, repo / "strategies" / SID
    res.mkdir(parents=True)
    strat.mkdir(parents=True)

    def results():
        (res / "train_result.json").write_text("{}")
        (res / "skeptic.json").write_text(json.dumps({"verdict": skeptic}))
        (res / "holdout_result.json").write_text(json.dumps({"runs": runs, "t": holdout_t, "mean_bps": 30}))
        commit(repo, "results")

    if results_first:
        results()
    (res / "PLAN.md").write_text("plan")
    (res / "plan.json").write_text(json.dumps({"family": plan_family}))
    commit(repo, "plan")
    if not results_first:
        results()
    (strat / "strategy.py").write_text("x = 1")
    (strat / "spec.json").write_text(json.dumps({"family": spec_family, "rule": RULE, "cost_bps": 10}))
    commit(repo, "strategy")


def verdicts(repo):
    return {name: ok for name, ok, _ in gate.checks(SID, smoke=False)}


def test_clean_case_passes_every_check(repo):
    build(repo)
    assert all(verdicts(repo).values()), verdicts(repo)


def test_results_committed_before_the_plan_fail(repo):
    build(repo, results_first=True)
    assert verdicts(repo)["plan committed before results"] is False


def test_holdout_below_bar_or_looked_at_twice_fails(repo):
    build(repo, holdout_t=2.9)
    assert verdicts(repo)["holdout passed once, clears budget bar"] is False


def test_second_holdout_look_fails(repo):
    build(repo, runs=2)
    assert verdicts(repo)["holdout passed once, clears budget bar"] is False


def test_skeptic_fail_blocks(repo):
    build(repo, skeptic="FAIL")
    assert verdicts(repo)["skeptic PASS"] is False


def test_spec_cannot_pick_a_different_family(repo):
    build(repo, spec_family="fresh_family")      # a family with no holdouts would mean a lower bar
    assert verdicts(repo)["spec family = plan family"] is False


def test_promote_refuses_and_writes_nothing_when_a_check_fails(repo, monkeypatch):
    monkeypatch.setattr(gate, "smoke_test", lambda sid: ("smoke test (5 sessions)", True, "ok"))
    build(repo, skeptic="FAIL")
    assert gate.promote(SID, "test") == 1
    assert not gate.REGISTRY.exists()
