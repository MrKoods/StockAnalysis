import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import dispatch  # noqa: E402
import ops_monitor  # noqa: E402
import paper_runner as pr  # noqa: E402

D = [date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21), date(2026, 10, 22)]


def frame(rows):
    return pd.DataFrame(rows, columns=["Open", "High", "Low", "Close", "Volume"], index=D[: len(rows)])


@pytest.fixture
def bars():
    flat = [[100, 101, 99, 100, 1]] * 4
    return {
        "SPY": frame(flat),
        "UP": frame([[50, 51, 49, 50, 1], [100, 104, 99, 103, 1], [103, 106, 102, 105, 1], [105, 110, 104, 108, 1]]),
        "DROP": frame([[50, 51, 49, 50, 1], [100, 100, 94, 95, 1], [95, 96, 90, 91, 1], [91, 92, 90, 91, 1]]),
    }


def row(t, side="long", sig="2026-10-19"):
    return {"strategy": "x", "signal_date": sig, "ticker": t, "side": side, "status": "pending"}


SPEC = {"hold_sessions": 0, "exit_at": "close", "cost_bps": 10}


def test_entry_next_open_exit_same_close(bars):
    r = pr.advance(row("UP"), SPEC, bars, D)
    assert r["status"] == "closed" and r["entry_date"] == "2026-10-20" and r["entry_px"] == 100
    assert r["exit_px"] == 103 and r["gross_bps"] == pytest.approx(300) and r["net_bps"] == pytest.approx(290)
    assert r["hedged_bps"] == pytest.approx(290)  # SPY flat


def test_short_and_multi_day_hold(bars):
    r = pr.advance(row("DROP", "short"), SPEC | {"hold_sessions": 2}, bars, D)
    assert r["exit_date"] == "2026-10-22" and r["gross_bps"] == pytest.approx(900)


def test_stop_checked_before_target(bars):
    r = pr.advance(row("DROP"), SPEC | {"stop_pct": 5, "target_pct": 1, "hold_sessions": 2}, bars, D)
    assert r["exit_reason"] == "stop" and r["exit_px"] == pytest.approx(95)


def test_stop_gap_fills_at_open(bars):
    # entry 100 day1 (low 94 > stop 93), day2 opens 95 ... use a 4% stop on a later-day gap
    b = dict(bars)
    b["GAP"] = frame([[50, 51, 49, 50, 1], [100, 101, 99, 100, 1], [90, 91, 89, 90, 1], [90, 91, 89, 90, 1]])
    r = pr.advance(row("GAP"), SPEC | {"stop_pct": 4, "hold_sessions": 2}, b, D)
    assert r["exit_reason"] == "stop_gap" and r["exit_px"] == 90


def test_open_trade_waits_and_no_lookahead(bars):
    r = pr.advance(row("UP"), SPEC | {"hold_sessions": 2}, bars, D[:2])
    assert r["status"] == "open" and not r.get("exit_date")
    assert pr.advance(row("UP", sig="2026-10-22"), SPEC, bars, D)["status"] == "pending"
    seen = pr.truncate(bars, D[1])
    assert max(seen["UP"].index) == D[1]


def test_missing_ticker_is_void(bars):
    assert pr.advance(row("NOPE"), SPEC, bars, D)["status"] == "void"


def test_score_verdicts():
    rule = {"min_days": 3, "max_days": 5, "pass_mean_bps": 5, "pass_t": 2}
    mk = lambda vals: [{"status": "closed", "exit_date": f"d{i}", "net_bps": v} for i, v in enumerate(vals)]
    assert pr.score(mk([10, 12]), rule)["verdict"] == "COLLECTING"
    assert pr.score(mk([10, 12, 11]), rule)["verdict"] == "PASS"
    assert pr.score(mk([10, -12, 3]), rule)["verdict"] == "CONTINUE"
    assert pr.score(mk([10, -12, 3, 1, -2]), rule)["verdict"] == "FAIL"
    assert pr.score(mk([-50, -40]), rule | {"early_fail_days": 2, "early_fail_mean_bps": -30})["verdict"] == "FAIL"


