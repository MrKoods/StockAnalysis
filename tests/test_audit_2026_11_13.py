"""Fixes from the 2026-11-13 audit: lost login, quote retries, test.py lock, holdout power, long-hold clustering,
the family luck count, per-run logs, notes/Auditor housekeeping, ON1 retirement, entry_session, the hedge funds."""
import json
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import dispatch  # noqa: E402
import jobs  # noqa: E402
import ops_monitor  # noqa: E402
import quotes  # noqa: E402
import research_data as rd  # noqa: E402

TODAY = date(2026, 11, 13)


# ---------- lost login ----------

def _dispatch(monkeypatch, tmp_path, statuses):
    monkeypatch.setattr(dispatch, "STATE", tmp_path)
    monkeypatch.setattr(dispatch, "USAGE", tmp_path / "usage.csv")
    for name in ("commit", "post", "write_context", "log"):
        monkeypatch.setattr(dispatch, name, lambda *a, **k: None)
    monkeypatch.setattr(dispatch.jobs, "advance", lambda dry: [])
    monkeypatch.setattr(dispatch, "research_work", lambda: "RESEARCH idea-a")
    monkeypatch.setattr(dispatch, "review_work", lambda: None)
    monkeypatch.setattr(dispatch.engineer, "prepare", lambda *a, **k: None)
    ran = []

    def fake_run(role, cfg, why, today, dry):
        ran.append(role)
        return {"status": statuses.get(role, "ok"), "date": str(today), "note": ""}
    monkeypatch.setattr(dispatch, "run_role", fake_run)
    cfg = {"roles": {r: {"enabled": True} for r in ("scout", "director", "researcher", "skeptic", "engineer")}}
    return ran, cfg, SimpleNamespace(force=[], dry_run=False)


def test_logged_out_stops_every_later_launch(monkeypatch, tmp_path):
    ran, cfg, a = _dispatch(monkeypatch, tmp_path, {"scout": "logged_out"})
    dispatch.run_roles(TODAY, a, cfg, {"scout": "x", "director": "y"}, ops_monitor.Findings(), [], {}, [])
    assert ran == ["scout"]


def test_refused_runs_do_not_count_toward_the_weekly_cap(monkeypatch, tmp_path):
    u = tmp_path / "usage.csv"
    u.write_text("date,role,model,turns,minutes,cost,status\n"
                 "2026-11-13,scout,sonnet,1,0.0,0,logged_out\n2026-11-13,director,opus,,0.0,,failed\n"
                 "2026-11-13,researcher,opus,30,6,3,ok\n2026-11-13,quote_clerk,haiku,1,0,0,failed\n", encoding="utf-8")
    monkeypatch.setattr(dispatch, "USAGE", u)
    monkeypatch.setattr(dispatch, "now_pt", lambda: pd.Timestamp("2026-11-13 15:00").to_pydatetime())
    assert dispatch.runs_this_week() == 1


def test_second_run_same_day_gets_its_own_log(monkeypatch, tmp_path):
    monkeypatch.setattr(dispatch, "STATE", tmp_path)
    (tmp_path / "logs").mkdir()
    first = dispatch.run_log_path(TODAY, "researcher")
    first.write_text("{}")
    assert first.name == "2026-11-13-researcher.json"
    assert dispatch.run_log_path(TODAY, "researcher").name == "2026-11-13-researcher-2.json"


# ---------- Quote Clerk: logout, retry inside the window, exit code ----------

def _quotes(monkeypatch, tmp_path, streams):
    monkeypatch.setattr(quotes, "STATE", tmp_path)
    monkeypatch.setattr(quotes, "USAGE", tmp_path / "usage.csv")
    monkeypatch.setattr(quotes, "QUOTES", tmp_path / "quotes.csv")
    monkeypatch.setattr(quotes, "INVALID", tmp_path / "invalid.json")
    monkeypatch.setattr(quotes, "needs", lambda when, today: ["AAA", "BBB"])
    monkeypatch.setattr(quotes, "too_late", lambda when, now: None)
    monkeypatch.setattr(quotes, "now_pt", lambda: pd.Timestamp("2026-11-13 12:56").to_pydatetime())
    monkeypatch.setattr(quotes.time, "sleep", lambda s: None)
    monkeypatch.setattr(quotes, "log", lambda *a, **k: None)
    posts = []
    monkeypatch.setattr(quotes, "post", lambda ch, text, user: posts.append(text))
    calls = iter(streams)
    monkeypatch.setattr(quotes, "_launch", lambda *a: next(calls))
    return posts


