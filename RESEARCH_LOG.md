# Research log — V3

One entry per experiment. Written **before** the run (hypothesis, method, pass
bar), completed **after** (result, verdict). A result recorded after the fact is
a result you have already rationalized.

Verdicts are one of: **CONFIRMED** (pass bar met) · **REJECTED** (pass bar
missed) · **INCONCLUSIVE** (the test could not answer the question — say why) ·
**EXPLORATORY** (mapping, no bar).

Rules that apply to every entry:

- Count how many configurations were tried before reporting a number. Report the
  deflated Sharpe alongside the headline.
- Report `bh_significant` and a bootstrap CI, never a bare p-value.
- Out-of-sample data (2019-2026) stays untouched until Phase 6. If you look at
  it, say so here, and it stops being out-of-sample.

---

## Backlog

Ideas that arrive mid-phase go here, not into the code. Nothing leaves this list
until the current hypothesis has a verdict.

- _(empty)_

---

## Phase 0 — Strip-down & scaffold

**Date:** 2026-08-26
**Verdict:** CONFIRMED

Removed the V2 model from `Version-3` (archive preserved on `Version-1`).
Retained the statistical lab, the yfinance client and its backoff wrapper,
logging/atomic-IO plumbing, robust z-score, and the fill-simulation gate.

Three deviations from the published plan, decided while tracing imports:

1. **`backtesting/walk_forward.py` deleted, not rewired.** It was built around
   `simulation._simulate_test_signals` and V2's per-signal outcome dicts. V3's
   strategy is a cross-sectional panel rebalanced on a schedule — a different
   shape entirely. A fresh walk-forward is written in Phase 6 against the panel.
2. **`shared/indicators/technical_common.py` deleted, not kept.** 513 lines
   shaped around V2's 8-point sub-signal scoring and coupled to
   `volume_profile.py`. V3 needs trailing returns, moving averages and ATR on a
   panel — clean pandas, written in Phase 1. Keeping the module to use three
   functions from it would have been exactly the trap this rebuild exists to
   avoid.
3. **`metrics.py` signatures changed.** IC and bootstrap functions took V2's
   outcome-dict shape, making the measurement layer depend on the strategy
   layer. They now take plain sequences. Added `compute_cross_sectional_ic`
   (per-date IC, averaged) — the honest metric for a ranking signal — and
   `summarize_returns` as the standard reporting bundle.

---

## Phase 1 — Data assembly

**Date:** 2026-08-26
**Verdict:** CONFIRMED

**Hypothesis:** n/a — infrastructure.

**Method:** Built a date × ticker panel of adjusted daily closes and dollar
volume for current S&P 500 constituents plus SPY and ^VIX. Survivorship bias
knowingly accepted and documented; point-in-time membership is a Phase 6
upgrade, and only if the signal proves real.

**Pass bar:** panel reconciles against a hand-checked sample; adjusted returns
match an external reference for 5 spot tickers.

**Result: PASS — 18/18 reconciliation checks.**

Panel: **5,699 dates × 503 tickers, 2004-01-02 → 2026-08-26**, median coverage
99.98%, no duplicate dates, monotonic index, no non-positive prices, price and
volume panels aligned on both index and columns, no context-ticker leakage.
Download took 72s.

Reconciliation (`python -m research.reconcile`), against facts sourced outside
the panel:
- **8/8 known splits** show no jump in the adjusted series (AAPL 7:1 and 4:1,
  NVDA 4:1 and 10:1, TSLA 5:1 and 3:1, AMZN 20:1, GOOGL 20:1).
- **5/5 SPY calendar-year total returns** match published figures to within
  **0.07pp** (2008, 2013, 2017, 2020, 2022).
- **5/5 spot tickers** match an independent fetch path (`yf.Ticker.history`)
  to within **0.0001%** across 252 dates.

### Two real findings

**1. MNST has corrupt vendor data — excluded.** Six moves >50% with alternating
signs between 2026-07-20 and 2026-08-07, oscillating between ~$95 and ~$47 — a
clean 2:1 factor appearing and disappearing on scattered days. This is not a
split (a split happens once and adjusts all prior history); the vendor is
intermittently serving unadjusted values. Left in, it would have handed a
momentum ranker enormous spurious signals on a name that never moved.

Rather than hardcode a one-off fix, `detect_adjustment_anomalies()` now looks
for the general signature — repeated large moves whose signs alternate AND whose
ratios cluster near a clean split factor. All three conditions together are what
keep 2008's genuine bank collapses and the 2020-03-09 oil crash out of the
results. It runs on every `--verify` and separates *handled* anomalies from
*unhandled* ones, so a re-download cannot silently reintroduce this or hide a
new instance. On the 503-name panel it flags exactly one ticker.

Excluded in `config.EXCLUDED_TICKERS` at **load** time, not download time, so
the cache stays a faithful record of what the vendor returned and the exclusion
stays auditable.

**2. The first version of the SPY check was wrong, not the data.** It measured
from the year's first close instead of the prior year's final close, silently
dropping the first trading day. 2013 read as +29.0% against a published +32.3%,
because 2 January 2013 alone was +2.56%; every other year was understated the
same way, just less visibly. Fixed, and the tolerance tightened from 2pp to
0.5pp — once measured correctly the panel is accurate to 0.07pp, so a loose
tolerance would only hide future drift.

### Accepted limitations

- **Survivorship bias.** The universe is *current* index membership, so names
  dropped from the index (usually after poor performance) are absent from the
  whole history. This inflates any long-only result, momentum included. Every
  Phase 2-5 number carries this caveat.
- **43 tickers under 50% coverage** — verified to be legitimate late listings,
  not data gaps: IPOs (UBER, ABNB, COIN, RDDT, PLTR), spin-offs (CARR/OTIS,
  GEHC, KVUE, SOLV/GEV, VLTO), mergers (KHC, DOW). No ticker has a missing
  chunk mid-history.
- **Single vendor.** These checks catch a corrupted pipeline, not a wrong
  vendor. Detecting that needs a second source — Phase 6, and only if the
  signal proves real.

---

## Phase 2 — Replicate classic momentum

**Status:** not started

**Hypothesis:** 12-1 cross-sectional momentum (rank on return from t−252 to
t−21, monthly rebalance) produces a positive long-short spread on this universe,
consistent with the published literature.

**Why this phase exists:** before trusting the lab on anything new, it must
reproduce a known result. If it cannot, the pipeline is wrong and every
subsequent number is meaningless.

**Pass bar:** long-short Sharpe in the ~0.4-0.6 range gross, full sample;
pooled per-date IC positive and BH-significant; the 2009 and 2020 momentum
crashes visible in the equity curve.

**Kill:** cannot reproduce the documented sign and rough magnitude → stop, fix
the lab, no new signals until it replicates.

**Result:** _pending_
