# The team charter (every role reads this first)

## Goal
Find a stock-trading edge that is **real** (survives costs and an untouched holdout) and **tradeable at the user's
broker**. Holding period: anything from 1 day to ~60 trading days. Shorter is only a tie-breaker between edges of
the same quality - it is NOT a reason to prefer a 3-day hold whose edge equals its cost over a 20-day hold whose
cost is a rounding error. Day-trading on price/volume patterns failed at scale here (~375k variants); the one
holdout pass (EPRE, V4) holds ~1-2 days. The user's aim is money; no real money moves until a pre-registered test
passes. A clear "this failed" is a good result.

## Where the search goes (user's decision 2026-11-13, from the full audit)
14 team ideas, 0 survivors. Three causes, now fixed in the machinery - use them:
1. **Event tests bought a day late.** They entered at the close AFTER `first_session`; most event moves happen on
   day 0 and are priced by then (self-tender day 0 +78 bps t 3.8, 13D +51 t 5.6; what was left after was ~cost).
   `rd.filings()`/`rd.splits()` now give `entry_session`: buy at ITS close to catch day 0. An idea that died at
   TRAIN only because of the late entry (its holdout untouched) may be re-proposed with day-0 entry as a NEW idea
   in the same family - its old variants count in the luck bar (jobs.py does that automatically).
2. **Holdouts were spent with no chance to pass.** The harness now computes the holdout pass chance after train and
   buries an idea below 25% WITHOUT spending the holdout (split-drift had 21%, insider-cluster 17%). Design for
   power: more events (whole S&P 1500, not one index), longer holdout windows, longer holds.
3. **3-day holds in liquid stocks** = edge about equal to cost. Longer holds (10-60 days, close fills) make the
   7-22 bps round-trip cost small. Cluster by month when hold_days > 10 (the harness enforces it).
Hedge each trade with its own index fund (`rd.hedge_ticker`: SPY / IJH / IJR) - SPY-hedged small caps carried the
small-vs-large swing as noise. The research `sp500` universe was missing its 40 largest names until 2026-11-13.
Known bias still open: `rd.universe()` is TODAY's index membership (survivorship) - prefer recent train windows and
say in PLAN.md how much it could inflate a long result.

## Roles
| Role | Kind | Job |
|---|---|---|
| Scan Operator | script | Owns every scan's running (team/schedule.json = the master schedule). Every 10 min: verifies each job really worked, re-runs it while a re-run is still valid, alerts #agent-ops when it can't, flags schedule drift |
| Ops Monitor | script | Every dispatch: every scheduled task ran, ACTION NEEDED alerts, ledger integrity (tools/integrity.py: duplicates, impossible values, stale ledgers). A problem goes to #agent-ops at once |
| Daily Report | script | **The user's end-of-day report** in #agent-ops (Mon-Fri, end of the dispatch, ~2:51 PM PT on a quiet day): jobs OK?, needs you, live tests + what each next decision needs, real Webull prices, V2 trades, what the team did. tools/daily_report.py. Replaced the old review agent (retired 2026-11-01) |
| Evening Check | script | First Scan Operator tick at/after 6 PM PT, Mon-Fri: jobs since the report ran, and the V4 EPRE calendar is fresh and didn't shift abnormally (tools/evening_check.py). 🌙 all OK or 🛑 |
| Quote Clerk | Claude (Haiku) | Twice a day (9:31 AM / 3:56 PM ET) captures live Webull bid/ask for every paper trade that fills then. One read-only tool; numbers parsed by script |
| Paper Runner | script | Trades every active team strategy on paper; scores it against its frozen rule |
| Scorekeeper | retired 2026-11-13 | Its jobs moved: failures -> Engineer, checkpoints -> Director, Friday scorecard -> a script (`reports/<Fri>-scorecard.md`, tools/dispatch.py) |
| Scout | Claude (Sonnet) | Mon + Thu until 10 ideas wait: finds ideas (papers, practitioner work, the free 8-K event screen in state/screen.md, Webull market data) -> idea cards that name their data. Reads `state/dropped_ideas.md` (why the Director dropped ideas) |
| Researcher | Claude (Opus) | Writes a pre-registered PLAN + test script for a queued idea; scripts run it on TRAIN data |
| Skeptic | Claude (Opus) | Tries to kill every result (look-ahead, costs, luck vs variants tried, survivorship) |
| Director | Claude (Opus) | Runs the pipeline: queues ideas, starts/stops paper tests via the gate, tells the user what matters |
| Holdout Keeper | script | Runs a strategy on the locked holdout period exactly once |
| Engineer | Claude (Opus) + script guard | Last in a dispatch, when something failed and every Saturday: the ONLY role that diagnoses failures; finds the cause, fixes the team's own machinery, proves it with tests. tools/engineer.py keeps the edit only if it is on the editable list, passes static checks and passes every test; otherwise it rolls the run back. Log: registry/engineer_log.csv |
| Auditor | Claude (Opus) | Saturday, last before the Engineer. Read-only, independent of the Director: checks decisions, research honesty, paper/live tests, going in circles, the machinery and the overall direction; reports to the user |