def _stream(*syms):
    qt = int(pd.Timestamp("2026-11-13 12:56").timestamp() * 1000)
    rows = [{"symbol": s, "bid": "10", "ask": "10.1", "quote_time": str(qt)} for s in syms]
    line = {"type": "user", "message": {"content": [{"type": "tool_result",
                                                     "content": [{"type": "text", "text": json.dumps(rows)}]}]}}
    return json.dumps(line) + "\n"


def test_logout_is_named_and_not_retried(monkeypatch, tmp_path):
    posts = _quotes(monkeypatch, tmp_path, ['{"result":"Not logged in · Please run /login"}'])
    msg = quotes.capture("close")
    assert "(logged_out)" in msg and any("LOGGED OUT" in p for p in posts)
    assert (tmp_path / "usage.csv").read_text().strip().endswith(",logged_out")


def test_partial_capture_is_retried_once_for_the_missing_tickers(monkeypatch, tmp_path):
    _quotes(monkeypatch, tmp_path, [_stream("AAA"), _stream("BBB")])
    assert "2/2 tickers captured (ok)" in quotes.capture("close")


# ---------- research harness ----------

def _research(tmp_path, monkeypatch, plan):
    monkeypatch.setattr(jobs, "RESEARCH", tmp_path)
    d = tmp_path / "x"
    d.mkdir()
    (d / "plan.json").write_text(json.dumps(plan))
    (d / "test.py").write_text("def run(*a): return 1\n")
    return d


def test_test_py_is_frozen_once_a_train_result_exists(tmp_path, monkeypatch):
    d = _research(tmp_path, monkeypatch, {"max_variants": 3})
    (d / "plan.lock").write_text(jobs.plan_hash("x"))
    (d / "test.py").write_text("def run(*a): return 2\n")          # before results: a fix is allowed
    assert not jobs.plan_changed("x")
    (d / "test.lock").write_text(jobs.plan_hash("x", "test.py"))   # written by do_train at the first result
    (d / "test.py").write_text("def run(*a): return 3\n")
    assert jobs.plan_changed("x")


PLAN = {"family": "f", "train_start": "2005-01-01", "train_end": "2017-12-31", "holdout_start": "2018-01-01",
        "holdout_end": "2019-12-31", "cost_bps": 20, "cluster": "week", "max_variants": 4, "hold_days": 3}


def test_underpowered_idea_is_buried_without_spending_the_holdout(tmp_path, monkeypatch):
    _research(tmp_path, monkeypatch, PLAN)            # 2-year holdout vs 13-year train: power far too low
    res = {"variants": 2, "chosen": "a", "configs": {"a": {"t": 3.2, "mean_bps": 40.0, "n_periods": 600}},
           "cost_bps_used": 22.0, "cost_floor_bps": 22.0, "plan_cost_bps": 20.0}
    monkeypatch.setattr(jobs, "run_phase", lambda iid, phase: (res, ""))
    monkeypatch.setattr(jobs.budget, "append", lambda r: None)
    monkeypatch.setattr(jobs.budget, "rows", lambda: [])
    monkeypatch.setattr(jobs, "post", lambda *a, **k: None)
    stages, buried = [], []
    monkeypatch.setattr(jobs.ideas, "set_stage", lambda iid, st, note: stages.append(st))
    monkeypatch.setattr(jobs, "bury", lambda iid, why: buried.append(why))
    jobs.do_train("x", False)
    assert stages == [] and "underpowered" in buried[0] and "Holdout NOT spent" in buried[0]
    tr = json.loads((tmp_path / "x" / "train_result.json").read_text())
    assert tr["holdout_power"]["pass_prob"] < jobs.MIN_HOLDOUT_POWER
    assert (tmp_path / "x" / "test.lock").exists()


def test_long_holds_must_cluster_by_month(tmp_path, monkeypatch):
    d = _research(tmp_path, monkeypatch, {**PLAN, "hold_days": 20})
    (d / "PLAN.md").write_text("p")
    monkeypatch.setattr(jobs.ideas, "get", lambda iid: None)
    assert any("cluster must be month" in p for p in jobs.plan_problems("x"))
    s = jobs.stats([{"date": "2018-01-05", "gross_bps": 50}, {"date": "2018-01-25", "gross_bps": 70},
                    {"date": "2018-02-09", "gross_bps": 10}], 0, "month", "2018-01-01", "2018-12-31")
    assert s["n_periods"] == 2 and s["mean_bps"] == 35.0


