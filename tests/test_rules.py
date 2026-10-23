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
