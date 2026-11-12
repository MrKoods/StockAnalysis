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

## 2026-11-03 (Tue) — weekday queue run
Pipeline was 0/2 in research, 5 ideas waiting (all Scout-added 11-03 + older calendar). Filled both slots:
- **queued reg-fd-small-cap-disclosure** (8k_7_01, 1d): strongest — builds on in-house 8-K screen (7.01 best
  type, t2.31 full-sample), real-time 8-K paper-tradable, data in hand, 8k_7_01 holdout untouched. Risk flagged
  to Researcher: 25bps spread on small/mid caps at 1d is the kill test.
- **queued analyst-initiation-buy** (analyst_ratings, 3d): distinct from dead generic-ratings (first-ever
  initiation+Buy only), Womack mechanism, 15bps. Caveat to Researcher: VERIFY ratings() loader has an "Initiated"
  action type first + check initiation count powers a holdout (2012-26 only); bounce to dead if not.
- **dropped january-small-cap-reversal** (once/yr ~25 clusters, most-mined anomaly, decayed, 25bps) and
  **pre-holiday-drift** (few holidays/yr = low event count, mined/decayed since 1988). Left **turn-of-month**
  parked at idea as the single calendar backup.
Ops: context flags 1 V4 trade past exit day still unscored (already posted to #agent-ops — evaluate task may be
failing; watch next run). Yahoo news-fetch errors in paper_runner logs are confirmation-only, non-blocking.
Watch next run: 2026-11-05 G2 paper 20-day cp (likely FAIL→retire via gate); both queued ideas should move to
`planned` (Researcher); the unscored-V4 evaluate task.

## 2026-11-05 (Thu) — weekday queue run
Pipeline 0/2 at start; 7 ideas parked (all live=yes in data_catalog — none verdict-only). Filled both slots:
- **queued early-10q-drift** (10q_timing, 3d): best — family wholly unmined, 10-Q quarterly freq = ~4x the 10-K
  analog's events (holdout power), clean timeliness mechanism, S&P 1500 (not small-cap-only), 18bps, paper-tradable
  off the live SEC index. Preferred over early-10k-drift (same mechanism, 1/4 the events) — left 10k parked.
- **queued restructuring-bounce** (8k_2_05, 3d): in-house screen t=1.79@3d, 2,097 item-2.05 filings, untouched
  8k_2_05 holdout, kitchen-sink mechanism, real-time 8-K. CAUTION to Researcher: reg-fd(7.01) + analyst-initiation
  both just died on TRAIN with NEGATIVE t because the small-cap LONG ran opposite — don't force an S&P400+600-only
  long; test full S&P 1500 too. 30bps@3d is the kill risk.
- **dropped quarter-end-window-dressing**: ~4 correlated clusters/yr = thin holdout power + heavily-mined calendar
  (same reasoning as pre-holiday/january drops). turn-of-month kept as single calendar backup.
- Left parked: turn-of-month (calendar backup), early-10k-drift (timeliness backup), debt-acceleration-bounce
  (kitchen-sink twin of 2.05, only 410 events — redundant/underpowered vs restructuring), nt-filing-short
  (blocker: verify paper_runner supports direction=short AND that NT 10-K/NT 10-Q forms exist in filings()).

### Live tests (from 2026-11-05 snapshot — do not re-derive)
- **V3 G2 paper: 20-day checkpoint = FAIL** (mean -33.5 bps, day-t -2.05; rule FAILs if mean<0). V3 folder =
  read-only for team, no team gate entry, so the team can't retire it — user's V3 session / Scorekeeper to act.
  Reported in outbox.
- V3 ON1 paper: 17/20 days, +70.3 bps, t 2.90 — still clearing its bar; 20-day cp Mon 11-09 (scored Tue 11-10 AM).
- V2 rank go/no-go: 72/100, +0.024R after costs (bar +0.15), week-t -0.26 — needs +0.474R over last 28 to GO; drifting NO-GO.
- V4 EPRE: 836 closed, hedged +28.7 bps, exit-day t 0.11 (7d) — too early, cp A at 1k. Integrity alerts (|ret/net_bps|>5000)
  already posted → Scorekeeper to diagnose.

### Watch next run
- Both queued ideas should move to `planned` (Researcher). Confirm.
- Mon 11-09 ON1 paper 20-day cp (borderline PASS — needs mean>=+5 AND t>=2 at day 20).
- V2 rank go/no-go approaching 100 trades.
- Did the user's V3 session stop/park G2 after its 20-day FAIL?
- Saturday = weekly director report + Auditor.

