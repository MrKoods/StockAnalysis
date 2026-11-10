# Scorekeeper notes (memory between runs)

Created 2026-10-27.

## Watch list (as of 2026-11-10)
- V2 rank go/no-go: last noted 79/100 trades (2026-11-06); likely NO-GO at 100 (week-t 0.82, need 2)
- V3 ON1 paper: day 20 was Mon 2026-11-09, scored at Wed 2026-11-11 06:45 evaluate — verdict pending
- V3 ON1 real-price: 5 days (2026-11-02 to 2026-11-06), 368 trades, real_mean -24.2 bps vs paper +71.3
  (gap 95.5 bps ≈ spread); real_t -0.54. COLLECTING (need 15 days). Direction negative — watch closely.
  11-07 through 11-09 close captures exist; 11-10 close MISSED (see below). Rule: 15-day point ~2026-11-24.
- V3 G2 paper: RETIRED 2026-11-08 per TEAM.md. No further tracking needed.
- V4 EPRE: checkpoint A (1,000 trades) imminent; hedged mean well above -20 bps bar.
- V4 EPRE real-price: 447 trades, 4 exit days (through 2026-11-09); real_hedged +82.5 bps, spread 12.2,
  real_t 1.05. Missed today's (11-10) exit-day capture — 19 trades permanently a gap unless user runs fix.
- VCYT: flagged 2026-11-05 as outlier (-5228 bps). integrity_seen.json records it as known.
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
2026-11-10: diagnosis. Reports/2026-11-10-diagnosis.md.
  QuoteClose failed (0x800710E0) — machine asleep 10AM-3:30PM PT, Windows killed task on wake.
  19 EPRE exit-day trades (11-06 entry batch) missed close capture; permanently a real-price gap
  unless user runs `python tools/quotes.py capture close` tonight.
  ON1 real-price now 5 days: -24.2 bps (negative direction, t -0.54). Still COLLECTING.
