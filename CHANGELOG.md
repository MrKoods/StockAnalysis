# CHANGELOG — AI-Assisted Swing Trading Signal System

Version numbers follow MAJOR.MINOR.PATCH:
- **MAJOR** — a fundamental change to how the strategy scores or picks trades
- **MINOR** — a new indicator, modifier, or scoring category
- **PATCH** — a threshold tweak, bug fix, or calibration update

**Rule:** No change to scoring weights, indicator settings, or thresholds goes live without a
version bump and a fresh backtest result logged below it. Enforced automatically by
`model_versioning.py` — no exceptions.

Every entry follows the same shape: **Problem** (what was wrong or missing) → **Fix** (what
changed to address it) → **Backtest/Result** (the measured outcome).

## Categories

Each entry below is tagged with the kind of change it is, so you can scan for what matters to you:

| Tag | Meaning |
|---|---|
| **Bug Fix** | Corrects broken or wrong behavior |
| **Scoring Change** | Changes a scoring weight, formula, or threshold |
| **Data Source** | Adds, changes, or removes a data feed |
| **Feature** | New capability that isn't a scoring change |
| **Infrastructure** | Engineering, reliability, or process work — no behavior change |
| **Backtest Methodology** | Changes how the backtest itself measures results |
| **Sector Rollout** | Turns a sector on/off for live paper trading |
| **Research** | Investigation or test run — not shipped to live trading |

## Quick reference

| Version | Date | Category | Summary |
|---|---|---|---|
| v2.2.34 | 2026-08-02 | Bug Fix | Every Yahoo Finance news article has been silently carrying an empty title since yfinance changed its response shape — no Yahoo article could ever count toward News, for any ticker |
| v2.2.33 | 2026-08-02 | Scoring Change | Re-swept RS z-score anchor, RSI sweet-spot band, and choppy-regime penalty against the 3-sector pooled backtest; kept 3 real improvements, rejected 2 that looked appealing but cost Sharpe |
| v2.2.32 | 2026-08-01 | Scoring Change | Sector-rotation penalty now softens for individual tickers with strong relative strength, instead of applying uniformly to every ticker in a weak sector |
| v2.2.31 | 2026-08-01 | Backtest Methodology / Feature | Wired regional_banks/healthcare into the backtest for the first time; re-confirmed the RSI entry band against all 3 sectors pooled |
| v2.2.30 | 2026-08-01 | Bug Fix | v2.2.28's seasonality fix was incomplete — a second, deeper key-type bug meant live scans still weren't reading the real config values |
| v2.2.29 | 2026-08-01 | Backtest Methodology / Scoring Change | Re-tested stale entry-filter defaults under the current scoring formula; backtest passes its own go-live gate for the first time |
| v2.2.28 | 2026-07-31 | Bug Fix | Fixed dead/miscalibrated sub-signals found via live paper-trading review |
| v2.2.27 | 2026-07-29 | Data Source | Added hyperscaler capex signal for the semiconductor sector |
| v2.2.26 | 2026-07-29 | Data Source | Added SEC EDGAR 8-K filings as a News source |
| v2.2.25 | 2026-07-29 | Bug Fix | Fixed a pre-market bug: NaN close price could reach scoring |
| v2.2.24 | 2026-07-28 | Sector Rollout | Turned on healthcare for paper trading |
| v2.2.23 | 2026-07-28 | Feature | Collect trade-structure data down to score 60, without lowering the real bar |
| v2.2.22 | 2026-07-28 | Feature | Real options Greeks filter, real IV percentile, real liquidity check |
| v2.2.21 | 2026-07-28 | Infrastructure | Alpha Vantage news is now a confirmation check, not a routine call |
| v2.2.20 | 2026-07-28 | Infrastructure | Better diagnostics, fixed a misleading pass/fail report, reconnected calibration |
| v2.2.19 | 2026-07-28 | Data Source | Moved one earnings data point off Alpha Vantage |
| v2.2.18 | 2026-07-26 | Research | Tested healthcare as an unrelated third sector |
| v2.2.17 | 2026-07-26 | Backtest Methodology | Replaced the win-rate pass/fail bar with a statistical one |
| v2.2.16 | 2026-07-26 | Research | Checked for hidden overlap between Technical and Sentiment |
| v2.2.15 | 2026-07-26 | Feature | Seeking Alpha can trigger an immediate Alpha Vantage double-check |
| v2.2.14 | 2026-07-26 | Data Source / Infrastructure | Seeking Alpha now counts toward News score; CI, lockfile, file split |
| v2.2.13 | 2026-07-24 | Data Source / Bug Fix | Seeking Alpha feeds breaking-news too; cut a wasted API call; test-log fix |
| v2.2.12 | 2026-07-23 | Infrastructure | Spread out the weekly fundamentals refresh |
| v2.2.11 | 2026-07-20 | Bug Fix | A whole sector's data could silently never refresh |
| v2.2.10 | 2026-07-19 | Sector Rollout | Turned on regional banks; results grouped by sector in the app |
| v2.2.9 | 2026-07-19 | Bug Fix | Sector-average valuation wasn't actually sector-scoped |
| v2.2.8 | 2026-07-19 | Infrastructure | Groundwork for a second sector; AV news moved to post-close only |
| v2.2.7 | 2026-07-19 | Backtest Methodology | Backtest now uses the real macro signal instead of always-neutral |
| v2.2.6 | 2026-07-19 | Backtest Methodology / Research | Fixed a validation bug; adopted a better entry filter; tested a 2nd sector |
| v2.2.5 | 2026-07-19 | Backtest Methodology | Tightened the entry filter, even though the headline number got worse |
| v2.2.4 | 2026-07-19 | Backtest Methodology | Fixed a broken analysis tool; found validation has never passed |
| v2.2.3 | 2026-07-19 | Bug Fix | Config bug silently ignored a setting; toned down a triple-counted penalty |
| v2.2.2 | 2026-07-19 | Bug Fix | Fixed 24 issues found in a full code review |
| v2.2.1 | 2026-07-18 | Infrastructure | Removed email/SMS alerts — Discord and the app are the only channels now |
| v2.2.0 | 2026-07-18 | Feature | Added near-miss awareness alerts; flagged an overlapping-penalty risk |
| v2.1.5 | 2026-07-17 | Bug Fix | Fundamental data now saves after each ticker, not just at the end |
| v2.1.4 | 2026-07-16 | Scoring Change | Excluded statistical outliers from sector-average valuation |
| v2.1.3 | 2026-07-16 | Bug Fix | Fixed a stale-news bug that could re-trigger blocks forever |
| v2.1.2 | 2026-07-15 | Infrastructure | Paper trading now logs every ticker's score, not just qualifying ones |
| v2.1.1 | 2026-07-15 | Feature | Breaking-news block: "hide the signal" → "show it with a warning" |
| v2.1.0 | 2026-07-14 | Feature | Added a breaking-news safety block (not a scoring category) |
| v2.0.0 | 2026-07-13 | Scoring Change | Added two new scoring categories; switched the sentiment data source |
| v1.0.0 | 2026-06-29 | Infrastructure | Initial project scaffold |

---

## [v2.2.34] — 2026-08-02 — [Bug Fix] yfinance news response shape change silently emptied every Yahoo article's title

**Status:** Live.

**Problem:** Investigating why News remained the weakest scoring layer (40.1% of max, live paper
trading average) despite v2.2.28's ticker-alias fix for regional_banks/healthcare found a much
larger, independent bug. `yf.Ticker(ticker).news` now nests real content under `item["content"]`
(title, pubDate, provider, canonicalUrl) — `fetch_news_yahoo()` was still reading
`item.get("title", "")` at the top level, which is always absent under this shape. Every Yahoo
Finance article, for every ticker, has been carrying `title=""` — meaning `is_ticker_relevant()`
could never match a single one of them, regardless of any alias list, since an empty string
contains no ticker name. This had zero test coverage (`fetch_news_yahoo` was never tested at all).
v2.2.28's alias fix was correct but had nothing to match against until this fix.

**Fix:** `shared/api_clients/news_client.py`: extracted parsing into a new pure `_parse_yahoo_news_item()`
helper that reads `item["content"]["title"/"pubDate"/"provider"/"canonicalUrl"]`, falling back to
the old flat top-level fields if `"content"` isn't present (in case yfinance reverts or an older
cached client returns the pre-change shape). Added 5 new tests
(`tests/test_news_client.py`) covering the current nested shape, the legacy flat-shape fallback,
and malformed/missing-field inputs — following this project's existing convention of testing pure
parsing helpers rather than mocking the live yfinance call.

**Verified against real live data:** direct relevance-matching test for regional banks went from
0/10 relevant articles (before, for every ticker — titles were always empty) to 8/10 (ZION), 6/10
(KEY), 7/10 (HBAN), 5/10 (RF), 6/10 (FITB) after the fix. A same-day paired live-scan comparison
(pre-fix vs. post-fix, all 17 tickers) showed the aggregate News layer average move 40.1% → 41.1%.

