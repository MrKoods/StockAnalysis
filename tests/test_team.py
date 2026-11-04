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
            "[EPRE paper] signals logged 1150 | open 136 | new today 0 | void 4\n"
            "[EPRE paper] closed 1010 | hedged mean +3.0 bps")    # void trades are neither open nor closed
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


def test_daily_report_sections(monkeypatch, tmp_path):
    import daily_report as dr
    monkeypatch.setattr(dr, "STATE", tmp_path)
    monkeypatch.setattr(dr, "TEAM", tmp_path)
    monkeypatch.setattr(dr.outlook, "short", lambda snap: {"ON1 paper": "PASS needs +13"})
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "2026-11-02-quotes.log").write_text(
        "2026-11-02 06:31:19 quotes open: 65/74 tickers captured (partial)\n"
        "2026-11-02 12:56:26 quotes close: 196/196 tickers captured (ok)\n", encoding="utf-8")
    f = ops_monitor.Findings(snapshot=SNAP, tasks_checked=17)
    text = dr.compose(date(2026, 11, 2), f, [])
    assert text.startswith("✅ **Daily report Mon 11-02** - all 17 scheduled jobs ran OK")
    assert "Needs you" not in text and "Quiet day" in text
    assert "• **V2 rank** - 65/100 trades · -0.006R after costs" in text
    assert "• **V3 ON1 paper** - day 13 · mean +53.5 bps · t nan\n  ↳ PASS needs +13" in text
    assert "open 65/74 (partial) · close 196/196" in text
    assert "• threshold closed: AMGN win +3.92R" in text and "• rank new signals: ADI bullish, QCOM bearish" in text
    assert "MU" not in text   # random track's daily picks are noise - not posted
    f.alerts = ["PaperRunner did NOT run"]
    assert "🛑 **Daily report Mon 11-02** - 1 problem(s)\n\n**⚠️ Needs you**\n• PaperRunner" in \
        dr.compose(date(2026, 11, 2), f, [])


def test_report_chunks_respect_discord_limit():
    import daily_report as dr
    text = "\n\n".join(["**A**\n" + "x" * 900, "**B**\n" + "y" * 900, "**C**\n" + "\n".join(["z" * 100] * 30)])
    parts = dr.chunks(text)
    assert all(len(p) <= dr.LIMIT for p in parts) and len(parts) >= 3
    assert "".join(parts).count("z" * 100) == 30


def test_evening_check_catches_dst_calendar_shift():
    import evening_check as ev
    good = {"refreshed": "2026-11-02", "events": 1458, "history_share": 0.52}
    assert ev.compare(good, good, "2026-11-02") == []
    bad = {"refreshed": "2026-11-02", "events": 1449, "history_share": 0.004}   # the real 2026-11-02 night
    assert "company history moved 52% -> 0%" in " ".join(ev.compare(bad, good, "2026-11-02"))
    stale = {**good, "refreshed": "2026-10-30"}
    assert "NOT refreshed" in " ".join(ev.compare(stale, good, "2026-11-02"))
    assert ev.compare({**good, "refreshed": "2026-11-03"}, good, "2026-11-02") == []   # late run dated in ET
    assert "shrank" in " ".join(ev.compare({**good, "events": 500}, good, "2026-11-02"))


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


def test_research_cadence(monkeypatch):
    f = ops_monitor.Findings()
    stages = {"idea": ["a", "b", "c"], "queued": ["q"]}
    monkeypatch.setattr(dispatch, "in_stage", lambda s: stages.get(s, []))
    mon = dispatch.triggers(date(2026, 11, 2), f, [], {}, {})
    assert "scout" in mon and "target 10" in mon["scout"]           # every weekday until 10 ideas wait
    assert "queue up to 1" in mon["director"]                       # room for 1 more (1 of 2 in research)
    stages["queued"] = ["q1", "q2"]
    assert "director" not in dispatch.triggers(date(2026, 11, 2), f, [], {}, {})   # pipeline full
    stages["idea"] = [str(i) for i in range(10)]
    assert "scout" not in dispatch.triggers(date(2026, 11, 2), f, [], {}, {})      # queue full
    sat = dispatch.triggers(date(2026, 11, 7), f, [], {}, {})
    assert "scout" not in sat and sat["director"] == "weekly review"


def test_screen_event_returns():
    import screen
    days = pd.bdate_range("2010-01-04", periods=6)
    opens = pd.DataFrame({"SPY": [100.0] * 6, "X": [100.0] * 6}, index=days)
    closes = pd.DataFrame({"SPY": [100.0] * 6, "X": [100, 102, 104, 106, 108, 300.0]}, index=days)
    ev = pd.DataFrame({"ticker": ["X", "X", "ZZZ"], "first_session": [days[0], days[4], days[0]]})
    drift = pd.Series({"SPY": 0.0, "X": 10.0}).reindex(closes.columns).to_numpy()
    r = screen.event_returns(ev, opens, closes, 3, drift)
    # X from the open of day 0 (100) to the close of day 2 (104) = +400 bps, minus 3 days x 10 bps drift;
    # the day-4 event has no day 6 (dropped), unknown tickers are dropped
    assert len(r) == 1 and r["gross_bps"].iloc[0] == pytest.approx(370)
    r1 = screen.event_returns(ev.iloc[1:2], opens, closes, 2, drift)
    assert r1.empty                                                 # +200% = a split/bad bar, dropped
    assert screen.family("5.02") == "8k_5_02"


def test_daily_bars_never_overwrite_with_worse(tmp_path):
    import daily_bars
    idx = pd.bdate_range("2020-01-01", periods=300)
    old = pd.DataFrame({"close": 1.0}, index=idx)
    old.to_parquet(tmp_path / "X.parquet")
    assert not daily_bars.better(old.iloc[:-1], tmp_path / "X.parquet")           # ends earlier
    longer = pd.DataFrame({"close": 1.0}, index=pd.bdate_range("2020-01-01", periods=305))
    assert daily_bars.better(longer, tmp_path / "X.parquet")
    short = pd.DataFrame({"close": 1.0}, index=pd.bdate_range("2020-06-01", periods=200))
    assert not daily_bars.better(short, tmp_path / "X.parquet")                   # partial history
    assert daily_bars.better(old, tmp_path / "missing.parquet")
