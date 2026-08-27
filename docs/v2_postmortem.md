# V2 post-mortem — the rules V3 runs on

V2 ran from 2026-06-29 (v1.0.0) to 2026-08-26 (v2.2.111): ~110 versions, four
sectors, 49 tickers, a five-category 100-point scoring model, 42 trade
structures, ~150 config keys, 1,620 tests. It never traded real money and never
passed its own go-live gate.

This document is the distilled output of that work. The full narrative is in
`CHANGELOG.md`, which is retained on this branch as the archive; the complete
V2 codebase is on the `Version-1` branch.

---

## What actually went wrong

**The order of operations.** V2 built a complete trading architecture on top of
hypotheses that had never been individually tested, then tried to validate the
whole bundle at once. When it didn't work, the available move was always to add
or fix a component — never to conclude that a component had no edge, because no
component had ever been measured on its own.

The final state of the evidence, as of v2.2.111:

| Measure | Value | Reading |
|---|---|---|
| Composite score IC | +0.2276 (p<0.0001, n=479) | Significant — but see below |
| Technical-only IC | −0.0231 (p=0.61) | Indistinguishable from noise |
| Real-only IC (Tech+News+Fundamental) | −0.0135 (p=0.77) | Indistinguishable from noise |
| Walk-forward windows passing | 0 of 6 | — |
| Qualifying trades, 13 years | 10 | Far too few to conclude anything |
| Deflated Sharpe | −4.52 (PSR 0.00) | The headline Sharpe was selection noise |

The only significant reading came from the composite score, whose Sentiment
component in the backtest was a **price-momentum proxy**, not the live
StockTwits data — i.e. the one thing that measured as predictive was a
backtest-only artifact that live trading could never reproduce.

---

## The traps — and the rules that follow from them

### 1. A proxy is not the signal
`backtesting/simulation.py` substituted a price-momentum proxy for Sentiment and
a static neutral for Positioning, because neither had backtestable history. Two
of five categories were therefore never tested at all, and the composite's only
positive IC traced back to the proxy.

> **Rule:** if a data source has no point-in-time history, it cannot be
> backtested, and it does not go in the model. Test what you can actually
> measure. Do not let a stand-in earn credit for the real thing.

### 2. Correct for multiple testing, always
v2.2.96 reported a "statistically significant negative signal" from a p=0.0501
reading. It was one of ~15 correlations computed in the same run. Under
Benjamini-Hochberg it did not survive, and its bootstrap CI straddled zero
(v2.2.97).

> **Rule:** count the tests in the batch before reading any p-value. Report
> `bh_significant` and a bootstrap CI, never a bare p-value. If the two
> disagree, the finding is not actionable.

### 3. Never hardcode a threshold that exists elsewhere
`confidence >= 90` was left in `backtest_engine.py` after the live threshold
moved to 70, then independently duplicated into three more files. Every backtest
number for four months graded a signal population live trading could not
produce. The bug recurred three times across two days, and every "the model
passes" milestone in V2's history was a casualty of it.

> **Rule:** one definition, imported everywhere. If a constant appears twice, it
> is a bug waiting for its third copy.

### 4. Simulate the fill
Until v2.2.63 the backtest filled every signal at the signal bar's own close,
never checking whether price traded into the entry zone — a systematic bias
toward the cleanest, most-likely-to-win setups. Correcting it dropped avg R:R
from 2.03 to 1.41.

> **Rule:** an entry you could not actually have gotten is not a trade. Model
> fills, costs and slippage before reading any performance number.

### 5. Silence is not evidence
A recurring shape, found in at least five places: missing data scored
identically to bad data. No news scored as unanimous bad news. No social posts
scored as bearish posts. A failed SEC request scored as "nothing was filed". A
padded placeholder day scored as real history and produced maximum momentum.

> **Rule:** absent, failed and neutral are three different states. Never collapse
> them. Every fetch path must distinguish "the vendor returned nothing" from
> "the call failed" from "the value is genuinely neutral."

### 6. A sample size problem cannot be fixed downstream
Qualifying signals fired roughly 1 in 250 ticker-days. Expanding the watchlist
23 → 49 tickers (v2.2.96) did not raise the qualifying trade count — it fell,
because relative-strength and rotation modifiers were computed against each
sector's own constituents, so new names shifted the baseline for the existing
ones rather than adding independent observations.

> **Rule:** decide up front how many independent observations a hypothesis needs
> to be testable, and check that the design can produce them before building it.
> If the answer is "not enough", change the design, not the filter.

### 7. The gate must be reachable and meaningful
The V2 go-live bar (80% win rate, 90/100 confidence, 1:3 R:R) was a v1.0 guess.
Real swing systems run 45-58% win rates and make money on payoff asymmetry. The
bar was never hit, distorted decisions for months, and is what let the
hardcoded-90 bug hide in plain sight.

> **Rule:** the bar is positive risk-adjusted expectancy with a confidence
> interval that excludes zero, on a sample large enough to mean it — proven
> out-of-sample and then again forward. Not a win-rate target.

### 8. Configuration that does nothing
A coverage audit found 109 config keys that no code path read. Changing them
changed nothing, silently. 68 were deleted, 39 wired up, and 5 real
config-vs-code value mismatches surfaced in the process.

> **Rule:** a config key with no reader is a lie. Keep the config small enough
> to hold in your head.

### 9. Tests must not write to real files
Repeatedly: test runs polluted the production `validation_log.csv` (found 99.7%
synthetic), `trade_outcomes.csv` (285 fake rows), overwrote real calibrated
weights, and once posted a real message to the live Discord channel.

> **Rule:** autouse fixtures redirect every real path by default. Never rely on
> each test remembering.

### 10. You must be able to conclude "no edge"
The deepest failure. Two months of work produced no mechanism for abandoning a
hypothesis, so every disappointing result became a bug hunt or another modifier.

> **Rule:** write kill criteria before starting the work, not after seeing the
> result.

---

## What V2 got right, and V3 keeps

- **The statistics.** IC, bootstrap CIs, Benjamini-Hochberg, deflated Sharpe,
  Sortino/Ulcer/drawdown-duration. Retained in `backtesting/metrics.py`,
  decoupled from any strategy shape.
- **The willingness to audit.** Every "passes" that turned into a "fails" was
  real progress. That instinct is the reason this rebuild is possible.
- **The habit of writing down what was learned.** This document exists because
  V2 kept a `CHANGELOG.md` honest enough to post-mortem.

---

## The V3 process, in one line

**Signal before architecture:** prove a single hypothesis predicts returns, on a
sample large enough to mean it, out-of-sample, net of costs — and only then
build anything around it.
