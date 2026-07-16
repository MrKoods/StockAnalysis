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
