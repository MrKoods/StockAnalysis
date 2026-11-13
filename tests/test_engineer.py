"""The Engineer's guard: what it refuses, and that a refusal really undoes the run (in a throwaway git repo)."""
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import daily_bars  # noqa: E402
import engineer  # noqa: E402


def sh(repo, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True,
                   capture_output=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for d in ("tools", "prompts", "tests", "registry"):
        (tmp_path / d).mkdir()
    (tmp_path / "tools" / "scan_ops.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "tools" / "gate.py").write_text("y = 1\n", encoding="utf-8")
    (tmp_path / "prompts" / "scout.md").write_text("Never touch the holdout.\nKeep it short.\n", encoding="utf-8")
    sh(tmp_path, "init", "-q")
    sh(tmp_path, "add", "-A")
    sh(tmp_path, "commit", "-q", "-m", "base")
    monkeypatch.setattr(engineer, "TEAM", tmp_path)
    monkeypatch.setattr(engineer, "RECORD", tmp_path / "registry" / "engineer_log.csv")
    monkeypatch.setattr(engineer, "STATEF", tmp_path.parent / f"{tmp_path.name}-engineer.json")   # outside the repo
    monkeypatch.setattr(engineer, "post", lambda *a, **k: True)
    monkeypatch.setattr(engineer, "log", lambda *a, **k: None)
    return tmp_path


def test_clean_fix_is_kept(repo, monkeypatch):
    monkeypatch.setattr(engineer, "run_tests", lambda: (True, "ok"))
    (repo / "tools" / "scan_ops.py").write_text("x = 2\n", encoding="utf-8")
    assert engineer.finish(date(2026, 11, 9), "ok") == "applied"
    assert (repo / "tools" / "scan_ops.py").read_text() == "x = 2\n"


def test_protected_file_rolls_back_everything(repo, monkeypatch):
    monkeypatch.setattr(engineer, "run_tests", lambda: pytest.fail("tests must not run once the guard refuses"))
    (repo / "tools" / "gate.py").write_text("y = 2\n", encoding="utf-8")
    (repo / "tools" / "scan_ops.py").write_text("x = 2\n", encoding="utf-8")
    (repo / "tests" / "test_eng_new.py").write_text("z = 1\n", encoding="utf-8")
    assert engineer.finish(date(2026, 11, 9), "ok") == "rolled back"
    assert (repo / "tools" / "gate.py").read_text() == "y = 1\n"
    assert (repo / "tools" / "scan_ops.py").read_text() == "x = 1\n"
    assert not (repo / "tests" / "test_eng_new.py").exists()


def test_failing_tests_roll_back(repo, monkeypatch):
    monkeypatch.setattr(engineer, "run_tests", lambda: (False, "1 failed"))
    (repo / "tools" / "scan_ops.py").write_text("x = 2\n", encoding="utf-8")
    assert engineer.finish(date(2026, 11, 9), "ok") == "rolled back"
    assert (repo / "tools" / "scan_ops.py").read_text() == "x = 1\n"


def test_unfinished_run_rolls_back(repo, monkeypatch):
    monkeypatch.setattr(engineer, "run_tests", lambda: (True, "ok"))
    (repo / "tools" / "scan_ops.py").write_text("x = 2\n", encoding="utf-8")
    assert engineer.finish(date(2026, 11, 9), "failed") == "rolled back"


@pytest.mark.parametrize("line", ["import subprocess", "open('.env')", "p = 'strategies/registry.json'",
                                  "run('Start-ScheduledTask x')", "from common import LIVE_V3"])
def test_forbidden_python_refused(repo, line):
    (repo / "tools" / "scan_ops.py").write_text(f"x = 1\n{line}\n", encoding="utf-8")
    assert any("forbidden" in p for p in engineer.review(engineer.code_changes()))


def test_existing_forbidden_word_is_not_held_against_a_fix(repo):
    (repo / "tools" / "scan_ops.py").write_text("import subprocess\n", encoding="utf-8")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", "has subprocess")
    (repo / "tools" / "scan_ops.py").write_text("import subprocess\nx = 3\n", encoding="utf-8")
    assert engineer.review(engineer.code_changes()) == []


def test_prompt_may_add_but_not_remove_a_limit(repo):
    p = repo / "prompts" / "scout.md"
    p.write_text("Never touch the holdout.\nKeep it short.\nPrefer close fills.\n", encoding="utf-8")
    assert engineer.review(engineer.code_changes()) == []
    p.write_text("Keep it short.\n", encoding="utf-8")
    assert any("removes a limit" in x for x in engineer.review(engineer.code_changes()))


def test_size_cap(repo):
    (repo / "tools" / "scan_ops.py").write_text("x = 1\n" * (engineer.MAX_ADDED + 5), encoding="utf-8")
    assert any("lines added" in p for p in engineer.review(engineer.code_changes()))


def test_failure_wakes_engineer_and_repeat_goes_to_user(tmp_path, monkeypatch):
    (tmp_path / "logs").mkdir()
    (tmp_path / "usage.csv").write_text("date,role,model,turns,minutes,cost,status\n"
                                        "2026-11-09,scout,sonnet,3,1,0.1,failed\n", encoding="utf-8")
    posts = []
    monkeypatch.setattr(engineer, "STATE", tmp_path)
    monkeypatch.setattr(engineer, "STATEF", tmp_path / "engineer.json")
    monkeypatch.setattr(engineer, "TICKETS", tmp_path / "tickets.md")
    monkeypatch.setattr(engineer, "TEAM", tmp_path)
    monkeypatch.setattr(engineer, "post", lambda ch, text, user: posts.append(text))
    day = date(2026, 11, 9)
    assert "1 failure ticket" in engineer.prepare(day, weekly_day=False)
    for _ in range(engineer.MAX_ATTEMPTS - 1):     # the same failure seen again on later runs
        engineer.save_json(engineer.STATEF, {**engineer.load_json(engineer.STATEF, {}), "last_run": "2026-11-08"})
        assert engineer.prepare(day, weekly_day=False)
    engineer.save_json(engineer.STATEF, {**engineer.load_json(engineer.STATEF, {}), "last_run": "2026-11-08"})
    assert engineer.prepare(day, weekly_day=False) is None
    assert any("need you" in p for p in posts)


def test_edgar_403_is_not_a_ticket(tmp_path, monkeypatch):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "2026-11-09-dispatch.log").write_text(
        "2026-11-09 14:50:02 edgar update failed: 403 Client Error\n"
        "2026-11-09 14:50:03 catalog failed: boom\n", encoding="utf-8")
    monkeypatch.setattr(engineer, "STATE", tmp_path)
    monkeypatch.setattr(engineer, "TEAM", tmp_path)
    urgent, _ = engineer.collect(date(2026, 11, 9), "2026-11-08")
    assert len(urgent) == 1 and "catalog failed" in urgent[0]


def test_daily_bars_refresh_when_bars_are_old():
    sat = date(2026, 11, 7)
    assert not daily_bars.fresh({"date": "2026-11-03", "through": "2026-11-02"}, sat)   # the 11-07 miss
    assert daily_bars.fresh({"date": "2026-11-07", "through": "2026-11-06"}, sat)
    assert not daily_bars.fresh({}, sat)


# ---- added 2026-11-13 (audit): after-test check, tools-only write patterns, handled tickets ----

def test_file_written_by_the_tests_is_caught_and_undone(repo, monkeypatch):
    def sneaky_tests():
        (repo / "registry" / "ideas.csv").write_text("x\n", encoding="utf-8")   # a test writing a result file
        return True, "ok"
    monkeypatch.setattr(engineer, "run_tests", sneaky_tests)
    (repo / "tools" / "scan_ops.py").write_text("x = 2\n", encoding="utf-8")
    assert engineer.finish(date(2026, 11, 9), "ok") == "rolled back"
    assert not (repo / "registry" / "ideas.csv").exists() and (repo / "tools" / "scan_ops.py").read_text() == "x = 1\n"


def test_raw_file_writes_refused_in_tools_but_fine_in_tests(repo):
    (repo / "tools" / "scan_ops.py").write_text("x = 1\nopen('out.txt', 'w').write('x')\n", encoding="utf-8")
    assert any("forbidden" in p for p in engineer.review(engineer.code_changes()))
    sh(repo, "checkout", "--", "tools/scan_ops.py")
    (repo / "tests" / "test_eng_x.py").write_text("def test_a(tmp_path):\n    (tmp_path / 'a').write_text('1')\n"
                                                  "    open(tmp_path / 'b', 'w').close()\n", encoding="utf-8")
    assert engineer.review(engineer.code_changes()) == []


def test_handled_occurrence_is_not_reticketed(tmp_path, monkeypatch):
    (tmp_path / "logs").mkdir()
    (tmp_path / "usage.csv").write_text("date,role,model,turns,minutes,cost,status\n"
                                        "2026-11-09,scout,sonnet,3,1,0.1,failed\n", encoding="utf-8")
    monkeypatch.setattr(engineer, "STATE", tmp_path)
    monkeypatch.setattr(engineer, "STATEF", tmp_path / "engineer.json")
    monkeypatch.setattr(engineer, "TICKETS", tmp_path / "tickets.md")
    monkeypatch.setattr(engineer, "TEAM", tmp_path)
    monkeypatch.setattr(engineer, "post", lambda *a, **k: True)
    assert engineer.prepare(date(2026, 11, 9), weekly_day=False)
    engineer.mark_handled("ok")                                       # the Engineer run finished
    st = engineer.load_json(engineer.STATEF, {})
    engineer.save_json(engineer.STATEF, {**st, "last_run": "2026-11-08"})
    assert engineer.prepare(date(2026, 11, 9), weekly_day=False) is None            # same occurrence: no ticket
    with open(tmp_path / "usage.csv", "a", encoding="utf-8") as fh:                 # same job, NEW day: ticket
        fh.write("2026-11-10,scout,sonnet,3,1,0.1,failed\n")
    assert "1 failure ticket" in engineer.prepare(date(2026, 11, 10), weekly_day=False)
