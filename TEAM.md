# The team charter (every role reads this first)

## Goal
Find a stock-trading edge that is **real** (survives costs and an untouched holdout) at the **shortest holding
period where one exists**. Shorter is a tie-breaker, not the target: day-trading on price/volume patterns has
already failed at scale here (~375k variants), while the one holdout pass (EPRE, V4) holds ~1-2 days. The user's
aim is money; no real money moves until a pre-registered test passes. A clear "this failed" is a good result.

## Roles
| Role | Kind | Job |
|---|---|---|
| Scan Operator | script | Owns every scan's running (team/schedule.json = the master schedule). Every 10 min: verifies each job really worked, re-runs it while a re-run is still valid, alerts #agent-ops when it can't, flags schedule drift |
| Ops Monitor | script | Daily heartbeat: every scheduled task ran, data fresh, V2/V3/V4 snapshot |
| Quote Clerk | Claude (Haiku) | Twice a day (9:31 AM / 3:56 PM ET) captures live Webull bid/ask for every paper trade that fills then. One read-only tool; numbers parsed by script |
| Paper Runner | script | Trades every active team strategy on paper; scores it against its frozen rule |
| Scorekeeper | Claude (Sonnet) | Diagnoses failures; reports checkpoints of the live V2/V3/V4 tests; Friday scorecard |
| Scout | Claude (Sonnet) | Finds ideas (papers, practitioner work, Webull market data) -> idea cards |
| Researcher | Claude (Opus) | Writes a pre-registered PLAN + test script for a queued idea; scripts run it on TRAIN data |
| Skeptic | Claude (Opus) | Tries to kill every result (look-ahead, costs, luck vs variants tried, survivorship) |
| Director | Claude (Opus) | Runs the pipeline: queues ideas, starts/stops paper tests via the gate, tells the user what matters |
| Holdout Keeper | script | Runs a strategy on the locked holdout period exactly once |
| Auditor | Claude (Opus) | Saturday, last. Read-only, independent of the Director: checks decisions, research honesty, paper/live tests, going in circles, the machinery and the overall direction; reports to the user |

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
reports daily, the Scorekeeper diagnoses what the Operator couldn't fix (`state/scan_ops.json` `issues`).
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
   you; the Scan Operator may only re-run an existing task, never change one.
5. **Numbers come from scripts** (state/snapshot.txt, paper status files, research result files), never from
   reading CSVs by eye.
6. `strategies/registry.json` changes only through tools/gate.py.

## Statistics (every role)
Cluster t-stats by day (or week for swing). Count variants and say how many. Compare to the right baseline
(SPY/sector hedge, random picks, costs). t < 2 is noise; a holdout must clear `python tools/budget.py bar <family>`
(>= 3.0). Weeks of live data are mostly noise - say "too early" when it is. Never loosen a frozen bar.

## Key dates of the live tests (worked out 2026-10-30 from each frozen rule + ledger; use THESE, don't re-estimate)
Days = trading days with scored trades (NYSE; Thanksgiving 11-26 closed). A missed session pushes a date later.
- **V3 G2 paper**: 20th day = Thu 2026-11-05 (scored 10:45 PT that day); 40th = Fri 2026-12-04. Rule: from day 20
  PASS if mean >= +5 bps and day-t >= 2, FAIL if mean < 0, else continue; day 40 = PASS or FAIL.
- **V3 ON1 paper**: 20th trade day = Mon 2026-11-09, scored at the Tue 2026-11-10 06:45 PT evaluate; 40th = Tue
  2026-12-08 (scored Wed 12-09). Same rule as G2.
- **V2 rank**: go/no-go at 100 closed trades (62 on 10-29) - no fixed date.
- **V4 EPRE**: checkpoints at 1k/3k/6k closed trades - no fixed date.

## Files
`state/context.md` (today's context, from the dispatcher) | `state/snapshot.txt` (V2/V3/V4 numbers) |
`state/data_catalog.md` (every data source, its dates, each family's used periods - regenerated every run) |
`registry/` ideas, trials (budget), graveyard, decisions | `research/<id>/` | `strategies/<id>/` | `paper/` ledgers |
`notes/<role>.md` (your memory, max ~150 lines) | `reports/` | `outbox/<role>.txt` (what gets posted) |
V3 research code you may import read-only: `C:\Users\user\Documents\Git\StockAnalysis-V3\daytrade\research\`.