## 2026-11-05 (Thu) — 2nd run, refill
early-10q-drift + restructuring-bounce both ran train + Skeptic FAIL today (now `dead`) → pipeline back to 0/2.
Refilled both slots from the 4 remaining parked ideas:
- **queued turn-of-month** (calendar_effects, 4d): distinct calendar mechanism untouched by today's failures;
  data in hand, paper-tradable. Caveat to Researcher: mined family + few TOM clusters/yr → must power a clean
  untouched holdout and prove it survives costs.
- **queued nt-filing-short** (nt_filing, 3d short): distinct late-filing short signal. Confirmed paper_runner
  supports side=short (paper_runner.py:235). Caveat: Researcher MUST verify filings() actually returns NT 10-K/
  NT 10-Q forms first; bounce to dead if not. 30bps short-side cost = kill test.
- **dropped early-10k-drift**: twin mechanism of the just-failed 10q-drift, with ~1/4 the events.
- **dropped debt-acceleration-bounce**: kitchen-sink twin of the just-failed 2.05 restructuring; only 410 events.
Only turn-of-month remains as a backup if these die — Scout should refill the parked pool next weekday.

### Corrections from the user's session (2026-11-02)
- Quote Clerk did NOT fail on 10-30: those were test runs. Scheduled captures started 11-02 and work: open
  65/74 (9 not yet quoted at 9:31 ET - expect ~10% most mornings; they fall back to official prices), close
  196/196. First ON1 real-price day scores with the 11-03 dispatch.
- A near-real-time Form 4 feed is NOT a paid service: SEC EDGAR is free (V2 already uses it; tools/edgar.py reads
  the daily index). Insider is closed anyway (all holdouts used), so no action - just don't repeat the premise.
- V4 EPRE: Yahoo's placeholder time moved 15:00 -> 16:00 ET when DST ended; fixed in V4 the same night (16:00/01:00
  now also count as placeholders for upcoming reports; no second trade on a report already held). V4's rules
  are unchanged - this restores how it ran Oct 26-30.

## 2026-11-06 (Fri) — refill run
turn-of-month + nt-filing-short both ran train + went dead today → pipeline 0/2. 4 ideas parked. Filled both slots:
- **queued pipe-short** (8k_3_02, 3d short): strongest. PIPE/unregistered-equity dilution = documented issuer
  underperformance; 3,635 filings, 8k_3_02 holdout untouched, real-time 8-K paper-tradable, side=short supported.
  Caveat: ~30bps short-side cost at 3d is the kill test; test full S&P 1500 (small-cap-only longs killed reg-fd +
  analyst-initiation).
- **queued activist-13d-long** (activist_13d, 3d long): SC 13D activist stake, documented positive abnormal
  return, long/easy-to-paper. CAVEAT to Researcher: VERIFY filings() actually returns SC 13D forms first — 13D is
  absent from data_catalog's top-12 (only SC 13G/13G-A show; 13G = passive cousin, not the signal). Bounce to dead
  if 13D not present OR event count can't power a clean holdout. (Couldn't self-verify: research_data.py Bash
  denied, filings.parquet not greppable — left as Researcher's cheap first step, same pattern as nt-filing-short.)
- **dropped year-end-loser-reversal**: = already-dropped january-small-cap-reversal (tax-loss reversal), mined/
  decayed, once-a-year so can never build a 20-40-day paper test; turn-of-month (last calendar) died today too.
- Left parked: **late-10k-short** (10k_timing) as the single backup — weaker now, both early-10q-drift AND
  nt-filing-short (related "late/early filing" theses) died today. Scout should refill the pool next weekday.

### Watch next run
- Both queued ideas → should move to `planned` (Researcher). Confirm activist didn't bounce to dead on the SC 13D check.
- Mon 11-09 ON1 paper 20-day cp (borderline PASS — needs mean>=+5 AND t>=2 at day 20; scored Tue 11-10 AM).
- V2 rank go/no-go approaching 100 trades (72/100 as of 11-05, drifting NO-GO).
- Did the user's V3 session stop/park G2 after its 20-day FAIL (11-05)?
- Saturday = weekly director report + Auditor report to read.

## 2026-11-07 (Sat) — weekly review
Pipeline full 2/2 (activist-13d-long, pipe-short both queued 11-06, in research); late-10k-short parked. Nothing
to queue. Wrote reports/2026-11-07-director.md.

G2 FAIL confirmed as NOT the team's to retire: ran `python tools/gate.py retire g2` → refused "g2 is not an
active paper test" (no team gate entry; V3 folder read-only). Reported to user as their V3 session's job. G2 is
still running (day 21/40, mean -26.2) as of 11-06 snapshot — user hasn't parked it yet.

