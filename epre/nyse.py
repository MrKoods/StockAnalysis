"""NYSE trading calendar (no third-party calendar package installed).

Full-day holidays and 1 PM early closes, hand-entered from the NYSE schedule through 2028.
`covered()` lets callers refuse to compute sessions past the table instead of silently guessing.
"""

from __future__ import annotations

from datetime import date, timedelta

HOLIDAYS = {date.fromisoformat(d) for d in [
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03",
    "2026-09-07", "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18", "2027-07-05",
    "2027-09-06", "2027-11-25", "2027-12-24",
    "2028-01-17", "2028-02-21", "2028-04-14", "2028-05-29", "2028-06-19", "2028-07-04", "2028-09-04",
    "2028-11-23", "2028-12-25",
]}
EARLY_CLOSE = {date.fromisoformat(d) for d in ["2026-11-27", "2026-12-24", "2027-11-26", "2028-07-03",
                                                "2028-11-24"]}
LAST_COVERED = date(2028, 12, 31)


def covered(d: date) -> bool:
    return d <= LAST_COVERED


def is_session(d: date) -> bool:
    return d.weekday() < 5 and d not in HOLIDAYS


def next_session(d: date) -> date:
    """First session strictly after d."""
    d += timedelta(days=1)
    while not is_session(d):
        d += timedelta(days=1)
    return d


def prev_session(d: date) -> date:
    """Last session strictly before d."""
    d -= timedelta(days=1)
    while not is_session(d):
        d -= timedelta(days=1)
    return d


def session_on_or_after(d: date) -> date:
    return d if is_session(d) else next_session(d)