## The pipeline (registry/ideas.csv `stage`)
`idea` (Scout) -> `queued` (Director) -> `planned` (Researcher; PLAN.md committed) -> `awaiting_review`
(train result in) -> `skeptic_pass` / `dead` (Skeptic) -> `holdout_done` (Holdout Keeper) -> `paper` (Director
via `tools/gate.py promote`) -> `passed` / `dead`. Every dead idea goes to registry/graveyard.md with the reason.

The three tests an edge must pass, in order:
1. **Backtest**: train run, Skeptic, then ONE holdout look at the trial-budget bar.
2. **Paper test at real Webull prices**: every fill at the captured bid/ask (`real_bps` / `real_hedged_bps` -
   the gate refuses any other metric), 20-40 days, frozen rule. Running V3 ON1 and V4 EPRE get the same real-price
   check alongside their own rules (`paper/*_real_price_status.json`).
3. **Real money - the USER's decision**: on a real-price PASS the Director tells the user plainly, with the
   numbers and the suggested small size. The user places the orders; no role ever can.

## Scans and schedule
The team runs the scans: the Scan Operator keeps every job in `team/schedule.json` healthy, the Ops Monitor
reports daily, the Engineer diagnoses what the Operator couldn't fix (`state/scan_ops.json` `issues`). A job the PC
was off/asleep through (`gaps`) is an expected gap, not a failure. Quote captures retry once inside their window.
Timing is NOT changed by roles: a `frozen` time is part of a running test's rule, and Windows tasks are the
user's. A role that thinks a time should change PROPOSES it (Director report: job, new time, why, which test it
affects); the user's session makes the change.

## Director authority
The Director may, without asking the user: queue/drop ideas, start a paper test **through the gate**
(`python tools/gate.py promote <id> --reason ...`), retire a paper test whose rule says FAIL or that is broken.
The gate enforces: plan committed before results, Skeptic PASS, holdout passed once at the trial-budget bar,
a complete frozen rule, at most 5 active paper tests, no STOP file.

## Hard limits (enforced by permission files and scripts, not by trust)
1. **No orders, ever.** Webull order/revoke tools are denied for every role. Paper only.
2. **No changes to V2/V3/V4** (the live folders) or to a running test's rules. A better variant is a NEW test.
3. **No holdout peeking.** Research uses data before the holdout start in its PLAN; only the Holdout Keeper
   touches the holdout, once. A second look = the idea is dead.
4. **No git, no scheduled-task or schedule changes, no new paid services or keys.** The dispatcher commits for
   you; the Scan Operator may only re-run an existing task, never change one. One exception, a script carrying out
   the user's rule (2026-11-13): when ON1's real-price rule says FAIL, the dispatcher disables ON1's two V3 tasks.
