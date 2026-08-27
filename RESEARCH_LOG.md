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

**Status:** not started

**Hypothesis:** n/a — infrastructure.

**Method:** Build a date × ticker panel of adjusted daily OHLCV for current
S&P 500 constituents, ~2005-2026, plus SPY and VIX. Survivorship bias is
knowingly accepted at this stage and documented; point-in-time membership is a
Phase 6 upgrade only if the signal proves real.

**Pass bar:** panel reconciles against a hand-checked sample; adjusted returns
match an external reference for 5 spot tickers.

**Kill:** free daily data cannot be made clean enough to trust.

**Result:** _pending_

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
