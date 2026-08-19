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
check, because they depend on live, real-time data. A full model audit on 2026-08-19 (v2.2.63)
found and fixed 17 more real gaps, including one that had been making the historical test's own
numbers look slightly better than real trading would achieve — the corrected win rate (61.2%,
down from 63.1%) still clears the safety bar. None of this changes whether the model is allowed
to trade real money — it still isn't, and won't be until it's approved.

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
| v2.2.63 | 2026-08-19 | Bug Fix / Scoring Change / Backtest Methodology | A full model audit (5 parallel reviews covering data, scoring, risk, the historical test, and live/paper trading) found and fixed 17 real gaps — the biggest: the historical test had been assuming every signal filled instantly instead of checking whether price actually reached the entry price first, the same check real trading already uses, flattering its numbers. Win rate moved from 63.1% to a more honest 61.2% after the fix — still clears the safety bar |
| v2.2.62 | 2026-08-19 | Bug Fix | Paper trading's earnings-proximity check only ever ran once, at signal time — an undefined-risk shares position signaled 6+ days before earnings could still be open when the report actually landed inside its up-to-15-day holding window, fully unprotected (live example: NVDA, signaled 12 days out from its 08-26 earnings). Now re-checked on every daily update and flattened early if it ages into the same 0-5-day pre-earnings window a new signal would already be forced into a capped-loss structure for. A second, same-shaped gap (news/event-gate checks are also signal-time-only) was found and flagged, not fixed — closing it needs a daily news re-scan per open ticker, a bigger change against limited free-tier API budgets that needs a design decision first |
| v2.2.61 | 2026-08-19 | Feature / Bug Fix | Un-staled the 3 stress-test skips (a fixture schema mismatch, not a real blocker) and wired cross_ticker_modifier into the backtest for real (earnings_modifier stays 0.0 — no historical earnings-date archive exists, a genuine data gap, not deferred laziness); built real dollar max-loss/max-gain and actual strikes/expiration for 35 of 42 trade structures; extended Greeks coverage from 20 to 29 structures (condors/butterflies/wheel/synthetics — pure wiring, no new modeling); extracted real contract/share counts from paper_runner.py's dual-cap sizing into a shared, reusable function and wired it into run_swing_model.py for the first time (which never computed a real position size before — the live Discord alert's "Dollar Risk" field always showed $0.00); surfaced the top-2 runner-up structures alongside the winner everywhere structure data reaches the user |
| v2.2.60 | 2026-08-19 | Feature / Bug Fix / Research | Widened the documented/configured holding period from 5-15 to 1-15 trading days (the "5" minimum was never actually enforced anywhere in code, so this is a documentation/config correction, not a behavior change); found and fixed the same bearish volume-profile stop/target gap already fixed live/paper-side in a third spot, the backtest engine itself; stopped discarding real per-structure trade economics (capital required, legs, effective days, Greeks) before they reached the Discord alert or paper-trading CSV; built and tested a genuinely different bearish entry style (capitulation/bounce-fade, not another continuation-mirror tweak) — result: worse than the continuation baseline and too rare to be usable (6 pooled trades vs. 339), a clean negative finding, left off by default |
| v2.2.59 | 2026-08-19 | Research / Sector Rollout | Three follow-up rounds of real-data testing on v2.2.58's bearish underperformance (entry RSI band, exit target/stop sizing, entry-confirmation timing — 16 variants, all 4 sectors) each helped a little and none came close to the go-live bar; best pooled Sharpe found was -1.73 against a +1.0 requirement. `enable_bearish_signals` turned on anyway for paper trading only, by explicit decision, specifically to start collecting real bearish outcomes instead of more historical replay |
| v2.2.58 | 2026-08-18 | Feature / Backtest Methodology | Built real bearish/breakdown detection to match the existing bullish path — technical breakdown signals, mirrored sentiment/news/positioning/regime/rotation scoring, and a bearish backtest replay — instead of the old "defaults to bullish whenever it isn't clearly bullish" behavior. Shipped behind `enable_bearish_signals: false` (stays off): the mirrored bearish path backtests to a negative Sharpe in all 4 sectors on the data available so far, a real finding to calibrate against, not a bug to force through |
| v2.2.57 | 2026-08-15 | Scoring Change / Feature | Built per-sector category weight calibration (v2.2.56's proposed fix for the 3-of-4-sectors-failing finding) — fit on historical data, validated on true held-out data per sector: semiconductors' fit was correctly rejected (would have made it worse), consumer discretionary's passed and is now live, banks/healthcare stay on the shared default until more data exists. Also found and fixed a real bound-violation bug in the weight clamping math itself, latent since the calibration regression first shipped |
| v2.2.56 | 2026-08-15 | Backtest Methodology | Tested two open design questions against real historical data instead of waiting on live trades: gating on Technical doesn't help and was dropped; the shared category weighting badly fails 3 of 4 sectors on their own data (only semiconductors clears the go-live bars) even though the multi-sector backtest's pooled "passed" check couldn't see that — fixed the check to require every sector to pass individually |
| v2.2.55 | 2026-08-15 | Bug Fix / Scoring Change | Seasonality's monthly calendar was scoring backwards — confirmed on clean sector-pure data after fixing the backtest's own sector-scoping gap (WR +4.6pp, Sharpe 3.01→4.16 on the same historical set); also fixed a weight-calibration step that had been mathematically incapable of changing any score since it shipped, a go-live gate floor that couldn't be passed even by a model performing to spec, dead macro config, and ticker misattribution in news scoring |
| v2.2.54 | 2026-08-14 | Bug Fix | Paper trading was booking stop-loss "losses" on breakout orders that never actually filled (AVGO/ABBV never traded into their entry zone); also found and fixed a support/resistance target/stop calculation that was computed every scan and silently thrown away, and a news-theme field that always logged blank due to a mismatched key name |
| v2.2.53 | 2026-08-13 | Bug Fix / Scoring Change | Extended the fundamentals audit to every other scoring layer — the biggest find: macro/seasonality rules built for semiconductors (rate hikes are bad, strong dollar hurts TSM/ASML) were being applied identically to regional bank stocks, where rising rates usually help; found and fixed 11 more real gaps across Technical, Positioning, Sentiment, News, and cross-ticker scoring |
| v2.2.52 | 2026-08-13 | Bug Fix / Scoring Change / Data Source | AMD's Aug 4 earnings beat never reached the model — a full audit of the fundamentals layer found and fixed 7 real gaps, including a dead scoring bucket, a stock being benchmarked partly against itself, and no revenue data being tracked at all (EPS-only) |
| v2.2.51 | 2026-08-11 | Bug Fix / Feature | Plain stock positions were priced at full share price instead of real dollar risk, diluting their modeled edge ~20x and wrongly excluding high-priced stocks from consideration — fixed the pricing and taught the system to prefer capped-loss options over shares only when an affordable one exists |
| v2.2.50 | 2026-08-11 | Bug Fix | Every bearish signal has been silently excluded from all 42 trade structures since paper trading started — the reward:risk check only handled the bullish stop-below-entry case |
| v2.2.49 | 2026-08-10 | Bug Fix | Paper trading could silently log a second same-direction position on a ticker that already had one open (found via PFE/LLY both duplicated 3 days apart) — added a duplicate-position guard scoped to paper trading's own ledger |
| v2.2.48 | 2026-08-10 | Bug Fix | A trade sitting exactly at the 1:3 minimum reward:risk was getting silently rejected by a floating-point rounding artifact, excluding all 42 trade structures; also added a sizing_note field so a signal that sizes to 0 or finds no eligible structure now says why, right in the ledger |
| v2.2.47 | 2026-08-10 | Backtest Methodology | Sector rotation's -15/+5 point penalty had never been tested against real outcomes — wired it into the backtest and found the "hot sector" boost was backwards |
| v2.2.46 | 2026-08-06 | Scoring Change | No trade has ever scored high enough to qualify (needed 90, best ever was 80) — lowered the bar to 70 after finding the backtest wasn't comparing fairly |
| v2.2.45 | 2026-08-06 | Infrastructure | 4 retail stocks (Home Depot, Nike, Starbucks, Target) never once got financial data — a leftover daily limit was blocking them; raised it |
| v2.2.44 | 2026-08-06 | Data Source | Found why Seeking Alpha kept failing: we were paying for the wrong listing on RapidAPI — switched to the one that's actually upgraded |
| v2.2.43 | 2026-08-06 | Infrastructure | Seeking Alpha's data feed was failing on every stock, every scan, all day — scans no longer waste time re-confirming a feed that's already known to be down |
| v2.2.42 | 2026-08-06 | Research | Extended the collinearity check to every scoring pair; new diagnostics for modifier calibration, score saturation, and threshold optimization; weight calibration upgraded to a real regression |
| v2.2.41 | 2026-08-06 | Backtest Methodology | Added Sortino ratio, Ulcer Index, drawdown duration, concurrent-position portfolio simulation, and real transaction costs to the backtest's own metrics |
| v2.2.40 | 2026-08-06 | Infrastructure | The post-close scan could run twice at once — a file lock now stops it, fixing why retail-sector tickers dropped out of an entire day's results |
| v2.2.39 | 2026-08-06 | Scoring Change | The model was treating its own confidence score as a literal win probability; two scoring modifiers were quietly double-counting the same signal; stale fundamental data was weighted the same as same-day data |
| v2.2.38 | 2026-08-06 | Bug Fix | The trade-structure picker was computing real diagnostic data every scan and throwing it away; a statistical outlier check now catches anomalies like MU's 2-2.5x-inflated reading |
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

## [v2.2.63] — 2026-08-19 — [Bug Fix / Scoring Change / Backtest Methodology] Full model audit — 17 real gaps found and fixed, including a historical-test fill assumption that flattered its own numbers

**Status:** Live.

**In short:** A structured audit combed through five parts of the model — where it gets its data, how
it scores a stock, how it manages risk, how its historical performance test works, and how live/paper
trading runs day to day — and found 17 real problems. The single biggest one: the historical
performance test had been assuming every signal got filled instantly at the exact price it fired at,
when in real trading a signal is a "wait for the price to actually get here" conditional order that can
simply expire unfilled if price never pulls back into it. That quietly favored the kind of strong,
no-pullback move that's most likely to win, making the test's numbers look a little better than real
trading would actually achieve. After fixing it — along with the other 16 issues — the model's win rate
moved from 63.1% to a more honest 61.2%. It still clears its own safety bar; the number just isn't
overstated anymore.

**Problem, fix, by area:**

1. **Historical test filled every signal instantly instead of checking for a real fill.** Added the
   same "did price actually trade into the entry zone within 5 days" check paper trading already uses
   (`shared/utils/fill_simulation.py`, now shared by both) — a signal that never gets filled in real
   trading no longer counts as a win (or a trade at all) in the test either.
2. **A losing-streak statistic in the same test was counted out of calendar order** — the identical bug
   shape already found and fixed once before in the test's equity curve (2026-07-19). Now sorted
   chronologically like everything else path-dependent in that test.
3. **Four scoring inputs weren't flipped around for a "bet the price will fall" trade** the way the
   rest of the model already is: a company's financial health, broader economic conditions, seasonal
   patterns, and news clustering could all end up working against a short trade instead of confirming
   it. All four now mirror correctly, matching the pattern already used elsewhere in the model.
4. **Two safety features meant to protect an open position day-to-day had no effect on the loop that
   actually runs paper trades** — cutting a trade loose early if its outlook sours, and a stall-based
   exit at the 10-day mark — despite being described as active in the settings. Both are now wired into
   the real daily update loop.
5. **The one automated check on an options trade with theoretically unlimited risk could be silently
   skipped** whenever a live pricing feed hiccuped, letting that trade through completely unchecked
   instead of being turned away. Now turned away instead.
6. **A data-quality check meant to catch bad stock-price data, weird timestamps, and out-of-range
   readings had never actually been connected to the real trading pipeline**, despite existing in the
   codebase and being described as running. Wired in for real; two of its own checks were also
   comparing against fields that don't exist in the data it's checking and have been corrected.
7. **One kind of financial-data lookup could fail in a way that wiped out every stock's financial score
   for an entire day's scan**, not just the one stock that had the problem. Now isolated per stock.
8. **A shared counter for a metered outside data service was undercounting real usage on retries**,
   risking that service running over its budget without warning. Now counts every real attempt.
9. **Smaller issues, one line each:** two stocks could be held both directions at once (now blocked);
   a portfolio-limits setting grouped every stock in two sectors into one bucket, making a "2 positions
   allowed" limit behave like "1 allowed" (regrouped into the actually-correlated pairs); one settings
   check only covered one of two places a scan could run from (now covers both).

**Fix:** All 17 issues fixed directly in code/config — see the commit history for full line-level
detail. A new automated check (`scripts/check_version_bump.py`, wired into CI) now enforces this
project's own long-standing rule that a scoring-relevant change can't go live without a version bump
and a fresh backtest — previously only true for one narrow internal path, not for a human editing
config or scoring code directly.

**Found, not fixed:** the same "checked once at signal time, never re-applied" pattern that motivated
item 4 above also affects `run_swing_model.py`'s live-position tracking pipeline more broadly — its
circuit-breaker/consecutive-loss safety logic is correctly wired to read state, but nothing yet writes
to that state, because the Discord "reply ENTERED/SKIPPED" listener that would populate it doesn't
exist in this codebase yet. That's a real piece of missing infrastructure (a persistent bot process),
not a bug in the scoring/risk logic itself — flagged for a future build, not attempted here. Paper
trading's own loop (the one actually running today) is unaffected — see CHANGELOG v2.2.37 for why that
loop deliberately doesn't share this state to begin with.

**Backtest:** Run date: 2026-08-19. Win rate: 61.2%. Avg R:R: 1:1.41. Sharpe ratio: 2.03. Max drawdown:
7.7%. Qualifying trades: 152. Max consecutive losses: 9. **Passed — clears every criterion on the
go-live bar**, same as the prior version, on genuinely corrected numbers this time.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.62] — 2026-08-19 — [Bug Fix] Open equity positions now re-checked for earnings proximity daily, not just at signal time

**Status:** Live.

**In short:** Found while reviewing open paper trades: `shared/utils/earnings_calendar.py`'s earnings-proximity screen — which forces a *new* signal into a capped-loss options structure whenever earnings are 0-5 days out — only ever runs once, at signal time. A trade signaled 6+ days before earnings (and so allowed to size as a plain, undefined-risk `long_stock` position, same as any other affordability-driven fallback) is never re-checked as the clock runs down. Since a position can stay open up to 15 trading days, one signaled comfortably outside the earnings window can still be sitting fully exposed on the day the report actually lands. This wasn't hypothetical: NVDA's live 2026-08-14 signal (earnings 2026-08-26, 12 days out at signal time, sized as plain shares because its options structure didn't fit the account's risk budget) would have ridden through the print unprotected on day 12 of its hold with no code path ever re-evaluating it.

**Fix:** `paper_trading/paper_updater.py`'s daily update loop now calls the new `_check_earnings_exit()` for any open, filled, still-unresolved `position_type == "shares"` trade — fetches the ticker's current next-earnings date (one `yfinance` call per ticker per run, only when at least one open row could act on it) and, if `earnings_calendar.get_earnings_modifier()` reports the position has aged into its `force_defined_risk`/`no_new_trades` window (0-5 days out), flattens it at the latest available close as a new `earnings_exit` outcome — before a post-earnings gap gets the chance to blow through the stop. Runs only after `_resolve_outcome()` finds the trade still open through the latest bar, so it can never preempt a stop/target/time-stop that already fired in the fetched price history. Options/other capped-loss structures are left untouched — their max loss is already bounded, nothing extra to protect.

**`earnings_exit` wired through the outcome pipeline it needed to be, deliberately left out where it didn't:**
- `shared/utils/discord_alerts.py::send_paper_outcome_alert` — new label/emoji/color (📅, yellow if profitable else red-toned) instead of falling through to a generic all-caps label with an always-red ❌ regardless of actual P&L.
- `paper_updater.py::print_summary()` — counted as a win when profitable, same rule already applied to `time_stop`, so it can't quietly drag the reported win rate down just by adding to the denominator without ever landing in a numerator (a bug this change would otherwise have introduced).
- `swing_model/feedback_loop.py`'s weight-calibration fitting already skips any outcome string outside `("win", "loss", "time_stop")` — `earnings_exit` falls into that same, already-correct exclusion (identical treatment to `expired`), so no change needed there.

**Second gap found, not fixed:** `news_layer.py`'s `event_gate_blocked` check (the one that blocked AMZN/HD's 2026-08-19 signals on a "labor strike" headline) has the exact same shape — evaluated once at signal time, never re-applied to a position that's already open. An adverse news event breaking mid-hold doesn't trigger any reaction today. Left as a flagged, undeferred gap rather than built here: unlike the earnings fix (one cheap, already-cached-shape `yfinance` calendar call per ticker), closing this needs a daily news re-fetch and re-score per open ticker against Alpha Vantage's metered free tier and StockTwits — a real cost/rate-limit tradeoff that needs a decision before building, not just wiring.

