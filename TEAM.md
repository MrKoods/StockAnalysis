# The team charter (every role reads this first)

## Goal (the user's words, 2026-11-14: make money trading - and get there through this team, running and improving itself)
Two halves, equally binding:
1. **The edge** - below.
2. **The team gets there on its own.** It runs every day without the user, catches and fixes its own failures,
   and gets better over time: it notices what wastes money or holdouts, changes its own process (prompts, notes,
   harness requests via the Engineer/Director), and checks the change worked. Every time the user has to step in
   is a defect to remove, not a normal step - except the user-only decisions in "Hard limits" (real money, task
   schedules, paid data, logging Claude in). When you ask the user for something, also say what would let the team
   handle it next time.

Find a stock-trading edge that is **real** (survives costs and an untouched holdout) and **tradeable at the user's
broker**. Holding period: anything from 1 day to ~60 trading days. Shorter is only a tie-breaker between edges of
the same quality - it is NOT a reason to prefer a 3-day hold whose edge equals its cost over a 20-day hold whose
cost is a rounding error. Day-trading on price/volume patterns failed at scale here (~375k variants); the one
holdout pass (EPRE, V4) holds ~1-2 days. The user's aim is money; no real money moves until a pre-registered test
passes. A clear "this failed" is a good result.

## Where the search goes (user's decision 2026-11-23, from the deep strategy review - read first)
~400,000 variants across V2/V3/V4/team found ONE survivor (EPRE, a risk premium). Cost is the binding limit, not
ideas. So:
- **Cost hurdle**: an idea's gross edge per trade must be >= 3x its real round-trip cost (tools/ideas.py refuses
  it otherwise). Research cadence halved: Scout Mondays to 5 waiting ideas, 1 idea in research at a time.
- **Look at risk premia and forced flows in index ETFs** (overnight vs intraday, rebalance / month-end flows,
  volatility-premium timing, macro-announcement premia), and longer holds at the close. Single 8-K events and
  single-stock short holds are deprioritized (19 ideas, mean t -0.2).
- **The user's account is $20k** (under the $25k pattern-day-trader line): real money can only use rules that
  hold overnight or longer. Options (defined-risk spreads) are allowed; there is no free option HISTORY, so the
  team records its own: tools/option_chains.py saves SPY/QQQ/IWM/SPX chains with bid/ask daily (paper/options,
  from 2026-11-23). Pre-cost, 2007-2017: put-writing ~= SPY's Sharpe, condors/butterflies ~0 - selling options
  is not an edge by itself; only a timed/selective rule that clears the cost hurdle at the recorded spreads is.
- **ETF fills**: the Quote Clerk quotes SPY/QQQ/IWM/IJR/MDY/DIA at every capture plus a ~9:45 ET capture (`open2`,
  run by the Scan Operator) - `python tools/quotes.py etf`. The ETF overnight premium needs <= ~1 bp a side.
- **EPRE-ML** (S&P 500+400 only, entries from 2026-11-24) is judged beside EPRE under its own pre-registered rule
  (StockAnalysis-V4/RULES.md amendment 2026-11-23). No further EPRE variants from live results.
- Free data inventory and what's NOT free (delisted prices, option history, Webull option/futures quotes):
  memory/notes of 2026-11-22; ask the user before paying for any data.

