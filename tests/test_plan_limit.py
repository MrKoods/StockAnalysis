import json
import sys
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import dispatch  # noqa: E402
import ops_monitor  # noqa: E402
import plan_limit  # noqa: E402

NOW = datetime(2026, 11, 3, 15, 7)   # Tue
REAL = ('{"type":"result","is_error":true,"api_error_status":429,"num_turns":1,'
        '"result":"You\'ve hit your session limit · resets 5:50pm (America/Los_Angeles)"}')


def test_detects_the_limit_and_reads_the_reset():
    assert plan_limit.is_limited(REAL, json.loads(REAL))
    assert not plan_limit.is_limited('{"result":"done"}', {"num_turns": 12})
    assert plan_limit.reset_time(REAL, NOW) == datetime(2026, 11, 3, 17, 50)
    assert plan_limit.reset_time("resets 2am", NOW) == datetime(2026, 11, 4, 2, 0)          # past -> tomorrow
    assert plan_limit.reset_time("resets Fri 9am", NOW) == datetime(2026, 11, 6, 9, 0)
    assert plan_limit.reset_time("resets Nov 7, 9:30am", NOW) == datetime(2026, 11, 7, 9, 30)
    assert plan_limit.reset_time("limit hit", NOW) == NOW + plan_limit.FALLBACK              # unreadable


def _setup(monkeypatch, tmp_path, limited_role):
    monkeypatch.setattr(dispatch, "STATE", tmp_path)
    monkeypatch.setattr(dispatch, "USAGE", tmp_path / "usage.csv")
    monkeypatch.setattr(dispatch, "commit", lambda *a: None)
    monkeypatch.setattr(dispatch, "post", lambda *a, **k: None)
    monkeypatch.setattr(dispatch, "write_context", lambda *a, **k: None)
    monkeypatch.setattr(dispatch.jobs, "advance", lambda dry: [])
    monkeypatch.setattr(dispatch, "research_work", lambda: "RESEARCH idea-a")
    monkeypatch.setattr(dispatch, "review_work", lambda: None)
    ran = []

    def fake_run(role, cfg, why, today, dry):
        ran.append(role)
        if role == limited_role:
            return {"status": "limited", "date": str(today), "note": "", "resets_at": "2026-11-03T17:50:00"}
        return {"status": "ok", "date": str(today), "note": ""}
    monkeypatch.setattr(dispatch, "run_role", fake_run)
    cfg = {"roles": {r: {"enabled": True} for r in ("scorekeeper", "scout", "director", "researcher", "skeptic")}}
    a = SimpleNamespace(force=[], dry_run=False)
    return ran, cfg, a


def test_nothing_runs_after_the_limit_and_the_rest_is_held(monkeypatch, tmp_path):
    ran, cfg, a = _setup(monkeypatch, tmp_path, limited_role="scout")
    want = {"scorekeeper": "diagnose", "scout": "scouting", "director": "pipeline has room"}
    limit = dispatch.run_roles(date(2026, 11, 3), a, cfg, want, ops_monitor.Findings(), [], {}, [])
    assert ran == ["scorekeeper", "scout"]                       # director/researcher never launched
    assert list(limit["roles"]) == ["scout", "director", "researcher"]
    assert limit["roles"]["researcher"] == "RESEARCH idea-a"
    assert limit["resets_at"] == "2026-11-03T17:50:00"


def test_no_limit_holds_nothing(monkeypatch, tmp_path):
    ran, cfg, a = _setup(monkeypatch, tmp_path, limited_role=None)
    limit = dispatch.run_roles(date(2026, 11, 3), a, cfg, {"scout": "x"}, ops_monitor.Findings(), [], {}, [])
    assert limit["roles"] == {} and ran == ["scout", "researcher"]


def test_resume_waits_for_the_reset_and_locks(monkeypatch, tmp_path):
    monkeypatch.setattr(plan_limit, "RESUME", tmp_path / "resume.json")
    monkeypatch.setattr(plan_limit, "LOCK", tmp_path / "resume.lock")
    plan_limit.save("2026-11-03", datetime(2026, 11, 3, 17, 50), {"director": "x"}, 0)
    monkeypatch.setattr(plan_limit, "now_pt", lambda: datetime(2026, 11, 3, 17, 51))
    assert not plan_limit.due()                                   # inside the 2-min grace
    monkeypatch.setattr(plan_limit, "now_pt", lambda: datetime(2026, 11, 3, 17, 53))
    assert plan_limit.due() and not plan_limit.due(plan_limit.BACKUP_GRACE)
    assert plan_limit.take_lock() and not plan_limit.take_lock()  # a second resume can't start
    assert plan_limit.running()
    plan_limit.drop_lock()
    plan_limit.clear()
    assert plan_limit.pending() is None and not plan_limit.due()


def test_limited_zero_turn_runs_do_not_count_toward_the_weekly_cap(monkeypatch, tmp_path):
    u = tmp_path / "usage.csv"
    u.write_text("date,role,model,turns,minutes,cost_equiv_usd,status\n"
                 "2026-11-03,researcher,opus,33,5.0,1.95,limited\n"
                 "2026-11-03,skeptic,opus,1,0.0,0,limited\n"
                 "2026-11-03,scout,sonnet,26,7.3,1.09,ok\n", encoding="utf-8")
    monkeypatch.setattr(dispatch, "USAGE", u)
    monkeypatch.setattr(dispatch, "now_pt", lambda: datetime(2026, 11, 4, 9, 0))
    assert dispatch.runs_this_week() == 2


def test_outside_outage_is_a_note_not_a_diagnosis(monkeypatch, tmp_path):
    monkeypatch.setattr(ops_monitor, "STATE", tmp_path)
    out = ("  paper_runner_task.log: 402 lines today, 0 error lines | outside outage: Yahoo Finance news down x59\n"
           "  paper_updater_task.log: 103 lines today, 2 error lines | e.g. boom | outside outage: Yahoo Finance news down x3\n")
    monkeypatch.setattr(ops_monitor.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout=out, stderr=""))
    f = ops_monitor.Findings()
    ops_monitor.check_snapshot(f)
    assert f.diagnose == ["paper_updater_task.log: 103 lines today, 2 error lines | e.g. boom"]
    assert len(f.notes) == 1 and "Yahoo Finance news down" in f.notes[0]
