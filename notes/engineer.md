# Engineer notes

## Resolved - don't repeat (from the user's session, 2026-11-13 audit; TEAM.md "Settled facts" has the details)
- 2026-11-10 was a POWER LOSS (09:52-15:23), not sleep. A gap; nothing to fix. Gaps are now notes, not tickets.
- The quotes.py late-run guard (too_late) exists since 2026-11-11 - don't propose it again.
- G2 is retired and its tasks are off. ON1 retires automatically on its real-price FAIL. Don't ask the user.

## Resolved - don't repeat (weekly review 2026-11-14)
- The weekly "Refused for …" ticket list is role-side, NOT machinery. Every plain-command refusal targets a
  tool/subcommand that doesn't exist: usage.py, research.py, graveyard.py, edgar_forms_probe.py (no such files);
  ideas.py has only list/add/set (no `get`); engineer.py has only tickets/check (no `log`); research_data has no
  CLI (filings() is a function, research_data.py:273). The rest are banned shell syntax (pipes/-c/;/&&/2>/dev/null
  /heredoc). Don't propose permission-allowlist changes for these — nothing real is being blocked. If this list
  keeps growing, the only fix is a "tools that exist" crib in common.md (off-list; user proposal). Don't re-diagnose.
- 11-10 QuoteClose x5 stale `issues` in scan_ops.json are real power-loss give-up records (not OWN_TASK), pruned
  by one-week age -> gone 11-17. Leave them; auditor called them settled.

## Open / for the user (not my editable files)
- 2026-11-19 V4 EPRE Signals scan crashed: `KeyError: 'posted'` at StockAnalysis-V4\epre\paper.py:185
  (`buys["posted"]`), called from signals() line 239 -> _lines(). ROOT CAUSE paper.py:233:
  `rows[[...comprehension...]]` -> when rows is EMPTY the list is `[]` and pandas `df[[]]` selects ZERO
  COLUMNS (not zero rows), dropping `posted` + all cols. Empty rows = a zero-new-entry day (mid-Nov
  earnings lull) OR all candidates already held. Ran fine 10-26..11-18 because every day had >=1 entry;
  first zero-entry day = first crash. Line 230 is safe (.isin -> bool Series); only 233 uses a raw list.
  OFF-LIMITS (V4 live folder) -> proposal in reports/2026-11-19-engineer.md: wrap the comprehension in
  `np.array(..., bool)` (the idiom already at lines 105/169). Will recur EVERY zero-entry day until fixed;
  blocks EPRE paper entries + real-price capture those days. Don't try to code-fix in team code or write a
  V4 test. If it recurs after the user's fix, re-check paper.py:233 uses a numpy bool array.
- Webull connector dark since 11-11 (TEAM.md Settled fact: 11-13..20, 6 days 0/N quotes): quotes.py exits 1 with
  `(webull_auth)`; Quote tasks record result 1. User-only fix (claude.ai -> Settings -> Connectors -> Webull).
  Real-price gap is unrecoverable while dark; ON1 real-price verdict + EPRE need it (due ~Mon 11-23). CONFIRMED
  pattern - don't re-diagnose. STOPPED the daily Engineer ticket (see Fixed, 2026-11-21): ops_monitor now alerts
  the user but no longer diagnoses a webull_auth Quote give-up. If a Quote ticket recurs from a DIFFERENT cause
  (webull_signed_out False) it will diagnose again - that one IS worth a look.
- 2026-11-20 integrity ON1 forward "1 row |bps|>5000": the row is `2026-10-20,sp500,-8709.49` (on1_forward_trades.csv
  line 658), a -87% one-night move = one bad underlying V3 price. families2.run computes the bps, forward.update_on1
  (V3 daytrade\forward.py:119-130) pools every finite bps with NO per-stock sanity clip. Same class as the known
  "bad Yahoo opens inflated ON1". integrity.py (BPS_MAX=5000) is CORRECT - don't quiet it; it reports once, so it
  won't re-ticket. OFF-LIMITS (V3). Impact low (corrupts one day of the secondary forward stat, not the real-price
  status; ON1 retiring ~11-23). Proposal 11-20: V3 clip overnight |bps|>5000 before pooling. Don't re-diagnose.
- 2026-11-16 paper_runner premarket SEC error ticket = transient `All retries exhausted` to www.sec.gov at
  05:42 (1 of 528 lines, amid Yahoo-down + SEC 400s that morning). V2 live-folder log; snapshot.py (off-list)
  counts it, ops_monitor forwards non-outage error lines to diagnose as designed. Transient external blip,
  nothing to fix. Don't re-diagnose a single transient SEC/Yahoo error line as machinery.
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
- 2026-11-21: webull_auth Quote give-ups no longer wake the Engineer daily (auditor Rec #1). ops_monitor.check_tasks
  already detected `webull_signed_out` and named the user fix in the alert, but line 145 appended the failure to
  `f.diagnose` UNCONDITIONALLY -> engineer.prepare minted a ticket every dark day (9 of 11 "couldn't fix" autonomy
  hits this week). Fix: webull_auth Quote give-up -> alert only, NO diagnose (same as a PC-off gap). Other Quote
  failures + non-Quote failures still diagnose. Proven by tests/test_eng_webull_auth_no_ticket.py. If a Quote
  ticket recurs, confirm webull_signed_out() still reads `(webull_auth)` from the day's quotes.log before assuming
  this fix broke - a real non-auth Quote failure SHOULD still ticket.
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