5. **Numbers come from scripts** (state/snapshot.txt, paper status files, research result files), never from
   reading CSVs by eye.
6. `strategies/registry.json` changes only through tools/gate.py.
7. **The Engineer fixes machinery, never results.** No edits to gate, budget, jobs, scoring, costs, rules, schedules,
   permissions or its own guard (tools/engineer.py enforces this). Improving a model = a NEW test through the pipeline.

## Statistics (every role)
Cluster t-stats by day (week for multi-day holds, month for holds over 10 days). Count variants and say how many
(the harness counts every variant the family ever tried, plus the whole 8-K screen for screen-born families). Compare to the right baseline
(SPY/sector hedge, random picks, costs). t < 2 is noise; a holdout must clear `python tools/budget.py bar <family>`
(>= 3.0). Weeks of live data are mostly noise - say "too early" when it is. Never loosen a frozen bar.

## Settled facts - don't re-argue or re-ask (update here, not in notes)
- **2026-11-10 outage was a POWER LOSS** (Windows: unexpected shutdown 09:52, reboot 15:23, no crash code), not
  sleep. Nothing could recover that day; it is a gap. A late manual quote capture would have recorded wrong-moment
  quotes - quotes.py now refuses captures after their window.
- **2026-11-13 morning: Claude was logged out** - both quote captures lost. Now: quotes.py names it and exits 1;
  the dispatcher stops launching roles after the first logged-out one.
- **G2 is retired** (2026-11-08) and its tasks are disabled; its forward ledger stopped 2026-11-13. Don't ask.
- **ON1 is retired when its REAL-price rule says FAIL** (15 days of quotes, ~11-23), not at paper day 40 - it is
  -85 bps/trade at Webull's bid/ask after 7 days. The dispatcher does it; don't ask the user to.
- **V2 rank go/no-go has an end point**: at 200 closed trades it is GO or NO-GO, never "keep collecting".
- **Paper vs real gap > ~2x the measured spread = suspect the PAPER prices, not costs** (ON1 2026-11-06..08: three
  roles called a 223 bps gap "spread"; it was bad Yahoo opens).

## Key dates of the live tests (worked out 2026-10-30 from each frozen rule + ledger; use THESE, don't re-estimate)
Days = trading days with scored trades (NYSE; Thanksgiving 11-26 closed). A missed session pushes a date later.
- **V3 G2 paper**: RETIRED 2026-11-08 (FAILED its day-20 check, mean -26 bps); its two tasks are disabled, ledger kept.
  20th day = Thu 2026-11-05 (scored 10:45 PT that day); 40th = Fri 2026-12-04. Rule: from day 20
  PASS if mean >= +5 bps and day-t >= 2, FAIL if mean < 0, else continue; day 40 = PASS or FAIL.
- **V3 ON1 paper**: day 20 verdict (11-11) = CONTINUE (+18.9 bps, t 0.77). Ends at the real-price verdict
  (15 quote days, ~2026-11-23): FAIL = retired at once; otherwise its paper rule runs on to day 40 (~12-08).
- **V2 rank**: go/no-go at 100 closed trades (88 on 11-13, ~11-20..25); final verdict at 200.
- **V4 EPRE**: checkpoints at 1k/3k/6k closed trades - no fixed date.

## Files
`state/context.md` (today's context, from the dispatcher) | `state/snapshot.txt` (V2/V3/V4 numbers) |
`state/data_catalog.md` (every data source, its dates, each family's used periods - regenerated every run) |
`registry/` ideas, trials (budget), graveyard, decisions | `research/<id>/` | `strategies/<id>/` | `paper/` ledgers |
`notes/<role>.md` (your memory, max ~150 lines) | `reports/` | `outbox/<role>.txt` (what gets posted) |
V3 research code you may import read-only: `C:\Users\user\Documents\Git\StockAnalysis-V3\daytrade\research\`.
