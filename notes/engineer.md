# Engineer notes

## Fixed
- 2026-11-11: scan_ops false-flagged its OWN task "exited with an error" (2026-11-10). Same sleep event as the
  QuoteClose ticket: machine asleep 10:00-15:30, pre-sleep ScanOps run terminated -> stale non-OK LastResult; a
  post-wake snapshot showed State != "Running" so the `State=="Running"` self-skip (scan_ops.py:94) missed it,
  and retry_until=null sent it straight to a give-up ticket. scan_ops never actually crashed (clean logs, no
  traceback, ran fine before/after). Fix: `OWN_TASK` + `if name == OWN_TASK: continue` after the drift check -
  scan_ops no longer judges its own run outcome; ops_monitor.check_tasks (ops_monitor.py:92) is the real ScanOps
  watchdog. Proven by tests/test_eng_scan_ops_self_flag.py. If a self-ticket recurs, this is where to look.
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