def test_last_due_weekly_mask():
    weekdays = {"Kind": "MSFT_TaskWeeklyTrigger", "Start": "2026-10-13T14:45:00-07:00", "Days": 62}  # Mon-Fri
    sat = datetime(2026, 10, 31, 10, 0)
    assert ops_monitor.last_due([weekdays], sat) == datetime(2026, 10, 30, 14, 45)
    tue_morning = datetime(2026, 10, 27, 9, 0)
    assert ops_monitor.last_due([weekdays], tue_morning) == datetime(2026, 10, 26, 14, 45)
    new_today = {**weekdays, "Start": "2026-10-27T14:50:00"}  # registered Tue 1 AM
    assert ops_monitor.last_due([new_today], tue_morning) is None


def test_task_not_run_and_failed():
    f = ops_monitor.Findings()
    trig = [{"Kind": "MSFT_TaskDailyTrigger", "Start": "2026-10-01T06:00:00", "Days": None}]
    now = datetime(2026, 10, 27, 15, 0)
    tasks = [{"Name": "StockAnalysis_A", "State": "Ready", "LastRun": "2026-10-26T06:00:05", "LastResult": 0, "Triggers": trig},
             {"Name": "StockAnalysis_B", "State": "Ready", "LastRun": "2026-10-27T06:00:05", "LastResult": 1, "Triggers": trig},
             {"Name": "StockAnalysis_C", "State": "Disabled", "LastRun": None, "LastResult": 0, "Triggers": trig}]
    ops_monitor.check_tasks(tasks, now, f)
    assert f.tasks_checked == 2 and len(f.alerts) == 2 and "A did NOT run" in f.alerts[0]
    assert len(f.diagnose) == 1 and "B ran" in f.diagnose[0]


def test_auditor_saturday_only():
    f = ops_monitor.Findings()
    assert "auditor" in dispatch.triggers(date(2026, 10, 31), f, [], {}, {})       # Saturday
    assert "auditor" not in dispatch.triggers(date(2026, 10, 30), f, [], {}, {})   # Friday


def test_checkpoint_crossing():
    snap = ("Rank-track go/no-go: COLLECTING (100/100 closed trades)\n[G2 paper] 20 days, 113 trades\n"
            "[EPRE paper] signals logged 1150 | open 140 | new today 0")
    cur = dispatch.metrics(snap)
    assert cur["V4 EPRE (closed trades)"] == 1010
    prev = {"V2 rank go/no-go (closed trades)": 99, "V3 G2 paper (days)": 20, "V4 EPRE (closed trades)": 990}
    hits = dispatch.crossed(prev, cur)
    assert any("rank" in h for h in hits) and any("EPRE" in h for h in hits)
    assert not any("G2 paper" in h for h in hits)  # already at 20 yesterday
    assert dispatch.crossed({}, cur) == []          # first run sets the baseline, no false alarm


# --- checks taken over from the old review agent (2026-11-01) ---
import integrity  # noqa: E402

SNAP = """[threshold] closed 31 | mean R +0.328 | win 45%
   closed 2026-10-30: AMGN win +3.92R
[rank] closed 65 | mean R +0.052 | win 38%
   new signals 2026-10-30: ADI bullish (shares), QCOM bearish (shares)
[random] closed 24 | mean R -0.302 | win 29%
   new signals 2026-10-30: MU bearish (shares)
   Rank-track go/no-go: COLLECTING (65/100 closed trades)
     mean R after costs -0.006 (need >= +0.15) | week-clustered t -0.25
     random-pick control: 24 closed, mean R after costs -0.356
[G2 paper] 16 days, 152 trades | mean -19.563 bps | day-t -1.36 | last day 2026-10-30: -64.956
[ON1 paper] 13 days, 962 trades | mean +53.491 bps | day-t nan | last day 2026-10-29: -81.035
  [EPRE paper] closed 388 | hedged mean -6.9 bps (net unhedged +42.6) | exit-day t -0.39 (3 days) | x
"""


