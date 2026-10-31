# Auditor notes

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
