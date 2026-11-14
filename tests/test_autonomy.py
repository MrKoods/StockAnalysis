"""tools/autonomy.py - the 'how self-running is the team' count (user's goal, 2026-11-14)."""
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import pytest

import autonomy
import dispatch


@pytest.fixture
def env(tmp_path, monkeypatch):
    (tmp_path / "reports").mkdir()
    (tmp_path / "state").mkdir()
    monkeypatch.setattr(autonomy, "TEAM", tmp_path)
    monkeypatch.setattr(autonomy, "STATE", tmp_path / "state")
    monkeypatch.setattr(autonomy, "LEDGER", tmp_path / "state" / "autonomy.json")
    monkeypatch.setattr(autonomy, "ENG_LOG", tmp_path / "engineer_log.csv")
    log = ("11-14 team-runner: director 2026-11-14 (weekly review)\n"
           "11-13 Audit 2026-11-13: reliability fixes\n"
           "11-13 pre-dispatch 2026-11-13: changes made outside the team run (user's session)\n"
           "11-06 team-runner: paper 2026-11-06\n"
           "11-05 Real Webull fill costs\n")
    monkeypatch.setattr(autonomy, "git", lambda *a: log)      # date filtering is git's job, not tested here
    return tmp_path


def test_user_commits_are_everything_but_team_runner(env):
    got = autonomy.user_commits("2026-11-08", "2026-11-14")
    assert all("team-runner" not in c for c in got) and len(got) == 3


def test_record_and_alert_days(env):
    autonomy.record(date(2026, 11, 12), SimpleNamespace(alerts=["QuoteClose failed"]))
    autonomy.record(date(2026, 11, 13), SimpleNamespace(alerts=[]))
    assert list(autonomy.alert_days("2026-11-08", "2026-11-14")) == ["2026-11-12"]


def test_self_fixes_from_engineer_log_and_scan_ops(env):
    autonomy.ENG_LOG.write_text("date,result,files,why\n2026-11-12,applied,tools/a.py tests/t.py,ok\n"
                                "2026-11-13,rolled_back,tools/b.py,tests failed\n", encoding="utf-8")
    (env / "state" / "scan_ops.json").write_text(
        '{"2026-11-12": {"retries:StockAnalysis_X": 1, "recovered:StockAnalysis_X": true},'
        ' "2026-11-13": {"gave_up:StockAnalysis_Y": true}, "issues": []}', encoding="utf-8")
    fixed, failed = autonomy.self_fixes("2026-11-08", "2026-11-14")
    assert len(fixed) == 2 and len(failed) == 2
    assert any("recovered" in x for x in fixed) and any("gave up on Y" in x for x in failed)


def test_asks_read_latest_report_section_only(env):
    (env / "reports" / "2026-11-07-director.md").write_text("## Data requests\n1. old request\n", encoding="utf-8")
    (env / "reports" / "2026-11-14-director.md").write_text(
        "## Decisions\n1. not a request\n\n## Data requests (the team can't)\n1. **NLP** filter\n2. FOMC dates\n"
        "\n## Next\n1. nope\n", encoding="utf-8")
    assert autonomy.asks("2026-11-08", "2026-11-14") == ["director: NLP filter", "director: FOMC dates"]


def test_summary_lines(env):
    lines = autonomy.summary(date(2026, 11, 14))
    assert lines[0].startswith("• You stepped in **") and "Team fixed itself" in lines[1]


def test_allowed_commands_lists_only_bash_rules(tmp_path, monkeypatch):
    (tmp_path / "team" / "settings").mkdir(parents=True)
    (tmp_path / "team" / "settings" / "x.json").write_text(
        '{"permissions": {"allow": ["Read(//c/**)", "Bash(python tools/ideas.py list)"]}}', encoding="utf-8")
    monkeypatch.setattr(dispatch, "TEAM", tmp_path)
    out = dispatch.allowed_commands("x")
    assert "python tools/ideas.py list" in out and "Read(" not in out
    assert dispatch.allowed_commands("missing") == ""
