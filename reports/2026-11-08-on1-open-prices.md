# ON1 paper results are inflated by bad opening prices (2026-11-08)

**Finding.** `daytrade/on1_paper.py` `_score()` takes `next_open` from yfinance once, at the 06:45 PT evaluate
(9:45 AM ET, session still open). Those opens are often far from where the stock traded. The ledger is never re-scored.

**Evidence**
- Webull minute bars: FIS opened 30.43 on 11-04 (ledger 40.62); PRIM traded ~65.67 in its first full minute on
  11-05 (ledger 84.45). KOP on 11-06 has no Webull bars returned; the quote and settled Yahoo open agree (~29) against
  a ledger of 43.35.
- All 18 days re-scored from settled daily bars (Yahoo, refreshed 11-08), 1,321 of 1,332 trades:

| | Mean | Day-t |
|---|---|---|
| Ledger (frozen scoring) | +87.3 bps, after its modelled costs | 3.11 |
| Settled opens | +24.7 bps, BEFORE costs | 0.93 |

515 trades differ by more than 100 bps, 141 by more than 500. The cause of the bad opens is inferred (intraday Yahoo
data at 9:45 ET later corrected), not proven.

**At real Webull quotes** (4 days): the 223 bps gap to paper is ~110 bps of open-price difference and ~100 bps of spread.

**What this means.** ON1's day-20 paper verdict (scored Tue 2026-11-10) uses these prices. A PASS there isn't evidence
of an edge. Hard limit 2 stops the team changing V3 or a running test's rules, so the user decides.

**Proposal for the user.** Treat the current ledger as compromised. Either re-score ON1 after the close using settled
opens as a declared correction, or restart it with evaluate moved to after the close. Check whether any other
test takes a same-morning open from Yahoo (not checked yet; G2 enters at 9:32 and is retired).

## Resolved 2026-11-09 (user's decision: do what's best)
Correction applied by `StockAnalysis-V3/daytrade/on1_correct_opens.py`: close and next_open on every scored row replaced
with Yahoo's settled daily bars, bps recomputed the same way. Picks, cost and verdict rule unchanged.

| 18 days, after costs | Mean | Day-t |
|---|---|---|
| Before | +86.2 bps | 3.10 |
| After | +19.6 bps | 0.74 |

Independent check against Webull's 9:31 mid on 359 trades: median miss 114 -> 47 bps; misses over 500 bps 57 -> 2.
895 of 1,332 rows changed; 1 had no settled bar and kept its original numbers. Original ledger:
`data/paper/on1_paper_ledger_before_open_correction_2026-11-09.csv`; changes: `data/paper/on1_open_corrections_2026-11-09.csv`.
`_score` now waits until the session has finished, so picks are scored one day later.
