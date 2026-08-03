# CHANGELOG — AI-Assisted Swing Trading Signal System

This is the history of every change made to an automated stock-trading model. It has **never
traded real money** — every version so far has been building, testing, and fixing a strategy
that is still only running in "paper trading" (see glossary below), which uses fake money.

If you're new here, read **every entry's "In short" line** — that's the plain-English version.
Everything below it (Problem / Fix / Backtest) is the technical detail, for anyone who wants it.

## Where things stand right now

The model has been rebuilt and re-tested many times but has never once passed all the
requirements to trade real money. The biggest recent milestone: on 2026-08-01, its historical
performance test passed its own safety bar for the first time ever, after realizing an old
setting no longer fit how the model has evolved. Several more real bugs were found and fixed
right after that — mostly things hiding in parts of the model that the historical test can't
check, because they depend on live, real-time data. None of this changes whether the model is
allowed to trade real money — it still isn't, and won't be until it's approved.

## Plain-English glossary

| Term | What it means |
|---|---|
| **Live** | The change is active right now, in the real running system. |
| **Paper trading** | The model makes real trading decisions using real, live market data — but with fake money. A dry run to prove it works before any real money is at risk. |
| **Backtest** | Running the strategy against years of *past* stock-market data to see how it would have done, before trusting it with money (real or fake). |
| **Signal / qualifying trade** | A stock the model considers actually worth trading — it has to score 90 out of 100 or higher. |
| **Win rate** | The percentage of trades that ended up profitable. |
| **Reward:risk (R:R)** | For every $1 a trade risks, how many dollars it's aiming to make. "2:1" means "risk $1 to try to make $2." |
| **Sharpe ratio** | One number measuring how good the returns are compared to how bumpy the ride was to get them. Higher is better; the model needs at least 1.0 to be allowed to go live. |
| **Go-live bar / gate** | The specific numbers (win rate, Sharpe ratio, number of trades, etc.) a version must hit in a backtest before it's allowed to risk real money. Nothing has passed all of these yet. |
| **Expectancy** | The average amount a trade is expected to make or lose, per dollar risked. |
| **Walk-forward window** | One specific slice of history (e.g. a 2-year stretch) used to test the strategy, so results aren't based on just one lucky or unlucky period. |
| **Sector / watchlist** | A sector is a group of related stocks (e.g. semiconductor companies) the model watches together. The watchlist is the full list of stocks it's currently scanning. |
| **Sub-signal / modifier** | One small ingredient that feeds into a stock's overall score — e.g. how its price is moving, or how positive the news about it is. |
| **Alpha Vantage, Finnhub, Yahoo, Seeking Alpha, SEC EDGAR, StockTwits** | Outside services the model pulls stock prices, news, and public sentiment from. |

## Categories

Every entry is tagged with the kind of change it is:

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

Version numbers follow MAJOR.MINOR.PATCH: MAJOR = a fundamental change to how the strategy
scores or picks trades; MINOR = a new indicator, modifier, or scoring category; PATCH = a
threshold tweak, bug fix, or calibration update. **Rule:** no change to scoring weights,
indicator settings, or thresholds goes live without a version bump and a fresh backtest result
logged below it — enforced automatically by the code, no exceptions.

## Quick reference

| Version | Date | Category | Summary |
|---|---|---|---|
| v2.2.37 | 2026-08-03 | Infrastructure | Paper trading's account size was a hardcoded duplicate of the config value, not read from it |
| v2.2.36 | 2026-08-03 | Bug Fix | The options-structure picker had 35 of 42 strategies silently mis-costed — real formulas now, so protective_put stops winning by accident |
| v2.2.35 | 2026-08-02 | Bug Fix | Two more hidden bugs in how the model reads public sentiment |
| v2.2.34 | 2026-08-02 | Bug Fix | Every Yahoo Finance news article had a blank title — none of them could ever be used |
| v2.2.33 | 2026-08-02 | Scoring Change | Re-checked several scoring settings against the bigger 3-sector test; kept 3, dropped 2 |
| v2.2.32 | 2026-08-01 | Scoring Change | Stopped punishing strong individual stocks as hard as their weak sector |
| v2.2.31 | 2026-08-01 | Backtest Methodology / Feature | Performance test now covers all 3 sectors instead of just one |
| v2.2.30 | 2026-08-01 | Bug Fix | Last version's seasonal-calendar fix was incomplete — a second bug was hiding under it |
| v2.2.29 | 2026-08-01 | Backtest Methodology / Scoring Change | An outdated filter was loosened — backtest passes its own bar for the first time |
| v2.2.28 | 2026-07-31 | Bug Fix | Found and fixed 5 separate bugs quietly suppressing real trade signals |
| v2.2.27 | 2026-07-29 | Data Source | Added a signal for big tech companies cutting chip-related spending |
| v2.2.26 | 2026-07-29 | Data Source | Started reading companies' official SEC filings as a news source |
| v2.2.25 | 2026-07-29 | Bug Fix | An incomplete, still-forming stock price could sneak into the model's math |
| v2.2.24 | 2026-07-28 | Sector Rollout | Turned on healthcare stocks for practice trading |
| v2.2.23 | 2026-07-28 | Feature | Started recording near-miss opportunities to learn from, without treating them as real trades |
| v2.2.22 | 2026-07-28 | Feature | The model can now actually check an options trade's risk profile, instead of skipping it |
| v2.2.21 | 2026-07-28 | Infrastructure | One news service is now called only when something looks urgent, to save its limited budget |
| v2.2.20 | 2026-07-28 | Infrastructure | Fixed misleading reports and reconnected a disconnected self-correction system |
| v2.2.19 | 2026-07-28 | Data Source | Switched one earnings data point to a free source instead of a paid, limited one |
| v2.2.18 | 2026-07-26 | Research | Tested the strategy on an unrelated group of stocks (healthcare) — it still worked |
| v2.2.17 | 2026-07-26 | Backtest Methodology | Replaced an unrealistically strict pass/fail bar with a smarter one |
| v2.2.16 | 2026-07-26 | Research | Checked whether two scoring categories were secretly measuring the same thing — they aren't |
| v2.2.15 | 2026-07-26 | Feature | The model now double-checks urgent headlines immediately instead of waiting hours |
| v2.2.14 | 2026-07-26 | Data Source / Infrastructure | Counted one more news source toward the real score; engineering cleanup |
| v2.2.13 | 2026-07-24 | Data Source / Bug Fix | Sped up news reactions, saved an API call, stopped fake test data leaking into real logs |
| v2.2.12 | 2026-07-23 | Infrastructure | Spread a weekly data refresh across the week instead of doing it all at once |
| v2.2.11 | 2026-07-20 | Bug Fix | Adding more stock groups could make some of them silently stop getting fresh data |
| v2.2.10 | 2026-07-19 | Sector Rollout | Turned on regional bank stocks for practice trading |
| v2.2.9 | 2026-07-19 | Bug Fix | A leftover bug — one stock group was still accidentally averaged in with another |
| v2.2.8 | 2026-07-19 | Infrastructure | Behind-the-scenes prep work for safely adding a second group of stocks |
| v2.2.7 | 2026-07-19 | Backtest Methodology | The historical test now accounts for interest rates and the dollar's strength |
| v2.2.6 | 2026-07-19 | Backtest Methodology / Research | Fixed a grading bug, adopted a better filter, tested a second stock group |
| v2.2.5 | 2026-07-19 | Backtest Methodology | Tightened a filter based on solid evidence, even though one headline number got worse |
| v2.2.4 | 2026-07-19 | Backtest Methodology | Fixed a broken tool and discovered the strategy has never passed its own internal check |
| v2.2.3 | 2026-07-19 | Bug Fix | Fixed a setting that was silently ignored, and stopped one warning sign counting three times |
| v2.2.2 | 2026-07-19 | Bug Fix | A full code review found and fixed 24 separate problems |
| v2.2.1 | 2026-07-18 | Infrastructure | Removed email/text alerts — Discord and the app are the only channels now |
| v2.2.0 | 2026-07-18 | Feature | Added a heads-up alert for stocks that almost, but didn't quite, qualify |
| v2.1.5 | 2026-07-17 | Bug Fix | One interruption during a data refresh could throw away a lot of finished work |
| v2.1.4 | 2026-07-16 | Scoring Change | Stopped one extreme stock from skewing its whole sector's average score |
| v2.1.3 | 2026-07-16 | Bug Fix | One old news story could keep blocking the entire watchlist forever |
| v2.1.2 | 2026-07-15 | Infrastructure | Started logging every stock's score, not just the ones that qualified |
| v2.1.1 | 2026-07-15 | Feature | A serious news event now shows a trade signal with a warning, instead of hiding it |
| v2.1.0 | 2026-07-14 | Feature | Added a safety switch that can hide a trade signal during a serious news event |
| v2.0.0 | 2026-07-13 | Scoring Change | Added a whole new scoring category and switched how the model reads public mood |
| v1.0.0 | 2026-06-29 | Infrastructure | The very first version — basic structure built, but no real logic yet |

---

## [v2.2.37] — 2026-08-03 — [Infrastructure] Paper trading's account size read from a hardcoded duplicate, not the config value

**Status:** Live.