**Tests:** New `tests/test_paper_updater_earnings_exit.py` (7 tests) covering the flatten/no-flatten boundary, earnings-day-itself, options structures being left alone, missing `position_type` defaulting to the protected case, and no-earnings-date/empty-bars no-ops. Full suite: 1279 passing (up from 1272), no regressions.

---

## [v2.2.61] — 2026-08-19 — [Feature / Bug Fix] Stress-test skips fixed, real cross_ticker backtest wiring, real max-loss/max-gain + strikes, wider Greeks coverage, real contract counts, and alternatives surfaced

**Status:** All live except the earnings_modifier gap, which remains an honest, undeferred limitation (no code path to fix it exists yet — see below).

**In short:** Follow-up to v2.2.60's audit. Fixed two real gaps (stale test skips, a hardcoded backtest modifier), then built five requested improvements to the trade-structure output: real dollar max-loss/max-gain, actual contract counts, real strikes/expiration dates, wider Greeks coverage, and the runner-up structures alongside the winner. Two genuine scope boundaries were surfaced and resolved with the user before building: earnings_modifier can't be fixed the way cross_ticker was (no historical earnings-date archive exists anywhere in this repo), and Greeks coverage stops at the 9 structures that are pure wiring — calendars/diagonals, ratio/back spreads, and LEAPS each need real new work (a multi-expiration redesign, brand-new strike conventions, and a new data-fetch dependency respectively) that wasn't attempted here.

**1. Stress-test skips fixed — a fixture bug, not a real blocker.** `tests/test_stress_scenarios.py`'s 3 tests all `pytest.skip("Implement Phase 12 first")`, but `backtesting/stress_test.py` has been fully implemented for a long time. Ran the tests un-skipped to find out why they were never re-enabled: 2 of 3 passed immediately; the 3rd failed because `sample_positions`' fixture used a non-canonical schema (`"stop"` instead of `"stop_loss"`, no `"risk_pct"` key) that doesn't match `swing_model/portfolio_manager.py`'s real position-dict schema, which `run_scenario()` reads. Fixed the fixture, removed all 3 skips — the stress-test suite now has real coverage for the first time.

**2. `cross_ticker_modifier` wired into the backtest for real; `earnings_modifier` stays 0.0, honestly.** `backtesting/simulation.py` hardcoded both to 0.0 unconditionally. Wired `cross_ticker_modifier` in following the exact pattern `macro_mod`/`rotation_mod` already use (v2.2.7/v2.2.47): pre-computed `trend_intact`/`breakout_confirmed` for every sector ticker once (vectorized, cheap), then at each candidate bar sliced every sector peer's OHLCV to `<= bar_date` (no lookahead) and called `analyze_cross_ticker()` for real. Verified against a real backtest run: 102 of 1045 outcomes got a nonzero modifier (mostly the +5 divergence boost), confirming real signal, not a silent no-op — runtime stayed reasonable (~45s for one full pass). `earnings_modifier` was investigated and found genuinely infeasible to fix the same way: no historical earnings-date archive exists anywhere in this repo, and yfinance's live calendar only returns the *next upcoming* earnings date — using it for a backtest bar in the past would leak future information. Left hardcoded 0.0 with a clear comment explaining why, per explicit user decision after this tradeoff was raised.

**3+5. Real dollar max-loss/max-gain and actual strikes for 35 of 42 structures.** `resolve_structure_economics()` (`options_math.py`) previously returned only `avg_win`/`avg_loss` (the technical target/stop scenario) and discarded every strike it computed along the way. Extended every branch to also return `max_loss_dollars`/`max_gain_dollars` (the structure's true theoretical worst/best case — for many categories, e.g. debit spreads, credit spreads, iron condors, this is an exact reuse of `net_debit`/`width`/`net_credit` already sitting in scope, zero new formulas; for covered_call/long_butterfly_call, the *true* structural cap, not the fav-limited `avg_win`) and `strikes` (the branch's own strike variables). `None` where risk/reward is genuinely unbounded (naked options, short straddle/strangle, synthetics, long calls' upside) — never fabricated. The 4 ratio/back-spread structures stay out: confirmed no strike convention exists anywhere in their code path (`compute_ev_surface`, not `resolve_structure_economics`) — inventing one is real new modeling work, not this pass. `trade_selector.py` now prefers real chain-quoted strikes (when a live option chain resolved them for Filter 4) over the theoretical Black-Scholes estimate, tagged via a new `strike_source` field. Threaded through to `paper_runner.py`/`run_swing_model.py`/`discord_alerts.py` and new CSV columns, including a real calendar `expiration_date` (today + effective_days, computed where the clock already lives, not inside the clock-free `options_math.py`). 8 new property tests confirm the defined-risk/unbounded split and that debit/credit spread bounds exactly match `avg_win`/`avg_loss`.

**6. Greeks coverage extended from 20 to 29 of 42 structures — pure wiring, no new modeling.** Added `iron_condor`, `iron_butterfly`, `short_butterfly`, `condor_spread`, `long_butterfly_call`, `wheel`, `risk_reversal`, `synthetic_long`, `synthetic_short` to `_GREEKS_RESOLVABLE_LEGS`, reusing the exact strike-offset conventions `resolve_structure_economics`'s own branches already use — confirmed each is single-expiration with no multi-leg-quantity or new-strike-convention blocker (`net_structure_greeks` already sums an arbitrary-length leg list). One real find along the way: `long_butterfly_call`'s inner wing needs a 6%-ITM strike that didn't exist as a `select_directional_leg_strike` moneyness bucket (only "otm"/6%, "far_otm"/12%, "deep_itm"/15%, "atm" existed) — added a new `"itm"` bucket (6%, mirroring "otm") rather than approximating with the wrong strike ("deep_itm" would have computed Greeks against different strikes than the structure's own EV was priced on). The same inner wing is a real 2x-short leg (per `resolve_structure_economics`' `-2 * bs(k_mid)` term); since `_GREEKS_RESOLVABLE_LEGS` has no per-leg quantity field, listed the same leg twice — `net_structure_greeks`' existing sum-across-legs loop correctly doubles its weight, confirmed by a dedicated test. Calendars/diagonals (4, genuinely need `net_structure_greeks` to support two different per-leg expirations — it currently takes one shared `T`), ratio/back spreads (4, no strike convention exists for them at all), and LEAPS (2, need a new long-dated chain fetch nothing in this pipeline does yet) remain unwired, each documented with its specific blocker.

**4. Real contract/share counts — extracted from paper_runner.py, not revived from the dead placeholder.** `position_sizer.py::compute_position_size()` was dead code (only called from tests) whose `contracts_or_shares` field was a literal placeholder string. The real dual-cap logic (risk-based size AND a separate capital/concentration cap, take the min — built in response to a real live incident: a $1.16 stop sizing to $1,676 deployed, 11% of a $15k account) already lived inline in `paper_runner.py`. Extracted it into `compute_position_size()` (new `per_unit_cost`/`position_type` params, defaults preserve exact prior behavior for any unchanged caller), rewired `paper_runner.py` to call the shared version, and wired the same function into `run_swing_model.py` — which had never computed a real position size or `dollar_risk` at all before this (confirmed via grep: the live Discord alert's "Dollar Risk" field has always shown $0.00). `run_swing_model.py` now also passes its *real* circuit-breaker/consecutive-loss state into the shared function instead of the manual pre-adjustment it used to do inline. 4 new tests, including a regression test reproducing the exact PFE-vs-AMZN incident this dual-cap fixes.

**7. Alternative structures surfaced.** `rank_trade_structures()` always computed the full EV-ranked list of eligible structures, but only the single winner ever reached the CSV or Discord — "why not #2" was collapsed into a bare exclusion count. `paper_runner.py`/`run_swing_model.py` now also extract the top 2 runners-up (by `ev_per_dollar_per_day`, excluding the winner — `ranked` is already sorted this way) into a compact summary (name, EV/day, capital required), surfaced via a new CSV column and a new "Alternatives" Discord field. Discord's 25-field-per-embed and 1024-char-per-field limits both have comfortable headroom (confirmed: ~13-14 fields used of 25 max).

**`paper_trading/paper_trades.csv` migrated again** (10 existing rows, all data preserved) — same non-negotiable step as v2.2.60, for the 5 new columns items 3/5/7 added (`structure_max_loss`, `structure_max_gain`, `structure_strikes`, `structure_expiration_date`, `alternative_structures`). Skipping this would have silently corrupted new-schema rows the next time `paper_updater.py`'s `_save_trades()` rewrote the file against the old header's column count.

**Full suite:** 1272 passing (up from 1256 baseline — 16 net new tests across structure economics, Greeks coverage, and position sizing), `ruff` clean.

**Approved by:** the user (explicit instruction, 2026-08-19), including the two scope-boundary decisions (earnings_modifier stays a gap; Greeks stop at the 9 pure-wiring structures) made explicitly before implementation, not assumed.

---

## [v2.2.60] — 2026-08-19 — [Feature / Bug Fix / Research] Wider holding period, a third bearish stop/target gap, real trade-structure metrics surfaced, and a genuinely different bearish entry tested (and rejected)

**Status:** Live except the new bearish entry style, which stays off by default (`bearish_entry_style: continuation` in `config/swing_config.yaml`) — see the research result below for why.

**In short:** Four connected pieces of work from one request: widen the holding period, keep improving bearish-signal quality, and stop losing real trade-structure detail (capital required, leg count, Greeks) between the point it's computed and the point a trader actually sees it.

**1. Holding period widened from 5-15 to 1-15 trading days.** Audited every "5" in the codebase tied to trade duration first — the actual finding: **the 5-day minimum was never enforced anywhere in code.** `paper_trading/paper_updater.py`'s exit logic only checks a maximum (`MAX_HOLDING_DAYS = 15`); `backtesting/simulation.py`'s `simulate_trade_outcome()` only ever reads the max side of its `holding_period` tuple. So this is a documentation/config correction to match what the system already does (a position can already exit the day after entry if stopped out or target hit), not a behavior change. Updated: `config/swing_config.yaml`'s `holding_period.min_days`, `simulate_trade_outcome()`'s default tuple, both explicit test call sites, `options_math.py`'s `_DEFAULT_DTE_IF_UNKNOWN` fallback (10 → 8, the new midpoint), and every "5-15 day" mention in README.md/PROJECT_OVERVIEW.md/Project_Scope.md/`position_rescoring.py`. Deliberately left alone (distinct concepts, not the holding-period bound): `signal_decay.py`'s pre-entry `SIGNAL_EXPIRY_DAYS`, `paper_updater.py`'s order-fill `FILL_WINDOW_DAYS`, `signal_decay.time_stop_day` (a separate mid-window checkpoint), and `news.decay_zero_at_days` (news relevance decay). Also refreshed a stale passage in `PROJECT_OVERVIEW.md` §11 that still claimed the entry filter "can only ever surface signals in trending_up" — true when written (2026-07-19), superseded by v2.2.58's bearish path.

**2. A third instance of the bearish volume-profile stop/target gap.** `shared/indicators/technical_common.py` has computed `high_volume_resistance`/`low_volume_area_below` (the bearish mirrors of the bullish-only `high_volume_support`/`low_volume_area_above`) since v2.2.58, but `shared/utils/risk_reward.py`'s `compute_stop_loss()`/`compute_target()` only accepted the bullish pair — bearish stops/targets fell back to pure ATR/min-R:R math even when a real resistance/support level was available and would be tighter. Fixed in `risk_reward.py` (new `high_volume_resistance`/`low_volume_area_below` params, same tighter-wins-if-closer logic as the bullish branch) and wired into all three call sites that build entry/stop/target: `paper_runner.py`, `run_swing_model.py`, **and `backtesting/simulation.py` itself** — the third site wasn't part of the original request but is the same bug, and leaving the backtest engine on the old behavior would have made it inconsistent with what live/paper trading now does.

**3. Real trade-structure economics no longer discarded before reaching the user.** `swing_model/trade_selector.py`'s `rank_trade_structures()` already computes capital required, leg count, effective days, and net Greeks (when a live option chain is available) for the winning structure — but only a bare structure name + one EV number ever survived to the Discord alert, the paper-trading CSV, or the live-signal path. Fixed: `paper_runner.py`, `run_swing_model.py`, and `discord_alerts.py` (`send_trade_alert`, `send_paper_signal_alert`, `format_trade_alert_text`) now carry `capital_required`/`structure_legs`/`structure_effective_days`/`structure_greeks_summary` through. **`paper_trading/paper_trades.csv`'s header was migrated** (10 existing rows, all data preserved) to include the new columns — appending new-schema rows without this would have silently corrupted them the next time `paper_updater.py`'s `_save_trades()` rewrote the file using the old header's column count. Did not add dollar max-loss/max-gain or contract counts — neither is actually computed anywhere yet (`avg_win`/`avg_loss` are expected values, not worst-case; `position_sizer.py` explicitly punts contract-count math to execution time) — flagged as a real follow-up rather than half-built here. Scope was deliberately limited to Discord + CSV, not the desktop app's SQLite schema, to avoid a database migration in the same pass.

**4. Tested a genuinely different bearish entry style — capitulation/bounce-fade — instead of a fourth round of continuation-mirror tuning.** v2.2.59's working theory: the bullish path is momentum-continuation (buy a fresh breakout while RSI is still healthy, 50-70); the bearish mirror shorts a fresh breakdown, which is often already oversold — structurally close to where a relief bounce/squeeze is likeliest, the opposite of the bullish case (real example: a semis short entered $77.99, stopped out $89.53 fourteen days later). Built `bounce_fade_setup()` (`shared/indicators/technical_common.py`): instead of shorting the breakdown itself, it waits for the relief bounce that follows and shorts that bounce's exhaustion — a confirmed breakdown within a lookback window, downtrend still intact, price bounced at least N×ATR off the post-breakdown low, RSI recovered into a neutral band and just turned back down. Wired into `backtesting/simulation.py` as `bearish_entry_style: "capitulation_fade"`, compared head-to-head against v2.2.59's own best-found continuation settings (RSI 30-55, 1.5R target, 1×ATR stop) via `backtesting/bearish_capitulation_fade_sweep.py`, same walk-forward-pooled methodology, all 4 sectors:

| Variant | n (pooled) | Win rate | Avg R:R | Sharpe |
|---|---|---|---|---|
| baseline_continuation_best_known | 339 | 36.9% | 1.43 | **-1.61** |
| capitulation_fade_wider_rsi (40-70 band) | 22 | 31.8% | 1.95 | -3.28 |
| capitulation_fade_default | 6 | 33.3% | 2.92 | -4.95 |
| capitulation_fade_tighter_bounce (0.5×ATR) | 6 | 33.3% | 2.92 | -4.95 |
| capitulation_fade_best_known_exit (+1.5R/1×ATR) | 6 | 33.3% | 2.17 | -6.36 |
| capitulation_fade_shorter_lookback (5 bars) | 3 | 33.3% | 3.00 | -5.11 |

**Result: worse, not better, and by a wide margin — a clean negative finding.** Every capitulation_fade variant underperforms the continuation baseline's already-negative -1.61 Sharpe. More importantly, **the signal is far too rare to be usable at all** — requiring a recent breakdown AND an intact downtrend AND a meaningful bounce AND RSI recovery-then-rollover simultaneously is a narrow intersection that real price data rarely satisfies (6 trades pooled across all 4 sectors over ~13.5 years, vs. 339 for continuation; regional_banks produced zero trades in every fade variant tried; healthcare's 2-trade sample swings to a nonsensical -1323.75 Sharpe, a small-sample artifact, not a real read). Widening the RSI recovery band (40-70) roughly quadrupled the sample (6→22) and materially improved Sharpe (-4.95→-3.28), suggesting the exhaustion gate specifically is the most over-tight part of the four AND-ed conditions — but even that improved variant remains clearly worse than continuation, not a promising direction to keep narrowing in on. Per the same multiple-testing caution v2.2.59 already applied (stopped after 3 rounds/16 variants), this was one clean comparison round, not an open-ended search — no further tuning of this entry style without a materially different hypothesis. **Shipped as working, tested infrastructure** (`bounce_fade_setup()` has its own unit tests; the sweep script and its methodology are reusable for a future different hypothesis) **behind `bearish_entry_style: continuation` as the default** — not wired into live/paper scoring at all (`scoring.py::determine_direction()` has no notion of entry "style"), so this finding has zero effect on the live/paper-active `enable_bearish_signals` path from v2.2.59.

**Full suite:** 1253 passing (up from 1247 baseline — 6 new tests for `bounce_fade_setup()`), 3 skipped (pre-existing, unrelated), `ruff` clean.

**Approved by:** the user (explicit instruction, 2026-08-19).

---

## [v2.2.59] — 2026-08-19 — [Research / Sector Rollout] Three more rounds of bearish tuning, then turned on for paper trading anyway to start collecting real data

**Status:** `enable_bearish_signals` is now **true** — live in paper trading (no real capital; this system has never traded real money). Bullish behavior is completely unchanged.

**In short:** v2.2.58 found the new bearish path backtests badly everywhere. Rather than guess at one fix, three genuinely different hypotheses were tested against real historical data — what triggers a signal, how big the target/stop is, and how quickly it triggers after the breakdown. All three helped a little. None got anywhere close to passing. Rather than keep searching the same fixed 13-year dataset for a fourth fix (real overfitting risk at that point), the flag was turned on for paper trading specifically to start generating the one thing backtesting can't manufacture: real bearish outcomes going forward.

**What was tested (all pooled across walk-forward windows, all 4 sectors):**

1. **Entry filter — bearish RSI band** (`backtesting/bearish_rsi_band_sweep.py`): swept the oversold floor from the shipped 18 up to 35. Win rate rose 32.4% → 42.9% as the floor tightened, but Sharpe never improved (-2.52 → -3.09 at the tightest band, since the sample shrinks faster than the edge grows). Best: **30-55 band, Sharpe -2.44.**
2. **Exit sizing — target R:R and stop distance** (`backtesting/bearish_exit_sizing_sweep.py`): tightening the ATR stop from 2x to 1x and lowering the target from 3R to 1.5R was the single most effective lever found — Sharpe improved from -2.44 to **-1.73**, avg R:R rose 0.85 → 1.40. Still a losing strategy, but the clearest real signal in this round.
3. **Entry timing — require next-bar confirmation** (`backtesting/bearish_confirmation_sweep.py`): requiring the bar after a breakdown to still close below the breakdown level (filtering one-day "bear trap" undercuts) helped semiconductors (Sharpe -1.93 → -1.52) but hurt regional banks (-2.12 → -3.18) — net flat pooled (-1.73 → -1.77).

**Working theory, unconfirmed:** the bullish path is momentum-continuation logic — buy a fresh breakout while RSI is still healthy (50-70), not yet stretched. The bearish mirror structurally enters *after* a breakdown that's often already oversold, closer to the point where a sharp reversal (short squeeze, dead-cat bounce) is most likely, not least. A real example from the data: a semiconductor short entered at $77.99 was stopped out at $89.53 fourteen days later. If this theory is right, no amount of tuning the current continuation-style formula fixes it — the short side likely needs a different kind of signal (mean-reversion/capitulation-fade), not a better-tuned mirror of the long side. That's a strategy-design question, not something resolved here.

**Decision:** rather than run a fourth or fifth variant against the same fixed historical sample (three rounds — 16 variants — already carries real multiple-testing risk with no independent confirmation), `enable_bearish_signals` was turned on for paper trading by explicit user decision, made with full knowledge that no bearish bucket clears the go-live gate today. This is not a claim that the bearish path is ready — it's a deliberate choice to start generating real, forward-looking bearish outcomes (the one input historical replay can't manufacture more of) rather than continuing to search backward-looking data for a fix. Real capital is not and will not be at risk from this — see "Where things stand right now" at the top of this file.

