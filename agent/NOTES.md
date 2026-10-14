# Agent notes (the review agent's memory between runs)

Created 2026-10-14. Keep under ~300 lines; summarize and prune.

## Watch list
- 2026-10-14 is the first V2 shares-only scan and the first random-control scan: confirm new rank
  rows are `shares` and random_trades.csv appears with <= 2 rows per sector.
- 2026-10-14 06:45 is the first real ON1 paper evaluate run: confirm on1_paper_ledger.csv gets bps filled.

## Open questions (candidates for weekly research)
- V2 rank: is the profit from the 15-day time stop alone? (target hit 3/61, stops -27R, time stops +29R)
- V2 rank: bank shorts drove the profit but picked banks did no better than other banks — skill or sector beta?
- V2: which score components (if any) predict R? Earlier IC work found no robust edge.
- V3 G2: does the edge survive realistic open-auction costs in less-liquid names?

## Research done
(none yet)

## Log

### 2026-10-13 daily review
- All tasks OK (result 0). First agent run.
- Pre-market: 1 transient SA /symbols/get-factor-grades empty-body error; scan completed fine.
- V2 rank: 7 new options signals (last options-regime scan). shares_only takes effect 2026-10-14.
  Snapshot "!! not shares" warning is a known false positive on transition day.
- V3 G2 paper: +102.7 bps today; 3 sessions, mean +33.4 bps, t 0.63 (too early).
- V3 ON1 paper: 74 signals logged, bps column unfilled; first evaluate 2026-10-14 06:45.
- No bugs found. No fixes proposed.