### Live tests (from 2026-11-07 snapshot / 11-06 scorecard — do not re-derive)
- V2 rank: 79/100, +0.129R after costs (bar +0.15), week-t 0.51–0.82 (bar 2). Drifting NO-GO; t is the wall.
- V3 ON1 paper: day 18/20, +86.2 bps, day-t 3.10 → very likely PASS at day 20 (Mon 11-09, scored Tue 11-10 AM).
  BUT ON1 real-price -35.5 bps/4 days vs paper +188 (~223 bps gap) → paper PASS ≠ tradeable; real-price 15-day
  check ~11-24 is the live gate. Tell user "not yet" even on a paper PASS.
- V4 EPRE: 943/1000 to cp A (~3 sessions). hedged +20.1 bps (FAIL<-20), t -0.06 — well above FAIL, too early.
  Real-price spread negligible (11 bps). cp A is FAIL-only; real-money conditions at cp B (3000).

### Auditor 2026-10-31 recs — my response (recorded late; prior notes missed these)
- Rec 1 (Director) replenish queue w/ real mechanisms, don't default to turn-of-month: **ACCEPTED — done**.
  Scout ran daily 11-03→11-06; 6 distinct mechanisms queued+tested, no lazy fallback; turn-of-month queued as a
  distinct test not a default. Queue supply held all week.
