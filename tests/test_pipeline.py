import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import ideas  # noqa: E402
import jobs  # noqa: E402
import research_data as rd  # noqa: E402


def test_data_cutoff_is_enforced(monkeypatch):
    monkeypatch.delenv("TEAM_DATA_END", raising=False)
    with pytest.raises(RuntimeError):
        rd.daily(["AAPL"])
    monkeypatch.setenv("TEAM_DATA_END", "2016-12-31")
    d = rd.daily(["AAPL"])["AAPL"]
    assert d.index.max() <= pd.Timestamp("2016-12-31") and d.index.min() < pd.Timestamp("2000-01-01")
    h = rd.hourly(["AAPL"])
    assert not h  # hourly archive starts 2023-11 - nothing before the cutoff
    monkeypatch.setenv("TEAM_DATA_END", "2024-01-05")
    h = rd.hourly(["AAPL"])["AAPL"]
    assert h.index.tz_convert("America/New_York").max().date() <= pd.Timestamp("2024-01-05").date()
    e = rd.earnings(["AAPL"])["AAPL"]
    assert pd.to_datetime(e["Earnings Date"], utc=True).max() <= pd.Timestamp("2024-01-06", tz="UTC")


def test_static_scan_blocks_direct_data(tmp_path):
    p = tmp_path / "test.py"
    p.write_text("import yfinance as yf\nimport research_data as rd\n")
    assert any("yfinance" in x for x in jobs.static_problems(p))
    p.write_text("import pandas as pd\ndf = pd.read_parquet('x')\n")
    assert jobs.static_problems(p)
    p.write_text("import os\nos.environ['TEAM_DATA_END'] = '2030-01-01'\n")
    assert jobs.static_problems(p)
    p.write_text("import research_data as rd\nimport numpy as np\n")
    assert jobs.static_problems(p) == []


def test_harness_stats_drop_out_of_window_and_charge_costs():
    trades = [{"date": "2015-01-02", "gross_bps": 20}, {"date": "2015-01-02", "gross_bps": 0},
              {"date": "2015-01-05", "gross_bps": 30}, {"date": "2014-12-31", "gross_bps": 999}]
    s = jobs.stats(trades, 10, "day", "2015-01-01", "2015-12-31")
    assert s["n_trades"] == 3 and s["outside_window"] == 1 and s["n_periods"] == 2
    assert s["mean_bps"] == pytest.approx(((10 - 10) / 2 + 20) / 2)   # day means: 0, 20


def test_luck_baseline_grows_with_variants():
    assert jobs.luck_t(1) == 0 and jobs.luck_t(100) > jobs.luck_t(10) > 2


def test_role_moves_are_limited(tmp_path, monkeypatch):
    monkeypatch.setattr(ideas, "IDEAS", tmp_path / "ideas.csv")
    ideas.save([{"id": "abc", "stage": "idea", "family": "f"}])
    with pytest.raises(SystemExit):
        ideas.set_stage("abc", "paper", "skip ahead", by_script=False)
    ideas.set_stage("abc", "queued", "ok", by_script=False)
    assert ideas.get("abc")["stage"] == "queued"
    with pytest.raises(SystemExit):
        ideas.set_stage("abc", "skeptic_pass", "fake", by_script=False)


def test_plan_change_after_commit_is_detected(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "RESEARCH", tmp_path)
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "plan.json").write_text(json.dumps({"max_variants": 10}))
    (tmp_path / "x" / "plan.lock").write_text(jobs.plan_hash("x"))
    assert not jobs.plan_changed("x")
    (tmp_path / "x" / "plan.json").write_text(json.dumps({"max_variants": 500}))
    assert jobs.plan_changed("x")


def test_plan_windows_must_be_ordered(tmp_path, monkeypatch):
    monkeypatch.setattr(jobs, "RESEARCH", tmp_path)
    d = tmp_path / "y"
    d.mkdir()
    for f in ("PLAN.md", "test.py"):
        (d / f).write_text("import research_data as rd\n")
    plan = {"family": "f", "train_start": "2010-01-01", "train_end": "2018-12-31", "holdout_start": "2018-06-01",
            "holdout_end": "2020-01-01", "cost_bps": 10, "cluster": "day", "max_variants": 5}
    (d / "plan.json").write_text(json.dumps(plan))
    assert any("train_end < holdout_start" in p for p in jobs.plan_problems("y"))