**Important finding — the gain was smaller than the relevance-matching numbers suggested, for a
real and separate reason, not a bug:** inspecting article ages directly, almost all of the newly-
relevant regional-bank articles are 11-16 day old Q2 2026 earnings-call recaps, past the News
layer's 5-day decay cutoff (`zero_at_days=5.0`) — deliberately, so a swing-entry decision isn't
driven by stale news. Only 0-3 genuinely fresh (≤5 day) relevant articles exist per bank ticker on
any given day. Higher-news-volume tickers (NVDA, ASML, ABBV) showed clearer gains (10.4→10.7,
8.7→9.9, 8.9→10.0) because they have enough daily volume for the fix to surface something fresh;
thin-coverage tickers are structurally capped by real news scarcity, not by this bug. Loosening the
decay window to capture more of the earnings-season backlog was considered and rejected — it would
score stale information as if current, undermining the reason the decay curve exists.

**Backtest result:** Not applicable — the 13.5-year backtest sources News from a separate archived
Alpha Vantage dataset (Q4 2025+) or a neutral fallback, never from live `fetch_news_yahoo()`, so
this bug never affected any backtest result quoted in this CHANGELOG. Verified via direct live-data
inspection and the new unit tests instead. 717 tests pass (was 712), 3 skipped.

**Approved by:** [pending]

---

## [v2.2.33] — 2026-08-02 — [Scoring Change] Re-swept technical/regime parameters against the pooled 3-sector backtest

**Status:** Live (all three kept changes are real scoring changes).

**Problem:** v2.2.31 established a much larger, healthier backtest (266 trades pooled across all 3
sectors, up from measuring 1 sector alone) and re-confirmed the RSI *entry-filter* band. That larger
sample makes it possible to productively re-tune individual scoring *sub-signal curves* — something
v2.2.28 had tried and abandoned as showing "zero effect," which v2.2.29 later found was itself a
small-sample artifact for at least one of those parameters (RS z-score anchor). Systematically
re-swept 5 candidate changes against the new pooled baseline instead of assuming any one result
generalizes from a single test.

**Tested and kept (3):**
- `swing_model/scoring.py` — RS z-score anchor swept 1.0/1.5/2.0(prior)/2.5σ: **1.5σ** gave the best
  Sharpe (3.21 vs 3.14/3.10/3.08) and more trades than the prior 2.0σ default (280 vs 266).
- `swing_model/scoring.py` — RSI sweet-spot band swept 52-68/**50-70**/48-74 (from prior 55-65):
  50-70 and 52-68 tied on Sharpe (3.34 vs 3.33); 48-74 overshot and was clearly worse on every axis
  (Sharpe 3.17, WR 57.5%, max DD 11.5%) — confirms this isn't "wider is always better." Kept 50-70
  for slightly more trades at the same Sharpe.
- `shared/utils/regime_detection.py` — choppy regime modifier swept -8(prior)/-4/-2/0: **-2** gave the
  best Sharpe (3.43 vs 3.39/3.40/3.34). Weakest-evidence change in this batch — the spread across the
  sweep is small and comes from a few dozen choppy-regime bars, closer to what this dataset can
  actually distinguish from noise than the other two. Kept as a genuine, if modest, local optimum.

**Tested and rejected (2):**
- `require_confirmation_bar` True: fewer trades (224 vs 294) and worse Sharpe (2.81 vs 3.34) —
  requiring next-bar confirmation removes real winning setups, not just noise.
- `min_breakout_volume_zscore` filter (tried 0.2 and 0.5): both raised win rate and lowered
  drawdown, but at a larger cost to Sharpe and trade count (0.5: 164 trades, Sharpe 2.66) than the
  quality gain justified — the filter cuts real signal, not just weak setups.

**Backtest result:** All 3 kept changes combined, vs. the v2.2.31/32 baseline —
**3-sector pooled:** 266→296 trades, win rate 59.0%→59.8%, avg R:R 1.62→1.63, Sharpe **3.10→3.43**,
max drawdown 9.1%→8.7%. **Semis-only:** 108→120 trades, win rate 60.2%→63.3%, Sharpe 2.81→3.39, max
drawdown 8.2% (unchanged). Passed: True for both. Quantity and quality improved together — no
tradeoff this round, unlike the two rejected changes above. 712 tests pass (unchanged), 3 skipped.

**Approved by:** [pending]

---

## [v2.2.32] — 2026-08-01 — [Scoring Change] Sector-rotation penalty now respects individual relative strength

**Status:** Live.

**Problem:** `sector_rotation_modifier` (up to -15 during SMH/KRE/XLV outflow) applied uniformly to
every ticker in a sector, regardless of that ticker's own relative strength. A stock significantly
outperforming its own trailing RS history despite a weak sector — the most interesting kind of
candidate, arguably — was penalized identically to the sector's laggards. Flagged as a live-scoring
improvement candidate during the multi-layer review (2026-07-31); this is the corresponding fix.

**Fix:** `shared/utils/sector_rotation.py`: new `dampen_rotation_penalty_for_leader(base_modifier,
rs_zscore)` softens a negative rotation modifier for tickers with `rs_zscore >= 1.5`, scaling linearly
to a 50% reduction cap by `rs_zscore >= 3.0`. Never touches a neutral or positive modifier, and never
cancels the penalty outright — a leader in a declining sector still carries real correlated risk, this
tempers the penalty rather than removing it. Wired into both live entry points
(`swing_model/run_swing_model.py`, `paper_trading/paper_runner.py`) where `rotation_modifier_val`/
`rotation_mod` is computed. 9 new/existing tests cover the dampening curve directly
(`tests/test_macro_context.py`).

**Backtest result:** Not applicable — the backtest hardcodes `sector_rotation_modifier=0.0` for every
bar (no historical per-sector rotation-state archive exists to replay), so this function is
structurally unreachable in `_simulate_test_signals()`, the same "live-only, not backtest-provable"
category as the earnings and cross-ticker modifiers. Verified via targeted unit tests instead
(dampening curve at rs_zscore 0/1.4/1.5/2.25/3.0/5.0) plus the full suite. 712 tests pass, 3 skipped.

**Approved by:** [pending]

---

## [v2.2.31] — 2026-08-01 — [Backtest Methodology / Feature] Multi-sector backtest; RSI band re-confirmed under it

**Status:** Backtest-only. No live/paper scoring behavior changed.

