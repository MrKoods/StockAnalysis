from datetime import date

import numpy as np

from epre import nyse
from epre.rules import entry_session, reaction_session


def test_holidays_are_weekdays_and_complete():
    assert all(d.weekday() < 5 for d in nyse.HOLIDAYS)
    for y in (2026, 2027, 2028):
        assert 9 <= sum(d.year == y for d in nyse.HOLIDAYS) <= 10
    assert not nyse.EARLY_CLOSE & nyse.HOLIDAYS


def test_reaction_session_cases():
    # Thu 2026-10-22: before open -> same day; after close -> Fri
    assert reaction_session(date(2026, 10, 22), 7 * 60) == date(2026, 10, 22)
    assert reaction_session(date(2026, 10, 22), 16 * 60) == date(2026, 10, 23)
    assert reaction_session(date(2026, 10, 22), 9 * 60 + 30) == date(2026, 10, 23)
    # after close Wed before Thanksgiving -> Fri (early close)
    assert reaction_session(date(2026, 11, 25), 16 * 60) == date(2026, 11, 27)
    # Saturday report -> Monday regardless of time
    assert reaction_session(date(2026, 10, 24), 7 * 60) == date(2026, 10, 26)


def test_entry_is_two_sessions_before():
    assert entry_session(date(2026, 10, 23)) == date(2026, 10, 21)
    assert entry_session(date(2026, 10, 26)) == date(2026, 10, 22)      # Mon -> Thu
    assert entry_session(date(2026, 11, 27)) == date(2026, 11, 24)      # skips Thanksgiving


def test_matches_research_mapping():
    """Same answer as PROTOCOL12's numpy mapping (events.load_earnings) on every day in a span."""
    sessions = []
    d = date(2026, 10, 1)
    while d < date(2027, 3, 1):
        if nyse.is_session(d):
            sessions.append(d)
        d = date.fromordinal(d.toordinal() + 1)
    S = np.array(sessions, dtype="datetime64[D]")
    for o in range(date(2026, 10, 5).toordinal(), date(2027, 2, 15).toordinal()):
        day = date.fromordinal(o)
        for minute in (7 * 60, 9 * 60 + 29, 9 * 60 + 30, 16 * 60):
            sess = np.searchsorted(S, np.datetime64(day), side="left")
            same = sessions[sess] == day
            k = sess if minute < 570 else (sess + 1 if same else sess)
            assert reaction_session(day, minute) == sessions[k]
            assert entry_session(sessions[k]) == sessions[k - 2]


def test_upcoming_placeholder_follows_dst(monkeypatch):
    """2026-11-02: Yahoo's 'time unknown' for an upcoming report moved 15:00 -> 16:00 ET when DST ended."""
    import pandas as pd
    from epre import calendar as cal

    def frame(upcoming_min, past_min):
        ts = [pd.Timestamp(f"2026-0{m}-05", tz="America/New_York") for m in (2, 5, 8)]
        ts = [t + pd.Timedelta(minutes=past_min) for t in ts] + \
             [pd.Timestamp("2026-11-04", tz="America/New_York") + pd.Timedelta(minutes=upcoming_min)]
        return pd.DataFrame({"ts": ts, "minute": [past_min] * 3 + [upcoming_min], "reported": [True] * 3 + [False]})

    today = date(2026, 11, 2)
    monkeypatch.setattr(cal, "earnings_frame", lambda t, limit=8: frame(16 * 60, 6 * 60))   # CG: BMO habit
    ev = cal.next_event("CG", today)
    assert ev["time_source"] == "history" and ev["bmo"]
    monkeypatch.setattr(cal, "earnings_frame", lambda t, limit=8: frame(16 * 60, 16 * 60))  # past 16:00 = real AMC
    ev = cal.next_event("AAPL", today)
    assert ev["time_source"] == "history" and not ev["bmo"]
    monkeypatch.setattr(cal, "earnings_frame", lambda t, limit=8: frame(8 * 60, 16 * 60))   # a real upcoming time
    assert cal.next_event("X", today)["time_source"] == "yahoo"


def test_variant_ml_counts_only_forward_mid_large_trades():
    import pandas as pd
    from epre import paper
    rows = []
    for i in range(800):
        rows.append({"entry_day": "2026-11-24" if i % 2 else "2026-11-20", "exit_day": f"2026-12-{1 + i % 20:02d}",
                     "index": ["sp500", "sp400", "sp600", "sp500"][i % 4], "hedged_bps": 15.0 + (i % 7),
                     "date_ok": "True"})
    led = pd.DataFrame(rows)
    out = paper.variant_ml_verdict(led)
    # forward (odd i) AND sp500/sp400: i % 4 in (1, 3) -> sp400 / sp500, all odd -> 400 trades
    assert "400 closed" in out and "collecting (400/700" in out
    assert "no closed trades yet" in paper.variant_ml_verdict(led[led["entry_day"] < paper.ML_START])
    big = pd.concat([led[led["entry_day"] >= paper.ML_START]] * 2)
    big = big.assign(hedged_bps=-30.0)
    assert "FAIL at checkpoint A" in paper.variant_ml_verdict(big)