def test_screen_family_luck_counts_every_screen_variant(monkeypatch):
    rows = [{"idea_id": "screen", "family": "8k_1_01", "stage": "search", "variants": "3"},
            {"idea_id": "screen", "family": "8k_2_02", "stage": "search", "variants": "54"},
            {"idea_id": "old-idea", "family": "8k_1_01", "stage": "search", "variants": "6"}]
    monkeypatch.setattr(jobs.budget, "rows", lambda: rows)
    assert jobs.family_search_variants("8k_1_01") == 3 + 6 + 54
    assert jobs.family_search_variants("calendar") == 0


# ---------- housekeeping + dropped reasons + ON1 retirement ----------

def test_housekeeping_flags_long_notes_and_unanswered_auditor(monkeypatch, tmp_path):
    monkeypatch.setattr(dispatch, "TEAM", tmp_path)
    (tmp_path / "notes").mkdir()
    (tmp_path / "reports").mkdir()
    (tmp_path / "notes" / "director.md").write_text("x\n" * 200)
    (tmp_path / "reports" / "2026-11-07-auditor.md").write_text("recs")
    todo = dispatch.housekeeping()
    assert any("200 lines" in t for t in todo) and any("2026-11-07-auditor.md" in t for t in todo)
    (tmp_path / "notes" / "director.md").write_text("## reports/2026-11-07-auditor.md\n- rec 1 accepted\n")
    assert dispatch.housekeeping() == []


def test_dropped_reasons_reach_the_scout(monkeypatch, tmp_path):
    monkeypatch.setattr(dispatch, "STATE", tmp_path)
    monkeypatch.setattr(dispatch.ideas, "load", lambda: [
        {"id": "pre-holiday", "family": "calendar", "stage": "dropped",
         "notes": "card | 2026-11-12 dropped: fires ~10 days a year - a 20-40 day paper test can't run"},
        {"id": "live-one", "family": "f", "stage": "idea", "notes": ""}])
    dispatch.write_dropped()
    text = (tmp_path / "dropped_ideas.md").read_text(encoding="utf-8")
    assert "pre-holiday" in text and "10 days a year" in text and "live-one" not in text


def test_on1_retires_once_on_real_price_fail(monkeypatch, tmp_path):
    monkeypatch.setattr(dispatch, "ON1_RETIRED", tmp_path / "on1_retired.json")
    posts = []
    monkeypatch.setattr(dispatch, "post", lambda ch, text, user, dry=False: posts.append(text))
    assert not dispatch.retire_on1({"verdict": "COLLECTING"}, dry_run=True)
    assert dispatch.retire_on1({"verdict": "FAIL", "days": 15, "real_mean_bps": -80}, dry_run=True)
    assert "ON1 retired" in posts[0]


def test_v2_checkpoint_regex_follows_the_verdict_past_100():
    m = dispatch.metrics("Rank-track go/no-go: KEEP COLLECTING (150/200 closed trades)\n")
    assert m["V2 rank go/no-go (closed trades)"] == 150
    assert dispatch.metrics("Rank-track go/no-go: COLLECTING (88/100 closed trades)")[
        "V2 rank go/no-go (closed trades)"] == 88


# ---------- research data ----------

def test_entry_session_buys_the_day_zero_close():
    sessions = pd.DatetimeIndex(["2026-11-09", "2026-11-10", "2026-11-11"])
    ts = pd.Series(pd.to_datetime(["2026-11-09 11:00", "2026-11-09 17:30", "2026-11-09 15:45",
                                   "2026-11-09 00:00", "2026-11-10 06:00"]))
    got = rd._entry_session(ts, sessions).dt.strftime("%m-%d").tolist()
    # intraday -> same close; after hours / late / no time -> next close; pre-market -> that day's close
    assert got == ["11-09", "11-10", "11-10", "11-10", "11-10"]
    first = rd._first_session(ts, sessions).dt.strftime("%m-%d").tolist()
    assert first == ["11-10", "11-10", "11-10", "11-10", "11-10"]


def test_each_index_hedges_with_its_own_fund():
    assert (rd.hedge_ticker("sp500"), rd.hedge_ticker("sp400"), rd.hedge_ticker("sp600")) == ("SPY", "IJH", "IJR")
    assert {"AAPL", "MSFT", "NVDA"} <= set(rd.universe("sp500"))          # the 40 megacaps were missing
