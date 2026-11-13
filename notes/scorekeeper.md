# Scorekeeper notes (memory between runs)

Created 2026-10-27.

## Watch list (as of 2026-11-13)
- V2 rank go/no-go: 88/100 trades (2026-11-13); mean +0.070R after costs (need >= +0.15), week-t 0.27 (need >= 2). NO-GO is the modal outcome. Last 12 trades need +0.737R avg to GO.
- V3 ON1 paper: day 21/40 as of 2026-11-13. CONTINUE (mean +5.1 bps, t 0.18). Day 40 scored ~Thu 2026-12-10. Need +77.7 bps/day avg over next 19 to PASS. Cliff-edge — just above 0 FAIL floor. Last day 11-11: -275 bps.
- V3 ON1 real-price: 7 days (2026-11-02 to 2026-11-11), 514 trades, real_mean -85.4 bps (t -1.60) vs paper +1.5 bps same trades. Half-spread 46.6 bps. COLLECTING (need 15 days, verdict ~2026-11-24). FAIL trajectory — spread eating all paper edge.
- V3 G2 paper: RETIRED 2026-11-08 (FAILED day-20, mean -26.2 bps). No further tracking.
- V4 EPRE paper: 991/1000 closed, mean +23.0 bps hedged. Checkpoint A (~9 trades away) PASS virtually certain (bar: < -20 bps). t 0.37 on 12 exit-days — growing.
- V4 EPRE real-price: 452 trades, 5 exit days, real_mean +91.7 bps (paper +92.3), spread 12.6 bps, t 1.48. Very promising. At checkpoint B real-money condition needs t >= 1 (already 1.48 on 5 days) + mean >= +10 bps (well clear) + accuracy >= 90% (95%).
- Loss cluster 2026-11-11: 3 bearish losses on one day (AVGO, KLAC, ADI; -4.31R) in rank track. Ex-cluster mean +0.180R.
- VCYT: flagged 2026-11-05 as outlier (-5228 bps). integrity_seen.json records it as known.
- g2_paper_task.log stale since 2026-10-09 (known quirk; G2 test retired anyway)

## Standing notes
- Rank verdict: only snapshot.py's numbers are valid; rank_verdict's default CSV paths are relative and read stale copies.
- V2 losses of -1.3..-1.8R are stop gap-throughs, not bugs.
- V3 universe symbols CWEN-A, HLX, LEG return Yahoo 404s (likely delisted) - low impact.
- ON1 data correction (2026-11-09): bad Yahoo opens replaced with settled prices (18 days). Numbers before 11-09 are obsolete. Picks now scored a day later.
- Random control is the baseline for rank (rank beats random by ~+0.30R/trade in current snapshot - context, not a pass).

## Log
2026-10-27: weekly scorecard run (setup test - run 2). Scorecard written to reports/2026-10-27-scorecard.md.
2026-10-30: weekly scorecard. Scorecard written to reports/2026-10-30-scorecard.md.
  G2 heading to FAIL at Nov 5. ON1 softened but still positive. V4 EPRE now active (388 closed).
  Quote Clerk had failed capture — no real-price data yet.
2026-11-05: diagnosis + G2 day-20 checkpoint. Reports/2026-11-05-diagnosis.md.
  G2 FAILED at day 20 (mean -33.5 bps, t -2.05). Director to retire.
  VCYT in EPRE ledger (line 831): ret_bps -5228. integrity_seen.json records it as known.
2026-11-06: weekly scorecard. Reports/2026-11-06-scorecard.md.
  ON1 paper strong (t 3.10, +86.2 bps pre-correction) — now obsolete (data correction 11-09).
  EPRE ~57 trades from checkpoint A. V2 rank mean clears bar but t=0.82 far from 2.
2026-11-10: diagnosis. Reports/2026-11-10-diagnosis.md.
  QuoteClose failed (0x800710E0) — machine asleep 10AM-3:30PM PT. 19 EPRE exit-day trades missed.
2026-11-11: diagnosis + ON1 day-20 checkpoint. Reports/2026-11-11-diagnosis.md.
  SA factor-grades transient outage at premarket. Graceful fallback; no data lost. ON1 day 20: CONTINUE.
2026-11-13: weekly scorecard. Reports/2026-11-13-scorecard.md.
  EPRE checkpoint A imminent (991/1000, +23.0 bps — PASS certain).
  V2 rank heading NO-GO (mean +0.070R, need +0.737R avg on last 12).
  ON1 paper cliff-edge (mean +5.1 bps, t 0.18); real-price FAIL trajectory (-85.4 bps on 7 days).