## Where the search went before (user's decision 2026-11-13, from the full audit)
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
Survivorship: S&P 500-only studies use real point-in-time membership (`rd.pit_filter`, team/ref/sp500_membership.csv,
added 2026-11-13 - 280 of today's 503 members had been in the tests for years before they joined). Still open for
sp400/sp600/'all' (no free membership history; stocks that fell out have no prices) - prefer recent train windows
and say in PLAN.md how much it could inflate a long result. Paid fix (CRSP/Norgate) only once something is close.

## Roles
| Role | Kind | Job |
|---|---|---|
| Scan Operator | script | Owns every scan's running (team/schedule.json = the master schedule). Every 10 min: verifies each job really worked, re-runs it while a re-run is still valid, alerts #agent-ops when it can't, flags schedule drift |
| Ops Monitor | script | Every dispatch: every scheduled task ran, ACTION NEEDED alerts, ledger integrity (tools/integrity.py: duplicates, impossible values, stale ledgers). A problem goes to #agent-ops at once |
| Daily Report | script | **The user's end-of-day report** in #agent-ops (Mon-Fri, end of the dispatch, ~2:51 PM PT on a quiet day): jobs OK?, needs you, live tests + what each next decision needs, real Webull prices, V2 trades, what the team did. tools/daily_report.py. Replaced the old review agent (retired 2026-11-01) |
| Evening Check | script | First Scan Operator tick at/after 6 PM PT, Mon-Fri: jobs since the report ran, and the V4 EPRE calendar is fresh and didn't shift abnormally (tools/evening_check.py). 🌙 all OK or 🛑 |
| Quote Clerk | Claude (Haiku) | 9:31 AM / ~9:45 AM / 3:56 PM ET captures live Webull bid/ask for every paper trade that fills then, plus 6 index ETFs. One read-only tool; numbers parsed by script |
| Paper Runner | script | Trades every active team strategy on paper; scores it against its frozen rule |
| Scorekeeper | retired 2026-11-13 | Its jobs moved: failures -> Engineer, checkpoints -> Director, Friday scorecard -> a script (`reports/<Fri>-scorecard.md`, tools/dispatch.py) |
| Scout | Claude (Sonnet) | Mondays until 5 ideas wait (halved 2026-11-23): finds ideas (papers, practitioner work, the free 8-K event screen in state/screen.md, Webull market data) -> idea cards that name their data. Reads `state/dropped_ideas.md` (why the Director dropped ideas) |
| Researcher | Claude (Opus) | Writes a pre-registered PLAN + test script for a queued idea; scripts run it on TRAIN data |
| Skeptic | Claude (Opus) | Tries to kill every result (look-ahead, costs, luck vs variants tried, survivorship) |
| Director | Claude (Opus) | Runs the pipeline: queues ideas, starts/stops paper tests via the gate, tells the user what matters |
| Holdout Keeper | script | Runs a strategy on the locked holdout period exactly once |
| Engineer | Claude (Opus) + script guard | Last in a dispatch, when something failed, when the Director files a build request, and every Saturday: the ONLY role that diagnoses failures; finds the cause, fixes the team's own machinery, proves it with tests. **Builds research tools** the Director asks for (`tools/lab/`, pure tested functions, frozen once a locked test uses them - user 2026-11-14), so the team grows its own capabilities instead of asking the user. tools/engineer.py keeps the edit only if it is on the editable list, passes static checks and passes every test; otherwise it rolls the run back. Log: registry/engineer_log.csv |
| Strategist | Claude (Opus) | Monthly (first Saturday 4+ weeks after its last review, before the Auditor): reads every result so far (`state/review_pack.md`, tools/playbook.py) and revises **`playbook/PLAYBOOK.md`** - search priorities, stop list, research methods - which the Scout, Director and Researcher follow. The self-improving part of the loop (user 2026-11-24). Its fixed section (the user's decisions) is restored by script after every run; it never touches rules, tests or results |
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
- **V2 retires itself on rank NO-GO** (user 2026-11-21): the dispatcher disables all 5 V2 tasks once
  (tools/dispatch.retire_v2_rank, state/v2_rank_retired.json). Don't ask the user to.
- **2026-11-13..20: the claude.ai Webull CONNECTOR was signed out** (not Claude) - 6 days of 0/N quotes, lost for
  good. quotes.py now names it (`webull_auth`); only the user can reconnect it (claude.ai -> Settings ->
  Connectors). Don't diagnose it again.
- **Patch mode** (user 2026-11-21): fixes to files the Engineer may not edit (V4 epre/, V3 daytrade/, team scoring
  code like quotes.py) go in state/patches/<id>.json; tools/patches.py proves them on a scratch copy, posts them,
  and the user applies with one command. Hard-limit files are never patchable. **Since 2026-11-24 a patch that
  touches only machinery** (patches.AUTO_FILES: data collection, reports, scan operations) **applies itself 24 h
  after it is ready** unless the user rejects it; scoring code, V3/V4, the runner and new network/process reach
  still wait for the user.
- **Quote backup** (2026-11-24): every capture also saves Yahoo bid/ask to paper/quotes_backup.csv, so a signed-out
  Webull no longer loses the record. Never used for a test's score; `python tools/quotes.py backup` measures how
  close it is to Webull. A Quote Clerk give-up on a signed-out day counts as "needed your sign-in", not a team
  failure (tools/autonomy.py). Goal shown daily: 30 days in a row without the user.
- **EPRE's t counts exit days, not trades**: 1,037 trades = 17 exit days (2026-11-20). The daily report also shows
  hedged mean by index - live sp600 was -42 bps while the backtest had the edge in smaller names. Informational;
  RULES.md checkpoints are unchanged.
- **Paper vs real gap > ~2x the measured spread = suspect the PAPER prices, not costs** (ON1 2026-11-06..08: three
  roles called a 223 bps gap "spread"; it was bad Yahoo opens).
- **EPRE's 1:45 PM PT scoring closes are final enough** - checked 2026-11-13 by re-downloading all 991 scored
  trades: 986 identical, 5 moved > 25 bps (dividends credited later), mean +23.0 -> +23.1 bps. No re-scoring;
  RULES.md stays as frozen.
- **The team branch is pushed to GitHub at the end of every dispatch** (tools/publish.py), only after a secret scan
  of the outgoing commits; a blocked or failed push is posted to #agent-ops. Never put a key or webhook in a file.
- **Day-0 paper trading is built** (2026-11-14): the Scan Operator tick at ~12:40 PT captures today's SEC filings
  (tools/edgar_live.py) and runs paper_runner.run_day0 for `"entry_at": "same_close"` strategies before the 12:56
  Quote Clerk. No user step is needed for a day-0 idea any more.
- **8-K text is held** (2026-11-14): data/edgar/text, ~250k filings of items 8.01/5.02/1.01/... (`rd.filing_text`),
  topped up every dispatch. Ideas that need WHAT a filing says are build requests for the Engineer, not data
  requests for the user. FOMC dates: `rd.fomc()`.
- **SEC renamed SC 13D/13G to SCHEDULE 13D/13G in late 2024**: `rd.filings(forms=['SC 13D'])` matches both since
  2026-11-14. Older code filtering the raw form missed every 13D after 2024 (e.g. strategies/activist-13d-long).

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
`playbook/PLAYBOOK.md` (search priorities, stop list, research methods - the Strategist's, revised monthly) |
V3 research code you may import read-only: `C:\Users\user\Documents\Git\StockAnalysis-V3\daytrade\research\`.
