# Daily review (runs weekdays ~2:45 PM Pacific, after the last scheduled job)

Follow `agent/prompts/common.md` exactly. Today's date and the scheduled-task status table are in
`agent/state/context.txt` (written by the launcher just before you started).

## Steps

1. Read `agent/NOTES.md`, `agent/state/context.txt`.
2. **Health.** Did every scheduled job run and succeed today (task table: LastTaskResult 0, last run
   today)? Run `python agent/tools/snapshot.py`. Look for: errors/tracebacks, a ledger that didn't
   update, data gaps, new V2 rows that aren't `shares`, duplicate rows, impossible values (exit
   before fill, R far beyond -1.2 or +4.5, negative prices), a sector over its 2-per-day budget.
   If something looks wrong, dig in (read the relevant log tail and code) until you know the cause.
3. **Results.** What opened, closed, filled or expired today, per track/strategy. Progress toward
   each frozen pass/fail rule. Anything statistically notable — but say "noise" when it is noise.
4. **Fix if broken.** For a clear bug (crash, wrong calculation, data corruption), prepare the fix in
   your workspace with a test, run the full test suite, and commit `PROPOSED FIX: ...`. Do not fix
   strategy behavior you merely disagree with — note it for the weekly review instead.
5. **Write the report** to `agent/reports/<today>-daily.md`: Health (OK / problems), Today's
   activity, Progress vs rules, Proposed fixes (if any), Watch list. Plain English first, numbers
   second. Keep it under ~80 lines.
6. **Write `agent/reports/discord.txt`** — the message the user sees, max 1,500 characters, plain
   text, no tables. First line exactly one of:
   - `✅ Daily review <date>: all systems normal`
   - `⚠️ Daily review <date>: <n> issue(s) - <short>`
   - `🛑 Daily review <date>: ACTION NEEDED - <short>`
   Then 3-8 short lines: what happened today, any issue, any proposed fix awaiting approval.
7. Update `agent/NOTES.md`, then `git add agent/reports agent/NOTES.md` (plus any proposed-fix
   files) and commit on `agent`.

Use ACTION NEEDED only when something is broken or a decision is required from the user.
