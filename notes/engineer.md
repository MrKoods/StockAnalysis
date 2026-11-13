# Engineer notes

## Resolved - don't repeat (from the user's session, 2026-11-13 audit; TEAM.md "Settled facts" has the details)
- 2026-11-10 was a POWER LOSS (09:52-15:23), not sleep. A gap; nothing to fix. Gaps are now notes, not tickets.
- The quotes.py late-run guard (too_late) exists since 2026-11-11 - don't propose it again.
- G2 is retired and its tasks are off. ON1 retires automatically on its real-price FAIL. Don't ask the user.

## Open / for the user (not my editable files)
- 2026-11-13 quote_clerk failed x2 (open 06:31, close 12:56 PT): headless Claude was NOT LOGGED IN
  (`apiKeySource:"none"`, `authentication_failed`, "Not logged in · Please run /login" in both
  state/logs/2026-11-13-quote_clerk-{open,close}.jsonl; usage.csv rows at $0/0 tokens). NOT a code bug
  — clerk fired on time, Claude refused. Same-day dispatch roles (scorekeeper, scout) were OK, so login
  was absent only at the two Quote-task windows. Different from 2026-11-10 (that was a power loss).
  No code fix: quotes.py + Quote tasks + Claude login all off-list. Proposal in reports/2026-11-13-engineer.md:
  user re-logins the CLI and confirms the scheduled Quote tasks see a persistent credential. One-day
  real-price gap (ON1/EPRE), unrecoverable. If it recurs, it's STILL auth — don't try to code around it.
  UPDATE (user's session, same day): quotes.py now detects the logout, posts LOGIN_HELP and exits 1; the
  dispatcher stops launching roles after the first logged-out one. Nothing left for you here.

## Fixed
- 2026-11-12: the 2026-11-11 self-flag fix stopped NEW ScanOps self-tickets, but the stale 2026-11-10 ScanOps
  record stayed in scan_ops.json `issues` (pruned only by one-week age), so engineer.py:183-185 replayed it as a
  phantom ticket every dispatch and was about to false-escalate at the attempt cap. Completed the fix: scan_ops.run()
  now also drops any `issues` row where job==OWN_TASK on prune (scan_ops.py:150-155) - a ScanOps row there can only
  be pre-fix residue since scan_ops no longer judges its own run; real ScanOps failures are caught by
  ops_monitor.check_tasks, not this list. Proven by test_prune_drops_stale_own_task_issue. If a phantom ScanOps
  ticket recurs, check that this prune still runs and that the issue date really is a pre-fix OWN_TASK entry.
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
- 2026-11-12 (optional): engineer.py (off-list, runs the agents) re-reads scan_ops/usage failures by date window
  with no "already resolved" memory, so a fixed issue keeps ticketing until it ages out and can false-escalate at
  the attempt cap. Proposed to the user in reports/2026-11-12-engineer.md. Headed off for ScanOps at the source;
  don't try to fix engineer.py yourself.
- 2026-11-10 QuoteClose failure root cause: machine was ASLEEP at the 12:56 PT frozen window; Task Scheduler ran
  the missed task late at 15:30 (after US close), it crashed before launching the clerk (no close jsonl / usage /
  log line). One-day gap in ON1/EPRE real-price capture; unrecoverable by design. Proposals in
  reports/2026-11-10-engineer.md: (1) keep machine awake / wake-to-run on the two Quote tasks; (2) optional
  quotes.py guard to skip a stale late run cleanly. Both need the user's session (quotes.py + tasks are off-list).

## Don't retry
- Don't try to "fix" QuoteClose in team code: quotes.py, the Windows tasks and the V4 ledger are all outside the
  editable list. If it fails again at its normal 12:56 time (machine awake) with a real traceback, THEN diagnose.
