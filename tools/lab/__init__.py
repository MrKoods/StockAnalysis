"""The team's research tools, built by the Engineer on the Director's request (build mode, user 2026-11-14).

Use from a research script or strategy:   from lab import <module>

Rules (tools/engineer.py enforces them; the Auditor reviews every one):
  - pure functions: data comes in as arguments (DataFrames/strings a script got from research_data), results go
    out as return values. No file, network, clock or process access - so research_data's TEAM_DATA_END cutoff
    still guards the holdout for anything built here.
  - every module has tests (tests/test_lab_<module>.py) and a docstring whose first line says what it does - that
    line is what the data catalog (state/data_catalog.md) shows the other roles.
  - FROZEN once used: a module imported by a locked research plan (research/<id>/plan.lock) or a paper strategy can
    no longer change. A better version is a new module (<name>_v2.py), so a pre-registered test keeps the exact code
    it was registered with.
"""
