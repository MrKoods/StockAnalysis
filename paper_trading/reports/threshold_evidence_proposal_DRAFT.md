# DRAFT — evidence review for `confidence.min_threshold` (not applied)

**Status: draft for human review. Nothing in this document has been applied to
`config/swing_config.yaml`.** Per this project's own versioning rule, actually
changing `confidence.min_threshold` requires a version increment and a logged
re-backtest in `CHANGELOG.md` — no exceptions. This document collects the
evidence that a threshold change might be warranted; it deliberately stops
short of running that formal re-backtest or picking a final number, since
either of those is the actual tuning decision, not evidence-gathering.

Generated from `paper_trading/score_distribution_diagnostic.py`,
`paper_trading/live_collinearity_diagnostic.py`, and the existing
`backtesting/reports/sensitivity_analysis.csv`, against real data as of
2026-07-28 (9 days of paper trading, 20 scan runs, 215 ticker-scans, 11
tickers across semiconductors + regional banks).

## The evidence

1. **In 215 real ticker-scans, the composite score has never once reached 90,
   or even 80.** Max ever observed: 71.72 (RF, regional banks). p99 is 66.75.
   Even a threshold of 85 — the most lenient candidate already in
   `config/swing_config.yaml`'s own `sensitivity_thresholds` list — would have
   produced a 0.0% qualification rate over this entire window.

2. **No individual scoring category is the bottleneck — joint alignment is.**
   Each category has independently hit high utilization at least once
   (Sentiment and Fundamental have each hit 100% of their max on some scan),
   but no ticker-day has had all 5 categories simultaneously in their own top
   20% (0.0% joint-peak rate at the 80th-percentile bar; 22.8% had 2+
   categories jointly there). A fixed 90-point composite is structurally a bet
   that categories peak together — live data shows they don't, at least not
   yet in 9 days of observation.

3. **The tail-dependence read is mixed, not a smoking gun.** The hypothesis
   going into this (see the original review) was that the backtest's
   proxy-Sentiment — built directly from price momentum — might be inflating
   how often Technical and Sentiment appear to peak together, versus genuinely
   independent live data. Measured: backtest lift = 1.08x (barely above the
   1.0x "no more than chance" baseline); live lift = 0.44x (live Technical and
   Sentiment peaks co-occur *less* than chance would predict). This doesn't
   strongly support the inflation hypothesis — it's a mild, inconclusive
   signal, not confirmation. The joint-peak-rate finding above (#2) is the
   stronger, more direct piece of evidence here.

4. **The existing backtest sensitivity table** (`backtesting/reports/sensitivity_analysis.csv`,
   pre-existing, unchanged by this review) already has data at lower
   thresholds on the historical sample:

   | threshold | qualifying trades | win rate | avg R:R | signals/month | max consec. losses |
   |---|---|---|---|---|---|
   | 85 | 32 | 59.4% | 2.43 | 0.66 | 7 |
   | 87 | 29 | 55.2% | 2.32 | 0.59 | 7 |
   | 90 | 27 | 51.9% | 2.23 | 0.55 | 7 |
   | 92 | 22 | 54.6% | 2.28 | 0.45 | 5 |
   | 95 | 13 | 69.2% | 2.11 | 0.27 | 3 |

   Note this table is from `_get_test_outcomes`' broader out-of-sample signal
   set, not the same fixed-slice sample the official 100-trade go-live gate
   uses (18 qualifying trades at 90 there) — it's directionally useful, not
   the formal gate result. Lower thresholds trade win rate for volume in the
   expected direction; 85 nearly triples signal frequency over 90 without
   collapsing win rate (59.4% vs. 51.9%).

## What this evidence does and doesn't support

**Supports:** the 90-point bar was calibrated without live category-score
data (it predates paper trading accumulating any real Positioning/Sentiment
history), and live data now shows categories don't jointly peak often enough
for 90 to produce any signal at all in a 9-day window across 11 tickers. That
alone is worth a formal re-evaluation.

**Doesn't yet support:** a specific replacement number. 9 days is a small
sample — the honest floor recommendation elsewhere in this codebase
(`_MIN_ROWS_FOR_MEANINGFUL_READ = 30` in the collinearity/score-distribution
diagnostics) hasn't been cleared yet either. And a lower threshold's backtest
performance (table above) hasn't been checked against the *formal* fixed-slice
go-live criteria (100+ qualifying trades, Sharpe ≥ 1.0, max drawdown ≤ 15%,
expectancy CI) — only the looser sensitivity-analysis sample.

## Recommended next step (not taken here)

Once more live scan history exists (say, 30+ days, matching this codebase's
own existing minimum-sample convention), re-run this diagnostic and, if the
0%-qualification pattern persists, run a full fixed-slice backtest at one or
two candidate thresholds (85 looks like the natural first candidate per the
table above) through the *formal* go-live gate — not just the sensitivity
table — and log that as its own versioned `CHANGELOG.md` entry per this
project's rule. That backtest run is the actual tuning decision; this
document is scoped to stop before it.
