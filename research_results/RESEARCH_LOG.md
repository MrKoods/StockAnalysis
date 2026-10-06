# Liquidity Sweep Reversal — variant search (2026-10-06)

**Question:** can any variant of the user's strategy show a real, after-cost edge?

**Data:** yfinance only. 1m bars: 20 sessions (2026-09-08..10-05). 5m bars: 59 sessions
(2026-07-14..10-05). 50 liquid US stocks/ETFs. Costs: 1 tick ($0.01) slippage per side.

**Method:** split every dataset in time before searching (1m: search Sep 8-23 / holdout
Sep 24-Oct 5; 5m: search before Aug 24 / holdout after). 734 configurations scored on the
search split only (`configs_tried.csv`). A 7-candidate shortlist was written down
(`SHORTLIST.md`) before the holdout was evaluated once (`holdout_results.csv`).

## Findings (search split)
- Exits (162 configs): every change moves mean R by only about ±0.05. Exits don't fix it.
- Entries (104): limit entries at the zone, without confirmation, lose money under every exit.
  The confirmation candle matters; the user's trigger/zone choices are about as good as any alternative.
- Detection params (60): non-monotonic, noise-driven; nothing robust.
- Filters (162): "trade with SPY / with the day's move" looked strong, but it held only for shorts
  in a down-trending month. Rejected as market direction, not an edge.
- Reverse diagnostic: trading the opposite side loses ~0.19R (t -2.5), so the setup direction does
  carry a small signal (~+0.1R before costs).
- Universe subsets: no consistent pattern.

## Holdout
All 1m candidates were flat or negative on the holdout (locked rules: -0.14R, n=52).
Only **C6** (5m base, sweep on 15m, any close back out of the zone, fixed 2R target) was positive
on both splits: +0.086R (n=215) search, +0.105R (n=211) holdout. Neither split was significant.
All 59 sessions: +0.095R, n=426, day-clustered t 1.8, 95% CI [-0.01, +0.20].
Post-hoc robustness (not evidence): 1.5-3R targets all +0.07 to +0.12R; both directions positive;
3 of 4 months positive; +0.055R without the best 3 tickers; +0.045R at 3x slippage.

## Status
C6 = UNPROVEN candidate. A forward test runs daily on sessions from 2026-10-06 on
(`python -m daytrade forward`, ledger `data/forward/c6_forward_trades.csv`). Pass bar fixed in
`daytrade/forward.py` before any forward data existed.
