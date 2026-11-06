"""2026-11-05: close entries (Webull retail has no auction orders, open spreads are ~10x close spreads),
the real-spread cost floor in research, auto-fail below the Skeptic's minimum, the reserved Saturday Director."""
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import dispatch  # noqa: E402
import fill_costs  # noqa: E402
import jobs  # noqa: E402
import ops_monitor  # noqa: E402
import paper_runner as pr  # noqa: E402

D = [date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22)]


def frame(rows):
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close", "Volume"], index=D[: len(rows)])


BARS = {
    "SPY": frame([[100, 101, 99, 100, 1]] * 4),
    "UP": frame([[50, 51, 49, 50, 1], [100, 104, 99, 103, 1], [103, 106, 102, 105, 1], [105, 110, 104, 108, 1]]),
    "DROP": frame([[50, 51, 49, 50, 1], [100, 100, 94, 95, 1], [95, 96, 90, 91, 1], [91, 92, 90, 91, 1]]),
}
CLOSE = {"entry_at": "close", "hold_sessions": 1, "exit_at": "close", "cost_bps": 10}


def row(t):
    return {"strategy": "x", "signal_date": "2026-10-19", "ticker": t, "side": "long", "status": "pending"}


def test_close_entry_buys_the_next_close_and_sells_a_later_close():
    r = pr.advance(row("UP"), CLOSE, BARS, D)
    assert r["entry_date"] == "2026-10-20" and r["entry_px"] == 103
    assert r["exit_date"] == "2026-10-21" and r["exit_px"] == 105
    assert r["gross_bps"] == pytest.approx((105 / 103 - 1) * 1e4, abs=0.01)


def test_close_entry_ignores_the_entry_days_range_for_stops():
    # bought at 95 on 10-20's close: that day's low (94) happened BEFORE the fill; 10-21's low 90 hits the 5% stop
    r = pr.advance(row("DROP"), CLOSE | {"stop_pct": 5, "hold_sessions": 2}, BARS, D)
    assert r["entry_px"] == 95 and r["exit_reason"] == "stop" and r["exit_date"] == "2026-10-21"
    assert r["exit_px"] == pytest.approx(95 * 0.95)


def test_close_entry_hold_zero_means_next_session():
    r = pr.advance(row("UP"), CLOSE | {"hold_sessions": 0}, BARS, D)
    assert r["exit_date"] == "2026-10-21"


def test_close_entry_real_price_uses_close_quotes():
    q = {("2026-10-20", "close", "UP"): (102.9, 103.1), ("2026-10-21", "close", "UP"): (104.9, 105.1)}
    r = pr.advance(row("UP"), CLOSE, BARS, D, q)
    assert r["real_entry_px"] == 103.1 and r["real_exit_px"] == 104.9 and r["real_legs"] == 2


def test_open_entry_unchanged():
    r = pr.advance(row("UP"), {"hold_sessions": 0, "exit_at": "close", "cost_bps": 10}, BARS, D)
    assert r["entry_px"] == 100 and r["exit_px"] == 103


COSTS = {"half_spread_bps": {"open": {"sp500": 40.0, "sp400": 93.0, "sp600": 126.0},
                             "close": {"sp500": 3.3, "sp400": 6.2, "sp600": 10.8}}}


def test_floor_uses_fill_times_and_the_most_expensive_index():
    assert fill_costs.floor_bps("close", "close", ["sp500"], COSTS) == 6.6
    assert fill_costs.floor_bps("open", "open", ["sp400", "sp600"], COSTS) == 252.0
    assert fill_costs.floor_bps("close", "open", ["sp500"], COSTS) == 43.3
    assert fill_costs.floor_bps("open", "open", [], COSTS) == 252.0          # undeclared = worst case


def test_measure_from_quotes(monkeypatch, tmp_path):
    q = pd.DataFrame({"date": ["2026-11-02"] * 40, "when": ["close"] * 40, "ticker": ["AAA"] * 40,
                      "bid": [99.9] * 40, "ask": [100.1] * 40})
    p = tmp_path / "quotes.csv"
    q.to_csv(p, index=False)
    monkeypatch.setattr(fill_costs, "QUOTES", p)
    monkeypatch.setattr(fill_costs, "index_of", lambda: {"AAA": "sp500"})
    m = fill_costs.measure()
    assert m["half_spread_bps"]["close"]["sp500"] == 10.0 and m["quotes"]["close"]["sp500"] == 40
    assert m["half_spread_bps"]["open"]["sp600"] == fill_costs.DEFAULT_HALF_BPS["open"]["sp600"]  # too few -> default


