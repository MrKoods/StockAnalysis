# Scorekeeper notes (memory between runs)

Created 2026-10-27.

## Watch list (as of 2026-11-06)
- V2 rank go/no-go: 79/100 trades; mean +0.185R (clears +0.15 bar), week-t 0.82 (need 2) — looking weak, t very unlikely to reach 2 in remaining 21 trades; likely NO-GO
- V3 ON1 paper: day 18/20, mean +86.2 bps, t 3.10 — PASS very likely at day 20 (Mon Nov 9, scored Tue AM)
- V3 ON1 real-price: 4 days, mean -35.5 bps vs paper +188.0 same trades (gap 223.5 bps, half-spread 50 bps). Too early but gap is large. Paper PASS ≠ tradeable. Rule: 15-day decision point ~2026-11-24.
- V3 G2 paper: FAILED day 20 (2026-11-05). Director must retire via gate.py. Still running on day 21.
- V4 EPRE: 943/1000 to checkpoint A (fail if hedged mean < -20 bps). Currently +20.1 bps. Exit-t -0.06 (8 days) too early. ~57 trades to checkpoint A (~3 trading days at current pace).
- V4 EPRE real-price: 429 trades, 3 exit days; real hedged +72.5 bps vs paper +71.7 (spread 11.3 bps). Negligible spread; too few exit days for t.
- VCYT: flagged 2026-11-05 as outlier (-5228 bps). integrity_seen.json records it as known. User may still need to verify $24.0 close vs Webull.
- g2_paper_task.log stale since 2026-10-09 (known quirk; G2 ledger is valid source)

## Inherited from the old review agent (retired 2026-11-01; its notes: StockAnalysis-agent/agent/NOTES.md)
- Its ON1 day-20 outlook ("needs only +7.2 bps/day, PASS is modal") was too optimistic: with the observed
  day-to-day sd (~101 bps), day-t >= 2 at day 20 needs the next 7 days to average ~+30 bps (Outlook section of
  state/snapshot.txt, 2026-11-01). Quote the Outlook, not old estimates.
- V2 rank: the near-zero mean is entirely the 15-day time stop (time-stop exits +0.82R avg, losses -1.1R; formal
  3R target hit ~2x). No signal feature separates time-stops from losses (6 tested, nothing survives). GO at
  n=100 is arithmetically out of reach; the rule still decides at 100.
- Random control is the baseline for rank (rank beats random by ~+0.35R/trade - context, not a pass).
- Loss clusters (3+ same-direction losses, same exit day) are one correlated move: mention once, give the mean
  excluding that day, change nothing. Known: random track exit 2026-10-23 (6 bullish losses).
- V3 universe symbols CWEN-A, HLX, LEG return Yahoo 404s (likely delisted) - low impact, maintenance item.
- Rank verdict: only snapshot.py's numbers are valid; rank_verdict's default CSV paths are relative and read a
  stale copy from any other folder.

## Log
2026-10-27: weekly scorecard run (setup test - run 2). Scorecard written to reports/2026-10-27-scorecard.md.
2026-10-30: weekly scorecard. Scorecard written to reports/2026-10-30-scorecard.md.
  G2 heading to FAIL at Nov 5. ON1 softened but still positive. V4 EPRE now active (388 closed).
  Quote Clerk had failed capture — no real-price data yet.
2026-11-05: diagnosis + G2 day-20 checkpoint. Reports/2026-11-05-diagnosis.md.
  G2 FAILED at day 20 (mean -33.5 bps, t -2.05). Director to retire.
  VCYT in EPRE ledger (line 831): ret_bps -5228 / net_bps -5244, flagged by integrity. Likely real
  post-earnings crash (50.29 -> 24.0, -52.3%). User must verify VCYT close on 11-05 in Webull.
  integrity_seen.json now records this as known; will not re-alert unless VCYT row changes.
2026-11-06: weekly scorecard. Reports/2026-11-06-scorecard.md.
  ON1 paper strong (t 3.10, +86.2 bps) — PASS likely Tue 11-10 AM. Real-price gap large (4 days).
  EPRE ~57 trades from checkpoint A — will pass easily at +20.1 bps.
  V2 rank mean clears bar but t=0.82 far from 2 — likely NO-GO at 100.
  G2 still running despite FAIL — Director must retire.
