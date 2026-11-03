# Director notes

## 2026-10-27 (Tue) — forced run
State at start: pipeline empty, 1 registered idea (insider-officer-buys), 0 team paper tests.

Decision: registered + queued **insider-cluster-buys** (>=2 distinct insiders, open-market, 5d window).
- Why over single-officer: single-officer's 2018-26 holdout is burned at a FAILING t2.3 — re-running as-specified
  = peeking. Cluster is a distinct, better-powered formulation with academic support (Lakonishok-Lee) and its own
  unused holdout. The single-officer near-miss is evidence the family has signal; cluster is the natural next test.
- insider-officer-buys left parked at `idea` (not dropped) — revisit only if cluster fails AND a fresh period exists.
- Researcher MUST design the PLAN on a fresh untouched period (2018-26 insider holdout is gone).

Pipeline limit: 1 queued + 1 parked-at-idea (idea stage doesn't count). OK.

### Live tests (from 2026-10-27 scorecard — do not re-derive numbers, read snapshot.txt)
- V2 rank go/no-go: 59/100 closed, mean R -0.019 (bar +0.15), t -0.20. Likely NO-GO. ~mid-Nov.
- V2 threshold: n=27, +0.113R, informational only (no rule).
- V3 ON1 paper: ON TRACK — only test clearing its bar (mean +81.6bps vs +5, t 2.37). 20-day cp Tue 2026-11-10 morning (see TEAM.md Key dates).
- V3 G2 paper: failing (mean -16bps, t -0.91). 20-day cp Thu 2026-11-05 (see TEAM.md Key dates).
- V3 G2/ON1 forward: too early (t 0.63 / 0.47).
- V4 EPRE: 115 open, 0 closed. Checkpoint A (1000 trades) far out.

### Watch next run
- g2_paper_task.log stale since 2026-10-09 though results update through 10-26 — scorekeeper flagged for ops.
- 2026-11-05 G2 paper cp (failing), 2026-11-10 AM ON1 paper cp, V2 rank go/no-go at 100 trades.
- Saturday = weekly director report due.
- Check insider-cluster-buys progresses to `planned` (Researcher).

## 2026-10-31 (Sat) — weekly review
Pipeline at start: empty of active research (cluster → dead; officer-buys dropped). Ideas parked: turn-of-month,
split-announcement-drift.

Decision: **queued split-announcement-drift**. Best available: real-time 8-K announcement = paper-tradable
(unlike insider family which is verdict-only), clear mechanism, short 3-5d, split family unmined here, data exists
(812 forward-split announcements 2001-26, data_catalog). Left **turn-of-month parked at `idea`** — classic,
heavily-mined calendar effect, keep as backup only if split fails. Pipeline now 1 queued, within limit.

### Auditor 2026-10-29 recommendations — my response
- Rec 1 (Director) drop insider-officer-buys: **ACCEPTED — already done** (shows `dropped`). No untouched insider
  window remains (2006-13, 2014-17, 2018-26 all used); revival condition can't be met.
- Rec 2 (User) insider = research-verdict-only without a near-real-time Form-4 feed/key: **passed to user** in
  this week's outbox + report; their call whether more insider cycles are worth it.
- Rec 3 (Director/Ops) g2_paper_task.log staleness before the ~11-05 cp: **ACCEPTED**. Verified G2 paper results
  ARE current (snapshot last day 2026-10-30), so the writer is live and the cp is readable off a live source; only
  the log file is stale. Left for Scan Operator to confirm the writer; cp can proceed.

### Live tests (from 2026-10-30 scorecard — read snapshot.txt, don't re-derive)
- V2 rank go/no-go: COLLECTING 65/100, mean R -0.006 (bar +0.15), t -0.25. Likely NO-GO. ~Dec.
- V3 G2 paper: 16/20 days, mean -19.6 bps, t -1.36 → heading to FAIL. Cp Thu 2026-11-05.
- V3 ON1 paper: 13/20 days, mean +53.5 bps, t 1.91 — best live test but softening (was t2.37@9d). Cp Mon 11-09
  (scored Tue 11-10 AM). Needs mean>=+5 AND t>=2.
- V3 ON1 real-price: COLLECTING 0 days — **Quote Clerk FAILED its first live capture 10-30**; only test_runs so
  far. Blocks ON1 from ever being real-money-ready even if paper PASSES. Flagged to user.
- V4 EPRE: 388/1000 closed, hedged mean -6.9 bps (above -20 FAIL line), too early.

### Watch next run
- 2026-11-05 G2 paper 20-day cp (likely FAIL → retire via gate if rule says FAIL).
- 2026-11-10 AM ON1 paper 20-day cp (borderline PASS/continue).
- Quote Clerk: is it capturing real quotes yet, or still test_run / failing? Real-price gate depends on it.
- split-announcement-drift → should progress to `planned` (Researcher).

### Corrections from the user's session (2026-11-02)
- Quote Clerk did NOT fail on 10-30: those were test runs. Scheduled captures started 11-02 and work: open
  65/74 (9 not yet quoted at 9:31 ET - expect ~10% most mornings; they fall back to official prices), close
  196/196. First ON1 real-price day scores with the 11-03 dispatch.
- A near-real-time Form 4 feed is NOT a paid service: SEC EDGAR is free (V2 already uses it; tools/edgar.py reads
  the daily index). Insider is closed anyway (all holdouts used), so no action - just don't repeat the premise.
- V4 EPRE: Yahoo's placeholder time moved 15:00 -> 16:00 ET when DST ended; fixed in V4 the same night (16:00/01:00
  now also count as placeholders for upcoming reports; no second trade on a report already held). V4's rules
  are unchanged - this restores how it ran Oct 26-30.
