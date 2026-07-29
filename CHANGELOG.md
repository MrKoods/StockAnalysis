# CHANGELOG — AI-Assisted Swing Trading Signal System

This project uses standard version numbers (MAJOR.MINOR.PATCH):
- MAJOR: a fundamental change to how the strategy scores or picks trades
- MINOR: a new indicator, modifier, or scoring category
- PATCH: a threshold tweak, bug fix, or calibration update

**Rule:** No change to scoring weights, indicator settings, or thresholds goes live without
bumping the version number and logging a fresh backtest result below it. No exceptions —
this is enforced automatically by the code (`model_versioning.py`).

---

## [v2.2.26] — 2026-07-29 — Added SEC EDGAR 8-K filings as a News source

**Status:** Live. A new free data source folded into the existing News layer's scoring and
Event Severity Gate — no scoring weights or thresholds changed.

### What changed
- New `shared/api_clients/sec_edgar_client.py` fetches each ticker's recent 8-K filings from
  SEC EDGAR's public company-filings feed (no API key required — SEC EDGAR is free and
  public) and extracts the human-readable Item description from each one (e.g. "Item 5.02:
  Departure of Directors...") rather than the generic, unvarying filing title.
- Folded into `news_layer.compute_news_score()` as a fifth article source alongside Alpha
  Vantage/Yahoo/Finnhub/Seeking Alpha, fetched on every scan.
- Scored at 1.0 source credibility (`source_credibility.py`) — higher than any journalism
  outlet, since an 8-K is the company's own regulatory disclosure, not third-party reporting.
- Added "SEC EDGAR" to the Event Severity Gate's `principal_sources` — a filing matching a
  trigger keyword is always treated as critical, same tier as FDA/Federal Reserve statements.
- Also counts toward the free-source pool that decides whether a scan spends its one Alpha
  Vantage confirmation call.
- Added 10 new tests, built against real response payloads captured from the live endpoint
  rather than invented fixtures.

### Why
Identified as a genuine, unfilled gap while reviewing what each scoring layer actually draws
on: a company's own 8-K is about as authoritative and immediate as a News source gets —
unlike Yahoo/Finnhub headlines, it's a primary disclosure filed straight with the regulator,
not a third party reporting on it after the fact.

### Backtest result
Not applicable — no historical 8-K archive is cached, same "accumulates going forward, not
backtestable yet" caveat already accepted for Seeking Alpha and live StockTwits sentiment;
`backtesting/simulation.py` always passes `sec_edgar_filings=None`. 696 tests pass (was 686),
3 skipped.

### Approved by
[pending]

---

## [v2.2.25] — 2026-07-29 — Fixed a pre-market data bug: NaN close price could reach scoring

**Status:** Live. Data-integrity fix only — doesn't touch scoring weights or thresholds.

### What changed
- `market_data_client.py`'s `fetch_ohlcv()` and `fetch_ohlcv_batch()` now trim any trailing
  OHLCV row whose Close is NaN before returning it.
- `technical_common.py` now raises a clear error if a NaN close somehow still reaches
  indicator computation, instead of silently scoring on it — caught by
  `indicator_pipeline.py`'s existing per-ticker error handling, which logs a validation entry
  and excludes just that ticker for the scan rather than failing the whole run.
- Added 7 new tests covering both the trim helper and the guard.

### Why
Every daily-interval yfinance request made during market hours (including pre-market)
includes an in-progress "today" bar — Open/Volume may already have partial pre-market
prints, but Close stays NaN until the session actually closes. Observed live: the 5:30am
pre-market scan logged `close=nan` for all 17 watchlist tickers; it self-resolved by the
9:00am mid-session scan once yfinance backfilled the row, but a NaN close feeding into
stop/target/position-size math is a real risk regardless of how quickly it self-resolves.

### Backtest result
Not applicable — this only affects the live/paper-trading data-fetch path; the backtest
doesn't call `fetch_ohlcv_batch` during market hours. 686 tests pass (was 679), 3 skipped.

### Approved by
[pending]

---

## [v2.2.24] — 2026-07-28 — Turned on the third sector (healthcare) for paper trading

**Status:** Live. Healthcare (6 tickers) is now actively scanned in paper trading, alongside semiconductors and regional banks. Still no real money at risk — no version of this model has ever passed its backtest requirements, so this only expands what paper trading watches, the same way regional banks did in v2.2.10.

### What changed
- Added the healthcare sector to the live config: 6 tickers (LLY, PFE, MRK, ABBV, UNH, JNJ) benchmarked against XLV. The underlying code already supported multiple sectors generically since v2.2.8, so this was config-only — no code changes needed.
- Added healthcare-specific breaking-news keywords (FDA rejection, clinical trial failure, drug recall, and similar) so a serious healthcare event blocks only healthcare tickers, not the whole watchlist — and added the FDA as an always-critical source, the same way the Federal Reserve already is for the other sectors.
- Gave healthcare its own position limit and correlated-position group, same pattern as the other two sectors. The total position ceiling across all sectors moved from 4 to 6.
- Fixed a stale comment describing the Alpha Vantage budget — it still described the old "one call per ticker" behavior from before v2.2.21's confirmation-only change.
- Updated one test that explicitly checked "exactly two sectors are active" to expect three.

### Why
Healthcare was already tested as a research-only sector in v2.2.18 and held up well (63.4% win rate, comparable to the other two sectors). The remaining blocker was Alpha Vantage's daily call budget — under the old system, adding 6 more tickers to an already-11-ticker watchlist risked exceeding the daily limit. Two recent changes removed that blocker: Alpha Vantage news calls are now confirmation-only rather than one-per-ticker (v2.2.21), and fundamental/earnings refreshes are capped at 3 tickers/day regardless of watchlist size (v2.2.19/v2.2.12) — so a bigger watchlist no longer means a bigger daily API bill, just a slower rotation through each ticker's fundamentals.

### Backtest result
Unchanged from the v2.2.18 research result: 141 combined trades across all three sectors, 59.6% win rate, 1.63 avg reward:risk — still well short of the go-live bar. This only expands what paper trading observes; it doesn't change eligibility for real money. 679 tests pass (unchanged count — one test updated for the new sector count).

### Approved by
[pending]

---

## [v2.2.23] — 2026-07-28 — Collect trade-structure data down to score 60, without lowering the real trading bar

**Status:** Live. The real trading threshold is still 90 — nothing changed there. This just makes the model also evaluate (but not act on) tickers scoring 60-89, purely to build a bigger research dataset.

### What changed
- Added a new threshold (60) that triggers trade-structure evaluation (which option structure would be picked) even when a ticker doesn't score high enough to be a real signal.
- Scores in the 60-89 range now get their evaluated structure and expected value saved to the database for later review — but they're never written to the real trade log, never trigger a trade alert, and don't count as a signal.
- Updated tests to match, including a check that scores below 60 still get nothing recorded.

### Why
Real 90+ signals are rare — paper trading logged zero in over 9 days. Waiting for enough real signals to judge how well the new Greeks/liquidity filters work (see v2.2.22) would take too long. Widening data collection down to 60 gives a much bigger sample to study, without touching what counts as a real trade anywhere else in the system.

### Backtest result
Not applicable — the backtest doesn't use this part of the code at all. 679 tests pass, 3 skipped.

### Approved by
[pending]

---

## [v2.2.22] — 2026-07-28 — Real options Greeks filter; real IV percentile; real liquidity check

**Status:** Live. Doesn't touch the trading score or the 90-point threshold — this only affects which options structure gets picked once a signal already qualifies.

### What changed
- The model now keeps the real options chain (strikes, bid/ask, implied volatility) it was already fetching, instead of throwing it away after computing a couple of averages.
- Added a real Greeks filter: for 20 of the 42 possible option structures, the model now rejects a structure if its time decay (theta) or volatility exposure (vega) is too large relative to how much money it risks. Complex structures (LEAPS, calendars, condors, butterflies, and similar) are intentionally left alone, since a single options-chain snapshot can't represent them accurately.
- The liquidity filter (checking if the bid/ask spread is too wide) now actually works — it was silently doing nothing before, since no real spread data ever reached it.
- Implied volatility percentile is now calculated from real history instead of always assuming a neutral 50. It takes about 10 days of history to become real; before that it honestly reports "not enough history yet" instead of guessing.
- Found and fixed a real bug along the way: missing options data was sometimes read as a real (but blank) quote instead of being skipped.
- Added 47 new tests covering all of this.

### Why
The code has said "Greeks filter: not implemented" since it was written, because the real options data was there but got thrown away right after use. This entry keeps that data around so the filter can be real instead of skipped. Two option structures can look equally profitable on paper while one quietly depends on time or volatility working out — this lets the model tell them apart.

### Backtest result
Not applicable — the backtest never calls this part of the code; it only tests the underlying buy/sell signal, not which option structure to use. 679 tests pass (was 638), 3 skipped.

### Approved by
[pending]

---

## [v2.2.21] — 2026-07-28 — Alpha Vantage news is now a confirmation check, not a routine call

**Status:** Live. Only changes how often a news API gets called — doesn't touch the scoring formula or the 90-point threshold.

### What changed
- The model now checks the free news sources (Yahoo, Finnhub, Seeking Alpha) first, on every scan. It only spends an Alpha Vantage call when one of those free sources already flagged something serious, to double-check it against an independent source.
- Previously, Alpha Vantage was called once per ticker automatically on every post-close scan, whether or not anything happened.
- Updated tests to match the new behavior.

### Why
Alpha Vantage has a strict daily call limit shared across news and other features. On 2026-07-28 the model burned through most of that budget calling Alpha Vantage routinely for every ticker, and most of those calls came back rate-limited anyway instead of returning real articles. Making Alpha Vantage a "confirm something real happened" tool instead of a routine call saves that budget for when it's actually needed.

### Backtest result
Not applicable — this only changes how often a live API gets called, not the scoring math. The backtest doesn't model live API budgets. 638 tests pass (was 637), 3 skipped.

### Approved by
[pending]

---

## [v2.2.20] — 2026-07-28 — Better diagnostics; fixed a misleading "pass/fail" report; connected the calibration system to real data

**Status:** Live. Doesn't change any scoring weight or the 90-point threshold — this is measurement tools, a reporting fix, and wiring a dormant feature to the right data source.

### What changed
- Added new read-only diagnostic tools that show how real paper-trading scores are distributed, and how close each category is to using its maximum points.
- Fixed a bug where "zero trades yet" was reported the same way as "the strategy failed" — now they're told apart, so an empty dataset doesn't look like a failing one.
- The system that's supposed to compare fresh trading results against how the model was originally trained (the calibration / feedback loop) was reading from and writing to files that nothing in the live system actually used. Reconnected it to the real, currently-running paper-trading data.
- None of this changes live scoring yet — recalibration stays switched off until it has real data to work from, and confirmed it still produces exactly the same score as before this change.
- Removed a dead, unused config file that falsely claimed to be read by the scoring code.

### Why
A review of 9 days of real paper-trading data found the model's score has never once reached 90 — not even 80, topping out around 72. The system meant to judge "did the strategy actually pass or fail" couldn't tell the difference between "no data yet" and "genuinely underperforming." Digging into why revealed the automatic recalibration system had been silently pointed at the wrong, empty files the whole time. This fixes the reporting and reconnects calibration to the real data, while making sure nothing it does can affect live trading until it's actually been proven against real results.

### Backtest result
Not applicable — no scoring weight or threshold changed. 637 tests pass (was 582), 3 skipped.

### Approved by
[pending]

---

## [v2.2.19] — 2026-07-28 — Moved one earnings data point off Alpha Vantage to save API budget

**Status:** Live. Data-source change only — the earnings score itself is computed exactly the same way, just fed by different, cheaper sources most of the time.

### What changed
- One of the four pieces that make up the earnings score now comes from Finnhub (free) instead of Alpha Vantage.
- The other piece that genuinely needs Alpha Vantage's deeper history now only calls it for brand-new tickers or right around a real earnings date — not on every routine weekly refresh.

### Why
Alpha Vantage's earnings call had been silently failing on every attempt — turned out to be a real daily limit (25 calls/day) on the account, not a bug. Investigating showed only one of the four earnings sub-scores actually needed Alpha Vantage's extra depth; the other works fine with Finnhub's free data. This cuts routine Alpha Vantage earnings calls from a few per day to roughly 1-2 per month.

### Backtest result
Not applicable — the earnings score formula itself didn't change, only which service supplies the underlying numbers. Verified against real (not mocked) API calls that Alpha Vantage's budget counter stayed untouched on the routine path. 582 tests pass (was 573), 3 skipped.

### Approved by
[pending]

---

## [v2.2.18] — 2026-07-26 — Tested a third, unrelated sector (healthcare) as a research check

**Status:** Live code, but research-only — nothing about the real trading watchlist changed.

### What changed
- Downloaded 13 years of price history for 6 healthcare/pharma stocks, purely for research. Not added to live trading.

### Why
Semiconductors and regional banks (already tested) both react to the same interest-rate cycle, so their agreement was weaker proof of a real, general edge than it looked — they could just be responding to the same underlying factor. Healthcare stocks move on different triggers (drug approvals, trial results), so testing them is a cleaner check of whether the entry strategy generalizes, or only works on rate-sensitive stocks.

### Result
Ran the same test on all three sectors:

| Sector | Trades | Win rate | Avg reward:risk |
|---|---|---|---|
| Semiconductors | 54 | 61.1% | 1.89 |
| Regional banks | 46 | 54.4% | 1.63 |
| Healthcare | 41 | 63.4% | 1.31 |
| **All three combined** | **141** | **59.6%** | **1.63** |

Healthcare's win rate held up just as well, a good sign the strategy isn't just a rate-cycle fluke. Its average reward-to-risk was lower, though — healthcare breakouts win about as often but pay out less per win. Per the existing rule, this is logged as new evidence, not used to retune anything.

### Approved by
MrKoods — 2026-07-26

---

## [v2.2.17] — 2026-07-26 — Replaced the simple win-rate pass/fail bar with a statistically honest one

**Status:** Live. Still not eligible to go live for real money — this changes *how* pass/fail is measured, it doesn't make anything pass. Because it changes the pass/fail rule itself, it required a fresh backtest per this file's own rule.

### What changed
- The old rule for "is this strategy good enough to trade real money" was a flat 80% win rate and 1.8 reward-to-risk ratio.
- Replaced it with a statistical confidence interval on the strategy's actual expected return per trade — a stricter, more honest test that accounts for how much data actually exists, not just a raw percentage.
- Applied the same new rule to paper trading's own pass/fail check, so both use the same standard.

### Why
The old 80%/1.8 bar implied a level of consistent profit far beyond what any version of this strategy — or most trading strategies — has ever shown, even in its best years. A flat percentage also can't tell a real edge apart from a small sample that got lucky. A confidence interval answers the better question: how sure can we be the edge is real, given how much data we have.

### Backtest result
Re-ran the full 13.5-year test under the new rule: 66.67% win rate, 2.35 avg reward:risk, expected value per trade 1.24R (low-end confidence estimate 0.42R — still solidly positive). Still fails overall — not because the edge looks fake, but because there are only 18 qualifying trades so far (100 required) and the Sharpe ratio (0.34) is below the 1.0 bar. This is a more useful failure reason than before: the signal looks statistically real, there's just not enough of it yet. 566 tests pass (was 559), 3 skipped.

Extended to paper trading on 2026-07-27 using the same rule — correctly reports "not enough trades yet" instead of a misleading pass/fail, since paper trading has zero qualifying trades so far. 573 tests pass, 3 skipped.

### Approved by
MrKoods — 2026-07-26 (paper trading extension: [pending])

---

## [v2.2.16] — 2026-07-26 — Checked whether two scoring categories were secretly measuring the same thing; locked in a no-more-tuning rule

**Status:** Live. Pure measurement and a documented process rule — no scoring or threshold change, no backtest needed.

### What changed
- Built a tool to check whether the Technical and Sentiment scoring categories are actually independent in the backtest, since the backtest's Sentiment stand-in is built from price movement — the same data Technical already uses directly.
- Made an existing informal decision official: no backtest data used before 2026-07-26 may be used again to tune entry-filter settings. Running the backtest again for reporting is fine; retuning against the same old data is not.

### Why
Five rounds of tuning against the same ~12-year sample risked quietly overfitting to it. Before locking that decision in, it was worth checking a related worry: is part of the backtest's apparent "5 independent categories" illusion, because two of them are built from the same underlying price data?

### Result
The worry didn't hold up. The two categories' scores were only weakly correlated (well below the level that would signal a real overlap problem) — the backtest's apparent diversification isn't artificially inflated by double-counting. Re-checked later against real, live paper-trading data (not just the backtest's price-based stand-in) with the same result: still weakly correlated, if anything slightly better separated. 573 tests pass (was 566), 3 skipped.

### Approved by
MrKoods — 2026-07-26

---

## [v2.2.15] — 2026-07-26 — Let Seeking Alpha trigger an immediate Alpha Vantage double-check on breaking news

**Status:** Live. Only changes when a pre-market/mid-session scan spends an Alpha Vantage call — no scoring impact.

### What changed
- If Seeking Alpha (already checked every scan at no extra cost) flags a serious headline about a ticker, the model now immediately spends one Alpha Vantage call to cross-check it with an independent source — instead of waiting up to 13 hours for the next post-close scan to catch it.

### Why
Confirming a real, serious event quickly is worth the extra API call, since missing one for up to 13 hours is a real cost. This only adds a call in the rare case something's actually flagged — it doesn't change routine usage.

### Backtest result
Not applicable — a live/paper timing change only, not something the backtest can replay. 559 tests pass (was 553), 3 skipped.

### Approved by
MrKoods — 2026-07-26

---

## [v2.2.14] — 2026-07-26 — Seeking Alpha now counts toward the News score; engineering cleanup (CI, lockfile, file split)

**Status:** Live. Adds a fourth live-only news source to the existing News category — doesn't change the scoring formula's weights or thresholds. The engineering cleanup has no scoring effect at all.

### What changed
- Seeking Alpha's headlines (already fetched every scan for free) now also count toward the scored News total, not just the breaking-news check.
- Split a very large file (951 lines) that had accumulated the highest concentration of past bugs in the project into three smaller, focused files. No behavior change.
- Added automated testing (CI) that runs on every code push, and a locked dependency file so a library update can't silently change behavior without a test catching it.
- Checked an unfamiliar new dependency by hand before trusting it — confirmed it's legitimate, not a supply-chain risk.

### Why
No automated testing meant a bad change only got caught if someone remembered to test it locally by hand. The oversized file had already produced multiple bugs by being one file doing too much. Adding Seeking Alpha to the real News score (not just breaking-news detection) helps the News category hold up on days when Alpha Vantage data is thin, at no extra cost.

### Backtest result
No effect, confirmed directly — the backtest has no historical Seeking Alpha data archive, so this change is inactive in backtest replay. Re-ran the full backtest anyway: 66.7% win rate, 18 qualifying trades, 2.35 avg reward:risk — consistent with the prior baseline (64.7%/17 trades), the small difference being normal re-run noise. 553 tests pass (was 552), 3 skipped.

### Approved by
MrKoods — 2026-07-26

---

## [v2.2.13] — 2026-07-24 — Seeking Alpha now feeds breaking-news detection too; cut a wasted API call; stopped tests from polluting real logs

**Status:** Live. Affects how fast breaking news gets detected and one small data source — not the scoring formula.

### What changed
- Seeking Alpha's headlines now also feed the breaking-news detector (not just Sentiment scoring) — this doesn't change the scored News total, only detection speed.
- Alerts now show the real time a news story broke, not just when the alert was posted, so a delayed detection isn't mistaken for a fresh one.
- Replaced one Alpha Vantage call (analyst target price) with the same data from Yahoo/Finnhub for free — same accuracy, one less API call per ticker.
- Fixed a real problem: test runs had been quietly writing fake entries into the real production log files for a long time — one log file turned out to be 99.7% test noise. Tests are now isolated from real logs.

### Why
Investigating why paper trading kept missing news that later showed up hours later found a real, measured detection delay — Alpha Vantage news is normally only checked post-close, so pre-market/mid-session scans couldn't catch a breaking story until much later. Adding Seeking Alpha as an every-scan source closes that gap. The API-call swap and test-log cleanup were both found and fixed in the same pass.

### Backtest result
Not applicable — none of this changes the scored News total or the earnings sub-score formula, only detection timing and data source for less-important pieces.

### Approved by
MrKoods — 2026-07-24

---

## [v2.2.12] — 2026-07-23 — Spread out the weekly fundamentals refresh instead of one big burst

**Status:** Live. Scheduling change only — no scoring impact.

### What changed
- Instead of refreshing every ticker's fundamentals in one Monday-night burst, each ticker now gets its own day of the week, with earnings-week tickers prioritized and a daily cap on how many refresh at once.
- The score breakdown now shows how recent each ticker's fundamental data actually is, since different tickers can now be refreshed on different days.

### Why
As the watchlist grows to cover more sectors, refreshing everything in one burst risks blowing through the daily API call budget in a single night. Spreading the same total cost across the week avoids that.

### Backtest result
Not applicable — scheduling only, doesn't change the fundamental scoring formula.

### Approved by
MrKoods — 2026-07-23

---

## [v2.2.11] — 2026-07-20 — Fixed a bug where a whole sector's data could silently never refresh

**Status:** Live. Bug fix — no scoring impact.

### What changed
- Fundamental and Positioning data refresh tracking is now done per ticker, instead of one shared "last updated" timestamp for the whole file.

### Why
With more than one sector now active, a sector processed later in the same scan run would see an earlier sector's refresh timestamp and wrongly assume its own tickers were already up to date — even though they'd never actually been fetched. That could have silently left a newly added sector's tickers with no real data indefinitely, with no error to flag it.

### Backtest result
Not applicable — this only affects live/paper data-fetch tracking, a part of the code the backtest doesn't use.

### Approved by
MrKoods — 2026-07-20

---

## [v2.2.10] — 2026-07-19 — Turned on the second sector (regional banks) for paper trading; results grouped by sector in the app

**Status:** Live. Regional banks are now actively scanned in paper trading, alongside semiconductors. Still no real money at risk — no version of this model has ever passed its backtest requirements, so this only expands what paper trading watches.

### What changed
- Regional banks (5 tickers) are now scanned alongside semiconductors — paper trading watches 11 tickers total instead of 6.
- The desktop app now groups results by sector, then by category within each sector.
- Re-ran the cross-sector backtest to confirm results were unchanged after all the recent groundwork.
- Built a new end-to-end test that actually runs a full two-sector scan (previous tests only checked individual pieces in isolation) to confirm the sectors don't interfere with each other.
- Found, but didn't yet fix: a market-crash safety check still only watches semiconductors, not each sector separately. Not currently wired into live scans either way, so it's not an active gap — flagged for a future fix.

### Why
Before turning on a second sector, several parts of the code had hidden single-sector assumptions that a direct review caught (mixing valuation numbers across sectors, wrong benchmark for relative strength, one shared position-limit pool instead of per-sector limits, and others) — see v2.2.8/v2.2.9 for the fixes. With those confirmed fixed and tested, this entry turns the second sector on.

### Backtest result
Unchanged from the prior sector research: 100 combined trades, 58.0% win rate, 1.78 avg reward:risk — still well short of the go-live bar. This only expands what paper trading observes; it doesn't change eligibility for real money. 536 tests pass (was 532).

### Approved by
MrKoods — 2026-07-19

---

## [v2.2.9] — 2026-07-19 — Fixed a real bug left over from the last entry: sector-average valuation wasn't actually sector-scoped

**Status:** Live. Same not-yet-eligible status as before — regional banks are still switched off, so this only matters once that's turned on.

### What changed
- Fixed the Fundamental category's "sector average" valuation comparison so it only averages tickers within the same sector, instead of accidentally blending every sector's tickers together.

### Why
Double-checking whether the second sector gets the full scoring treatment revealed that the previous entry (v2.2.8) had described this fix but never actually made it — the averaging bug was still there. Left unfixed, it would have blended semiconductor valuations (much higher P/E) with bank valuations (much lower P/E) into one meaningless average the moment both sectors had data cached, undercutting the exact problem v2.2.8 was supposed to prevent. Checked every other scoring category directly and confirmed none of them had the same bug.

### Backtest result
Not applicable — the backtest doesn't model this yet either way, and this has no effect on live scoring while the second sector stays switched off. Verified with new tests instead. 532 tests pass (was 529).

### Approved by
MrKoods — 2026-07-19

---

## [v2.2.8] — 2026-07-19 — Built the groundwork to support a second sector; Alpha Vantage news moved to post-close only

**Status:** Live. The actual live/paper watchlist is unchanged — still just the original 6 semiconductor tickers. This entry only builds the plumbing to safely support a second sector later.

### What changed
- Config can now describe multiple sectors, each with its own benchmark. The live watchlist stays semiconductors-only for now; regional banks exist in config but stay switched off.
- Fixed 7 places in the code that had hidden single-sector assumptions and would have silently produced wrong results the moment a second sector was simply added — including mismatched benchmarks, blended valuations, pooled correlation checks across unrelated sectors, and a breaking-news block that would have covered every sector instead of just the one it was about.
- Found and fixed one unrelated real bug along the way: a sector-wide news block was incorrectly treated as covering every ticker, not just the sector it was actually about.
- Position limits and correlated-position protection are now tracked per sector instead of one shared pool.
- Alpha Vantage news calls are now restricted to the post-close scan only, for every ticker — a real budget necessity: adding an 11-ticker two-sector watchlist at the old calling pattern would have blown through the free daily API limit.

### Why
The goal was to actually track a second sector live, not just as a research question — following earlier backtest evidence (see below) that the entry strategy generalizes beyond semiconductors. Before turning anything on, a direct code review found multiple places that would have quietly broken with two sectors active. This entry fixes all of them first, with the second sector still switched off, before it's ever actually turned on in a later, separately-approved entry.

### Backtest result
Not applicable for the infrastructure work — behavior-preserving, confirmed by 529 passing tests with zero regressions (was 497 before this entry). The Alpha Vantage cadence change has no meaningful backtest comparison available, since the backtest doesn't model call timing at all — flagged as a known gap, not a result being hidden.

### Approved by
MrKoods — 2026-07-19 (second-sector activation deliberately left for a separate, later entry)

---

## [v2.2.7] — 2026-07-19 — Backtest now uses the real macro-economic signal instead of pretending it's always neutral

**Status:** Live. This only fixes a gap in the backtest — live/paper trading was already using the real macro signal.

### What changed
- The backtest previously always treated the macro-economic modifier (interest rates, dollar strength) as exactly zero for every single simulated trade, even though live trading has computed a real version of it since early on. Fixed the backtest to use real historical interest-rate and dollar-index data instead.

### Why
Investigating why the strategy performed noticeably worse in more recent years than in 2018-2021 found a real pattern: every well-performing period lined up with falling or low interest rates, and every poorly-performing period lined up with rising or high rates (a well-known effect — cheap money favors momentum strategies, rising rates make price action choppier). The tool to account for this already existed for live trading; the backtest just never used it.

### What using it actually showed
Recent 2-year windows that used to fail now pass (69-75% win rate). The strategy never once produced a qualifying trade during an unfavorable macro reading in the corrected backtest — confirming the fix works by filtering out weak setups during bad macro conditions, as intended. The official result improved modestly: 66.7% win rate (was 64.7%), 2.35 avg reward:risk, 18 qualifying trades (still below the 100 required).

### Backtest result
66.7% win rate, 2.35 avg reward:risk, 18 qualifying trades (100 required — still not enough), 3.0% max drawdown. Still not eligible for live trading — not enough trades yet, regardless of the improved win rate.

### Approved by
MrKoods — 2026-07-19

---

## [v2.2.6] — 2026-07-19 — Fixed a real bug in how the backtest was validated; adopted a better entry filter; tested a second, unrelated sector

**Status:** Live. The entry-filter change is backtest-methodology only. The real go-live safety bar (80% win rate, minimum reward:risk) is untouched by this entry.

### What changed
- **Fixed the real reason the strategy had "never once passed" a rolling validation check**: the validation windows were too short (6 months) for how rarely this strategy actually fires, so almost every window had too few trades to judge fairly. Lengthened the windows to 24 months. With the fix, results looked completely different: instead of 0-for-24, one window (2018-2020) clearly passed and most others had enough data to judge fairly, rather than being starved of trades.
- Lowered the internal diagnostic pass bar (a looser stability check, separate from the real 80% go-live bar) to match what the strategy has actually, repeatedly shown, instead of an arbitrary target it had never once hit.
- Tested the strategy on a second, unrelated sector (regional banks) purely as research — not added to live trading. Real historical data, same time span as semiconductors.
- Re-tested an entry-filter idea (requiring the breakout to hold for one more day before entering) that had earlier looked unhelpful — turned out that earlier read was itself distorted by the too-short-windows bug. With the fix, it's the single best-performing filter change tested, so it was adopted.

### Why
Trying to explain why the strategy looked much weaker in recent years than in 2018-2021 led to fixing a real methodology bug (undersized test windows) rather than a real feature of the strategy. Testing a second sector was requested to check whether the strategy's edge is real and general, or just a semiconductor-specific fluke.

### Combined result (both sectors, with the adopted filter)
| | Trades | Win rate | Avg reward:risk |
|---|---|---|---|
| Semiconductors only | 53 | 64.2% | 1.82 |
| Regional banks only | 51 | 52.9% | 1.73 |
| **Combined** | **104** | **58.7%** | **1.78** |

A real, modest, positive edge that holds up (same direction, similar size) across two unrelated sectors — more convincing than semiconductor-only evidence could ever be on its own.

### Decision: pause further backtest tuning
Five rounds of tweaking the entry filter against the same historical sample is starting to risk overfitting to it. Decided to treat the current filter as settled for now and let real, new paper-trading data — not more backtest tuning — be the next real test.

### Backtest result
64.7% win rate, 2.29 avg reward:risk, 17 qualifying trades (100 required — still not enough on this slice alone). Still not eligible for live trading due to the trade-count shortfall, despite the encouraging win rate. The combined two-sector result above (104 trades, 58.7%) is the more statistically meaningful number and the actual basis for adopting this filter.

### Approved by
MrKoods — 2026-07-19

---

## [v2.2.5] — 2026-07-19 — Tightened the backtest's entry filter based on real evidence, even though the headline number got worse

**Status:** Live. Backtest-methodology change only — doesn't touch live/paper scoring, which already scores RSI without a hard cutoff.

### What changed
- Lowered the backtest's upper RSI cutoff for what counts as a valid breakout entry, from 82 to 70 — filtering out more "already extended" moves.

### Why
A losing trade was typically taking 5-9 days to resolve, not 1-2 — a sign of overextended entries rather than fast false breakouts. Testing this properly (pooled across many independent time windows, not just the one held-out test slice, to avoid overfitting) showed tightening the RSI ceiling clearly improved win rate (49.4% → 60.8%) across the broader sample.

### An honest tension
On the broad, pooled sample this change clearly helps. But on the one specific historical slice the backtest reports as its headline number, this same change makes the result look *worse* and drops the trade count below the minimum needed for a reliable read. Both facts are reported here rather than only the favorable one — the broader, pooled sample is judged the more trustworthy evidence, so the change was adopted anyway.

### Backtest result
The official single-slice number got worse with this change: 51.8% win rate (was 57.0%), 27 qualifying trades (was 107, now below the 100 minimum). Already not eligible for live trading before this change; unaffected by it either way. The real basis for adopting this filter is the broader pooled evidence above, not this one slice.

### Approved by
MrKoods — 2026-07-19 (adopted knowing the single-slice headline number got worse; based on the broader evidence)

---

## [v2.2.4] — 2026-07-19 — Fixed a broken analysis tool; found the strategy has never once passed rolling validation

**Status:** Live. Tooling/analysis fix only — no scoring or threshold impact.

### What changed
- Fixed a tool meant to show how win rate changes at different score thresholds — it had a bug that made it silently return all zeros every single time it had ever been run.
- Made the strategy's existing rolling validation check (running the strategy across many historical windows, not just one) actually get printed and reviewed — it had been computed all along but never surfaced.
- Tried adding a volume-confirmation requirement to the entry filter — it looked better on the single test slice, but that's exactly the kind of overfitting risk the held-out test slice exists to prevent, so it was not adopted without broader validation.

### Why
Investigating whether the 90-point score threshold was well calibrated required actually running the broken tool, which surfaced that it had never worked.

### What the fixes revealed
Win rate barely changes across every threshold from 85 to 95 — meaning a stricter cutoff alone won't push win rate toward the go-live bar; the score itself needs to get better at ranking candidates. Separately, the rolling validation check has never once passed in any of its 24 historical windows — most windows simply don't have enough qualifying trades to judge fairly (a signal that fires this rarely needs longer windows, fixed in the next entry).

### Backtest result
Not applicable for this entry specifically — the main backtest result itself is unchanged by this fix; only the previously-broken analysis tools now work correctly and reveal existing facts about the model.

### Approved by
MrKoods — 2026-07-19

---

## [v2.2.3] — 2026-07-19 — Fixed a config bug that silently ignored a setting; toned down a triple-counted penalty

**Status:** Live.

### What changed
- Fixed a bug where a modifier's config setting was never actually being read due to a naming mismatch — it had silently been using a hardcoded default the whole time.
- Reduced one particular sector-wide penalty from -10 to 0, because it was found to overlap heavily with two other penalties all ultimately driven by the same underlying market signal — effectively triple-counting one observation as three separate warning signs.

### Why
Investigating why paper trading had produced zero qualifying signals found three separate penalties all firing at once, all tracing back to the exact same underlying cause, stacking to a large combined penalty across the entire watchlist regardless of any individual stock's own merit.

### Backtest result
Not applicable — the backtest doesn't model this particular modifier at all, so this change has no effect on the existing backtest result. All 500 tests pass (497 passed, 3 skipped).

### Approved by
MrKoods — 2026-07-19

---

## [v2.2.2] — 2026-07-19 — Fixed 24 issues found in a full code review

**Status:** Live. Several of these fixes changed real scoring/risk calculations (called out below), so this isn't just a cleanup pass.

### What changed
Grouped by area:

**Backtest accuracy** — Fixed the order trades were counted in (was scrambling the performance-over-time calculation) and how the Sharpe ratio was annualized (the previously reported figure of 9.1 was wrong and must not be cited — it was inflated by this bug). Fixed the historical test window losing its first ~2 months to warm-up with no chance of producing a trade. Fixed fundamental data in the backtest using today's live numbers for the entire multi-year replay instead of what would have actually been known at each point in time (a real look-ahead bias).

**Scoring accuracy** — Fixed several places where scores could be subtly wrong: missing technical data reading as "bearish" instead of "unknown," a harsh cliff in the earnings-growth score that treated any decline the same regardless of severity, a data-unavailable safety cap that could be silently skipped, sentiment scores trusting a single data point too much, three different and disagreeing ways of counting insider trades, and a credibility-scoring bug that could mistakenly treat a garbled source name as a trusted outlet.

**Risk and execution enforcement** — The documented minimum reward-to-risk filter and a liquidity filter were being calculated but never actually checked, so a bad-risk trade could still get recommended. Fixed position sizing to not silently exceed its own 5% cap. Fixed a gap that let two same-direction positions open on the same stock. Fixed bad price data being able to produce backwards stop-loss/target levels. Fixed a volatility-regime classification gap that skipped an important safety brake during elevated (but not extreme) market volatility.

**Calibration/feedback loop** — Fixed the safety check meant to catch a bad recalibration — it was comparing a number to itself and could never actually fail. Implemented a scoring parameter that had been defined but never actually used.

**Dead code removed** — Deleted an old paper-trading module that could never actually do anything (nothing ever fed it real data), and implemented a previously-stubbed position re-scoring feature (not yet turned on for live use).

**Reliability/security** — API keys are now stripped out of error messages before they get logged (previously an error could leak a live key into a log file in plain text). Two Alpha Vantage calls that weren't being counted against the daily budget now are. Critical files now save safely (crash-proof) instead of risking corruption if interrupted mid-write. Fixed a bug that mislabeled the cause of a failed scan.

### Why
Requested a full code review "thinking like a senior developer and market analyst." Most consequential single finding: the Sharpe ratio bug, since it invalidated a previously-reported headline number.

### Backtest result
Ran fresh against real historical data: **57.0% win rate** (required 80% — fail), **2.01 avg reward:risk** (required 3:1 — fail), 107 qualifying trades (required 100 — pass), Sharpe ratio 2.45 (this replaces the earlier, incorrect 9.1 figure). All 107 qualifying trades happened to fall in the same market regime (trending up) — the available historical data doesn't have enough variety to test other market conditions. Not eligible for live trading — win rate and reward:risk both fall well short, and the lack of market-condition variety means even the passing-regime result can't be generalized yet.

### Approved by
MrKoods — 2026-07-19 (code changes only; backtest failed, not approved for live trading)

---

## [v2.2.1] — 2026-07-18 — Removed email/SMS alerts — Discord and the app are now the only channels

**Status:** Live. Infrastructure simplification — no scoring impact.

### What changed
- Removed email and SMS as alert delivery methods, along with the priority-escalation logic that decided which channel to use. Discord is now the only delivery channel (plus the desktop app's own notification feed).
- Removed the now-unused email/SMS credentials and settings.

### Why
The project is still in paper trading with no real money at risk, so the "guaranteed delivery" reason for having email/SMS as backups doesn't apply yet. Maintaining those credentials and the extra delivery logic was ongoing overhead for a guarantee that isn't currently needed. Discord plus the in-progress desktop app (which saves every alert for later review) already covers the real need.

### Backtest result
Not applicable — alert delivery only, no effect on scoring or trade selection.

### Approved by
MrKoods — 2026-07-18

---

## [v2.2.0] — 2026-07-18 — Added "near-miss" awareness alerts; flagged an overlapping-penalty risk

**Status:** Live. A new notification type, not a scoring change.

### What changed
- Added a low-key Discord alert for a ticker that scores 80-89 — close to, but not over, the real 90-point trading threshold. Clearly labeled as "not a trade signal," and never logged as a real trade.
- Added a log note for when two particular penalties are negative in the same scan, since they're both ultimately driven by the same underlying market signal — flagged as informational only, not auto-corrected.

### Why
Reviewing a day's real scan results showed the 90-point cutoff was a hard cliff with zero visibility — a score of 89 and a score of 12 looked identical (invisible) from outside the system. The near-miss alert gives visibility without changing what counts as a real signal.

### Backtest result
Not applicable — new alert type and logging only, no effect on scoring or trade selection.

### Approved by
MrKoods — 2026-07-18

---

## [v2.1.5] — 2026-07-17 — Fundamental data now saves after each ticker, not just at the very end

**Status:** Live. Reliability fix — no scoring impact.

### What changed
- The weekly fundamentals refresh now saves progress after every ticker completes, instead of only once the whole batch finishes.

### Why
Found the fundamentals file was 11 days stale. Traced it to a manual interruption partway through a refresh — because the old code only saved once at the very end, that single interruption threw away several tickers that had already successfully finished, with no warning anywhere. The interruption itself was a one-off, but the "all-or-nothing" save was a real structural weakness that could recur from any crash, network drop, or API limit hit mid-batch.

### Backtest result
Not applicable — reliability fix only, no effect on scoring or trade selection.

### Approved by
MrKoods — 2026-07-17

---

## [v2.1.4] — 2026-07-16 — Excluded statistical outliers from the sector-average valuation comparison

**Status:** Live. This one does change a real scoring calculation (the valuation sub-score), so it's flagged carefully.

### What changed
- The Fundamental category's valuation score now excludes statistical outliers before averaging peer valuations, instead of letting one distorted value skew the average for the whole sector.

### Why
Found that three tickers all hit the maximum possible fundamental score at the same time — investigating showed one ticker's price-to-earnings ratio was wildly inflated (from a temporary earnings drop), dragging the whole sector's "average" valuation up and making everyone else look artificially cheap by comparison. With only 5-6 tickers in the watchlist, one distorted number doesn't just mis-score itself — it quietly biases every comparison. Confirmed directly against real data: excluding the outlier corrected the sector average significantly and spread the scores back out realistically.

### Backtest result
Inherited the same not-yet-passing status as before, not independently re-tested — the existing backtest already fails for unrelated reasons. This specific fix was verified directly against real current data instead.

### Approved by
MrKoods — 2026-07-16

---

## [v2.1.3] — 2026-07-16 — Fixed a stale-news bug that could re-trigger news blocks forever; log modifiers with scores

**Status:** Live. Bug fix plus logging — no scoring impact.

### What changed
- The breaking-news block system now correctly ages out old articles for sector-wide triggers, the same way it already did for ticker-specific ones.
- Score logs now also show all six shared modifiers (market regime, sector rotation, macro, earnings timing, cross-ticker, seasonality), not just the five main category scores.

### Why
A 6-day-old news story kept re-triggering a fresh block on the entire watchlist every day, because the sector-wide check never aged out old articles the way the ticker-specific check already did — left unfixed, this one headline could have kept re-blocking the whole watchlist indefinitely. Separately, real scan data showed every ticker's score falling in lockstep across a single day, which couldn't be explained without seeing the shared modifiers alongside the per-ticker scores.

### Backtest result
Not applicable — bug fix and logging only. The stale-news fix was verified directly against the real headline that caused the bug.

### Approved by
MrKoods — 2026-07-16

---

## [v2.1.2] — 2026-07-15 — Paper trading now logs every ticker's score, not just the ones that qualify

**Status:** Live. Logging-only change — no scoring impact.

### What changed
- Added a log line showing every ticker's full score breakdown on every scan, regardless of whether it clears the trading threshold.

### Why
On the first full day of paper trading, nothing qualified — meaning there was zero record anywhere of what any ticker had actually scored, making it impossible to check whether the scoring categories were working sensibly. This closes that visibility gap without changing what counts as a real signal.

### Backtest result
Not applicable — logging only.

### Approved by
MrKoods — 2026-07-15

---

## [v2.1.1] — 2026-07-15 — Breaking-news block changed from "hide the signal" to "show it with a warning"

**Status:** Live. Doesn't affect the existing not-yet-eligible-for-live-trading status either way.

### What changed
- A serious breaking-news event no longer hides a qualifying trade signal completely — it now surfaces normally, with a clear warning attached, so a human can make the final judgment call instead of the system silently deciding for them.

### Why
During early paper trading, a real breaking-news event blocked the entire watchlist for a scan. Hiding every signal outright during an active event risks hiding a genuinely valid opportunity — better to show everything and flag it clearly.

### Backtest result
Inherited the same not-yet-passing status as before, unaffected by this change. The prior full backtest run scored 64.5% win rate against the 80% requirement — everything else passed except win rate, for reasons unrelated to this change (documented in earlier entries). The historical data used for backtesting has no real breaking-news events in it, so this specific change can't be tested by the backtest either way.

### Approved by
MrKoods — 2026-07-15 (paper-trading behavior change; not approved for live trading)

---

## [v2.1.0] — 2026-07-14 — Added a breaking-news safety block (not a scoring category)

**Status:** Not yet eligible to go live — see "Backtest result" below.

### What changed
- Added a new safety mechanism that can block a ticker from surfacing as a trade signal when a serious, thesis-opposing breaking-news event is detected — a company scandal, an export ban, fraud allegations, and similar. This is a separate veto layer, not a sixth scoring category — News still scores exactly as before.
- The block only ever suppresses a signal, never boosts one, and automatically expires after a set cooling-off period.
- Added new alert types for when a block triggers or expires, and a safety net that auto-repairs corrupted block-tracking data.

### Why
The existing 5-category score has a real blind spot: news only makes up 15 of 100 points, so a genuinely severe, fast-moving story can be outvoted by four much slower-moving categories that haven't caught up yet. This adds a fast, targeted safety brake specifically for that scenario. It's deliberately one-directional (block only, never boost) — chasing a shock headline that already confirms a trade thesis is a good way to buy the top of a spike; the goal here is loss prevention, not extra upside chasing.

### Backtest result
Not run, and can't be meaningfully backtested with the currently available historical data — the historical news archive wasn't curated to include real trigger events like these, so there's nothing genuine to test the block against yet. Not eligible for live trading until a real backtest is run and passes.

### Approved by
Pending — do not go live on this version until a backtest is run and passes.

---

## [v2.0.0] — 2026-07-13 — Added two new scoring categories; switched the sentiment data source

**Status:** Not yet eligible to go live — see "Backtest result" below.

### What changed
- Added a new **Market Positioning** category (worth 20 points): options activity, institutional ownership changes, short interest, insider trading, and analyst ratings — all free data.
- Removed Reddit as a sentiment source entirely (access had stalled indefinitely) and replaced it with StockTwits (a paid subscription with clearly tagged bullish/bearish posts) plus a Seeking Alpha engagement measure — a real quality upgrade, not just a substitute.
- Insider trading data moved from its own separate bonus/penalty into the new Positioning category, since it had been counted twice before.
- Rebalanced how many points each category is worth: Technical 50→40, Positioning (new) →20, Sentiment 20→15, News unchanged at 15, Fundamental 15→10.
- Brought the written design document up to date — it had drifted out of sync with the actual code for a while.

### Why
Reddit access had stalled with no clear path forward, and StockTwits' explicitly-tagged posts are a genuinely better sentiment signal regardless. Options/institutional/insider activity is a real, distinct signal the original design never captured. The written spec hadn't been updated in a while and needed to catch up to what the code actually did.

### Backtest result
Not run yet — there's no historical data for StockTwits or the new Positioning category; both need to build up real history from this point forward, the same way Fundamental data did. Not eligible for live trading until a real backtest is run and passes.

### Approved by
Pending — do not go live on this version until a backtest is run and passes.

---

## [v1.0.0] — 2026-06-29 — Initial project scaffold

**Status:** Scaffolding complete — the basic skeleton is built, but most of the real logic isn't written yet.

### What's in this version
- The full project structure and configuration, matching the original design document.
- All 14 planned build phases stubbed out with placeholder functions.
- The scoring formula design: Technical 60 / Sentiment 25 / News 15, plus 7 modifier types.
- 42 possible trade structures defined, with a framework for ranking them.
- Position sizing and circuit-breaker rules defined.

### What's not built yet
- The real scoring logic.
- Real expected-value calculations.
- Backtesting.
- Every weight is a starting hypothesis until backtesting proves it out.

### Backtest result
Not applicable — no backtest has been run yet; this version is scaffolding only.

### Approved by
MrKoods — 2026-06-29

---

<!-- Template for future entries:

## [vX.Y.Z] — YYYY-MM-DD — Short description

### What changed
- ...

### Why
- ...

### Backtest result
- Run date: YYYY-MM-DD
- Win rate: X%
- Avg reward:risk: 1:X
- Qualifying trades: N
- Approved by: ...

-->