def test_cost_used_floor_and_holdout_reuse(monkeypatch, tmp_path):
    monkeypatch.setattr(jobs, "RESEARCH", tmp_path)
    monkeypatch.setattr(jobs.fill_costs, "floor_bps", lambda e, x, u: 20.0 if (e, x) == ("close", "close") else 250.0)
    plan = {"cost_bps": 25, "entry_at": "close", "exit_at": "close", "universe": ["sp600"]}
    assert jobs.cost_used(plan, "x", "train") == (25.0, 20.0)                # plan above the floor: plan wins
    assert jobs.cost_used({"cost_bps": 25}, "x", "train") == (250.0, 250.0)  # undeclared timing = open/open
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "train_result.json").write_text('{"cost_bps_used": 31.0, "cost_floor_bps": 20.0}')
    assert jobs.cost_used(plan, "x", "holdout") == (31.0, 20.0)              # holdout judged like the train run


def _train(monkeypatch, tmp_path, t, mean):
    monkeypatch.setattr(jobs, "RESEARCH", tmp_path)
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "plan.json").write_text('{"family": "f", "train_start": "2005-01-01", "train_end": "2013-12-31",'
                                              ' "cost_bps": 20, "cluster": "week", "max_variants": 4}')
    res = {"variants": 2, "chosen": "a", "configs": {"a": {"t": t, "mean_bps": mean, "n_periods": 300}},
           "cost_bps_used": 22.0, "cost_floor_bps": 22.0, "plan_cost_bps": 20.0}
    monkeypatch.setattr(jobs, "run_phase", lambda iid, phase: (res, ""))
    monkeypatch.setattr(jobs.budget, "append", lambda r: None)
    monkeypatch.setattr(jobs, "post", lambda *a, **k: None)
    stages, buried = [], []
    monkeypatch.setattr(jobs.ideas, "set_stage", lambda iid, st, note: stages.append(st))
    monkeypatch.setattr(jobs, "bury", lambda iid, why: buried.append(why))
    jobs.do_train("x", False)
    return stages, buried


@pytest.mark.parametrize("t,mean", [(-2.77, -17.9), (0.99, 20.3), (1.99, 5.0)])
def test_below_the_skeptic_minimum_dies_without_a_review(monkeypatch, tmp_path, t, mean):
    stages, buried = _train(monkeypatch, tmp_path, t, mean)
    assert stages == [] and len(buried) == 1 and "no review needed" in buried[0]


def test_promising_train_result_goes_to_the_skeptic(monkeypatch, tmp_path):
    stages, buried = _train(monkeypatch, tmp_path, 2.4, 15.0)
    assert stages == ["awaiting_review"] and buried == []


def test_saturday_director_review_is_exempt_from_the_weekly_cap(monkeypatch, tmp_path):
    monkeypatch.setattr(dispatch, "STATE", tmp_path)
    for name, val in (("commit", lambda *x: None), ("post", lambda *x, **k: None),
                      ("write_context", lambda *x, **k: None), ("runs_this_week", lambda: 99)):
        monkeypatch.setattr(dispatch, name, val)
    monkeypatch.setattr(dispatch.jobs, "advance", lambda dry: [])
    monkeypatch.setattr(dispatch, "research_work", lambda: None)
    monkeypatch.setattr(dispatch, "review_work", lambda: None)
    monkeypatch.setattr(dispatch, "in_stage", lambda s: [])
    ran = []
    monkeypatch.setattr(dispatch, "run_role", lambda role, cfg, why, today, dry: ran.append(role) or
                        {"status": "ok", "date": str(today), "note": ""})
    cfg = {"weekly_claude_run_cap": 25, "roles": {r: {"enabled": True} for r in ("scout", "director")}}
    a = SimpleNamespace(force=[], dry_run=False)
    dispatch.run_roles(date(2026, 11, 7), a, cfg, {"scout": "scouting", "director": "weekly review"},
                       ops_monitor.Findings(), [], {}, [])
    assert ran == ["director"]                       # cap reached: scout skipped, weekly review still runs
