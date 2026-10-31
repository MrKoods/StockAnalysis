# Skeptic review — split-announcement-drift (2026-10-31)

Verdict: **PASS** to holdout. Chosen = pre-registered `h4_r2` (hold 4 sessions, forward splits ≥2:1),
train week-clustered net t **3.08**, mean **64.98** gross bps over 395 trades / 282 weeks.

## 1. Look-ahead — PASS
- Entry uses the OPEN of `first_session` (`test.py:67`, `df["open"].iloc[pos]` with `idx[pos]==fs`
  enforced at `test.py:56`); exit uses the CLOSE 4 bars later (`test.py:67`, `exit_pos=pos+hold`).
  No same-bar close on an open entry.
- `first_session` is leak-free: `rd._first_session` (`research_data.py:157-167`) is the first session
  whose 09:30 open is *after* the announcement time; a 00:00 (no-time, old filings) is pushed to the
  next session — conservative. Event dated by `announced`, NOT `filing_date`.
- `announced` is the SEC **acceptance** timestamp of the earliest 8-K / EX-99 within 120d before the
  ex-date that says "stock split" (`edgar.py:168-184`); EX-10/10-Q/proxy boilerplate excluded so the
  date is not pulled too early. Point-in-time correct. The 120d-before-ex-date search anchors on the
  ex-date (a historical fact) only to *find* the filing; the trade is dated by the filing's own
  accepted time, so no leak.
- SPY hedge pulled at the same entry_day open / exit_day close, exact-date matched (`test.py:62-66`).

## 2. Luck — PASS
- `luck_t_best_of_n` = 1.89 (best-of-6). Chosen t 3.08 is far above it. `chosen` is **pre-registered**
  (`h4_r2` hardcoded `test.py:24`, stated in PLAN §Variants, matches the idea card rule sketch
  ≥2:1 / +4d) — committed (76d94a1) *before* the train run (dbc2f6f), so this is a single pre-registered
  hypothesis, not best-of-N. The actual best (h2_r2, t 3.26) was deliberately NOT chosen.
- Neighbourhood is coherent, not a lone spike: the r2 tier (≥2:1) is strong at BOTH holds
  (h2_r2 3.26, h4_r2 3.08); the all-forward r1 tier dilutes (1.55 / 2.38) as expected when tiny
  splits are mixed in. h4_r3 collapses to 0.74 but that tier is n=38 (noise), not a counter-signal.

## 3. Costs & fills — PASS (with margin)
- `cost_bps` 20 round-trip. Net chosen mean ≈ 45 bps. At 1.5× cost (30): ≈ 35 bps net. At 2× (40):
  ≈ 25 bps net. Survives comfortably. Opens/closes and smaller ≥2:1 names cost more than 20, but the
  gross edge (65 bps) leaves room. The holdout is the real cost test.

## 4. Sample — PASS
- 395 trades, 282 week-periods across 2001-2017 — well over the ≥20-week floor. Splits do cluster in
  bull years; distribution across the 17y not individually verified but 282 weeks is broad. → holdout watch.

## 5. Baseline — PASS, flag survivorship
- Metric is SPY-hedged, not long-only beta. BUT the universe is today's S&P 1500 back-applied; splitters
  that later delisted are missing → biases a LONG split signal UP (flagged in PLAN §Known biases).
  Modest for a 4-session hold but real. **If the holdout t lands marginal (just over/under 3.0), read it
  as survivorship, not an edge.** Also: only ~812 of ~3,189 forward splits have a found announcement;
  the dropped NaT rows skew toward better-documented (larger) events.

## 6. Paper match — PASS, flag population gap
- `strategy.py` MIN_RATIO 2.0, HOLD 4, metric `real_hedged_bps` = `spec.json` hold_sessions 4 /
  exit close / r2 → matches `chosen` h4_r2.
- Divergence (documented, not a defect): research enters premarket-announced splits SAME day at open;
  the once-daily after-close paper runner CANNOT, so `strategy.py:68-72` **skips** same-day cases
  rather than entering a day late. Correct choice (mistiming would break the rule), but it means the
  paper population is a *subset* of the backtest — even thinner than the already-rare ~30 forward
  splits/yr, and its mean could differ if premarket-announced splits behave differently. Director note,
  not a kill.

## 7. Graveyard — PASS
- No prior split idea in the graveyard. Distinct from earnings-gap / PEAD-ESUR (earnings surprise),
  gap-fade (price pattern), insider (Form 4). First use of the `corporate_events` family budget
  (6 variants, 0 holdouts spent; bar 3.0).

## Holdout watch (for Holdout Keeper / Director)
1. Survivorship biases LONG up → marginal t = survivorship, not edge.
2. Announcement-coverage bias (only ~26% of forward splits dated) skews to larger events.
3. If promoted: paper excludes premarket-announced splits → very thin, mean may drift from backtest.
