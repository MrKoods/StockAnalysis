# Scorekeeper notes (memory between runs)

Created 2026-10-27.

## Watch list (as of 2026-11-11)
- V2 rank go/no-go: 83/100 trades (2026-11-11); mean +0.135R after costs (need >= +0.15), week-t 0.66 (need >= 2). Likely NO-GO at 100.
- V3 ON1 paper: day 20 checkpoint scored 2026-11-11. CONTINUE (mean +18.9 bps >= +5 but t 0.77 < 2). Day 40 scored ~Thu 2026-12-10. Need +50.6 bps/day avg over next 20 to PASS.
- V3 ON1 real-price: 6 days (2026-11-02 to 2026-11-09), 441 trades, real_mean -45.5 bps (t -1.08) vs paper +47.2. COLLECTING (need 15 days, ~2026-11-24). Direction firmly negative — spread ~48 bps half-spread eating paper edge.
- V3 G2 paper: RETIRED 2026-11-08 per TEAM.md. No further tracking needed.
- V4 EPRE: 987 closed, mean +25.3 bps hedged. Checkpoint A (1,000 trades) imminent — 13 trades away. Bar: FAIL if < -20 bps. Well clear.
- V4 EPRE real-price: 4 exit days. 19 exit-day trades from 11-06 entry batch permanently missed (11-10 QuoteClose failure, user ran fix or not).
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
2026-11-11: diagnosis + ON1 day-20 checkpoint. Reports/2026-11-11-diagnosis.md.
  SA /symbols/get-factor-grades transient outage at premarket (~05:30 PT). 3 attempts, all empty body.
  Graceful fallback: NVDA/AMD/ASML fundamentals carried forward, scan completed, 2 signals logged (KEY, PFE). No action needed.
  ON1 day 20: CONTINUE (mean +18.9 bps, t 0.77). Real-price -45.5 bps on 6 days — negative direction, spread eating paper edge.
