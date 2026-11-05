# Scorekeeper notes (memory between runs)

Created 2026-10-27.

## Watch list (as of 2026-10-30)
- V2 rank go/no-go: 65/100 trades; mean R -0.006 (need +0.15), t -0.25 — looking weak, likely NO-GO
- V3 ON1 paper: 13 days, t 1.91, mean +53.5 bps — softening (was t 2.37/+81.6 bps at 9 days); checkpoint at 20 days = Tue 2026-11-10 AM; borderline
- V3 G2 paper: FAILED day 20 (2026-11-05): mean -33.5 bps, t -2.05. Director to retire.
- V4 EPRE: 836 closed trades, hedged mean +28.7 bps, day-t 0.11 (7 exit days) — too early for t; checkpoint A at 1,000 trades
- V4 EPRE real-price: 322 trades, 2 exit days only; real hedged +110.6 bps vs paper +111.2 (spread cost 12.6 bps). Too early.
- VCYT: flagged 2026-11-05 as outlier (-5228 bps). User to verify $24.0 exit close vs Webull.
- ON1 real-price (Quote Clerk): 0 days captured. The 2026-10-30 runs in state/usage.csv were TEST runs
  (note test_run), not failures; scheduled captures start Mon 2026-11-02 06:31 / 12:56 PT. Must be working before
  ON1 paper matters.
- g2_paper_task.log stale since 2026-10-09 (known quirk; G2 ledger is the valid source)

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
