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

## Mass search (2026-10-06, same day)
User asked for thousands of variants. 309,744 configs scanned (1m: 162,906 over 20 sessions;
5m: 146,838 over 59 sessions) = 126 detection variants x 96 exits x 14 filters per timeframe.
Vectorized exits verified identical to the reference simulator (tests/test_mass.py).

| | 1m | 5m |
|---|---|---|
| eligible configs (enough trades) | 135,576 (n>=60) | 69,114 (n>=150) |
| median mean R/trade | -0.042 | -0.003 |
| best-of-N luck test p | 0.82 | 0.35 |
| PBO (CSCV) | 0.42 | 0.69 |
| out-of-sample daily R of the in-sample best | -0.21 | -0.16 |

The best configs (t ~3-3.7) are no better than the best of the same number of zero-edge
configs. Picking the in-sample winner loses money out of sample on average. No setting has a
consistent marginal effect across both timeframes except "short only", which is market direction.
C6 sits at the 95th percentile of the 5m distribution, exactly where a lucky draw would sit.
Conclusion: no evidence that any variant of this strategy has an edge on this data.
C6's forward test continues unchanged as the only clean test.

## Fresh-ticker test + hourly 2-year search (2026-10-06, afternoon)
**Fresh tickers** (pre-registered in SHORTLIST2_fresh_tickers.md before download): 463 S&P 500
stocks never used in any search. All 42 candidates FAIL (C0, C6, top-20 1m, top-20 5m mass-scan
winners). Average mean across candidates: -0.03R. C6: -0.020R over 4,418 trades.
Search winners at t ~3.5 on the old 50 tickers became t ~ -1 to -3 on new tickers.

**Hourly version** (core idea: sweep of PDH/PDL or 2-day H/L, reclaim, intraday reversal), 509
tickers x 387 search sessions (Nov 2023 - Jun 2025; Jul 2025+ locked, never scored):
21,168 configs, typically 1,000-15,000 trades each. Median config -0.013R; 95% of configs in
[-0.037, +0.014]. Best +0.044R (t 2.1) = luck (best-of-N p 0.80, PBO 0.39).
No holdout shortlist was made: nothing beat the luck baseline, so there is nothing to confirm.

## Verdict on the strategy family
Across ~331,000 variants, three timeframes, 513 tickers and 2 years: no evidence of an edge.
The true effect of a sweep-reversal trade on liquid US stocks is about 0R before costs, slightly
negative after. More variants of this family would only produce more false positives.

## Other strategy families (2026-10-06, evening) — FIRST REAL CANDIDATE: G2 gap fade
Families on hourly bars, 509 S&P 500 + core tickers, search Nov 2023 - Jun 2025 (9,768 configs):
- MOM (intraday momentum/reversal): best = luck (p 0.997). Rejected.
- ORB (first-hour breakout): every config negative. Rejected.
- GAP: one coherent region (fade the opening gap toward the previous close, only when that
  direction agrees with the 20-day trend, exit around midday) was positive across many
  neighbouring configs. CSCV PBO 0.08, in-sample best positive out of sample in 89% of splits.
  Pre-registered luck test: p 0.40 (t-standardized version, informational: p 0.19) -> not a
  family pass; the top 2 configs went to the holdout under rule 2 of SHORTLIST3.
Holdout (Jul 2025 - Oct 2026, opened once): both positive, both directions, both halves, but
t 1.87 / 2.37 < the pre-registered 2.6 -> formally FAIL.
Independent confirmation (SHORTLIST4, pre-registered before download): G2 =
GAP(0.25 ATR, fade, open, target prev close, no stop, exit 12:30 bar close, with 20d trend)
on 396 untouched S&P 400 midcaps: +0.045 ATR (~+0.17% of price) per trade, n 50,497,
t 4.70, longs +0.049 / shorts +0.041, both years positive, holds at 2 bps/side -> PASS.
Artifact check: entering at the official opening-auction price instead of the first hourly
print gives the same result (+0.0383 vs +0.0380 ATR) on S&P 500 days where both exist.
Costs are the main risk: breakeven ~4 cents or ~4-5 bps per side on S&P 500 names.
G2 forward test started (forward.py; pass bar fixed in code, >= 40 sessions, t >= 2.0).