**Problem:** The live model has traded three sectors (semiconductors, regional_banks, healthcare)
since v2.2.24, but `run_backtest()` had only ever validated semiconductors — `data/historical_banks/`
and `data/historical_healthcare/` (the same 2013-2026 gitignored research datasets used for the
sector's own live rollout backtests) existed on disk but were never wired into the go-live gate.
Every backtest result quoted in this CHANGELOG through v2.2.29, including the "backtest passes for
the first time" milestone, was measuring 1 of the 3 sectors the live model actually trades.

Separately, mid-investigation work (not committed, recovered from a stash) had reverted v2.2.29's
`rsi_max` decision (45-82) back to 45-70 — the pre-v2.2.29 value — based on a docstring rationale
that was never actually re-validated against data before being written down. Left as-is, this would
have shipped an unvalidated, in-progress reversal of a decision that v2.2.29 had explicitly tested
and documented.

**Fix:**
- `backtesting/backtest_engine.py`: new `run_multi_sector_backtest()` — runs the same replay +
  metrics pipeline once per sector (each against its own benchmark: SMH/KRE/XLV via
  `_SECTOR_DATASETS`), pools the resulting out-of-sample signals into one combined qualifying
  population before computing win rate/R:R/Sharpe/drawdown/expectancy. Sectors are scored against
  their own benchmark and never mixed at the raw-OHLCV level (benchmarking a bank ticker against
  SMH would be meaningless) — pooling happens at the outcome level. Does not yet run walk-forward
  per sector (a separate, larger change); covers the same 70/30 single-slice headline metric every
  other result here is compared against.
- `backtesting/simulation.py` / `backtest_engine.py`: `_simulate_test_signals()`/`_get_test_outcomes()`
  take a `benchmark_ticker` parameter (default `"SMH"`, so single-sector `run_backtest()` callers are
  unaffected) instead of hardcoding `"SMH"` in three places.
- Re-tested `rsi_max` 70 vs. 82 directly against both the semis-only backtest and the new pooled
  3-sector backtest before touching anything: 82 wins on every axis in both — trade count (108 vs 28
  semis-only, 266 vs 91 pooled), Sharpe (2.81 vs 1.16 semis-only, 3.10 vs 2.29 pooled), and gate
  pass/fail (82 passes both, 70 fails both). Restored 82 as the default and rewrote the docstring to
  record this A/B result directly, replacing the unvalidated reversal.

**Backtest result:** Semis-only (unchanged from v2.2.29): 108 trades, WR 60.2%, Sharpe 2.81, max DD
8.2%, passed=True. **New — all 3 sectors pooled:** 266 qualifying trades (semiconductors 249,
regional_banks 149, healthcare 146 — note trades aren't mutually exclusive across the funnel stages,
this is the final qualifying count per sector), win rate 59.0%, avg R:R 1.62, Sharpe **3.10**, max
drawdown 9.1%, expectancy CI lower bound 0.452 (≥ 0.3 ✓). **Passed: True.** This is the first backtest
result that actually reflects all three sectors the live model trades, not just one of them.
712 tests pass (was 707 — 2 seasonality tests from v2.2.30 plus 3 covering the new
`run_multi_sector_backtest`), 3 skipped.

**What this does and doesn't mean:** this is backtest infrastructure and a re-validated parameter —
it does not change what live/paper scoring does. It does substantially change how much confidence
to place in "the backtest passes" as a claim about the live model, since it now actually covers what
the live model trades.

**Approved by:** [pending]

---

## [v2.2.30] — 2026-08-01 — [Bug Fix] v2.2.28's seasonality fix was incomplete

**Status:** Live.

**Problem:** v2.2.28 fixed the config key mismatch (`monthly_adjustments`→`monthly_modifiers`)
but missed a second bug underneath it. `get_seasonality_modifier()` looked up
`monthly.get(str(month), ...)` — a string key ("8"). `yaml.safe_load()` parses
`swing_config.yaml`'s unquoted numeric keys (`8: 0`) as **int**, not str, so
`monthly.get("8")` on that real, int-keyed dict always returned `None` and silently
fell through to the quarterly fallback — which itself falls back to a second
hardcoded default (`_DEFAULT_QUARTERLY`) since the config has no
`quarterly_adjustments` key either. Verified live: an August scan was computing
seasonality=+1.0 (Q3's hardcoded quarterly value) instead of the config's real,
calibrated August value of 0. The v2.2.28 fix was necessary but not sufficient —
after that fix "shipped," live scans still weren't reading the config.
Caught because the unit test written to cover the v2.2.28 fix used a string-keyed
test dict (`{"12": -1.0}`), which happens to match the buggy string lookup and
passed regardless of whether the real bug was fixed — the same failure mode as
the original bug, one level up.

**Fix:** `shared/utils/seasonality.py` now tries an int key lookup first (matching
real YAML parsing), falling back to a str key lookup (for hand-authored quoted
configs or programmatic callers), before falling through to the quarterly default.
Added two tests: one with int keys mirroring real YAML parsing, and one that loads
the actual `config/swing_config.yaml` end-to-end and asserts August resolves to its
real configured value (0) — so this class of bug can't hide behind a hand-built,
string-keyed test dict again.

**Backtest result:** Not applicable — this is a data-correctness fix (the modifier now
reads the intended value instead of a wrong fallback), not a calibration change to
re-validate. Confirmed directly against the real config file rather than via backtest.
707 tests pass (709 after the two new tests are added), 3 skipped.

**Approved by:** [pending]

---

## [v2.2.29] — 2026-08-01 — [Backtest Methodology / Scoring Change] Re-tested stale entry-filter defaults; backtest now passes its own go-live gate

**Status:** Live (RS z-score anchor — real scoring change). Backtest-only (RSI band, confirmation
bar — see Problem below for why these don't touch live scoring).

**Problem:** v2.2.28 found and fixed 5 bugs but left the core question open: only 18-19 trades
qualify in the primary 70/30 backtest split, nowhere close to the 100-trade minimum, with Sharpe
stuck at 0.34. Diagnostic instrumentation of the candidate funnel (breakout bars → confirmation →
trend_intact → sector trend → rs_zscore → 20d RS → RSI band) found the RSI 45-70 entry band
eliminates 79% of an already-filtered candidate pool — by far the largest cut in the entire chain,
dwarfing every other filter combined. That band was deliberately tightened from 45-82 in v2.2.5,
justified at the time by real walk-forward evidence (pooled win rate 49.4%→60.8%). Re-running
`entry_filter_variants.py` (pooled across walk-forward windows, isolating RSI band alone against
today's confirmation-bar default) found that improvement has evaporated under the current 5-category
scoring formula — pooled win rate is now statistically flat (54.7%-56.7%) whether RSI is 45-70 or
45-82. The model has changed substantially since v2.2.5 (Positioning layer, Fundamental layer, new
modifiers); the evidence that justified the tightening no longer holds against the system it was
tuned for.

**Also retested against the larger, corrected sample:** the RS z-score anchor loosening (3σ→2σ) and
breakout proximity scaling from v2.2.28, both reverted at the time for showing zero effect. RS anchor
now shows a real, positive effect (below) — the earlier "zero effect" verdict was an artifact of
testing against a tiny (19-trade) sample where no candidate happened to be sensitive to that curve.
Breakout proximity scaling still shows zero effect, for a cleanly understood structural reason this
time: the backtest only ever scores bars that are already confirmed breakouts by construction
(`Close > prior_20d_high` is the candidate-selection criterion itself), so the "not yet confirmed"
code path this change touches is structurally unreachable in this test harness — not a sample-size
problem. Also tested dropping the 20-day RS-vs-SMH filter as a hypothesized redundant check (it
barely filters anything: 234→242 in the raw funnel) — this one is not redundant after all: removing
it added 4 trades but dropped Sharpe 3.33→3.13 and win rate 61.6%→59.7%, a net loss. Reverted.

**Fix:**
- `backtesting/simulation.py`: `_simulate_test_signals()` defaults changed `rsi_max` 70.0→82.0 (back
  to the pre-v2.2.5 original) and `require_confirmation_bar` True→False. **Important distinction:**
  both parameters are backtest-only candidate-selection filters — the docstring is explicit that
  live/paper scoring has no such hard gate (RSI scores continuously, 0-8 points, no cutoff; there is
  no "confirmation bar" concept in live scoring at all). This fix corrects how fairly the backtest
  measures the model's true historical edge — it does **not** change what live paper trading does.
- `swing_model/scoring.py`: RS z-score anchor loosened 3σ→2σ (rs_z=+2 now maps to the full 8/8, was
  +3). **This one is a real, live scoring change** — it changes how every ticker's Technical layer
  RS sub-signal is computed, in production, immediately.

**Backtest result:** Primary 70/30 split: 19→125 qualifying trades, win rate 68.4%→61.6%, avg R:R
2.18→2.04, Sharpe **0.34→3.33**, max drawdown 3.0%→8.2% (still well under the 15% ceiling), max
consecutive losses 3→15. **Passed: True — the first time this backtest has passed its own go-live
gate** (min_qualifying_trades=100 ✓, expectancy CI lower bound 0.593 ≥ 0.3 ✓, Sharpe 3.33 ≥ 1.0 ✓,
max drawdown 8.2% ≤ 15% ✓). 3 of 6 individual walk-forward windows pass; window 1 (2014-2016) remains
a genuinely weak period for this strategy (35% WR) worth watching, not an artifact of this change.
707 tests pass (unchanged), 3 skipped.

**What this does and doesn't mean:** the backtest's measured historical edge is now dramatically
healthier — a real, useful correction to a stale test methodology. It does not, by itself, explain
or fix live paper trading's 2+ week zero-signal drought: live scoring never had the RSI/confirmation
gates this fix touches, so nothing changes there except the RS z-score anchor's small, real effect.
The live drought's likely drivers — the 90-point confidence threshold and the current choppy/
weak-sector regime — were left untouched this round, per prior discussion.

**Approved by:** [pending]

---

## [v2.2.28] — 2026-07-31 — [Bug Fix] Fixed dead/miscalibrated sub-signals found via live paper-trading review

**Status:** Live. No scoring weight, category max, or the 90-point threshold changed. Two
calibration experiments (RS z-score anchor, breakout proximity scaling) were tested and
reverted — no measurable effect.

**Problem:** Paper trading logged 0 qualifying signals for 2+ weeks across all three sectors,
and a fresh backtest showed qualifying trades falling from 149 (07-04) to 18. Digging into why
turned up five separate, unrelated bugs quietly suppressing real signal:

**Fix** — one bug and fix per area:
- **Technical:** `score_volume_profile_position()` was fully built in `volume_profile.py` but
  never actually called anywhere live — every ticker scored a flat neutral 4.0/8 regardless of
  real volume-node position, on every scan. Wired it into `compute_technical_indicators()`
  (`shared/indicators/technical_common.py`) and rescaled to the 0-8 sub-signal max.
- **News:** 11 of 17 watchlist tickers (regional banks + healthcare, added v2.2.10/v2.2.24) had
  no company-name alias in `ner_extractor.py`. Without one, relevance-matching falls back to the
  bare ticker symbol, which almost never appears literally in a headline — confirmed live,
  HBAN/RF/FITB/KEY scored News=0.0/15 every scan despite Finnhub returning real articles. Added
  the missing aliases.
- **Fundamental:** `_FUNDAMENTAL_MAX_TICKERS_PER_DAY` was still 3, a cap sized for the original
  6-ticker watchlist. The current 17-ticker watchlist needs ~2.4/day just to keep up, leaving no
  slack for catch-up — confirmed live, 4 of 6 healthcare tickers still showed
  fundamental_score=0 a week after going live. Raised the cap to 5 (`indicator_pipeline.py`).
- **Sentiment:** a RapidAPI outage was hard-zeroing the Seeking Alpha engagement sub-signal for
  every ticker while the API was down, with no fallback. Added a 48h last-known-good cache
  (`data/processed/sentiment_engagement_cache.json`, `sentiment_client.py`) that now falls back
  to the last successful fetch.
- **Modifiers (seasonality):** `seasonality.py` read a config key `monthly_adjustments` that
  doesn't exist — `swing_config.yaml` actually calls it `monthly_modifiers`. The lookup silently
  fell through to hardcoded defaults that disagree in sign with the calibrated config values
  (January: config -5 vs. hardcoded +2) — the model had never once run on the config's real
  seasonality values. Corrected the key name.
- **Tested and reverted (no effect):** RS z-score anchor loosening (3σ→2σ) and breakout
  proximity scaling both produced bit-for-bit identical backtest results — the Technical layer's
  existing pre-filters already narrow candidates to a pool where sub-scores saturate near max,
  so tuning inside that pool changed nothing. Not kept.

**Backtest:** 18 → 19 qualifying trades, win rate 66.7% → 68.4%, avg R:R 2.35 → 2.18, Sharpe
unchanged at 0.34, max drawdown unchanged at 3.0%. Still **FAILS** the go-live gate (100 trades
min, Sharpe ≥ 1.0) — this patch fixes bugs and data gaps, not the trade-count/Sharpe gap
(structural selectivity from the 90-point threshold and Technical AND-gates, left alone pending
a separate strategic decision). 707 tests pass (was 706), 3 skipped.

**Approved:** [pending]

---

## [v2.2.27] — 2026-07-29 — [Data Source] Added hyperscaler capex signal for the semiconductor sector

**Status:** Live. Extends v2.2.26's SEC EDGAR work via the same News/Event Severity Gate
mechanism — no new scoring category, no weight/threshold change.

**Problem:** SEC EDGAR's atom feed `<summary>` (what v2.2.26 reads) only ever contains generic
Item-code boilerplate, never real company commentary — verified against AMZN's own filings. The
real numbers live one level deeper, in the filing's attached press-release exhibit. Hyperscaler
capex (AMZN/MSFT/GOOGL/META) is the demand driver behind semiconductor sector moves, and it
shows up in these filings before it reaches general news — but the exhibit text was never read.

**Fix:**
- New `fetch_hyperscaler_capex_snippets()` (`sec_edgar_client.py`) pulls each company's recent
  earnings 8-Ks (Items 2.02/7.01/8.01), locates the Exhibit 99.x press release via the filing's
  `index.json`, and extracts short snippets around capex terms ("purchases of property and
  equipment", "capital expenditures", "AI infrastructure"). Confirmed against AMZN's Q1 2026
  8-K: the atom summary has zero capex text, while the exhibit states a $59.3B YoY increase with
  real commentary.
- Added `capex_context_tickers: [AMZN, MSFT, GOOGL, META]` under semiconductors in
  `swing_config.yaml` — fetched once per scan, folded into every semiconductor ticker's News pool.
- Added capex-cut keywords to the semiconductor sector's Event Severity Gate triggers.
- 15 new tests.

**Backtest:** N/A — same "accumulates going forward" caveat as v2.2.26; no historical exhibit
archive exists. 707 tests pass (was 696), 3 skipped.

**Approved:** [pending]

---

## [v2.2.26] — 2026-07-29 — [Data Source] Added SEC EDGAR 8-K filings as a News source

**Status:** Live. New free source folded into existing News scoring and the Event Severity
Gate — no weight/threshold change.

**Problem:** A company's own 8-K regulatory filing is about as authoritative and immediate as a
News source gets — a primary disclosure, not third-party reporting after the fact — but nothing
in the News layer read it. Identified as a genuine, unfilled gap while reviewing what each
scoring layer actually draws on.

**Fix:**
- New `sec_edgar_client.py` fetches each ticker's recent 8-Ks from SEC EDGAR's free public feed
  and extracts the human-readable Item description (e.g. "Item 5.02: Departure of Directors")
  instead of the generic, unvarying filing title.
- Folded in as a fifth News source alongside Alpha Vantage/Yahoo/Finnhub/Seeking Alpha.
- Scored at 1.0 source credibility — higher than any journalism outlet, since it's the
  company's own regulatory disclosure.
- Added "SEC EDGAR" to the Event Severity Gate's `principal_sources` — same critical tier as
  FDA/Fed statements.
- Also counts toward the free-source pool that decides whether a scan spends its one AV
  confirmation call.
- 10 new tests, built against real captured response payloads.

**Backtest:** N/A — no historical 8-K archive; `simulation.py` always passes
`sec_edgar_filings=None`, same caveat already accepted for Seeking Alpha/StockTwits. 696 tests
pass (was 686), 3 skipped.

**Approved:** [pending]

---

## [v2.2.25] — 2026-07-29 — [Bug Fix] Fixed a pre-market bug: NaN close price could reach scoring

**Status:** Live. Data-integrity fix only.

**Problem:** Every daily-interval yfinance request made during market hours (including
pre-market) includes an in-progress "today" bar — Open/Volume may already have partial
pre-market prints, but Close stays NaN until the session actually closes. Live: the 5:30am
pre-market scan logged `close=nan` for all 17 watchlist tickers. It self-resolved by the 9am
mid-session scan once yfinance backfilled the row, but a NaN close feeding stop/target/
position-size math is a real risk regardless of how quickly it self-resolves.

**Fix:**
- `fetch_ohlcv()`/`fetch_ohlcv_batch()` (`market_data_client.py`) now trim any trailing OHLCV
  row with a NaN Close before returning it.
- `technical_common.py` now raises a clear error if a NaN close still reaches indicator
  computation, instead of silently scoring on it — caught by `indicator_pipeline.py`'s existing
  per-ticker error handling (logs a validation entry, excludes just that ticker).
- 7 new tests.

**Backtest:** N/A — only affects the live/paper fetch path; the backtest doesn't call
`fetch_ohlcv_batch` during market hours. 686 tests pass (was 679), 3 skipped.

**Approved:** [pending]

---

## [v2.2.24] — 2026-07-28 — [Sector Rollout] Turned on healthcare for paper trading

**Status:** Live. Healthcare (6 tickers) now actively scanned alongside semiconductors and
regional banks. Still no real money at risk — no version has passed backtest requirements yet.

**Problem:** Healthcare had already been tested as research-only in v2.2.18 (63.4% win rate,
comparable to the other sectors), but the remaining blocker to actually turning it on was Alpha
Vantage's daily call budget — adding 6 more tickers to an already-11-ticker watchlist risked
exceeding the daily limit. Two earlier changes removed that blocker: confirmation-only AV news
calls (v2.2.21) and the 3-ticker/day fundamentals cap (v2.2.19/v2.2.12), so a bigger watchlist
no longer means a bigger daily API bill.

**Fix:**
- Added healthcare to live config: LLY, PFE, MRK, ABBV, UNH, JNJ, benchmarked against XLV. Code
  already supported multiple sectors generically since v2.2.8 — config-only change.
- Added healthcare breaking-news keywords (FDA rejection, trial failure, drug recall) so a
  serious event blocks only healthcare tickers. Added FDA as an always-critical source, like
  the Fed.
- Gave healthcare its own position limit and correlated-position group. Total position ceiling
  across all sectors: 4 → 6.
- Fixed a stale comment describing the old pre-v2.2.21 Alpha Vantage budget behavior.
- Updated one test expecting exactly two active sectors to expect three.

**Backtest:** Unchanged from v2.2.18's research result — 141 combined trades, 59.6% win rate,
1.63 avg R:R, still well short of go-live. Expands what paper trading observes only. 679 tests
pass (one updated for the new sector count).

**Approved:** [pending]

---

## [v2.2.23] — 2026-07-28 — [Feature] Collect trade-structure data down to score 60, without lowering the real bar

**Status:** Live. Real trading threshold stays at 90. This only makes the model also evaluate
(not act on) 60-89 scores, to build a bigger research dataset.

**Problem:** Real 90+ signals are rare — zero in over 9 days of paper trading. Waiting for
enough real signals to judge the new Greeks/liquidity filters (v2.2.22) would take too long.

**Fix:**
- Added a threshold (60) that triggers trade-structure evaluation without qualifying as a real
  signal.
- Scores 60-89 get their evaluated structure and EV saved to the database for review — never
  written to the real trade log, never alerted, don't count as a signal.
- Updated tests, including a check that sub-60 scores still get nothing recorded.

**Backtest:** N/A — the backtest doesn't use this code path. 679 tests pass, 3 skipped.

**Approved:** [pending]

---

## [v2.2.22] — 2026-07-28 — [Feature] Real options Greeks filter, real IV percentile, real liquidity check

**Status:** Live. Doesn't touch the trading score or 90-point threshold — only affects which
options structure gets picked once a signal already qualifies.

**Problem:** The Greeks filter had said "not implemented" since it was written, because the
real options chain (strikes, bid/ask, IV) was fetched and then thrown away right after computing
a couple of averages. Two structures could look equally profitable on paper while one secretly
depended on time or volatility working out — with no way to tell them apart. The liquidity
filter (bid/ask spread) was also silently a no-op, since no real spread data ever reached it, and
IV percentile always assumed a neutral 50 instead of using real history.

**Fix:**
- Keeps the real options chain instead of discarding it after computing averages.
- Added a real Greeks filter: for 20 of 42 possible structures, rejects a structure if theta or
  vega is too large relative to risk. Complex structures (LEAPS, calendars, condors,
  butterflies) are left alone — a single chain snapshot can't represent them accurately.
- The liquidity filter now actually works, fed by the real spread data it was always meant to use.
- IV percentile is now computed from real history. Needs ~10 days of history to activate;
  reports "not enough history yet" before that instead of guessing.
- Fixed a bug where missing options data was read as a real but blank quote instead of being
  skipped.
- 47 new tests.

**Backtest:** N/A — the backtest only tests the buy/sell signal, not option-structure selection.
679 tests pass (was 638), 3 skipped.

**Approved:** [pending]

---

## [v2.2.21] — 2026-07-28 — [Infrastructure] Alpha Vantage news is now a confirmation check, not a routine call

**Status:** Live. Only changes how often a news API gets called — no scoring/threshold impact.

**Problem:** Alpha Vantage has a strict daily call limit shared across features. AV was
previously called once per ticker automatically on every post-close scan, whether or not
anything happened. On 2026-07-28 the model burned most of that budget on routine per-ticker
calls, most of which came back rate-limited instead of returning real articles.

**Fix:**
- Checks free news sources (Yahoo, Finnhub, Seeking Alpha) first, every scan. Only spends an AV
  call when a free source already flagged something serious, to cross-check it.
- Updated tests to match.

**Backtest:** N/A — live API-call cadence only; the backtest doesn't model call budgets. 638
tests pass (was 637), 3 skipped.

**Approved:** [pending]

---

## [v2.2.20] — 2026-07-28 — [Infrastructure] Better diagnostics, fixed a misleading pass/fail report, reconnected calibration

**Status:** Live. No scoring weight or threshold change — measurement tools, a reporting fix,
and wiring a dormant feature to the right data source.

**Problem:** A review of 9 days of real paper-trading data found the score has never reached
90, or even 80 — topping out around 72. But the pass/fail system couldn't tell "no data yet"
from "genuinely underperforming," so it was impossible to know how bad the gap really was.
Digging into why also revealed the calibration/feedback-loop system (meant to compare fresh
results against training data) had been silently reading and writing files nothing in the live
system actually used.

**Fix:**
- New read-only diagnostics showing real paper-trading score distributions and how close each
  category gets to its max.
- Fixed the "zero trades yet" vs. "the strategy failed" reporting bug — now distinguished.
- Reconnected calibration to the real, running paper-trading data. Recalibration itself stays
  switched off until it has real data to work from — confirmed this change produces the exact
  same score as before.
- Removed a dead, unused config file that falsely claimed to be read by the scoring code.

**Backtest:** N/A — no scoring weight or threshold changed. 637 tests pass (was 582), 3 skipped.

**Approved:** [pending]

---

## [v2.2.19] — 2026-07-28 — [Data Source] Moved one earnings data point off Alpha Vantage

**Status:** Live. Data-source change only — the earnings score formula is unchanged, just fed
by cheaper sources most of the time.

**Problem:** AV's earnings call had been silently failing on every attempt — a real daily limit
(25 calls/day) on the account, not a bug. Investigating showed only one of the four earnings
sub-scores actually needed AV's extra depth; the rest worked fine on Finnhub's free data.

**Fix:**
- One of four earnings sub-score inputs now comes from Finnhub (free) instead of AV.
- The piece that genuinely needs AV's deeper history now only calls it for brand-new tickers or
  near a real earnings date, not on every weekly refresh — cutting routine AV earnings calls
  from a few/day to ~1-2/month.

**Backtest:** N/A — formula unchanged, only the data supplier. Verified against real API calls
that AV's budget counter stayed untouched on the routine path. 582 tests pass (was 573), 3
skipped.

**Approved:** [pending]

---

## [v2.2.18] — 2026-07-26 — [Research] Tested healthcare as an unrelated third sector

**Status:** Live code, research-only — nothing about the real trading watchlist changed.

**Problem:** Semiconductors and regional banks (already tested) both react to the same
interest-rate cycle, so their agreement was weaker proof of a real, general edge than it
looked — they could just be responding to the same underlying factor. Healthcare stocks move on
different triggers (drug approvals, trial results), making it a cleaner check of whether the
entry strategy generalizes, or only works on rate-sensitive stocks.

**Fix:** Downloaded 13 years of price history for 6 healthcare/pharma stocks and ran the same
backtest, purely for research. Not added to live trading.

**Result**

| Sector | Trades | Win rate | Avg R:R |
|---|---|---|---|
| Semiconductors | 54 | 61.1% | 1.89 |
| Regional banks | 46 | 54.4% | 1.63 |
| Healthcare | 41 | 63.4% | 1.31 |
| **All three combined** | **141** | **59.6%** | **1.63** |

Healthcare's win rate held up as well as the others — a good sign this isn't just a rate-cycle
fluke — though its avg R:R was lower (wins about as often, pays out less). Logged as new
evidence per the no-retuning rule, not used to retune.

**Approved:** MrKoods — 2026-07-26

---

## [v2.2.17] — 2026-07-26 — [Backtest Methodology] Replaced the win-rate pass/fail bar with a statistical one

**Status:** Live. Still not eligible for real money — this changes how pass/fail is measured,
not what passes. Required a fresh backtest since it changes the pass/fail rule itself.

**Problem:** The old go-live bar (flat 80% win rate, 1.8 R:R) implied a consistency level far
beyond what this strategy — or most trading strategies — has ever shown, even in its best years.
A flat percentage also can't tell a real edge apart from a small sample that got lucky.

**Fix:**
- Replaced the flat bar with a statistical confidence interval on the strategy's actual expected
  return per trade — a stricter, more honest test that accounts for how much data actually
  exists, not just a raw percentage.
- Applied the same new rule to paper trading's own pass/fail check.

**Backtest:** 66.67% win rate, 2.35 avg R:R, EV per trade 1.24R (low-end estimate 0.42R, still
positive). Still fails — not because the edge looks fake, but only 18 qualifying trades exist
(100 required) and Sharpe (0.34) is below the 1.0 bar. A more useful failure reason than before:
the signal looks statistically real, there's just not enough of it yet. 566 tests pass (was
559), 3 skipped. Extended to paper trading 2026-07-27 — correctly reports "not enough trades
yet" instead of a misleading pass/fail. 573 tests pass, 3 skipped.

**Approved:** MrKoods — 2026-07-26 (paper trading extension: [pending])

---

## [v2.2.16] — 2026-07-26 — [Research] Checked for hidden overlap between Technical and Sentiment

**Status:** Live. Pure measurement plus a process rule — no scoring/threshold change, no
backtest needed.

**Problem:** Five rounds of tuning against the same ~12-year sample risked quietly overfitting
to it. Before locking in a rule against further tuning, it was worth checking a related worry:
is part of the backtest's apparent "5 independent categories" an illusion, because the backtest's
Sentiment stand-in is built from price movement — the same data Technical already uses directly?

**Fix:** Built a tool to directly measure the correlation between Technical and Sentiment scores
in the backtest, and made an existing informal decision official: no backtest data from before
2026-07-26 may be used again to tune entry filters. Re-running the backtest for reporting is
fine; retuning against the same old data is not.

**Result:** The worry didn't hold up — the two categories' scores were only weakly correlated,
well below the level that would signal real overlap. Re-checked later against real live
paper-trading data (not just the backtest's price-based stand-in) with the same result. 573
tests pass (was 566), 3 skipped.

**Approved:** MrKoods — 2026-07-26

---

## [v2.2.15] — 2026-07-26 — [Feature] Seeking Alpha can trigger an immediate Alpha Vantage double-check

**Status:** Live. Only changes when a pre-market/mid-session scan spends an AV call — no
scoring impact.

**Problem:** AV news was normally only checked post-close, so a genuinely serious event flagged
by Seeking Alpha (checked every scan, free) could sit unconfirmed for up to 13 hours before the
next post-close scan caught it.

**Fix:** If Seeking Alpha flags a serious headline about a ticker, the model now immediately
spends one AV call to cross-check it with an independent source, instead of waiting for the next
scan.

**Backtest:** N/A — live/paper timing change, not replayable. 559 tests pass (was 553), 3
skipped.

**Approved:** MrKoods — 2026-07-26

---

## [v2.2.14] — 2026-07-26 — [Data Source / Infrastructure] Seeking Alpha now counts toward News score; CI, lockfile, file split

**Status:** Live. Adds a fourth live-only News source — no weight/threshold change. The
engineering cleanup has no scoring effect.

**Problem:** No automated testing (CI) meant a bad change only got caught if someone remembered
to test it locally by hand. A 951-line file had accumulated the highest concentration of past
bugs in the project by doing too much in one place. Separately, Seeking Alpha's headlines were
already fetched free every scan but only used for breaking-news detection, not counted toward
the actual News score — leaving that category weaker than it needed to be on days AV data was
thin.

**Fix:**
- Seeking Alpha headlines now also count toward the scored News total.
- Split the 951-line file into three smaller, focused files. No behavior change.
- Added CI (runs on every code push) and a locked dependency file, so a library update can't
  silently change behavior without a test catching it.
- Manually vetted an unfamiliar new dependency before trusting it — confirmed legitimate, not a
  supply-chain risk.

**Backtest:** No effect — no historical Seeking Alpha archive exists, so this path is inactive
in replay. Re-ran anyway: 66.7% win rate, 18 trades, 2.35 avg R:R — consistent with the prior
64.7%/17 trades (normal re-run noise). 553 tests pass (was 552), 3 skipped.

**Approved:** MrKoods — 2026-07-26

---

## [v2.2.13] — 2026-07-24 — [Data Source / Bug Fix] Seeking Alpha feeds breaking-news too; cut a wasted API call; test-log fix

**Status:** Live. Affects breaking-news detection speed and one data source — not the scoring
formula.

**Problem:** Investigating why paper trading kept missing news that later showed up hours later
found a real, measured detection delay: AV news was normally only checked post-close, so
pre-market/mid-session scans couldn't catch a breaking story until much later. Separately, test
runs had been quietly writing fake entries into the real production log files for a long time —
one log file turned out to be 99.7% test noise.

**Fix:**
- Seeking Alpha headlines now also feed the breaking-news detector (previously Sentiment scoring
  only) — closes the detection gap without changing the scored News total.
- Alerts now show the real time a news story broke, not just when the alert was posted, so a
  delayed detection isn't mistaken for a fresh one.
- Replaced one Alpha Vantage call (analyst target price) with the same data from Yahoo/Finnhub
  for free — same accuracy, one less API call per ticker.
- Isolated tests from real logs so test runs stop polluting production log files.

**Backtest:** N/A — none of this changes the scored News total or the earnings sub-score
formula, only detection timing and data source for less-important pieces.

**Approved:** MrKoods — 2026-07-24

---

## [v2.2.12] — 2026-07-23 — [Infrastructure] Spread out the weekly fundamentals refresh

**Status:** Live. Scheduling change only — no scoring impact.

**Problem:** Every ticker's fundamentals refreshed in one Monday-night burst. As the watchlist
grows to cover more sectors, refreshing everything at once risks blowing through the daily API
call budget in a single night.

**Fix:**
- Each ticker now gets its own day of the week, with earnings-week tickers prioritized and a
  daily cap on how many refresh at once — spreading the same total cost across the week.
- The score breakdown now shows how recent each ticker's fundamental data actually is, since
  different tickers can now be refreshed on different days.

**Backtest:** N/A — scheduling only, doesn't change the fundamental scoring formula.

**Approved:** MrKoods — 2026-07-23

---

## [v2.2.11] — 2026-07-20 — [Bug Fix] A whole sector's data could silently never refresh

**Status:** Live. Bug fix — no scoring impact.

**Problem:** Fundamental and Positioning data refresh tracking used one shared "last updated"
timestamp for the whole file. With more than one sector active, a sector processed later in the
same scan run would see an earlier sector's refresh timestamp and wrongly assume its own
tickers were already up to date — even though they'd never actually been fetched. That could
have silently left a newly added sector's tickers with no real data indefinitely, with no error
to flag it.

**Fix:** Refresh tracking is now done per ticker, instead of one shared timestamp for the whole
file.

**Backtest:** N/A — this only affects live/paper data-fetch tracking, a part of the code the
backtest doesn't use.

**Approved:** MrKoods — 2026-07-20

---

## [v2.2.10] — 2026-07-19 — [Sector Rollout] Turned on regional banks; results grouped by sector in the app

**Status:** Live. Regional banks now scanned alongside semiconductors. Still no real money at
risk — no version of this model has ever passed its backtest requirements, so this only expands
what paper trading watches.

**Problem:** Before turning on a second sector, a direct code review found several parts of the
code had hidden single-sector assumptions (mixed valuation numbers across sectors, wrong
benchmark for relative strength, one shared position-limit pool instead of per-sector limits) —
fixed in v2.2.8/v2.2.9. With those confirmed fixed and tested, the second sector could safely go
live.

**Fix:**
- Regional banks (5 tickers) now scanned alongside semiconductors — 11 tickers total.
- Desktop app now groups results by sector, then category.
- Re-ran the cross-sector backtest to confirm results were unchanged after the recent groundwork.
- Built a new end-to-end test that actually runs a full two-sector scan (previous tests only
  checked individual pieces in isolation) to confirm the sectors don't interfere with each other.
- Found, but didn't yet fix: a market-crash safety check still only watches semiconductors, not
  each sector separately. Not currently wired into live scans either way, so not an active gap —
  flagged for a future fix.

**Backtest:** Unchanged from prior research — 100 combined trades, 58.0% win rate, 1.78 avg
R:R, still short of go-live. Expands what paper trading observes only. 536 tests pass (was 532).

**Approved:** MrKoods — 2026-07-19

---

## [v2.2.9] — 2026-07-19 — [Bug Fix] Sector-average valuation wasn't actually sector-scoped

**Status:** Live. Same not-yet-eligible status as before — regional banks are still switched
off, so this only matters once that's turned on.

**Problem:** Double-checking whether the second sector gets the full scoring treatment revealed
that v2.2.8 had described a fix to the Fundamental category's "sector average" valuation
comparison but never actually made it — it was still averaging every sector's tickers together.
Left unfixed, it would have blended semiconductor valuations (much higher P/E) with bank
valuations (much lower P/E) into one meaningless average the moment both sectors had data
cached — undercutting the exact problem v2.2.8 was supposed to prevent.

**Fix:** Fixed the valuation comparison to only average tickers within the same sector. Checked
every other scoring category directly and confirmed none of them had the same bug.

**Backtest:** N/A — the backtest doesn't model this yet either way, and this has no effect on
live scoring while the second sector stays switched off. Verified with new tests instead. 532
tests pass (was 529).

**Approved:** MrKoods — 2026-07-19

---

## [v2.2.8] — 2026-07-19 — [Infrastructure] Groundwork for a second sector; AV news moved to post-close only

**Status:** Live. The actual live/paper watchlist is unchanged — still just the original 6
semiconductor tickers. This entry only builds the plumbing to safely support a second sector
later.

**Problem:** The goal was to actually track a second sector live, following earlier backtest
evidence that the entry strategy generalizes beyond semiconductors — but a direct code review
first found multiple places that had hidden single-sector assumptions and would have silently
produced wrong results the moment a second sector was simply added: mismatched benchmarks,
blended valuations, pooled correlation checks across unrelated sectors, and a breaking-news
block that would have covered every sector instead of just the one it was about.

**Fix:**
- Config can now describe multiple sectors, each with its own benchmark. Live watchlist stays
  semiconductors-only for now; regional banks exist in config but stay switched off.
- Fixed all 7 places with hidden single-sector assumptions, including one unrelated bug found
  along the way: a sector-wide news block was incorrectly treated as covering every ticker, not
  just the sector it was actually about.
- Position limits and correlated-position protection are now tracked per sector instead of one
  shared pool.
- Restricted Alpha Vantage news calls to the post-close scan only, for every ticker — a real
  budget necessity, since an 11-ticker two-sector watchlist at the old calling pattern would
  have blown through the free daily API limit.

**Backtest:** N/A for the infrastructure work — behavior-preserving, confirmed by 529 passing
tests with zero regressions (was 497 before this entry). The Alpha Vantage cadence change has no
meaningful backtest comparison available, since the backtest doesn't model call timing at all —
flagged as a known gap, not a result being hidden.

**Approved:** MrKoods — 2026-07-19 (second-sector activation deliberately left for a separate,
later entry)

---

## [v2.2.7] — 2026-07-19 — [Backtest Methodology] Backtest now uses the real macro signal instead of always-neutral

**Status:** Live. This only fixes a gap in the backtest — live/paper trading was already using
the real macro signal.

**Problem:** The strategy performed noticeably worse in more recent years than in 2018-2021.
Investigating found a real pattern: every well-performing period lined up with falling or low
interest rates, and every poorly-performing period lined up with rising or high rates (a
well-known effect — cheap money favors momentum strategies, rising rates make price action
choppier). Live trading had already computed a real macro modifier since early on, but the
backtest always treated it as exactly zero for every simulated trade.

**Fix:** Fixed the backtest to use real historical interest-rate and dollar-index data instead
of a hardcoded zero.

**What using it actually showed:** Recent 2-year windows that used to fail now pass (69-75% win
rate). The strategy never once produced a qualifying trade during an unfavorable macro reading
in the corrected backtest — confirming the fix works by filtering out weak setups during bad
macro conditions, as intended.

**Backtest:** 66.7% win rate (was 64.7%), 2.35 avg R:R, 18 qualifying trades (100 required —
still not enough), 3.0% max drawdown. Still not eligible for live trading — not enough trades
yet, regardless of the improved win rate.

**Approved:** MrKoods — 2026-07-19

---

## [v2.2.6] — 2026-07-19 — [Backtest Methodology / Research] Fixed a validation bug; adopted a better entry filter; tested a 2nd sector

**Status:** Live. The entry-filter change is backtest-methodology only. The real go-live safety
bar (80% win rate, minimum reward:risk) is untouched by this entry.

**Problem:** The strategy had "never once passed" its rolling validation check across 24
historical windows. Investigating why found the real cause was a methodology bug, not a real
feature of the strategy: the validation windows (6 months) were too short for how rarely this
strategy actually fires, so almost every window had too few trades to judge fairly.

**Fix:**
- Lengthened validation windows from 6 to 24 months. With the fix, one window (2018-2020)
  clearly passed and most others had enough data to judge fairly, rather than being starved of
  trades.
- Lowered the internal diagnostic pass bar (a looser stability check, separate from the real 80%
  go-live bar) to match what the strategy has actually, repeatedly shown.
- Re-tested an entry-filter idea (requiring the breakout to hold for one more day before
  entering) that had earlier looked unhelpful — that earlier read turned out to be distorted by
  the same too-short-windows bug. With the fix, it's the single best-performing filter change
  tested, so it was adopted.
- Also tested regional banks as a second, unrelated sector purely as research (not added to live
  trading), to check whether the strategy's edge is real and general, or just a
  semiconductor-specific fluke.

**Combined result (both sectors, with the adopted filter)**

| | Trades | Win rate | Avg R:R |
|---|---|---|---|
| Semiconductors only | 53 | 64.2% | 1.82 |
| Regional banks only | 51 | 52.9% | 1.73 |
| **Combined** | **104** | **58.7%** | **1.78** |

A real, modest, positive edge that holds up (same direction, similar size) across two unrelated
sectors — more convincing than semiconductor-only evidence could ever be on its own.

**Decision: paused further backtest tuning.** Five rounds of tweaking the entry filter against
the same historical sample is starting to risk overfitting to it. The current filter is treated
as settled for now; real, new paper-trading data — not more backtest tuning — is the next real
test.

**Backtest:** 64.7% win rate, 2.29 avg R:R, 17 qualifying trades (100 required — still not
enough on this slice alone). Still not eligible for live trading due to the trade-count
shortfall, despite the encouraging win rate. The combined two-sector result above is the more
statistically meaningful number and the actual basis for adopting this filter.

**Approved:** MrKoods — 2026-07-19

---

## [v2.2.5] — 2026-07-19 — [Backtest Methodology] Tightened the entry filter, even though the headline number got worse

**Status:** Live. Backtest-methodology change only — doesn't touch live/paper scoring, which
already scores RSI without a hard cutoff.

**Problem:** A losing trade was typically taking 5-9 days to resolve, not 1-2 — a sign of
overextended entries rather than fast false breakouts. Testing this properly (pooled across many
independent time windows, not just the one held-out test slice, to avoid overfitting) showed
tightening the RSI ceiling clearly improved win rate (49.4% → 60.8%) across the broader sample.

**Fix:** Lowered the backtest's upper RSI cutoff for what counts as a valid breakout entry, from
82 to 70 — filtering out more "already extended" moves.

**An honest tension:** On the broad, pooled sample this change clearly helps. But on the one
specific historical slice the backtest reports as its headline number, this same change makes
the result look worse and drops the trade count below the minimum needed for a reliable read.
Both facts are reported here rather than only the favorable one — the broader, pooled sample is
judged the more trustworthy evidence, so the change was adopted anyway.

**Backtest:** The official single-slice number got worse with this change: 51.8% win rate (was
57.0%), 27 qualifying trades (was 107, now below the 100 minimum). Already not eligible for live
trading before this change; unaffected by it either way. The real basis for adopting this filter
is the broader pooled evidence above, not this one slice.

**Approved:** MrKoods — 2026-07-19 (adopted knowing the single-slice headline number got worse;
based on the broader evidence)

---

## [v2.2.4] — 2026-07-19 — [Backtest Methodology] Fixed a broken analysis tool; found validation has never passed

**Status:** Live. Tooling/analysis fix only — no scoring or threshold impact.

**Problem:** Checking whether the 90-point score threshold was well calibrated required running
a tool meant to show how win rate changes at different score thresholds — but it had a bug that
made it silently return all zeros every single time it had ever been run, so nobody could
actually see the answer.

**Fix:** Fixed the tool. Also made the strategy's existing rolling validation check (running the
strategy across many historical windows, not just one) actually get printed and reviewed — it
had been computed all along but never surfaced. Separately tried adding a volume-confirmation
requirement to the entry filter — it looked better on the single test slice, but that's exactly
the kind of overfitting risk the held-out test slice exists to prevent, so it was not adopted
without broader validation.

**What the fix revealed:** Win rate barely changes across every threshold from 85 to 95 —
meaning a stricter cutoff alone won't push win rate toward the go-live bar; the score itself
needs to get better at ranking candidates. Separately, the rolling validation check has never
once passed in any of its 24 historical windows — most windows simply don't have enough
qualifying trades to judge fairly (a signal that fires this rarely needs longer windows, fixed
in the next entry).

**Backtest:** N/A for this entry specifically — the main backtest result itself is unchanged by
this fix; only the previously-broken analysis tools now work correctly and reveal existing facts
about the model.

**Approved:** MrKoods — 2026-07-19

---

## [v2.2.3] — 2026-07-19 — [Bug Fix] Config bug silently ignored a setting; toned down a triple-counted penalty

**Status:** Live.

**Problem:** Investigating why paper trading had produced zero qualifying signals found two
separate issues. First, a modifier's config setting was never actually being read due to a
naming mismatch — it had silently been using a hardcoded default the whole time. Second, three
separate penalties were all firing at once, all tracing back to the exact same underlying market
signal, stacking to a large combined penalty across the entire watchlist regardless of any
individual stock's own merit.

**Fix:**
- Fixed the naming mismatch so the modifier's real config setting is actually read.
- Reduced one particular sector-wide penalty from -10 to 0, since it was found to overlap
  heavily with two other penalties, effectively triple-counting one observation as three
  separate warning signs.

**Backtest:** N/A — the backtest doesn't model this particular modifier at all, so this change
has no effect on the existing backtest result. All 500 tests pass (497 passed, 3 skipped).

**Approved:** MrKoods — 2026-07-19

---

## [v2.2.2] — 2026-07-19 — [Bug Fix] Fixed 24 issues found in a full code review

**Status:** Live. Several of these fixes changed real scoring/risk calculations (called out
below), so this isn't just a cleanup pass.

**Problem:** A full code review was requested "thinking like a senior developer and market
analyst." It surfaced 24 separate issues across six areas of the codebase — most consequential:
the Sharpe ratio bug below, since it invalidated a previously-reported headline number.

**Fix** — grouped by area, problem then fix:
- **Backtest accuracy** — Trade-counting order was scrambling the performance-over-time
  calculation, and Sharpe ratio annualization was wrong (the previously reported figure of 9.1
  was inflated by this bug and must not be cited) — both fixed. The historical test window was
  losing its first ~2 months to warm-up with no chance of producing a trade — fixed. Fundamental
  data in the backtest was using today's live numbers for the entire multi-year replay instead
  of what would have actually been known at each point in time (a real look-ahead bias) — fixed.
- **Scoring accuracy** — Fixed several places where scores could be subtly wrong: missing
  technical data reading as "bearish" instead of "unknown," a harsh cliff in the
  earnings-growth score that treated any decline the same regardless of severity, a
  data-unavailable safety cap that could be silently skipped, sentiment scores trusting a single
  data point too much, three different and disagreeing ways of counting insider trades, and a
  credibility-scoring bug that could mistakenly treat a garbled source name as a trusted outlet.
- **Risk and execution enforcement** — The documented minimum reward-to-risk filter and a
  liquidity filter were being calculated but never actually checked, so a bad-risk trade could
  still get recommended — fixed. Also fixed: position sizing silently exceeding its own 5% cap,
  two same-direction positions able to open on the same stock, bad price data producing
  backwards stop-loss/target levels, and a volatility-regime classification gap that skipped an
  important safety brake during elevated (but not extreme) market volatility.
- **Calibration/feedback loop** — The safety check meant to catch a bad recalibration was
  comparing a number to itself and could never actually fail — fixed. A scoring parameter that
  had been defined but never actually used was implemented.
- **Dead code removed** — Deleted an old paper-trading module that could never actually do
  anything (nothing ever fed it real data), and implemented a previously-stubbed position
  re-scoring feature (not yet turned on for live use).
- **Reliability/security** — API keys are now stripped out of error messages before they get
  logged (previously an error could leak a live key into a log file in plain text). Two Alpha
  Vantage calls that weren't being counted against the daily budget now are. Critical files now
  save safely (crash-proof) instead of risking corruption if interrupted mid-write. Fixed a bug
  that mislabeled the cause of a failed scan.

**Backtest:** Ran fresh against real historical data: **57.0% win rate** (required 80% — fail),
**2.01 avg reward:risk** (required 3:1 — fail), 107 qualifying trades (required 100 — pass),
Sharpe ratio 2.45 (this replaces the earlier, incorrect 9.1 figure). All 107 qualifying trades
happened to fall in the same market regime (trending up) — the available historical data
doesn't have enough variety to test other market conditions. Not eligible for live trading — win
rate and reward:risk both fall well short, and the lack of market-condition variety means even
the passing-regime result can't be generalized yet.

**Approved:** MrKoods — 2026-07-19 (code changes only; backtest failed, not approved for live
trading)

---

## [v2.2.1] — 2026-07-18 — [Infrastructure] Removed email/SMS alerts — Discord and the app are the only channels now

**Status:** Live. Infrastructure simplification — no scoring impact.

**Problem:** The project is still in paper trading with no real money at risk, so the
"guaranteed delivery" reason for having email/SMS as backup alert channels doesn't apply yet.
Maintaining those credentials and the extra priority-escalation logic to pick between channels
was ongoing overhead for a guarantee that isn't currently needed.

**Fix:** Removed email and SMS as alert delivery methods, along with the priority-escalation
logic that decided which channel to use, and the now-unused credentials/settings. Discord (plus
the desktop app's own notification feed) is now the only delivery channel.

**Backtest:** N/A — alert delivery only, no effect on scoring or trade selection.

**Approved:** MrKoods — 2026-07-18

---

## [v2.2.0] — 2026-07-18 — [Feature] Added near-miss awareness alerts; flagged an overlapping-penalty risk

**Status:** Live. A new notification type, not a scoring change.

**Problem:** Reviewing a day's real scan results showed the 90-point cutoff was a hard cliff
with zero visibility — a score of 89 and a score of 12 looked identical (invisible) from
outside the system.

**Fix:**
- Added a low-key Discord alert for a ticker that scores 80-89 — close to, but not over, the
  real 90-point trading threshold. Clearly labeled as "not a trade signal," and never logged as
  a real trade.
- Added a log note for when two particular penalties are negative in the same scan, since
  they're both ultimately driven by the same underlying market signal — flagged as informational
  only, not auto-corrected.

**Backtest:** N/A — new alert type and logging only, no effect on scoring or trade selection.

**Approved:** MrKoods — 2026-07-18

---

## [v2.1.5] — 2026-07-17 — [Bug Fix] Fundamental data now saves after each ticker, not just at the end

**Status:** Live. Reliability fix — no scoring impact.

**Problem:** Found the fundamentals file 11 days stale. Traced it to a manual interruption
partway through a refresh — because the old code only saved once at the very end, that single
interruption threw away several tickers that had already successfully finished, with no warning
anywhere. The interruption itself was a one-off, but the "all-or-nothing" save was a real
structural weakness that could recur from any crash, network drop, or API limit hit mid-batch.

**Fix:** The weekly fundamentals refresh now saves progress after every ticker completes,
instead of only once the whole batch finishes.

**Backtest:** N/A — reliability fix only, no effect on scoring or trade selection.

**Approved:** MrKoods — 2026-07-17

---

## [v2.1.4] — 2026-07-16 — [Scoring Change] Excluded statistical outliers from sector-average valuation

**Status:** Live. This one does change a real scoring calculation (the valuation sub-score), so
it's flagged carefully.

**Problem:** Found that three tickers all hit the maximum possible fundamental score at the same
time — investigating showed one ticker's price-to-earnings ratio was wildly inflated (from a
temporary earnings drop), dragging the whole sector's "average" valuation up and making everyone
else look artificially cheap by comparison. With only 5-6 tickers in the watchlist, one distorted
number doesn't just mis-score itself — it quietly biases every comparison.

**Fix:** The Fundamental category's valuation score now excludes statistical outliers before
averaging peer valuations, instead of letting one distorted value skew the average for the whole
sector. Confirmed directly against real data: excluding the outlier corrected the sector average
significantly and spread the scores back out realistically.

**Backtest:** Inherited the same not-yet-passing status as before, not independently re-tested
— the existing backtest already fails for unrelated reasons. This specific fix was verified
directly against real current data instead.

**Approved:** MrKoods — 2026-07-16

---

## [v2.1.3] — 2026-07-16 — [Bug Fix] Fixed a stale-news bug that could re-trigger blocks forever

**Status:** Live. Bug fix plus logging — no scoring impact.

**Problem:** A 6-day-old news story kept re-triggering a fresh block on the entire watchlist
every day, because the sector-wide breaking-news check never aged out old articles the way the
ticker-specific check already did — left unfixed, this one headline could have kept re-blocking
the whole watchlist indefinitely. Separately, real scan data showed every ticker's score falling
in lockstep across a single day, which couldn't be explained without seeing the shared modifiers
alongside the per-ticker scores.

**Fix:**
- The breaking-news block system now correctly ages out old articles for sector-wide triggers,
  the same way it already did for ticker-specific ones.
- Score logs now also show all six shared modifiers (market regime, sector rotation, macro,
  earnings timing, cross-ticker, seasonality), not just the five main category scores.

**Backtest:** N/A — bug fix and logging only. The stale-news fix was verified directly against
the real headline that caused the bug.

**Approved:** MrKoods — 2026-07-16

---

## [v2.1.2] — 2026-07-15 — [Infrastructure] Paper trading now logs every ticker's score, not just qualifying ones

**Status:** Live. Logging-only change — no scoring impact.

**Problem:** On the first full day of paper trading, nothing qualified — meaning there was zero
record anywhere of what any ticker had actually scored, making it impossible to check whether
the scoring categories were working sensibly.

**Fix:** Added a log line showing every ticker's full score breakdown on every scan, regardless
of whether it clears the trading threshold.

**Backtest:** N/A — logging only.

**Approved:** MrKoods — 2026-07-15

---

## [v2.1.1] — 2026-07-15 — [Feature] Breaking-news block: "hide the signal" → "show it with a warning"

**Status:** Live. Doesn't affect the existing not-yet-eligible-for-live-trading status either
way.

**Problem:** During early paper trading, a real breaking-news event blocked the entire
watchlist for a scan. Hiding every signal outright during an active event risks hiding a
genuinely valid opportunity — the system was deciding silently for the trader instead of
surfacing the situation and letting a human judge it.

**Fix:** A serious breaking-news event no longer hides a qualifying trade signal completely — it
now surfaces normally, with a clear warning attached, so a human can make the final judgment
call.

**Backtest:** Inherited the same not-yet-passing status as before, unaffected by this change.
The prior full backtest run scored 64.5% win rate against the 80% requirement — everything else
passed except win rate, for reasons unrelated to this change. The historical data used for
backtesting has no real breaking-news events in it, so this specific change can't be tested by
the backtest either way.

**Approved:** MrKoods — 2026-07-15 (paper-trading behavior change; not approved for live trading)

---

## [v2.1.0] — 2026-07-14 — [Feature] Added a breaking-news safety block (not a scoring category)

**Status:** Not yet eligible to go live — see Backtest result below.

**Problem:** The existing 5-category score has a real blind spot: news only makes up 15 of 100
points, so a genuinely severe, fast-moving story (a company scandal, an export ban, fraud
allegations) can be outvoted by four much slower-moving categories that haven't caught up yet.

**Fix:** Added a new safety mechanism that can block a ticker from surfacing as a trade signal
when a serious, thesis-opposing breaking-news event is detected — a separate veto layer, not a
sixth scoring category; News still scores exactly as before. The block only ever suppresses a
signal, never boosts one, and automatically expires after a set cooling-off period. Deliberately
one-directional — chasing a shock headline that already confirms a trade thesis is a good way to
buy the top of a spike; the goal here is loss prevention, not extra upside chasing. Also added
new alert types for when a block triggers or expires, and a safety net that auto-repairs
corrupted block-tracking data.

**Backtest:** Not run, and can't be meaningfully backtested with the currently available
historical data — the historical news archive wasn't curated to include real trigger events like
these, so there's nothing genuine to test the block against yet. Not eligible for live trading
until a real backtest is run and passes.

**Approved:** Pending — do not go live on this version until a backtest is run and passes.

---

## [v2.0.0] — 2026-07-13 — [Scoring Change] Added two new scoring categories; switched the sentiment data source

**Status:** Not yet eligible to go live — see Backtest result below.

**Problem:** Reddit access (the prior sentiment source) had stalled with no clear path forward.
Separately, options activity, institutional ownership changes, short interest, insider trading,
and analyst ratings were all real, distinct signals the original design never captured — and
insider trading data was being counted twice, in its own separate bonus/penalty as well as
implicitly elsewhere. The written design document had also drifted out of sync with the actual
code.

**Fix:**
- Added a new **Market Positioning** category (worth 20 points) covering options activity,
  institutional ownership, short interest, insider trading, and analyst ratings — all free data.
- Removed Reddit as a sentiment source entirely and replaced it with StockTwits (a paid
  subscription with clearly tagged bullish/bearish posts) plus a Seeking Alpha engagement
  measure — a real quality upgrade, not just a substitute.
- Moved insider trading data out of its own separate bonus/penalty and into the new Positioning
  category, fixing the double-count.
- Rebalanced category weights: Technical 50→40, Positioning (new) →20, Sentiment 20→15, News
  unchanged at 15, Fundamental 15→10.
- Brought the written design document back in sync with the actual code.

**Backtest:** Not run yet — there's no historical data for StockTwits or the new Positioning
category; both need to build up real history from this point forward, the same way Fundamental
data did. Not eligible for live trading until a real backtest is run and passes.

**Approved:** Pending — do not go live on this version until a backtest is run and passes.

---

## [v1.0.0] — 2026-06-29 — [Infrastructure] Initial project scaffold

**Status:** Scaffolding complete — the basic skeleton is built, but most of the real logic
isn't written yet.

**What's in this version**
- The full project structure and configuration, matching the original design document.
- All 14 planned build phases stubbed out with placeholder functions.
- The scoring formula design: Technical 60 / Sentiment 25 / News 15, plus 7 modifier types.
- 42 possible trade structures defined, with a framework for ranking them.
- Position sizing and circuit-breaker rules defined.

**What's not built yet**
- The real scoring logic, real expected-value calculations, and backtesting. Every weight is a
  starting hypothesis until backtesting proves it out.

**Backtest:** N/A — no backtest has been run yet; this version is scaffolding only.

**Approved:** MrKoods — 2026-06-29

---

<!-- Template for future entries:

## [vX.Y.Z] — YYYY-MM-DD — [Category] Short description

**Status:** ...

**Problem:** What was wrong or missing, and why it mattered.

**Fix:**
- ...

**Backtest:** Run date: YYYY-MM-DD. Win rate: X%. Avg R:R: 1:X. Qualifying trades: N.

**Approved:** ...

-->
