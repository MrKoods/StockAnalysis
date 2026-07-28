# CHANGELOG — AI-Assisted Swing Trading Signal System

Model versioning follows semantic versioning: MAJOR.MINOR.PATCH
- MAJOR: fundamental change to scoring architecture or trade selection logic
- MINOR: new indicator, modifier, or signal category added
- PATCH: threshold adjustment, bug fix, or calibration update

**Rule:** No changes to scoring weights, indicator parameters, or thresholds go live without
a version increment and successful re-backtest logged below. No exceptions.
`model_versioning.py` enforces this — it will reject a version bump without a passing
backtest entry in this file.

---

## [v2.2.20] — 2026-07-28 — Live score-distribution diagnostics; paper-trading go-live gate reporting fix; feedback-loop calibration wired to the system that's actually running

**Status:** Code updated. No scoring, threshold, or weight value changed — `confidence.min_threshold` (90) and every category weight are byte-for-byte unchanged. This is measurement tooling, a reporting fix, and dormant-pipeline wiring, all of which stay inert (`live_weights=None` in practice) until real calibration data exists. See "Backtest result" below.

### What changed

**Diagnostics (new, read-only):**
- New `paper_trading/score_distribution_diagnostic.py`: percentile distribution of real logged composite scores, per-category ceiling utilization (mean/best-ever as % of each category's max points), a joint-peak-rate measure (how often 2+/all 5 categories are simultaneously in their own top 20%), and a live-data threshold-sensitivity table (companion to `backtesting/metrics.py::run_sensitivity_analysis()`, same default threshold candidates). Run via `python -m paper_trading.score_distribution_diagnostic`.
- New `shared/utils/tail_dependence.py::conditional_top_quantile_rate()`: measures whether two score columns tend to hit their own top quantile together more than chance would predict (lift), independent of bulk Pearson/Spearman correlation — wired into both `backtesting/collinearity_diagnostic.py` and `paper_trading/live_collinearity_diagnostic.py`'s `main()` output.
- `shared/utils/macro_overlay.py`: `save_macro_state()`/`load_macro_state()` were dead code — nothing called them, and `data/processed/macro_state.json` had never been updated (`computed_at_utc: null`) despite its own comment claiming otherwise. `run_swing_model.py` and `paper_runner.py` now call `save_macro_state()` right after computing macro state each scan — observability only, doesn't feed back into scoring.

**Paper-trading go-live gate:**
- `paper_trading/paper_trade_metrics.py::evaluate_paper_trading_pass()`: new `data_status` field (`"evaluated"` vs. `"insufficient_trades"`, floor = 15 trades, matching `feedback_loop.run_calibration()`'s own minimum). Below the floor, `overall_pass` still reports `False` (unchanged, safe default) but the failure reason now says `insufficient_trade_data_...` instead of `expectancy_ci_lower_...` — at n=0 the CI lower bound is trivially 0.0, which previously read identically to "the edge genuinely failed."
- New `load_paper_trade_gate_inputs()` reads `paper_trading/paper_trades.csv` (written by `paper_updater.py` — the system that's actually been running) rather than `data/logs/trade_outcomes.csv` (`feedback_loop.py`'s file, fed only by `portfolio_manager.py`'s manual-Discord-confirmation flow, which has stayed empty since no version has gone live). Wired into `monitoring/performance_dashboard.py::generate_weekly_summary()` (new `go_live_gate` field on every return path) and a new `python -m monitoring.performance_dashboard` CLI entry point — `generate_weekly_summary()` had no scheduled caller before this either, confirmed via repo-wide search.

**Feedback-loop calibration, wired to the real data source:**
- `swing_model/feedback_loop.py::run_calibration()` now accepts an explicit `outcomes` list (falls back to reading `_TRADE_OUTCOMES_FILE` if omitted, unchanged default behavior) and actually reads `cfg`'s `feedback_loop` block (`out_of_sample_holdout`, `weight_change_version_threshold`) instead of silently ignoring it in favor of hardcoded defaults that merely happened to match.
- New `load_calibration_outcomes_from_paper_trades()` adapts `paper_trades.csv` rows into `run_calibration()`'s expected shape (`technical_score`→`technical_total` etc.). Known, explicitly scoped-out gap: `signal_key` stays `"unknown"` for every row — `build_signal_key()` needs raw indicator flags (`breakout_confirmed`, `sentiment_direction`) that `paper_trades.csv`'s schema doesn't capture; win-rate-by-signal-combination bucketing needs a separate follow-up to `paper_runner.py`'s row-writer, not done here.
- `_save_live_weights()` now writes `last_calibrated`/`n_trades` metadata alongside the weight fractions; new `load_live_weights_if_calibrated()` returns `None` unless that metadata is present — so `calibrated_weights.json`'s current on-disk placeholder (`{"technical": 0.6, "sentiment": 0.25, "news": 0.15}`, never produced by an actual calibration) can't silently start affecting live scoring. `needs_version_increment`'s >5pp check now calls `swing_model.model_versioning.check_backtest_required()` directly (previously a duplicate inline re-implementation that never actually cross-called it, despite `model_versioning.py`'s own docstring claiming otherwise).
- New `should_recalibrate()` (trade-count-since-last-calibration or monthly cadence, both from `cfg`) called from a new `paper_updater.py::_maybe_run_calibration()`, invoked right after `update_paper_trades()` saves closed trades. A calibration that fails holdout, or passes but needs a version bump, now sends a Discord alert (`shared/utils/discord_alerts.py::send_calibration_alert()`, new) — `feedback_loop.py`'s own module docstring has said "if failing: Discord alert" since Phase 14; nothing actually sent one until now.
- `run_swing_model.py` and `paper_runner.py` now pass `live_weights=load_live_weights_if_calibrated()` into `compute_confidence_score()` (previously always `None`, the implicit default). With zero real calibrations on record, this resolves to `None` today exactly as before — confirmed by the full suite passing unchanged.
- Removed dead `data/processed/live_weights.json` (nested `technical_max`/sub-signal-cap schema) and `config/global_config.yaml`'s `live_weights_file` key — zero readers anywhere in the codebase (confirmed via repo-wide grep), and the file's own header comment ("Read by scoring.py on every scan") was false; `scoring.py`'s `live_weights` parameter has always read the differently-shaped `calibrated_weights.json` instead.

**Evidence produced (not applied):**
- New `paper_trading/reports/threshold_evidence_proposal_DRAFT.md`: collects the diagnostic findings below into a draft, unapplied evidence review for `confidence.min_threshold`. Explicitly stops short of picking a replacement number or running the formal fixed-slice re-backtest — those are the actual tuning decision, which stays a separate, versioned, human-approved step per this file's own rule.

### Why it was changed

A review of the workspace and 9 days of real paper-trading history (215 ticker-scans, 20 scan runs, 11 tickers across two sectors) found the composite score has never once reached 90 — or even 80 — with a max ever observed of 71.72. `evaluate_paper_trading_pass()`'s go-live gate therefore had `n_trades=0` the entire time, which read identically to a genuine expectancy failure without a way to tell the two apart. Digging into why surfaced that the calibration feedback loop everyone assumed would eventually resolve this (`feedback_loop.py`, `live_weights`) was reading from and writing to files nothing in the live/paper pipeline actually used or trusted: `trade_outcomes.csv` (empty, wrong system), `data/processed/live_weights.json` (dead, wrong schema), and `run_calibration()` itself was never invoked outside tests. This entry makes the measurement tooling honest, fixes the reporting gap that was hiding the "no data yet" state, and connects the calibration pipeline to `paper_trades.csv` — the file that's actually been accumulating real data — while keeping every live-scoring effect inert until a real calibration genuinely earns it.

### Backtest result

N/A — no scoring weight, category maximum, modifier bound, or the 90-point `confidence.min_threshold` was touched. `compute_confidence_score()`'s `live_weights` branch was already implemented and already a no-op with the default `None` (see v2.2.x history); this entry only changes what feeds that parameter once real calibration data exists, which it does not yet. 637 tests pass (was 582), 3 skipped (unchanged, stale stress-test skips). `ruff check .` clean.

### Approved by

[pending]

---

## [v2.2.19] — 2026-07-28 — Move earnings surprises to Finnhub; gate Alpha Vantage's remaining call by earnings proximity

**Status:** Code updated. Same not-yet-eligible-to-go-live status as v2.1.0-v2.2.18 — data-source and fetch-cadence change only, no scoring formula impact. `earnings_momentum_score`'s four sub-scores and their point ranges are completely unchanged; only where three of the four get their data, and how often the fourth's data source gets called, changed.

### What changed
- `shared/api_clients/fundamental_client.py`: `get_earnings_history()` split into two methods. `get_earnings_surprises()` now sources `earnings_surprises`/`consecutive_beats` from Finnhub's `/stock/earnings` (free tier, already-configured key, no Alpha Vantage budget cost) — confirmed it returns exactly the `{actual, estimate}` shape needed, 4 quarters deep, same depth AV's EARNINGS response was already limited to for this sub-calculation. `get_eps_growth_trend()` keeps the Alpha Vantage EARNINGS call, now scoped to only the one figure that genuinely needs 8-quarter depth neither Finnhub nor yfinance's free tiers provide (the year-over-year comparison). `get_all_fundamentals()` gained a `fetch_eps_growth_trend: bool = True` parameter — when `False`, `get_earnings_surprises()` (Finnhub) still runs every time, but `get_eps_growth_trend()` (AV) is skipped entirely.
- `swing_model/indicator_pipeline.py`: `fetch_fundamental_data()` now only requests `fetch_eps_growth_trend=True` for cold-start (bootstrap) or earnings-priority tickers — a plain weekly rotation refresh passes `False` and carries the last known `eps_growth_trend` value forward from cache instead of spending an AV call to get back an answer that can't have changed since the last quarterly report.
- `tests/test_fundamental_client.py`: replaced the old `get_earnings_history`-still-uses-AV regression guard with coverage for both new methods and `get_all_fundamentals`'s gating (12 tests, was 6).
- `tests/test_indicator_pipeline_fundamental_refresh.py`: added `TestEpsGrowthTrendGating` (3 tests) covering the bootstrap/earnings-priority-vs-rotation gating and the carry-forward behavior; existing mock signatures updated for the new `fetch_eps_growth_trend` parameter.

### Why it was changed
Alpha Vantage's `EARNINGS` call had failed on every fetch attempt since the staggered refresh (v2.2.12) went live — confirmed via a direct, unmocked call against the real API that it's a genuine 25-requests/day account-level cap (Alpha Vantage's own response: *"our standard API rate limit is 25 requests per day"*), not a bug in the retry/budget logic. Investigating what that EARNINGS call was actually used for found `earnings_momentum_score` is built from four ±2/±3-point sub-scores, and only one of them (`eps_growth_score`, needing the 8-quarter YoY comparison) actually requires AV's depth — `earnings_surprise_score` was being computed from the same AV response but needs only 4 quarters, which Finnhub already provides for free. Moving that sub-score off AV and gating the remaining AV call to only fire near real earnings events (instead of every ticker's weekly rotation slot) cuts routine EARNINGS usage from up to 3 calls/day to roughly 1-2/month across the whole 11-ticker watchlist.

### Backtest result
N/A — doesn't touch the scoring formula, weights, or thresholds; `fundamental_layer.py`'s `earnings_momentum_score` computation is byte-for-byte unchanged, since `get_all_fundamentals()`'s combined `earnings` dict still returns the exact same `{eps_growth_trend, earnings_surprises, consecutive_beats}` shape it always did — only the data source and fetch frequency changed underneath it. Verified end-to-end against real (unmocked) Finnhub and Alpha Vantage APIs: a real `get_all_fundamentals("AVGO", fetch_eps_growth_trend=False)` call returned real `earnings_surprises` data from Finnhub while `data/processed/av_call_count.json`'s count stayed unchanged, confirming zero AV budget spent on the routine path. 582 tests pass (was 573), 3 skipped (unchanged).

### Approved by
[pending]

---

## [v2.2.18] — 2026-07-26 — Healthcare sector pulled as a third, non-rate-sensitive diversification test

**Status:** Code updated. **Research-only, same as regional banks (v2.2.6) — `config/swing_config.yaml`'s live watchlist is unchanged, zero live/paper trading impact.** Not a scoring or threshold change; no re-backtest of the live model required.

### What changed
- New `data/historical_healthcare/` (gitignored, local-only — matches `data/historical_banks/`'s existing pattern): 2013-2026 OHLCV via yfinance for XLV (benchmark) + LLY, PFE, MRK, ABBV, UNH, JNJ.
- `.gitignore`: added `data/historical_healthcare/`.

### Why it was changed
Semis and regional banks are both rate-sensitive procyclicals — chips on growth/rate fears, banks on net-interest-margin and credit fears — so their agreement (v2.2.6/v2.2.7) is weaker evidence of genuine generalization than it looks: both could simply be responding to the same underlying rate-regime factor already shown (v2.2.7) to explain most of the pass/fail pattern. Healthcare/pharma was picked specifically because its momentum breakouts are driven by different catalysts (drug approvals, trial readouts, FDA decisions) largely independent of the macro rate cycle — a real test of whether the entry-filter edge is generic or sector-specific, not a third rate-sensitive data point dressed up as a third opinion.

### Result
Re-ran the identical pooled walk-forward methodology (current default filter: RSI 45-70 + confirmation bar, all windows, KRE/SMH/XLV relabeled as the generic backtest benchmark key per sector) fresh across all three sectors for a clean comparison:

| Sector | Benchmark | Pooled trades | Win rate | Avg R:R | Max consec. losses |
|---|---|---|---|---|---|
| Semiconductors | SMH | 54 | 61.1% | 1.89 | 3 |
| Regional banks | KRE | 46 | 54.4% | 1.63 | 8 |
| Healthcare | XLV | 41 | 63.4% | 1.31 | 3 |
| **All three pooled** | — | **141** | **59.6%** | **1.63** | — |

(Small variance from the semis/banks figures previously logged in v2.2.6/v2.2.7 is expected re-run noise from walk-forward window boundaries on slightly more recent data, not a regression.)

**Healthcare's win rate (63.4%) holds up as well as or better than semis and banks — genuinely reassuring for the "is this a real, generalizable edge" question.** Its average R:R (1.31) is meaningfully lower than either procyclical sector, though — healthcare breakouts win about as often but capture noticeably less reward per winner. Read together: the *direction-calling* part of the entry filter (breakout + trend + RS + RSI band) looks like it generalizes past rate-sensitive names; the *reward-magnitude* part may be more sector-dependent (healthcare's smaller/faster momentum moves vs. semis' larger, more explosive rallies) than previously evidenced with only two, similarly-behaved sectors. Three-sector pooled expectancy (0.596×1.63 − 0.404×1.0 ≈ 0.57R/trade) stays clearly positive.

Per the v2.2.16 lockbox rule, this is reported as new evidence, not a trigger to retune entry-filter parameters against it.

### Approved by
MrKoods — 2026-07-26

---

## [v2.2.17] — 2026-07-26 — Replace the flat 80% WR / 1.8 R:R go-live gate with a bootstrapped expectancy CI

**Status:** Code updated. Still not eligible to go live — this changes how "passed" is determined, it does not make anything pass. This IS a threshold change (the pass/fail criterion itself), so it gets the full re-backtest this file's own rule requires, even though it never touches live scoring weights, indicator parameters, or the 90-point confidence threshold that decides which trades surface.

### What changed
- `backtesting/metrics.py`: new `compute_r_multiples()` (per-trade achieved R, wins and losses — unlike `compute_avg_rr()`, which only ever averaged winners) and `bootstrap_expectancy_ci()` (bootstrapped confidence interval on mean per-trade R-expectancy, 10,000 resamples, fixed seed=42 by default for determinism — a go-live gate that flips pass/fail between identical re-runs from resampling noise alone would undermine trust in the gate itself).
- `backtesting/backtest_engine.py::run_backtest()`: `passed` now requires the bootstrapped 95% CI lower bound on expectancy to clear a new `min_expectancy_r` parameter (default 0.3R), instead of `win_rate >= 0.80 and avg_rr >= 1.8`. Trade-count (≥100), Sharpe (≥1.0), and max-drawdown (≤15%) floors are unchanged. `win_rate`/`avg_rr` are still computed and included in the result dict for continuity with existing reports/dashboards — they just no longer gate `passed` directly. New result fields: `expectancy_r_mean`, `expectancy_r_ci_lower`, `expectancy_r_ci_upper`.
- `Project_Scope.md` (Performance Thresholds section) and `PROJECT_OVERVIEW.md` (§1 non-negotiable gate) updated with a callout explaining the change — the original 80%/1:3 table, Kelly Criterion note, and streak-probability table are left as-is for historical/illustrative context (they were never recomputed under the new criterion; there's no single win-rate scalar to plug into that math the same way), not silently rewritten.
- New tests in `tests/test_phase12_backtest.py`: `compute_r_multiples`/`bootstrap_expectancy_ci` unit tests (empty input, determinism under a fixed seed, CI narrowing with more trades) and `test_passed_requires_expectancy_ci_lower_above_threshold` confirming `passed` actually responds to `min_expectancy_r` rather than the old win_rate/avg_rr pair.

### Why it was changed
The flat 80% win rate / 1.8 avg R:R pair implied ~1.24R expectancy per trade sustained indefinitely — far above anything this design (or most systematic equity strategies) has ever demonstrated, even in its best historical windows (see PROJECT_OVERVIEW.md §11's walk-forward findings) — and a bare percentage pair can't distinguish a real edge from a small sample that got lucky. An expectancy confidence interval answers the question the gate actually needs answered: not just "is the observed number above X" but "how confident can we be the true edge is above X, given how much data we have."

### Backtest result
Re-ran the full 13.5-year fixed-slice backtest under the new gate: **win_rate=66.67%, avg_rr=2.35, expectancy_r_mean=1.236, expectancy_r_ci_lower=0.422, expectancy_r_ci_upper=2.03, sharpe=0.34, max_drawdown=2.97%, qualifying_trades=18 (of 100 required), total_signals=50.** `passed=False` — same as every prior version — but for a more informative reason than before: **the expectancy CI lower bound (0.422R) already clears the new 0.3R bar.** What's actually blocking go-live on this slice is trade count (18 vs. 100 required) and Sharpe (0.34 vs. 1.0 required), not a lack of edge. This is a more useful diagnosis than "66.7% vs. 80%, fail" — it says the signal looks statistically real when it fires, there just isn't enough of it yet (consistent with the "let paper trading accumulate more history" direction already in progress, not a reason to resume backtest-filter tuning — see the v2.2.16 lockbox rule). 566 tests pass (was 559), 3 skipped (unchanged, stale stress-test skips).

### Approved by
MrKoods — 2026-07-26

### Extended to paper trading — 2026-07-27
The same bootstrapped expectancy CI gate now also governs paper trading's own go-live check, not just the backtest's. `paper_trading/paper_trade_metrics.py::evaluate_paper_trading_pass()` previously gated on a separate flat `win_rate >= 0.80 and avg_rr >= 3.0` pair; it now requires the same CI-lower-bound-clears-`min_expectancy_r` (default 0.3R) criterion, reusing `backtesting/metrics.py`'s `compute_r_multiples()`/`bootstrap_expectancy_ci()` directly rather than duplicating the logic. `win_rate`/`avg_rr` are still computed and returned for continuity, no longer gate `overall_pass` directly (mirrors the backtest side exactly). New result fields: `expectancy_r_mean`, `expectancy_r_ci_lower`, `expectancy_r_ci_upper`, `expectancy_pass` (replaces `win_rate_pass`/`rr_pass`). Sanity-checked against paper trading's actual current state (zero logged qualifying trades): correctly reports `expectancy_ci_lower=0.0R, n_trades=0` rather than a misleading pass/fail. Holding both go-live gates to inconsistent statistical standards would undermine trust in whichever one ends up making the real call. `tests/test_phase13_paper_trading.py::TestEvaluatePaperTradingPass` rewritten to match (7 tests, same count as before — old win-rate/rr-based tests replaced 1:1 with expectancy-CI-based ones). 566 tests pass (unchanged by this change specifically — net-neutral swap), 3 skipped (unchanged). See v2.2.16's extension below, made in the same session, for the 566→573 jump.

Approved by: [pending]

---

## [v2.2.16] — 2026-07-26 — Technical/Sentiment collinearity diagnostic; formal backtest-tuning lockbox rule

**Status:** Code updated. No scoring, threshold, or trade-selection change of any kind — this entry is a measurement tool and a documented process rule, not a model change. No backtest re-run required.

### What changed
- New `backtesting/collinearity_diagnostic.py`: measures how independent the Technical and Sentiment categories actually are in backtest replay, where Sentiment is a price-momentum proxy (`_sentiment_from_price_momentum`) rather than real StockTwits data — since Technical already scores momentum/breakout/RSI directly, a proxy built from the same price series risked being the same signal wearing two labels, inflating the backtest's apparent win rate versus what independent live sentiment data will actually contribute. Reuses the identical candidate-detection filters as `_simulate_test_signals` so the sampled population matches what the real backtest scores. Run via `python -m backtesting.collinearity_diagnostic`.
- `Project_Scope.md` (Clarification 6, residual model risks): formalized the "stop iterating" decision already made in v2.2.6 into an explicit rule — no historical or paper-trading data timestamped before 2026-07-26 may be used to tune backtest entry-filter parameters (RSI band, confirmation bar, volume gate, stop/target multipliers) again. Re-running the existing backtest for reporting/regression-checking is unaffected; only re-*tuning* against already-reused data is blocked. The next legitimate tuning pass is against paper-trading data accumulated after this date.

### Why it was changed
Part of a broader review of the project's statistical methodology (go-live gate calibration, cross-sector diversification test, this collinearity question, and the lockbox rule — see accompanying discussion). The collinearity question specifically was raised as a hypothesis ("is the backtest's apparent 5-category diversification partly illusory because two categories share the same underlying data in replay?") and needed an actual measurement rather than an argument from principle.

### Result
**The hypothesis did not hold up.** Measured across 201 candidate bars (6 tickers, same filters as the real backtest): Pearson r(technical_total, sentiment_total) = 0.115, Spearman ρ = 0.113 — both well below the 0.5 threshold that would indicate substantial collinearity, and closer to the "meaningfully separate information" end even under the proxy. The raw inputs each score is built from (rs_zscore vs. mom_5d) correlate similarly weakly (r=0.141, ρ=0.090). Read with two caveats: (1) the sample is pre-filtered to already-qualifying breakout candidates (trend_intact, RS>0, RSI 45-70), which compresses the variance of both variables and could understate the true unconditional correlation — a restriction-of-range effect, not a flaw in the measurement itself; (2) `sentiment_total` is a bucketed step function of `mom_5d`, which Pearson r can under-capture even for a real monotonic relationship — Spearman ρ was computed alongside for this reason and landed in the same range, so this isn't the explanation for the low reading. Net: the proxy-sentiment concern raised earlier this session is not corroborated by this data; the 63-67% backtest win rates aren't being meaningfully inflated by Technical/Sentiment double-counting.

### Approved by
MrKoods — 2026-07-26

### Extended to live paper trading — 2026-07-27
New `paper_trading/live_collinearity_diagnostic.py` runs the same Technical/Sentiment correlation measurement against real accumulated paper-trading scan history (`stockanalysis_history.db`'s `ticker_results`/`layer_scores` tables, via a `collect_score_pairs()` join) instead of backtest replay. This isn't re-testing the original proxy concern — paper trading already uses real StockTwits/Seeking Alpha sentiment data, no proxy involved — it's the complementary question of whether independence actually holds now that real data has accumulated. Uses every logged scan result (215 rows across 20 scan runs as of 2026-07-27), not just breakout candidates, since v2.1.2 already logs every ticker regardless of qualification — no equivalent restriction-of-range caveat as the backtest version. **Result: Pearson r = -0.108, Spearman ρ = -0.105** — comparable to, slightly better than, the backtest's proxy-based r=0.115, both well under the 0.3 "meaningfully separate information" threshold. The collinearity concern does not hold up with real data either. `tests/test_live_collinearity_diagnostic.py` (7 new tests, isolated per-test SQLite DB via existing `db_path` parameters on `app_ui/db.py`'s insert functions). 573 tests pass total, up from 566 — this addition's own +7 (the v2.2.17 extension above, made in the same session, was a net-neutral test swap and didn't itself move the count). 3 skipped (unchanged).

Approved by: [pending]

---

## [v2.2.15] — 2026-07-26 — Seeking Alpha triggers same-scan AV cross-reference on a critical event

**Status:** Code updated. Same not-yet-eligible-to-go-live status as v2.1.0-v2.2.14 — this only changes when a pre-market/mid-session scan spends an Alpha Vantage call, not the scoring formula. See "Backtest result" below.

### What changed
- `swing_model/news_layer.py`: new `seeking_alpha_flags_critical_event()` — runs the existing `classify_severity()` logic standalone (cheap, local, no API cost) against Seeking Alpha's headlines for a ticker, before deciding whether to fetch Alpha Vantage news that scan.
- `swing_model/run_swing_model.py`, `paper_trading/paper_runner.py`: pre-market/mid-session scans (which skip AV news entirely by default, post-close-only, for budget reasons — v2.2.x) now make one exception: if Seeking Alpha (already fetched every scan for Sentiment, at no extra cost) flags a critical ticker- or sector-scope event for that ticker, the AV call fires immediately instead of waiting for the post-close scan. Cross-references the event against an independent, pre-scored source the same scan it's detected, rather than up to ~13 hours later.
- New `tests/test_event_gate.py::TestSeekingAlphaFlagsCriticalEvent` (6 tests) covering ticker-scope, sector-scope, wrong-ticker, non-critical, empty-input, and gate-disabled cases.

### Why it was changed
User asked, in the context of the v2.2.14 AV-budget-relief work, whether Seeking Alpha could also be used to trigger an Alpha Vantage cross-reference check rather than only feed the scored News total. This is deliberately scoped to the trigger alone (not a routine-call rotation or an AV-vs-SA sentiment-agreement flag, both discussed and deferred) — it *adds* an AV call in the rare case something's actually flagged, on scans that currently spend zero, rather than reducing total AV usage; that trade is worth it since confirming a real event is cheap next to missing one for ~13 hours.

### Backtest result
N/A — live/paper fetch-cadence change only, not modeled in `backtesting/simulation.py` (which never calls Alpha Vantage live and has no `seeking_alpha_articles` archive at all, per v2.2.14). Doesn't touch the scoring formula. 559 tests pass (was 553 before this entry), 3 skipped (same stale stress-test skips, unrelated).

### Approved by
MrKoods — 2026-07-26

---

## [v2.2.14] — 2026-07-26 — Fold Seeking Alpha into the scored News total; split backtest_engine.py; add CI/lockfile

**Status:** Code updated. Same not-yet-eligible-to-go-live status as v2.1.0-v2.2.13 — the News-scoring change adds a live-only fourth source to an existing category rather than altering the scoring formula's weights or thresholds; the rest of this entry is engineering infrastructure with no scoring effect at all. See "Backtest result" below.

### What changed
- `swing_model/news_layer.py`: `compute_news_score()` now folds `seeking_alpha_articles` directly into `all_articles` — Seeking Alpha headlines (already fetched every scan for the Sentiment layer's engagement-velocity proxy, at no extra API cost) now contribute to the scored 0-15 News total (credibility/theme/clustering/decay) exactly like AV/Yahoo/Finnhub articles, not just Event Severity Gate detection as of v2.2.13. `shared/utils/source_credibility.py` already had a `seekingalpha.com` → 0.55 credibility score defined before this change ever wired it into scoring. `run_swing_model.py`/`paper_trading/paper_runner.py` updated to match (`sa_severity_articles` renamed `sa_news_articles`); `tests/test_event_gate.py` updated to assert the new fold-in behavior instead of the old severity-only isolation.
- **Why this addresses the AV budget constraint**: Alpha Vantage's `NEWS_SENTIMENT` call is already restricted to the post-close scan (1/ticker/day) and shares a 20-call/day free-tier budget with weekly `EARNINGS` calls — a real constraint on watchlist growth (see PROJECT_OVERVIEW.md §13). Seeking Alpha runs on every scan via the existing paid RapidAPI subscription at zero AV cost. Giving News a genuine second live source (rather than AV alone) means the category is less exposed on scans/days where AV data is thin, without spending any additional AV budget — the natural next step this unlocks (not done here, flagged as a follow-up) is staggering the AV news call itself per-ticker the same way `fetch_fundamental_data()` already staggers `EARNINGS` (v2.2.12), now that News doesn't depend on AV alone.
- `backtesting/backtest_engine.py` (951 → 193 lines) split into three files, mechanical refactor only, no behavior change: `backtesting/simulation.py` (the historical-replay engine — `_simulate_test_signals`, `simulate_trade_outcome`, and their direct helpers), `backtesting/walk_forward.py` (`run_walk_forward`), and `backtesting/metrics.py` gains `_trades_per_year`/`_build_equity_curve`. `backtest_engine.py` now only holds `run_backtest`/`_get_test_outcomes`/`_save_report` and re-exports `run_walk_forward`/`simulate_trade_outcome` for existing callers (`entry_filter_variants.py`, `tests/test_phase12_backtest.py`) — verified no import broke.
- New `.github/workflows/ci.yml`: runs `pytest --cov` + `ruff check .` on every push/PR to `main`/`Version-1`.
- New `pyproject.toml`: `[tool.ruff]` config, scoped to `select = ["E", "F"]` (correctness) since the codebase is clean against that today — `I`/`UP`/`B` (import sort, pyupgrade, bugbear) surface ~400 pre-existing stylistic findings, deliberately left for their own separate adoption commit rather than silently bundled in here. Fixed the one real finding (`F401` unused import in `tests/test_multi_sector_pipeline.py`).
- New `requirements.lock.txt`: fully resolved via `pip-compile` (pip-tools), for reproducible CI installs. `requirements.txt` stays the human-edited floor-version list; regenerate the lock after editing it (`pip-compile requirements.txt --output-file=requirements.lock.txt --resolver=backtracking`). One transitive dependency (`cody-special`, pulled in via `py_vollib`'s `lets-be-rational` backend) was manually verified before trusting it — an unfamiliar single-release package name is worth checking, this one turned out to be a legitimate W.J. Cody erf/normal-CDF approximation from the same `vollib` GitHub org, not a supply-chain risk.

### Why it was changed
User-requested engineering hardening pass: no CI meant a bad commit only got caught if someone remembered to run `pytest` locally; no lockfile meant an unpinned `yfinance`/`spacy` upgrade could silently change behavior with no test catching it; `backtest_engine.py` at 951 lines was the file with the highest concentration of self-caught bugs (Sharpe periodicity, equity-curve ordering) in this project's history, consistent with one file doing too much. The Seeking Alpha change was the user's own suggestion for relieving the Alpha Vantage budget constraint flagged in the same review.

### Backtest result
**No observable effect — confirmed, not just argued.** `backtesting/simulation.py` has no historical Seeking Alpha article archive (unlike AV, cached from Q4 2025 onward) and always calls `compute_news_score(..., seeking_alpha_articles=None)`; `list(None or [])` contributes nothing to `all_articles` whether or not this change exists, so the backtest path is mathematically unchanged. Re-ran the full 13.5-year backtest after this change: 66.7% WR, 18 qualifying trades, 2.35 avg R:R, 0.34 Sharpe — consistent with the existing v2.2.6-documented baseline (64.7% WR / 17 trades on the same fixed slice; small variance is expected re-run noise, not a regression). This is the same "accumulates going forward, not backtestable yet" caveat already accepted for Positioning and live StockTwits sentiment (see PROJECT_OVERVIEW.md §13) — tracked the same way. The `backtest_engine.py` split and CI/lockfile additions have no backtest-relevant code path at all. 553 tests pass (was 552 before this entry), 3 skipped (same stale stress-test skips, unrelated — see PROJECT_OVERVIEW.md §10).

### Approved by
MrKoods — 2026-07-26

---

## [v2.2.13] — 2026-07-24 — Feed Seeking Alpha into event-gate detection; cut a redundant AV call; isolate test logging

**Status:** Code updated. Same not-yet-eligible-to-go-live status as v2.1.0-v2.2.12 — the event-gate/AV-source changes affect signal detection speed and one Fundamental sub-score's data source, not the scoring formula itself; the test-isolation fix is reliability-only. See "Backtest result" below.

### What changed
- `swing_model/news_layer.py`, `run_swing_model.py`, `paper_trading/paper_runner.py`: Seeking Alpha's editorial headlines (already fetched every scan for the Sentiment layer's engagement-velocity proxy, at no extra API cost) now also feed Event Severity Gate detection — severity classification only, never the scored News total, which stays computed from exactly the same 3 sources (Alpha Vantage/Yahoo/Finnhub) it was backtested against. Alpha Vantage news is restricted to the post-close scan for budget reasons, which left pre-market/mid-session unable to detect a critical event until hours after it broke — one real headline sat undetected roughly 13 hours before the post-close scan finally caught it. `shared/utils/discord_alerts.py`'s event-gate-triggered embed now shows the actual article timestamp and the resulting detection lag explicitly, instead of only when the alert itself posted.
- `shared/api_clients/fundamental_client.py`: `get_estimate_revisions()` now sources analyst target price from yfinance and rating breakdown from Finnhub, dropping the Alpha Vantage OVERVIEW call entirely. That call's own prior docstring already noted it was low-value on the free tier (current target price only, no real revision history), so this is one fewer AV call/ticker for the same practical depth — freeing budget as the watchlist grows across sectors. `implied_upside_pct` (feeds `estimate_revisions_score` in `fundamental_layer.py`) is computed the same way as before; only its target-price source changed.
- New `tests/conftest.py`: autouse fixtures redirect `write_audit_entry`/`write_validation_entry`/`write_override_entry` (`shared/utils/logger.py`) and `backtest_engine._save_report()` into `tmp_path` for every test. Without this, any test exercising a real error path wrote synthetic entries straight into the production `data/logs/*.csv` files and `backtesting/reports/` — audited and found `validation_log.csv` was 99.7% test pollution going back to its very first entry. `logger.py`/`backtest_engine.py`'s path defaults are now module-level constants referenced by name (not baked into function default-argument values, which Python evaluates once at import time) specifically so they're monkeypatchable.
- New `tests/test_fundamental_client.py` covering the Finnhub/yfinance `get_estimate_revisions()` rework.

### Why it was changed
Investigating why paper trading kept missing news that later showed up as a post-close event-gate trigger led to the Seeking Alpha wiring — the detection lag was real and measured, not hypothetical. The AV OVERVIEW removal was opportunistic budget cleanup found in the same pass. The test-log-pollution fixture came from directly auditing `validation_log.csv` and finding the overwhelming majority of entries were test artifacts, not real production data-quality issues — a real risk for anyone trying to read that file as a signal.

### Backtest result
**N/A / not independently re-tested.** The event-gate detection-lag fix and AV→yfinance/Finnhub data-source swap don't change the News category's scored total or the `estimate_revisions_score` formula itself — only detection speed and one sub-score's underlying data source — so the existing backtest result isn't invalidated by this entry, but it also wasn't specifically re-verified against these paths. The test-isolation fix has no effect on scoring, thresholds, or trade selection.

### Approved by
MrKoods — 2026-07-24

---

## [v2.2.12] — 2026-07-23 — Stagger fundamental refresh per ticker; prioritize by earnings proximity

**Status:** Code updated. Same not-yet-eligible-to-go-live status as v2.1.0-v2.2.11 — scheduling/reliability change, no scoring formula impact.

### What changed
- `swing_model/indicator_pipeline.py`: `fetch_fundamental_data()` no longer refreshes the whole watchlist in one Monday-evening burst. Each ticker gets a stable weekly rotation slot (`_rotation_weekday()`, hashed so it's consistent across runs, not Python's randomized built-in `hash()`), capped at `_FUNDAMENTAL_MAX_TICKERS_PER_DAY` (3) refreshes per day, prioritized as: cold-start (never fetched) > within `_FUNDAMENTAL_EARNINGS_LOOKAHEAD_DAYS` (3) of a known earnings date (free yfinance calendar lookup — the one event that actually invalidates cached fundamentals) > due on its rotation day.
- `swing_model/scoring.py`, `fundamental_layer.py`, `paper_trading/paper_runner.py`: now surface `fundamental_data_as_of` per ticker in the score breakdown and score-log line, since staggered refreshing means two tickers scored the same day can have fundamentals from different dates.

### Why it was changed
With multi-sector infrastructure (v2.2.8+) expanding the watchlist, a single Monday-evening burst refresh costs 2 Alpha Vantage calls per ticker on top of that day's post-close news calls — as the watchlist grows across sectors, that risks exceeding the 25-call/day free-tier budget in one burst. Staggering spreads the same total cost across the week instead.

### Backtest result
N/A — scheduling/cadence change only. Doesn't affect the fundamental scoring formula, only how frequently and on what day each ticker's underlying data is refreshed; the backtest's point-in-time fundamental lookup (added v2.2.2) already tolerates data of varying recency.

### Approved by
MrKoods — 2026-07-23

---

## [v2.2.11] — 2026-07-20 — Track fundamental/positioning fetch cadence per ticker, not file-wide

**Status:** Code updated. Same not-yet-eligible-to-go-live status as v2.1.0-v2.2.10 — bug fix, no scoring formula impact.

### What changed
- `swing_model/indicator_pipeline.py`: `fetch_fundamental_data()` and `fetch_positioning_data()` now track refresh cadence per ticker via `state["fetched_dates"]`, instead of a single file-wide `last_updated` timestamp. `_load_fundamental_state()`/`_load_positioning_state()` gained a migration path so existing state files don't trigger a spurious same-day re-fetch of tickers whose data was already fresh under the old scheme.

### Why it was changed
With multiple sectors active (v2.2.8+), a sector processed later in the same scan run would see an earlier sector's fetch timestamp on the shared file-wide `last_updated` field and conclude its own tickers were "already refreshed today" — even though they had never been fetched at all. That silently pinned newly-added sector tickers to null fundamental/positioning data indefinitely, with no error anywhere to surface it.

### Backtest result
N/A — bug fix to live/paper fetch-cadence tracking only; the backtest replay doesn't go through this code path.

### Approved by
MrKoods — 2026-07-20

---

## [v2.2.10] — 2026-07-19 — Activate regional_banks for paper trading; app UI groups results by sector

**Status:** Code updated. **`regional_banks.active` is now `true` — paper trading will scan both sectors starting with the next scheduled run.** This is a paper-trading activation only, not a live-capital decision: per this file's own Performance Thresholds, no version has ever passed the backtest, so real money stays at zero risk regardless of this flag, same as every version since v2.0.0. This is a MINOR bump (new capability, tradeable universe expands from 6 to 11 tickers) rather than MAJOR — no scoring architecture or trade-selection logic changed, only which tickers get scanned.

### What changed

**App UI now shows results grouped by sector, then category within each sector** (the actual trigger for this entry — user asked for this ahead of tomorrow's paper test and it didn't exist yet):
- `app_ui/db.py`: `ticker_results` gains a `sector TEXT` column. New `_migrate()` runs on every `get_connection()` call, adding the column to pre-existing DB files via `ALTER TABLE` (checked against `PRAGMA table_info` first, since sqlite3 has no `ADD COLUMN IF NOT EXISTS`) — verified directly against a copy of the real, already-in-use `stockanalysis_history.db`, not just a synthetic test fixture. `insert_ticker_result()` gains an optional `sector` parameter.
- `paper_trading/paper_runner.py`: both `_db_insert_ticker_result_safe()` call sites now pass `sector=sector` — the `ticker_sector_map` lookup already existed in scope from v2.2.8's per-sector loop, this just threads it into the DB write.
- `app_ui/results_tab.py`: `_render_run()` restructured to group top-level by sector (label derived generically from the config key, e.g. `regional_banks` → "Regional Banks", so a future sector needs no UI code change), category nested within each sector, exactly as before otherwise. Rows with no sector recorded (pre-migration history) group under "Unknown Sector" rather than being dropped.

**Verification, in order of rigor:**
1. Re-ran the cross-sector backtest (same tooling as v2.2.6/v2.2.7, nothing about the strategy logic changed since then) — confirmed unchanged: semis 54 trades/61.1% WR, banks 46 trades/54.3% WR, pooled 100 trades/58.0% WR/1.78 avg R:R.
2. **New `tests/test_multi_sector_live_pipeline.py`** — the first test in this whole multi-sector effort to actually run `paper_runner.run_paper_scan()` itself end to end with two active sectors (everything external mocked: no real API calls, no real Discord sends). This is the thing backtesting structurally cannot verify — `backtest_engine.py`'s simulation never calls `run_pipeline()`/`_fetch_market_context()` at all, so unit tests of individual pieces are the only prior evidence this actually worked together. Confirms: `run_pipeline()` is called exactly once per sector with that sector's own tickers and benchmark (`SMH`→semis tickers, `KRE`→bank tickers, not mixed); a semis trade and a bank trade can be recommended in the same scan simultaneously (proves per-sector portfolio caps, not a shared pool); every `ticker_results` row lands with the correct sector tag.
3. **Checked `fundamental_layer.py`'s `self._watchlist` (still reads the legacy flat `watchlist.tickers` key directly)** — confirmed via grep it's assigned once and never read anywhere else in the class; dead code, not a correctness risk.
4. **Found, but did not fix: `shared/utils/black_swan_detector.py::check_black_swan()` still checks a single SMH-only drop threshold**, not per-sector as this file's own v2.2.8 entry said it would eventually need. Checked its call sites directly: **zero** — it's not wired into `run_swing_model.py` or `paper_runner.py` at all, a pre-existing gap unrelated to and unaffected by any multi-sector work this session. Not a blocker for tomorrow since it has no effect on live/paper behavior either way; noted here rather than silently left out, and worth wiring up (single- or multi-sector) as its own future entry.

### Why it was changed
User: "tomorrow we paper test... the app ui should show both sectors and results of each in a categorized fashion... check to make sure this is the case." Direct verification (not assumption) found two real gaps: `regional_banks` was still `active: false`, and the app UI had no sector dimension anywhere — `ticker_results` had no `sector` column and `results_tab.py` grouped only by category. Both fixed and verified before activating, given the immediately preceding entry (v2.2.9) was itself a lesson in not trusting a prior "this is fixed" claim without re-checking.

### Backtest result
Unchanged from v2.2.6/v2.2.7 (confirmed by re-run, see above) — pooled cross-sector: 100 trades, 58.0% win rate, 1.78 avg R:R, ≈+0.63R expected value per trade. Still well short of the 80%/1:3 go-live bar; this entry only expands what paper trading observes, it does not change eligibility for real capital. 536 tests pass (was 532), including the new end-to-end multi-sector pipeline test.

### Approved by
MrKoods — 2026-07-19

---

## [v2.2.9] — 2026-07-19 — Fix a real gap in v2.2.8: fundamental "sector average" wasn't actually sector-scoped

**Status:** Code updated. Same not-yet-eligible-to-go-live status as v2.0.0–v2.2.8. Same scope as v2.2.8 — `regional_banks` stays `active: false`, this only matters once it's turned on.

### What changed
- `swing_model/fundamental_layer.py::score_all_tickers()`: the peer pool handed to `compute_fundamental_score()`/`score_valuation_vs_peers()` is now filtered to the tickers in `watchlist` (`{t: v for t, v in all_fundamentals_cached.items() if t in watchlist}`) instead of the full, unfiltered `fundamental_state.get("tickers", {})`.

### Why it was changed
- User asked directly whether the second sector gets the full 5-layer scoring system. Re-verifying the answer surfaced that v2.2.8's fix for this exact issue (item #1 in that entry's list of 7 things that would silently break) was **claimed but never actually implemented** — v2.2.8 only touched `run_swing_model.py`, `paper_runner.py`, `event_gate.py`, `news_layer.py`, `portfolio_manager.py`, and config; `fundamental_layer.py`/`indicator_pipeline.py` were never edited.
- The bug: `fundamental_state.json` accumulates every ticker ever fetched across every call (the same forward-building-history pattern already used for Positioning) — it is not scoped by the `tickers` argument passed into `fetch_fundamental_data()`/`run_pipeline()`. `score_all_tickers(watchlist, fundamental_state)` correctly iterated only `watchlist` to decide *which* tickers to score, but passed the *entire* accumulated `fundamental_state["tickers"]` dict — both sectors' entries, once both existed in the cache — into `score_valuation_vs_peers()` as the peer pool for every one of them. Calling `run_pipeline()` once per active sector (v2.2.8's Phase 1 fix) scoped *which tickers get scored* but never scoped *which tickers' data get averaged together* — those are two different things, and only the first one was actually fixed.
- Concretely, this would have blended semiconductor P/E multiples (~30-40x) with regional bank P/E multiples (~8-12x) into one meaningless "sector average" the first time both sectors' fundamental data existed in the same cache file — exactly the failure mode v2.2.8 set out to prevent, just missed in implementation despite being correctly described in that entry's own text.
- Positioning, Sentiment, News, and Technical were checked directly (not assumed) and confirmed not to have the same class of bug: Positioning scores each ticker purely against its own prior snapshot (no cross-ticker pooling at all, no `score_all_tickers`-style function exists in `positioning_layer.py`); Sentiment and News are computed per-ticker with no peer-averaging; Technical's relative-strength/regime/rotation modifiers were the ones v2.2.8 did correctly fix.

### Backtest result
N/A — the backtest doesn't model this bug at all (`backtest_engine.py`'s fundamental history archive lookup is single-sector to date; the fix is verified directly by new unit tests instead). Not modeled in live/paper scoring either while `regional_banks.active: false` — no behavior change for the currently-running single-sector config. New tests: `tests/test_fundamental_layer.py::TestScoreAllTickersMultiSectorScoping` (3 tests) — constructs a mixed-sector cache and confirms a bank-scoped call's peer average excludes semiconductor tickers and vice versa. 532 tests pass total (was 529).

### Approved by
MrKoods — 2026-07-19

---

## [v2.2.8] — 2026-07-19 — Multi-sector infrastructure (Phases 0-3); AV news restricted to post-close

**Status:** Code updated. Same not-yet-eligible-to-go-live status as v2.0.0–v2.2.7. **The live tradeable universe is unchanged** — `regional_banks` is present in config but `active: false`; every real scan today still runs exactly the original 6 semiconductor tickers against SMH. Phases 0-2 below are additive/behavior-preserving refactors (no scoring/threshold change, verified via regression tests, no backtest required per this file's own rule). Phase 3 (Alpha Vantage cadence) does change News-category data availability at pre-market/mid-session and is flagged separately below.

### What changed

**Phase 0 — Sector-aware config schema.** `config/swing_config.yaml` gains `watchlist.sectors` (semiconductors: active, benchmark SMH; regional_banks: inactive, benchmark KRE — the sector backtest-validated in v2.2.6/v2.2.7's research-only relabel test). Legacy flat `watchlist.tickers`/`watchlist.benchmark` keys are kept, unchanged, for call sites not yet migrated. New `shared/utils/sector_config.py` centralizes every sector-aware config read (`get_active_sectors`, `get_all_tickers`, `get_ticker_sector_map`, `get_sector_tickers`, `get_sector_benchmark`), falling back to the legacy flat keys when `watchlist.sectors` is absent.

**Phase 1 — Fixed the specific places that would have silently produced wrong results if a second sector's tickers were simply appended to the old flat list:**
- `swing_model/run_swing_model.py` and `paper_trading/paper_runner.py`: `run_pipeline()`, `_fetch_market_context()`, regime classification, sector rotation, and cross-ticker analysis all now run **once per active sector** instead of once for the whole watchlist against a single hardcoded `"SMH"`. Each sector's relative-strength, regime, and rotation modifier are computed against that sector's own benchmark. `_fetch_market_context()`'s signature changed from `(watchlist)` to `(cfg)` to fetch every active sector's benchmark in one batch call.
- `shared/utils/event_gate.py`: **found and fixed a real latent bug** — `is_ticker_blocked()` treated *any* sector-scope block as covering every ticker unconditionally (`if block.get("scope") == SCOPE_SECTOR: return block`), never actually checking the block's `tickers` list for sector-scoped blocks. Harmless with one sector (a sector-wide block always covered the whole, single-sector watchlist anyway) but would have blocked every ticker in every sector the moment a second sector existed. Now checks `ticker in block.get("tickers", [])` uniformly for both scope types.
- `config/swing_config.yaml`'s `event_severity_gate.sector_wide_triggers` (flat list) → `sector_triggers` (dict keyed by sector name, semiconductors keeps its existing list, regional_banks gets its own: "bank failure", "FDIC receivership", "deposit run", "banking crisis", "SIFI designation", "regional bank contagion"). `event_gate.classify_severity()`/`_find_trigger_match()` and `news_layer.classify_severity()`/`compute_news_score()` all gained a `sector` parameter so a chip-ban headline can't flag a critical event while scoring a bank ticker, and vice versa. `run_swing_model.py`/`paper_runner.py` now scope sector-wide block creation to `get_sector_tickers(cfg, sector)` instead of the entire multi-sector watchlist.
- `swing_model/news_layer.py`: NER ticker-mention matching (which tickers a headline could be about) now reads `get_all_tickers(cfg)` instead of the legacy flat key directly — intentionally NOT sector-scoped, since a headline can legitimately mention any active ticker in any sector.
- New `tests/test_sector_config.py` (15 tests) and `tests/test_multi_sector_pipeline.py` (10 tests) — the latter proves both the real config still resolves to one active sector today, and that sector isolation (benchmarks, event-gate blocks, trigger classification) is actually correct once two sectors are active.

**Phase 2 — Portfolio caps and correlated-position protection are now per-sector, not one shared pool.** `swing_model/portfolio_manager.py::can_open_new_position()` previously read `MAX_OPEN_POSITIONS`/`_CORRELATED_PAIRS` as hardcoded Python constants — confirmed via direct inspection that `cfg` was accepted but never actually used for these checks. Now reads `cfg["portfolio"]["sectors"][sector].max_open_positions`/`correlated_groups` (falling back to the old hardcoded values when cfg lacks this structure), plus a new `max_total_open_positions` ceiling (sum of active sectors' caps) checked across all positions regardless of sector. Correlated-pair protection is generalized from fixed 2-element pairs to arbitrary-size groups (`pair.issubset(group)`), so the regional-banks sector can define its 5 tickers as one correlated group ("max 1 open bank position at a time") using the same mechanism, not a special case. **Also found and fixed:** the real call site in `run_swing_model.py` never passed `cfg` to `can_open_new_position()` at all — without this fix, the new sector-aware logic would have been dead code in production, always falling back to defaults. `config/swing_config.yaml`'s `portfolio` block restructured to match (`max_total_open_positions: 4`, `sectors.semiconductors.max_open_positions: 2` + `correlated_groups` matching the original 6 pairs, `sectors.regional_banks.max_open_positions: 2` + one 5-ticker group). With only semiconductors active, effective behavior is unchanged (semis' own cap of 2 remains the binding constraint; no bank position can ever be opened while the sector is inactive). `tests/test_phase8_portfolio.py` extended with 5 new multi-sector cases (sector slots don't share a pool, global ceiling still applies, correlated groups stay sector-isolated).

**Phase 3 — Alpha Vantage news restricted to the post-close scan only, for every active ticker.** `_fetch_av_news_safe()` calls in `run_swing_model.py`/`paper_runner.py` are now gated on `scan_type == "post_close"`; pre-market/mid-session fall back to the already-free Yahoo+Finnhub sources. This mirrors the cadence-tiering already used for Fundamental (weekly) and Positioning (daily) — and is a genuine resource constraint, not a preference: at 6 tickers × 3 scans/day, AV usage (~18 calls) was already close to the 20-call soft budget; the originally-planned 11-ticker two-sector watchlist at the same 1:1 call pattern would need ~33 calls/day, blowing past both the 20 soft and 25 hard free-tier limits. `config/swing_config.yaml`'s `alpha_vantage_budget` updated to reflect this (`post_close: 6` — was `8`, itself a stale figure since no code ever actually made separate SMH/VIX AV calls; `pre_market`/`mid_session: 0`, was `6`/`6`). New tests in `tests/test_app_ui_persistence.py` confirm AV news is fetched for `post_close` and skipped for `pre_market`.

### Why it was changed
User asked to actually track a second sector live, not just as a backtest research question (following the v2.2.6/v2.2.7 finding that the entry-filter edge generalizes to regional banks). Before touching the live watchlist, requested a design pass — two Explore-agent research passes over the codebase found 7 places with hard single-sector assumptions that would have silently produced wrong results if bank tickers were simply appended to the existing flat ticker list (blended valuation peer-averages, wrong relative-strength benchmark, pooled cross-ticker correlation across unrelated sectors, a system-wide event-gate block from a sector-specific trigger, a shared 2-slot portfolio cap, and the AV budget wall) plus one that was already broken independent of this feature (the `is_ticker_blocked` bug). This entry fixes all of them in behavior-preserving phases, verified by regression tests, before the second sector is ever actually turned on — that activation is deliberately deferred to a separate, later version bump requiring its own real backtest run against the live multi-sector code path (not the v2.2.6/v2.2.7 research relabel), per this file's own MAJOR-version rule for trade-selection-affecting changes.

### Backtest result
**N/A for Phases 0-2** — additive/behavior-preserving, verified by 529 passing tests (was 497 at v2.2.7's session start; +32 across this entry's new/extended test files), zero regressions against the pre-refactor baseline. **Phase 3 (AV cadence) has no meaningful backtest comparison available** — the backtest engine's News layer (`backtesting/historical_news_loader.py`) does point-in-time lookups against archived historical articles per calendar date, with no concept of scan_type/intraday cadence at all, so there is no mechanism in the existing backtest harness to simulate "3x/day AV calls" vs. "post-close-only AV calls" and compare results. This is a known gap, not a result being omitted — flagged here rather than fabricating a comparison the harness can't actually produce. The live/paper effect (fewer AV-sourced articles feeding pre-market/mid-session News scores, more Yahoo/Finnhub-only coverage at those times) will only be observable in real paper-trading data going forward.

### Approved by
MrKoods — 2026-07-19 (plan reviewed and approved in plan mode before implementation; live watchlist activation deliberately deferred to a separate future version)

---

## [v2.2.7] — 2026-07-19 — Wire the real macro overlay into the backtest (was hardcoded to zero)

**Status:** Code updated. Same not-yet-eligible-to-go-live status as v2.0.0–v2.2.6. **This closes a backtest-only gap — it does not change live/paper scoring at all.** `paper_trading/paper_runner.py` already computes a real macro overlay every scan (`_compute_macro_safe(mkt["tnx_series"], mkt["dxy_series"], cfg)`, live TNX/DXY data) and has since Enhancement 7 was built. Only the backtest was faking it.

### What changed
- `backtesting/backtest_engine.py`: `_simulate_test_signals()` previously passed `macro_modifier=0.0` to `compute_confidence_score()` unconditionally, for every single simulated trade, in every version through v2.2.6. New `_load_macro_series()` loads cached `data/historical_macro/TNX.csv` / `DXY.csv` (10-yr Treasury yield, USD index — same two proxies `shared/utils/macro_overlay.py` already uses live) once per backtest run; each candidate bar now computes a real, point-in-time `compute_macro_state()` result (no look-ahead — series sliced to `<= bar_date`) and uses its actual `confidence_modifier` (-10 to +3) instead of the hardcoded zero. `china_keyword_count_5d` is fixed at 0 (no historical news-keyword archive covers the full backtest window) — neutral-when-unavailable, the same pattern already used for News/Fundamental elsewhere in this function. Each outcome now also carries a `macro_state` field for diagnostics.
- `data/historical_macro/` (new, gitignored — same treatment as `data/historical_banks/`): `TNX.csv`, `DXY.csv`, 2013-2026, fetched via yfinance.

### Why it was changed
- Directly investigating the open question flagged in v2.2.6 (walk-forward windows pass consistently in 2018-2021, mostly fail 2022-onward, unexplained). Pulled 10-year Treasury yield annual averages and lined them up against every walk-forward window: **every passing window sits in a falling-or-low-rate environment (2014-2021); every failing window with enough trades to judge sits in a rising-or-persistently-high-rate environment (2016-2018 partial, 2020-2026).** Textbook mechanism — cheap capital favors growth/momentum continuation, rising rates compress valuations and produce choppier, more mean-reverting price action. The codebase already has a tool built for exactly this (`macro_overlay.py`, monitors Fed rate direction among other things) but the backtest had simply never exercised it.

### What wiring it in actually showed
- Re-ran the rolling (24mo window, 6mo step) walk-forward with the real macro overlay active. The 2022-2023 rate-hiking-cycle windows now surface **fewer but meaningfully higher-quality** qualifying trades (e.g. 2022-07→2024-07: 4 trades at 75% WR, up from consistently-failing full samples pre-fix) — the overlay is suppressing weak candidates below the 90 threshold during adverse macro readings rather than letting them through to become recorded losses. **Zero qualifying trades ever occurred during an `"adverse"` macro state** (109 neutral, 103 favorable, 0 adverse, out of 212 pooled trades on the rolling view) — confirms the modifier works by suppression, exactly as designed.
- More strikingly: **the 2024-01→2026-01 and 2024-07→2026-07 windows flip from FAIL to PASS** (69.2% and 75.0% WR respectively) — the most recent, most relevant-to-right-now stretch of the walk-forward analysis looks meaningfully better once the model is allowed to use the same macro awareness live trading already has.
- Official fixed-slice result improves modestly: 66.7% WR (was 64.7%), avg R:R 2.35 (was 2.29), 18 qualifying trades (was 17, still below the 100-trade minimum), max drawdown 3.0%, max consecutive losses 3.
- Cross-sector combined pooled result (semis + banks, non-overlapping 24mo windows, same methodology as v2.2.6): 100 trades, 58.0% WR, 1.78 avg R:R — close to the pre-fix estimate (104 trades, 58.7%/1.78), i.e. the aggregate headline number barely moved, but the *temporal consistency* improved substantially, which is the more important result: this was an investigation into *why* performance varied by era, and it now has a real, evidenced, partial answer instead of an open mystery.

### Backtest result
Fixed-slice: 66.7% win rate, avg R:R 2.35, 18 qualifying trades (below the 100-trade minimum), Sharpe not meaningful at this sample size, max drawdown 3.0%. Per this file's own rule this remains ineligible for live trading — trade-count shortfall on the fixed slice is disqualifying regardless of the improved win rate. The cross-sector pooled evidence (100 trades, 58.0% WR, 1.78 avg R:R) remains the more statistically meaningful figure.

### Approved by
MrKoods — 2026-07-19

---

## [v2.2.6] — 2026-07-19 — Fix walk-forward window sizing; adopt next-bar confirmation; test a second sector

**Status:** Code updated. Same not-yet-eligible-to-go-live status as v2.0.0–v2.2.5. Entry-filter change is backtest-methodology only (does not touch live/paper scoring, same as v2.2.5 — see that entry). Walk-forward window/bar changes are backtest-diagnostic only — **the actual go-live safety gate (80% win rate, 1:3 min R:R, `run_backtest()`'s own `passed` computation, Project_Scope.md's Performance Thresholds) is untouched by this entry.**

### What changed

**1. Walk-forward window sizing fixed — this was the real bug behind "0/24 windows ever passed."**
- `backtesting/backtest_engine.py`: `run_walk_forward()` gains `step_months` (decoupled from `validate_months`, defaults to the same value for backward-compatible non-overlapping windows) and changes `validate_months`'s default from 6 to 24. At this design's real signal frequency (~0.5-2 qualifying trades/month post-v2.2.5), a 6-month window routinely produced 0-5 trades — too few to judge win rate on at all. Re-running the original v2.2.4 walk-forward analysis with 24-month windows: **6 non-overlapping windows, 1 clearly passes (2018-2020: 76.5% WR, 17 trades), most of the rest have enough data to judge and mostly don't clear the bar** — a completely different, far more informative picture than "0 of 24," which was mostly an artifact of undersized windows, not genuine failure.
- Also added `min_trades_for_verdict` (default 10) and a `"verdict"` field (`"pass"` / `"fail"` / `"insufficient_data"`) per window — a zero-signal window during a regime this strategy structurally can't trade (v2.2.4's regime-coverage finding) is not evidence of failure, it's correct abstention, and is now distinguishable from genuine underperformance instead of both reading as `passed: False`.
- A rolling view (`step_months=6`, `validate_months=24`, 21 overlapping windows) shows a real temporal pattern worth remembering: **windows starting 2018-2021 pass consistently; windows starting 2022 onward mostly fail or lack data.** The edge was strongest in 2018-2021 and has looked weaker in the most recent multi-year stretch — the stretch closest to right now. Not explained away by anything in this entry; flagged as a real, unresolved caveat.

**2. Walk-forward diagnostic bar recalibrated (0.70 WR / 1.8 R:R / 6mo window → 0.55 WR / 1.3 R:R / 24mo window) — diagnostic only.**
- `run_walk_forward()`'s `win_rate_bar`/`avg_rr_bar` defaults lowered based on real evidence: the pooled 24-window backtest result (see #3 below) landed around 55-65% WR / 1.7-1.8 avg R:R depending on exact filter combination, consistently below the original 70%/1.8 bar regardless of how the window was sized. The original bar was set before any data existed; this recalibration reflects what the strategy has actually, repeatedly shown across independent periods and two sectors (see below) rather than continuing to score every window against a target it has never once hit even in its best-performing years.
- **This does not touch the ultimate 80%/1:3 go-live threshold anywhere else in the codebase or in Project_Scope.md.** That remains the non-negotiable bar for real capital, exactly as strict as originally designed. This change only affects the walk-forward function's internal stability diagnostic — "is this edge real and repeatable across time" — which is a different, looser question than "is it good enough to risk money on."

**3. A second sector (regional banks/financials) tested as an independent, research-only dataset — not added to the live watchlist.**
- New `data/historical_banks/` (gitignored-equivalent research data, not part of `data/historical/`): KRE (benchmark) + ZION, KEY, HBAN, RF, FITB — 2013-2026, matching the semiconductor dataset's span. (CMA/Comerica failed to fetch via yfinance, substituted FITB.)
- `backtest_engine.py`'s sector-relative logic (`smh_sector_trend`, RS-vs-benchmark, VIX-proxy regime classification) is hardcoded to look up a ticker literally named `"SMH"` — tested the bank sector by relabeling KRE's DataFrame under the `"SMH"` key when building the test data dict for this sector, which correctly reuses all the existing sector-relative math for a different sector's benchmark. Documented here since it's a deliberate relabel, not a bug.
- `config/swing_config.yaml`'s live watchlist is **completely unchanged** — still the original 6 semiconductor tickers + SMH. This is a backtest research question ("does the edge generalize"), not a live-trading universe expansion, which would be a separate, much bigger decision (sector rotation logic, correlated-pair rules, API budget, Discord/UI changes) not made here.

**4. A real correction: next-bar confirmation, dismissed in v2.2.4/v2.2.5 as unhelpful, is actually the best-evidenced entry-filter change once the window-sizing bug (#1) is fixed.**
- Re-ran `backtesting/entry_filter_variants.py`'s comparison with the corrected 24-month windows instead of the original flawed 6-month ones. Result reversed the earlier conclusion:

  | Variant | Pooled trades (6 windows) | Win rate | Avg R:R | Windows passed |
  |---|---|---|---|---|
  | Original (RSI 45-82, no confirmation) | 299 | 53.2% | 1.70 | 3/6 |
  | RSI 45-70 only (the v2.2.5 change) | 89 | 53.9% | 1.69 | **1/6** |
  | Volume confirmed (≥0.5z) | 59 | 59.3% | 1.69 | 2/6 |
  | **Next-bar confirmation + RSI 45-70 — adopted** | 53 | **64.2%** | **1.82** | **3/6** |

  Under the original, undersized 6-month windows (v2.2.5), next-bar confirmation measured as flat/unhelpful (49.1% vs. 49.4% baseline) — that read was itself contaminated by the same small-sample problem this entry's window fix addresses. With enough trades per window to actually judge, it's the strongest single change tested, and the v2.2.5 RSI-only change is now the *weakest* of the four real variants. Rather than defend the earlier conclusion, `_simulate_test_signals()`'s default `require_confirmation_bar` is changed from `False` to `True`, kept alongside the RSI 45-70 default from v2.2.5 (both together is what was actually tested and adopted above).
- Re-verified against the fixed 2022-2026 slice too (the number that diverged badly for the v2.2.5 RSI-only change): **64.7% WR, avg R:R 2.29, 17 qualifying trades, max drawdown 3.0%, max consecutive losses 3** — the fixed-slice and pooled-window reads now broadly agree, unlike the v2.2.5 change, which is itself a reassuring consistency check on this one.

### Combined evidence (both sectors, final adopted default: RSI 45-70 + next-bar confirmation)

| | Trades | Win rate | Avg R:R |
|---|---|---|---|
| Semis only | 53 | 64.2% | 1.82 |
| Banks only | 51 | 52.9% | 1.73 |
| **Combined, pooled** | **104** | **58.7%** | **1.78** |

Combined EV ≈ +0.63R/trade — a real, modest, positive edge validated independently across two unrelated sectors with the same filter logic, not just one. Banks alone are weaker than semis alone, so the edge isn't sector-agnostic in strength, but it holds the same sign and rough magnitude in both — meaningfully more reassuring than semis-only evidence, which could just as easily have been semiconductor-specific noise.

### Decision: stop further backtest-parameter iteration on this fixed historical sample
Five rounds of testing against the same ~12-year, now-two-sector dataset (stop-multiplier, volume gate, RSI band, confirmation bar, and the combination) is approaching the point of diminishing, overfitting-risk returns — each additional twist tests a hypothesis against data that's already been looked at repeatedly. The entry filter (RSI 45-70 + next-bar confirmation) is considered settled for now, not because it's proven, but because further backtest tuning against this same finite sample isn't the right next step. **The next legitimate validation is time**: continued daily paper trading against genuinely new, never-backtested data. Revisit backtest-driven filter changes only once meaningfully more historical or paper-trading data exists, not on a shorter cycle than that.

### Backtest result
Fixed-slice `run_backtest()` result with the final v2.2.6 default: 64.7% win rate, avg R:R 2.29, 17 qualifying trades (well below the 100-trade minimum on this slice alone — small-sample caveat applies same as always), Sharpe 0.14 (not meaningful at n=17), max drawdown 3.0%, max consecutive losses 3. Per this file's own rule this remains ineligible for live trading — the trade-count shortfall on the fixed slice alone is disqualifying regardless of the encouraging win rate. The pooled cross-sector evidence above (104 trades, 58.7% WR) is the more statistically meaningful figure and the actual basis for this version's entry-filter decision.

### Approved by
MrKoods — 2026-07-19 (explicitly requested acting on all 5 of the "expert analyst" recommendations from this session, including the second-sector test)

---

## [v2.2.5] — 2026-07-19 — Tighten backtest entry-filter RSI ceiling (82→70) based on walk-forward evidence

**Status:** Code updated. Same not-yet-eligible-to-go-live status as v2.0.0–v2.2.4. **This is a backtest-methodology change only — it does not touch live or paper scoring.** `swing_model/scoring.py` already scores RSI continuously (0-8 points, tapering above 80, no hard cutoff); this filter exists solely in `backtesting/backtest_engine.py`'s simplified candidate-selection logic, which decides which historical bars the backtest even considers as breakout candidates.

### What changed
- `backtesting/backtest_engine.py`: `_simulate_test_signals()`'s default `rsi_max` changed from `82.0` to `70.0`. `rsi_min` stays `45.0`. Both remain overridable parameters (see v2.2.4's parameterization) for future research.
- `backtesting/entry_filter_variants.py`: `VARIANTS["baseline"]` renamed to `"original_baseline_45_82"` and pinned to explicit `{rsi_min: 45.0, rsi_max: 82.0}` (was `{}`) — an empty dict would have silently started meaning "45-70" the moment the function default changed here, breaking the variant comparison's own reference point. Added `"current_default_45_70"` as the new baseline label.
- `backtesting/reports/sensitivity_analysis.csv` regenerated against the new default.

### Why it was changed
- User asked what an expert stock/technical analyst would flag about the entry design, given the diagnostic finding that qualifying-trade losses take 5-9 days to resolve (not 1-2) and 41% of qualifying trades stall around 0.88R when the 15-day time stop hits (v2.2.4 finding) — a signal-conviction pattern, not a fast-false-breakout pattern. RSI 82 as an upper bound lets through already-extended moves with less runway left to reach a 3R target before time runs out.
- Built `backtesting/entry_filter_variants.py` to test this properly: pooled qualifying trades across all 24 walk-forward windows (2014-2026) instead of hand-tuning against the single fixed 70/30 test slice (the exact overfitting trap flagged in v2.2.4 when a volume-confirmation experiment was tested and reverted for this reason). Five variants tested — RSI tightening, volume confirmation, next-bar confirmation, and a combination — pooled results:

| Variant | Pooled trades (24 windows) | Win rate | Avg R:R |
|---|---|---|---|
| Original (RSI 45-82) | 156 | 49.4% | 1.22 |
| **RSI tightened (45-70) — adopted** | 51 | **60.8%** | 1.41 |
| Volume confirmed (≥0.5 z-score) | 104 | 55.8% | 1.25 |
| Next-bar confirmation | 110 | 49.1% | 1.08 |
| RSI + volume combo | 32 | 71.9% | 1.48 |

  Next-bar confirmation (does the bar after the breakout still close above the level) did **not** help — consistent with losses resolving over 5-9 days rather than 1-2, a simple one-bar check doesn't catch the real failure pattern. The RSI+volume combo shows the best number but on only 32 pooled trades across 12 years — flagged as promising, not adopted, too thin a sample to trust yet.

### An important, honest tension — not hidden
- On the pooled 24-window sample, RSI 45-70 clearly improves win rate (49.4%→60.8%).
- But on the *specific* fixed 2022-2026 slice `run_backtest()` reports as its headline number, the same change makes it **worse**: 57.0%→51.8% win rate, and qualifying trades drop from 107 to **27 — below the project's own 100-trade minimum** for a statistically valid read on that slice alone.
- This is not necessarily a contradiction: at n=27, a handful of individual trades flipping win/loss swings the percentage by several points on pure noise, and the 24-window pooled sample (207 total trades across independent periods) is the statistically sturdier of the two reads. But it's a real, visible tension, not a clean win — decided to adopt based on the pooled evidence being more trustworthy than one slice, with this section serving as the explicit record of that judgment call and its cost (signal frequency at the 90 threshold drops from ~2.19/month to ~0.55/month per the regenerated sensitivity report).

### Backtest result
Official fixed-slice number **degrades** with this change: 51.8% win rate (was 57.0%), avg R:R 2.23 (was 2.01), 27 qualifying trades (was 107, now below the 100-trade minimum), Sharpe 0.64 (was 2.45, though at n=27 this figure is on a thin sample). Per this file's own rule this remains ineligible for live trading — already true before this change, unaffected by it. The 24-window pooled evidence in the table above is the actual basis for adopting this default, not the fixed-slice number, which is exactly why this section documents both rather than only the favorable one.

### Approved by
MrKoods — 2026-07-19 (adopted knowing the fixed-slice headline number moved unfavorably; decision rests on the pooled walk-forward evidence)

---

## [v2.2.4] — 2026-07-19 — Fix broken sensitivity-analysis tool; surface walk-forward's real result

**Status:** Code updated. Same not-yet-eligible-to-go-live status as v2.0.0–v2.2.3 — tooling/analysis fix, no scoring/threshold impact on live or paper trading.

### What changed
- `backtesting/metrics.py`: `run_sensitivity_analysis()` took a `historical_data: dict` parameter and read `historical_data.get("outcomes", [])` — but every caller passed the raw `{ticker: DataFrame}` dict from `load_historical_data()`, which has no `"outcomes"` key. The lookup always missed, so the function silently returned all-zero rows at every threshold, every time it had ever been run. Changed the signature to take `outcomes: list[dict]` and `test_months: float` directly instead of a dict wrapper that nothing ever populated correctly.
- `backtesting/backtest_engine.py`: extracted the train/test split + signal simulation block from `run_backtest()` into a new shared helper `_get_test_outcomes()`, so `run_backtest()` and the `--sensitivity` path both operate on the exact same out-of-sample signal set instead of two independently-computed splits that could silently drift apart. `run_backtest()`'s own result is unchanged (verified identical: 57.0% WR / avg R:R 2.01 / 107 trades / Sharpe 2.45 before and after this refactor).
- `backtesting/run_backtest.py`: `--sensitivity` now calls `_get_test_outcomes()` then `run_sensitivity_analysis()` with real data instead of the broken dict.

### Why it was changed
- User asked what to do next given daily paper trading is ongoing. Investigating whether the 90-point confidence threshold was well-calibrated required running `--sensitivity`, which turned out to have never worked — Project_Scope.md documents this tool (Clarification 3) but it had no test coverage and had silently done nothing since it was written.

### What the fix revealed
- **Win rate is roughly flat (56.8%–60.5%) across every threshold from 85 to 95** — it does not climb meaningfully as the bar gets stricter (`backtesting/reports/sensitivity_analysis.csv`). A well-calibrated confidence score should show win rate rising with threshold; this one doesn't. This means raising the live threshold above 90 is unlikely to move win rate toward 80% by itself — the score isn't ranking candidates by real forward edge within this range, so the fix has to be a better signal, not a stricter cutoff.
- **Walk-forward has never once passed.** `run_backtest()` already computes this on every run (`run_walk_forward()`, 24 six-month windows from 2014–2026) but the console output in `run_backtest.py` never printed it, so it had gone unexamined. Result: **0 of 24 windows meet the pass bar** (win rate ≥70%, avg R:R ≥1.8, ≥10 trades). Most windows have far too few qualifying trades (many are 0–5) to be individually meaningful, and window-to-window win rate swings from 0% to 76.9% — consistent with a strategy that fires rarely enough that no single 6-month slice is a reliable sample. The 57.0%/107-trade headline number from the fixed 2022–2026 test split is the most statistically meaningful figure available, but it obscures how unstable the underlying signal is period-to-period.
- **A volume-confirmation entry gate was tested and reverted, not adopted.** Requiring `breakout_volume_zscore >= 0.5` on the backtest's entry filter improved the test-set result (57.0%→62.0% WR, avg R:R 2.01→2.07, max drawdown 7.5%→5.7%) but dropped qualifying trades to 79, below the 100-trade minimum, and — more importantly — this was discovered by iterating filter parameters directly against the single fixed out-of-sample test set, which is exactly the kind of test-set overfitting the 70/30 split exists to prevent. Reverted rather than shipped. A legitimate version of this idea needs validation against the walk-forward windows (or a fresh, never-peeked-at holdout), not a single re-run against the same 30% slice.

### Backtest result
N/A for this entry specifically — `run_backtest()`'s own output is unchanged by this fix (confirmed identical before/after). The walk-forward and sensitivity results it surfaced are existing, previously-uncomputed-or-unexamined facts about v2.2.2/v2.2.3, not a new backtest run against new code.

### Approved by
MrKoods — 2026-07-19

---

## [v2.2.3] — 2026-07-19 — Fix cross_ticker config mismatch; dampen sector-wide modifier stacking

**Status:** Code updated. Same not-yet-eligible-to-go-live status as v2.0.0–v2.2.2 — see "Backtest result" below.

### What changed
- `swing_model/cross_ticker_analysis.py`: `analyze_cross_ticker()` looked up modifier values under the keys `"sector_wide"`/`"individual_divergence"` in `cfg["modifiers"]["cross_ticker"]`, but `config/swing_config.yaml` defines those same settings under `sector_wide_discount`/`divergence_boost`. The mismatch meant the configured values were never read — the function silently fell back to hardcoded defaults (`-5.0`/`+5.0`/`-10.0`) every time, regardless of what was set in config. Fixed the lookup keys to match the config schema.
- `config/swing_config.yaml`: `modifiers.cross_ticker.sector_wide_discount` changed from `-10` (a value that, per the bug above, was never actually being applied — the real behavior was always `-5.0`) to `0`. This is a deliberate dampening, not a restoration of the old intended `-10`: `regime` and `sector_rotation` modifiers are both already derived from the same underlying SMH price trend that drives cross_ticker's "sector-wide" state (3+ tickers moving together), so a third sector-wide penalty on top of those two triple-counts one observation. Confirmed directly against real paper-trading logs (2026-07-17): `regime=-5.0`, `sector_rotation=-15.0`, `cross_ticker=-5.0` fired identically across TSM and MU despite very different underlying category scores — all three tied to the same sector-wide SMH weakness that week. `divergence_boost` (+5, individual outperformance) and the `underperforming` penalty (-10, individual-specific) are untouched — those reflect genuine ticker-specific information the other two modifiers can't see, so they're not redundant.
- This exact risk was already flagged in v2.2.0 (regime/sector_rotation correlation logged as a warning, not auto-corrected, "a real risk-weighting decision that shouldn't be made silently"). This entry makes that deliberate call for the sector-wide portion of `cross_ticker` specifically, rather than leaving it unresolved indefinitely.

### Why it was changed
- User asked how to improve the model before continuing paper trading. Investigating why paper trading has produced zero qualifying signals surfaced that `regime` + `sector_rotation` + `cross_ticker` were stacking to a uniform -24 modifier across the entire watchlist on 2026-07-17, independent of any individual ticker's technical merit — a config bug and an unresolved triple-counting risk compounding each other.

### Backtest result
**N/A — not modeled by the current backtest harness.** `backtesting/backtest_engine.py`'s `_simulate_test_signals()` hardcodes `cross_ticker_modifier=0.0` for every simulated trade (cross-ticker correlation across the 6-ticker watchlist isn't computed in the backtest replay at all). This change has no effect on the existing v2.2.2 backtest result (57.0% WR / avg R:R 2.01 / 107 trades / Sharpe 2.45, trending_up regime only) — that result stands as the current baseline, unaffected by this fix. The lack of cross_ticker modeling in the backtest is itself a gap worth closing eventually, separate from this fix. All 500 tests pass (497 passed, 3 skipped, `tests/test_volume_cross_ticker.py` included).

### Approved by
MrKoods — 2026-07-19

---

## [v2.2.2] — 2026-07-19 — Fix 24 issues from a full-codebase senior-engineer review

**Status:** Code updated. Same not-yet-eligible-to-go-live status as v2.1.0-v2.2.1 — see "Backtest result" below. Several of these entries change scoring/risk computations (flagged individually), so this is not a pure reliability patch like v2.1.5/v2.2.1.

### What changed

**Backtest validity**
- `backtesting/backtest_engine.py`, `backtesting/metrics.py`: the equity curve is now built in chronological order (sorted by exit date) instead of the ticker-by-ticker order signals were generated in, and `compute_sharpe()` now annualizes using the actual observed trade frequency (`_trades_per_year()`) instead of always assuming `sqrt(252)` as if each trade were one calendar day. Both distorted the previously-reported Sharpe ratio (9.10) — **that figure is stale and must not be cited until the backtest is re-run.** Win rate (63.1%) and avg R:R (2.02) were unaffected by either bug.
- `backtesting/backtest_engine.py`: the 70/30 test split now includes a real pre-cutoff warmup buffer (65 bars) per ticker so the first ~60 nominal test-period days aren't lost to indicator warmup with zero chance of producing a signal; a new `signal_cutoff` param on `_simulate_test_signals()` ensures warmup-buffer bars still can't themselves count as an out-of-sample signal.
- `backtesting/backtest_engine.py`, `swing_model/indicator_pipeline.py`: fundamental scoring in the backtest now does a point-in-time lookup against a dated archive (`data/processed/fundamental_history/`, written on every weekly refresh) instead of using today's live snapshot for the entire multi-year replay — closes a real lookahead-bias source. The archive starts empty, so bars before the first archived snapshot fall back to neutral; it builds up week by week from here (same "accumulates going forward" tradeoff already accepted for Positioning).

**Scoring correctness**
- `shared/indicators/technical_common.py`, `swing_model/scoring.py`: MACD unavailability (short history, <35 bars) no longer silently reads as "not bullish" — new `macd_data_available` flag lets `trend_score` tell "insufficient data" apart from a genuine bearish MACD instead of capping the score either way.
- `swing_model/fundamental_layer.py`: `eps_growth_score` changed from an asymmetric -2..+3 scale with a hard cliff at -5% decline (anything worse, from -6% to -60%, scored identically) to a symmetric, graduated -3..+3 scale.
- `swing_model/scoring.py`: the positioning offline-degradation cap (caps score at 70 when positioning data is unavailable) previously only fired when `positioning_offline` was explicitly `True` — an empty/`None` positioning dict (the documented "data unavailable" default) silently bypassed it. Now also fires on an empty dict.
- `swing_model/sentiment_layer.py`: the StockTwits bullish-ratio z-score now requires a minimum baseline sample size (5 messages across the trailing window) before trusting it — previously a single message on a low-volume ticker, with prior days at the neutral 0.5 placeholder, could produce `pstdev([0.5]*4)==0`, fall back to a tiny `std_baseline=0.15`, and max the 0-7 sub-score off n=1.
- `shared/utils/insider_tracker.py`, `swing_model/positioning_layer.py`: consolidated three divergent buyer-counting implementations (one correctly windowed + shares-or-text, two text-only and unwindowed) into one shared `count_distinct_traders()` — `positioning_layer._score_insider` and `insider_tracker._signal_to_modifier` used to be able to disagree with `classify_transactions`' own classification.
- `shared/utils/source_credibility.py`: `score_news_outlet()` no longer matches when a short/garbled parsed source string is merely contained *within* a known outlet key (e.g. a truncated "ft" matching "ft.com" and inheriting Financial Times' 0.88 credibility) — only the safe direction (a known key found within the parsed source) remains.

**Risk/execution enforcement**
- `swing_model/trade_selector.py`: now actually enforces the documented 1:3 R:R filter and a liquidity/slippage filter (structures where slippage eats ≥50% of raw EV are excluded) — both were computed but never checked before, so a 1:1 R:R structure could rank #1 and be marked `"recommended": True`. The documented Greeks filter (theta/vega/gamma) remains unimplemented — no options-chain data currently flows into this function — and is now surfaced via a `greeks_filter_status` field instead of silently reading as passed.
- `shared/utils/position_sizer.py`: `compute_position_size()` now zeroes `risk_pct`/`dollar_risk` when the 5% capital cap is exceeded instead of returning full sizing and relying on the caller to check `capital_approved`.
- `swing_model/portfolio_manager.py`: `can_open_new_position()` now blocks a second same-direction position on a ticker that already has one open — the existing correlated-pair check only compared *different* tickers and couldn't catch this.
- `shared/utils/risk_reward.py`: `compute_entry_zone()`/`compute_stop_loss()` now reject `atr_14 <= 0` instead of silently producing a distorted (potentially inverted) stop/target from a bad ATR data point.
- `shared/utils/regime_detection.py`: the VIX 25-30 band (elevated but below the extreme cutoff) with mixed trend signals now correctly classifies as `REGIME_HIGH_VOL` instead of both branches silently returning `REGIME_CHOPPY`, which had made the `vix_high_threshold` parameter a no-op and skipped the score-cap safety brake for that band.
- `shared/utils/options_math.py`: `compute_ev_surface()` no longer double-multiplies by `win_probability`, which was systematically understating EV for every complex/surface structure (ratio spreads, back spreads).

**Calibration / feedback loop**
- `swing_model/feedback_loop.py`: `_score_outcomes()` now actually uses its `weights` argument (a win/loss composite-separation score) instead of ignoring it and returning the raw win rate — previously `run_calibration()`'s holdout old-vs-new comparison was always equal, so the safety gate meant to reject a bad recalibration could never fail.
- `swing_model/scoring.py`: `compute_confidence_score()`'s `live_weights` parameter was accepted and documented but never read anywhere in the function body — implemented it (redistributes the technical+sentiment+news point pool per calibrated fractions). No current caller passes it, so this has no effect on live scoring yet.
- `backtesting/backtest_engine.py`: corrected `run_backtest()`'s docstring, which claimed the 70/30 split calibrates weights on the train set — it never did and still doesn't; that's a separate, opt-in mechanism (`feedback_loop.run_calibration()`).

**Dead code**
- `swing_model/signal_decay.py`: `rescore_open_positions()` (post-entry daily re-scoring, >10pt confidence-drop early exit, trailing stop, time stop) was `raise NotImplementedError("Phase 8")` — fully implemented. Not wired into `run_swing_model.py`'s live loop yet, since that would mean the system starts closing positions automatically without a separate review pass.
- `paper_trading/paper_trade_engine.py`, `paper_trading/paper_state.py` (removed): deleted `run_paper_session()`/`_update_paper_position()` and the `paper_state.py` module — nothing ever populated `data/processed/paper_positions.json` with an open position, so this orchestrator could only ever no-op. The real, working paper-trading pathway is `paper_runner.py` (`run_paper_scan`) + `paper_updater.py`, both operating on `paper_trading/paper_trades.csv`. `simulate_fill()` (used/tested independently) stays.

**Reliability / ops**
- `shared/api_clients/fundamental_client.py`, `shared/api_clients/news_client.py`, `shared/utils/discord_alerts.py`, `download_historical_news.py`: redact API keys/webhook tokens from error messages before logging — `requests`' `HTTPError` embeds the full request URL (including the `apikey`/`token` query param), so an unredacted 429/403/5xx would have written the live key to `app.log`/`validation_log.csv` in plaintext.
- `shared/api_clients/fundamental_client.py`: `get_earnings_history()`/`get_estimate_revisions()` now check and increment the same Alpha Vantage daily call budget (`av_call_count.json`) that `news_client.py` already enforced — previously these 2 calls/ticker ran uncounted, so a Monday weekly refresh could push real AV usage past the free-tier daily cap while every individual counter still looked fine. Also capped per-call backoff at 90s (was unbounded — worst case ~42 minutes across a full 6-ticker refresh with both calls each).
- New `shared/utils/atomic_io.py` (`atomic_write_json`/`atomic_write_text`, temp-file + rename): wired into `paper_updater.py`'s trade CSV, `feedback_loop.py`'s win-rate/weights files, `news_client.py`'s AV call counter, and `portfolio_manager.py`'s position state — a crash or overlapping run mid-write could previously truncate/corrupt any of these.
- `swing_model/run_swing_model.py`: the per-ticker exception handler now still writes an audit_log.csv row on failure (previously a ticker with an exception anywhere before the normal audit write — sentiment/news/scoring/event-gate all run before it — silently had no row at all for that scan), and no longer blindly mislabels every such failure as a yfinance issue (that flag now only sets where an actual OHLCV fetch failure occurs). A failed VIX fetch now fails conservative (`REGIME_HIGH_VOL`) instead of defaulting to a calm VIX=15 reading.
- `shared/utils/data_validator.py`: `validate_ohlcv()` now also checks Open is within [Low, High] — previously only High/Low/Close/Volume were validated per bar.
- `app_ui/config_tab.py`: the config editor now detects and warns when the file changed on disk since it was last loaded here, before overwriting it.

### Why it was changed
User requested a full-codebase review "thinking like a senior developer and stock market analysis expert," which was run as four parallel focused reviews (core scoring layers; risk management/market-context utils; backtesting/paper trading; orchestration/API clients/app infra). All findings were spot-checked against the actual code before being reported, then fixed on request. Full list and reasoning for each fix is in the conversation this version was produced from; the most consequential single finding was the Sharpe-ratio computation bug, since it directly invalidates a previously-reported headline backtest metric.

### Backtest result
**RUN 2026-07-19 — FAILED.** `python -m backtesting.run_backtest` against `data/historical/{AMD,ASML,AVGO,MU,NVDA,SMH,TSM}.csv` (3,395 daily bars/ticker), 70/30 split with walk-forward.

- Win rate: **57.0%** (required 80%) — ❌
- Avg R:R: **2.01** (required ≥1:3) — ❌
- Qualifying trades: 107 (required ≥100) — ✅
- Sharpe ratio: **2.45** — this replaces the stale 9.1 figure from the pre-v2.2.2 engine; confirms that figure was inflated by the Sharpe/equity-curve bug fixed in this version, independent of the win-rate shortfall
- Max drawdown: 7.5%
- Regime coverage: **all 107 qualifying trades fall in `trending_up` only** — no choppy, high-volatility, or trending-down trades appear in the test set, so the regime-coverage requirement (Project_Scope.md → Performance Thresholds) is not met either, separate from the win-rate failure. The available historical window does not currently contain enough regime diversity in the out-of-sample period to validate the model outside a trending market.

This is the first backtest run against the actual 5-category (Technical/Positioning/Sentiment/News/Fundamental) scoring model with real fix-ups from this version's review — it supersedes the pre-v2.0.0-era 63.1%/149-trade figure, which was never valid for this scoring design in the first place (see v2.0.0/v2.1.0 entries). Per this file's own rule, v2.2.2 remains ineligible for live trading: win rate and R:R both fall well short of threshold, and the test window's lack of regime diversity means even the trending-up-only result can't yet be generalized. Root-causing the win-rate gap (which of the five categories is contributing false positives) and extending the historical window for regime coverage are both required before the next attempt.

### Approved by
MrKoods — 2026-07-19 (code changes only; backtest failed, not approved for live trading)

---

## [v2.2.1] — 2026-07-18 — Remove email/SMS notification delivery; Discord + app UI only

**Status:** Code updated. Same not-yet-eligible-to-go-live status as v2.1.0-v2.2.0 — infrastructure simplification, no scoring/threshold impact.

### What changed
- `shared/utils/notification_router.py`: rewritten to send every alert to Discord only. Removed `send_email()`, `send_sms()`, the `PRIORITY_NORMAL`/`PRIORITY_CRITICAL`/`PRIORITY_HIGHEST` constants, and `classify_alert_priority()` — priority-based escalation had no remaining purpose once email/SMS were removed as delivery targets. `route_alert()` no longer takes a `priority` argument and its result dict drops `email_sent`/`sms_sent`, keeping only `discord_sent`/`errors`.
- `swing_model/run_swing_model.py`: updated the two `route_alert()` call sites (`_handle_open_position_critical_event`, `_try_send_missed_scan_alert`) to drop the now-removed `priority` argument and `classify_alert_priority` import.
- Removed SMTP (`SMTP_HOST`/`SMTP_PORT`/`SMTP_USER`/`SMTP_PASSWORD`/`ALERT_EMAIL_TO`) and Twilio (`TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN`/`TWILIO_FROM_NUMBER`/`TWILIO_TO_NUMBER`) variables from `.env.example`, the `twilio` dependency from `requirements.txt`, and `email_secondary`/`sms_tertiary` from `config/global_config.yaml`'s `notifications` block.
- `tests/test_phase10_alerts.py`: removed `TestAlertPriority` (tested the now-deleted `classify_alert_priority()`). `tests/test_event_gate.py`: updated the `route_alert` mock and assertions in `TestOpenPositionCriticalAlert` to match the new (no-priority, Discord-only) signature and return shape.
- Updated `README.md`, `Project_Scope.md`, and `App_UI_Scope.md` (the draft desktop-UI addendum) to describe Discord as the sole alert delivery channel — the app UI's persisted notification feed is the second place alerts surface, not email/SMS.

### Why it was changed
- The system is still in the paper-trading phase with no live capital at risk (every version through v2.2.0 remains not-yet-eligible-to-go-live per this file's own rule), so the guaranteed-delivery rationale behind the original email/SMS redundancy (Enhancement 8 in `Project_Scope.md`) doesn't apply yet. Maintaining SMTP and Twilio credentials and the priority-escalation branching added real operational surface (two more sets of credentials to keep current, two more delivery paths that could silently fail) for a guarantee the project doesn't currently need. Discord plus the in-progress desktop app UI (which persists every notification to SQLite for later review, `App_UI_Scope.md` §3.2) covers the actual current need.
- Simplifying `notification_router.py` down to a single delivery path now also removes a source of friction for the app-UI work in progress — the UI's notification-feed schema no longer needs per-channel (Discord/email/SMS) status tracking, just a single Discord `sent`/`failed` status.

### Backtest result
N/A — notification infrastructure only, no effect on scoring, thresholds, or trade selection.

### Approved by
MrKoods — 2026-07-18

---

## [v2.2.0] — 2026-07-18 — Near-miss awareness alerts; flag correlated regime/sector-rotation penalties

**Status:** Code updated. Same not-yet-eligible-to-go-live status as v2.1.0-v2.1.5. New notification category (not a scoring change) — bumped MINOR per this file's own versioning rule, same precedent as v2.1.0's Event Gate addition.

### What changed
- `shared/utils/discord_alerts.py`: new `send_near_miss_alert()` — a deliberately low-key (grey, "not a trade signal" language, no entry/stop/target) Discord ping for a ticker that scores 80-89 (configurable via `NEAR_MISS_THRESHOLD`), distinct from the real 90+ signal alert so it can't be mistaken for a recommendation.
- `paper_trading/paper_runner.py`: fires `send_near_miss_alert()` for any ticker scoring in `[NEAR_MISS_THRESHOLD, CONFIDENCE_THRESHOLD)`. Near-misses are never written to `paper_trades.csv` — awareness only, not part of the trade dataset.
- `paper_trading/paper_runner.py`: added a log note when `regime_modifier` and `sector_rotation_modifier` are both negative in the same scan — both are derived from the same underlying SMH price action (regime: SMH vs. its own SMA trend; sector_rotation: SMH return vs. SPY) but summed as independent modifiers. The note doesn't change the score; it just flags when a heavily-penalized score reflects one real observation counted twice rather than two independent ones.

### Why it was changed
- Reviewing 2026-07-17's scan showed the 90-point threshold is a hard cliff with zero visibility into "how close" a sub-threshold ticker actually was — an 89 and a 12 looked identical (invisible) from the outside. The near-miss tier gives forward visibility without changing what counts as an actual signal or touching the threshold itself.
- Separately, reviewing the same day's modifier breakdown (added in v2.1.3) showed `regime` and `sector_rotation` both pegged negative simultaneously across the whole watchlist, both traceable to the same SMH weakness. Flagging this compounding is informational only — deliberately not auto-adjusting the score, since that's a real risk-weighting decision that shouldn't be made silently.

### Backtest result
N/A — new notification category + diagnostic logging only, no effect on scoring, thresholds, or trade selection.

### Approved by
MrKoods — 2026-07-18

---

## [v2.1.5] — 2026-07-17 — Fundamental refresh saves incrementally, not just at the end

**Status:** Code updated. Same not-yet-eligible-to-go-live status as v2.1.0-v2.1.4 — reliability fix, no scoring/threshold impact.

### What changed
- `swing_model/indicator_pipeline.py`: `fetch_fundamental_data()` now writes `fundamental_state.json` after every ticker in the weekly refresh loop, instead of only once after all 6 tickers finish. `last_updated` is still only set once the full loop completes (success or per-ticker-caught-failure) — a partial batch correctly still reads as "not refreshed today" so the next opportunity retries it, rather than settling for a part-stale, part-fresh snapshot mislabeled as complete.
- `tests/test_indicator_pipeline_fundamental_refresh.py`: new file (no coverage existed for this module before) — 4 tests, including one that reproduces the exact real incident (`KeyboardInterrupt` mid-batch) and confirms already-fetched tickers survive on disk while `last_updated` correctly stays unset.

### Why it was changed
- Found while reviewing today's scan: `fundamental_state.json` was still showing `last_updated: 2026-07-06`, 11 days stale. Traced it through `data/logs/paper_runner_task.log` and found the July 13 (Monday) weekly refresh had started successfully — NVDA and AMD both completed — and then a literal `^C` appears in the raw log, mid-retry on AVGO: a manual interruption, not a recurring bug. But because the old code only saved once at the very end, that one interruption discarded NVDA and AMD's already-fetched data too, and silently left the system on the prior week's snapshot with no error or warning anywhere. No Monday-after-5pm-ET has recurred since (next is July 20), so nothing had triggered a retry.
- The interruption itself was a one-off, but the all-or-nothing save was a real structural fragility — the same failure mode would recur from a mid-batch crash, a network drop, or hitting the Alpha Vantage budget cap partway through (a real risk: a full 6-ticker refresh can use up to ~18 AV calls, on top of that day's routine news fetching in the same scan).

### Backtest result
N/A — reliability/persistence fix, no effect on scoring, thresholds, or trade selection.

### Approved by
MrKoods — 2026-07-17

---

## [v2.1.4] — 2026-07-16 — Exclude statistical outliers from sector-average valuation scoring

**Status:** Code updated. Same not-yet-eligible-to-go-live status as v2.1.0-v2.1.3 — see "Backtest result" below. Unlike the last three entries, this one does change a scoring computation (Fundamental category's valuation sub-score), so it's flagged more carefully.

### What changed
- `swing_model/fundamental_layer.py`: `score_valuation_vs_peers()` now excludes statistical outliers (modified Z-score via median + MAD, threshold 3.5) from the trailing P/E, forward P/E, and EV/EBITDA sector-average calculations before scoring each ticker against them. New helper `_exclude_outliers()`. Falls back to the unfiltered value set when there are fewer than 4 data points (too small a sample for outlier detection to be meaningful) or when MAD is 0 (no spread to measure against). The excluded ticker itself is unaffected in every other respect — it's still scored, just against the corrected average, same as everyone else.
- `tests/test_fundamental_layer.py`: new file (no test coverage existed for `fundamental_layer.py` before this) — 10 tests covering `_exclude_outliers()` directly and its integration into `score_valuation_vs_peers()`, verified against a fixture shaped like the real watchlist data that exposed the bug.

### Why it was changed
- Found while reviewing 2026-07-15/16's real paper-trading fundamental scores: NVDA, AVGO, and MU all hit the exact fundamental-score ceiling (10.0/10) simultaneously. Traced it back through the real cached data (`data/processed/fundamental_state.json`) and confirmed the math was technically correct but methodologically flawed — AMD's trailing P/E (184x, inflated by a -30.4% EPS decline the prior quarter depressing the denominator) was dragging the 6-ticker sector average up to ~66.6x, which made every OTHER ticker in the watchlist look artificially cheap by comparison (even a genuinely un-cheap 62x P/E scored as "below sector average"). With only 5-6 tickers in the watchlist, one distorted value doesn't just mis-score itself — it silently biases every peer comparison. Verified the fix directly against the real data: sector P/E average corrects from 66.6x to 43.1x with AMD excluded, and the four tickers previously clustered at/near the ceiling now spread out (5, -1, 2, 6, 6, 3) instead of clustering at (6, -1, 6, 6, 6, 4).

### Backtest result
**Inherited PENDING/FAILED status from v2.1.0, not independently re-tested.** This does change how the Fundamental category's valuation sub-score is computed, which is exactly the kind of change this file's rule is meant to catch — but the existing backtest already fails on the win-rate criterion for unrelated reasons (Positioning/Sentiment proxy-data limitations, documented in v2.0.0/v2.1.0), and this specific fix was verified by direct computation against real current fundamental data instead, not backtest replay (the backtest's historical fundamentals feed would need its own outlier-exclusion validation separately, which hasn't been done). Per this file's own rule, this version remains ineligible for live trading until a passing backtest is logged — same status as v2.1.0.

### Approved by
MrKoods — 2026-07-16

---

## [v2.1.3] — 2026-07-16 — Fix recurring stale event-gate triggers; log modifiers alongside scores

**Status:** Code updated. Same not-yet-eligible-to-go-live status as v2.1.0/v2.1.1/v2.1.2 — bug fix + logging, no scoring/threshold impact.

### What changed
- `swing_model/news_layer.py`: `compute_news_score()`'s sector-wide critical-event detection now applies the same 5-day recency bar (`news_decay_weight`, `zero_at_days=5.0`) already used for ticker-relevant articles. Previously it checked `all_articles` with no age filter at all, so a stale article could keep matching a sector-wide trigger indefinitely.
- `paper_trading/paper_runner.py`: the per-ticker score log line (added in v2.1.2) now also includes the six shared modifier values (regime, macro, sector_rotation, earnings, cross_ticker, seasonality) and their total, alongside the existing sub-category breakdown.
- `tests/test_event_gate.py`: added `test_stale_sector_wide_article_does_not_retrigger` and `test_recent_sector_wide_article_within_bar_still_triggers` to cover the fix.

### Why it was changed
- Observed directly in production: the same 6-day-old "tariff" headline (Benzinga, 2026-07-10) re-triggered a brand-new sector-wide block on both 2026-07-15 and 2026-07-16, immediately after each prior block's cooling-off expired at post-close. Confirmed via a direct decay calculation that the article was already fully stale (decay = 0.0) yet was still counted as a fresh critical event, because the sector-wide loop never checked article age at all — only the ticker-relevant loop did. Left unfixed, this one headline could have kept re-blocking the entire watchlist every day indefinitely for as long as the news API kept surfacing it.
- Separately: reviewing 2026-07-15/16's paper trading data showed every ticker's score falling in lockstep across the day (e.g., TSM 27.6 → 8.5 → 6.2), which the v2.1.2 score log couldn't explain since it only captured the five per-ticker sub-scores, not the modifiers that get applied identically to the whole watchlist each scan. Logging modifiers alongside scores closes that visibility gap.

### Backtest result
N/A — bug fix + logging change, no effect on scoring, thresholds, or trade selection. The recency-filter fix was verified directly against the real headline/timestamp that triggered the bug (`compute_news_score` now returns zero critical_events for it, confirmed both via unit test and a standalone repro script).

### Approved by
MrKoods — 2026-07-16

---

## [v2.1.2] — 2026-07-15 — Paper trading: log every ticker's score regardless of qualification

**Status:** Code updated. Same not-yet-eligible-to-go-live status as v2.1.0/v2.1.1 — logging-only change, no scoring/threshold impact.

### What changed
- `paper_trading/paper_runner.py`: added an INFO-level log line for every ticker on every scan, showing the full computed score breakdown (technical/positioning/sentiment/news/fundamental sub-totals, final score, direction, and qualifies yes/no) — regardless of whether the ticker clears the 90-confidence threshold.

### Why it was changed
- Reviewing the first full day of paper trading (2026-07-15, 3 scans, 0 qualifying signals) surfaced a real visibility gap: `paper_runner.py` only ever wrote to `paper_trades.csv` for qualifying signals, so on a day where nothing qualified there was no record anywhere of what any ticker actually scored — making it impossible to audit whether the technical/positioning/sentiment/news/fundamental layers were computing sensible values. This closes that gap without changing what surfaces as a signal or how it's scored.

### Backtest result
N/A — logging-only change, no effect on scoring, thresholds, or trade selection.

### Approved by
MrKoods — 2026-07-15

---

## [v2.1.1] — 2026-07-15 — Event Severity Gate changed from veto to advisory flag

**Status:** Code updated. Same not-yet-eligible-to-go-live status as v2.1.0 — see "Backtest result" below; this change does not affect that status either way.

### What changed
- The Event Severity Gate (added in v2.1.0) no longer suppresses a candidate's surfacing when a critical event is active. `swing_model/scoring.py`'s `compute_confidence_score()` — `meets_threshold` is now score-only; `event_gate_blocked` no longer forces it to `False`.
- `swing_model/run_swing_model.py` and `paper_trading/paper_runner.py`: `signal_surfaced` no longer excludes gate-blocked candidates. A qualifying signal on a ticker with an active block now surfaces normally, with a clear warning attached rather than being hidden.
- `notes` field and Discord alerts (`send_trade_alert`, `send_paper_signal_alert` in `shared/utils/discord_alerts.py`) now display an explicit "⚠️ ACTIVE EVENT ALERT" warning (orange embed color, `[ACTIVE EVENT]` title prefix, trigger name, "review before trading") when `event_gate_blocked` is `True`, instead of silently dropping the candidate.
- `paper_trading/paper_trades.csv` gained `event_gate_blocked` / `event_gate_trigger` columns so flagged-but-surfaced paper signals are visible in the dataset (previously blocked signals were never logged at all, so there was nothing to record).
- Block creation, expiry, and cooling-off logic in `shared/utils/event_gate.py` (`add_block`, `is_ticker_blocked`, `expire_blocks`, `has_active_block_for_trigger`) is unchanged — only the consequence of an active block changed, from suppression to advisory annotation.
- Updated `tests/test_event_gate.py`'s `TestScoringEventGateVeto` → `TestScoringEventGateAdvisory` and related docstrings/comments across `event_gate.py`, `news_layer.py`, `run_swing_model.py`, `paper_runner.py` to reflect the new advisory framing.

### Why it was changed
- During initial paper-trading observation, a real live news headline (sector-wide "tariff" trigger) blocked the entire watchlist for a scan. Hard-suppressing every signal under an active critical event hides potentially valid opportunities entirely — the preference is to see every qualifying signal and make an informed judgment call when a critical event is active, rather than have the system make that call unilaterally.

### Backtest result
**Inherited from v2.1.0 — PENDING/FAILED, unaffected by this change.** The last full backtest run (2026-07-15) scored 64.5% win rate against the 80% requirement (avg R:R 1.89, Sharpe 8.92, max drawdown 7.5%, 169 qualifying trades — all other thresholds passed; win rate did not). That shortfall is driven by Positioning/Sentiment proxy-data limitations documented in the v2.0.0/v2.1.0 entries, not by the Event Gate's veto-vs-advisory behavior. The Event Gate contributed zero blocks in that backtest run (the historical dataset has no curated trigger events), so this specific change is not testable by the existing backtest either way, and re-running it would reproduce the identical result rather than validate anything about this change. Per this file's own rule, this version remains ineligible for live trading until a passing backtest is logged — same status as v2.1.0.

### Approved by
MrKoods — 2026-07-15 (paper-trading behavior change; not approved for live trading)

---

## [v2.1.0] — 2026-07-14 — Event Severity Gate added (news veto, not a scoring change)

**Status:** Code and scope document updated. **Not yet eligible to go live — see "Backtest result" below; this follows the same not-yet-validated status as v2.0.0, now compounded by v2.1.0's own backtest limitation.**

### What changed
- Added the **Event Severity Gate** — a binary veto mechanism in the news pipeline, not a sixth scoring category. News keeps its normal 15-point additive scoring for every item unchanged; the gate only suppresses surfacing when a critical, thesis-opposed item is detected. New file: `shared/utils/event_gate.py` (severity classification, thesis-opposed comparison, block-state load/save/add/expire for `data/processed/event_gate_state.json`).
- `swing_model/news_layer.py`: added `classify_severity(item, cfg)` (keyword + source classification against the new `event_severity_gate` config block) and wired `critical_events` detection into `compute_news_score()` — sector-wide triggers checked across all articles, ticker triggers checked against NER-attributed relevant articles.
- `swing_model/scoring.py`: `compute_confidence_score()` gained `event_gate_blocked` / `event_gate_trigger` parameters. When blocked, `meets_threshold` is forced `False` regardless of score — the real `final_score` is still computed and returned in full for the audit log. Verified identical base/final scores blocked vs. unblocked (the gate never alters the score itself).
- `swing_model/run_swing_model.py`: checks `event_gate_state.json` for an existing block before scoring each ticker; after scoring, processes this scan's critical news to create new blocks (thesis-opposed ticker events, or unconditional for sector-wide triggers), logs thesis-aligned critical events without blocking or boosting, fires an immediate critical-priority alert via `notification_router.py` for any open position hit by a critical event (does not wait for the daily re-score), and expires blocks whose cooling-off condition (next post-close scan completing after the event timestamp) is met — excluding blocks created in the same scan run that just created them.
- `shared/utils/discord_alerts.py`: two new alert types — `EVENT_GATE_TRIGGERED` (🚨 red) and `EVENT_GATE_EXPIRED` (ℹ️ grey).
- `shared/utils/notification_router.py`: added `event_gate_critical` to the critical-priority alert type set (email escalation applies).
- `shared/utils/data_validator.py`: added `validate_event_gate_state()` — malformed content repairs to a safe empty/partial state with a warning; blocks older than 5 trading days auto-expire with a warning as a safety net. Never crashes a scan.
- `shared/utils/logger.py`: added `event_gate_blocked` / `event_gate_trigger` columns to `audit_log.csv`. Every gate trigger, suppression, and expiry gets its own audit row.
- `config/swing_config.yaml`: new `event_severity_gate` block (enabled flag, cooling-off mode, sector-wide/ticker trigger lists, principal sources, minimum source credibility, headline-match requirement).
- `Project_Scope.md`: new "Event Severity Gate" subsection in the Swing Trading Model section (after the News/Temporal Alignment material); new alert types added to the Alert Types table; `event_gate_state.json` added to the file structure and Category 2 (Data Risk Mitigations); Quick Reference table updated.
- `tests/test_event_gate.py`: new — 39 tests covering classification, thesis-opposed comparison, block state, expiry/cooling-off, malformed-state auto-repair, news_layer integration, the scoring veto, and the open-position critical alert path.

### Why it was changed
- The five-category additive score has a structural blind spot: News maxes at 15/100, so a severe breaking event can be mathematically outvoted by four slower-moving layers (Technical daily, Positioning daily-to-quarterly, Fundamental weekly) that haven't reacted yet. Existing gates (high-vol regime cap, Black Swan detector, earnings-day block) are price-triggered or lagging — none of them gates on the headline itself before price has moved.
- The gate is deliberately asymmetric (veto only, never a boost) because chasing shock headlines that already confirm a thesis is how a system buys the top of a gap — the goal is loss prevention on the fast-moving downside case, not additional upside chasing.

### Backtest result
**PENDING — not run, and cannot be meaningfully backtested with current data.** The gate can only be replayed against historical news archives that actually contain trigger events (export restriction announcements, CEO resignations, fraud allegations, etc.) within the backtesting window — the existing historical dataset was not curated for this and trigger-list completeness cannot be validated retroactively against events the list wasn't built to anticipate. A future backtest run can measure blocked-candidate outcomes where trigger events did occur in the historical window, but a clean pass there would not certify the trigger list is complete for novel shocks going forward. Per this file's own rule, this version must not be treated as validated for live trading until a passing backtest entry is added below — same PENDING status and same rule as v2.0.0.

### Approved by
Pending — do not go live on this version until the above backtest is run and passes.

---

## [v2.0.0] — 2026-07-13 — Market Positioning + Fundamental categories added; Reddit removed for StockTwits/Seeking Alpha

**Status:** Code and scope document rewritten to match. **Not yet eligible to go live — Phase 12 re-backtest has not been run against this version. See "Backtest result" below.**

### What changed
- Added a new **Market Positioning** category (20 pts): options positioning (put/call ratio + IV skew), institutional ownership change, short interest trend, insider transactions, analyst rating trend. New files: `shared/api_clients/positioning_client.py`, `swing_model/positioning_layer.py`. All sourced free via yfinance.
- **Removed Reddit/PRAW entirely** (no dormant client, no modifier path). Replaced the Sentiment layer's data source with **StockTwits** (explicitly-tagged Bullish/Bearish messages) + a **Seeking Alpha** commentCount engagement proxy, both via a paid RapidAPI subscription (`RAPIDAPI_KEY`). `shared/api_clients/sentiment_client.py` and `swing_model/sentiment_layer.py` rewritten; cross-subreddit consistency and manufactured-spike-detection logic retired (StockTwits' structured tags don't need them).
- **Insider transactions moved from a standalone confidence modifier (±8) into a Market Positioning sub-signal** (0-3 pts) — the two were double-counting the same Form 4 data. `insider_modifier` removed from `compute_confidence_score()`'s signature and from `run_swing_model.py`/`paper_runner.py` wiring.
- Rebalanced all five category weights: Technical 50→40, Positioning —→20, Sentiment 20→15, News 15 (unchanged), Fundamental 15→10 (Fundamental's own internal -15..+15 scale is unchanged; `scoring.py` now rescales its contribution to fit 10 points instead of 15).
- Updated `config/swing_config.yaml` (new `positioning:` block, rebalanced `confidence_scoring:` block, removed `modifier_bounds.insider_activity`) and `config/global_config.yaml` (removed `reddit:` block, added `stocktwits:`/`seeking_alpha:` blocks).
- Updated `discord_alerts.py` signal-breakdown formatting, `data_validator.py` (new `validate_positioning_data()`), `backtest_engine.py` (5-category scoring call, neutral Positioning proxy pending real historical data, rescaled `_BACKTEST_SCORE_MAX`).
- `Project_Scope.md` rewritten to reflect this design — it had never been updated for the Fundamental layer either, so this closes two gaps at once (see the document's own "What Changed From v1.0.0" section).

### Why it was changed
- Reddit's developer app access had stalled indefinitely (submitted 2026-07-07, no auto-approval path), and StockTwits' structured sentiment tagging is a genuine quality improvement over Reddit's keyword-inferred classification, not just an availability fix.
- Options/institutional/short-interest/insider data is a committed-capital signal class the original design never captured — independent of and complementary to sentiment.
- The Fundamental layer had already been built directly in code without ever being reflected in the scope document; this version reconciles that drift.

### Backtest result
**PENDING — not run.** No historical StockTwits or Market Positioning data exists yet (both accumulate forward from this version's first live scan onward, per the same forward-building-history pattern the Fundamental layer already uses). `backtest_engine.py`'s Positioning input is a static neutral proxy and its Sentiment input is a price-momentum proxy — neither is a substitute for a real Phase 12 backtest. Per this file's own rule, this version must not be treated as validated for live trading until a passing backtest entry is added below.

### Approved by
Pending — do not go live on this version until the above backtest is run and passes.

---

## [v1.0.0] — 2026-06-29 — Initial scaffold

**Status:** Scaffolding complete. Phases 1-14 in active development.

### What's in this version
- Full project scaffold per Project_Scope.md
- All 14 build phases stubbed with function signatures
- Configuration: `swing_config.yaml` and `global_config.yaml` with all thresholds
- Scoring formula defined: Technical 60 / Sentiment 25 / News 15 + 7 modifier types
- 42 trade structures defined with EV ranking framework
- Position sizing: 1.0-2.5% risk by confidence tier (90-100)
- Circuit breakers: Yellow 5% / Orange 10% / Red 15% drawdown
- Max 2 simultaneous positions; max 3% total risk; NVDA/AMD correlated pair limit

### What's not yet built
- Real scoring logic (Phase 6)
- Real EV calculations (Phase 7)
- Backtesting (Phase 12)
- Empirically calibrated weights — all weights are hypotheses until Phase 12 passes

### Backtest result
N/A — no backtest run yet. Version 1.0.0 is scaffold-only.

### Approved by
MrKoods — 2026-06-29

---

<!-- Template for future entries:

## [vX.Y.Z] — YYYY-MM-DD — Short description

### What changed
- ...

### Why it was changed
- ...

### Backtest result
- Run date: YYYY-MM-DD
- Historical window: ...
- Train/test split: 70/30
- Qualifying trades (test set): N
- Win rate (test set): X%
- Average R:R (test set): 1:X
- Walk-forward windows: all passed / window N failed
- Approved by: ...

-->
