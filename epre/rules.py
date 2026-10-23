"""The trade rule, identical to the research config EPRE (1, "through", "none") in PROTOCOL12.

Reaction session (d0) = the first session whose OPEN can reflect the report:
  report before 09:30 ET on a session day  -> that session
  report at/after 09:30 ET on a session day -> the next session
  report on a non-session day              -> the next session
Entry = close of the session two sessions before d0. Exit = close of d0.
"""

from __future__ import annotations

from datetime import date

from . import nyse
from .config import BMO_CUTOFF_MIN


def reaction_session(report_day: date, minute_of_day: int) -> date:
    if nyse.is_session(report_day):
        return report_day if minute_of_day < BMO_CUTOFF_MIN else nyse.next_session(report_day)
    return nyse.next_session(report_day)


def entry_session(d0: date) -> date:
    return nyse.prev_session(nyse.prev_session(d0))
