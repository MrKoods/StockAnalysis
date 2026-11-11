# Engineer notes

## Fixed
- 2026-11-10: scan_ops.py recorded the same give-up failure once per 10-min tick (append was outside the `once()`
  gate), so 1 failure made N identical `issues` -> N identical Engineer tickets AND burned the attempt budget
  (engineer.py increments the attempt key once per copy). Fixed at scan_ops.py:123 with a content-dedupe; proven
  by tests/test_eng_scan_ops_dedup.py. If duplicate tickets recur, this is where to look.

## Open / for the user (not my editable files)
- 2026-11-10 QuoteClose failure root cause: machine was ASLEEP at the 12:56 PT frozen window; Task Scheduler ran
  the missed task late at 15:30 (after US close), it crashed before launching the clerk (no close jsonl / usage /
  log line). One-day gap in ON1/EPRE real-price capture; unrecoverable by design. Proposals in
  reports/2026-11-10-engineer.md: (1) keep machine awake / wake-to-run on the two Quote tasks; (2) optional
  quotes.py guard to skip a stale late run cleanly. Both need the user's session (quotes.py + tasks are off-list).

## Don't retry
- Don't try to "fix" QuoteClose in team code: quotes.py, the Windows tasks and the V4 ledger are all outside the
  editable list. If it fails again at its normal 12:56 time (machine awake) with a real traceback, THEN diagnose.