**Problem:** `paper_trading/paper_runner.py` passed `account_equity=15000.0` to the diagnostic
trade-structure evaluator as a hardcoded literal, duplicating `config/swing_config.yaml`'s
`position_sizing.starting_capital`. Raised while confirming both values agreed (they did, $15,000)
— but a literal duplicate silently drifts the moment either one is changed without the other, and
nothing would catch it. Checked whether this could instead read a live, updating balance (the
better fix, if a real one existed): it doesn't — paper trading has no dollar-equity tracking of its
own at all. `paper_trades.csv` logs each trade's `pnl_pct` only; the account-equity/peak-equity
tracking in `swing_model/portfolio_manager.py` (`data/processed/position_state.json`) belongs to a
separate system (`run_swing_model.py`'s own position tracking), not paper trading, and reading from
it here would have silently mixed two unrelated pipelines' state.

**Fix:** `paper_trading/paper_runner.py` now reads `cfg.get("position_sizing", {}).get(
"starting_capital", 15000.0)` instead of a hardcoded `15000.0` — single source of truth, config
changes now actually take effect here. Building real running-balance tracking for paper trading
(computing position-sized dollar P&L per closed trade, the way `portfolio_manager.py` already does
for the separate live-tracking pipeline) is a separate, larger feature, not done here.

**Backtest result:** Not applicable — this only affects the diagnostic trade-structure evaluator's
starting capital figure, not any backtested scoring path. 745 tests pass (unchanged), 3 skipped.

**Approved by:** [pending]

---

## [v2.2.36] — 2026-08-03 — [Bug Fix] 35 of 42 trade structures had mis-costed EV; protective_put's ranking dominance was an artifact, not merit

**Status:** Live (this is the trade-structure diagnostic tier — score 60-89, not the 90+ real
signal path — but the ranking is real, collected data, not inert).

**Problem:** Investigating why the diagnostic trade-structure evaluator (see v2.2.23, scores
60-89) had picked `protective_put` in all 4 real evaluations recorded since it started collecting
data found two compounding bugs, not a genuine 4-for-4 preference:

1. `STRUCTURE_MULTIPLIERS` (`shared/utils/options_math.py`) stores a `profit_mult`/`loss_mult` pair
   per structure meant to model its real risk/reward shape. For 35 of 42 structures, these were
   descriptive placeholder strings (`"leverage"`, `"spread_width_minus_debit"`, `"put_premium"`,
   `"theta_decay"`, ...) that read like they were meant to become real formulas but never did.
   `_compute_structure_ev`'s `isinstance` guard silently converted every one of them to `1.0`,
   making 35 structures' modeled EV indistinguishable from plain long/short stock — none of their
   actual leverage, defined-risk cap, or premium cost was ever being modeled.
2. `_estimate_capital_required`'s `protective_put` branch used a special-cased shortcut
   (`entry * 0.3`) that its economically near-identical siblings `married_put`/`collar` didn't get
   — they fell through to a generic default ~15-30x larger. Verified directly: a real capital
   requirement for 100 shares + a put (even at 50% margin) is $1,250-$15,000 for this watchlist's
   tickers, vs. the old estimate's $8-$90 — nowhere close to affordable at a $15k account's $750
   per-trade cap. `protective_put` was winning because its capital denominator was ~100x too small,
   not because it was a better trade. Since bug #1 also meant almost every *other* structure's EV
   was computed identically to plain stock, the ranking effectively reduced to "whichever structure
   has the smallest capital estimate" — exactly the property `protective_put`'s shortcut exploited.
3. (Found while fixing #1) `iv_percentile` (0-100, where today's IV ranks against its own history —
   a rank, not a volatility value) was being divided by 100 and fed into option-pricing math as if
   it were the actual IV fraction, conflating "IV is unusually high for this stock right now" with
   "this stock's IV is 80%" — two different, independent facts.

**Fix:**
- `shared/utils/options_math.py`: new `resolve_structure_economics()` — real Black-Scholes-derived
  `avg_win`/`avg_loss`/`capital_required` for all 35 affected structures, replacing the placeholder-
  multiplier lookup. Strike conventions reuse this module's own `select_directional_leg_strike()`
  offsets (otm=6%, far_otm=12%, deep_itm=15%) for consistency with the existing Greeks filter.
  EV and capital are computed together per structure so they can never disagree the way
  `protective_put`'s did — the actual root cause above. The 4 ratio/back-spread structures already
  routed through a separate real (if simplified) surface calculation and are untouched; the 3 pure-
  stock structures were already correct and are untouched.
- `swing_model/trade_selector.py`: `_compute_structure_ev` now calls `resolve_structure_economics`
  first, falling back to the old numeric-multiplier path only for the 3 pure-stock structures it
  doesn't cover. Removed a redundant second `_estimate_capital_required` call later in
  `rank_trade_structures` that was silently overwriting the newly-consistent capital figure with the
  old one — found while wiring this in; without removing it, the fix would have had no effect.
  Added `atm_iv` parameter (sourced from `positioning_client.py`'s real chain data via
  `_options_raw`) so real option pricing uses actual IV instead of a mislabeled percentile.
- Found and fixed a bug in my own new code during verification: `diagonal_call`/`diagonal_put`'s net
  debit could come out at or near zero given this module's strike/expiry approximation, and a fixed
  `max(net_debit, 0.01)` floor turned that into an absurd ~$1 capital figure (`ev_per_dollar_risked`
  364 — instantly ranked #1 above everything else). Replaced every such floor with one proportional
  to the stock's own price instead of a fixed tiny constant.
- 22 new tests (`tests/test_structure_economics.py`) — broad sweep across all 35 structures for
  degenerate/absurd output (the exact class of bug above) plus targeted checks per category (debit
  spreads' loss bounded by net debit, credit spreads' win+loss ≈ width, protective_put/married_put
  now getting equal treatment, long options' loss bounded by premium paid). One pre-existing test
  (`tests/test_phase7_trade_math.py`) updated: it asserted `long_call` passes the default Greeks
  theta bound on the *old* $2,500 capital heuristic; the new, more accurate ~$984 real premium makes
  the same real theta correctly show as exceeding 5% of capital — swapped to `bull_put_spread`,
  which clears the bound by construction (its two legs' theta partially offset).

**Verified against real live market data** (JNJ, RF — fetching real chains/prices, not synthetic
inputs): `protective_put`/`married_put`/`collar` no longer appear in either ticker's ranking at all
(correctly excluded — genuinely unaffordable at this account size). Top-ranked structures are now
`diagonal_call`, `long_call`, `bull_call_spread` — real, sensible, capital-efficient structures with
realistic dollar figures ($16-$608 range), not a single outlier dominating by ranking artifact.

**Backtest result:** Not applicable — this is the diagnostic trade-structure tier (score 60-89),
which the 13.5-year backtest doesn't exercise (it measures only the win-rate/R:R/Sharpe of the
90+ signal path). Verified via direct live-data inspection and the new test suite instead. 745 tests
pass (was 723), 3 skipped.

**Approved by:** [pending]

---

## [v2.2.35] — 2026-08-02 — [Bug Fix] Sentiment's ratio and velocity sub-signals had two independent bugs

**Status:** Live.

**In short:** Found two more hidden bugs in how the model reads public sentiment — one made
genuinely bullish stocks look bearish, and one made a "how fast is mood changing" measurement
almost always pinned at max or zero instead of properly graded.

**Problem:** Following up v2.2.34's News fix, checked the other scoring layers for the same kind
of silent bug, using real live data rather than just re-running old numbers. Sentiment was the
weakest remaining layer. Tracing one healthcare stock's near-zero sentiment score against its
real StockTwits messages turned up two separate bugs:
1. The bullish-vs-bearish ratio calculation counted every message toward the total, including
   ones with no bullish/bearish tag at all (most StockTwits messages don't carry one). Every
   untagged message silently dragged the ratio toward "bearish," even though it expressed no
   opinion either way. On real data, 10 tagged messages were unanimously bullish, 0 bearish — but
   the ratio came out near zero anyway.
2. The "how fast is sentiment changing" score averaged two raw numbers that aren't on the same
   scale — one stays small, the other swings much wider — so the wider one dominated almost every
   time, making the result nearly always pinned at the extreme ends instead of a graded score.

**Fix:**
- The ratio calculation now only counts messages that actually carry a bullish/bearish tag,
  instead of treating "no opinion" the same as "bearish."
- The rate-of-change score now puts both underlying numbers on the same scale before combining
  them, so neither one silently dominates the other.
- Added 6 new tests covering both fixes directly.

**Verified against real data:** the affected stock's sentiment score moved from 0.0 to a properly
graded value, and its overall sentiment reading correctly flipped from "bearish" to "bullish" —
matching what its real messages actually showed.

**Backtest:** N/A — the 13.5-year historical test doesn't use real StockTwits data at all (it
uses a stand-in based on price movement), so this bug never affected any backtest result in this
file. Verified with live data and new tests instead. 723 tests pass (was 717), 3 skipped.

**Also checked in the same pass:** two other low-scoring stocks were traced end-to-end and found
to be scoring correctly based on genuinely weak real data — not further bugs.

**Approved:** [pending]

---

## [v2.2.34] — 2026-08-02 — [Bug Fix] A data-source change silently emptied every Yahoo Finance article's title

**Status:** Live.

**In short:** Discovered that every single news article pulled from Yahoo Finance had a blank
title, because Yahoo changed how it structures that data and the model was never updated to
match — meaning no Yahoo News article, for any stock, could ever have counted toward the News
score, until now.

**Problem:** Investigating why News remained the weakest scoring category found a bigger,
separate bug: Yahoo Finance's data now nests the actual article details one level deeper than
before, but the code reading it was still looking in the old spot — which is always empty under
the new format. The result: every Yahoo article's title has effectively been blank the entire
time, so the model could never match it to a real ticker, no matter how good its list of company
names was. This had no test coverage at all, so nothing ever caught it.

**Fix:** Updated the Yahoo News reader to pull from the correct, current location, with a
fallback to the old location in case Yahoo changes its format back. Added 5 new tests covering
both the current format and the fallback.

**Verified against real live data:** relevance-matching for a sample of regional bank stocks went
from 0 out of 10 matched articles (every title was blank) to 5-8 out of 10 after the fix.

**A real limit found along the way, not a bug:** the gain was smaller than that jump suggests,
because most of the newly-matched articles are older than the 5-day cutoff the News score already
uses to avoid trading on stale information — so only a handful of genuinely fresh articles per
stock exist on any given day regardless. That cutoff is working as intended and wasn't changed.

**Backtest:** N/A — the 13.5-year historical test never uses this live Yahoo News function, so
this bug never affected any backtest result in this file. Verified with live data and new tests
instead. 717 tests pass (was 712), 3 skipped.

**Approved:** [pending]

---

## [v2.2.33] — 2026-08-02 — [Scoring Change] Re-checked several scoring settings against the bigger 3-sector test

**Status:** Live (all three kept changes are real scoring changes).

**In short:** Now that the performance test covers all three groups of stocks together (see
v2.2.31) instead of just one, re-checked five candidate scoring-setting changes against that
bigger, more trustworthy sample. Kept three that genuinely helped; rejected two that looked good
at first but actually made results worse overall.

**Problem:** v2.2.28 had tried tuning a couple of scoring settings and found "no effect" — but
that test only had a small, one-sector sample to check against. v2.2.31's much bigger, combined
test made it possible to properly re-check that and a few other settings, instead of trusting a
result from a small sample.

**Kept (3 real improvements):**
- A relative-strength scoring setting was loosened slightly — produced a better risk-adjusted
  return and more qualifying trades than the old setting.
- The "sweet spot" range for one momentum indicator was widened slightly — matched the best
  result on the risk-adjusted return measure while keeping more trades; a version widened even
  further was clearly worse on every measure, confirming wider isn't automatically better.
- A penalty for choppy, directionless markets was eased — modest improvement, the weakest-evidence
  change of the three, but a real one.

**Rejected (2 that looked appealing but weren't worth it):**
- Requiring an extra day of confirmation before entering a trade: fewer trades and a noticeably
  worse risk-adjusted return — it was filtering out real winning trades, not just weak ones.
- A minimum-volume filter on breakouts: improved win rate and reduced the worst losing stretch,
  but at too high a cost to overall risk-adjusted return and trade count to be worth it.

**Backtest:** All three kept changes together, across all three stock groups: qualifying trades
266→296, win rate 59.0%→59.8%, reward:risk 1.62→1.63, Sharpe ratio 3.10→3.43, worst drawdown
9.1%→8.7%. Still passes its safety bar. 712 tests pass (unchanged), 3 skipped.

**Approved:** [pending]

---

## [v2.2.32] — 2026-08-01 — [Scoring Change] Stopped punishing strong individual stocks as hard as their weak sector

**Status:** Live.

**In short:** A stock doing genuinely well even though its whole sector is struggling was being
penalized exactly as hard as the sector's laggards. That penalty is now eased off for real
standouts, instead of applying evenly to everyone.

**Problem:** The model applies a penalty to every stock in a sector that's losing money overall
(sector "rotation" out of it), regardless of how that individual stock is actually performing. A
stock significantly outperforming its own history despite a weak sector — arguably the most
interesting kind of opportunity — was getting the exact same penalty as the sector's weakest
performers. Flagged as worth fixing during a broader review.

**Fix:** The sector penalty now softens (by up to half) for a stock with strong-enough relative
strength, scaling in gradually rather than as an on/off switch. It never fully cancels the
penalty — a strong stock in a falling sector still carries real risk — and never affects a stock
that isn't already being penalized. Added 9 tests covering the softening curve directly.

**Backtest:** N/A — the historical test doesn't yet track this kind of live, real-time sector data
at all (a known, pre-existing gap, not something this change caused), so this can only be verified
with live-behavior unit tests, which it was. 712 tests pass, 3 skipped.

**Approved:** [pending]

---

## [v2.2.31] — 2026-08-01 — [Backtest Methodology / Feature] Performance test now covers all 3 sectors instead of just one

**Status:** Backtest-only. No live/paper trading behavior changed.

**In short:** The historical performance test had only ever been checking one of the three
groups of stocks the model actually trades. It now checks all three together, which is a much
more honest measure of how the real, live model would have performed. Also confirmed a filter
setting that had been accidentally reverted without being properly re-checked first.

**Problem:** The live model has traded three sectors (semiconductors, regional banks, healthcare)
for a while now, but the historical performance test had only ever been validated against
semiconductors — the other two sectors' historical data existed but was never actually plugged
in. Every backtest result reported in this file up to this point, including the "passed for the
first time" milestone, was really only measuring one of the three sectors the live model trades.

Separately, some in-progress work had reverted a recently-tested filter setting back to an older
value, based on a note that was never actually re-checked against real data before being written
down. Left alone, this would have shipped an unvalidated reversal of a decision that had
explicitly been tested and confirmed.

**Fix:**
- Built a new version of the performance test that runs the same process once per sector (each
  against its own appropriate benchmark) and then combines the results into one overall measure —
  sectors are never mixed at the raw price-data level, only at the final outcome level.
- Re-tested the reverted filter setting directly against both the old, single-sector test and the
  new, combined 3-sector test before touching anything. The original (less strict) setting won on
  every measure in both tests — more qualifying trades, a better risk-adjusted return, and it's
  the one that actually passes the safety bar. Restored it as the default.

**Backtest:** Semiconductors-only result unchanged. **New, combined 3-sector result:** 266
qualifying trades, 59.0% win rate, 1.62 avg reward:risk, Sharpe ratio 3.10, worst drawdown 9.1%.
**Passes its safety bar.** This is the first backtest result that actually reflects all three
sectors the live model trades, not just one of them. 712 tests pass (was 707), 3 skipped.

**What this means:** this changes how much confidence to place in "the backtest passes" as a
statement about the real, live model — it does not change what live or paper trading actually
does.

**Approved:** [pending]

---

## [v2.2.30] — 2026-08-01 — [Bug Fix] Last version's seasonal-calendar fix was incomplete

**Status:** Live.

**In short:** v2.2.28 fixed a bug where the model wasn't reading its seasonal-calendar settings
correctly — but that fix turned out to be incomplete. A second, sneakier bug meant live scans
were still silently ignoring the real settings even after the first fix "shipped." Both are now
actually fixed.

**Problem:** The first fix corrected a misspelled setting name, but missed that the settings file
stores month numbers in a way that didn't match how the code was looking them up (a technical
type mismatch — the code was searching for "8" as text, but the file stores it as a plain
number). That mismatch meant the lookup always silently failed and fell back to a generic
default, even after the name was corrected. Confirmed live: an August scan was using a
placeholder value instead of the real, calibrated August setting. This was caught because the
test written for the first fix happened to use test data that accidentally matched the buggy
lookup, so it passed regardless of whether the real bug was fixed.

**Fix:** The lookup now tries both the number-based and text-based formats before falling back to
a default. Added two tests: one that mirrors how the settings file is actually structured, and
one that loads the real settings file end-to-end and checks it resolves correctly — so this exact
kind of bug can't hide behind a hand-built test again.

**Backtest:** N/A — this is a correctness fix (the setting now reads its real intended value),
not a calibration change. Verified directly against the real settings file. 707 tests pass (709
once the two new tests are counted), 3 skipped.

**Approved:** [pending]

---

## [v2.2.29] — 2026-08-01 — [Backtest Methodology / Scoring Change] An outdated filter was loosened — backtest passes its own bar for the first time

**Status:** Live (one real scoring change — see below). Backtest-only for the rest.

**In short:** A filter that was tightened years ago, based on evidence from a much older version
of the model, no longer helps now that the model has changed so much — loosening it back up
(plus one other small, real scoring tweak) is what finally let the historical performance test
pass its own safety bar for the first time ever.

**Problem:** v2.2.28 fixed five real bugs but left the core problem unsolved: the historical test
was only finding 18-19 qualifying trades, far short of the 100 needed, with a poor risk-adjusted
return. Digging into exactly where candidates were getting filtered out found one particular
momentum-indicator cutoff was throwing away the vast majority of an already-narrowed pool of
candidates — by far the single biggest filter in the whole chain. That cutoff had been tightened
years ago (v2.2.5) based on real evidence at the time, but re-testing it against today's version
of the model (which has since gained two entire new scoring categories) found that old evidence
no longer holds — win rate is now statistically flat whether the cutoff is tight or loose.

**Also re-checked, now that a bigger sample was available:** two settings that v2.2.28 had tested
and found "no effect" were re-tested. One (a relative-strength setting) turned out to have a real,
positive effect after all — the earlier "no effect" verdict was simply an artifact of testing
against too small a sample. The other genuinely still shows no effect, for a clear structural
reason this time, not a sample-size problem. A third setting (dropping a filter that looked
possibly redundant) was tested and found not to be redundant after all — removing it made results
worse, so it was kept as-is.

**Fix:**
- Loosened the momentum-indicator cutoff back toward its original, pre-v2.2.5 value, and removed
  a same-day confirmation requirement — both are backtest-only settings that correct how fairly
  the historical test measures the model's edge. **Neither of these changes what live or paper
  trading actually does** — live scoring never had a hard cutoff here to begin with.
- Loosened the relative-strength setting identified above. **This one is a real, live scoring
  change** — it changes how every stock's technical score is computed, starting immediately.

**Backtest:** Qualifying trades jumped from 19 to 125, win rate 68.4%→61.6%, reward:risk
2.18→2.04, Sharpe ratio **0.34→3.33**, worst drawdown 3.0%→8.2% (still comfortably under the
ceiling). **Passed — the first time this backtest has ever passed its own safety bar.** One
historical stretch (2014-2016) remains a genuinely weak period for this strategy, worth watching,
not a fluke of this change. 707 tests pass (unchanged), 3 skipped.

**What this means:** the backtest's measured historical performance is now dramatically
healthier — a real, useful correction. It does not, by itself, explain why paper trading went
quiet for 2+ weeks around this time: live scoring never had the two backtest-only gates this fix
touches, so nothing changes there except the one real scoring tweak above. The live model's
90-point threshold and the market conditions at the time were left untouched this round.

**Approved:** [pending]

---

## [v2.2.28] — 2026-07-31 — [Bug Fix] Found and fixed 5 separate bugs quietly suppressing real trade signals

**Status:** Live. No scoring weight, category max, or the 90-point threshold changed. Two
tested calibration ideas were reverted after showing no measurable effect.

**In short:** Paper trading had gone quiet — zero real trade signals for over two weeks. Digging
into why turned up five completely separate, unrelated bugs across different parts of the model,
each one quietly suppressing real signal in its own way. All five are now fixed.

**Problem:** Paper trading logged 0 qualifying signals for 2+ weeks across all three sectors, and
a fresh backtest showed qualifying trades falling sharply too. Investigating turned up five
separate bugs:

**Fix** — one bug and fix per area:
- **Technical:** a piece of scoring logic for where a stock's price sits relative to its trading
  volume history was fully built but never actually wired in anywhere — every stock scored a flat,
  meaningless neutral value regardless of the real picture. Wired it in properly.
- **News:** 11 of 17 watchlist stocks had no company-name entry in the list the model uses to
  match news headlines to tickers. Without one, matching falls back to the bare ticker symbol,
  which almost never appears literally in a headline — several bank stocks scored zero News
  points every single scan despite real articles existing about them. Added the missing entries.
- **Fundamental:** a daily cap on how many stocks' fundamental data could refresh was still set
  for the model's original, much smaller watchlist — nowhere near enough for the current, larger
  one, so some stocks' fundamental data was going stale indefinitely. Raised the cap.
- **Sentiment:** a temporary outage at one data provider was zeroing out a sentiment sub-score
  for every stock while it was down, with no fallback. Added a short-term cache that now falls
  back to the last successful reading instead.
- **Seasonality:** the model was reading its seasonal-calendar settings under the wrong internal
  name, so it silently ignored the real, calibrated settings and used generic hardcoded values
  instead — some of which pointed in the opposite direction of the real settings. Corrected the
  name. (This fix later turned out to be incomplete — see v2.2.30.)
- **Tested and reverted (no real effect found at the time):** two other scoring-setting tweaks
  were tried and produced identical results before and after — not kept. (One of these was later
  re-tested against a bigger sample and did turn out to help — see v2.2.29.)

**Backtest:** Qualifying trades ticked up slightly, but the test still fails its safety bar
overall — this update fixes real bugs and data gaps, not the deeper reason too few trades qualify
in the first place (a separate, bigger question, addressed starting in v2.2.29). 707 tests pass
(was 706), 3 skipped.

**Approved:** [pending]

---

## [v2.2.27] — 2026-07-29 — [Data Source] Added a signal for big tech companies cutting chip-related spending

**Status:** Live. Extends v2.2.26's work — no new scoring category, no weight/threshold change.

**In short:** Added a way to catch big tech companies (Amazon, Microsoft, Google, Meta) signaling
they're cutting back on AI/chip-related spending, straight from their own official filings —
before it shows up in general news.

**Problem:** The official-filings feed added in v2.2.26 only ever contains generic boilerplate
text, never real company commentary — the actual numbers live one step deeper, in an attached
press release. Big tech's spending on AI infrastructure is a major demand driver for semiconductor
stocks, and shows up in these filings before it reaches general news — but that deeper text was
never actually being read.

**Fix:** Built a way to locate and read the attached press release inside each of these four
companies' filings, pull out short snippets around spending-related terms, and fold that into the
News score for every semiconductor stock. Also added spending-cut-related keywords to the
breaking-news safety check, so a real spending pullback gets flagged the same way a tariff or
export-ban headline already does. Added 15 new tests.

**Backtest:** N/A — same as v2.2.26, no historical archive of this data exists yet to test
against. 707 tests pass (was 696), 3 skipped.

**Approved:** [pending]

---

## [v2.2.26] — 2026-07-29 — [Data Source] Started reading companies' official SEC filings as a news source

**Status:** Live. New free source folded into existing News scoring — no weight/threshold change.

**In short:** Started treating companies' own official regulatory filings as a News source,
since they're often more reliable and immediate than articles written about them after the fact.

**Problem:** A company's own official filing is about as authoritative and immediate as news gets
— but nothing in the model read it. Identified as a real, unfilled gap in what the News category
draws on.

**Fix:** Built a way to fetch each stock's recent official filings and extract a readable summary
of what changed, and folded it in as a fifth News source (alongside the four already in use).
Given the highest credibility rating of any source, since it's the company's own disclosure, not
someone else's reporting on it. Also added to the list of always-critical sources for the
breaking-news safety check. Added 10 new tests.

**Backtest:** N/A — no historical archive of this data exists yet to test against, same as later
added for Seeking Alpha/StockTwits. 696 tests pass (was 686), 3 skipped.

**Approved:** [pending]

---

## [v2.2.25] — 2026-07-29 — [Bug Fix] An incomplete, still-forming stock price could sneak into the model's math

**Status:** Live. Data-integrity fix only.

**In short:** Fixed a bug where an incomplete "today" stock price — one that hasn't finished
forming yet during pre-market hours — could sneak into the model's stop-loss and target-price
math.

**Problem:** Every request for today's price data made during market hours includes a
still-forming, incomplete entry for the current day — its closing price genuinely doesn't exist
yet. Live: an early-morning scan logged a missing closing price for every single watchlist stock.
It resolved itself an hour later once the data caught up, but feeding a missing/incomplete price
into stop-loss and target math is a real risk regardless of how quickly it resolves itself.

**Fix:** The data-fetching code now trims off any still-forming "today" row before using the
data. Added a backup check further downstream that raises a clear error if a missing price ever
slips through anyway, instead of silently scoring on it. Added 7 new tests.

**Backtest:** N/A — only affects live/paper trading's real-time data fetch; the historical test
doesn't run during live market hours. 686 tests pass (was 679), 3 skipped.

**Approved:** [pending]

---

## [v2.2.24] — 2026-07-28 — [Sector Rollout] Turned on healthcare stocks for practice trading

**Status:** Live. Healthcare stocks now actively scanned alongside semiconductors and regional
banks. Still practice money only — no version of this model has ever been approved for real
trading.

**In short:** Turned on a third group of stocks (healthcare) for practice trading, joining the
two groups already running.

**Problem:** Healthcare had already been tested as research-only and looked promising, but the
remaining blocker to actually turning it on for real (practice) trading was a shared daily limit
on paid data calls — adding 6 more stocks risked exceeding it. Two earlier changes already fixed
that: one data source is now called far less often, and another has a daily cap regardless of
watchlist size — so a bigger watchlist no longer means a bigger daily bill.

**Fix:**
- Added 6 healthcare stocks to the real, live watchlist. The code already supported multiple
  sectors generically, so this was mostly a settings change.
- Added healthcare-specific breaking-news keywords (drug rejections, failed trials, recalls) so a
  serious healthcare event only blocks healthcare stocks, not the whole watchlist.
- Gave healthcare its own position limit, separate from the other two groups. Total position
  limit across all three groups increased accordingly.

**Backtest:** Unchanged from the earlier research result — still well short of the bar needed to
trade real money. This only expands what practice trading watches. 679 tests pass (one updated
for the new group count).

**Approved:** [pending]

---

## [v2.2.23] — 2026-07-28 — [Feature] Started recording near-miss opportunities to learn from

**Status:** Live. The real trading bar stays at 90 — nothing changed there. This just makes the
model also evaluate (never act on) stocks scoring 60-89, purely to build a bigger research
dataset.

**In short:** Started quietly recording data on decent-but-not-quite-good-enough opportunities
too, purely to learn from them — they're never treated as real trade signals.

**Problem:** Real, qualifying signals are rare — zero in over 9 days of practice trading.
Waiting for enough real signals to properly judge some recent improvements would take far too
long.

**Fix:** Added a lower threshold (60) that triggers the model to fully evaluate a stock — what
trade structure it would pick, expected value — without it counting as a real signal or ever
reaching the real trade log or an alert.

**Backtest:** N/A — the historical test doesn't use this part of the code. 679 tests pass, 3
skipped.

**Approved:** [pending]

---

## [v2.2.22] — 2026-07-28 — [Feature] The model can now actually check an options trade's risk profile

**Status:** Live. Doesn't touch the trading score or 90-point threshold — only affects which
specific options trade gets picked once a stock already qualifies.

**In short:** The model can now actually check whether an options trade's risk profile makes
sense, instead of skipping that check entirely like it always claimed to do.

**Problem:** A safety check meant to filter out overly risky options trades had said "not
implemented" since it was first written, because the real market data needed for it was being
fetched and then thrown away right after a quick summary calculation. Two trades could look
equally good on paper while one secretly depended on time or volatility working out in a very
specific way — with no way to tell them apart. Two related checks (a liquidity check and a
volatility-history check) were also silently broken or missing real data.

**Fix:** Kept the real market data around instead of discarding it, and used it to build a
working version of all three checks: a real risk-profile filter for most trade types (complex
ones are deliberately left alone, since one data snapshot can't represent them accurately), a
working liquidity check, and a real volatility-history reading instead of always assuming an
average value. Also fixed a bug where missing data was being read as real-but-empty instead of
being properly skipped. Added 47 new tests.

**Backtest:** N/A — the historical test only checks the buy/sell signal itself, not which
specific options trade gets picked. 679 tests pass (was 638), 3 skipped.

**Approved:** [pending]

---

## [v2.2.21] — 2026-07-28 — [Infrastructure] One news service is now called only when something looks urgent

**Status:** Live. Only changes how often a news service gets called — no scoring impact.

**In short:** One particular news service, which has a strict daily call limit, is now only
called to double-check something that already looks serious — instead of being called
automatically and routinely for every single stock, which was wasting its limited daily budget.

**Problem:** That service has a strict daily call limit shared across several features. It was
being called automatically for every stock on every scan, whether or not anything newsworthy had
happened — and on one particular day, most of that budget got burned on calls that came back
rate-limited instead of returning anything useful.

**Fix:** The model now checks its free news sources first, every scan, and only spends a call to
this limited service when a free source already flagged something serious worth double-checking.

**Backtest:** N/A — a live API-usage change only; the historical test doesn't model daily call
budgets. 638 tests pass (was 637), 3 skipped.

**Approved:** [pending]

---

## [v2.2.20] — 2026-07-28 — [Infrastructure] Fixed misleading reports and reconnected a disconnected self-correction system

**Status:** Live. No scoring weight or threshold change — measurement tools, a reporting fix, and
reconnecting a dormant feature to the right data.

**In short:** Fixed a report that made "we don't have enough data yet" look identical to "the
strategy is failing," and discovered a planned self-correction system had been quietly
disconnected from real data the whole time. Reconnected it (though it still isn't switched on).

**Problem:** A review of real practice-trading results found scores were consistently coming in
well below the qualifying threshold — but the pass/fail reporting couldn't distinguish "not
enough data yet" from "genuinely underperforming," making it impossible to know how serious that
actually was. Digging into why also revealed a planned system meant to compare fresh results
against how the model was originally trained had been silently reading and writing to files that
nothing in the live system actually used.

**Fix:** Fixed the misleading report so the two situations are now told apart. Reconnected the
self-correction system to real, live data — though it stays switched off until it has enough real
data to trust; confirmed this reconnection alone doesn't change any live score. Also removed a
leftover, unused settings file that falsely appeared to be part of the real scoring logic.

**Backtest:** N/A — no scoring weight or threshold changed. 637 tests pass (was 582), 3 skipped.

**Approved:** [pending]

---

## [v2.2.19] — 2026-07-28 — [Data Source] Switched one earnings data point to a free source

**Status:** Live. Data-source change only — the earnings score formula itself is unchanged.

**In short:** Switched one small piece of earnings data over to a free source, since the paid
one it was using kept silently hitting its daily limit.

**Problem:** One paid data source's earnings calls had been silently failing every time — a real
daily limit on the account, not a bug. Investigating found only one of four earnings sub-scores
actually needed that source's extra depth; the rest worked fine on a free alternative.

**Fix:** Switched the non-critical piece to a free source, and limited the piece that genuinely
needs the paid source's depth to only run for brand-new stocks or right around a real earnings
date — cutting how often the paid source gets called by roughly 95%.

**Backtest:** N/A — the earnings formula itself is unchanged, only where the numbers come from.
582 tests pass (was 573), 3 skipped.

**Approved:** [pending]

---

## [v2.2.18] — 2026-07-26 — [Research] Tested the strategy on an unrelated group of stocks (healthcare)

**Status:** Live code, research-only — nothing about the real trading watchlist changed.

**In short:** Tested the strategy on healthcare stocks — a group with nothing in common with the
two already tested — just to check it isn't secretly only working because of one shared factor.
It held up well.

**Problem:** The two sectors already tested (semiconductors and regional banks) both move with
the same interest-rate cycle, so their agreement was weaker proof of a real, general edge than it
first looked — they could just be reacting to the same underlying factor. Healthcare stocks move
on different triggers (drug approvals, trial results), making it a cleaner test of whether the
strategy actually generalizes.

**Fix:** Downloaded 13 years of price history for 6 healthcare stocks and ran the same historical
test, purely for research. Not added to live trading yet.

**Result**

| Sector | Trades | Win rate | Avg R:R |
|---|---|---|---|
| Semiconductors | 54 | 61.1% | 1.89 |
| Regional banks | 46 | 54.4% | 1.63 |
| Healthcare | 41 | 63.4% | 1.31 |
| **All three combined** | **141** | **59.6%** | **1.63** |

Healthcare's win rate held up just as well as the other two — a good sign this isn't just a
rate-cycle coincidence — though its typical payout per win was smaller. Logged as new evidence,
not used to retune anything.

**Approved:** MrKoods — 2026-07-26

---

## [v2.2.17] — 2026-07-26 — [Backtest Methodology] Replaced an unrealistically strict pass/fail bar with a smarter one

**Status:** Live. Still not eligible for real money — this changes *how* pass/fail is measured,
not what passes. Required a fresh backtest since it changes the pass/fail rule itself.

**In short:** The old rule for "is this good enough to trade real money" was so strict that
almost no realistic strategy could ever pass it. Replaced it with a smarter, statistics-based
version that accounts for how much data actually exists.

**Problem:** The old bar (a flat win rate and payout ratio) implied a level of consistency far
beyond what this — or most — trading strategies ever show, even in a great year. A flat
percentage also can't tell a real edge apart from a small sample that just got lucky.

**Fix:** Replaced the flat bar with a statistical confidence check on the strategy's actual
expected return per trade — a stricter, more honest test that accounts for how much data exists,
not just a raw percentage. Applied the same new rule to practice trading's own pass/fail check.

**Backtest:** Still fails — but for a clearer, more honest reason than before: the underlying
signal looks statistically real, there just isn't enough of it yet (not enough qualifying trades,
and the risk-adjusted return is still below the bar). 566 tests pass (was 559), 3 skipped.
Applied to practice trading too on 2026-07-27 — it now correctly reports "not enough trades yet"
instead of a misleading pass/fail. 573 tests pass, 3 skipped.

**Approved:** MrKoods — 2026-07-26 (practice-trading extension: [pending])

---

## [v2.2.16] — 2026-07-26 — [Research] Checked whether two scoring categories secretly measure the same thing

**Status:** Live. Pure measurement plus a process rule — no scoring/threshold change, no backtest
needed.

**In short:** Double-checked that two of the model's five scoring categories weren't secretly
measuring the same underlying thing, which would make the model look more diversified than it
really is. They aren't — the worry didn't hold up.

**Problem:** Repeated rounds of tuning against the same historical sample risked quietly
overfitting to it. Before locking in a rule against further tuning, it was worth checking a
related worry: is part of the model's apparent "5 independent categories" an illusion, since the
historical test's stand-in for public sentiment is itself built from price movement — the same
data the technical category already uses directly?

**Fix:** Built a tool to directly measure how correlated the two categories' scores actually are,
and made an existing informal rule official: no historical data from before this date may be used
again to tune entry settings going forward.

**Result:** The worry didn't hold up — the two categories were only weakly related, well below a
level that would signal real double-counting. Re-checked later against real live data with the
same result. 573 tests pass (was 566), 3 skipped.

**Approved:** MrKoods — 2026-07-26

---

## [v2.2.15] — 2026-07-26 — [Feature] The model now double-checks urgent headlines immediately

**Status:** Live. Only changes when a scan spends a limited API call — no scoring impact.

**In short:** If a serious headline turns up, the model now double-checks it with an independent
source right away, instead of waiting up to 13 hours for the next scheduled check.

**Problem:** One limited data source was normally only checked once a day, so a genuinely
serious event flagged by a free, always-on source could sit unconfirmed for up to 13 hours.

**Fix:** A serious flagged headline now immediately triggers one independent double-check call,
instead of waiting for the next scheduled scan.

**Backtest:** N/A — a live/paper timing change, not something the historical test can replay.
559 tests pass (was 553), 3 skipped.

**Approved:** MrKoods — 2026-07-26

---

## [v2.2.14] — 2026-07-26 — [Data Source / Infrastructure] Counted one more news source toward the real score; engineering cleanup

**Status:** Live. Adds a fourth live-only News source — no weight/threshold change. The
engineering cleanup has no scoring effect at all.

**In short:** Started counting one more news source toward the model's actual score (it was
already being read, just not counted), and did some behind-the-scenes engineering cleanup —
automated testing, and splitting up an overgrown file that had caused more bugs than any other.

**Problem:** With no automated testing, a bad change only got caught if someone remembered to
test it by hand. A 951-line file had accumulated more bugs than anywhere else in the project by
doing too much in one place. Separately, one news source was already being fetched for free every
scan but only used to detect breaking news, not counted toward the actual News score — leaving
that score weaker than it needed to be.

**Fix:** Started counting that source toward the real News score. Split the oversized file into
three smaller, focused ones with no behavior change. Added automated testing that runs on every
code change, and locked dependency versions so an outside library update can't silently change
behavior unnoticed.

**Backtest:** No effect — no historical archive of that news source exists, so this path doesn't
run during the historical test. Re-ran it anyway to confirm nothing else broke: results were
consistent with the prior run. 553 tests pass (was 552), 3 skipped.

**Approved:** MrKoods — 2026-07-26

---

## [v2.2.13] — 2026-07-24 — [Data Source / Bug Fix] Sped up news reactions, saved an API call, stopped fake test data leaking into real logs

**Status:** Live. Affects how fast the model reacts to breaking news, and one small data source —
not the scoring formula.

**In short:** Sped up how quickly the model reacts to breaking news, swapped one paid data point
for a free equivalent, and stopped test runs from quietly writing fake entries into real log
files.

**Problem:** Investigating why practice trading kept missing news that only showed up hours
later found a real, measured delay: one key data source was normally only checked once a day.
Separately, running the automated tests had been quietly writing fake entries into the real
production log files for a long time — one log file turned out to be almost entirely test noise.

**Fix:** A free, always-on news source now also feeds the breaking-news detector immediately,
closing that detection gap. Alerts now show when a story actually broke, not just when the alert
was sent. Swapped one paid data point for the same information from a free source. Isolated
automated tests from the real log files so they stop writing fake data into them.

**Backtest:** N/A — none of this changes the scored News total or the earnings formula, only
detection speed and data source for minor pieces.

**Approved:** MrKoods — 2026-07-24

---

## [v2.2.12] — 2026-07-23 — [Infrastructure] Spread a weekly data refresh across the week

**Status:** Live. Scheduling change only — no scoring impact.

**In short:** A weekly data-refresh task used to run for every stock all at once; now it's spread
across the week instead, to avoid risking a daily data-call limit.

**Problem:** As the watchlist grows to cover more stocks, refreshing all of them in one burst
risks blowing through a shared daily data-call limit in a single night.

**Fix:** Each stock now gets its own day of the week for its refresh, with stocks near their
earnings date prioritized, and a daily cap on how many refresh at once.

**Backtest:** N/A — scheduling only, doesn't change the underlying scoring formula.

**Approved:** MrKoods — 2026-07-23

---

## [v2.2.11] — 2026-07-20 — [Bug Fix] Adding more stock groups could make some of them silently stop getting fresh data

**Status:** Live. Bug fix — no scoring impact.

**In short:** Found and fixed a bug where, once more than one group of stocks was active, some
stocks could silently stop getting fresh data without anyone noticing.

**Problem:** Data-freshness tracking used a single shared "last updated" timestamp for the whole
file, rather than one per stock. With more than one group active, a group processed later in the
same run would see an earlier group's timestamp and wrongly assume its own stocks were already
up to date — even though they'd never actually been refreshed. Left unfixed, this could have
silently left an entire new group's data stale indefinitely, with no error to flag it.

**Fix:** Freshness is now tracked per stock, instead of one shared timestamp for everything.

**Backtest:** N/A — only affects live/paper data-fetch tracking, a part of the code the
historical test doesn't use.

**Approved:** MrKoods — 2026-07-20

---

## [v2.2.10] — 2026-07-19 — [Sector Rollout] Turned on regional bank stocks for practice trading

**Status:** Live. Regional bank stocks now scanned alongside semiconductors. Still practice money
only — no version of this model has ever been approved for real trading.

**In short:** Turned on a second group of stocks (regional banks) for practice trading, after
confirming the code correctly keeps the two groups from interfering with each other.

**Problem:** Before turning on a second group, a direct review found several places in the code
had hidden assumptions that only one group of stocks would ever be active — mixed data across
groups, wrong comparison benchmarks, one shared limit instead of separate ones per group. Fixed
in the previous two entries; with those confirmed fixed and tested, the second group could safely
go live.

**Fix:** Turned on regional bank stocks alongside semiconductors — nearly doubling the watchlist.
The desktop app now groups results by sector. Re-ran the historical test to confirm nothing
changed unexpectedly, and built a new test that runs a full two-group scan end-to-end to confirm
the groups genuinely don't interfere with each other.

**Backtest:** Unchanged from the earlier research result — still well short of the bar needed to
trade real money. This only expands what practice trading watches. 536 tests pass (was 532).

**Approved:** MrKoods — 2026-07-19

---

## [v2.2.9] — 2026-07-19 — [Bug Fix] A leftover bug — one stock group was still accidentally averaged in with another

**Status:** Live. Regional banks are still switched off, so this only matters once that's turned
on.

**In short:** A bug that was supposed to be fixed in the last update actually wasn't — one group
of stocks' valuation comparison was still accidentally blending in another group's numbers.

**Problem:** Double-checking the previous entry's work found it had described a fix to a
valuation comparison but never actually made it — it was still averaging every group's stocks
together. Left unfixed, this would have blended two very different groups' typical valuations
into one meaningless average the moment both had data — the exact problem the previous entry was
supposed to prevent.

**Fix:** Fixed the comparison to only average stocks within the same group. Checked every other
scoring category directly and confirmed none of them had the same bug.

**Backtest:** N/A — no live effect while the second group stays switched off. Verified with new
tests instead. 532 tests pass (was 529).

**Approved:** MrKoods — 2026-07-19

---

## [v2.2.8] — 2026-07-19 — [Infrastructure] Behind-the-scenes prep work for safely adding a second group of stocks

**Status:** Live. The real watchlist is unchanged — still just the original 6 semiconductor
stocks. This entry only builds the groundwork to safely support a second group later.

**In short:** Before turning on a second group of stocks, did a direct review and found — and
fixed — several hidden bugs that would have quietly broken the moment a second group was simply
added.

**Problem:** The plan was to actually add a second group of stocks live, based on earlier
evidence the strategy works beyond just semiconductors — but a direct review first found multiple
places that assumed only one group would ever exist and would have silently produced wrong
results the moment that changed: mismatched comparison benchmarks, blended valuations, and a
breaking-news block that would have covered every group instead of just the one it was about.

**Fix:** Fixed all of the places found with this hidden assumption. Position limits are now
tracked separately per group instead of one shared pool. Also restricted one paid news source to
being called only once a day per stock instead of more often, since a bigger, two-group watchlist
at the old calling pattern would have blown through its daily limit.

**Backtest:** N/A for this groundwork — confirmed to change nothing, via 529 passing tests with
zero regressions.

**Approved:** MrKoods — 2026-07-19 (turning the second group on was deliberately left for a
later, separate entry)

---

## [v2.2.7] — 2026-07-19 — [Backtest Methodology] The historical test now accounts for interest rates and the dollar's strength

**Status:** Live. This only fixes a gap in the historical test — live/paper trading was already
accounting for this.

**In short:** The historical performance test was ignoring interest rates and the dollar's
strength the whole time, even though live trading already accounted for them. Fixed the
historical test to match.

**Problem:** The strategy performed noticeably worse in recent history than in earlier years.
Investigating found a real pattern: good stretches lined up with falling or low interest rates,
and poor stretches lined up with rising or high rates — a well-known effect (cheap money favors
this kind of strategy; rising rates make price action choppier). Live trading had already
accounted for this for a while, but the historical test always pretended it was neutral for every
single simulated trade.

**Fix:** Fixed the historical test to use real historical interest-rate and dollar-strength data
instead of pretending it was always neutral.

**What it showed:** Recent stretches that used to fail now pass. The strategy never once
produced a qualifying trade during an unfavorable rate environment in the corrected test —
confirming the fix filters out weak setups exactly when it should.

**Backtest:** Win rate improved, still not enough qualifying trades to pass the bar. Not eligible
for real trading — trade count, not win rate, is the blocker.

**Approved:** MrKoods — 2026-07-19

---

## [v2.2.6] — 2026-07-19 — [Backtest Methodology / Research] Fixed a grading bug, adopted a better filter, tested a second stock group

**Status:** Live. The filter change is backtest-methodology only. The real safety bar for going
live is untouched by this entry.

**In short:** Found and fixed the real reason the strategy had never once passed its internal
stability check — the test windows used were simply too short. With that fixed, a previously
rejected filter idea turned out to actually be the best one tested, and the strategy was
confirmed to also work on a second, unrelated group of stocks.

**Problem:** The strategy had never once passed its rolling stability check. Investigating found
the real cause was a testing bug, not a real weakness: the test periods were too short for how
rarely this strategy actually fires, so almost every period simply didn't have enough trades to
judge fairly.

**Fix:** Lengthened the test periods substantially — with that fix, most periods now had enough
data to judge fairly. Re-tested an entry-filter idea that had earlier looked unhelpful — that
earlier read turned out to be distorted by the same too-short-periods bug; with the fix, it's the
best-performing filter change tested, so it was adopted. Also tested regional bank stocks as a
second, unrelated group purely as research, to check whether the strategy's edge is real and
general, or just a coincidence specific to semiconductors.

**Combined result (both groups, with the adopted filter)**

| | Trades | Win rate | Avg R:R |
|---|---|---|---|
| Semiconductors only | 53 | 64.2% | 1.82 |
| Regional banks only | 51 | 52.9% | 1.73 |
| **Combined** | **104** | **58.7%** | **1.78** |

A real, modest, positive edge that holds up across two unrelated stock groups — more convincing
than semiconductor-only evidence could ever be on its own.

**Decision: paused further tuning.** Five rounds of tweaking the filter against the same
historical sample risked overfitting to it. The current filter is treated as settled; real new
practice-trading data is the next real test, not more historical tuning.

**Backtest:** Still not enough qualifying trades to pass on the single-group slice alone. The
combined two-group result above is the more meaningful number and the actual basis for adopting
this filter.

**Approved:** MrKoods — 2026-07-19

---

## [v2.2.5] — 2026-07-19 — [Backtest Methodology] Tightened a filter based on solid evidence, even though one headline number got worse

**Status:** Live. Backtest-methodology change only — doesn't touch live/paper scoring.

**In short:** Tightened one entry filter after solid evidence showed it clearly helped overall —
even though, on the one specific test slice used as the official headline number, this same
change made results look worse. Both facts are reported here rather than only the favorable one.

**Problem:** A losing trade was typically taking much longer to resolve than a winning one — a
sign of entering too late in a move, not of fast false starts. Testing this properly, pooled
across many independent time periods (not just the one official test slice, to avoid fooling
itself), showed tightening one particular cutoff clearly improved win rate across the broader
sample.

**Fix:** Tightened that cutoff.

**Backtest:** The official single-slice number got worse with this change — fewer qualifying
trades, lower win rate on that one slice. Already not eligible for real trading before this
change either way. The real basis for adopting it is the broader, pooled evidence, not this one
slice, which the previous "Problem" section explains.

**Approved:** MrKoods — 2026-07-19 (adopted knowing the single-slice headline number got worse,
based on the broader evidence)

---

## [v2.2.4] — 2026-07-19 — [Backtest Methodology] Fixed a broken tool and discovered the strategy has never passed its own internal check

**Status:** Live. Tooling/analysis fix only — no scoring or threshold impact.

**In short:** A tool meant to answer "is the 90-point bar set correctly?" turned out to have been
silently broken the entire time. Fixed it — and in the process, discovered the strategy has never
once passed its own internal stability check either.

**Problem:** Checking whether the qualifying-score threshold was set sensibly required running a
tool that had a bug making it silently return meaningless results every single time it had ever
been run — so nobody could actually see the real answer.

**Fix:** Fixed the tool, and made an existing internal stability check (that had been computed
all along but never actually reviewed) get surfaced and read. Separately tried adding one more
requirement to the entry filter — it looked better on the one official test slice, but that's
exactly the kind of coincidence the official slice can be fooled by, so it wasn't adopted without
broader confirmation.

**What the fix revealed:** the qualifying-score threshold barely matters across a wide range —
meaning a stricter cutoff alone won't help; the scoring itself needs to get better at ranking
candidates. Separately, the internal stability check has never once passed — most test periods
simply don't have enough trades to judge fairly (fixed in the next entry).

**Backtest:** N/A for this entry specifically — the headline result is unchanged; only the
previously-broken tools now work and reveal real facts about the model.

**Approved:** MrKoods — 2026-07-19

---

## [v2.2.3] — 2026-07-19 — [Bug Fix] Fixed a setting that was silently ignored, and stopped one warning sign counting three times

**Status:** Live.

**In short:** Found two separate bugs while investigating a quiet stretch: one setting was being
silently ignored, and one warning sign was effectively being counted three times over for the
same underlying reason.

**Problem:** Investigating why practice trading had produced zero qualifying signals found two
issues. First, one setting was never actually being read due to a naming mismatch, so it had
silently been using a generic default the whole time. Second, three separate penalties were all
firing together, all tracing back to the exact same underlying market condition, stacking into an
unfairly large combined penalty regardless of any individual stock's own merit.

**Fix:** Fixed the naming mismatch so the real setting is now actually used. Reduced one of the
three overlapping penalties to zero, since it was found to duplicate the other two.

**Backtest:** N/A — the historical test doesn't model this particular setting. All 500 tests
pass (497 passed, 3 skipped).

**Approved:** MrKoods — 2026-07-19

---

## [v2.2.2] — 2026-07-19 — [Bug Fix] A full code review found and fixed 24 separate problems

**Status:** Live. Several of these fixes changed real scoring/risk calculations (called out
below), so this isn't just a cleanup pass.

**In short:** A full code review turned up 24 separate problems across the codebase — some
cosmetic, some serious enough to have quietly affected real numbers (including one that made a
previously-reported "great" result actually wrong). All 24 were fixed.

**Problem:** A full code review was requested. It surfaced 24 separate issues across six areas —
most consequential: a risk-adjusted-return calculation was wrong, which had inflated a
previously-reported headline number that must no longer be trusted.

**Fix** — grouped by area:
- **Historical-test accuracy** — Fixed the trade-counting order (was scrambling the
  performance-over-time picture), fixed the wrong risk-adjusted-return calculation described
  above, fixed the test losing its first couple of months to warm-up with zero chance of a trade,
  and fixed the test using today's live data for the entire multi-year replay instead of only
  what would have actually been known at each point in time.
- **Scoring accuracy** — Fixed several places scores could be subtly wrong: missing data reading
  as "bad" instead of "unknown," an overly harsh cliff for earnings declines that ignored how
  severe the decline actually was, a safety cap that could be silently skipped, sentiment trusting
  a single data point too much, three different and disagreeing ways of counting insider trades,
  and a bug that could mistake a garbled source name for a trusted one.
- **Risk and execution enforcement** — A documented minimum payout-ratio filter and a liquidity
  filter were being calculated but never actually enforced, so a bad-risk trade could still get
  recommended. Also fixed: position sizing silently exceeding its own cap, two same-direction
  trades able to open on the same stock, bad price data able to produce backwards stop-loss/
  target levels, and a safety brake that was being skipped during elevated (not extreme) market
  volatility.
- **Self-correction system** — A safety check meant to catch a bad recalibration was comparing a
  number to itself and could never actually fail. Fixed. A scoring setting that had been defined
  but never actually used was properly wired in.
- **Dead code removed** — Deleted an old module that could never actually do anything (nothing
  ever fed it real data), and finished a previously-unfinished feature (not yet turned on for
  live use).
- **Reliability/security** — API keys are now stripped out of error messages before they get
  logged (previously an error could leak a live key into a log file in plain text). Two data
  calls that weren't being counted against a daily budget now are. Critical files now save
  safely, without risk of corruption if interrupted mid-write. Fixed a bug that mislabeled the
  cause of a failed scan.

**Backtest:** Ran fresh against real historical data — still fails the bar for going live
(win rate and payout ratio both fall short), though it did pass the minimum-trade-count check.
The corrected risk-adjusted-return number is meaningfully different from what was previously
reported, and the earlier number should no longer be cited. Not eligible for real trading.

**Approved:** MrKoods — 2026-07-19 (code changes only; the backtest still failed, not approved
for real trading)

---

## [v2.2.1] — 2026-07-18 — [Infrastructure] Removed email/text alerts — Discord and the app are the only channels now

**Status:** Live. Infrastructure simplification — no scoring impact.

**In short:** Removed email and text-message alerts, since Discord and the desktop app already
cover the real need and the extra channels were just ongoing upkeep for a guarantee that isn't
needed yet.

**Problem:** The project is still practice-trading only, with no real money at risk, so the
"must never miss an alert" reason for having backup alert channels doesn't apply yet. Maintaining
those extra channels was ongoing overhead for a guarantee not currently needed.

**Fix:** Removed email and text-message alerts entirely, along with the logic that decided which
channel to use. Discord (plus the desktop app's own notification feed) is now the only channel.

**Backtest:** N/A — alert delivery only, no effect on scoring or trade selection.

**Approved:** MrKoods — 2026-07-18

---

## [v2.2.0] — 2026-07-18 — [Feature] Added a heads-up alert for stocks that almost, but didn't quite, qualify

**Status:** Live. A new notification type, not a scoring change.

**In short:** Added a low-key alert for a stock that scores close to, but just under, the real
90-point trading bar — so a near-miss is at least visible, instead of looking identical to a
stock scoring nowhere close.

**Problem:** Reviewing a day's real scan results showed the 90-point cutoff was an all-or-nothing
cliff with zero visibility — a score of 89 and a score of 12 looked exactly the same (invisible)
from outside the system.

**Fix:** Added a clearly-labeled "not a trade signal" alert for a stock scoring 80-89. Also added
a log note for when two related penalties both fire in the same scan, since they're driven by the
same underlying cause — informational only, not auto-corrected.

**Backtest:** N/A — new alert type and logging only, no effect on scoring or trade selection.

**Approved:** MrKoods — 2026-07-18

---

## [v2.1.5] — 2026-07-17 — [Bug Fix] One interruption during a data refresh could throw away a lot of finished work

**Status:** Live. Reliability fix — no scoring impact.

**In short:** One manual interruption during a weekly data refresh accidentally threw away
several stocks' worth of already-finished work, because progress was only saved once, at the
very end. Now it saves as it goes.

**Problem:** Found the fundamentals data 11 days stale. Traced it to a manual interruption
partway through a refresh — because the old code only saved once at the very end, that single
interruption threw away everything that had already successfully finished, with no warning
anywhere. The interruption itself was a one-off, but the all-or-nothing save was a real weakness
that could recur from any crash, network drop, or data-limit hit mid-refresh.

**Fix:** The weekly refresh now saves progress after every single stock completes, instead of
only once the whole batch finishes.

**Backtest:** N/A — reliability fix only, no effect on scoring or trade selection.

**Approved:** MrKoods — 2026-07-17

---

## [v2.1.4] — 2026-07-16 — [Scoring Change] Stopped one extreme stock from skewing its whole sector's average score

**Status:** Live. This one does change a real scoring calculation, so it's flagged carefully.

**In short:** One stock's unusually distorted valuation was dragging up the entire sector's
"average," making every other stock in that sector look artificially cheap by comparison. Now
extreme outliers are excluded before averaging.

**Problem:** Found three stocks all hitting the maximum possible fundamental score at the same
time — investigating showed one stock's valuation ratio was wildly inflated by a temporary
earnings drop, dragging the whole sector's "average" up and making everyone else look
artificially cheap. With only a handful of stocks in each sector, one distorted number doesn't
just mis-score itself — it quietly biases every comparison in that sector.

**Fix:** The valuation score now excludes statistical outliers before averaging, instead of
letting one distorted value skew the whole sector's comparison. Confirmed against real data: the
fix corrected the sector average and spread scores back out realistically.

**Backtest:** Inherited the same not-yet-passing status as before — verified directly against
real current data instead of a fresh full re-run.

**Approved:** MrKoods — 2026-07-16

---

## [v2.1.3] — 2026-07-16 — [Bug Fix] One old news story could keep blocking the entire watchlist forever

**Status:** Live. Bug fix plus logging — no scoring impact.

**In short:** A 6-day-old news story was re-triggering a fresh safety block on the entire
watchlist every single day, because the whole-sector version of that check never aged out old
articles the way the single-stock version already did. Fixed — and score logs are now more
complete too.

**Problem:** Left unfixed, that one headline could have kept re-blocking the whole watchlist
indefinitely. Separately, real scan data showed every stock's score dropping in lockstep on the
same day, which couldn't be explained without seeing the shared background factors alongside each
stock's individual score.

**Fix:** The breaking-news block now correctly ages out old articles for whole-sector triggers,
the same way it already did for single-stock ones. Score logs now also show all six shared
background factors, not just the five main category scores.

**Backtest:** N/A — bug fix and logging only. The fix was verified directly against the real
headline that caused it.

**Approved:** MrKoods — 2026-07-16

---

## [v2.1.2] — 2026-07-15 — [Infrastructure] Started logging every stock's score, not just the ones that qualified

**Status:** Live. Logging-only change — no scoring impact.

**In short:** On the first full day of practice trading, nothing qualified — meaning there was
zero record of what any stock had actually scored. Now every stock's full score gets logged
every scan, regardless of outcome.

**Problem:** With zero record of what didn't qualify, it was impossible to check whether the
scoring categories were even working sensibly.

**Fix:** Added a log line showing every stock's full score breakdown on every scan.

**Backtest:** N/A — logging only.

**Approved:** MrKoods — 2026-07-15

---

## [v2.1.1] — 2026-07-15 — [Feature] A serious news event now shows a trade signal with a warning, instead of hiding it

**Status:** Live. Doesn't affect the existing not-yet-eligible status either way.

**In short:** A serious breaking-news event used to hide a qualifying trade signal completely.
Now it shows the signal with a clear warning attached, so a person can make the final call
instead of the system deciding silently on their behalf.

**Problem:** During early practice trading, a real breaking-news event blocked the entire
watchlist for a scan. Hiding every signal outright during an active event risks hiding a
genuinely good opportunity along with the bad ones.

**Fix:** A serious breaking-news event no longer hides a qualifying trade signal — it now shows
up normally, with a clear warning attached.

**Backtest:** Inherited the same not-yet-passing status, unaffected by this change. The
historical data used for testing has no real breaking-news events in it, so this specific change
can't be tested against history either way.

**Approved:** MrKoods — 2026-07-15 (practice-trading behavior change; not approved for real
trading)

---

## [v2.1.0] — 2026-07-14 — [Feature] Added a safety switch that can hide a trade signal during a serious news event

**Status:** Not yet eligible to go live — see Backtest below.

**In short:** Added a safety switch that can hide a stock's trade signal if a seriously damaging
news story breaks about it (a scandal, fraud allegations, and similar) — even if its score would
otherwise qualify.

**Problem:** The scoring system has a real blind spot: news only makes up a small slice of the
total score, so a genuinely severe, fast-moving story can be outvoted by four much slower-moving
categories that haven't caught up yet.

**Fix:** Added a safety mechanism that can block a stock from surfacing as a trade signal when a
serious, damaging news event is detected — a separate safety layer, not a change to how News
itself is scored. It only ever hides a signal, never boosts one, and automatically expires after
a set cooling-off period. Deliberately one-directional — the goal is avoiding a bad trade, not
chasing a shock headline that already confirms good news.

**Backtest:** Not run, and can't be meaningfully tested with the currently available historical
data — it doesn't include real events like these to test against. Not eligible for real trading
until a real backtest is run and passes.

**Approved:** Pending — do not go live on this version until a backtest is run and passes.

---

## [v2.0.0] — 2026-07-13 — [Scoring Change] Added a whole new scoring category and switched how the model reads public mood

**Status:** Not yet eligible to go live — see Backtest below.

**In short:** Added a brand-new scoring category based on options activity, ownership changes,
and insider trading, and switched the service used to gauge public sentiment to a better one.

**Problem:** The prior public-sentiment source had become unreliable with no clear fix in sight.
Separately, real signals like options activity, big ownership changes, and insider trading
weren't being captured by the model at all — and insider trading data was accidentally being
counted twice over.

**Fix:** Added a new scoring category covering options activity, ownership changes, short
interest, insider trading, and analyst ratings. Switched to a better, clearly-tagged public
sentiment source. Fixed the insider-trading double-count by folding it into the new category.
Rebalanced how many points each category is worth to make room for the new one.

**Backtest:** Not run yet — there's no historical data yet for the new source or category; both
need to build up real history from this point forward. Not eligible for real trading until a real
backtest is run and passes.

**Approved:** Pending — do not go live on this version until a backtest is run and passes.

---

## [v1.0.0] — 2026-06-29 — [Infrastructure] The very first version

**Status:** Basic structure built, but almost none of the real logic was written yet.

**In short:** The starting point — the project's skeleton was laid out, with a rough plan for
how scoring would work, but almost nothing was actually implemented yet.

**What's in this version**
- The full project structure, matching the original design plan.
- Every planned build phase stubbed out as placeholders.
- A first-draft scoring formula and a framework for ranking different trade structures.
- Position-sizing and safety-brake rules defined, but not yet proven.

**What's not built yet**
- The real scoring logic, real profit/loss projections, and any historical testing. Every
  setting at this point is just a starting guess, not yet proven by testing.

**Backtest:** N/A — no backtest has been run yet; this version is scaffolding only.

**Approved:** MrKoods — 2026-06-29

---

<!-- Template for future entries:

## [vX.Y.Z] — YYYY-MM-DD — [Category] Short description

**Status:** ...

**In short:** One plain-English sentence — no jargon, no file names. What happened and why it
matters, in words anyone could understand.

**Problem:** What was wrong or missing, and why it mattered.

**Fix:**
- ...

**Backtest:** Run date: YYYY-MM-DD. Win rate: X%. Avg R:R: 1:X. Qualifying trades: N.

**Approved:** ...

-->