def test_digest_order_and_tracks():
    d = ops_monitor.digest(SNAP)
    assert d[0] == "V2 rank: 65/100 closed, -0.006R after costs (GO needs +0.15)"
    assert d[1] == "V2 random control: 24 closed, -0.356R"
    assert "V3 ON1 paper: day 13, mean +53.491 bps, t nan" in d
    assert "V4 EPRE: 388/1,000 closed, hedged -6.9 bps, t -0.39" in d
    assert "  threshold closed today: AMGN win +3.92R" in d
    assert "  rank new today: ADI bullish, QCOM bearish" in d
    assert not any("MU" in x for x in d)  # random track's daily picks are noise - not posted


def test_snapshot_bang_lines(monkeypatch, tmp_path):
    monkeypatch.setattr(ops_monitor, "STATE", tmp_path)
    out = ("   !! 2 new row(s) not 'shares' although shares_only is on: ['A']\n"
           "   !! loss cluster 2026-10-23: 6 bullish losses on one day\n")
    monkeypatch.setattr(ops_monitor.subprocess, "run",
                        lambda *a, **k: type("R", (), {"stdout": out, "stderr": "", "returncode": 0})())
    f = ops_monitor.Findings()
    ops_monitor.check_snapshot(f)
    assert any("not 'shares'" in x for x in f.diagnose) and f.notes == ["loss cluster 2026-10-23: 6 bullish losses on one day"]
    f2 = ops_monitor.Findings()
    ops_monitor.check_snapshot(f2)
    assert f2.notes == []  # a cluster is reported once, not every day it stays in the 7-day window


def v2_row(**kw):
    r = {"signal_date": "2026-10-28", "ticker": "A", "direction": "bullish", "fill_date": "2026-10-29",
         "exit_date": "2026-10-30", "achieved_rr": 1.0, "entry_price": 10, "fill_price": 10, "exit_price": 11,
         "stop_loss": 9}
    return {**r, **kw}


def test_integrity_v2():
    today = date(2026, 10, 30)
    ok = pd.DataFrame([v2_row(), v2_row(ticker="B", achieved_rr=-1.75)])  # gap-through loss is legit
    assert integrity.v2_checks(ok, "V2 rank", today) == []
    bad = pd.DataFrame([v2_row(), v2_row(), v2_row(ticker="C", exit_date="2026-10-28", achieved_rr=12.0, exit_price=0)])
    msgs = " | ".join(integrity.v2_checks(bad, "V2 rank", today))
    assert "1 duplicate" in msgs and "exit before fill" in msgs and "outside" in msgs and "exit_price <= 0" in msgs
    assert "stopped updating" in " ".join(integrity.v2_checks(ok, "V2 rank", date(2026, 11, 5)))


def test_integrity_v4_and_seen(monkeypatch, tmp_path):
    d = pd.DataFrame([{"entry_day": "2026-10-28", "exit_day": "2026-10-28", "ticker": "X", "ret_bps": 9000,
                       "net_bps": 1, "hedged_bps": 1, "entry_close": 5, "exit_close": 5}])
    msgs = " | ".join(integrity.v4_checks(d, date(2026, 10, 28)))
    assert "on/before entry" in msgs and "|ret_bps| > 5000" in msgs
    two = pd.DataFrame([{"entry_day": e, "exit_day": "2026-11-05", "ticker": "CG", "report_day": "2026-11-04"}
                        for e in ("2026-11-02", "2026-11-03")])
    assert "duplicate row(s) on ticker+report_day" in " ".join(integrity.v4_checks(two, date(2026, 11, 3)))
    monkeypatch.setattr(integrity, "SEEN", tmp_path / "seen.json")
    monkeypatch.setattr(integrity, "scan", lambda today=None: ["p1"])
    assert integrity.check() == (["p1"], [])
    assert integrity.check() == ([], ["p1"])  # known problem: no second wake-up


import outlook  # noqa: E402


def test_outlook_arithmetic():
    s = outlook.v2_line("COLLECTING (65/100 closed trades)\n     mean R after costs -0.006 (need")
    assert "+0.440R" in s and "+0.011R" in s
    per_day = pd.Series([-20.0] * 16)
    s = outlook.v3_line("G2 paper", per_day)
    assert "day 16/20" in s and "must average +80.0" in s  # (0*20 - (-320)) / 4
    assert "past the last checkpoint" in outlook.v3_line("x", pd.Series([1.0] * 41))
