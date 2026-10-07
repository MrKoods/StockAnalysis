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

## Round 1 of "3 more models" (PROTOCOL5, 2026-10-06 night)
Five families, 595 strategies x 8 filters = 4,723 configs on S&P 500 search data.
- XS cross-sectional morning, PER time-of-day periodicity, MR idiosyncratic mean reversion,
  NR narrow-day breakout: typical config ~ -4 bps = exactly the 2+2 bps cost -> zero gross edge.
  Their best configs were flat/negative on the holdout. Dead.
- ON overnight: coherent positive region (PBO 0.01). Best: buy the worst 5% last-hour losers
  at the close, sell next open (ON1). Holdout +11.1 bps t 2.24 (< 2.6) -> Stage 3 fail; no model
  selected under PROTOCOL5.
- Flaw found: "raw" vs "minus-market" signals give identical ranks, so the shortlist rule picked
  exact duplicates. Fix next round: dedupe candidates with identical trades.
Separate pre-registered test (SHORTLIST6, declared as a deviation): ON1 on midcaps +7.2 bps t 1.89,
small caps +9.0 bps t 2.38 -> FAIL (midcap t below 2.0), though positive in every slice and year.
ON1 added to the forward test as a SECONDARY candidate, labelled as not passing.

## Round 2: volume / stocks-in-play families (PROTOCOL7, 2026-10-06 night)
266 strategies x 8 filters = 1,950 configs. Nothing passed Stage 3.
- SIP (first-hour high-RVOL names, with/against the first-hour move): best search t 1.8-2.0,
  holdout negative (-2.7 to -4.6 bps). Dead.
- GAPV (gaps split by volume): best = low-volume gap fade, long only (a G2 neighbour): holdout
  +6.3 bps t 1.32 -> fail. High-volume gap continuation ("news gaps go") did not show up.
- ONV (overnight + last-hour volume): volume conditioning added nothing; the top configs are ON1
  itself (holdout t 2.24) and its 10% version (t 2.17) -> fail.
Cumulative: ~6,700 configs over 8 non-sweep families; G2 remains the only confirmed model,
ON1 the only secondary.

## Route 2: short-horizon DAILY families (PROTOCOL8, 2026-10-07)
Data: yfinance daily since 1999 (S&P 500/400/600 current constituents + 15 ETFs). Market-hedged
metric, Newey-West t. 559 strategies, 4,860 configs searched on S&P 500 2000-2017.

**Look-ahead bug caught before reporting:** the first run computed filter features from the entry
session's close for open-entry trades (search t up to 33, "with_trend" everywhere). Fixed, regression
test added, Stages 1-4 rerun unchanged (logged in the protocol; buggy log kept for the record).

Corrected result: NO config passes the 2018-2026 S&P 500 holdout. Classic effects were strong in
2000-2017 and decayed after: short-term reversal t 6.6 -> 1.7; IBS mean reversion t 10.5 -> 1.6;
breakout fade t 7.5 -> 1.96; daily gap fade (open -> close) t 23.6 -> -1.35; overnight reversal
t 9.9 -> negative; turn-of-month = luck.

## G2 re-check, market-hedged (diagnostic, 2026-10-07)
G2's earlier tests were not market-hedged. Hedged against the equal-weight universe over the same
open -> 13:30 window (~1 bp/side): S&P 500 +4.3 bps/trade (t 2.57; since Jul 2025 +2.6, t 0.91),
S&P 400 +6.0 bps (t 3.51; since Jul 2025 +7.8, t 2.57); positive for longs and shorts. Raw was
+9.6 / +15.2 bps -> roughly half of the apparent edge was market drift. The daily-bar G2-like gap
fade held to the close: strongly positive 2000-2017, ~0 hedged since 2018. G2's forward pass bar is
unchanged (pre-registered, raw); the hedged figure will be reported alongside and should be
treated as the more honest one.

## Round 4: 10,000 multi-signal combination models + 8 ridge models (PROTOCOL9, 2026-10-07)
Blends of 2-4 of 14 pre-entry signals (random weights), 8 entry/exit windows, market-hedged,
2 bps/side; look-ahead test (random per-value perturbation of all post-entry data) passes for
every window before the run.
- Typical random model: -4.0 bps/trade = exactly the cost (zero gross edge); 95% within
  [-8.7, +0.6] bps. Best search t 3.63 vs luck p95 4.15 (p 0.29) -> no better than chance.
- The top models were almost all "fade the gap in the first hour" blends (G2's mechanism).
- Holdout (S&P 500, Jul 2025+): all 18 candidates FAIL; most turned negative (top random model
  +7.4 -> -5.1 bps; ridge open->10:30 +6.2 -> -1.4 bps). No candidate reached Stage 4.
- CSCV PBO came out 0.0 here because it only resamples within the search period; it cannot see a
  change of regime after it. The out-of-time holdout is what caught the failure.
Cumulative: ~22,000 non-sweep variants across 15 families + combinations + ML; G2 remains the only
confirmed model (thin, ~+4-6 bps hedged), ON1 secondary.
