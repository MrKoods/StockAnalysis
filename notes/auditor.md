# Auditor notes

## 2026-11-07 — 3rd audit (regular Saturday slot)
No red flags. Honest week: 8 ideas died (reg-fd, analyst-init, early-10q, restructuring, turn-of-month,
nt-filing, activist-13d, pipe-short) — all clean nulls. Spot-checked pipe-short + activist train_result.json
= exact match to graveyard (t −1.57/−31.89; t 0.17/+2.37); auto-fail below luck bar, no holdout spent — good
discipline. restructuring skeptic.json substantive (cites test.py:43-82). Commit order plan-before-results holds.
New auto-fail path (00a948c) working, preserves holdouts. gate.py list EMPTY — zero team paper tests ever
promoted (all paper = V2/V3/V4). scan_ops issues empty all week. Prior C4 + C5 both RESOLVED.

### Open findings (check next audit)
- **C6 OPEN (Scorekeeper)**: 11-06 scorecard V2-rank row used gross +0.185R vs the after-cost bar +0.15 and
  said "Mean just clears bar" — wrong; after-cost mean is +0.129 < bar. Conclusion still honest (NO-GO),
  Director used the right number. CHECK: does the next scorecard pair after-cost mean with after-cost bar?
- **C7 OPEN (Director/direction)**: single-8-K-item vein near-exhausted + cost-blocked. Edges of 15-30 bps
  keep dying against a 21.8-25 bps floor; events too sparse to power 2018-26 holdout. 0 promotions to paper
  in ~3 weeks. Not circling (distinct families), but a dead-end. Recommended biasing queue to EPRE-style
  edges that clear the cost floor with margin. CHECK: did Director narrow the 8-K family churn or keep mining it?

### Pattern to watch (direction) — ESCALATED from 10-31
The 10-31 "idea supply + event count is the binding constraint" has sharpened into a cost-floor problem:
small-cap event longs/shorts at 1-5d simply can't beat ~25 bps round-trip. EPRE (holdout pass) works because
earnings reactions dwarf costs. Steer toward large-reaction mechanisms, not thin-margin event drift.

### Watch calendar
- Mon 11-09 ON1 paper 20-day cp (likely PASS, scored Tue 11-10 AM) — but ON1 real-price −35.5 bps/4d vs paper
  +188 = ~223 bps gap; paper PASS ≠ tradeable. Real gate = 15-day real-price check ~11-24.
- Did user's V3 session stop/park G2 (FAILED 11-05, still running day 21)?
- V2 rank ~100-trade go/no-go (79/100, drifting NO-GO, t wall).
- V4 EPRE cp A at 1k (~943, ~3 sessions) — FAIL-only bar, won't fail.
- VCYT in EPRE ledger (−5228 bps) = genuine 52% earnings crash, not a data error (diagnosis 11-05); user to
  confirm $24.0 close vs Webull if not done.
- Next audit: regular Saturday slot after the Director.

## 2026-10-31 — 2nd audit (regular Saturday slot)
Project sound. One honest negative this week: split-announcement-drift → dead. Clean cycle:
plan-before-results (commit order 76d94a1→dbc2f6f→913f880→d1b22e7), pre-registered h4_r2 honored over
train-best h2_r2, Skeptic substantive (flagged survivorship = prescient), holdout ran once (t0.99<3.0),
graveyard+budget+ideas all consistent. No red flags. Director acted on all 3 of my 10-29 recs.

### Prior findings — resolution
- **C1 CLOSED**: insider-officer-buys dropped (shows `dropped`). Director accepted; no untouched insider
  window remains. Done.
- **C2 → now moot/closed**: insider = verdict-only without a live Form-4 feed. Director passed to user.
  Insider family now fully exhausted (all 3 holdouts burned). Nothing left to run unless user builds a free
  EDGAR Form-4 feed. Reframed as 10-31 Rec 3; treat as closed unless user revives.
- **C3**: was my error (g2 log staleness = known quirk). Stays closed. Don't re-flag.

### Open findings (check next audit)
- **C4 OPEN (Director)**: idea queue near-empty after split died — only turn-of-month parked (weak,
  heavily-mined). Scout last ran 10-29. CHECK: did Scout replenish with real mechanisms before the next
  research slot, or did the Director default to queuing turn-of-month?
- **C5 OPEN (User)**: real-price Quote Clerk = 0 data (only test_runs 10-30; both paper/*_real_price_status.json
  trades:0). Sole gate on ON1 real-money readiness. 10-31 Sat = nothing due. CHECK: did scheduled capture fire
  Mon 11-03+ and start producing real-price days before ON1's ~11-10 cp? Scorekeeper/Director "FAILED"
  wording is slightly loose (they were test_runs that DID return quotes) but the conclusion is honest.

### Pattern to watch (direction)
Two families in a row (insider, corporate_events/split) died UNDERPOWERED on the modern 2018-26 holdout
(split holdout mean +78bps > train, but n=99 → t0.99). Discipline is correct. But the binding constraint is
now idea *supply + event count*, not method honesty. Push toward event families with enough annual events to
power a modern holdout.

### Watch calendar
- 2026-11-03 first real trading-day test of Quote Clerk real-price capture.
- 2026-11-05 V3 G2 paper 20-day cp (likely FAIL → gate retire). 2026-11-09/10 ON1 paper 20-day cp (borderline).
- ~Dec: V2 rank 100-trade go/no-go (likely NO-GO, 65/100); V3 40-day cps; V4 EPRE 1k-trade cp A.
- Next audit: regular Saturday slot after the Director.