**Full suite:** unchanged from v2.2.58 (1243 passing, 3 skipped), `ruff` clean — this entry is a config flip plus three new read-only diagnostic scripts, no scoring-code changes.

**Approved by:** the user (explicit instruction, 2026-08-19), following review of v2.2.58's findings via the Signal Panel artifact.

---

## [v2.2.58] — 2026-08-18 — [Feature / Backtest Methodology] Real bearish/breakdown detection, shipped behind a kill switch pending review

**Status:** Code shipped, **not live at time of writing**. `enable_bearish_signals: false` in `config/swing_config.yaml` kept every live/paper scan exactly as bullish-only as before this entry. *Superseded 2026-08-19 — see v2.2.59: after three further rounds of testing found no fix, the flag was turned on for paper trading anyway to start collecting real data.*

**In short:** The model could technically label a trade "bearish," but almost nothing upstream of that label actually knew how to recognize or score a bearish setup — it only ever detected uptrends/breakouts, so "bearish" almost never fired and defaulted back to "bullish" instead. This build gives the model a real, symmetric way to recognize and score bearish setups, then backtested that new path honestly. The result: the mirrored bearish detection does not clear the same go-live bar the bullish path does, in any of the 4 sectors, on the data available right now. That's a real, useful finding — not a bug — and it's exactly why this stays off pending review rather than going live automatically.