- Rec 2/3 (User): Quote Clerk firing (resolved by 11-02 correction — captures work) + insider line closed unless
  user builds Form-4 feed (user's call). Both passed to user.

### Watch next run
- activist-13d-long + pipe-short → should be `planned`/`awaiting_review`; confirm 13D check didn't kill activist.
- Mon 11-09 ON1 paper 20-day cp (likely PASS). Tue 11-10 AM scored.
- Did user's V3 session stop/park G2 yet?
- V2 rank nearing 100 trades (drifting NO-GO).
- 2026-11-07 Auditor report (runs after me today) — read + respond next run.

## 2026-11-09 (Mon) — weekday queue run
Pipeline 0/2 at start (pipe-short + activist-13d-long both died on TRAIN over weekend). 3 ideas parked. Was
strict — queued the one real idea, dropped the two weak:
- **queued seo-short** (seo_offering, 3d short): new unmined family, SEO dilution is one of the best-documented
  anomalies (Myers-Majluf, Loughran-Ritter), 424B = real-time EDGAR paper-tradable, full S&P1500. Researcher FIRST:
  verify filings() returns 424B4/424B5 (only 424B2/B3 in catalog top-12 — unconfirmed, bounce to dead if not).
  CAUTION: pipe-short (3.02 PIPE, same dilution-short thesis @3d) died on TRAIN t -1.57 last week — but SEO is a
  distinct instrument (registered follow-ons, larger names). ~30bps short cost @3d = kill test.
- **dropped late-10k-short**: softer twin of dead nt-filing-short (same late-filing short, card admits it's softer);
  10k_timing family exhausted. **dropped quarter-end-winner-short**: short inverse of already-dropped
  quarter-end-window-dressing — mined calendar, ~4 corr events/yr can't power a holdout or a 20-40d paper test.
- Left pipeline at 1/2 on purpose (no padding); Scout refills parked pool next weekday.

### Watch next run
- Did seo-short move to `planned`? Confirm 424B4/B5 verify didn't bounce it to dead.
- ON1 paper 20-day cp was today (Mon 11-09) — scored Tue 11-10 AM (picks now scored a day later, post-settlement).
  Likely PASS on paper BUT ON1 real-price was deeply negative (−35 bps/4d vs +188 paper) → tell user "not yet";
  real-price 15-day check ~11-24 is the live gate. Retire ON1 is NOT the team's (V3 read-only) — user's session.
- V2 rank nearing 100 trades (79/100 @11-05, drifting NO-GO).
- Did user's V3 session stop/park G2 after its 20-day FAIL (11-05)?

## 2026-11-11 (Wed) — weekday queue run
Pipeline 0/2 at start (seo-short died on TRAIN, t -5.92; no other research live). 5 fresh ideas parked (Scout
added pre-earnings-premium, pre-earnings-beat-streak, proxy-contest-long, earnings-announcement-risk-premium 11-10/11;
issuer-self-tender-long 11-10). Filled both slots + dropped one duplicate:
- **queued issuer-self-tender-long** (self_tender, 3d long): strongest by edge size — self-tender at a premium =
  hard price floor + undervaluation (Peyer-Vermaelen ~8%), clearly clears the 50-bps edge bar vs 15bps cost;
  unmined family; full S&P1500 LONG (avoids the small-cap-only-long trap that killed reg-fd/analyst-init/restructuring);
  real-time SC TO-I = paper-tradable. Researcher FIRST: verify filings() returns SC TO-I (not in catalog top-12) +
  that rare self-tender events still power a clean holdout; bounce to dead if not.
- **queued pre-earnings-premium** (pre_earnings, 1d): our one proven vein (earnings), DISTINCT from live V4 EPRE —
  holds BEFORE announcement (close-2→close-1) vs EPRE through it. Fresh pre_earnings family, full S&P1500, huge event
  count = best holdout power here. KILL RISK = edge SIZE (1-day slice of a multi-day premium, Laarits 2020): told
  Researcher to size gross edge on TRAIN first, must clear ~50 bps vs 15-25bps cost or bounce to dead.
- **dropped earnings-announcement-risk-premium**: it IS the Savor-Wilson announcement premium = already passed
  holdout (Round 7, t4.0) and running live as V4 EPRE. Re-testing a live edge can't produce a new result.
- Left parked at `idea`: **pre-earnings-beat-streak** (conditional twin of pre-earnings-premium, same pre_earnings
  family/holdout — redundant unless #1 dies; backup) and **proxy-contest-long** (6.5% edge BUT small/mid-cap-only
  LONG = the exact pattern that inverted-and-killed reg-fd/analyst-init/restructuring, and activist-13d just died
  11-07; backup only). Scout refills next weekday.

### Live tests (from scripts this run — do not re-derive)
- V3 ON1 paper hit its 20-day checkpoint today. Even a paper PASS ≠ tradeable: ON1 real-price COLLECTING 6 days,
  mean **-45.5 bps**, t -1.08, half-spread 48 bps vs paper +47.2 on the same trades — the spread eats the whole
  edge. Real-price 15-day gate ~11-24 is the live decision. Retiring ON1 is the user's V3 session (team read-only).

## 2026-11-11 (Wed) — 2nd run, refill
Both morning-queued ideas (issuer-self-tender-long, pre-earnings-premium) died on TRAIN same day → pipeline 0/2.
Only 2 ideas parked. Was strict — queued 1, dropped 1 (left pipeline 1/2, no padding):
- **queued proxy-contest-long** (proxy_contest, 3d long): big edge (Fos 2017 ~6.5% event-window premium) clears the
  50-bps cost bar easily; new unmined family, holdout untouched; DFAN14A = real-time EDGAR paper-tradable.
  Researcher FIRST: verify filings() returns DFAN14A (not in catalog top-12); bounce to dead if absent / can't
  power a clean holdout. CAUTION: small/mid-cap-only LONG = exact inversion that killed reg-fd/analyst-init/
  restructuring, and activist-13d-long died 11-07 → test full S&P1500 too, not only 400+600.
- **dropped pre-earnings-beat-streak**: base twin pre-earnings-premium (same pre_earnings family + same 1-day
  close-2→close-1 slice) died on train TODAY — the 1-day pre-earnings slice has no edge; a 4-beat-streak filter
  cuts events further (less holdout power) without evidence the base edge exists. pre_earnings vein looks exhausted.
- Parked pool now empty → Scout must refill next weekday.

### Watch next run
- proxy-contest-long → should move to `planned`; confirm DFAN14A verify didn't bounce it to dead.
- V2 rank nearing 100 trades (drifting NO-GO).
- ON1 real-price 15-day check ~11-24 (spread -45 bps eats the edge); did user's V3 session park G2 / ON1?
- Saturday = weekly director report + Auditor to read.

## 2026-11-12 (Thu) — refill run
proxy-contest-long died on TRAIN today → pipeline 0/2. Only 1 idea parked (pre-holiday-small-cap-long). Was
strict — dropped it, left pipeline 0/2 (no padding):
- **dropped pre-holiday-small-cap-long** (pre_holiday, 1d S&P600 long): 3 independent kills. (1) Un-paper-tradable
  cadence — fires ~10 days/yr, so a 20-40 day paper test (days-with-scored-trades) = ~2-4 yrs; same fatal flaw
  that killed turn-of-month/january/quarter-end/pre-holiday-drift. No path to real money through the gate on any
  useful horizon. (2) Most-mined calendar anomaly (known since 1988); card itself predicts decay below 50bps
  post-2000. (3) Small-cap-ONLY LONG = the exact inversion that killed reg-fd/analyst-init/restructuring/
  activist-13d/proxy-contest (5 straight). Distinct-family/82bps-gross only beats the edge-size filter.
- Parked pool now empty → Scout must refill next weekday. Calendar vein is now effectively closed here (every
  calendar card dropped on the same cadence/mining logic).

### Watch next run
- Scout should refill parked pool (was empty after this run).
- V2 rank nearing 100 trades (drifting NO-GO).
- ON1 real-price 15-day check ~11-24 (spread -45 bps eats the edge); did user's V3 session park G2 / ON1?
- Saturday = weekly director report + Auditor to read.
