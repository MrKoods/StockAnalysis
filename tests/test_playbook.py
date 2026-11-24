"""tools/playbook.py - the monthly Strategist's playbook, its guard and evidence pack (user 2026-11-24)."""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import pytest

import dispatch
import playbook

REAL = Path(__file__).resolve().parents[1] / "playbook" / "PLAYBOOK.md"


@pytest.fixture
def env(tmp_path, monkeypatch):
    for d in ("reports", "registry", "state", "notes", "playbook"):
        (tmp_path / d).mkdir()
    monkeypatch.setattr(playbook, "TEAM", tmp_path)
    monkeypatch.setattr(playbook, "STATE", tmp_path / "state")
    monkeypatch.setattr(playbook, "PLAYBOOK", tmp_path / "playbook" / "PLAYBOOK.md")
    monkeypatch.setattr(playbook, "PACK", tmp_path / "state" / "review_pack.md")
    monkeypatch.setattr(playbook, "log", lambda *a, **k: None)
    return tmp_path


def test_the_committed_playbook_carries_the_fixed_section_verbatim():
    assert f"{playbook.START}\n{playbook.FIXED}\n{playbook.END}" in REAL.read_text(encoding="utf-8")


def test_guard_undoes_an_edit_of_the_fixed_section_and_keeps_the_rest(env):
    good = f"# Playbook\n\n{playbook.START}\n{playbook.FIXED}\n{playbook.END}\n\n## Search priorities\n1. ETFs\n"
    playbook.PLAYBOOK.write_text(good.replace("No real money until", "Real money is fine before"), encoding="utf-8")
    assert "RESTORED" in playbook.guard()
    assert playbook.PLAYBOOK.read_text(encoding="utf-8") == good
    assert playbook.guard() == "fixed section intact"
    playbook.PLAYBOOK.write_text("# Playbook\n\n## Search priorities\n1. ETFs\n", encoding="utf-8")   # deleted
    playbook.guard()
    text = playbook.PLAYBOOK.read_text(encoding="utf-8")
    assert text.startswith("# Playbook\n") and playbook.FIXED in text and "1. ETFs" in text


def test_due_first_saturday_four_weeks_after_the_last_review(env):
    sat = date(2026, 11, 28)
    assert playbook.due(sat) and not playbook.due(date(2026, 11, 27))          # never reviewed: first Saturday
    (env / "reports" / "2026-11-28-strategist.md").write_text("x")
    assert not playbook.due(date(2026, 12, 5)) and not playbook.due(date(2026, 12, 19))
    assert playbook.due(date(2026, 12, 26))                                    # 28 days later


def test_pack_reports_family_outcomes_and_train_to_holdout_shrinkage(env, monkeypatch):
    import autonomy
    monkeypatch.setattr(autonomy, "summary", lambda today: ["• self-running line"])
    (env / "registry" / "ideas.csv").write_text(
        "id,date,source,family,horizon,stage,summary,mechanism,data_needed,est_cost_bps,notes,est_gross_bps\n"
        "a,2026-11-01,s,fam1,1d,dead,x,m,d,10,\"train done: chosen v1 t 3.0 | holdout FAIL: t 1.0, 5 bps\",\n"
        "b,2026-11-02,s,fam1,1d,dropped,x,m,d,10,dropped,\n"
        "c,2026-11-03,s,fam2,1d,idea,x,m,d,10,,\n", encoding="utf-8")
    playbook.write_pack(date(2026, 11, 28))
    text = playbook.PACK.read_text(encoding="utf-8")
    assert "| fam1 | 2 | dead 1, dropped 1 | 3.0 | 1.0 |" in text
    assert "1 ideas reached a holdout: mean chosen train t 3.00 -> holdout t 1.00 (holdout keeps 33%" in text
    assert "• self-running line" in text


def test_dispatch_wakes_the_strategist_on_a_due_saturday_only(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(dispatch, "open_items", lambda stage: 0)
    f = SimpleNamespace(alerts=[], diagnose=[])
    monkeypatch.setattr(dispatch.playbook, "due", lambda today: True)
    assert "strategist" in dispatch.triggers(date(2026, 11, 28), f, [], {}, {})
    assert "strategist" not in dispatch.triggers(date(2026, 11, 27), f, [], {}, {})
    monkeypatch.setattr(dispatch.playbook, "due", lambda today: False)
    assert "strategist" not in dispatch.triggers(date(2026, 11, 28), f, [], {}, {})