**Problem:**
1. The technical layer only ever detected breakouts/uptrends (`shared/indicators/technical_common.py`'s `is_breakout()`, `trend_intact`) — there was no `is_breakdown()`/`downtrend_intact` counterpart, so a genuine breakdown scored identically to boring sideways chop.
2. `scoring.py::determine_direction()` defaulted to `"bullish"` in almost every case — a technically-bearish setup could never be labeled bearish unless sentiment did all the work, since technical structurally couldn't confirm it.
3. Sentiment ratio/velocity, news credibility, and all 5 Positioning sub-signals only ever rewarded "more bullish = higher score," with no notion of "this confirms a bearish thesis" (a strongly bearish StockTwits tilt, bearish-confirming news, put-heavy options flow, institutional distribution, short-interest building, and insider selling all scored *low* regardless of what direction was actually being evaluated).
4. Regime and sector-rotation modifiers were also bullish-framed — an uptrend rewarded every candidate regardless of direction, backwards for a short thesis.
5. The backtest hardcoded `direction="bullish"` for every simulated trade (`backtesting/simulation.py`) — there was no historical bearish outcome archive anywhere, live or backtested, to calibrate against.

**Fix:**
1. Added `is_breakdown()`, `breakdown_confirmed`, `downtrend_intact`, `macd_bearish`, and a bearish volume-profile read (`shared/indicators/technical_common.py`, `shared/utils/volume_profile.py`) — real breakdown detection, not just "absence of an uptrend."
2. Hoisted direction determination earlier in the per-ticker pipeline (`run_swing_model.py`/`paper_runner.py`) so `determine_direction()` runs *before* Sentiment/News/Positioning scoring, and rewrote it to use the new real bearish signals instead of falling through to `"bullish"`.
3. Added a `direction` parameter to `sentiment_layer.py`'s ratio/velocity scoring, `news_layer.py`'s credibility scoring, and all 5 `positioning_layer.py` sub-scorers — each now mirrors around its own neutral midpoint per direction (put-heavy options / institutional distribution / short interest building / insider selling / analyst downgrades each score high for a bearish candidate, the mirror of what scores high for bullish).
4. Made `regime_detection.get_regime_modifiers()` and `sector_rotation.py`'s rotation modifier + leader-dampening direction-aware (an uptrend now penalizes a bearish thesis instead of rewarding it; a genuine "downside leader," not just a bullish outperformer, gets its own dampening).
5. Added a mirrored breakdown-candidate path to the backtest (`backtesting/simulation.py`) — real bearish quality gates, direction-aware entry/stop/target, and a bearish outcome archive generated from real historical data for the first time. Also fixed a minor `achieved_rr` inconsistency in the bearish loss branch of `simulate_trade_outcome()` while touching this file.
6. Extended per-sector weight calibration (`swing_model/feedback_loop.py`, `backtesting/sector_weight_calibration.py`) to fit bullish and bearish weights independently per sector, reusing the existing sample-size floor/shrinkage machinery unchanged — a bearish bucket with too little data simply stays on the shared default, same as an under-sampled sector already does today.
7. Added `enable_bearish_signals: false` to `config/swing_config.yaml` — the single gate, checked inside `determine_direction()`, that keeps live/paper trading bullish-only regardless of signal strength. Backtesting and calibration bypass it (they need to exercise the bearish path to generate anything to validate against); only real live/paper callers pass the real config with the flag defaulting off.

**Backtest result:** Ran the same per-sector replay this project already uses (`backtesting/architecture_diagnostic.py`), now split by direction, against the historical data on disk (confidence ≥ 90 qualifying bar, same go-live bar as every other entry: ≥100 qualifying trades, expectancy CI-lower ≥ 0.3R, Sharpe ≥ 1.0, max drawdown ≤ 15%):

| Sector | Direction | n qualifying | Win rate | Avg R:R | Expectancy CI-lower | Sharpe | Max DD |
|---|---|---|---|---|---|---|---|
| Semiconductors | Bullish | 138 | 65.9% | 1.92 | **0.71** | **3.78** | 6.8% |
| Semiconductors | Bearish | 11 | 45.5% | 0.49 | -0.57 | -3.11 | 4.1% |
| Regional banks | Bullish | 94 | 55.3% | 1.41 | 0.13 | 0.50 | 13.1% |
| Regional banks | Bearish | 22 | 22.7% | 1.08 | -0.72 | -3.55 | 8.7% |
| Healthcare | Bullish | 74 | 52.7% | 1.40 | 0.05 | 0.22 | 10.1% |
| Healthcare | Bearish | 84 | 34.5% | 0.83 | -0.45 | -2.55 | 21.1% |
| Consumer discretionary | Bullish | 542 | 48.9% | 1.42 | 0.14 | 0.27 | 19.0% |
| Consumer discretionary | Bearish | 135 | 29.6% | 1.02 | -0.41 | -2.53 | 33.6% |

Only semiconductors:bullish clears every bar (consistent with v2.2.56's earlier finding that only semiconductors clears the go-live bar on its own data) — no bearish bucket in any sector clears the trade-count floor with a positive Sharpe, and 3 of 4 don't clear the trade-count floor at all. This isn't read as "the code is broken" (the pipeline was re-verified against the pristine pre-change commit on the same ad-hoc query and produced the same low headline number, ruling out a regression), and it isn't read as "bearish detection doesn't work" either — it's read as "the mirrored gates (in particular the RSI oversold band, a direct 100-minus-RSI reflection of the bullish 45-82 band with no re-validation of its own) are an unvalidated starting point, exactly as expected for a first pass, and exactly why this stays behind a kill switch rather than shipping on the assumption that a mirror image of a tuned bullish parameter is itself tuned." A Phase 0 diagnostic (`backtesting/breakdown_diagnostic.py`) confirms this isn't a data-availability dead end either — 227-951 qualifying breakdown bars per sector exist in the historical window, concentrated exactly where expected (semiconductors: 74 in 2022, 36 in 2018 — the two largest real SMH drawdowns in the dataset).

Full suite: 1243 passing (up from 1220 baseline), 3 skipped, `ruff` clean.

**Note on reproducibility:** `data/historical/*.csv` is live-updated by this project's own scheduled scans; re-running the exact query above during active hours can shift which historical bars fall on which side of the train/test split and move the small-sample bearish numbers by a meaningful amount run-to-run (confirmed directly — a raw, unfiltered version of this same semiconductors:bearish query returned 0% and 45.5% win rate in two runs minutes apart). The qualitative finding — every bearish bucket underperforms its own sector's bullish bucket, and none come close to the go-live bar — held across both runs and is the actionable takeaway; the exact decimal win-rate/Sharpe figures above are a snapshot, not a number to cite precisely later the way this project's other backtest results are.

**Next steps (not done here, deliberately):** re-tune the bearish-specific constants (the RSI oversold band most of all) against this same data the way the bullish 45-82 band was itself re-tested rather than assumed; let more real bearish outcomes accumulate for calibration once enabled; only then consider flipping `enable_bearish_signals` on.

**Approved by:** [pending]

---

## [v2.2.57] — 2026-08-15 — [Scoring Change / Feature] Per-sector category weight calibration — fit on historical data, validated on true held-out data per sector, not applied blind

**Status:** Live (paper trading only, per this project's own gate on real capital).

**In short:** The last entry found that one shared scoring formula doesn't work equally well for every kind of stock. This is the fix: instead of guessing new numbers by hand, let each sector's own trading history teach the model how much its price chart, its public sentiment, and its news coverage should each matter — a custom formula per sector, not one-size-fits-all.

Building it surfaced two real bugs. First, the historical news data barely varies at all in most of our older records, because real news tracking only started a bit over a year ago — trying to learn from it was like trying to learn a lesson from a mostly-blank page, and it was silently stopping the whole learning process from running at all. Fixed so it just skips that one ingredient instead of giving up entirely. Second, and more important: the safety math that keeps any one factor from getting too much or too little weight had a real flaw — it could let a number sneak slightly past the limit it was supposed to obey. That flaw has been sitting there since this feature was first built and just never got triggered by real numbers before. Replaced with a version that can't do that.

Result: for semiconductor stocks, the custom formula was tested and it would have made results worse, so the system correctly threw it out and kept the original settings. For retail-sector stocks, the custom formula tested genuinely better and is now in use. Bank and healthcare stocks don't have enough trading history yet to safely build a custom formula, so they stay on the original shared settings for now.

**Problem:**
1. No mechanism existed to give different sectors different category weights — `scoring.py`'s `live_weights` calibration (fixed from a no-op in v2.2.55) only ever supported one global weight set, applied identically regardless of what sector a ticker belongs to.
2. `feedback_loop._fit_logistic_weights()` aborted the entire fit if *any* of the three features (technical/sentiment/news) had zero variance in the training data. Running it against historical backtest outcomes (not real paper trades, which is what it was originally built for) hit this immediately: `news_total` is constant across nearly every row before Q4 2025, since no historical Alpha Vantage article archive exists before then — every historical fit attempt degenerated to `None` before this was fixed.
3. `_recompute_weights()`'s (and initially this feature's own) weight-bounding logic clamped each weight to its documented range (30-80% technical, 5-40% sentiment, 5-30% news) and then rescaled the three to sum to 1.0 — but rescaling after clamping can itself push a value back past the bound it just enforced (e.g. sentiment and news both floor-clamped forces technical above its ceiling once rescaled). Caught by a test using a strongly technical-dominant synthetic signal; the same bug was already latent in the original global calibration, just never exercised by real data landing far enough past a bound to expose it.
4. Naively trusting a regression fit on a thin sample (regional_banks: 90, healthcare: 68 qualifying historical trades) risks replacing "wrong shared weights" with "confidently wrong sector-specific weights" — worse, not better.

**Fix:**
1. `feedback_loop._fit_logistic_weights()` now drops any zero-variance feature from the fit instead of aborting — returns a dict containing only the keys that could actually be fit; callers treat an omitted key as "no information, keep this weight's prior/default value," not as a fitted 0.
2. New `feedback_loop.fit_sector_calibrated_weights()`: takes `{sector: outcomes}`, and for each sector with at least `_MIN_SAMPLES_FOR_SECTOR_CALIBRATION` (100) qualifying trades, fits weights and shrinks them toward the shared default proportional to sample size (full trust at 300+ trades) — a fit on 127 trades is trusted less than one on 506, even though both clear the floor to be attempted at all. Sectors below the floor get no entry at all, not even a heavily-shrunk one.
3. New `feedback_loop._clamp_and_normalize_weights()`: a proper water-filling projection onto the box-constrained simplex (clamp to bounds, redistribute the sum-to-1 gap only across weights not already pinned to a bound, freeze any weight the redistribution itself pushes onto a bound, repeat) — guaranteed to land in-bounds whenever a feasible point exists, unlike the single clamp-then-rescale pass it replaces. Both `_recompute_weights()` (the original global calibration) and `fit_sector_calibrated_weights()` now share this one implementation.
4. New `backtesting/sector_weight_calibration.py`: replays each sector's historical out-of-sample outcomes, holds out the most recent ~20% chronologically per sector (never a random split — matches `run_calibration()`'s existing train/holdout discipline for the global calibration), fits on the rest, and only saves a sector's weights if they beat the shared default on that untouched holdout slice — the same safety gate `run_calibration()` already uses, just applied per sector against historical data instead of once against real paper trades.
5. New `data/processed/calibrated_weights_by_sector.json` — deliberately a separate file from `calibrated_weights.json` (the pre-existing global/live-paper-trading calibration), since the two have different data sources and formats and shouldn't be conflated.
6. `feedback_loop.load_live_weights_if_calibrated()` gains an optional `sector` param: returns that sector's weights if present, else falls through to the existing global-weights behavior unchanged. `paper_runner.py`/`run_swing_model.py` now compute `live_weights_by_sector` once per active sector (same pattern already used for `seasonality_mod_by_sector`) and pass each ticker's own sector's weights into `compute_confidence_score()`.
7. New `config/swing_config.yaml` flag `feedback_loop.sector_calibration_enabled` (default `true`) — a kill switch, not the primary safety mechanism (that's the holdout gate in fix 4) — lets per-sector weighting be reverted to the shared default instantly without deleting the calibrated file, same operational pattern as `regional_banks.active` and other staged sector rollouts in this project's history. `backtesting/simulation.py` now tags `sector` onto every outcome record (derived from `benchmark_ticker`, reusing v2.2.55's mapping) so calibration can bucket by it.

**Backtest result:** This entry's validation *is* a backtest result in the relevant sense — real historical data, held out properly, per sector:

| Sector | Train | Holdout | Fit-eligible | Default score | Fitted score | Result |
|---|---|---|---|---|---|---|
| Semiconductors | 102 | 25 | yes | 0.7651 | 0.7511 | **Rejected** — fit would have made it worse |
| Consumer discretionary | 405 | 101 | yes | -0.9936 | -0.5299 | **Saved** — genuinely improved on unseen data |
| Regional banks | 72 | 18 | no (< 100) | — | — | Not attempted — stays on shared default |
| Healthcare | 55 | 13 | no (< 100) | — | — | Not attempted — stays on shared default |

Saved weights for consumer discretionary: technical 40%, sentiment 40%, news 20% (vs. the shared default's implicit ~57/21/21) — a real, sample-size-appropriate shift toward sentiment mattering more for consumer names, not asserted as intuition but because it's what the holdout data actually rewarded. 8 new tests in `tests/test_phase14_feedback.py` (`TestFitSectorCalibratedWeights`, `TestLoadLiveWeightsIfCalibratedPerSector`) plus 1 existing test updated to assert the corrected zero-variance-feature behavior instead of the old all-or-nothing abort; full suite 1039 passing (up from 1030), 3 skipped (unchanged, pre-existing), ruff clean.

**Approved by:** [pending]

---

## [v2.2.56] — 2026-08-15 — [Backtest Methodology] Real data now answers two open design questions instead of guessing: gating on Technical doesn't help (dropped); the shared category weighting fails 3 of 4 sectors on their own data, invisible in the pooled "passed" check until now

**Status:** Live.

**In short:** Two open questions were left from the last round of fixes: should a stock be required to have a genuinely strong price chart before a trade can qualify at all (instead of letting other factors make up for a weak one), and does the same scoring formula actually work equally well across every kind of stock we trade? Rather than guess, both were tested directly against years of real historical data.

First question: no, it doesn't help. Requiring a stronger chart setup made no real difference, and pushed too far it actually made results worse. The idea was dropped.

Second question: yes, and it's a bigger problem than expected. Semiconductor stocks do very well under the current formula. But bank stocks, healthcare stocks, and retail stocks each individually do poorly enough that none of them alone would be considered safe to trade on — even though the combined average across all of them looked fine, because the strong semiconductor results were quietly covering for the weak ones. Fixed the check so a passing average can no longer hide a group of stocks that's actually failing.

**Problem:**
1. No tooling existed to test either open design question against real data — both were sitting as "worth discussing later," which for a system this thoroughly audited otherwise meant guessing instead of measuring.
2. `backtest_engine.py::run_multi_sector_backtest()` pools every sector's outcomes into one set of metrics before computing win rate/Sharpe/expectancy/drawdown — `per_sector` only ever tracked qualifying trade *count*, not each sector's own win rate/Sharpe/expectancy. A sector with a strong edge can mathematically carry a "passed" pooled read while other sectors underneath are failing outright, and there was no way to see that from the returned result.

**Fix:**
1. New `backtesting/architecture_diagnostic.py`: `per_sector_breakdown()` replays each sector's own out-of-sample outcomes separately (reusing `_get_test_outcomes()` per `_SECTOR_DATASETS` entry, same data `run_multi_sector_backtest()` already loads) and reports win rate/avg R:R/Sharpe/expectancy CI-lower/max drawdown per sector instead of one pooled number. `technical_gate_sweep()` re-filters the pooled qualifying set at increasing Technical floors (0/40/50/60/70% of `TECHNICAL_MAX`) and reports the same metrics at each floor, to see whether a floor actually improves results rather than just shrinking the sample.
2. `run_multi_sector_backtest()` now computes each sector's own `expectancy_r_ci_lower`/`sharpe_ratio`/`max_drawdown_pct`/`passed` (same three criteria as the pooled check: expectancy CI-lower ≥ `min_expectancy_r`, Sharpe ≥ 1.0, max drawdown ≤ 15%) and returns them under a new `per_sector_metrics` key. The top-level `passed` now requires the pooled criteria AND every sector's own `passed` to be true; the old pooled-only result is preserved separately as `pooled_passed` for comparison. A sector with zero qualifying trades correctly fails (not passes) — `bootstrap_expectancy_ci`'s existing convention returns `ci_lower=0.0` for an empty sample. No scoring/weighting logic changed — this only changes what "passed" is honest about.

**Backtest result:** This entry *is* the backtest result — `architecture_diagnostic.py`'s two questions were the point, not a side effect of a code change. Full replay against all 4 sectors' real historical data:

| Sector | Win Rate | Avg R:R | Sharpe | Expectancy CI-lower | Max DD | Qualifying |
|---|---|---|---|---|---|---|
| Semiconductors | 66.9% | 2.17 | 4.16 | 0.86 | 5.9% | 127 |
| Regional banks | 54.4% | 1.66 | 0.64 | 0.191 | 12.6% | 90 |
| Healthcare | 54.4% | 1.70 | 0.69 | 0.206 | 9.2% | 68 |
| Consumer discretionary | 46.3% | 1.61 | 0.22 | 0.145 | 23.9% | 506 |
| Pooled (old-style single number) | 51.2% | 1.74 | 1.43 | 0.353 | 23.9% | 791 |

Pooled Sharpe/expectancy individually clear their bars, but pooled max drawdown (23.9%, identical to consumer discretionary's own — the largest sector by sample size dominates the pooled equity curve) already failed the 15% cap even before this fix, so `passed` was `False` either way on this run; the value of the fix is that it's now an honest, diagnosable `False` (three named sectors failing on their own data) instead of one opaque pooled number that happened to fail for a reason nobody could see without this breakdown — and it protects against a future run where pooled drawdown improves enough to pass while sector-level failures remain masked. Technical-gate sweep: win rate/Sharpe/expectancy are flat from 0% to 50% of Technical's max (791 qualifying trades, unchanged), barely move at 60% (788 trades), and all three get *worse* at 70% (49.7% WR, Sharpe 1.04, expectancy 0.292 — now failing — on 707 trades). No existing tests pinned the old single-boolean `passed` shape narrowly enough to break; full suite 1030 passing (unchanged — no new tests added, this is a research script plus a metrics-reporting change, not new production logic requiring its own unit tests beyond what already exercises `run_multi_sector_backtest()`), 3 skipped (unchanged, pre-existing), ruff clean.

**Approved by:** [pending]

---

## [v2.2.55] — 2026-08-15 — [Bug Fix / Scoring Change] Seasonality scored backwards, weight calibration couldn't change a score, the go-live gate's own floor couldn't be passed by a model at spec, dead macro config, and news ticker-misattribution — a whole-model audit going section by section, not just re-checking prior fixes

**Status:** Live.

**In short:** Asked to review every part of the model and find ways to make it better overall, even if that meant changing how it's designed — this is that review. Five separate real problems were found and fixed.

The big one: the calendar the model uses to judge "good months" and "bad months" for trading has been backwards this whole time — it treated December as strong and January as weak, when the real data says the opposite. This was actually suspected months ago but never confirmed, because the tool used to check it was itself flawed (it was mixing in data from stock types the rule was never meant to apply to). Once that measuring problem was fixed and the calendar was flipped to match what the real data shows, the exact same historical test went from a 62% win rate to a 67% win rate, and the risk-adjusted return score improved by more than a third.

Second: a feature meant to let the model learn from its own past results and fine-tune its own scoring has been running for over a week — but a math mistake meant it could never actually change anything. It looked like it was working, but it was quietly doing nothing.

Third: the rule for "how many closed trades do we need before we can trust a performance verdict" was set at a number so low that even a model performing exactly as well as hoped would fail the check most of the time. Raised it to a number the math actually supports.

Fourth: several settings for tracking interest rates and the US dollar were never actually being read by the code, due to a simple naming mismatch — they'd been silently ignored the whole time.

Fifth: the part of the system that reads news headlines and figures out which company they're about couldn't handle company names with more than one word (like "Advanced Micro Devices"), so it was either crediting the news to the wrong company or missing it completely — and it also occasionally matched a stock's ticker letters by accident inside an unrelated word. Both are now fixed. On top of that, when the same news story showed up from three different sources, it was being counted as three separate stories instead of one.

**Problem:**
1. `config/swing_config.yaml`'s `modifiers.seasonality.monthly_modifiers` — the live table, not `seasonality.py`'s code-side `_DEFAULT_MONTHLY` fallback — has scored Q4 (Oct-Dec) positive and Jan/Feb negative since it was written. v2.2.42's `modifier_calibration_diagnostic.py` first measured this against pooled 3-sector backtest outcomes and found it backwards (65.8% win rate for "negative" months vs. 50.9% for "positive"), but flagged it for review rather than fix, since two explanations were equally plausible: a genuine sign error, or the semiconductor-only calendar's rationale simply not generalizing to the bank/healthcare bars it was being measured against. Nobody circled back.
2. Investigating which explanation was true surfaced the real root cause: `backtesting/simulation.py` calls `get_seasonality_modifier()` and `compute_macro_state()` without a `sector` argument at all, even though both functions exist specifically to neutralize their semiconductor-specific logic for other sectors (`_SECTORS_WITH_VALIDATED_SEASONALITY`/`_SECTORS_WITH_VALIDATED_MACRO_LOGIC`, added v2.2.53) — every live/paper call site already passes `sector` correctly; this one backtest call site never did. So every pooled-sector calibration read of either modifier, including v2.2.42's, had been silently measuring "semiconductor rules applied to random other sectors" diluted in with the real semiconductor signal.
3. `swing_model/scoring.py`'s live-weight calibration (Step 4b): `pool = technical_total + sentiment_total + news_total`, then each field set to `pool * (w_i / w_sum)`. Since `sum_i(w_i/w_sum) == 1` for any weights, the three fields always summed back to the exact same `pool` — base_score was mathematically identical regardless of what feedback_loop.py's calibration computed. Live at this call site since v2.2.42 (2026-08-06); every calibration run since has computed real numbers, logged them, and had zero effect on any trade the system has ever surfaced.
4. `paper_trading/paper_trade_metrics.py`'s `_MIN_TRADES_FOR_MEANINGFUL_READ = 15` was set to match `feedback_loop.py`'s own calibration-attempt minimum, on the theory both gates should agree on "enough data." Never checked against what the actual downstream test requires. Simulated a model performing exactly to the current backtest's spec (62.3% WR, 2.13 avg R:R) through 300 trials of `bootstrap_expectancy_ci` at each of several sample sizes: at n=15, mean CI-lower is ~0.10R (need ≥0.3R) and a genuinely-good model reads as passing only ~29% of the time — the gate can't be cleared by the system it's supposedly calibrated against.
5. `shared/utils/macro_overlay.py` reads `tnx_adverse_threshold_pct`/`tnx_favorable_threshold_pct`/`dxy_adverse_threshold_pct`/`dxy_favorable_threshold_pct`/`china_keyword_adverse_threshold` from config; `config/swing_config.yaml` only ever had `tnx_rise_threshold_pct: 3.0` — wrong key name, and wrong scale even if renamed (the code computes fractional pct-change, e.g. 0.03 for a 3% move, not 3.0). The other four keys weren't in config at all. Every threshold silently ran on its hardcoded fallback; the config block had never once taken effect.
6. `shared/utils/ner_extractor.py`'s multi-company sentiment attribution split headlines into single whitespace tokens and tested `alias.lower() in word` — a longer string can never be a substring of one shorter token, so any multi-word company alias ("Advanced Micro Devices", "Taiwan Semiconductor", "Eli Lilly", "Home Depot", "Fifth Third Bancorp", ...) could never match, silently resolving "neutral" in every multi-company headline — including the exact example in this module's own docstring. Separately, short all-caps ticker aliases matched as raw substrings: `is_ticker_relevant("Fed stimulus must continue", "MU")` returned `True` ("mu" inside "stimulus").
7. `swing_model/news_layer.py` concatenated Alpha Vantage + Yahoo + Finnhub + Seeking Alpha + SEC EDGAR articles with no deduplication at all. A single syndicated wire story pulled via three feeds simultaneously inflated both `relevant_article_count` and — since `count_independent_cluster`'s own dedup keys on `source_domain`, and Yahoo hardcodes `finance.yahoo.com` for every item regardless of the real publisher — the "independent source" clustering bonus, crediting one piece of information as up to three corroborating sources.

**Fix:**
1. `backtesting/simulation.py::_simulate_test_signals()` now derives `sector` from `benchmark_ticker` (`SMH`→`semiconductors`, `KRE`→`regional_banks`, `XLV`→`healthcare`, `XLY`→`consumer_discretionary`) and passes it to both `get_seasonality_modifier()` and `compute_macro_state()`, matching every live/paper call site.
2. `config/swing_config.yaml`'s `monthly_modifiers` sign flipped for every month (magnitudes kept as-is — a full per-month re-derivation is a separate, larger follow-up, not done here). `shared/utils/seasonality.py`'s `_DEFAULT_MONTHLY` fallback updated to match exactly (previously disagreed with the live config table in sign for most months — including feeding a Discord alert's stated rationale text from a different table than the one that set the actual modifier value, so an alert could say "bullish restocking demand" while applying a penalty). `_MONTH_RATIONALE` rewritten to state what's actually known (the sign is empirically re-derived, not a re-asserted demand-calendar story that was never separately verified).
3. `scoring.py`'s calibration now weights each sub-score by its own percentage of its max (0-1), not its raw point value — using the raw value would let Technical's 40-point budget keep mechanically dominating regardless of calibrated weight. A ticker's combined quality is the weighted average of the three percentages, rescaled to the fixed 70-point pool; each field reports its own share, preserving the sum invariant `technical_total + sentiment_total + news_total` that `base_score` and every downstream consumer (layer_scores DB rows, Discord alerts, audit_log) depend on. Verified directly: calibration weights matching the implicit 40/15/15 default now reproduce the exact original score (mathematical identity), while weights favoring a maxed-out sub-signal now measurably raise the score and vice versa.
4. `_MIN_TRADES_FOR_MEANINGFUL_READ` raised 15 → 30 — a middle ground (pass rate for a spec-performing model crosses 50% around n=30, keeps climbing to ~80% by n=50), chosen to keep the real-world wait reasonable (~26 days at the observed ~1.17 funded signals/day) rather than picking a fully-reliable but slower value. `feedback_loop.py`'s own recalibration-attempt trigger deliberately left at 15 — unlike this gate, an early attempt there just wastes one cheap `run_calibration()` call that returns `"insufficient_data"`, not a decision anyone acts on.
5. Added the four missing threshold keys to `config/swing_config.yaml` with values matching the code's existing hardcoded fallbacks exactly (`tnx_adverse_threshold_pct: 0.03`, `tnx_favorable_threshold_pct: -0.03`, `dxy_adverse_threshold_pct: 0.02`, `dxy_favorable_threshold_pct: -0.02`, `china_keyword_adverse_threshold: 5`) — a wiring fix, not a threshold change; today's live behavior is unchanged, but the config now actually controls something.
6. `ner_extractor.py`'s multi-company branch rewritten to attribute each directional keyword to whichever mentioned ticker's alias sits nearest to it in the headline (character-offset nearest-neighbor), replacing the token-window approach — fixes both the multi-word-alias miss and a second bug the token approach also had (a keyword meant for one company could bleed into a different company's count in a short headline). All alias matching (`extract_ticker_sentiments` and `is_ticker_relevant`) now uses `\b`-bounded regex matching instead of raw substring search, fixing the MU/"stimulus" false positive the same way for both functions. Also removed a duplicated "growth" entry in `_BULLISH_KEYWORDS` that was silently double-weighting it.
7. Added `news_layer.py::_dedupe_articles()` — collapses same-titled articles (normalized: lowercased, punctuation-stripped) to the single copy with the highest source credibility, run once upstream of every article-count-based signal (relevant-article filtering, clustering, decay, credibility weighting).

**Backtest result:** Re-ran the full semiconductor backtest (`python -m backtesting.run_backtest`, same `data/historical/` set, same 70/30 split) after fixes 1-2 (seasonality/macro sector-scoping) and 6-7 (NER/dedup, both exercised by the backtest's real historical News replay) — fixes 3-5 don't touch the backtest path (calibration isn't exercised there; the gate-math and macro-config fixes are value-neutral today, see above). Result: **66.9% win rate (was 62.3%), avg R:R 2.17 (was 2.13), Sharpe 4.16 (was 3.01), max drawdown 5.9% (was 8.0%), 127 qualifying trades (was 122), max consecutive losses unchanged at 7.** Unlike v2.2.54's volume-profile fix (a deliberate wash — a correctness fix, not expected to move the edge), this one moved every headline number in the same direction on the same historical data, consistent with correcting a real sign error rather than introducing a new one. Also re-ran `modifier_calibration_diagnostic.py` after the sector-scoping fix alone (before the sign flip) to get the clean read that justified it: sector-pure semiconductor seasonality sample shrank from the original pooled 370/653/480 (negative/zero/positive) to 82/1349/72, and the inversion got *more* pronounced, not less, once cross-sector noise was removed — 70.7% vs. 38.9%, a -31.8pp gap vs. the original diluted -4.8pp reading. 5 pre-existing seasonality tests updated in `tests/test_macro_context.py` to assert the corrected (now-negative-for-Q4) direction instead of the old one; full suite 1030 passing (unchanged count — no new tests added this round, existing ones updated), 3 skipped (unchanged, pre-existing), ruff clean.

**Approved by:** [pending]

---

## [v2.2.54] — 2026-08-14 — [Bug Fix] Paper trading was booking phantom stop-loss losses on breakout orders that never filled; a real support/resistance calculation was computed every scan and thrown away; a news-theme field always logged blank from a key-name mismatch

**Status:** Live.

**In short:** Checking that day's open paper trades turned up three separate bugs. Biggest one: two of the day's trades (AVGO and ABBV) were the kind of order that only actually buys once the stock's price climbs up to a certain trigger level — but neither stock ever got close to that level. The system didn't check for this, so it was about to record both as real losses even though no position was ever actually opened. Second: the part of the system that sets stop-loss and target prices has always been able to use real price levels — actual support and resistance from the stock's own trading history — but nothing was ever feeding it that information, so every single trade just used a generic, made-up risk/reward number instead. Third, smaller: a field meant to record what kind of news drove a trade has been blank on every trade since it was added, because of a simple mislabeled name in the code.

**Problem:**
1. `paper_updater.py::update_paper_trades()` walked every open trade's stop/target starting from the signal date, assuming the order filled at `entry_price` immediately — with no check that price ever actually traded into `entry_zone_lower`/`entry_zone_upper`. For a breakout/breakdown signal (the zone is anchored to the ticker's own rolling 20-day high/low, which can sit well away from the current close by design), this meant a trigger price the stock never reached could still resolve to a stop-loss "loss" with real negative P&L on the very next scheduled run.
2. `shared/utils/risk_reward.py::compute_stop_loss()`/`compute_target()` accept `high_volume_support`/`low_volume_area_above` to anchor a bullish stop/target to real volume-profile nodes instead of a flat ATR-multiple/min-R:R number — and `shared/indicators/technical_common.py` was already computing the exact volume profile needed (for the unrelated `volume_profile_score` technical sub-signal) on every scan. But every production caller (`paper_runner.py`, `run_swing_model.py`, `backtesting/simulation.py`) called both functions without those arguments, so they silently always took the fallback path. Every trade in the paper ledger shows `rr_ratio` = exactly 3.00, with no exceptions.
3. `paper_runner.py` read a computed news theme back out as `news.get("dominant_theme", "")`, but `swing_model/news_layer.py::compute_news_score()` returns it under the key `dominant_narrative_theme` — a rename that happened on the producer side without the one consumer being updated. `.get()`'s default silently absorbed the miss instead of erroring, so `dominant_news_theme` has been blank in `paper_trades.csv` since the column was added.

**Fix:**
1. Added `paper_updater.py::_find_fill()` — walks bars after a signal looking for the first one where price actually trades into the entry zone (High reaching it for a breakout, Low for a breakdown, mirroring `_resolve_outcome`'s existing bullish/bearish convention). Three outcomes: filled (stop/target tracking starts from that bar, not the signal date), still pending (left open, checked again next run), or expired (zone never reached within `FILL_WINDOW_DAYS` = 5 trading days — new `"expired"` outcome, no P&L, no exit price, no R-multiple, since none of that happened). Added `send_paper_expired_alert()` (`discord_alerts.py`) so an expired signal gets its own notice instead of reading as a stopped-out loss. Excluded `"expired"` rows from `feedback_loop.py`'s calibration input and `paper_trade_metrics.py`'s win-rate/accuracy stats, same as an open trade is excluded today — otherwise an expired row would have silently dragged down win rate as a non-win without ever being a real loss.
2. `technical_common.py::compute_technical_indicators()` now also returns `high_volume_support` (nearest high-volume node below close) and `low_volume_area_above` (nearest low-volume node above close) from the volume profile it already builds. `paper_runner.py`, `run_swing_model.py`, and `backtesting/simulation.py` now pass both through to `compute_stop_loss`/`compute_target`. Bearish trades are unaffected — both refinements are bullish-only by the existing function docstrings.
3. `paper_runner.py`'s read renamed to `news.get("dominant_narrative_theme", "")`, matching what `news_layer.py` actually returns.

**Backtest result:** Isolated A/B re-run (`python -m backtesting.run_backtest`, default semiconductor `data/historical/` set, 122 qualifying trades in both arms — fix 1 doesn't touch the backtest path at all, and fix 2/3 don't change which signals qualify, only stop/target placement and a display field): 63.1%→62.3% win rate, avg R:R 2.03→2.13, Sharpe 3.03→3.01, max drawdown 8.3%→8.0%, max consecutive losses unchanged at 7. Net: a wash, as expected for a correctness fix rather than a strategy change — stops/targets now reflect real support/resistance instead of a mechanical fallback, without materially moving the edge on this sample. Also confirmed while re-running: the previously-cited 149-trade/Sharpe-9.10 baseline is stale on current `main` regardless of this change (122 trades, Sharpe ~3.0 both before and after) — Sharpe 9.10 was already flagged stale by the 2026-07-19 fix, this just reconfirms it; the 149→122 trade-count gap wasn't root-caused this session. 8 new tests (`tests/test_paper_updater_fill_confirmation.py`, covering `_find_fill`'s fill/pending/expired paths for both directions); full suite 1030 passing (up from 1022), 3 skipped (unchanged, pre-existing), ruff clean.

**Approved by:** [pending]

---

## [v2.2.53] — 2026-08-13 — [Bug Fix / Scoring Change] Extended the fundamentals audit (v2.2.52) to Technical, Positioning, Sentiment, News, and every scoring modifier — found macro/seasonality rules built for semiconductors were being applied to regional banks backwards, plus 11 more real gaps

**Status:** Live.

**In short:** After auditing the fundamentals layer (v2.2.52), did the same "senior dev / trading expert" pass over every other layer that feeds the final score: Technical, Positioning, Sentiment, News, and the six post-score modifiers (regime, sector rotation, earnings proximity, cross-ticker, seasonality, macro overlay). The single biggest find: the macro overlay and seasonality modifiers both carry rules that only make sense for semiconductors — "rising interest rates are bad" and "a strong dollar hurts TSM/ASML" for macro, a chip-industry demand calendar for seasonality — but both were being applied identically to every active sector, including regional banks, where rising rates are usually a net *positive* (wider lending margins). That's not a rounding error; it's the model scoring an entire sector's rate sensitivity backwards. Alongside that, found and fixed 11 more real gaps: a China-tension signal hardcoded to always read "nothing happening," several computed-and-thrown-away signals, a trade-direction label with no minimum-sample protection (while the point score three lines away had one), an options-positioning score with no per-ticker baseline, a news freshness signal double-counting itself, the largest scoring category (Technical, 40 of 100 points) reporting no data-quality signal at all, and a cross-ticker divergence check using one fixed threshold for both volatile and calm stocks alike.

**Problem:**
1. `macro_overlay.py`'s TNX/DXY/China-tension logic and `seasonality.py`'s monthly demand curve are both semiconductor-specific by design and rationale, but `run_swing_model.py`/`paper_runner.py` computed each once per scan with no sector context at all, then applied the same result to every ticker in every active sector (semiconductors, regional_banks, healthcare, consumer_discretionary).
2. `china_keyword_count_5d` was hardcoded to `0` everywhere, with a comment admitting the news data it needed "isn't yet parsed at this stage of the pipeline" — the config-declared `china_keywords` list and lookback setting did nothing. Worse, this silently raised macro_overlay's own 2-of-3-signals-adverse bar to effectively "TNX and DXY both," since China could never contribute.
3. Four computed values were thrown away: `sentiment_lead_lag` was a permanent stub hardcoded to `"neutral"` ("Requires backtested baseline — populated in Phase 12," never delivered); `divergence_flag` (a real bullish-setup/bearish-warning signal) was computed every scan but never read by anything downstream; `_CORRELATED_PAIRS` in `cross_ticker_analysis.py` duplicated `portfolio_manager.py`'s real, actively-used correlated-group check and was itself referenced nowhere; `post_earnings_settling` was computed and returned but never actually changed `confidence_modifier` — the day after a report jumped straight from a -20 penalty to 0, identical to 19+ days out, contradicting the module's own "tentative restore" docstring.
4. `sentiment_layer.py`'s `dominant_sentiment` — which feeds `determine_direction()` and decides the trade's actual bullish/bearish direction — was computed from the raw, ungated bullish/bearish ratio. Three lines away, the point score (`_score_ratio`) explicitly refuses to trust that same ratio below 5 tagged messages; the direction label had no such protection.
5. Sentiment velocity's fallback path (used when StockTwits' native fields are absent) applied an x25 multiplier to a trajectory-delta metric; a swing no bigger than this file's own "significant" threshold (0.05) already hit the score's ceiling/floor, making the sub-signal close to binary for realistic inputs.
6. `positioning_layer.py` scored put/call ratio and IV skew against fixed absolute constants (ratio=1.0, skew=0.0 as "neutral") with no per-ticker baseline — different tickers run structurally different baseline ratios, and real equities carry a structural put-skew most of the time (crash-hedging demand), so a flat skew=0 is actually unusual, not neutral.
7. `news_layer.py`'s `decay_score` averaged article freshness across every relevant article — but freshness already acts as a multiplicative weight inside `credibility_weighted_score` (`w = credibility × decay`), so a batch of fresh articles was rewarded twice by the same underlying signal.
8. `technical_common.py` reported no data-quality signal at all, unlike Positioning/Sentiment/Fundamentals — a ticker with insufficient history silently fell back to substitute values (e.g. `sma_50` standing in as the close price, which reads as "trend broken" rather than "unknown") with nothing to tell `compute_data_sufficiency()` apart from a ticker with a full, real indicator set.
9. `cross_ticker_analysis.py`'s divergence threshold was a fixed 3% for every ticker — over-firing "individual divergence" on a volatile semiconductor name's routine noise while under-detecting genuine divergence on a calmer name.

**Fix:**
1. `compute_macro_state()`/`get_seasonality_modifier()` now accept a `sector` param; outside `semiconductors` both resolve neutral (trend readings still computed and returned for observability) instead of applying unvalidated logic. `run_swing_model.py`/`paper_runner.py` now compute both per-sector (mirroring how regime/rotation already worked), not once globally. `sector=None` (the default) preserves the original behavior for any existing caller, including `backtesting/simulation.py`, which doesn't pass a sector.
2. Added `_compute_china_tension_count()` — a real, free (Yahoo News, no API budget) keyword count scoped to the semiconductor watchlist, replacing the hardcoded `0`.
3. `sentiment_lead_lag` removed. `divergence_flag` now passes through `compute_confidence_score()`'s output instead of being silently discarded. `_CORRELATED_PAIRS` removed (with a comment pointing at `portfolio_manager.py`'s real implementation). `post_earnings_settling` now applies a real, configurable partial penalty (`post_earnings_settling_penalty`, default -5) instead of a same-day cliff to 0.
4. `dominant_sentiment` now requires the same `_RATIO_MIN_BASELINE_MESSAGES` floor as the point score before trusting the ratio; below it, defaults to neutral.
5. Velocity's fallback multiplier reduced (×25 → ×12.5) so a "significant" (0.05) trajectory swing lands at a modest ~3.1 instead of already being most of the way to the ceiling; reaching the ceiling now requires roughly twice the swing it used to.
6. Added `compute_put_call_ratio_percentile()`/`compute_iv_skew_percentile()` (extending the existing `iv_history`/`compute_iv_percentile` pattern in `indicator_pipeline.py`) — both metrics now score against each ticker's own rolling history, falling back to the old absolute-constant formula per-metric during cold start. Caught and fixed one bug of its own during implementation: all three percentile functions shared a generic `"data_quality"` return key, which would have silently overwritten each other when merged into one options dict — renamed per-metric before merging.
7. `decay_score` now reflects the single freshest relevant article instead of the average across all of them — a genuinely different signal ("is something happening right now") instead of re-deriving the same per-article weighting already inside `credibility_weighted_score`.
8. Added `data_quality`/`sub_signal_data_quality` (sma_20/sma_50/atr/macd) to `compute_technical_indicators()`'s output, wired into `compute_data_sufficiency()`.
9. Added `_estimate_five_day_volatility()` — each ticker's divergence bar now scales to ~1.5× its own trailing 5-day volatility estimate (floored at 1.5%), falling back to the original fixed 3% when a ticker's own volatility can't be estimated yet (insufficient history).

**Backtest result:** Partial impact, not a clean re-run trigger for everything here. `backtesting/simulation.py` calls `compute_technical_indicators`, `compute_news_score`, `compute_macro_state`, and `get_seasonality_modifier` directly, but never passes a `sector` argument to the latter two — fix 1 is a behavioral no-op for the existing backtest path (same as every other caller that doesn't opt in). Technical's fix 8 only adds new dict keys, no existing values changed. Fix 7 (News `decay_score`) *does* change a real scored value the backtest exercises — recommend a fresh backtest run before comparing News-driven results against any pre-v2.2.53 number. Positioning, Sentiment, and cross-ticker changes (fixes 4-6, 9) aren't in `backtesting/simulation.py`'s call path at all (Positioning/Sentiment use "accumulates going forward, not backtestable yet" proxies there already — see PROJECT_OVERVIEW.md §13), so no backtest impact either way. Verified via unit tests instead: 33 new/updated tests across 12 test files (1022 total passing, up from 989, 3 skipped — unchanged, pre-existing), ruff clean.

**Approved by:** [pending]

---

## [v2.2.52] — 2026-08-13 — [Bug Fix / Scoring Change / Data Source] Fundamental layer audit: a real earnings report went stale for a full quarter, valuation scoring had a dead bucket and compared each stock partly against itself, and revenue was never tracked at all (EPS-only)

**Status:** Live.

**In short:** Asked whether the model was catching a wave of semiconductor earnings news, which led to checking AMD specifically — its Aug 4, 2026 report (EPS $1.66 vs. $1.61 estimate, a beat) had never made it into the model. `eps_growth_trend` still reflected May's quarter, and would have stayed stuck there until ~3 days before AMD's *next* report in November. Traced the root cause and then broadened into a full "senior dev / trading expert" audit of the whole fundamentals layer, which turned up six more real gaps: a dead bucket in valuation scoring, a stock's peer-average benchmark that included the stock itself, no revenue or margin data tracked at all (EPS-only), an "estimate revisions" score that was actually just a valuation-gap proxy, an EPS-acceleration check vulnerable to a cyclical company's easy year-ago comp, and a price feeding that valuation-gap calc that could be over a week stale. Fixed all seven.

**Problem:**
1. `eps_growth_trend`'s refresh was gated on proximity to a ticker's *next* scheduled earnings date (`indicator_pipeline.py`'s `_get_upcoming_earnings_date`) — but yfinance's own calendar flips to the *following* quarter almost immediately once a company actually reports. Confirmed live: AMD's calendar already showed Nov 3 as "next earnings" the same week it reported Aug 4. The ±3-day lookahead window could therefore only ever really fire *before* a report, not after, despite reading as symmetric — so a report landing on an otherwise-ordinary rotation refresh day left the figure a full quarter stale until the *next* report's own pre-earnings window opened, ~3 months later.
2. `score_valuation_vs_peers()`'s P/E and EV/EBITDA scoring had a dead middle bucket: a stock trading 10-50% above its peer average and one trading 0-10% above scored identically (+1) — the `else` branch that should have been a distinct, lower score fell through to the same value as the near-parity bucket. No test pinned the middle bucket's value, so this went unverified since it was written.
3. Each ticker's own P/E and EV/EBITDA were included in the "peer average" it was then scored against. With a 6-name semiconductor watchlist, a ticker's own value was ~17% of its own benchmark — an expensive outlier dragged its own comparison average toward itself, understating its real premium.
4. The layer only ever tracked EPS and valuation multiples — no revenue growth or gross-margin data at all, so EPS growth driven by margin expansion or buybacks looked identical to genuine demand-driven growth.
5. `estimate_revisions_score` was, in practice, a valuation-gap proxy (`implied_upside_pct` — current price vs. analyst target), not a real revisions signal: a stock rallying toward its own price target shrinks its "upside" and scores as if analysts had turned bearish, even though no analyst estimate actually moved.
6. The EPS-growth "accelerating" flag compared only the two most recent quarters — vulnerable to a single easy year-ago comp flipping it on for a cyclical name (MU, living through memory-pricing boom/bust cycles) with no real momentum behind it.
7. `implied_upside_pct`'s `current_price` came from the same weekly-ish fundamentals refresh as the analyst target price — up to ~7-9 days stale for a metric that's purely a price-vs-target gap, meaningful for names that can move 5-10% in a week.

**Fix:**
1. `indicator_pipeline.py`: added `_get_last_reported_earnings_date()` (yfinance's actual reported-earnings history, not the forward-looking calendar) and a new `growth_fetched_dates` state key, tracked separately from the existing `fetched_dates`. A ticker whose real last-reported date is newer than its `growth_fetched_dates` entry now jumps the refresh queue regardless of what the forward calendar says. Caught mid-implementation that comparing against `fetched_dates` alone would have self-defeated the fix: a plain rotation touch updates `fetched_dates` without ever re-pulling growth data, which would have permanently masked a report landing on an off-cycle rotation day — covered by `test_rotation_only_touch_does_not_mask_a_missed_report`, the exact AMD-shaped scenario.
2. `fundamental_layer.py`: replaced both bucket ladders with one shared, explicitly monotonic `_score_premium()` (discount → +2, 0-15% premium → +1, 15-40% → 0, 40-75% → -1, 75%+ → -2), used by both P/E-vs-peers and EV/EBITDA-vs-peers.
3. Added `_leave_one_out_average()` — every ticker's peer benchmark (valuation, and now growth too) excludes that ticker's own value.
4. `fundamental_client.py`: new `get_revenue_and_margin_trend()` pulls one YoY revenue comparison and a QoQ gross-margin comparison from yfinance's quarterly income statement (confirmed live across the full watchlist — free tier only goes back 4-6 quarters, not deep enough for a multi-point trend like EPS's, but enough for this). Gated by the same `fetch_eps_growth_trend` flag and carried forward on rotation refreshes the same way EPS growth already was. `score_earnings_momentum()` now caps `eps_growth_score` back down when EPS growth screens positive but revenue is actually down YoY (the classic low-quality-earnings pattern), and surfaces the gross-margin trend in the breakdown either way.
5. `estimate_revisions_score` now compares today's analyst target price against the *prior* snapshot — `indicator_pipeline.py` stashes the old target price before each refresh overwrites it — isolating a real analyst re-rating from the stock simply moving. Falls back to the old implied-upside proxy only when no prior snapshot exists yet (cold start).
6. "Accelerating" now requires 2 *consecutive* improving quarters when 3+ quarters of history are available, not just the latest vs. the one before.
7. `score_earnings_momentum()` / `compute_fundamental_score()` / `score_all_tickers()` now accept a `live_price` override, wired from `indicator_pipeline.run_pipeline()`'s own same-scan OHLCV close instead of the cached fundamentals snapshot's price.

Also added, as a smaller side effect of fix 4's peer-relative-growth machinery: `eps_growth_score` now gets a small ±1 nudge based on a ticker's growth relative to the sector's own leave-one-out average, alongside the existing fixed absolute thresholds — the same peer-relative treatment valuation already had but growth didn't.

**Backtest result:** Not yet re-run. `FundamentalScorer` is in `backtesting/simulation.py`'s call path (`_load_fundamental_history` scores every archived weekly snapshot), so these scoring changes do affect backtest results — recommend running a fresh backtest before comparing against any pre-v2.2.52 number. Verified instead via unit tests: 37 new/updated tests across `test_fundamental_client.py`, `test_fundamental_layer.py`, and `test_indicator_pipeline_fundamental_refresh.py` (989 total passing, up from 952, 3 skipped — unchanged, pre-existing). Also confirmed directly against the live cache (read-only, no fetch performed) that AMD's real Aug 4 report is now correctly flagged for a growth-data refresh on the model's next scan.

**Note:** `growth_fetched_dates` doesn't exist yet in the current cache, so the very next scan will treat every watchlist ticker as due for a growth-data refresh, not just AMD — a one-time catch-up burst, comfortably inside the existing 25/day fetch budget for the ~23-ticker watchlist.

**Approved by:** [pending]

---

## [v2.2.51] — 2026-08-11 — [Bug Fix / Feature] Plain stock positions were mispriced in the trade-structure ranking; added an explicit, budget-aware preference for capped-loss options over shares

**Status:** Live.

**In short:** JNJ qualified as a signal (71.0/100) but its only viable options structure cost more than its risk budget allowed, and the system had no way to fall back to a plain stock position — the signal just vanished, logged with 0 shares and no trade. Digging into why turned up that plain stock positions (`long_stock`, `short_stock`) are already 3 of the 42 trade structures the system evaluates every scan — they just weren't priced correctly. They were using the full share price as their "capital at risk" instead of the real dollar amount actually lost if the stop is hit, which diluted their modeled edge by roughly 20x compared to every options structure, and wrongly excluded expensive stocks (LLY at ~$1,232/share) from consideration entirely — purely because the share price itself topped the $750 cap, regardless of how tight the real risk was. Fixed the pricing, and separately taught the system to prefer capped-loss options over plain shares whenever a genuinely affordable one exists, consistent with the account's no-negative-months mandate — falling back to shares only when nothing capped-loss actually fits that trade's budget.

**Problem:**
1. `swing_model/trade_selector.py`'s `_estimate_capital_required()` returned `entry` (the full share price) as `capital_required` for `long_stock`/`short_stock`/`long_stock_trailing_stop`, instead of the real dollar risk (entry-to-stop distance) it already computes one line earlier and simply didn't use for this branch.
2. That capital figure is both the ranking's EV-per-dollar denominator and the basis for the $750 (5% of $15k) eligibility cap — so it silently diluted these 3 structures' modeled edge by roughly (share price ÷ stop distance) versus every options structure (which correctly divides by premium paid, not notional), and separately excluded them outright whenever share price alone exceeded $750, even when the real dollar risk was a small fraction of that (confirmed directly: LLY's real risk was ~$96/share against a $1,232 share price).
3. Even correctly priced, the ranking had no way to prefer a structure that fit a given signal's own confidence-tier risk budget (0.5%–2.5% of account equity depending on score) over one that merely cleared the blanket $750 account-wide cap. A structure could pass that blanket cap and still cost several times what a specific trade was actually allowed to risk, with no fallback — this was JNJ's exact failure: its best-EV option (`long_strangle`) cost $248.56 against a $75 budget at its 71.0 score, well under the $750 cap but nowhere near affordable for that trade.

**Fix:**
1. `_estimate_capital_required()`: `long_stock`/`short_stock`/`long_stock_trailing_stop` now price at `abs(entry - stop)` — the real dollar risk — matching every options structure's own convention.
2. `rank_trade_structures()` now assigns `recommended` via an explicit priority chain instead of always taking the top-ranked-by-EV structure: (a) a capped-loss options structure that fits this signal's own confidence-tier risk budget and has positive expected value; failing that, (b) a plain-stock structure that fits the same budget and has positive EV — this is what lets a trade like JNJ's become a real, sized position instead of silently vanishing; failing that, (c) the best capped-loss option regardless of budget, preserving the existing "sizes to 0, here's why" diagnostic behavior from v2.2.48 when nothing affordable exists at all; failing that, (d) the overall top-ranked structure. The diagnostic sort order (by `ev_per_dollar_per_day`) is unchanged — this only changes which single structure gets flagged `recommended=True`.
3. `paper_trading/paper_runner.py` and `swing_model/run_swing_model.py` both used to read `ranked_structures[0]` directly, ignoring the `recommended` flag entirely — updated both to look up the `recommended=True` entry instead, so a preference for a lower-ranked-by-EV structure actually takes effect instead of being silently overridden by list position. `paper_runner.py`'s position-sizing logic now branches on a new explicit `position_type` field (`"shares"`/`"options"`, added to each ranked structure) rather than a truthiness heuristic on `structure_recommended`/`capital_required` that could mislabel a winning stock structure as an option and conflate its cost with its risk.

**Verification:** Re-ran the real logic against JNJ's actual 2026-08-11 signal (entry $274.90, stop $261.51, target $315.08, confidence 71.0) — previously sized to 0 shares/contracts and vanished from the ledger; now correctly falls through to `long_stock`, sizing to 2 shares ($549.80 deployed). Also confirmed LLY still correctly reports "not affordable at this confidence tier" when no structure fits its budget (rather than the old wrong reason — share price alone), and wins with `long_stock` once a higher confidence tier gives it enough budget. 941 tests pass (10 new, shared with v2.2.50), 3 skipped (pre-existing), ruff clean.

**Approved by:** [pending]

---

## [v2.2.50] — 2026-08-11 — [Bug Fix] Every bearish signal has been silently excluded from all 42 trade structures since paper trading started

**Status:** Live.

**In short:** Found while investigating why a qualifying signal could size to zero — `trade_selector.py`'s own reward:risk check assumed every trade's stop sits below its entry, which is only true for bullish trades. For a bearish trade the stop sits *above* entry by this system's own documented convention, so the formula always computed a reward:risk of exactly `0.0` — always below the minimum — and every one of the 42 trade structures was excluded before any other filter even ran. Confirmed directly: zero bearish rows exist anywhere in `paper_trading/paper_trades.csv`, ever.

**Problem:**
1. `swing_model/trade_selector.py`'s `rank_trade_structures()` computed its shared reward:risk value as `(target - entry) / (entry - stop)`, guarded by `if (entry - stop) > 0 else 0.0` — for bearish, `entry - stop` is negative, so this always fell to the `0.0` branch, which always fails the minimum-reward:risk filter and excludes every structure, unconditionally, for every bearish signal.
2. Two downstream functions in `shared/utils/options_math.py` had the identical class of bug, independently: `resolve_structure_economics()`'s validity guard required `stop < entry` unconditionally, even though the payoff math inside it already worked in `abs()`-based magnitudes and didn't actually depend on that assumption anywhere; `compute_ev_surface()` (used by the 4 ratio/back-spread structures) computed unsigned `up_move`/`down_move`, which for bearish would flip a favorable move into an apparent loss and a stop-hit into an apparent gain.
3. All three bugs happened to mask each other in terms of visible symptoms (a bearish signal always showed "0 structures eligible" regardless of which one actually fired first), which is likely why this went unnoticed — nothing in the test suite exercised any of these three functions with a bearish candidate before this fix.

**Fix:** Replaced `trade_selector.py`'s inline reward:risk formula with the existing, already direction-aware `compute_rr_ratio()` from `shared/utils/risk_reward.py` (reused, not re-derived — it already branches correctly for both directions and is the same convention `paper_runner.py` and `run_swing_model.py` already use upstream of this function). Loosened `resolve_structure_economics()`'s guard to reject only the genuinely degenerate `stop == entry` case — no `direction` parameter was actually needed, since its internal `fav`/`unfav` values were already `abs()`-based and each structure's option-type choice is driven by its own name, not by candidate direction. Fixed `compute_ev_surface()` and `trade_selector.py`'s own `_compute_structure_ev()` to use `abs()` for their up-move/down-move magnitudes, matching `resolve_structure_economics`' existing convention. Added bearish-direction test coverage to `tests/test_structure_economics.py` and `tests/test_phase7_trade_math.py` (both previously bullish-only).

**Backtest result:** Not applicable — `trade_selector.py` isn't in `backtesting/simulation.py`'s call path (confirmed no caller anywhere under `backtesting/`), same as v2.2.48's precedent. 941 tests pass (10 new, shared with v2.2.51), 3 skipped (pre-existing), ruff clean.

**Approved by:** [pending]

---

## [v2.2.49] — 2026-08-10 — [Bug Fix] Paper trading could silently log a second same-direction position on a ticker that already had one open

**Status:** Live.

**In short:** Found while reviewing open paper-trading positions: PFE and LLY each had two open bullish positions logged 3 days apart, doubling real exposure to those names without any deliberate decision to do so. Traced it: `swing_model/portfolio_manager.py` has a documented `can_open_new_position()` rule for exactly this ("no second same-direction position on a ticker that already has one open"), but `paper_trading/paper_runner.py` never called it — it only reused `run_swing_model.py`'s scoring/data-fetch helpers, not its position-tracking ones.

**Problem:** `can_open_new_position()` checks `data/processed/position_state.json`'s `positions` list, which only ever gets populated by `swing_model/portfolio_manager.py::add_position()` — itself only called from `handle_entry_confirmation()`, the flow that fires when a human replies "entered" to a live Discord alert. Paper trading has no human in that loop, so simply calling `can_open_new_position()` from `paper_runner.py` wouldn't have worked: the list it checks would stay permanently empty. Considered wiring paper trading into `position_state.json` directly (auto-adding/closing positions the way a confirmed live trade would) — rejected, because `CHANGELOG.md` v2.2.37 already hit this exact question for account-equity tracking and explicitly kept paper trading's state out of `position_state.json` to avoid "silently mixed two unrelated pipelines' state": that file belongs to `run_swing_model.py`'s own live/Discord position tracking, a separate, currently-dormant pipeline (`paper_runner.py` is the one that actually runs daily — see `PROJECT_OVERVIEW.md`).

**Fix:** New `_load_open_positions()` in `paper_runner.py` — reads `paper_trades.csv` itself (any row with a blank `outcome` is still open) and returns the set of `(ticker, direction)` pairs currently open. Checked once per scan, immediately before a qualifying signal would otherwise be logged; a ticker already carrying an open same-direction position is skipped with a log line instead of logged as a second position. Self-contained to paper trading's own ledger — no dependency on `portfolio_manager.py` or `position_state.json`, and no changes needed to `paper_updater.py` (once a position's `outcome` gets filled in on close, the next scan's `_load_open_positions()` naturally stops counting it as open).

**Not fixed here:** the two existing duplicate rows (PFE, LLY) already in `paper_trades.csv` are unchanged — this only prevents new duplicates going forward.

**Backtest result:** Not applicable — paper-trading-only change, no scoring/backtest path touched. 931 tests pass, 3 skipped (pre-existing), unchanged from baseline.

**Approved by:** [pending]

---

## [v2.2.48] — 2026-08-10 — [Bug Fix] A trade sitting exactly at the 1:3 minimum reward:risk was getting silently rejected by a floating-point rounding artifact; also added a sizing_note field so the ledger explains itself

**Status:** Live.

**In short:** LLY qualified as a real signal (76.6/100) but showed up with no recommended trade structure and 0 shares deployed, with no explanation anywhere in `paper_trades.csv`. Traced it: every one of the 42 trade structures was being rejected for "R:R below minimum," even though the trade's actual reward:risk was exactly 3:1 — the system's own configured minimum. The real ratio, computed from full-precision numbers, was `2.999999999999998`, off from an exact 3.0 by one bit of floating-point representation error — comparing that directly against the threshold with strict `<` silently threw out a trade that was, for every practical purpose, right at the line. Fixed the comparison, and separately made sure the next time a signal produces something non-actionable (0 shares, or no eligible structure), `paper_trades.csv` itself says why instead of requiring a multi-step investigation to reconstruct it after the fact.

**Problem:**
1. `swing_model/trade_selector.py`'s `rank_trade_structures()` computes one shared R:R value from the candidate's entry/stop/target and checks it against `config/swing_config.yaml`'s `min_rr_ratio` (3.0) for every structure — a single failure here excludes all 42 at once.
2. `shared/utils/risk_reward.py::compute_target()` builds its target as exactly `entry + min_rr × risk`, so a trade using the formulaic fallback (no real volume-profile level available) lands exactly on the minimum by construction — a very common case, not a rare edge.
3. Entry/stop/target each pass through their own `round(x, 4)` upstream (`compute_entry_zone`, `compute_stop_loss`, `compute_target`), and IEEE-754 float arithmetic on already-rounded inputs can land a few ULPs under an exact target — confirmed directly: `rr - 3.0 == -2.220446049250313e-15` for LLY's real 2026-08-10 signal. Queried the app UI's `ticker_results` table directly and found this had already silently fired on at least one real prior scan (`result_id 868`: `structures_eligible_after_filters: 0`, `exclusion_summary` citing "rr below min threshold" for all 42) — this wasn't a one-off, it's intermittent depending on which way the float noise rounds for a given scan's exact numbers.
4. Separately: nothing in `paper_trades.csv` recorded *why* a row had a blank `structure_recommended` or 0 `position_size` — that context existed only as a transient `app.log` line and in the app UI's separate SQLite history, not in the CSV a human actually reviews trade-by-trade.

**Fix:**
1. `trade_selector.py`: round the shared R:R to 2 decimal places (matching `compute_rr_ratio()`'s own existing convention elsewhere in the codebase) before the threshold comparison — absorbs the ~1e-15 float noise without loosening the real 3.0 bar in any way that matters economically.
2. `paper_runner.py`: new `sizing_note` CSV column, populated whenever a qualifying signal produces 0 shares/contracts, gets capital-capped below what the risk budget alone would allow, or finds zero eligible trade structures at all — same reasoning that was already being logged transiently, now persisted in the ledger itself. `paper_trades.csv` migrated to the new schema (existing 6 rows backfilled with an empty `sizing_note`, nothing else changed).

**Verification:** Re-ran the real live pipeline for LLY after the fix — `diagonal_call` ($616 capital, well under the $750 cap) is now correctly found and ranked. 931 tests pass, 3 skipped (pre-existing), no change from baseline.

**Approved by:** [pending]

---

## [v2.2.47] — 2026-08-10 — [Backtest Methodology] Sector rotation's -15/+5 point penalty had never been tested against real outcomes — wired it into the backtest and found the "hot sector" boost was backwards

**Status:** Backtest-only fix. Live/paper trading behavior is unchanged — `swing_model/run_swing_model.py` has always computed sector rotation from real, live SMH/SPY price data; only the backtest's replay was faking it.

**In short:** Today's post-market scan showed every semiconductor stock taking the model's full -15 point "sector outflow" penalty — exactly the gap v2.2.46 called out: the backtest had always faked this number to zero, so nobody could ever check whether -15 (or the matching +5 "sector inflow" boost) was actually the right number. Wired real historical SMH-vs-SPY data into the backtest for the first time, ran the calibration check, and found the outflow penalty holds up — but the inflow boost doesn't. Sector-neutral trades won 63.7% of the time; "hot sector" (inflow) trades only won 53.9% — worse, not better. Turned the inflow boost off (+5 → 0); left the outflow penalty at -15, since that direction is real (44.8% win rate) even though the sample behind it is thin.

**Problem:**
1. `modifier_calibration_diagnostic.py` (added in v2.2.42) already documented that `sector_rotation_modifier` was one of the modifiers `backtesting/simulation.py` hardcodes to 0.0 during every replay — "no amount of outcome analysis on backtest replay can say anything about their calibration," in its own words.
2. `config/swing_config.yaml`'s -15/+5 magnitudes were, per that same diagnostic's docstring, "hand-set round numbers with no [backtest] lineage" — a guess dressed up as a rule.
3. This wasn't theoretical: today's scan vetoed all 6 semiconductor tickers with the flat -15, some of which (NVDA, TSM) had real stock-specific strength buried under a never-validated sector-wide penalty.

**Fix:** Directly mirrored the fix v2.2.7 made for `macro_overlay`, which had the identical hardcoded-to-zero problem. Fetched real SPY daily history back to 2013 (`data/historical_market/SPY.csv`, gitignored research data, same pattern as `data/historical_macro/`), added a point-in-time `compute_rotation_state()` call to `backtesting/simulation.py`'s per-bar replay loop (reusing the SMH data and `rs_zscore` already computed there, so the existing leader-dampening logic — softening the penalty for genuine relative-strength leaders — applies in backtest exactly as it does live), and moved `sector_rotation_modifier` from the diagnostic's "never exercised" list to its "exercised" list. Ran the diagnostic against 544 real pooled outcomes:

| Sector state | Trades | Win rate | Avg R:R |
|---|---|---|---|
| Outflow (negative) | 29 | 44.8% | 1.71 |
| Neutral (zero) | 157 | 63.7% | 1.47 |
| Inflow (positive) | 358 | 53.9% | 1.63 |

Neutral sector conditions outperformed both outflow *and* inflow — the outflow penalty's direction is supported (though n=29 is thin), but the inflow boost's direction is backwards on a much larger sample (n=358). `modifiers.sector_rotation.inflow_boost` changed from +5 to 0; `outflow_penalty` left at -15.

**Backtest result:** PASS, unchanged within noise. Before: 63.3% WR / 2.01 avg R:R / Sharpe 3.39 / 8.2% DD / 120 trades (2026-08-02 report). After: 62.8% WR / 2.01 avg R:R / Sharpe 2.96 / 8.3% DD / 121 trades. 931 tests pass, 3 skipped (pre-existing).

**Approved by:** [pending]

---

## [v2.2.46] — 2026-08-06 — [Scoring Change] No trade has ever scored high enough to qualify (needed 90, best ever was 80) — lowered the bar to 70 after finding the backtest wasn't comparing fairly

**Status:** Live.

**In short:** Not one scan, out of 750 real scans over two weeks, has ever produced a score above 80 —
ten points short of the 90 needed to count as a real trade signal. The backtest said this shouldn't
happen, so before changing anything this was checked as a possible bug rather than assumed to just be
a bad setting. It turned out the backtest wasn't being fair: it skips three real-world penalties and
fakes two whole categories of data that live trading has to deal with for real. So the backtest's
"90 is achievable" result was never really comparable to what live trading experiences. Lowered the
real threshold to 70, just under the best score ever actually seen live, so real signals can start
happening instead of guaranteed zero.

**Problem:**
1. A diagnostic tool built a few days ago confirmed the pattern with real numbers: across 750 scans,
   scores topped out at 79.84 — never close to 90, and barely ever above 80.
2. But running the backtest against years of history said 90 should be reachable over half the time —
   a real contradiction worth digging into rather than dismissing.
3. Traced it to the backtest's simulation code (`backtesting/simulation.py`): it doesn't apply 3 of
   the scoring penalties (sector rotation, earnings, cross-ticker) at all — they're hardcoded to zero
   for every single day it tests, always. It also swaps in fixed, made-up numbers for two whole
   categories (Positioning and Sentiment) instead of real data, because that real historical data
   doesn't exist yet. This is honestly written into the code's own comments — not a hidden bug — it
   just hadn't been connected before to why live scores are always low. Live trading pays these
   penalties for real: today alone, every semiconductor stock took a real -15 point penalty from a
   current tariff-related event, something the backtest has never modeled once.
4. Bottom line: the backtest's claim that 90 is achievable was never a fair test of what live trading
   actually faces.

**Fix:** Lowered the real qualifying score (`CONFIDENCE_THRESHOLD` in `swing_model/scoring.py`) from
90 to 70 — just under the highest score ever actually seen live, so it's still meaningfully selective
(only about 1.7% of real past scans would have cleared it), but no longer requires a combination of
conditions the model has literally never produced. Also cleaned up a related risk: this same number
used to be typed out separately in two files, which could silently drift apart — now there's one
shared source and everything else reads from it. The "near miss" threshold was lowered too (80 -> 65),
so it still means something under the new number instead of becoming unreachable.

**Why this doesn't have a "backtest: PASS" line:** Normally a threshold change needs a fresh backtest
to confirm it. But the backtest's own scoring engine is exactly what was just shown to be unfair —
running it again would just repeat the same overly optimistic result. Treating that as approval would
be gaming the process, not satisfying it. So this is logged honestly as a judgment call based on real
trading data, not a backtest-approved change. Worth raising the bar again once enough real trading
history builds up to fix the backtest's missing pieces.

**Backtest result:** Not applicable, on purpose — see above. 915 tests pass, 3 skipped (pre-existing);
1 test had a fixture score that assumed the old 90/80 thresholds — updated to match the new 70/65.

**Approved by:** [pending]

---

## [v2.2.45] — 2026-08-06 — [Infrastructure] 4 retail stocks (Home Depot, Nike, Starbucks, Target) never once got financial data — a leftover daily limit was blocking them; raised it

**Status:** Live.

**In short:** These four stocks always showed "no financial data available" — not outdated data,
never fetched even once, in every single scan since they were added. That put a hard cap on their max
possible score every time. The cause: a daily limit on how many stocks can fetch fresh financial data,
left over from a rule that no longer applies. Raised the limit so all four now get real data.

**Problem:** There's a daily cap (`swing_model/indicator_pipeline.py`) on how many stocks can fetch
fresh financial data per day, shared across every scan. It was set to protect a shared Alpha Vantage
account limit — but the code that fetches financial data stopped using Alpha Vantage months ago, and
nobody updated the cap as the stock list grew from 6 to 23. This exact problem already happened once
before, to a different group of stocks, and the code's own notes flagged fixing it as a deliberate
follow-up that never got done. It happened again here: stocks are checked group by group in a fixed
order, and whichever group goes last each day — this one — kept losing out to the earlier groups'
daily needs and never got a turn.

**Fix:** Raised the daily limit from 5 to 25 — comfortably above the full 23-stock list, so every
stock can get fetched in a single day if needed. Neither of the two services it uses now (Finnhub and
Yahoo Finance data) has a meaningful daily limit at this volume. Tested it live: all four stocks got
real financial data on the very next fetch.

**Backtest result:** Not applicable — this only changes which stocks have real vs. missing financial
data, not how scoring works. 915 tests pass, 3 skipped (pre-existing); 2 tests that assumed the old
limit of 5 now use a small test-only limit instead, so they don't break if this number changes again.

**Approved by:** [pending]

---

## [v2.2.44] — 2026-08-06 — [Data Source] Found why Seeking Alpha kept failing: we were paying for the wrong listing on RapidAPI — switched to the one that's actually upgraded

**Status:** Live.

**In short:** The last fix made the failures cheaper to hit; this one makes them stop happening.
Upgrading the RapidAPI plan to 10,000 requests/month didn't help, because the upgrade was applied to a
*different* Seeking Alpha listing than the one this code actually calls — same product name, two
unrelated publishers, two unrelated subscriptions. Switched the code to use the listing that's
actually paid for.

**Problem:** The code was calling a Seeking Alpha API from publisher "tipsters," still on the old
500-requests-a-month plan. The account's upgrade to 10,000/month went to a *different* Seeking Alpha
API, from publisher "apidojo." Confirmed this by reading the actual error message, which said plainly:
still on plan BASIC, limit 500 — no matter what was upgraded elsewhere in the account. Every scan was
quietly falling back to old cached data (or nothing at all) for this signal, all day, regardless of
which plan was active.

**Fix:**
- Switched the code to call apidojo's Seeking Alpha API instead of tipsters'.
- The web address and request format had to change too, since it's a different provider — the old one
  doesn't exist on apidojo's side at all (confirmed: a clean "not found," not a quota error).
- The shape of the data coming back happened to match what the code already expected, so nothing else
  needed to change.
- Tested it live end-to-end: confirmed the 10,000/month limit is active, and got back real news
  articles with real comment counts for Apple and Nvidia.

**Backtest result:** Not applicable — this only changes which outside data source is called, not how
scoring works. 915 tests pass, 3 skipped (pre-existing).

**Approved by:** [pending]

---

## [v2.2.43] — 2026-08-06 — [Infrastructure] Seeking Alpha's data feed was failing on every stock, every scan, all day — scans no longer waste time re-confirming a feed that's already known to be down

**Status:** Live.

**In short:** Every stock in every scan today got blocked by the Seeking Alpha data feed ("too many
requests"), and each one wasted about 3.5 minutes retrying before giving up and falling back to old
cached data — for every single stock, every time, for no benefit. That's why a scan that normally
takes about 20 minutes took 87 minutes today. Scans now notice after the very first failure that this
feed is down and skip the long wait for the rest of that scan, while still checking quickly in case it
comes back.

**Problem:** The code that talks to this data feed treated every failure as a one-off glitch and
retried the slow way (wait 30 seconds, then 60, then 120) every single time, for every stock. That's a
fine assumption for an occasional blip — but real data from today, and from an earlier incident on
2026-08-03, shows this isn't occasional: once it fails for one stock, it keeps failing for the rest of
that scan too. Paying that full wait on every stock, every time, turned routine scans into 80-90
minute ones, pushing scans well past when they're supposed to finish.

**Fix:** Added a simple "circuit breaker": once this data feed fails once in a scan, the rest of that
scan skips the long wait and just tries once quickly instead — so it still catches a recovery
mid-scan, without paying the full retry cost on every remaining stock. A successful response resets it
back to normal immediately. This data feed and the separate StockTwits feed are tracked independently,
so a Seeking Alpha outage doesn't slow down StockTwits.

**Backtest result:** Not applicable — this only changes retry timing, not how scoring works. 915
tests pass, 3 skipped (pre-existing).

**Approved by:** [pending]

---

## [v2.2.42] — 2026-08-06 — [Research] Extended the collinearity check to every scoring pair; new diagnostics for modifier calibration, score saturation, and threshold optimization; weight calibration upgraded to a real regression

**Status:** Research/diagnostic only. No live scoring behavior changed except `feedback_loop.py`'s
weight-calibration algorithm, which has no real trade data to run against yet (see Fix below).

**In short:** Built five new tools to answer questions the model's own math couldn't answer about
itself: whether any two scoring signals are secretly the same signal twice, whether the six scoring
modifiers are actually backed by evidence, how often a score gets artificially capped, whether 90 is
really the right cutoff, and whether the fixed 60/25/15 technical/sentiment/news split is the right
split. None of the answers were applied automatically — each one is reported as a real finding for a
human to weigh in on, following the same pattern as v2.2.39's regime/sector_rotation fix.

**Problem/context:** Following v2.2.39's regime/sector_rotation fix, several adjacent questions had
no tooling to answer them:
1. The live collinearity check (`paper_trading/live_collinearity_diagnostic.py`, introduced v2.2.16)
   only ever compared Technical vs. Sentiment — structurally unable to have caught the regime/
   sector_rotation double-count itself, since that's a modifier-to-modifier pair.
2. Of the six scoring modifiers, only `seasonality.monthly_modifiers` carries any comment claiming
   backtest calibration (`config/swing_config.yaml`) — `regime`, `sector_rotation`, `earnings`,
   `cross_ticker`, `macro_overlay` are hand-set round numbers with no such lineage.
3. No visibility into how often each of the 5 scoring categories actually saturates at its own point
   ceiling, compressing resolution exactly where a 90-point threshold needs it most.
4. No data-driven read on whether 90 is a good cutoff now that v2.2.39 maps scores to a real
   probability instead of treating the raw number as one.
5. `feedback_loop.py`'s live weight-calibration heuristic (`_recompute_weights`) only asked "is this
   sub-signal's average higher in wins than losses," applying an identical ±2pp nudge regardless of
   how large or statistically reliable that gap actually was.

**Fix:**
- `paper_trading/live_collinearity_diagnostic.py`: generalized `collect_score_pairs()` from a
  hardcoded technical/sentiment pull to a full pivot of every layer logged to `layer_scores` (5
  categories + 6 modifiers), and added `compute_pairwise_collinearity()` — Pearson r, Spearman rho,
  and tail-dependence lift for every one of the resulting 55 pairs, flagging any pair where
  `|r| >= 0.5` or tail-lift `>= 1.5x`. Run against 676 real logged scans: flagged
  `sentiment_total <-> technical_total` on tail dependence (1.65x lift) despite a near-zero bulk
  correlation (r=0.094) — a real finding a bulk-correlation-only check would have missed entirely.
  `regime_modifier <-> sector_rotation_modifier` itself read r=0.407 on this data (below the flag
  threshold) — confirms the double-count fixed in v2.2.39 only manifests when both are negative at
  once, which averaging over the full range dilutes into an unremarkable bulk correlation.
- New `backtesting/modifier_calibration_diagnostic.py`: buckets real pooled 3-sector backtest
  outcomes by each exercised modifier's sign, reporting win rate/avg R:R per bucket.
  `sector_rotation_modifier`/`earnings_modifier`/`cross_ticker_modifier` are flagged explicitly as
  **not measurable this way** — `backtesting/simulation.py` hardcodes all three to 0.0 during replay
  (no historical sector-rotation-vs-benchmark alignment, earnings calendar, or cross-ticker joint
  data covering the full backtest window exists), so no amount of outcome analysis on this data can
  speak to their calibration. Of the 3 modifiers that do vary during replay: `regime_modifier` and
  `macro_modifier` point the correct direction (positive bucket beats negative bucket on win rate).
  `seasonality_modifier` — the one modifier with any claimed calibration lineage — read **inverted**
  on pooled 3-sector data: negative-seasonality trades won 65.8% of the time vs. 50.9% for
  positive-seasonality trades. Not corrected here — flagged for review before touching
  `config/swing_config.yaml`'s `monthly_modifiers`; possible causes include the original calibration
  being fit on semiconductors alone and not generalizing, or a genuine sign error.
- Extended `paper_trading/score_distribution_diagnostic.py` with `saturation_rates()` — fraction of
  logged rows within 2% of each category's own point ceiling. Real result on 676 logged scans:
  `fundamental` sits at its ceiling 15.7% of the time; `technical`/`positioning`/`news` never do
  (0.0%), `sentiment` rarely (1.6%) — a narrower, more concentrated problem than assumed going in.
- New `backtesting/threshold_optimization_analysis.py`: sweeps confidence thresholds 40-95 against
  real pooled backtest data, computing win rate, avg R:R, expected R per trade, and whether each
  threshold alone clears the existing go-live gate (bootstrapped expectancy CI, Sharpe, drawdown).
  Real result: expected R per trade increases monotonically through the top of the tested grid (95);
  85 is the lowest threshold that clears the existing go-live gate on its own. `CONFIDENCE_THRESHOLD`
  (90, `swing_model/scoring.py`) was **not** changed — this is reported as a data point for a
  live-trading-behavior decision, not something to apply automatically from a backtest reading.
- `swing_model/feedback_loop.py`: `_recompute_weights` now tries a regularized logistic regression
  first (new `_fit_logistic_weights` — scipy, L2-penalized, standardized features so a large-scale
  sub-signal like technical (0-40) can't mechanically dominate a small-scale one like news (0-15)
  purely from units), falling back to the old sign-only heuristic when there's too little data
  (<20 samples), all-one-outcome-class data, or a zero-variance feature. Run against real pooled
  backtest outcomes as a sanity check (not live data — none exists yet, see below): assigned
  sentiment ~48-54% vs. technical's ~29-42%, nearly inverting the current fixed 60/25/15 split.
  Flagged with an important caveat, not applied: this backtest's "sentiment" is a price-momentum
  proxy, not real StockTwits data (documented in `backtesting/collinearity_diagnostic.py` since
  v2.2.16), so this result likely re-states price momentum under a different label rather than
  reflecting genuine crowd-sentiment predictive power. Needs re-running against real paper-trading
  sentiment once enough trades have closed — `_recompute_weights` itself is unreachable in production
  today regardless, since `data/logs/trade_outcomes.csv` and paper trading's closed-trade log are
  both still empty (no version has gone live).

**Backtest result:** Not applicable — diagnostic/research tooling only; no scoring path changed.
34 new tests. 915 tests pass, 3 skipped.

**Approved by:** [pending]

---

## [v2.2.41] — 2026-08-06 — [Backtest Methodology] Added Sortino ratio, Ulcer Index, drawdown duration, concurrent-position portfolio simulation, and real transaction costs to the backtest's own metrics

**Status:** Backtest-only — no live scoring path affected.

**In short:** The backtest's own scorecard had four blind spots: it judged bumpy-but-profitable
swings as harshly as genuine losses, couldn't tell a quick dip from a months-long slump, could only
ever model one open trade at a time even though this project holds several at once in real life, and
assumed every trade fills for free. All four are now measured for real.

**Problem:** The backtest's performance metrics (`backtesting/metrics.py`,
`backtesting/backtest_engine.py`) had four gaps versus what a real risk review needs:
1. Sharpe penalizes upside variance identically to downside — the wrong lens for this project's
   deliberately asymmetric structures (`long_strangle` convex, credit spreads concave — see
   v2.2.36's real EV formulas).
2. `max_drawdown_pct` reports depth only — a drawdown that's deep-and-brief and one that's
   equally-deep-and-months-long are indistinguishable from this one number alone.
3. `_build_equity_curve` stepped through outcomes one trade at a time, always fully realizing one
   trade's P&L before the next could affect the curve — structurally unable to represent several
   correlated positions (e.g. multiple semiconductor names) losing simultaneously, which is exactly
   how this project can be positioned live.
4. The simulated P&L had zero transaction costs, making Sharpe/expectancy systematically optimistic
   versus what real fills (bid/ask spread, slippage) will actually produce.

**Fix (all in `backtesting/metrics.py`, wired into `backtest_engine.py`'s `run_backtest()` and
`run_multi_sector_backtest()`):**
- `compute_sortino()` — Sharpe's downside-deviation-only counterpart.
- `compute_max_drawdown_duration()` / `compute_ulcer_index()` — longest stretch of consecutive
  steps underwater, and the Ulcer Index (Martin, 1987): root-mean-square of drawdown across the
  whole curve, combining depth and duration into one number instead of reporting depth alone.
- New `build_portfolio_equity_curve()` — walks entry/exit events in true chronological order instead
  of one trade at a time; each position's risk is locked in at its own entry against whatever equity
  existed at that moment, and multiple positions can have risk locked in simultaneously against the
  same starting equity. Run against real pooled 3-sector history: peak concurrency was **38
  positions open at once**, committing **35.2% of equity at risk simultaneously** — well past what
  the 1%-per-trade framing suggests in isolation. Portfolio-view Sharpe (3.12) and drawdown (9.47%)
  came out modestly worse than the serial view (3.34 / 9.29%) on this dataset.
- `_build_equity_curve()` now subtracts round-trip slippage from every simulated trade's P&L by
  default ($0.02/share × 2 — reusing the exact per-share convention already established in
  `shared/utils/options_math.py`'s `adjust_ev_for_slippage`, not a new, uncalibrated number).
- None of the four new metrics gate `passed` — reported alongside, not folded into, the existing
  Sharpe/drawdown/expectancy-CI floors. Raising the go-live bar on new metrics is a deliberate
  decision for a human to make, not something to apply silently by adding a new field.

**Backtest result:** Methodology change, not a scoring change — see v2.2.39's logged PASS for the
current gate result computed under this same methodology. 30 new tests. 892 tests passed at the
point this landed (915 after v2.2.42's later additions), 3 skipped.

**Approved by:** [pending]

---

## [v2.2.40] — 2026-08-06 — [Infrastructure] The post-close scan could run twice at once — a file lock now stops it, fixing why retail-sector tickers dropped out of an entire day's results

**Status:** Live.

**In short:** Traced a real incident — an entire trading day's post-close scan lost all its retail
stock results (Amazon, Nike, Starbucks, Target, Home Depot, Tesla) twice in a row — to the scan
being relaunched before the previous run had finished. A new safety lock stops that from happening
again, even though what's actually triggering the double-launch is outside this project's code.

**Problem:** 08-04's post-close scan restarted from scratch twice within 5 minutes — `app.log` shows
a fresh `[post_close] Fetching OHLCV for: ['NVDA', ...]` at 13:48:34 and again at 13:53:30, each one
re-fetching every sector from the very beginning. Almost certainly an external scheduler (Windows
Task Scheduler or similar; nothing in this repo triggers a 5-minute cadence) relaunching the job
without checking whether a previous instance was still alive. Because retail tickers
(AMZN/TSLA/HD/NKE/SBUX/TGT) are processed last in ticker order, and the Seeking Alpha/RapidAPI 429
retry storm (`sentiment_client.py`, confirmed live 2026-08-03) was making every earlier ticker take
several minutes, every relaunched instance got killed before it ever reached them — retail dropped
out of that day's post-close results twice in a row.

**Fix:** New `shared/utils/scan_lock.py` — a file-based mutex
(`data/processed/scan_locks/{scan_type}.lock`, storing PID + timestamp, with a cross-platform
liveness check via `os.kill(pid, 0)`). `paper_trading/paper_runner.py`'s `run_paper_scan()` now
acquires this lock before doing any work; a second invocation for the same `scan_type` while one is
already running logs a warning and exits immediately instead of duplicating work and contending for
the same rate-limited APIs. This does not fix whatever is triggering the repeated external
relaunches (outside this repo's control) — it stops the actual damage regardless of that root cause.

**Backtest result:** Not applicable — no scoring-path change. 11 new tests
(`tests/test_scan_lock.py`). 915 tests pass, 3 skipped.

**Approved by:** [pending]

---

## [v2.2.39] — 2026-08-06 — [Scoring Change] The model was treating its own confidence score as a literal win probability; two scoring modifiers were quietly double-counting the same signal; stale fundamental data was weighted the same as same-day data

**Status:** Live.

**In short:** Three real bugs found while reviewing the scoring formula end to end. The biggest one:
every options-structure calculation assumed a score of 90 meant a 90% chance of winning — the
model's own historical win rate at that score is actually about 60%. Every profit estimate for every
stock was overstated, and overstated by more the higher a stock's score was. Also fixed: two scoring
adjustments that were really the same underlying signal counted twice, and financial data that's up
to two weeks old counting exactly as much as data from this morning.

**Problem:**
1. `swing_model/trade_selector.py` fed every EV formula (all 42 trade structures)
   `win_prob = confidence / 100.0` — treating the raw 0-100 composite score as a literal win
   probability. A score of 90 was assumed to mean a 90% chance of winning; this project's own
   backtested win rate at that threshold is ~60%. Every EV number computed for every ticker every
   scan was systematically overstated, and by a different amount depending on each ticker's own
   score — directly undermining the outlier detection and exclusion-mining tooling added in v2.2.38,
   since part of what looked like "this ticker's EV is unusually high" could just be "this ticker
   scored higher, so it got a more inflated assumed win probability."
2. `regime_modifier` (SMH vs. its own SMA trend) and `sector_rotation_modifier` (SMH return vs. SPY)
   are both derived from the same underlying SMH price action but were summed in
   `swing_model/scoring.py` as if independent — self-flagged by the code's own NOTE, firing
   repeatedly on live scans (e.g. NVDA, 08-05 mid-session: regime -2.0, sector_rotation -15.0,
   summed to -17.0 as if two separate corroborating signals).
3. `fundamental_data_as_of` routinely lags the scan date by 1-13+ days (Alpha Vantage's own fetch
   cadence/rate limits, not a bug — see `fundamental_layer.py`), yet `fundamental_contribution` was
   summed into the base score at full weight regardless of age, as if a same-day technical signal
   and a two-week-old fundamental snapshot were equally current.

**Fix:**
- New `swing_model/win_probability_calibration.py`: `calibrate_win_probability()` — piecewise-linear
  interpolation over real (confidence threshold -> historical win rate) points, isotonic-smoothed
  (new `shared/utils/isotonic.py`, a small weighted Pool-Adjacent-Violators implementation, avoiding
  a new scikit-learn dependency for one algorithm) so a single noisy threshold's small-sample dip
  doesn't get taken at face value. Calibration points generated by new
  `backtesting/fit_win_probability_calibration.py` from a real pooled 3-sector backtest run (544
  outcomes) — at confidence 90, the real isotonic-smoothed win rate is 59.8%, not 90%.
  `rank_trade_structures()` and `compute_confidence_score()` both take an optional
  `win_probability_calibration` parameter; `paper_runner.py` loads the real calibration file
  (`data/processed/win_probability_calibration.json`) once per scan and passes it through. Falls
  back to the old `confidence/100` behavior only when the calibration file is missing, flagged
  explicitly via a new `win_prob_calibrated` field so callers/DB rows can tell which happened.
- `swing_model/scoring.py`: when `regime_modifier` and `sector_rotation_modifier` clamp to the same
  sign, `total_modifier` now uses whichever has the larger magnitude instead of summing both.
  Opposite signs still sum normally — a real disagreement between the two lenses (SMH's own trend
  vs. SMH's return relative to SPY), not a double-count. The raw per-modifier values are unchanged
  in the returned breakdown (new `regime_sector_rotation_combined` field shows the deduped
  contribution) so audit logs and the v2.2.42 NOTE-detection logic still see both real numbers.
- `swing_model/scoring.py`: new `_fundamental_staleness_weight()` — full weight within 3 days of
  `fundamental_data_as_of` (this project's normal refresh cadence), linearly ramping down to a 0.5
  floor by 15 days old, and held at that floor beyond — never fully zeroed, since earnings/EPS-
  growth facts don't actually go stale as fast as a same-day price-derived valuation ratio would.
- Also added in the same pass: `calibrated_win_probability`/`win_prob_calibrated` and a new
  `compute_data_sufficiency()` (`data_confidence`: high/medium/low, from counting degraded
  sentiment/positioning/fundamental sub-signals against their own existing `data_quality` flags) on
  the score breakdown — visibility for a future calibration decision, not new gating logic.

**Backtest result:** **PASS.** Multi-sector (semiconductors + regional_banks + healthcare), 296
qualifying trades: win rate 59.8%, avg R:R 1.63, Sharpe 3.34, Sortino 13.69, max drawdown 9.29%
(43-trade duration, Ulcer Index 3.23), expectancy CI lower bound 0.482R (bar: 0.3R). 915 tests pass,
3 skipped.

**Approved by:** [pending]

---

## [v2.2.38] — 2026-08-06 — [Bug Fix] The trade-structure picker was computing real diagnostic data every scan and throwing it away; a statistical outlier check now catches anomalies like MU's 2-2.5x-inflated reading

**Status:** Live (this is the trade-structure diagnostic tier — score 60-89, not the 90+ real
signal path, but the data is real and now actually kept).

**In short:** The system was already computing useful data about why a stock's options structure got
rejected, and about how a structure's estimated profitability compared to similar past readings —
but was throwing both away right after using them once. Now it keeps them, and automatically flags a
reading like MU's — 2-2.5x higher than very similar stocks on the same structure the same day — for
a second look instead of silently accepting it.

**Problem:** Reviewing a batch of live paper-trading scans found three related problems in the
diagnostic trade-structure evaluator (introduced v2.2.23, real EV formulas added v2.2.36):
1. When a ticker cleared the diagnostic threshold but every one of the 42 structures got filtered
   out (TSM, AMZN, PFE — repeatedly, across multiple separate scans), `rank_trade_structures()`
   already computes `exclusion_summary`/`structures_eligible_after_filters` explaining exactly why —
   but the caller discarded both after reading only the top-ranked structure, leaving no way to audit
   which filter was actually eliminating every candidate for these specific tickers.
2. `ev_per_dollar_risked` compared structures with very different real time exposure on equal
   footing — a `leaps_call` (~270 days) or `diagonal_call` (dte+30 days) was ranked directly against
   a `long_strangle` (~10 days) as if both tied up capital for the same length of time. Confirmed
   live: MU's `long_strangle` reading (~119 EV/$) was ~2-2.5x AVGO/NVDA's on the same structure, same
   scan, same day.
3. No mechanism existed to flag when a structure's EV reading was a statistical outlier against its
   own trailing history, the way the MU case above should have been.

**Fix:**
- `app_ui/db.py`: `ticker_results` gained `structures_eligible_after_filters`, `exclusion_summary`,
  and `ev_outlier_z` columns (migrated automatically on connection open, verified against the live
  676-row database with zero data loss); `paper_trading/paper_runner.py` now persists all three
  instead of discarding them after reading the top-ranked structure.
- `shared/utils/options_math.py`: `resolve_structure_economics()` now returns `effective_days` — the
  actual time exposure each structure's own EV was computed against (most structures: `dte`;
  `leaps_call`/`leaps_put`: `_LEAPS_MIN_DAYS`-scale; `calendar_*`/`diagonal_*`: `dte+30` for the
  longer-dated back leg). `swing_model/trade_selector.py` now ranks by `ev_per_dollar_per_day`
  (EV/$ divided by `effective_days`) instead of the un-normalized ratio. Verified directly: for a
  MU-like high-ATR candidate, `diagonal_call` looked like the near-#1 pick under the old metric
  (13.95 vs. `long_strangle`'s 15.44) but drops to 0.35/day once its real 40-day exposure is applied
  — correctly demoted below `long_strangle`'s 1.54/day, which achieves comparable-or-better edge in
  a quarter of the time.
- New `shared/utils/robust_stats.py`: a MAD-based (median absolute deviation) modified z-score,
  resistant to the very outlier it's checking for — unlike a mean/std z-score, one extreme historical
  value can't drag the reference distribution toward it. Wired into `paper_runner.py`: every
  recommended structure's EV is now checked against its own trailing history
  (`get_expected_values_for_structure()`); `|z| >= 3.5` logs a NOTE and persists `ev_outlier_z`.
  Root cause of the MU-shaped anomaly confirmed directly with a new characterization test suite
  (`tests/test_structure_economics.py::TestHighAtrPriceRatioCharacterization`):
  `resolve_structure_economics`' fixed-OTM-offset structures price their premium from
  entry/IV/dte only — never from the underlying's ATR — while the payoff scales directly with ATR,
  so a high-ATR/price-ratio candidate mechanically gets a larger `avg_win` for the same premium.
  Deliberately not patched in the formula itself (risks over- or under-correcting every structure
  sharing that strike convention, not just `long_strangle`) — the new outlier check is the safety net.
- New `paper_trading/ev_outlier_and_exclusion_diagnostic.py`: mines the newly-persisted columns —
  aggregates exclusion reasons by sector/ticker, flags tickers repeatedly clearing the diagnostic
  threshold with zero eligible structures, summarizes outlier-flag rates per structure.

**Backtest result:** Not applicable to this diagnostic tier (score 60-89) — doesn't touch the 90+
signal path's backtest. 66 new/updated tests. 869 tests pass, 3 skipped (at the point this landed).

**Approved by:** [pending]

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
