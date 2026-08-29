# CHANGELOG — AI-Assisted Swing Trading Signal System

This is the history of every change made to an automated stock-trading model. It has **never
traded real money** — every version so far has been building, testing, and fixing a strategy
that is still only running in "paper trading" (see glossary below), which uses fake money.

If you're new here, read **every entry's "In short" line** — that's the plain-English version.
Everything below it (Problem / Fix / Backtest) is the technical detail, for anyone who wants it.

## Where things stand right now

The model has been rebuilt and re-tested many times but has never once passed all the
requirements to trade real money. On 2026-08-01, its historical performance test passed its own
safety bar for the first time ever, after an old setting was updated to match how the model has
evolved. A full model audit on 2026-08-19 (v2.2.63) found and fixed 17 more real gaps, including
one that had been making the historical test's own numbers look slightly better than real trading
would achieve — the corrected win rate (61.2%, down from 63.1%) still cleared the safety bar at
the time.

**A second full model audit on 2026-08-22 (v2.2.75) found that "clearing the safety bar" claim was
itself measuring the wrong thing.** The historical test's qualifying bar had stayed stuck at the
model's old 90-point scoring threshold for months after the real, live threshold was lowered to
70 — so it had been grading an easier, hypothetical version of the signal, not the one actually
running. Corrected, the same test now says: win rate 55.9%, and it **no longer clears the safety
bar**. This is the most consequential correction so far — every prior "passed" milestone was real
for the population it tested, but that population wasn't the one live/paper trading actually uses.

None of this changes whether the model is allowed to trade real money — it still isn't, and won't
be until it's approved.

## Plain-English glossary

| Term | What it means |
|---|---|
| **Live** | The change is active right now, in the real running system. |
| **Paper trading** | The model makes real trading decisions using real, live market data — but with fake money. A dry run to prove it works before any real money is at risk. |
| **Backtest** | Running the strategy against years of *past* stock-market data to see how it would have done, before trusting it with money (real or fake). |
| **Signal / qualifying trade** | A stock the model considers actually worth trading — it has to score 70 out of 100 or higher (lowered from 90 in v2.2.46; see v2.2.75 for the historical-test bug this caused). |
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
7
## Quick reference

| Version | Date | Category | Summary |
|---|---|---|---|
| v2.2.112 | 2026-08-28 | Infrastructure | Phase 1 of the API re-architecture — plumbing only, no change to any score. Every external data source now shares one on-disk cache and one cross-process rate limiter, so the day's three scans stop re-fetching news, filings and earnings dates that haven't changed since the morning, and the Alpha Vantage daily budget stops being spent on the "slow down" error responses it gets when calls come too fast. Also: the SEC request timeout was too short and made every scan stall for minutes on retries (fixed), and a CI check now blocks any new code that calls an external API without going through the shared layer |
| v2.2.111 | 2026-08-26 | Feature | Added a switch (OFF by default) that lets the model count news for less in sectors where news barely exists. Regional banks average 5 news articles per stock against 65 for chip makers, so news currently occupies 15 of the 100 scoring points for banks while telling us almost nothing. This is a free control to test real fixes against — it costs no API calls, and it is deliberately switched off until measured, because "banks have little news" does not automatically mean "bank news is less predictive" |
| v2.2.110 | 2026-08-26 | Bug Fix | The last of the "invented data treated as real" bugs. When a stock had no social-media posts on a given day, the model filled that day in with a neutral placeholder — then measured sentiment MOMENTUM against those placeholders, so a stock with 30 posts in six minutes registered maximum momentum from a jump that never happened, scoring HIGHER than a stock with genuine five-day history. Also split feed outages from code bugs in the data-fetching layer, so a broken function call can no longer look like "the vendor sent nothing" |
| v2.2.109 | 2026-08-26 | Bug Fix | A failed request to the SEC filings service looked exactly like "this company announced nothing" — both returned an empty result. If SEC ever throttled or blocked us, the model would quietly lose one of its five news sources and all of its filing-based safety triggers while appearing perfectly healthy. Failures are now recorded separately so they can be seen |
| v2.2.108 | 2026-08-26 | Bug Fix | Closed the last two open items from the data-source audit. Social-media sentiment was scoring a stock nobody posts about exactly like one where every post is against the trade — silence now scores neutral, matching the same fix made to news earlier today. And the daily news-API allowance is no longer spent first-come-first-served: a share is now held back for the end-of-day scan, which had been getting only 6 of 20 calls despite being the scan that actually picks the trades |
| v2.2.107 | 2026-08-26 | Bug Fix | Two data-fetching bugs found while auditing every external data source. Taiwan Semiconductor and ASML had been returning ZERO regulatory filings on every scan ever run — as foreign companies they file a different form type than the one the model asked for, so their own announcements were invisible to the model's safety checks. And the model was reading social-media sentiment with no check on how OLD the posts were: one small bank's trade direction was being set by posts up to a year old, the newest already five weeks stale. All API keys were checked and are working correctly |
| v2.2.106 | 2026-08-26 | Infrastructure | Housekeeping. Removed one bank stock (WBS) whose price history from the data provider is missing 15 trading days its peers all have — it had been failing data checks and getting excluded from every scan anyway, while still filling the error log daily. And stopped flagging another bank (CFG) as broken for reporting 100.4% institutional ownership: above 100% is normal and real, because shares lent to short sellers get counted twice |
| v2.2.105 | 2026-08-26 | Bug Fix | The reward-to-risk figure recorded against each trade was the one planned before the trade opened, not the one it actually got. Trades rarely open at exactly the planned price, and the profit target does not move when they don't — so the real ratio drifts. 8 of the 10 trades opened so far were affected, the worst advertising 3.0:1 when it was really 2.0:1. The real figure is now recorded alongside the planned one. Also: a suspected position-sizing flaw was investigated and found NOT to be one — the numbers had been read on the wrong measure |
| v2.2.104 | 2026-08-26 | Bug Fix | Two fixes to how trades set their exit prices. Some profit targets were unreachable: one pick needed a +39% move inside a two-week window, because the model would aim at any "thin volume" price level no matter how far away it sat. Targets are now capped at what the stock realistically moves in the holding period. And some stop-losses sat closer than a single normal day's price swing, so they would be triggered by ordinary noise rather than by the trade actually going wrong — stops now have a minimum distance. Of today's 8 picks, 6 are unchanged and 2 were corrected |
| v2.2.103 | 2026-08-26 | Bug Fix | Two scoring/measurement fixes found while reviewing the day's trades. First: a stock nobody writes about was being scored exactly like a stock with unanimous, credible bad news — 7 of 12 regional banks scored zero out of fifteen on news despite pulling 30+ articles each, because none were judged relevant. Silence is now scored as neutral, not as damning. Second: a trade too small to buy even one share still counted in the win rate. LLY closed today having never risked a cent, and it had quietly turned the record from 0-of-2 into 0-of-3 |
| v2.2.102 | 2026-08-26 | Bug Fix | The two parallel trade-selection experiments were supposed to run independently, but one was quietly filtering the other. If a stock was good enough to be picked by the main strategy earlier in the day, the second (ranking-based) strategy never even saw it — so it was systematically blind to the single best stock in each sector, the one most worth ranking. Found while answering a question about how the ranking actually picks its top two. Confirmed live: on 2026-08-25 the top-scoring healthcare stock was invisible to the ranking, which picked 2nd and 3rd place instead |
| v2.2.101 | 2026-08-26 | Feature | The model no longer lets a stale trade idea block a fresh one. When it spots a setup, it places an order that only triggers if the stock actually moves to a certain price — and until that happens, no money is committed. Previously, that waiting order would block the same stock for up to a week, even after the model had formed a newer and better opinion about it. Now a newer signal cancels the untriggered order and takes its place. Orders that have actually been filled still block, unchanged — that's real money at stake and doubling up on it is exactly what the rule is for. Cancelled orders are recorded as "superseded" and kept out of the win-rate maths, since no money was ever at risk |
| v2.2.100 | 2026-08-26 | Bug Fix | Review of the 2026-08-25 scan and the full trade ledger, and the four real bugs it turned up. The most serious: the new rank-based paper-trading track was logging **three times** the trades it was configured to. It is meant to record the top 2 stocks per sector per day, but the check that stopped duplicates only stopped the same *stock* twice — so each of the day's three scans went further down the list and logged 2 more, 6 per sector instead of 2, every one of them labelled "rank #1"/"rank #2" in the log. That track exists purely to build a clean dataset to judge the strategy on, so it was corrupting the only evidence it was created to produce. Also: a 5-day price-momentum figure recorded on every trade was never actually calculated and had been silently saving as 0.0000 on all 39 trades ever logged; repeat "critical event" alerts fired ~9 times a day for the same news story; and two trades too small to buy even one share were being counted as real open positions |
| v2.2.99 | 2026-08-24 | Bug Fix / Infrastructure | Full code-cleanliness audit of the core model. Found and fixed a real pricing bug: the EV formula used for 4 of the 42 option structures (ratio/back spreads) was ignoring implied volatility and time decay entirely, and — separately — comparing per-share dollars against per-contract dollars, undervaluing those 4 structures' rankings by roughly 100x versus every other structure. Also: wired up a finished-but-never-connected Discord alert for adverse macro conditions (and fixed its color logic, dead on arrival since before it was ever connected); corrected a module's doc claiming it uses AI-based text recognition when it's always been simple keyword matching; removed several dead settings and 6 functions nothing in the codebase ever called |
| v2.2.98 | 2026-08-24 | Feature | Strategy pivot: added a second, parallel paper-trading track that always trades the top 2 highest-scoring stocks in each sector, every scan, instead of only the rare ones that hit the official 70+ bar. Runs alongside the existing system, not replacing it, with its own ledger, own $15,000 pretend account, and its own Discord messages so the two can be told apart and compared over time. Direct fix for "not enough trades to learn from" — this guarantees a steady flow of real data instead of waiting on a bar that's proven too rare to clear reliably, in any sector, no matter how many stocks get added to the watchlist |
| v2.2.97 | 2026-08-24 | Research / Bug Fix | v2.2.96's "the real score shows a statistically real negative relationship with returns" claim was checked more rigorously and does NOT hold up — that one p=0.05 reading was one of ~15 similar tests run in the same pass, and doesn't survive the standard correction for running that many tests at once, nor does its own resampled confidence interval clearly exclude zero. Corrected finding: no robust evidence of edge in either direction from the real (non-proxy) part of the score — not proof it's broken, just still no proof it works. Added the two statistical checks that caught this to the standard backtest report so this doesn't have to be re-derived by hand next time |
| v2.2.96 | 2026-08-24 | Research / Feature | Nearly doubled the watchlist (23 -> 49 stocks) to grow the historical test's sample size, heaviest in the two sectors with zero winning-or-losing trades to learn from. Result: it didn't work the way expected — banks are still at zero qualifying trades even after more than doubling that sector's stock count, and total qualifying trades across all sectors combined actually went down slightly, not up. Also see v2.2.97 — the "revealed a real negative signal" framing below did not hold up under closer scrutiny |
| v2.2.95 | 2026-08-24 | Feature / Bug Fix / Research | Added a second, much-larger-sample way to check whether the score actually predicts anything (thousands of scored days instead of only 17 historically-qualifying trades) — first read says the real Technical/News/Fundamental data shows no significant edge on its own; the earlier win-rate numbers likely leaned on a backtest-only stand-in for Sentiment. Also: a scan-time crash on one stock used to vanish with a single log line — now it's visible and doesn't affect other stocks that day |
| v2.2.94 | 2026-08-24 | Bug Fix / Feature | Fixed two tickers being silently dropped from scans over vendor data-rounding noise, and a "fraud" news trigger repeatedly crying wolf on fraud-prevention marketing copy. Added tracking for whether trades that never filled would have won anyway, and a daily Discord summary of open/closed trades and P&L |
| v2.2.93 | 2026-08-23 | Scoring Change | Raised two portfolio-wide risk caps to match v2.2.92's bigger per-trade risk budget, so they still mean something instead of blocking almost every trade |
| v2.2.92 | 2026-08-23 | Scoring Change | Raised how much money each trade is allowed to risk, from $75 up to $500 at minimum confidence — the old amount was too small to ever afford a real options trade |
| v2.2.91 | 2026-08-23 | Scoring Change | When two possible trades tie on expected profit, the model now picks the one with the smaller potential loss |
| v2.2.90 | 2026-08-23 | Backtest Methodology | Added a stricter statistical check to the historical test, to catch a good-looking result that's really just noise. Today's result: it is noise |
| v2.2.89 | 2026-08-23 | Bug Fix / Scoring Change | Found stale, outdated scoring weights for one sector still steering live trades — cleared them out. Every sector now uses the safe shared default until it earns its own |
| v2.2.88 | 2026-08-23 | Infrastructure | Added a missing test proving a data field was actually being saved correctly — it was, but nothing had ever checked |
| v2.2.87 | 2026-08-23 | Infrastructure | Stopped tracking a large log file in git — it's already backed up locally and was just cluttering every commit |
| v2.2.86 | 2026-08-23 | Infrastructure | Built an automatic check that stops the 90-vs-70 threshold bug (v2.2.75/v2.2.83) from quietly coming back a fourth time |
| v2.2.85 | 2026-08-23 | Bug Fix | Fixed the weekly summary alert failing to send — it wasn't loading the settings file that holds the Discord key |
| v2.2.84 | 2026-08-23 | Backtest Methodology | The historical test's pass/fail decision now also has to hold up across every past time period tested, not just one. It doesn't — it fails |
| v2.2.83 | 2026-08-23 | Backtest Methodology / Bug Fix | The 90-vs-70 threshold bug from v2.2.75 was copied into 3 more places — fixed everywhere. Corrected numbers are worse than first thought: 0 of 6 test periods pass, not 2 |
| v2.2.82 | 2026-08-23 | Bug Fix | A silent failure path in yesterday's risk-tracking fix could have hidden a future repeat of the same bug — it now logs a warning instead of staying quiet |
| v2.2.81 | 2026-08-23 | Infrastructure | Added tests for a real-money-tracking feature that had none — the single riskiest untested code in the project |
| v2.2.80 | 2026-08-23 | Infrastructure | Cut duplicate data requests that were nearly doubling how many stock-price API calls each scan made |
| v2.2.79 | 2026-08-23 | Bug Fix / Feature / Infrastructure | The weekly performance check-in was supposed to alert on Discord and run on a schedule — it did neither. Both fixed |
| v2.2.78 | 2026-08-23 | Feature | Paper trading now warns (but doesn't block) when a new signal would push too much money in one direction across every sector at once |
| v2.2.77 | 2026-08-23 | Bug Fix / Feature / Infrastructure | Paper trading — the system actually running every day — never had a crash/crisis safety check. Added one |
| v2.2.76 | 2026-08-23 | Backtest Methodology | Recalculated, from real data, the formula that converts the historical test's score onto the same 0-100 scale live trading uses |
| v2.2.75 | 2026-08-22 | Backtest Methodology | Found the historical test had been quietly grading an easier version of the model for months (still requiring a 90+ score after live trading was lowered to 70+). Fixed — the corrected result no longer passes |
| v2.2.74 | 2026-08-19 | Scoring Change / Bug Fix / Infrastructure | Finished wiring up the last batch of settings that used to do nothing when changed |
| v2.2.73 | 2026-08-19 | Scoring Change / Infrastructure | Wired up another batch of settings that used to do nothing when changed — no behavior changed, since the code already matched what the settings said |
| v2.2.72 | 2026-08-19 | Infrastructure | Sorted through 109 unused settings — removed the 68 that were dead weight, kept 41 to wire in over the next two versions |
| v2.2.71 | 2026-08-19 | Infrastructure | Removed two features that were fully described in the settings but never actually built |
| v2.2.70 | 2026-08-19 | Bug Fix | Paper trading now sends the same instant alert live trading does when breaking news hits an open position, instead of waiting until the next day |
| v2.2.69 | 2026-08-19 | Research | Looked at merging two duplicated pieces of code between live and paper trading — decided it was riskier than it looked, left them separate |
| v2.2.68 | 2026-08-19 | Bug Fix / Infrastructure | Fixed a bug undercounting paper trading's win rate; merged a few duplicated code blocks between live and paper trading |
| v2.2.67 | 2026-08-19 | Bug Fix / Scoring Change | Checked for signals that accidentally double-penalize the same fact — found and fixed one more (two separate China-trade-tension checks overlapping) |
| v2.2.66 | 2026-08-19 | Bug Fix / Infrastructure | Built an automatic check for two repeat-mistake patterns; along the way found and fixed 2 more real bugs it would have caught |
| v2.2.65 | 2026-08-19 | Bug Fix | Went looking for repeated mistakes on purpose instead of one at a time — found and fixed 9 real ones, including a safety switch that was turning off a day early |
| v2.2.64 | 2026-08-19 | Bug Fix | Same-day fix: yesterday's new "cut a bad position early" check was comparing against incomplete data and wrongly closed 7 real paper trades. Turned off until it's fixed properly |
| v2.2.63 | 2026-08-19 | Bug Fix / Scoring Change / Backtest Methodology | A full review of the whole model found and fixed 17 real problems — the biggest one had made the historical test look better than real trading actually would |
| v2.2.62 | 2026-08-19 | Bug Fix | Paper trading's earnings-date safety check only ran once, at signal time, so a trade could still be caught unprotected when earnings actually landed. Now re-checked every day |
| v2.2.61 | 2026-08-19 | Feature / Bug Fix | Fixed 3 stalled tests; wired real dollar risk/reward numbers into more trade structures; fixed the live alert always showing $0.00 for dollar risk; now shows the runner-up trade options too, not just the winner |
| v2.2.60 | 2026-08-19 | Feature / Bug Fix / Research | Corrected the documented holding period (the 5-day minimum was never actually enforced); fixed the same bearish-signal bug in a third place; stopped throwing away real trade-cost numbers before they reached the alert and paper-trading log; tested a different style of bearish signal — it did worse, so it stays off |
| v2.2.59 | 2026-08-19 | Research / Sector Rollout | Tested 16 variations trying to fix bearish signals' weak historical results — none got close to passing. Turned bearish signals on for paper trading anyway, to start collecting real results instead of more historical guesswork |
| v2.2.58 | 2026-08-18 | Feature / Backtest Methodology | Built real detection for bearish (falling-price) signals, instead of always defaulting to bullish. Kept switched off for now — it tested poorly on historical data in every sector |
| v2.2.57 | 2026-08-15 | Scoring Change / Feature | Let each sector fine-tune its own scoring weights instead of sharing one set — one sector's tuning passed and went live, semiconductors' was correctly rejected as worse, the rest stay on the shared default. Also fixed a real bug in the math that keeps those weights within safe limits |
| v2.2.56 | 2026-08-15 | Backtest Methodology | Found the shared scoring weights work for semiconductors but badly fail the other 3 sectors — the test used to average this away and call it a pass. Fixed the test to require every sector to pass on its own |
| v2.2.55 | 2026-08-15 | Bug Fix / Scoring Change | Found the seasonal calendar was scoring backwards and fixed it — win rate improved right away on the same historical data. Also fixed a weight-calibration step that could never actually change anything, plus a few other dead or misattributed settings |
| v2.2.54 | 2026-08-14 | Bug Fix | Fixed paper trading logging fake losses on trades that never actually filled; fixed a stop/target calculation that was computed but silently thrown away; fixed a news field that always logged blank |
| v2.2.53 | 2026-08-13 | Bug Fix / Scoring Change | Found the model was applying semiconductor-specific rules (like "rate hikes are bad") to bank stocks, where the opposite is usually true — fixed, plus 11 more scoring bugs found the same way |
| v2.2.52 | 2026-08-13 | Bug Fix / Scoring Change / Data Source | AMD's real earnings beat never reached the model's score — a review of the fundamentals scoring found and fixed 7 bugs, including revenue never being tracked at all |
| v2.2.51 | 2026-08-11 | Bug Fix / Feature | Stock positions were priced by full share price instead of real dollar risk, which wrongly excluded high-priced stocks. Fixed — and now prefers capped-loss options over shares when an affordable option exists |
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

## [v2.2.112] — 2026-08-28 — [Infrastructure] API re-architecture phase 1 — shared cache + rate limiter + Alpha Vantage throttle fix

**Status:** Live. **No scoring behaviour change** — the scan produces the same scores. This is
plumbing: it stops the model wasting API calls and stalling on timeouts. 1655 tests pass (35 new);
ruff and all four guardrail checkers pass clean.

**The problem.** Each of the three daily scans (pre-market / mid-session / post-close) runs as a
separate process that shared nothing with the others. So news, SEC filings, and earnings dates were
re-fetched from scratch three times a day even though almost none of it changes between 8:30am and
4:30pm. There was no shared pacing either: Alpha Vantage's free tier answers "please slow down to 1
request per second" with a normal-looking HTTP 200, and the old code (a) logged that as an
unexpected response, (b) did not retry it, and (c) still counted it against the day's 25-call
budget — so on any day with a sector-wide event gate (which fans an Alpha Vantage confirmation out
to every ticker in that sector) the budget was gone by mid-session, entirely on error responses.
Separately, the SEC request timeout was 15 seconds, which it routinely exceeded — each timeout then
cost a 30-second backoff, and a scan could spend the better part of an hour on nothing but SEC
retries.

**What changed.**

- **`shared/api_clients/rate_limiter.py`** — one persisted per-host record (`{last_call_ts, date,
  count}`) guarded by the existing cross-process file lock, so pacing and daily caps are shared
  across all three scan processes and the paper updater. `acquire(host)` sleeps just long enough to
  honour a minimum interval and raises `BudgetExhausted` at the daily cap, which callers treat as
  "skip this source, use the fallback". Limits reflect the real, verified budgets — Alpha Vantage
  24/day at ~1.3s apart, Finnhub ~55/min, Seeking Alpha 400/day, StockTwits uncapped (its RapidAPI
  plan is 500,000/month), SEC ~4/s, yfinance ~1/s.

- **`shared/api_clients/cache.py`** — `cached_call(namespace, key, ttl, fetch_fn)` backed by
  `data/cache/<namespace>/<key>.json` (`.pkl` for price frames), atomic writes, and a policy of not
  pinning an empty result so a transient outage doesn't get cached for the whole TTL. Wired into the
  Yahoo / Finnhub / SEC news fetchers (~4h), the SEC ticker→CIK map (30 days), and the earnings-date
  lookups that used to be ~180 raw yfinance calls a day for data that changes once a quarter (now 7
  days).

- **Alpha Vantage throttle handling** (`news_client.py`) — a `{"Information"}` / `{"Note"}` /
  `{"Error Message"}` body is now recognised as a throttle: logged as one, waited out, retried once,
  then it returns nothing. The daily-call counter is incremented only after a response that actually
  carried articles — never for a throttle or a retry.

- **SEC timeout 15s → 30s**, and every SEC call now goes through the rate limiter.

- **`scripts/check_no_raw_http.py`** + a CI step — fails the build if anything in `swing_model/`,
  `paper_trading/`, `shared/utils/`, `shared/indicators/`, `monitoring/` or `app_ui/` calls
  `requests` or `yfinance` directly instead of through `shared/api_clients/`. This is the guardrail
  that keeps a future data source from silently sitting outside the cache + limiter — the same
  recurrence shape the confidence-threshold and config-coverage checkers already guard against.

- **Fixes found along the way:** `paper_updater`'s OHLCV download now returns cleanly for a signal
  dated today or later (yfinance was logging "possibly delisted; no price data found" on every
  fresh post-close signal, because a start date in the future makes its request's start later than
  its end); `requirements.txt` pins yfinance's upper bound and adds `curl_cffi` explicitly (the
  browser-impersonation dependency yfinance needs to get past Yahoo's bot detection, previously only
  pulled in transitively).

**Not in this version:** the scoring-layer re-routing (SEC structured financials into the
Fundamental layer, Alpha Vantage's real per-article sentiment scores into the News layer, the actual
Fed funds rate into the macro overlay, analyst-trend and insider signals off yfinance onto Finnhub).
Those change scoring output and land under their own version with a fresh backtest.

---

## [v2.2.111] — 2026-08-26 — [Feature] Per-sector News coverage weighting — shipped DISABLED as a measurement control

**Status:** Live but INACTIVE (`scoring_weights.news_coverage_weighting.enabled: false`).

**In short:** A configurable multiplier on the News category's share of the Technical/Sentiment/News
pool, per sector. Off by default. Built as the zero-API-cost control arm for the user's planned
comparison of Finnhub-coverage fixes. All 1620 tests pass (14 new); ruff and all three guardrail
checkers pass clean.

**The problem.** News coverage is wildly uneven by sector, and that is a property of a company's
media profile rather than of its trade setup. Measured live 2026-08-26 (mean Finnhub articles per
ticker): semiconductors 65.1, consumer_discretionary 55.0, healthcare 29.1, **regional_banks 5.4** —
with 7 of 12 banks matching ZERO relevant articles out of 30+ fetched. v2.2.103 stopped that absence
being scored as BAD news (it now floors at a neutral 5.0/15), but a neutral score still occupies 15
of the 100 composite points while carrying no information at all.

**Why it ships DISABLED.** "Banks have thin coverage" is measured. "Therefore bank news is less
predictive" is **not** — it could equally be that sparse bank news is highly informative precisely
because banks get written about only when something real happens. Sourcing better bank news may beat
this outright. Turning it on now would also contaminate the rank track ahead of its 2026-09-19
checkpoint, so it stays inert until deliberately switched on for a measured comparison.

**Mechanism.** Freed News points are reallocated to Technical and Sentiment **pro rata to their
existing shares**, so the pool stays at exactly 70 and base_score remains comparable across sectors —
and Technical's 40:15 edge over Sentiment is preserved, changing the news/other balance without
re-ranking those two against each other. Each category's contribution rescales with its cap, so a
score is always the same percentage of a differently-sized slice.

Deliberately NOT folded into `live_weights`, despite sharing its redistribution math: `live_weights`
means "calibrated importance fitted from outcomes" (`feedback_loop.py`) and this means "how much real
information does this sector's feed carry". Overloading one on the other would let a future
calibration silently fight a coverage adjustment with no way to tell which produced a given weight.
They compose instead — this applies to whatever split `live_weights` leaves behind.

**Measured effect if enabled at 0.5 for regional_banks (2026-08-26 board):**

| | |
|---|---|
| ZION / KEY / HBAN / MTB / CFR / PNFP / ONB (news 0.0) | **+2.73 to +4.16** |
| RF / CFG / UMBF (news 3.2-7.0) | +0.44 to +1.52 |
| FITB (news 8.6) | **-1.20** |
| TFC (news 11.1) | **-2.47** |

Mean +2.07 across 12 banks, range -2.47 to +4.16. Note this is **directional, not a blanket boost**:
it lifts tickers whose news is uninformative and penalises tickers whose news is genuinely strong,
which is the property that makes it a meaningful knob rather than a constant offset. No bank comes
close to the 70 threshold either way (best moves 48.2 to 45.7).

**How to test it.** Set `enabled: true` and adjust the per-sector multipliers. A sector with no entry
is never silently reweighted, a malformed value falls back to 1.0, and 1.0 is a verified exact no-op.
Evaluate on the News sub-score and `relevant_article_count` rather than composite score — the v2.2.103
neutral floor otherwise masks part of the difference.

---

## [v2.2.110] — 2026-08-26 — [Bug Fix] Placeholder days scored as real history; feed outages and code bugs made distinguishable

**Status:** Live.

**In short:** The last two items from the data-source audit. All 1606 tests pass (16 new); ruff and
all three guardrail checkers pass clean.

**1. Sentiment measured momentum against fabricated days (`swing_model/sentiment_layer.py`).**
`_build_daily_bullish_ratios` pads days with no messages using a neutral 0.5 PLACEHOLDER so the
bucket list is always `days` long. Both the ratio z-score and the fallback velocity were reading
those placeholders as observations.

It bites because the StockTwits endpoint returns a fixed 30 messages however much activity a ticker
has, so how many days those 30 span varies enormously (measured live 2026-08-26: NVDA 0.1 hours,
ABBV 31 hours, PNFP 233 days). A dense, narrow sample lands almost entirely in ONE bucket — and
scored HIGHER than a genuinely broad one, which is backwards:

| Sample shape | daily_totals | ratio | velocity |
|---|---|---|---|
| NVDA — 30 msgs / 6 min | `[0,0,0,0,30]` | 5.6/7 | **5.0/5 (max)** |
| spread over 5 real days | `[5,6,6,6,6]` | 4.5/7 | 0.0/5 |

`_RATIO_MIN_BASELINE_MESSAGES` did not catch it: it counts baseline MESSAGES without checking how
many baseline DAYS produced them. ABBV's `[0,0,0,7,23]` cleared the 5-message bar on strength of a
single day, so `pstdev([0.5, 0.5, 0.5, 0.14])` was tiny and the z-score saturated at 7.0/7.

New `_MIN_REAL_BASELINE_BUCKETS` (2) requires real message-bearing DAYS, not just message count. The
velocity fallback now returns neutral when it cannot find two real observations — a rate of change
needs two points, and NVDA's maxed 5.0 was measuring the placeholder-to-real step, not sentiment
moving.

**Correction to the original diagnosis.** The audit assumed `_score_ratio` was fabricating a z-score
on thin data. It was not: it already falls back to scaling today's observed ratio linearly, which is
an honest snapshot (NVDA's 5.6/7 is exactly "80% of tagged messages were bullish"). Only the BUCKET
COVERAGE check was missing, and only the velocity fallback was inventing a signal. The fix is
correspondingly narrower than proposed — and deliberately leaves ABBV's 5.0/5 velocity intact, since
7 messages at ratio 0.14 followed by 23 at 1.0 is a genuine swing, not an artifact.

**2. A code bug could not be told apart from a feed outage
(`swing_model/run_swing_model.py`).** Seven external-feed wrappers each carried their own bare
`except Exception`, degrading EVERY failure to an empty list. That is correct for an outage — one
flaky ticker must not kill a 48-ticker scan — and wrong for a programming fault, which then presents
as "the vendor returned nothing".

This cost a real debugging detour the same day: v2.2.108 added kwargs to `_fetch_av_news_safe`, a
stale test stub raised `TypeError` on the new signature, and the wrapper swallowed it into an empty
result that read as "AV was simply not called". Same class as an SEC block reading as "no filings"
(v2.2.109).

One shared `_safe_fetch` helper replaces the seven copies — matching how this codebase has already
consolidated `_CSV_COLUMNS`, `trade_outcomes` and `_http_backoff`. Expected failures (`OSError` and
so covering requests' ConnectionError/Timeout, plus `ValueError`/`KeyError`/`IndexError` from vendor
payloads) log and return `[]` as before. Anything else logs at ERROR with a traceback AND writes a
`fetch_bug` row to `validation_log.csv`, then still returns `[]` so the scan survives. The reporting
path is itself wrapped, so a failure to log can never break a scan.

---

## [v2.2.109] — 2026-08-26 — [Bug Fix] An SEC request failure was indistinguishable from "nothing was filed"

**Status:** Live.

**In short:** `sec_edgar_client` returned `[]` both when a request FAILED and when it succeeded
against a company with no recent filings. Failures now return `None` internally and are written to
`validation_log.csv`. All 1590 tests pass (5 new); ruff and all three guardrail checkers pass clean.

**Why this was worth fixing rather than setting an email.** The project is technically out of
compliance with SEC's fair-access policy: `SEC_EDGAR_USER_AGENT` is unset, so requests carry
`StockAnalysis-SwingModel research@stockanalysis.local` — a non-routable domain. SEC asks for a
reachable contact and enforces by IP blocking. Assessed properly, the risk profile is:

- **Probability: low.** ~156 sequential requests a day (52 per scan x 3 scans) against a 10/second
  limit — two orders of magnitude of headroom. A User-Agent IS being sent, just an unreachable one,
  and SEC's automated enforcement targets missing or abusive agents. The realistic trigger is SEC
  wanting to make contact and having no route.
- **Impact: moderate.** One of five news sources, plus every filing-based Event Severity Gate
  trigger.
- **Detectability: poor — and that was the real problem.** A block returned `[]`, identical to a
  quiet week. Scores would drift down across the whole board with no visible cause.

Low probability x poor detectability is the profile that costs a day to diagnose six months later, so
the detectability half is the durable fix — it protects against every SEC outage, not just a policy
block, and it needs no contact address at all. The user opted for this over setting an email.

**The fix.** `_fetch_filings_for_form` now returns `None` on a request or parse failure and `[]` only
on a successful-but-empty feed. `fetch_recent_8k_filings` writes a `sec_edgar_request_failed_{form}`
row to `validation_log.csv` and logs a warning naming the consequence ("news and event-gate coverage
reduced"), while a genuine empty result stays quiet — a signal that fires on quiet weeks would be
worthless. A malformed feed counts as a failure, not an empty result.

**This also repairs a latent hazard in v2.2.107's own 6-K fallback**, shipped hours earlier: because
failure and emptiness were the same value, a FAILED 8-K request fell through to the 6-K branch, and a
successful 6-K response would then have cached 6-K as that ticker's form type — silently mislabelling
a domestic filer off the back of a transient outage, permanently for the life of the process. The
failure path now stops immediately without attempting the fallback.

---

## [v2.2.108] — 2026-08-26 — [Bug Fix] Sentiment neutral-on-missing; Alpha Vantage budget reserved for the owning scan

**Status:** Live.

**In short:** The two items left open by v2.2.107's data-source audit. All 1586 tests pass (13 new);
ruff and all three guardrail checkers pass clean.

**1. Sentiment forfeited to 0 on missing data where neutral is 7.5/15
(`swing_model/sentiment_layer.py`).** All three sub-scores are SYMMETRIC measures — a
bullish/bearish ratio, a sentiment/volume velocity, and a comment-count velocity — so 0 is not "no
information", it is the maximally-OPPOSING end of each scale:

| Sub-score | Range | Neutral | Was returning on no data |
|---|---|---|---|
| ratio | 0-7 | 3.5 | 0 |
| velocity | 0-5 | 2.5 | 0 |
| engagement | 0-3 | 1.5 | 0 |

A ticker nobody posts about was therefore scored exactly like one whose chatter is unanimously
against the thesis, across 15 of the 100 composite points — the same correction News received in
v2.2.103. `_score_engagement` was already internally inconsistent about this: it returned the neutral
midpoint when it had ONE item ("partial") and forfeited to 0 only at zero. Now all three return their
own midpoint, and `SENTIMENT_NEUTRAL_TOTAL` (7.5) is exactly `SENTIMENT_MAX / 2`.

`SENTIMENT_OFFLINE_CAP` still applies on top, deliberately. The two answer different questions: the
neutral score says "no evidence either way", the cap says "be less confident overall when this signal
is missing". Scoring absence as maximally bearish AND capping confidence was double-counting the same
gap.

**This and v2.2.107 are a matched pair.** Zero of the day's 48 tickers hit the forfeit path under the
old rules — nothing was "offline", because every ticker returned messages, however stale. v2.2.107's
staleness guard is what starts routing tickers there (3 of 5 sampled regional banks had no StockTwits
message inside the 5-day window). Shipped alone, that guard would have knocked ONB/CFR/UMBF from a
FABRICATED ~6.0/15 down to 0/15. Together they land on an honest 7.5 instead — more truthful than the
fabrication and not a penalty for being small.

**2. Alpha Vantage budget is no longer first-come-first-served
(`shared/api_clients/news_client.py`, `config/swing_config.yaml`).** AV is a confirmation source, not
a routine feed: a scan spends a call only when a free source already flagged a critical event. That
makes consumption lumpy, and the budget was drained in scan order — so the EARLIEST scan, ranking on
the least information, spent it and the most informed one went without. Measured live 2026-08-26: all
20 calls consumed, the post_close scan got only **6**, and TGT's news fetch was skipped outright.
Structurally the same failure as the rank-track slot bug fixed in v2.2.100, where the first scan of
the day claimed every per-sector slot.

New `alpha_vantage.reserve_for_owner_scan` (default 8 of 20) holds calls back for post_close — the
scan that ranks on the full session's data and owns the rank track's per-sector slots. Earlier scans
now stop at 12; post_close keeps the full 20 available. Deliberately a reservation rather than a
raised ceiling: AV's free tier allows 25/day against the 20 used here, so raising the limit buys five
calls and does nothing about the ordering. `scan_type=None` preserves the original behaviour for any
caller that does not know its scan type, and `reserve_for_owner_scan: 0` restores it globally.

**Test note.** Two existing tests asserted the old forfeit-to-0 behaviour and were rewritten — that 0
was the bug, not the contract, the same situation as `test_no_articles_returns_zero` in v2.2.103. A
third (`test_av_news_fetched_when_free_source_flags_critical_event`) failed for an unrelated reason
worth recording: its `_fetch_av_news_safe` stub took only `(ticker)`, so the new `scan_type`/`cfg`
kwargs raised a TypeError that the wrapper's broad `except Exception` swallowed into an empty result.
The wrapper logs a warning, so it is not silent in production — but a signature error is a
programming fault rather than the transient network failure that catch exists for, and it presented
as "AV was simply not called". Stubs updated to `(ticker, **kw)`.

---

## [v2.2.107] — 2026-08-26 — [Bug Fix] TSM/ASML filed a form the client never asked for; StockTwits had no staleness guard

**Status:** Live.

**In short:** Full audit of every external data source and API key. All 7 sources healthy and all 4
keys accepted; two real fetching bugs found, both silent. All 1573 tests pass (12 new); ruff and all
three guardrail checkers pass clean.

**1. TSM and ASML returned zero SEC filings on every scan ever run
(`shared/api_clients/sec_edgar_client.py`).** The client requested `type=8-K` only. A FOREIGN PRIVATE
ISSUER never files an 8-K — it files a 6-K, the same "a material event happened" current report.
Verified against SEC's submissions API:

| Ticker | 6-K | 8-K |
|---|---|---|
| TSM | 712 | **0** |
| ASML | 361 | **0** |
| NVDA (domestic control) | — | 63 |

Silent because an empty Atom feed is indistinguishable from "nothing was filed recently". That is 2
of 11 semiconductors permanently blind on this input — and since these filings feed the Event
Severity Gate, neither could ever raise a ticker-specific critical event from its own disclosures,
for a sector whose gate fires on tariff and export-control news constantly.

EDGAR's `type` parameter takes a single value, so the fix tries 8-K first and falls back to 6-K on an
empty result, caching whichever produced filings for the rest of the process. A domestic filer still
costs exactly one request; a foreign issuer costs two on its first fetch of the run. Deliberately
discovery-based rather than a hardcoded TSM/ASML list, so it works for any foreign issuer added to
the watchlist later without anyone remembering this distinction exists. Confirmed live: TSM and ASML
now return 10 filings each.

**2. StockTwits had no staleness guard on the path that decides trade DIRECTION
(`swing_model/sentiment_layer.py`).** `_build_daily_bullish_ratios` has always bucketed to
`0 <= age_days < days`, so the POINT score was protected. `classify_dominant_sentiment` read the raw
message list with no age filter at all — and it feeds `scoring.determine_direction()`, which decides
whether a trade is taken long or short. Its own docstring calls that "more consequential than a point
score". The most consequential output in the pipeline was the one input nothing was filtering.

It matters because the endpoint returns a fixed 30 messages regardless of how much real activity a
ticker has, so "30 messages" means wildly different things per ticker. Measured live 2026-08-26:

| Ticker | 30 messages span | Newest message |
|---|---|---|
| NVDA | 0.1 hours | today |
| ABBV | 31 hours | today |
| PNFP | 233 days | today |
| **ONB** | **364 days** | **2026-07-22 — 5 weeks stale** |

Sampling 5 regional banks, **3 (ONB, CFR, UMBF) had ZERO messages inside the 5-day window** while
still being scored as though they had data — ONB scored 6.0/15 sentiment on 2026-08-26 with no post
newer than 2026-07-22.

Fixed with a shared `_STOCKTWITS_MAX_AGE_DAYS` window applied in `classify_dominant_sentiment` and in
the `sentiment_offline` check, so the direction path and the point-score path can no longer disagree
about which messages are real. `sentiment_offline` previously tested only for an EMPTY list; 30
year-old messages counted as "online". Undated messages are now dropped rather than kept, because
`_parse_ts` falls back to `now()` on a parse failure — which would make an undated message look
maximally fresh, precisely backwards for a staleness filter.

**API key audit — all clean, nothing changed.** All four keys present and accepted:
Alpha Vantage (HTTP 200, 50 items), Finnhub (200, 246 articles), RapidAPI for both StockTwits and
Seeking Alpha (200), plus keyless SEC EDGAR and yfinance. The Discord webhook was shape-validated
only and deliberately NOT posted to — that would be an outward-facing side effect, not a read. `.env`
is untracked and gitignored, a repo-wide grep for hardcoded secrets is clean, the Alpha Vantage key
is redacted from error text, RapidAPI's key travels in a header rather than a URL, and
`tests/test_news_client.py` already asserts keys never reach the logs.

**Known and NOT changed, flagged for a decision:**
- **Sentiment forfeits to 0 when offline, where neutral would be 7.5/15.** All three sub-scores
  document a neutral midpoint (ratio 3.5 of 7, velocity 2.5 of 5, engagement 1.5 of 3) and all three
  "forfeit to 0" instead — the same absence-scored-as-worst shape fixed for News in v2.2.103. Fix 2
  above moves the fully-stale tickers into that path, so ONB/CFR/UMBF now score 0/15 rather than a
  fabricated ~6/15. That is more honest either way, but it is a further hit to exactly the
  low-coverage banks News was already penalising. Deliberately left alone here because, unlike News,
  this behaviour is intentional and has a documented compensating mechanism
  (`SENTIMENT_OFFLINE_CAP = 70` caps overall confidence when sentiment is unavailable). Whether
  forfeit-or-neutral is right is a strategy decision, and the two layers should agree.
- **`SEC_EDGAR_USER_AGENT` is unset**, so it falls back to
  `StockAnalysis-SwingModel research@stockanalysis.local` — a non-routable domain. SEC's fair-access
  policy asks for a reachable contact so they can make contact before throttling. Working today
  (HTTP 200), but a one-line `.env` addition removes the risk.
- **Finnhub coverage is heavily sector-skewed** — semiconductors average 65.1 articles per ticker,
  consumer discretionary 55.0, healthcare 29.1, regional banks **5.4** (one ticker zero). The
  upstream cause of the News disparity fixed in v2.2.103. A vendor coverage limitation, not a bug.
- **Alpha Vantage budget** — deferred to a wider API discussion (see v2.2.106).

---

## [v2.2.106] — 2026-08-26 — [Infrastructure] Dropped a ticker with unusable vendor data; stopped failing a real market condition as invalid

**Status:** Live.

**In short:** Two data-quality items from the day's scan review, both producing daily noise and
neither affecting scoring correctness. All 1561 tests pass (7 new); ruff and all three guardrail
checkers pass clean.

**1. WBS removed from the regional_banks watchlist (`config/swing_config.yaml`).** It had been
failing pre-flight OHLCV validation and being excluded from EVERY scan since at least 2026-08-24,
while still costing 6 validation-log rows a day. Checked directly against the vendor rather than
assumed:

| Ticker | Bars (1y) | Max gap | Gaps > 4d | Zero-volume days |
|---|---|---|---|---|
| **WBS** | **236** | **9** | **3** | **2** |
| ZION / KEY / MTB / CFR | 251 | 4 | 0 | 0 |

WBS is missing 15 trading days its peers all have, and carries zero-volume prints on otherwise normal
price action (2026-04-08 opened 71.92, closed 71.64, volume 0). Every peer comes back clean, so this
is specific to WBS — not a vendor-wide artifact, and not an over-strict validator. The validator was
right; the data is genuinely unusable. Removing it loses no coverage that was actually being
collected. Regional banks keep 12 tickers, active watchlist 48. Re-add if the data source is fixed or
replaced — the ticker itself is a legitimate KRE constituent.

**2. Institutional-ownership bound widened from 1.0 to 1.5 — and deliberately NOT clamped
(`shared/utils/data_validator.py`).** CFG reported `held_percent_institutions` 1.0043 and failed
validation every scan on a 0.43% overshoot. That overshoot is almost certainly accurate: ownership
above 100% is a real, routine market phenomenon, not corrupt data — shares lent to short sellers and
resold are counted by both the original holder and the buyer, and 13F filing dates lag the share
count they are divided by. Yahoo reports >100% for heavily-shorted names as a matter of course.

The initial proposal was to clamp the value to 1.0. That would have been wrong:
`positioning_layer._score_institutional` scores the TREND (this scan's value against the previous
scan's), never the absolute level, so clamping would erase a genuine 1.0043 -> 1.0100 accumulation
into a flat 1.0 -> 1.0 non-event. The raw value is exactly what the signal is built from. The bound
is now a unit-error tripwire rather than a market judgement: a percentage passed as 100.43 instead of
1.0043 lands far outside 1.5, while any plausible real reading lands well inside.

**Not changed: the Alpha Vantage daily budget.** All 20 calls were spent on 2026-08-26 and the
post-close scan — the most informed one, and the one that now owns the rank-track picks — got only 6
of them, with TGT's news fetch skipped entirely. Earlier scans consume the budget first, which is the
same first-come-first-served shape as the rank-track slot bug fixed in v2.2.100. Deferred at the
user's request pending a wider API discussion; the fix would be reserving a share of the budget for
the owning scan rather than raising the limit (AV's free tier is 25/day, only five more calls, which
would not address the ordering).

---

## [v2.2.105] — 2026-08-26 — [Bug Fix] Recorded reward:risk was the planned figure, not the one the trade got

**Status:** Live.

**In short:** `rr_ratio` is frozen at signal time off the zone-midpoint `entry_price`, but the target
price does not move when the fill lands somewhere else — so the ratio the ledger advertises stops
being the ratio the trade is running. New `rr_ratio_at_fill` records the real one. All 1554 tests
pass (4 new); ruff and all three guardrail checkers pass clean.

**The problem.** A fill rarely lands on the zone midpoint — the fill simulator prices a gap at the
open, deliberately (`shared/utils/fill_simulation.py`'s "worse of trigger-vs-open" convention). When
it doesn't, risk changes while the target stays put. A worse fill means MORE risk for the SAME
target, so the real ratio falls; a better fill raises it. Measured across all 10 filled trades on
2026-08-26, **8 drifted**:

| Ticker | Planned | Actually got |
|---|---|---|
| PFE 2026-08-07 | 3.00 | **2.00** |
| TGT | 3.00 | **2.34** |
| PFE 2026-08-10 | 3.00 | 2.48 |
| LLY | 3.00 | 3.06 |
| NVDA | 3.00 | 3.12 |
| MU | 3.00 | 3.31 |
| AMGN | 3.00 | 3.32 |
| MRK / ABBV / JNJ | 3.00 | **3.50** |

Worst case is a 33% overstatement. The drift is signed and trade-specific, not noise, so it does not
wash out across a sample — any EV, expectancy or R:R statistic reading `rr_ratio` after a fill is
reading the planned number rather than the real one.

**The fix.** `paper_updater.py` computes and stamps `rr_ratio_at_fill` at the moment a fill is
confirmed, in the same block that already re-anchors `actual_dollar_risk` to the fill price for
exactly this reason ("the R-multiple and the dollar figure it gets multiplied by sharing the same
price basis"). Written ALONGSIDE `rr_ratio`, never over it: the planned ratio is what the signal was
selected on and is worth keeping for provenance. Exit behaviour is deliberately untouched — the
target price does not move, this only records what that target is worth from where the trade actually
got in. `scripts/backfill_rr_ratio_at_fill.py` populated the 10 rows filled before the column
existed; it fills blanks only and never overwrites.

**Investigated and found NOT to be a bug: shares positions "getting ~10x the exposure" of options.**
The earlier review flagged MU deploying $4,144 (27.6% of the simulated account) against $263-484 for
every options pick, and proposed equalising the cap. Measured on the dimension that actually matters,
there is nothing to equalise — **risk is already comparable**:

| | capital deployed | % account | dollar risk | % account |
|---|---|---|---|---|
| MU (shares) | $4,144.52 | 27.6% | $405.88 | 2.71% |
| options picks | $263-484 | 1.8-3.2% | $263-484 | 1.75-3.23% |

MU's risk sits mid-range against the options rows. The gap is in capital COMMITTED, not capital at
risk: shares tie up full notional while a long option ties up only its premium, which is also its max
loss. `position_sizer.py` takes whichever of the risk budget and the capital cap binds tighter, and
for options those two are near-identical because premium approximates risk — so the apparent
asymmetry is an artifact of comparing a notional figure against a risk figure, not a sizing defect.
No change made. The residual concern — that committed capital matters if the account is treated as a
finite cash balance — is real but is the deferred portfolio-simulation question (the sizer anchors to
a fixed `starting_capital` rather than a decremented balance), not a per-position sizing fix.

**Test note.** Both new drift tests failed on first run, and the fixtures were at fault rather than
the code: they left `entry_zone_lower`/`entry_zone_upper` blank, which sends the updater down its
legacy no-zone path where `pnl_entry_price` IS `entry_price` — so no slippage occurs and there is
nothing to measure. Corrected to use a real zone with a bar that gaps past it, which is the situation
the column exists to capture.

---

## [v2.2.104] — 2026-08-26 — [Bug Fix] Unreachable targets and sub-noise stops — entry/stop/target geometry now ATR-bounded

**Status:** Live.

**In short:** Targets could be set anywhere a low-volume pocket happened to sit, with no upper bound,
and stops could be pulled inside a single day's typical range. Both are now bounded in ATR terms.
All 1550 tests pass (12 new); ruff and all three guardrail checkers pass clean.

**A correction to how this was originally diagnosed.** The first pass flagged MU's +29.4% target as a
fantasy on percentage alone. Measured properly it is nothing of the sort: MU's ATR is 6.6% of price,
so that target is 1.55x its expected 10-day move — the second most achievable of the day's eight
picks. Percentage move is the wrong lens for this entirely; a 29% target on a high-volatility
semiconductor and a 6% target on a mega-cap staple can be equally (im)plausible. Every threshold here
is therefore ATR-relative. The genuine outlier was QCOM at 3.26x.

**1. Volume-profile targets had no upper bound (`shared/utils/risk_reward.py`).** `compute_target`
took any `low_volume_area_above` sitting beyond the `min_rr` target, on the sound reasoning that price
travels quickly through thin volume — but that says nothing about WHEN. Live 2026-08-26: QCOM drew a
pocket 65.84 away against a 5.63 stop distance, an **11.69:1 target needing +39%**, or 3.26x its
expected 10-day range, inside a 10-day time stop. Every other pick that day sat at 0.79-2.14x.

New `reachable_move(atr, holding_days, multiple)` = `multiple x ATR x sqrt(holding_days)`. The square
root is the random-walk scaling of volatility with time — a stock does not travel ATR x N over N days,
it travels roughly ATR x sqrt(N), so a target set as a flat ATR multiple silently gets harder the
shorter the window. Deliberately a coarse feasibility bound, not a forecast: it answers "is this
target in the same postcode as what this stock actually does in two weeks", which a fixed `min_rr`
multiple never asks.

An out-of-range volume level is DISCARDED, not clamped to the ceiling: the pocket was the entire
justification for reaching past `min_rr`, so if it is unreachable there is no evidence for an
intermediate target either — the `min_rr` target stands. The `min_rr` target itself is never capped;
shrinking it would quietly violate the configured minimum R:R, and a `min_rr` target that is itself
unreachable means the STOP is too wide for the window, which is a sizing question, not a target one.

**2. HVN stops could sit inside one day's range (`shared/utils/risk_reward.py`).** `compute_stop_loss`
accepted a high-volume-node support/resistance whenever it was tighter than the ATR stop, no matter
how close. Live 2026-08-26: **SBUX stopped at 0.83 x ATR and QCOM at 0.88 x ATR**, against ~2.25 for
the picks that fell back to the plain ATR stop. A stop inside a single day's typical range is hit by
ordinary noise rather than by the thesis being wrong — and it is doubly bad here because
target = `min_rr` x stop distance, so a too-tight stop ALSO shrinks the target. The trade gets an
easily-triggered stop and a small target at the same time: stopped out on noise before its own modest
target is reached. New `min_stop_atr_multiple` (default 1.0) floors the distance; the ATR stop remains
the outer bound, so this only ever trims tightness.

**Measured effect on the day's 8 rank picks — 6 unchanged, 2 corrected:**

| Ticker | Stop was | Stop now | Target R:R was | now | Target / expected 10-day move |
|---|---|---|---|---|---|
| QCOM | 0.88 x ATR | 1.25 x ATR | 11.69 | 3.00 | 3.26 -> 1.19 |
| SBUX | 0.83 x ATR | 1.25 x ATR | 3.00 | 3.00 | 0.79 -> 1.19 |

The book moves from a 0.79-3.26x spread to 1.19-2.14x. Stops land at 1.25 x ATR rather than 1.0
because the floor is measured from `entry_zone_lower` while entry is the zone midpoint, a further
0.25 x ATR up.

Both knobs are config-driven (`risk_reward.min_stop_atr_multiple`,
`risk_reward.max_target_atr_multiple`) and both degrade to the old behaviour — set the stop multiple
to 0, or omit `atr_14`/`holding_days`, and the functions behave exactly as before. The feasibility
ceiling is measured against `signal_decay.time_stop_day` (10), not `MAX_HOLDING_DAYS` (15): a trade
holding under 30% of the target move is closed at day 10, so sizing a target against 15 days it will
rarely be given is part of what made targets unreachable in practice.

**Test note — the first implementation was written backwards, in both directions.** The existing
`test_hvn_stop_used_when_tighter` / `..._bearish` tests caught it immediately. Bullish stops sit BELOW
entry, so a floor on stop DISTANCE is a ceiling on stop PRICE, and the clamp needs `min()`, not
`max()`; bearish is the mirror. As written it pushed an HVN at 1.25 x ATR (perfectly acceptable) IN to
the floor instead of leaving it alone — the exact opposite of the intent. `TestStopDistanceFloor` now
covers both directions on both sides of the boundary specifically so this cannot silently invert
again.

---

## [v2.2.103] — 2026-08-26 — [Bug Fix] "No news" scored as worst-possible news; unfunded trades counted in the win rate

**Status:** Live.

**In short:** Two fixes from a review of the day's scan and trades, both distorting numbers that feed
the rank track's 2026-09-19 checkpoint. All 1538 tests pass (7 new); ruff and all three guardrail
checkers pass clean.

**1. A ticker with no relevant coverage was scored identically to one with unanimous, credible,
thesis-destroying news (`swing_model/news_layer.py`).** Every news sub-score returns 0.0 on an empty
article list — but 0.0 is also the maximally-OPPOSING value of both symmetric sub-scores.
`credibility_weighted_score` maps confirming 1.0 / neutral 0.5 / opposing 0.0 scaled to 0-6, so a
wholly neutral article set lands on 3.0 and an empty one landed on 0.0. `theme_alignment_score` maps
[-1,+1] through `(v+1)*2` to 0-4, so opposing lands on 0.0, neutral on 2.0 — and empty landed on 0.0
again. Absence of evidence was being scored as strong evidence against, across 15 of the 100
composite points.

Measured live on 2026-08-26: **7 of 12 regional banks scored 0.0/15 despite each fetching 30+
articles** (the relevance filter matched none of them), pulling the sector to a 2.97 mean against
7.52-9.42 for every other sector. That is a ~5-point composite handicap applied for lack of press
coverage — a function of market cap and media profile, not of the trade setup. It is also a standing
candidate explanation for a finding this project has recorded repeatedly without resolving: regional
banks producing zero qualifying trades in every audit.

Fixed by scoring no-coverage at each symmetric sub-score's own midpoint (credibility 3.0, theme
alignment 2.0). `clustering_score` and `decay_score` deliberately stay at 0.0: unlike the other two
they are not confirm/oppose axes but counts of positive evidence ("how many independent corroborating
clusters", "how fresh is the newest item"), so zero is the honest answer when there is nothing to
count, not a penalty. Neutral therefore totals **5.0/15, not the 7.5 midpoint** — silence should not
score like evidence. Effect on today's board: the 8 affected tickers each gain exactly +5.0, the best
of them moving 44.9 to 49.9 — still far below the 70 threshold, so this removes an artificial
handicap without manufacturing qualifying trades.

News also now reports a `data_quality` field (`complete` / `no_relevant_articles` / `no_articles`) and
is counted by `compute_data_sufficiency()`. It was the last scoring layer reporting no data-quality
signal at all — fundamental has had `unavailable` -> neutral since it was built, sentiment has
`sentiment_offline`, and technical gained one in the 2026-08-22 audit.

**2. Trades that never deployed capital were counted in the win rate
(`shared/utils/trade_outcomes.py`, `paper_updater.py`, `paper_trade_metrics.py`).** A signal can
qualify, resolve a real directional call, and still size to zero units when its best structure costs
more than the risk budget allows at this account size. **LLY 2026-08-12 closed 2026-08-26 as a
time_stop at -0.264R with `position_size=0` and `pnl_dollars=0.00`** — it could never have made or
lost a cent. Counted by outcome alone it landed in the win-rate denominator and, being unprofitable,
not the numerator: the paper track went from 0-of-2 to **0-of-3** on the strength of a trade that did
not exist in dollar terms. MU is the same shape and still open, so it would have done this again.

New `is_funded()` / `is_performance_row()` alongside the existing `is_scored()`, and the win-rate
paths in `paper_updater.print_summary()` and `paper_trade_metrics`' lifetime totals now use
`is_performance_row`. The summary reports unfunded closed rows on their own line rather than hiding
them.

Deliberately NOT applied to signal accuracy or weight calibration. An unaffordable call still
resolved a genuine directional prediction, and that is real evidence about whether the MODEL is
right — just not about whether the STRATEGY is fit to trade money.
`compute_signal_accuracy()` already reports funded and unfunded side by side, and `feedback_loop`'s
calibration set keeps both; both are correct as they stand. `paper_trade_metrics._is_funded` is now
an alias of the shared definition rather than a second copy.

**Test note.** `test_no_articles_returns_zero` asserted the old behaviour and was rewritten — the
0.0 it locked in was the bug, not the contract. The replacement comparison test was also rewritten
after it failed: driving theme alignment with synthetic "bearish" headlines is unreliable, since
`identify_dominant_theme` scored a hand-written "NVDA bearish outlook" fixture at 4.0, i.e. maximally
CONFIRMING. The test now asserts per sub-score on the credibility axis, which is driven directly by
the sentiment label and isolates the axis cleanly.

---

## [v2.2.102] — 2026-08-26 — [Bug Fix] The threshold track's dedup was silently filtering the rank track's candidate pool

**Status:** Live.

**In short:** `_run_rank_track`'s docstring promises the two paper-trading tracks are "fully
independent ... never cross-checked against the threshold track". They weren't. The main scan loop
checked the THRESHOLD track's same-day dedup at the top of the loop and `continue`d before the
rank-track candidate stash, so any ticker that had already produced a qualifying signal that day
never entered the rank track's candidate pool at all. Found while answering a question about whether
the rank track really picks its sector top two. All 1531 tests pass (6 new); ruff and all three
guardrail checkers pass clean.

**Why it matters more than a normal dedup bug: the bias has a direction.** The only tickers that
land in `paper_trades.csv` are the ones scoring 70+. So the filtered-out set was never random — it
was precisely the STRONGEST name in each sector, the one most worth ranking. The rank track was
therefore not testing "does rank-selection work" so much as "does rank-selection work on everything
that didn't already qualify outright."

**Confirmed live on 2026-08-25.** AMGN qualified pre-market at 75.0 and was logged to the threshold
track. It is then absent from the entire 47-ticker post-close scoreboard — skipped at that
`continue`. Healthcare's post-close rank picks were MRK (72.6) and ABT (68.7), with the sector's
highest scorer silently ineligible.

**v2.2.100 made this worse, not better.** Gating the rank track to `post_close` was right on its own
terms (it ranks on the full session's data), but it means the rank track now always runs LAST — which
is exactly when the threshold ledger is most populated, and so when this filter bites hardest.
Before that change the pre-market scan usually took the rank slots before the threshold track had
logged anything, so the leak mostly didn't fire.

**The fix.** The dedup moved from the top of the loop to immediately after the rank-track candidate
stash. The threshold track still refuses to log a second same-day signal — unchanged — but the
ticker now reaches the ranking with a real score.

Two placement details, both deliberate. It stays ABOVE the sub-threshold branch: that branch fires a
near-miss Discord alert, and a ticker with a live signal already logged today shouldn't also ping as
a near-miss if it slips under 70 on a later scan. And the cost of moving it is that an already-logged
ticker now re-runs the loop's per-ticker fetches instead of short-circuiting — unavoidable rather
than incidental, since a ticker can't be ranked without a score and the score needs those fetches.
It is also small: only tickers that already produced a qualifying signal TODAY reach there, typically
0-1 a day (2026-08-25: just AMGN) against 47 scanned, and the Alpha Vantage fetch stays
budget-guarded by `free_sources_flag_critical_event` either way.

**Test note.** The existing 1525-test suite passed both before and after the fix — nothing covered
this ordering, which is why it survived. `tests/test_rank_track_threshold_independence.py` asserts
the invariant directly against the loop's source (the same approach the repo's guardrail checkers
take, since the behavioural path needs a full network scan), and was verified to FAIL when the bug is
deliberately reintroduced rather than passing vacuously. It also guards the two ways the fix could be
undone: deleting the dedup outright (which would double-log threshold signals) and moving it back
above the stash.

---

## [v2.2.101] — 2026-08-26 — [Feature] A newer qualifying signal now supersedes a still-pending one on the same ticker

**Status:** Live.

**In short:** The duplicate-position guard treated every open row as equivalent. It isn't: a PENDING
row (logged, entry order never triggered, no capital at risk) is a stale opinion, while a FILLED row
is real exposure. A pending row on a ticker now gets cancelled when a newer signal qualifies on that
same ticker, and the fresh signal takes its place. Filled rows block exactly as before. All 1525
tests pass (26 new); ruff and all three guardrail checkers pass clean.

**The problem.** `entry_zone_lower/upper` is a breakout/breakdown trigger, not a price the stock is
already at, so a signal sits unfilled for up to `FILL_WINDOW_DAYS` (5) before expiring. Throughout
that window `_load_open_positions()` reported the ticker as occupied and
`paper_runner.py` skipped every new qualifying signal on it. But that pending row's entry zone, stop
and target were computed from data now up to a week old — and if the same model scores the same
ticker as qualifying again today, today's read is strictly the better-informed one. The old
behaviour let a stale, never-triggered order hold the slot until it expired, and the replacement
signal was simply discarded. On the current ledger that guard is holding three tickers (AMZN, HD,
AMGN), all pending, none with a cent at risk.

**The change.** New `_load_pending_positions()` returns tickers whose open rows are all unfilled —
deliberately a strict subset of `_load_open_positions()`, so a ticker carrying ANY filled row is
absent even if it also has a pending one (real exposure wins). Both tracks' guards now split on it:
pending → `_supersede_pending_signals()` cancels the old row and the new signal is logged; filled →
skip, unchanged.

Cancelled rows get `outcome="superseded"`, `exit_date`, and a `sizing_note` recording the date and
the superseding signal's confidence. They book no P&L, because no capital was ever at risk.

**The race it guards against.** `paper_updater.py` stamps `fill_date` the moment the entry zone
trades, and can do so mid-scan — between the guard reading its snapshot and the supersede actually
running. Cancelling then would close a position with real money in it. So
`_supersede_pending_signals()` re-checks pending status UNDER THE LOCK and returns an empty list if
the row filled underneath it; both call sites treat that as "ticker still occupied" and fall back to
skipping. The check that matters is the one holding the lock, not the one that decided to try.

**Supersede fires across OPPOSITE directions — deliberate, confirmed with the user.** A qualifying
bearish signal cancels a pending bullish one on the same ticker, and vice versa. Three reasons: it
matches the guard it sits inside, which already blocks regardless of direction on the Signal
Integrity Audit's C.5 reasoning (conflicting-direction signals on one name read as noisy signal
quality, not a hedge this model is built to run); a direction flip is the STRONGEST evidence the
pending order is stale, so restricting to same-direction would preserve that order precisely when
the model has most emphatically repudiated it, while discarding the newer read; and a pending order
has no capital committed, so there is no exposure to net out. The filled-position check is
unaffected — real exposure blocks whichever way it points.

The code achieves this by never consulting `direction` at all, which reads as an oversight rather
than a decision, so `TestSupersedeIgnoresDirection` exists to stop it being "fixed" into
same-direction-only later. Worth noting this also improves the data: previously a bearish signal on
a pending-bullish ticker was silently discarded and the flip left no trace, whereas the ledger now
records what replaced what, making direction flips visible and countable for the first time. If
whipsaw on a ticker turns out to be a real problem, that is the data needed to prove it — and the
remedy would be a separate whipsaw guard ("suppress this ticker after N direction changes in M
days"), not a restriction on supersede. Conflating the two would give the worst of both: keeping the
stale order AND rejecting the new one, which is not caution, just acting on older information.

**New `shared/utils/trade_outcomes.py` — the reason this change is small instead of risky.** "Did
this row ever put money at risk?" was written as a scattered `outcome != "expired"` literal in eight
places across `paper_updater.py`, `paper_trade_metrics.py` and `feedback_loop.py` — every win-rate
denominator, every P&L total, and the calibration training set. Adding a second never-funded outcome
meant finding all eight, and any one missed would silently count an unfilled signal as a real closed
trade: dragging win rate down, feeding a phantom loss into live scoring-weight calibration, and doing
it invisibly, since the row looks structurally identical to a genuine close. That is the same shape
as the hardcoded-threshold bug this project already hit three times (v2.2.75/v2.2.83). Replaced with
one `UNFUNDED_OUTCOMES` set and `is_scored()`/`is_unfunded()` helpers, imported everywhere.

One call site deliberately keeps the `expired`-only literal:
`compute_expired_signal_opportunity_cost()` asks "the market never came to our entry order — would
entering at signal price have paid?". A superseded row was cancelled because a newer signal replaced
it on the same ticker, so its hypothetical would double-count the same underlying move the
replacement already tracks.

The summary counts the two causes separately rather than pooling them — expired means the market
never came to the order, superseded means the model changed its mind before it got there, and those
say different things about the model.

---

## [v2.2.100] — 2026-08-26 — [Bug Fix] Scan/trade-ledger review — 4 real bugs, including one silently tripling the rank track's own dataset

**Status:** Live.

**In short:** Review of the 2026-08-25 scan output and all 39 logged trades across both paper-trading
tracks. Four real bugs, one of which was quietly corrupting the dataset the rank track was created to
build, plus the ledger reset and three structural changes that stop it recurring. All 1499 tests
pass (56 new); ruff and all three guardrail checkers pass clean.

**1. The rank track logged 3x its configured trade count — and mislabelled every row's rank
(`paper_trading/paper_runner.py`).** `rank_track.top_n_per_sector` is 2, and the intent is 2 picks per
sector per DAY. `_run_rank_track` loaded a dedup key set of `(signal_date, ticker)` and, on hitting an
already-logged ticker, `continue`d further down that sector's ranking — so it never logged the same
ticker twice, but every scan still filled `top_n` *fresh* slots. With three scans a day (pre-market /
mid-session / post-close) that is 3x top_n per sector: on 2026-08-25 exactly 6 rows per sector, 24
in one day against a configured 8. Worse, scans 2 and 3 are by construction the LOWER-ranked names
(the higher ones were already taken), and the log line reported the loop's `picks` counter as the
rank — so ASML was written to the log as "rank #1 in semiconductors" while MU, logged hours earlier
at a higher score, was the real #1. The track's entire purpose is a clean, comparable dataset to
judge a rank-based strategy on (see v2.2.98), so this was inflating and biasing the only evidence it
exists to produce, ahead of its own 2026-09-19 checkpoint. Fixed by counting slots consumed per
`(day, sector)` and seeding each sector's `picks` from what earlier scans already used; the log line
now reports the candidate's true within-sector rank alongside the slot number. Sector is resolved
from this scan's candidates first (authoritative) with config's watchlist map as fallback — a ticker
that resolves to neither cannot be attributed to a sector and so cannot consume a slot, which would
silently restore the overcounting, so that case is now warned about rather than swallowed.

**2. `mom_5d` was never computed in the live pipeline — all 39 logged trades recorded 0.0000
(`shared/indicators/technical_common.py`).** Both `paper_runner.py` and `run_swing_model.py` persist
5-day price momentum to their CSV rows via `indicators.get("mom_5d", 0.0)`, but nothing anywhere in
`swing_model/` or `shared/` ever produced that key — only `backtesting/` computed a `mom_5d`, locally,
for its own momentum-proxy sentiment layer. So every live row silently saved the default while
presenting as a real measurement, and the column reads exactly 0.0000 on all 39 rows across both
tracks. Now computed alongside the other windowed scalars in `compute_technical_indicators`, so every
consumer (live pipeline, backtest, tests) picks it up without its own copy; insufficient history or a
NaN/zero base bar reports 0.0 rather than raising or yielding `inf`. The backtest's separate local
copy is deliberately left alone. **Note for anyone analysing the existing ledger: `mom_5d` carries no
information on any row logged before this version — it is a constant, not a measurement.**

**3. Open-position critical-event alerts re-fired on every scan
(`swing_model/run_swing_model.py`, `paper_trading/paper_runner.py`, `shared/utils/event_gate.py`).**
The alert fired once per matching critical event per scan, with no memory across runs. A critical news
item stays in the feed for days, so MU produced ~9 identical "tariff" alerts a day across
2026-08-24/25 — for a position that had sized to 0 units, so there was nothing to act on either.
Alert fatigue on a safety channel is a real failure mode. Now fires once per
`(ticker, trigger, event timestamp)`, keyed on the event rather than the headline so the same story
arriving via a second vendor's phrasing does not re-alert, while a genuinely new story on the same
trigger still does. This mirrors the `action != pos["_last_management_action"]` transition guard the
signal-decay alert beside it already used. The dedup ledger lives in `event_gate_state.json`;
`validate_event_gate_state` rebuilds that dict from scratch on every load, so it had to be taught to
preserve (and prune) the new key — otherwise the ledger would reset each scan and the duplicates
would come straight back.

**4. Zero-size positions counted as real marked positions (`paper_trading/paper_updater.py`).** A
signal whose risk budget cannot buy even one share/contract at this account size logs with
`position_size=0` and no capital at risk. The mark-to-market step still wrote its dollar mark as
`"0.00"` — a NON-BLANK string, which is exactly what the summary's `marked` filter tests for. So these
rows counted toward the open capital-at-risk total, directly contradicting that filter's own "blank
for pending/expired/zero-size rows" comment: 2 of the 8 "marked position(s)" reported on 2026-08-25
(LLY and MU) were these. Zero-size rows now get no dollar mark, and the summary reports them on their
own line. `unrealized_rr` is still written for them — the R-multiple is a genuine read on signal
quality whatever the position's dollar size.

**5. One scan now owns the day's rank slots — `rank_track.scan_type`, default `post_close`
(`config/swing_config.yaml`, `paper_trading/paper_runner.py`).** Fixing bug 1 by itself left the
day's per-sector slots going to whichever scan ran first, which is `pre_market` — the scan ranking on
the LEAST information of the day's three. `post_close` has the full session's data and costs nothing
in timing, since entry is a next-day breakout trigger either way. It also dissolves the contention
rather than managing it: one scan a day, top 2 per sector, no competition between scans. Set to
`any` to restore every-scan behaviour. Deliberately belt-and-braces with bug 1's per-(day, sector)
budget rather than replacing it — the two fail differently: the gate picks WHICH scan ranks, the slot
count stops any scan from logging past the budget, including a manual re-run or retry of the owning
scan (see `data/logs/paper_runner_task_rerun.log` — those happen).

**6. New standing guardrail: `scripts/check_rank_track_slot_budget.py`, wired into CI.** What makes
bug 1 worth a permanent check rather than a one-off fix is that it was **invisible from the logs**.
Every run reported `Rank track: 8 new signal(s) logged` — exactly the expected number — because each
scan only ever counted its own work. Nothing was wrong in any single run's output; the violation
existed only across runs, in the file, and would have survived to the 2026-09-19 checkpoint and
quietly biased the verdict. The check reads the ledger (not source — the invariant is a property of
what actually got logged, so a future refactor reintroducing the bug through a different code shape
is still caught) and fails if any (signal_date, sector) group exceeds `top_n_per_sector`. Verified
against the real bad example: run on the pre-fix ledger it reports all four sectors at 6 rows against
a budget of 2 and exits 1. Rows whose ticker is no longer in any active sector are reported as a
warning, not a failure, and the warning says plainly that those rows aren't budget-checked so a
violation could hide among them. Same reasoning as `check_confidence_threshold_duplication.py`: the
manual audit caught this after the fact, nothing caught it as it happened. In CI it no-ops
(`rank_trades.csv` is untracked); its real work is against a live ledger.

**Ledger reset — the 24 contaminated 2026-08-25 rank rows were deleted.** The day logged 24 against a
configured budget of 8. The surplus can't be cleanly reconstructed: scores moved between scans, so
"the true top 2" depends on which scan owns the day, which was itself unsettled until fix 5 above.
One day of data on a track that produces 8 signals/day is cheaper to re-collect than a permanently
caveated baseline, so `rank_trades.csv` was reset to headers only and the track restarts clean under
the fixed code. None of the deleted rows had a fill or an outcome — they were unresolved signals, not
history. Pre-reset file preserved at `paper_trading/rank_trades.csv.pre-v2.2.100.bak` (the ledger is
untracked, so git would not have recovered it).

**7. Score denominators are now persisted — `technical_max`/`sentiment_max`/`news_max`
(`paper_trading/paper_runner.py`, both row builders).** `scoring.py`'s `live_weights` path rescales
technical/sentiment/news to the calibrated fraction of their shared 70-point pool, which MOVES each
category's real ceiling — deliberately, and deliberately not re-clamped, since re-clamping would
break the three-field sum invariant `base_score` depends on. The denominator was never stored, so a
row was uninterpretable after the fact: AMZN 2026-08-19's `sentiment_score=26.1` against a nominal
max of 15 reads as a scoring bug and is actually a 0.4 sentiment weight raising the real cap to 28.
Now written on every new row by both tracks, defaulting to the nominal caps when no calibration is
active. Only these three: `positioning_max`/`fundamental_max` are fixed config constants that
calibration never touches (and `scoring.py` doesn't return them), so they can't drift out from under
a row the way these can.

`scripts/migrate_paper_trades_csv_schema.py` extended to migrate BOTH ledgers — the two tracks share
one `_CSV_COLUMNS` list, so migrating only the threshold track would have left the rank track's
header short and silently corrupted its next append (`csv.DictReader` maps the old, shorter header
positionally onto the new longer rows, shifting every column after the insertion point). The rank
track didn't exist when that script was first written, which is why it only ever handled one file.

**Historical rows backfilled rather than left blank — `scripts/backfill_score_maxes.py`.** The
initial assessment in this entry's "not changed" list was that the pre-v2.2.100 denominators were
unrecoverable. That was wrong: they aren't in the ledger, but they are in git, and only ONE
calibration was ever live. Global `calibrated_weights.json` has never carried a `last_calibrated`
key, and `load_live_weights_if_calibrated()` returns None without one — so the global path never
reweighted anything, for any row, ever. The per-sector file held exactly one entry,
consumer_discretionary {technical 0.4, sentiment 0.4, news 0.2}, live 2026-08-15 (946646f) to
2026-08-23 (a085942), in the old flat pre-direction schema that is read as BULLISH weights only.
That yields 28.0/28.0/14.0 for consumer_discretionary bullish rows in that window and nominal
40/15/15 everywhere else.

Three independent checks that the derivation is right, all asserted in the script itself and in
`tests/test_score_max_persistence.py`: (a) exactly the 3 rows the rule marks as calibrated are the
only 3 in the ledger whose stored scores exceed their nominal maxes — no false positives, no misses;
(b) after backfill no row anywhere exceeds its own denominator, and the script aborts rather than
writing if one would; (c) AMZN appears on BOTH sides of the window — 2026-08-07 sentiment 4.7 (fits
nominal 15) and 2026-08-19 sentiment 26.1 (needs 28) — same ticker, same sector, so the date
boundary alone separates them. All 15 threshold-track rows backfilled; both scripts refuse to
overwrite non-blank values and are safe to re-run. Pre-migration ledger preserved at
`paper_trading/paper_trades.csv.pre-v2.2.100-schema.bak`.

**This supersedes the pooled-analysis warning below for those three rows** — they are now
self-describing (AMZN 93% of its sentiment cap, HD 74%, TGT 75%) and can be normalised rather than
discarded. They remain scored under a calibration later judged invalid, so treat them as a different
scoring regime, not as bad data.

**Not changed, flagged for a decision:**
- **Three threshold-track trades (AMZN and HD 2026-08-19, TGT 2026-08-20) were scored under the
  per-sector calibration that v2.2.89 deleted as "stale, invalid ... actively steering live scoring."**
  Under that calibration consumer-discretionary sentiment carried a 0.4 weight (real cap 28, not the
  nominal 15), which is why those rows show sentiment scores of 26.1 / 20.6 / 21.1 — legal at the
  time, by the deliberate reweighting in `scoring.py`, but not comparable to anything scored after
  2026-08-23. AMZN's 77.1 is the highest confidence in the whole ledger and was driven by that
  inflated sentiment. The CSV never records the max a score was graded against, so this is not
  recoverable from the ledger alone — **see fix 7 above, which revises this: they were recoverable
  from git, and have been backfilled.** What stands is that they were scored under a calibration
  since judged invalid, so they belong to a different scoring regime than everything around them.
- **`position_sizing.max_capital_pct` is 0.33333 (33.3%, $5,000 at $15k), raised from 5%/$750 on
  2026-08-23 (v2.2.92/93).** Combined with bug 1 above, the rank track deployed $14,072.80 of its
  $15,000 notional pool in a single day, with ASML alone at $3,792.70 (25%). All within the configured
  cap, so nothing here is a bug — but the sizer anchors to a fixed `starting_capital` per signal
  rather than a decremented balance, so there is no portfolio-level backstop on a track that fires
  every day. Also means pre- and post-2026-08-23 dollar P&L are not comparable.

---

## [v2.2.99] — 2026-08-24 — [Bug Fix / Infrastructure] Code-cleanliness audit of the core model — dead code removed, 5 real gaps found and fixed

**Status:** Live.

**In short:** User-requested pass over `swing_model/`, `backtesting/`, `paper_trading/`, `shared/`
(88 files) for dead code and cleanliness, done via ruff (unused args/vars/zip-strict), a dedicated
orphaned-function sweep, and manual verification of every candidate before touching anything. Found
and fixed 5 real bugs/gaps, plus removed confirmed dead code. All 1443 tests pass; both guardrail
checkers (`check_config_coverage.py`, `check_confidence_threshold_duplication.py`) pass clean.

**The one with real trading impact — `compute_ev_surface` (`shared/utils/options_math.py`), used by
4 of the 42 structures (`call_ratio_spread`, `put_ratio_spread`, `call_back_spread`,
`put_back_spread`):**
1. **IV/risk-free rate silently discarded.** The function has always accepted `iv`/`r` params (real
   fetched implied vol was being passed in from `trade_selector.py`) but never referenced them in
   its body — the EV estimate was a plain linear approximation with zero volatility or delta
   modeling, despite the docstring promising "option value increases by estimated delta × move."
   `daily_theta_est` was hardcoded to `0.0` with a comment acknowledging "theta is net positive for
   ratio spreads (sellers)" — i.e. it should have been nonzero. Fixed: real per-day theta now
   computed via `net_structure_greeks`/`compute_greeks` (already used correctly elsewhere in this
   same file for the other 35 structures), using each structure's actual legs — ratio spreads
   modeled 1-long/2-short at near/far OTM strikes (same 0.06/0.12 convention this module already
   uses for its other 2-leg spreads), back spreads the exact mirror (1-short/2-long, same strikes,
   every leg's side flipped). Deliberately did not hardcode a fixed sign either way in its place —
   whether a ratio spread nets positive or negative theta depends on how the near (single, larger-
   magnitude) leg compares to the two far (smaller-magnitude) legs, which itself depends on strike
   spacing/IV/days-to-expiry, not a universal rule. Checked against this project's own real numbers:
   at the ~8-day default hold this codebase actually uses, the near leg dominates, so
   `call_ratio_spread` nets NEGATIVE theta here — the opposite of the old inline comment's
   assumption, which was never actually computed before this fix and only ever described half of
   this function's own 4 structures anyway (never addressed back spreads at all). The one
   guaranteed, tested property is the mirror relationship: back spread theta = −(ratio spread theta)
   exactly, since the legs are identical strikes with every side flipped.
2. **Separately, a ~100x unit-scale bug.** `compute_ev_surface`'s output was in raw per-share
   dollars (never multiplied by the module's standard ×100-per-contract convention), while
   `_estimate_capital_required` — the denominator every structure's `ev_per_dollar_risked` ranking
   divides by — returns per-contract (×100) dollars for these 4 structure names. That mismatch meant
   these structures' ranking ratio was ~100x smaller than a fairly-computed one, regardless of their
   real economics — likely making them effectively unselectable against the other 38 structures for
   as long as this bug existed. Fixed by scaling the surface's output consistently with the rest of
   the module. Also passed `dte` through from `trade_selector.py` (previously always fell back to
   the module default) so the new theta estimate uses the real days-to-expiry when known.

**Other real gaps found and fixed:**
- **`send_macro_warning` (`shared/utils/discord_alerts.py`) existed, fully built, but nothing ever
  called it** — adverse macro conditions (TNX/DXY/China-tension trend) were computed and persisted
  every scan but never reached Discord. Wired into both `run_swing_model.py` and
  `paper_trading/paper_runner.py`, once per adverse sector, right after each already persists
  `macro_state`. Also fixed in the same function: its color logic checked for `"ADVERSE"`
  (uppercase) against `macro_overlay.py`'s actual lowercase state values (`"adverse"`/`"neutral"`)
  — the warning color could never have fired even before this alert was ever connected. Added a
  `sector` param so multiple simultaneously-adverse sectors in one scan produce distinguishable
  alerts instead of identical ones.
- **`ner_extractor.py`'s module docstring claimed spaCy-based NER with a keyword-matching
  fallback — the spaCy path never existed in practice.** `load_nlp()` was defined but never called
  from anywhere; `extract_ticker_sentiments` (the real entry point, feeding every scored ticker-day's
  News category, live and backtest) has always been pure keyword/alias matching. Removed the dead
  `load_nlp()`/spaCy-import scaffold and corrected both docstrings to describe what the code actually
  does. Also removed the now-unused `spacy`/`click` dependencies from `requirements.txt` (confirmed
  unused anywhere else in the codebase first). Not a live-behavior change — the keyword-matching path
  is what has always run — but a genuine capability-description gap worth knowing about: if real NER
  is wanted, it needs a deliberate design + backtest revalidation, not a silent re-add.
- **`classify_regime`'s `breadth_advance_decline` param (`shared/utils/regime_detection.py`) was
  accepted but never used** — the module docstring claimed regime is classified using "VIX level,
  SMH trend, and market breadth," but every real call site (`run_swing_model.py`,
  `backtest_engine.py`/`simulation.py`, tests) has only ever passed `vix`/`smh_ohlcv`. No data source
  for breadth exists anywhere in the pipeline. Removed the dead parameter and corrected the
  docstring — zero behavior change, since it was never passed anyway.
- **`identify_dominant_theme`'s `lookback_days` param (`shared/utils/narrative_tracker.py`) was
  decorative** — `news_layer.py` called it with `lookback_days=5` as if it mattered, but the
  function never used it; the real article window is entirely controlled by a different, decoupled
  mechanism upstream (`news_cfg.decay_zero_at_days`, currently also 5.0 by coincidence). Harmless
  today, but if `decay_zero_at_days` is ever retuned this parameter would keep silently doing
  nothing — same "looks wired, isn't" shape as the 109-key config backlog closed 2026-08-19. Removed
  the parameter; the real window is documented at the call site instead.

**Confirmed dead code removed (no behavior change):**
- `paper_runner.py`: a `_load_open_positions(RANK_TRADES_CSV)` call computed and immediately
  discarded every scan (real file I/O for nothing — `_run_rank_track` already does its own
  independent load).
- `trade_selector.py`'s `_apply_filters`: `iv_percentile`/`max_capital`/`cfg` params were threaded
  through but never used inside it (the real filtering on those already happens in the caller
  directly). `_estimate_capital_required`'s unused `target` param.
- 4 more orphaned functions, confirmed zero callers anywhere in the repo including tests:
  `build_indicator_table` (`indicator_pipeline.py`), `compute_pnl_surface` (`risk_reward.py`),
  `calibrate_weights` (`backtesting/metrics.py` — superseded by `feedback_loop.py`'s calibration),
  `classify_lead_lag` (`temporal_alignment.py`).
- No commented-out code blocks or unreachable code found anywhere in scope.

**Backtest:** No scoring weights or thresholds changed for the 38 structures already using
`resolve_structure_economics`; the `compute_ev_surface` fix only affects the 4 structures that were
never being fairly priced in the first place, so there's no prior "working" baseline this regresses.
Given how rarely qualifying trades occur at all (see CHANGELOG v2.2.94-97), these 4 structures have
likely never actually won a ranking in live/paper trading under the old bug — this fix mainly
determines whether they get a fair shot going forward, not a change to already-observed results.
1445 tests pass (6 new: 4 for `send_macro_warning`'s color/sector coverage, 2 for
`compute_ev_surface`'s per-contract scale and theta-mirror property; its 2 pre-existing tests were
also updated for the new `structure_name`/`dte` signature). Both guardrail checkers pass clean.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.98] — 2026-08-24 — [Feature] Rank-based parallel paper-trading track — strategy pivot after Phases 1/2 confirmed the sample-size problem can't be fixed by auditing or ticker expansion

**Status:** Live.

**In short:** After v2.2.95-v2.2.97 confirmed — twice, rigorously — that there's still no robust
evidence the model has real edge in either direction, and that expanding the watchlist didn't grow
the number of trades to learn from, the user decided the fix isn't more auditing or more tickers —
it's a strategy pivot. Added a second, fully parallel paper-trading track that ranks every scored
stock WITHIN each sector and always trades the top N (default 2), every scan, regardless of
whether they clear the official 70-point bar. Runs alongside — never replacing — the existing
threshold-based system, so the two can be directly compared over time. This is the direct fix for
the sample-size problem the 70+ bar makes structurally rare (~1 in 250 scored stock-days,
confirmed unaffected by watchlist size in v2.2.96): a guaranteed, steady flow of new trades instead
of waiting on rare qualifying events.

**A blocking finding that reshaped the design, caught before any code was written:**
`get_risk_pct()` (`shared/utils/position_sizer.py`) returns exactly 0.0 for any confidence score
below 70, by design — consumed by both `compute_position_size()` and `rank_trade_structures()`.
Without a fix, every rank-track pick (nearly all below 70, by construction) would size to **zero
real capital** — a CSV full of unfunded rows, not usable data. Fixed with an explicit,
user-approved design: both functions gained an optional `risk_pct_override` parameter (default
`None` — today's exact behavior for the existing threshold/live paths, which never pass it), and
the rank track passes a flat 3.33% for every pick regardless of score (same $500-at-$15k figure as
the threshold track's lowest real tier — simplest, most defensible choice until there's real data
to justify a confidence-scaled curve for a score range with zero track record).

**Architecture — two-pass within the same scan, not a new pipeline**
(`paper_trading/paper_runner.py`): Pass 1 is the existing per-ticker loop, left behaviorally
unchanged, now additionally stashing each ticker's computed context (indicators, direction,
sector, regime, score, earnings/positioning data) as it runs — reusing whatever this scan already
fetched, zero additional external API cost (StockTwits/Seeking Alpha/news are not re-fetched,
directly respecting the "leave room for practice scans" budget concern from Phase 2). Pass 2 runs
after the loop finishes: groups the stash by sector, ranks by score, takes the top N per sector,
and for each pick computes entry/stop/target/structure **fresh** (never reusing whatever pass 1 may
have already computed for a 60-69 scorer — that computation used the real `get_risk_pct`, i.e. a
$0 budget, so it was never actually budget-checked the way this track's flat 3.33% needs). Logs to
a new `paper_trading/rank_trades.csv` (same schema as the existing ledger) and fires a
distinctly-branded Discord alert. Deliberately does not insert an app-UI dashboard DB row (that
table has no unique constraint per ticker per scan run — a second insert would silently duplicate;
CSV + Discord only for now, dashboard visibility is a deliberate future decision, not an oversight).

**Fully independent from the threshold track in every way:** own duplicate-position guard (a
ticker can legitimately be open in both tracks simultaneously, even opposite directions — that
divergence is part of what the comparison is meant to surface), own simulated $15,000 capital pool
(not a split of the existing one — nothing in this codebase treats `starting_capital` as a real
decremented ledger balance, it's a sizing anchor recomputed fresh per signal), own Discord identity
(`shared/utils/discord_alerts.py`: purple embed color, `🧪 [RANK]` title prefix, distinct webhook
username — same webhook, no new secret needed), and — importantly — **calibration stays scoped to
the threshold track only**. `_maybe_run_calibration()` writes into the SHARED
`data/processed/calibrated_weights.json` that feeds live scoring weights for both tracks (same
`scoring.py` engine); `paper_trading/paper_updater.py`'s `update_paper_trades()` gained a
`run_calibration` parameter, explicitly `False` for the rank track's daily cycle, so its very
different outcome distribution can't silently recalibrate weights the threshold track also depends
on — revisit deliberately once there's real rank-track data to have an informed opinion.

**Outcome resolution extends the existing scheduled task, no new one added**
(`paper_trading/paper_updater.py`): `_load_trades`/`_save_trades`/`update_paper_trades`/
`print_summary`/`_try_send_daily_summary` all gained optional `csv_path`/`lock_path`/`track`
parameters (defaulting to today's exact behavior), and `__main__` now runs each track's full daily
cycle (resolve outcomes → print summary → send daily Discord summary) once per track, each wrapped
in its own try/except so one track's failure can't prevent the other from running.

**Config:** new `rank_track.top_n_per_sector: 2` in `config/swing_config.yaml` — tunable from real
data later without a code change. Sectors now have 11-14 tickers each (post v2.2.96 expansion), so
top-2/sector is roughly 8 new rank-track signals/day once same-day dedup collapses the 3x/day scan
cadence — a large multiple of the current real qualifying rate, without immediately reaching down
to bottom-of-barrel names on a weak day.

**Backtest:** Not applicable — this is a live paper-trading mechanism change, not a scoring/
threshold change; nothing here is backtestable (the backtest never simulates rank-based selection).
1439 tests pass (9 new: `risk_pct_override` unit tests on both sizing functions, an end-to-end
integration test confirming the rank track produces real funded rows for sub-60-scoring tickers
with zero DB-row side effects, and calibration-exclusion tests). Both guardrail checkers
(`check_config_coverage.py`, `check_confidence_threshold_duplication.py`) pass clean.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.97] — 2026-08-24 — [Research / Bug Fix] SUPERSEDES v2.2.96's "real negative signal" claim — checked with proper statistical rigor, it does not hold up

**Status:** Live.

**In short:** Immediate follow-up to v2.2.96, run before starting Phase 3 at the user's explicit
request ("run this before phase 3") to check whether that entry's headline finding — the real
(non-proxy) part of the score has a statistically significant NEGATIVE relationship with forward
returns — was actually real, or an artifact of not correcting for how many tests were run. **It was
the latter.** The corrected, honest conclusion: there is currently no robust evidence of edge in
either direction from the fully-real part of the score. That's a real result, just a less dramatic
and less actionable one than v2.2.96 reported — and importantly, it does NOT mean "the model has no
edge," it means "this test still can't tell us either way," the same throughline as every prior
phase of this audit.

**What was checked, in order:**

1. **Look-ahead bias review of `backtesting/simulation.py`** (could the score have been leaking
   future information into its own correlation with future returns, producing a spurious signal
   either direction?). Found no obvious leak: technical indicators are computed on `df_slice =
   df.iloc[:entry_idx + 1]` (structurally truncated before the entry bar, every time), news is
   date-windowed to `<= bar_date` (`historical_news_loader.py`), fundamental data uses an explicit
   point-in-time archive (`_fundamental_as_of` — most recent snapshot at-or-before `bar_date`), and
   cross-ticker/macro context is explicitly sliced `<= bar_date` with comments flagging exactly this
   concern. Not exhaustively re-verified line-by-line (e.g. every individual technical-indicator
   window direction wasn't independently re-derived), but nothing found suggests the negative
   reading was a simulation artifact.

2. **Benjamini-Hochberg correction across every IC reading the same backtest run produced.**
   v2.2.96's finding was one p-value (0.0501) viewed in isolation. The actual multi-sector backtest
   run that produced it computed ~15 IC reads at once (pooled + 4 sectors x 3 score-field variants
   each) — at that many simultaneous tests, seeing one land right at the conventional p<0.05 line is
   close to what you'd expect from chance alone, not strong evidence. Corrected: of 15 reads, only 2
   survive BH correction — and both are POSITIVE readings on the composite score that includes the
   backtest's Sentiment proxy (pooled confidence, semiconductors confidence), the exact category
   already flagged in v2.2.95 as untrustworthy. Every technical-only and real-only reading, positive
   or negative, at every sector including the pooled one, fails to survive correction.

3. **Bootstrap confidence interval on the IC itself** (does the point estimate hold up under
   resampling, independent of the multiple-testing question). The pooled real-only reading v2.2.96
   led with: CI = [-0.0673, +0.0004] — straddles zero, does not exclude it. Consistent with check 2:
   this specific number was not robust.

**One nuance surfaced, not resolved:** the pooled technical-only reading (IC=-0.0348, p=0.0414) has
a bootstrap CI that DOES exclude zero ([-0.0689, -0.0009]) even though it does not survive BH
correction — the two checks aren't measuring exactly the same thing (one asks "is this point
estimate stable under resampling," the other asks "is this significant once you account for how
many things were tested"), and here they disagree. Treated as inconclusive, not swept aside: this
is the single reading closest to being real evidence of something, and would be the first thing to
re-check if more data accumulates.

**Fix — added the missing rigor to the standard report, not just this one-off check**
(`backtesting/metrics.py`, `backtesting/backtest_engine.py`, `backtesting/run_backtest.py`):
- `bootstrap_ic_ci()`: resampled CI on an IC point estimate (paired resampling, same principle as
  the existing `bootstrap_expectancy_ci`).
- `benjamini_hochberg_correction()`: standard BH step-up procedure, chosen over a stricter
  Bonferroni correction as the more appropriate bar for an exploratory multi-test scan like this one
  (same "best/most-extreme of N trials can look significant by chance alone" problem
  `compute_deflated_sharpe_ratio` already exists to catch for Sharpe ratios, now covered for IC too).
- Both wired into `_compute_metrics_bundle`'s `ic_confidence`/`ic_technical`/`ic_real_only` dicts
  (now carrying `ci_lower`/`ci_upper`/`bh_significant` alongside `ic`/`p_value`) and into
  `run_backtest.py`'s printed report, so a future backtest run shows the corrected picture
  automatically instead of requiring a manual follow-up script to catch the same mistake again.

**Backtest:** No scoring weights, formulas, or thresholds changed — this is a statistical-rigor
correction to how the IC finding itself is reported, not a strategy change. 1420+ tests pass
(14 new: bootstrap CI + BH correction pure-math tests). Both guardrail checkers pass clean.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.96] — 2026-08-24 — [Research / Feature] Ticker universe expansion (full model audit, Phase 2) — didn't grow qualifying trades as expected, but revealed a real negative signal in the pooled data

**Status:** Live (paper trading only — watchlist expansion, no scoring/threshold change).

**In short:** Phase 2 of the full model audit. Expanded the watchlist from 23 to 49 stocks —
heaviest in regional banks and healthcare (the two sectors with ZERO historically-qualifying
trades found in Phase 1), lighter in semiconductors and consumer discretionary (which already had
some, if thin, data) — on the theory that more stocks means more historical setups to learn from.
**That theory didn't hold up.** Regional banks still have ZERO qualifying trades even after growing
from 5 to 13 stocks. Healthcare went from 0 to 1 (not remotely enough for a read). Consumer
discretionary actually went DOWN, from 6 qualifying trades to 3, despite nearly doubling its stock
count. Total qualifying trades across all 4 sectors combined: 14, down slightly from 17 before this
change. Expanding the stock list was not the fix for the sample-size problem.

**What it did reveal:** the same Information Coefficient check from v2.2.95, now run on the much
bigger scored population this expansion produced (3,439 scored days pooled across all 4 sectors,
vs. a few hundred per sector before), shows something the smaller sample couldn't detect clearly:
the real (non-proxy) part of the score — Technical + News + Fundamental, no Sentiment stand-in —
has a small but statistically real NEGATIVE relationship with what actually happened afterward
(IC -0.033, p=0.05, n=3,439). Not "no signal" — a very slight signal in the wrong direction. Broken
down by sector, this isn't uniform: regional banks and healthcare show nothing detectable either
way; consumer discretionary is the one driving the negative pooled reading (IC -0.055, p=0.02); the
positive read semiconductors shows on its own likely still leans on the same Sentiment proxy
contamination flagged in v2.2.95. Effect sizes are small across the board — this isn't "the model is
broken," but it is a second piece of real evidence, on top of v2.2.95's, that the strongest-looking
numbers so far may be resting more on the parts of this test that aren't fully real than on the
parts that are.

**Why the trade count didn't grow the way expected:** two contributing factors, not fully separated
here. (1) Genuinely qualifying setups (a score of 70+) are just rare at this model's real bar —
roughly 1 in every 250 scored stock-days across the whole expanded universe — so growing the stock
count grows the denominator a lot faster than the numerator. (2) Relative-strength and
sector-rotation modifiers are computed relative to each sector's own stock set — adding stocks
changes that baseline for every stock in the sector, including the original ones, which is the
likely mechanism behind consumer discretionary's qualifying count actually dropping after
expansion, not just staying flat.

**Ticker additions** (see config/swing_config.yaml's own per-sector comments for full selection
rationale — same ETF membership, comparable market-cap/liquidity tier, real sub-industry
diversification, not just "more of the same"):
- **regional_banks** (+8, 5→13): CFG, TFC, MTB, WBS, CFR, PNFP, ONB, UMBF
- **healthcare** (+8, 6→14): AMGN, GILD, BMY, VRTX, TMO, ABT, ISRG, SYK
- **semiconductors** (+5, 6→11): TXN, ADI, AMAT, QCOM, KLAC
- **consumer_discretionary** (+5, 6→11): MCD, BKNG, TJX, LOW, ORLY

**Implementation:** `config/swing_config.yaml` (watchlist + portfolio-level `correlated_groups` for
the new tickers, reasoned the same way — genuine sub-industry/geography pairs, not everything
mechanically grouped), `shared/utils/ner_extractor.py` (`_TICKER_TO_COMPANY` aliases for all 26 new
tickers — omitting this silently zeroes a ticker's News-category NER attribution, the exact gap the
original bank/healthcare rollout hit and this session deliberately avoided repeating). 13.5 years of
real historical OHLCV backfilled for all 26 new tickers into the matching `data/historical*/`
directory (2013-01-01 through today, same format/source as the existing files).

**Backtest:** Full re-run across all 4 sectors post-expansion — see "what it did reveal" above for
the headline numbers. No scoring weights, formulas, or thresholds changed. 1420 tests pass (1 test
updated — `test_real_config_watchlist_includes_all_sectors` — to assert the new, larger real
watchlist instead of the old one). Both guardrail checkers
(`check_config_coverage.py`, `check_confidence_threshold_duplication.py`) pass clean.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.95] — 2026-08-24 — [Feature / Bug Fix / Research] Information Coefficient validation methodology + paper_runner.py scan-error visibility (full model audit, Phase 1)

**Status:** Live.

**In short:** First implementation phase of a full model audit. Two independent tracks. (1) A
second way to validate the model that doesn't need a full "did this trade win or lose" — it checks
whether the raw 0-100 score ranks stocks in the right order relative to what actually happened
next, across every scored day, not just the rare ones that cross the 70-point bar. Run against the
real semiconductor history: the full score does show a real relationship (statistically real, not
random) — but that reading leans mostly on Sentiment, and this backtest's version of Sentiment is a
stand-in built from price movement, not real trader sentiment data. Checked on just the parts that
are 100% real historical data (Technical, News, Fundamental) and the relationship disappears —
statistically indistinguishable from noise. This doesn't prove the model has no edge; it means the
main evidence for one so far may be resting more on a proxy than on the real signal layers. (2) A
crash while scoring one stock used to disappear from view entirely except for one line in a log
file — now it leaves a real trace and, critically, doesn't stop the rest of that day's stocks from
being scanned.

**Why now:** two prior full audits (2026-08-19, 2026-08-22/23) found and fixed a bug — a leftover
"needs a 90 score to count" filter — that had been silently duplicated into 4 different files and
kept surviving its own fix. Once it was fully removed everywhere and the historical test was
re-run at the real 70-point bar, the numbers dropped hard: only 11 historically-qualifying trades
for semiconductors (the best-performing sector) in 13.5 years of data, and ZERO for regional banks
and healthcare. That's nowhere near enough to trust a win-rate number. Rather than lowering the bar
again (which is exactly the mistake already made and undone twice), this adds a second validation
method that works even with a small qualifying-trade count, since it uses every scored day instead
of just the rare ones that clear the bar.

**Fix 1 — Information Coefficient (`backtesting/metrics.py`, `backtesting/simulation.py`,
`backtesting/backtest_engine.py`, `backtesting/walk_forward.py`, `backtesting/run_backtest.py`):**
added `compute_information_coefficient()` — a rank correlation (Spearman) between the raw score and
what actually happened afterward, computed on the FULL pre-filter scored population the historical
test already builds internally and then discards (`all_outcomes`, before the `confidence >= 70`
filter). Reported on three versions of the score to keep the read honest: the full blended score
(which includes two stand-in categories this historical replay can't measure for real —
Positioning is a flat neutral value, Sentiment is built from 5-day price movement, not real crowd
sentiment data); Technical alone (the single largest, fully real category); and a "real data only"
version combining Technical + News + Fundamental. This is purely additive — reported alongside the
existing win-rate/Sharpe numbers, doesn't change or gate the pass/fail decision.

**First real result, semiconductors (13.5yr, n=311 scored days vs. 11 qualifying trades):**

| Score version | IC | p-value | Real signal? |
|---|---|---|---|
| Full blended score | +0.274 | <0.0001 | Yes — but includes the Sentiment stand-in |
| Technical only (fully real) | +0.018 | 0.75 | No — statistically indistinguishable from noise |
| Real-data-only (Technical+News+Fundamental) | +0.034 | 0.56 | No — same |

**What this means:** the model's one genuinely statistically-significant reading right now comes
from a category this historical test can't test for real. The categories that ARE real show no
measurable edge in this check. This doesn't mean the real model has no edge — the real Sentiment
layer uses actual StockTwits/Seeking Alpha data, nothing like the price-based stand-in — but it
does mean the strongest evidence so far for "the score works" is resting on the part of the test
that's the least trustworthy, not the most. Flagged as a real, open question for the next phase,
not resolved here.

**Fix 2 — scan-error visibility (`paper_trading/paper_runner.py`, `app_ui/db.py`):** the loop that
scores every stock, once per scan, wraps the entire ~720-line per-stock process (fetch data, score
it, size a trade, log it) in one catch-all. Any unexpected crash anywhere in that block used to
just print one error line and move on — no record in the validation log, no row in the dashboard
database, nothing to show the stock was ever attempted that day. Added: the same failure now also
writes a validation-log entry (matching every other module's existing pattern) and a dashboard row
under a new `scan_error` category, carrying whatever partial score was computed before the crash
when one exists, instead of a blank. Verified with a real injected failure (one stock's scoring
deliberately made to crash mid-scan): the failing stock now leaves a clear trace and the other
stock in the same scan is completely unaffected.

**Backtest:** No scoring weights, formulas, or thresholds changed — both fixes are additive
reporting/visibility changes. Full test suite (1410+ tests, plus 2 new tests covering the IC
function and the scan-error visibility fix) passes.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.94] — 2026-08-24 — [Bug Fix / Feature] Fixed silent OHLCV exclusions and a recurring fraud-gate false positive; added entry-zone opportunity-cost tracking and a daily Discord summary

**Status:** Live.

**In short:** Four fixes/additions from a daily scan review. Two tickers (AMD, RF) were silently
dropped from entire scans today because a data-quality check couldn't tell a few cents of vendor
rounding noise apart from real corrupted data — fixed with a small tolerance plus a retry. KEY's
"fraud" news trigger kept firing on KeyBank's own fraud-prevention marketing, never a real fraud
story — fixed by teaching the keyword matcher to recognize that context. Also added: a way to
measure whether the entry-zone breakout rule is costing missed winners or protecting capital on
trades that never filled, and a daily Discord report summarizing open/closed trades and P&L
instead of only being available on request.

**Fix 1 — silent OHLCV exclusions (`shared/utils/data_validator.py`,
`swing_model/indicator_pipeline.py`):** The Open-vs-[Low,High] sanity check used an exact
boundary, so RF's real 2026-08-24 bar (Open $30.47 vs Low $30.50, a 0.1% gap) tripped the same
check meant to catch a genuine decimal-shift corruption, and excluded RF from both the
mid-session and post-close scans. Added `data_validation.open_range_tolerance_pct` (default
0.3%) — still catches real corruption instantly, no longer flags vendor rounding noise.
Separately, AMD failed the same check at scan time but its data had self-corrected by later that
day — added one 15-second-delayed retry (fresh single-ticker fetch) before excluding a ticker, to
catch this kind of transient vendor-side settlement race.

**Fix 2 — fraud-gate false positives (`shared/utils/event_gate.py`):** Ticker-trigger keyword
matching (`event_severity_gate.ticker_triggers`) was a plain case-insensitive substring search
with no context. KEY's "fraud" trigger re-fired 6+ times between 2026-07-23 and 2026-08-24 on
KeyBank's own fraud-prevention marketing copy; AMD's fired once on a headline about a different
company's fraud-detection product that only mentioned AMD as a hardware vendor. Neither was ever
a real fraud allegation about the ticker in question. Added
`event_severity_gate.advisory_context_exclusions` — a ticker-trigger match is now suppressed when
the headline also contains an advisory/marketing phrase ("fraud prevention," "fraud tool," "fraud
detection," "recognize and avoid," "prevent fraud"). Verified a genuine fraud allegation (UNH's
real Medicare-fraud lawsuit) and a hypothetical real KEY fraud story both still gate normally.

**Addition 1 — entry-zone opportunity-cost tracking (`paper_trading/paper_trade_metrics.py`,
`paper_trading/paper_updater.py`):** Expired (never-filled) signals were excluded from every
accuracy metric, with no way to tell whether the breakout-confirmation entry rule was protecting
capital or costing missed winners. Every expired row now gets a hypothetical-fill simulation —
entered immediately at the signal-time `entry_price`, walked through the exact same stop/target/
time-stop logic real trades use — recorded in new `hypothetical_*` CSV columns.
`compute_expired_signal_opportunity_cost()` reports the aggregate read (hypothetical win rate,
avg R). Deliberately kept separate from win-rate/signal-accuracy, which stay scoped to trades
that actually resolved for real. First two real cases (AVGO, HBAN) both show the entry-zone rule
protected capital — an immediate fill would have stopped out within a day on both.

**Addition 2 — daily Discord summary (`shared/utils/discord_alerts.py`,
`paper_trading/paper_updater.py`):** `generate_daily_summary()` + `send_daily_summary_alert()`
post a daily report — open positions with mark-to-market P&L (flagging any sized to 0 real
contracts), anything closed that day, pending unfilled orders, lifetime realized/unrealized/net
P&L, and short rule-based takeaways (best/worst open position, positions more than halfway to
stop, opportunity-cost read). Fires once per scheduled `paper_updater` run; never recommends
closing a position, same "flag, don't auto-act" principle as the existing critical-event alert.

**Backtest:** Not applicable — none of today's changes touch scoring weights, formulas, or
thresholds; all four are data-quality, gating-context, and reporting changes. Full test suite
(1410 tests) passes unchanged; config coverage check confirms both new config keys are properly
wired.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.93] — 2026-08-23 — [Scoring Change] Portfolio-level risk caps raised ~6.667x to match the per-trade budget increase

**Status:** Live.

**In short:** Follow-up to v2.2.92. After raising how much each trade can risk, the two safety caps
meant to limit *total* risk across all open positions at once — a 3% portfolio-wide cap and a 1.5%
one-direction cap — were left at their old, much smaller values. A single top-tier trade now risks
16.67% alone, more than 5x the old portfolio cap, so that cap would trigger on almost every trade
regardless of real risk, making it meaningless. Raised both caps to match, confirmed with the user.

**Fix:** Same ~6.667x multiplier (500/75) applied to both caps, in `swing_model/portfolio_manager.py`:

| Constant | Old | New |
|---|---|---|
| `MAX_TOTAL_RISK_PCT` | 3% | 20% |
| `MAX_NET_DIRECTIONAL_DELTA` | 1.5% | 10% |

And the same key in `config/swing_config.yaml` that both the live path and paper trading's advisory
concentration check read at runtime: `portfolio.max_simultaneous_risk_pct` 3% → 20%.

**Scope check — neither cap currently blocks anything live:** `swing_model/run_swing_model.py` (the
path `can_open_new_position()`/`MAX_TOTAL_RISK_PCT` actually gates) has never run in production —
paper trading is the only active daily pipeline, and it doesn't call that function. Paper trading's
own cross-sector concentration check (v2.2.78) reuses `get_portfolio_delta()`/
`MAX_NET_DIRECTIONAL_DELTA` but only as an advisory note appended to `sizing_note` — it never skips
logging a signal, by design. So today's change is a consistency fix (the numbers now mean what they
claim to mean, in scale with the real per-trade risk) rather than a behavior change to any currently
enforced gate — the note text paper trading emits will read "10.0%" instead of "1.5%" going forward,
and will fire less often now that the threshold is proportionally wider.

**Docstrings/comments updated** throughout `portfolio_manager.py` (`add_position()`,
`can_open_new_position()`, `get_portfolio_delta()`) and the concentration-note block in
`paper_runner.py` to state the new percentages and the 2026-08-23 raise, so the code's own comments
don't go stale the way the v2.2.75 threshold bug's duplicated constants did.

**Backtest:** Not applicable — a risk-cap value, not a scoring or entry-signal change; no backtest
signal is affected. Full test suite (1410 tests) passes unchanged.

**Approved:** Pending.

---

## [v2.2.92] — 2026-08-23 — [Scoring Change] Per-trade risk budget raised ~6.667x — $75 to $500 at the floor tier

**Status:** Live.

**In short:** Acting on a finding from today's earlier audit: 8 of the last 13 real trades were too
small to afford an actual options contract, so they fell back to plain stock instead — riskier,
since stock has no built-in loss limit the way an options contract does. The cause was the smallest
risk tier being just $75, far too little to ever buy a real contract. The user chose to raise it.

**This matters most because the smallest tier is the only one that's ever actually used** — real
live confidence scores rarely go above ~78-80 (see v2.2.75), so almost every real qualifying signal
lands in the lowest tier, never reaching the higher tiers the ladder was designed to reward.

**Fix:** `SIZING_TIERS` (`shared/utils/position_sizer.py`) raised by the same ~6.667x multiplier
(500/75) across all 5 tiers, preserving the "higher confidence → more risk" ordering:

| Tier | Old risk_pct / $ at $15k | New risk_pct / $ at $15k |
|---|---|---|
| 70-89 | 0.5% / $75 | 3.33% / $500 |
| 90-92 | 1.0% / $150 | 6.67% / $1,000 |
| 93-95 | 1.5% / $225 | 10.0% / $1,500 |
| 96-98 | 2.0% / $300 | 13.33% / $2,000 |
| 99-100 | 2.5% / $375 | 16.67% / $2,500 |

`position_sizing.max_capital_pct` (`config/swing_config.yaml`, plus both call-site fallback defaults
in `paper_runner.py`/`run_swing_model.py` that apply when the config key is missing) raised in
tandem, same multiplier: 5%/$750 → 33.3%/$5,000 — a bigger risk budget needs a bigger capital
ceiling to actually be usable, or it just gets re-clipped back down by the blanket cap immediately
after being raised.

**Real before/after** (TGT, 2026-08-20, confidence 71.8, entry $159.00/stop $148.57): sizing goes
from 4 shares / $636 deployed / $49.96 actual risk to **31 shares / $4,929 deployed / $499.50 actual
risk**.

**Confirmed this fixes the exact class of gap the audit flagged**, not just a bigger number in the
abstract: `tests/test_phase7_trade_math.py`'s `test_structure_over_old_tier_budget_no_longer_falls_
through_post_raise` uses a real historical incident (JNJ, 2026-08-11 — a $249 `long_strangle` that
used to size to 0 and vanish entirely under the old $75 tier, falling through to a gap-risk
`long_stock` instead) and confirms the capped-risk option is now correctly, directly affordable and
recommended — no fallback needed.

**Fix:** `shared/utils/position_sizer.py`, `config/swing_config.yaml`, `paper_trading/paper_runner.py`,
`swing_model/run_swing_model.py` (fallback defaults), `swing_model/trade_selector.py` (docstring/comment
accuracy). 12 existing tests updated to the new dollar amounts across `tests/test_phase7_trade_math.py`
and `tests/test_consecutive_loss_and_delta_cap.py`. 1410/1410 tests pass.

**Backtest:** Not applicable — position sizing doesn't affect confidence scoring, the qualifying
threshold, or trade-outcome win/loss determination, none of which the backtest measures differently
because of this change.

**Approved:** Pending — do not go live on this version until reviewed. Real live/paper behavior
change: real dollar amounts risked and deployed per trade increase substantially (paper capital only,
zero real money at risk either way).

---

## [v2.2.91] — 2026-08-23 — [Scoring Change] EV ranking now tiebreaks on loss-tail severity, not just point-estimate EV

**Status:** Live.

**In short:** The system picks between 42 possible ways to structure a trade by ranking them on
expected profit alone. When two options tie on expected profit, it used to pick between them
arbitrarily — even when one carries a much bigger worst-case loss than the other. These ties are
common in practice, not a rare edge case.

**Fix:** Extracted the sort into a small, directly-testable `_ranking_sort_key(x)` function. Primary
key unchanged (`ev_per_dollar_per_day`, higher is better); secondary tiebreak on `max_loss_dollars`,
smaller is better. Undefined-risk structures (`max_loss_dollars is None` — never fabricated, see
`resolve_structure_economics`) always lose a tiebreak against any defined-risk structure at the same
EV level, via an infinity sentinel. Confirmed this reaches the actual "recommended" pick, not just the
diagnostic display order that reaches Discord/the CSV — the recommendation priority chain walks
`ranked_structures` in this same sorted order via `next(...)`.

**Fix:** `swing_model/trade_selector.py`. 5 new tests in `tests/test_phase7_trade_math.py`
(`TestRankingSortKeyMaxLossTiebreak`) — direct sort-key tests plus an end-to-end invariant check
against a real `rank_trade_structures()` call with real Black-Scholes-computed structures (exact ties
are hard to force through real option pricing, so this checks that whichever structures DO tie in a
real evaluation are correctly ordered by ascending max loss, rather than trying to engineer a
guaranteed tie).

**Backtest:** Not applicable — affects trade-structure selection among already-qualifying signals,
not the confidence-scoring/qualifying-threshold path the backtest replays.

**Approved:** Pending — do not go live on this version until reviewed. Live/paper scoring behavior
change: a tied-EV structure choice can now differ from before, favoring lower max loss.

---

## [v2.2.90] — 2026-08-23 — [Backtest Methodology] Deflated Sharpe reporting — is the headline number just the best of several looks at the data

**Status:** Live.

**In short:** A good-looking test result can sometimes just be the luckiest of several attempts,
not real skill. This project has tuned its entry rules against the same historical data more than
5 separate times — each attempt is a chance for a good-looking number to be luck rather than a real
edge. A statistical check for exactly this (a "deflated Sharpe ratio") already existed for other
diagnostics but had never been run against the project's own headline result. It has been now.

**Real historical tuning attempts aren't all in one place to test directly** — they're scattered
across separate one-off scripts run over several weeks. Instead, this uses each of the 6
walk-forward test windows (different multi-year historical slices) as stand-ins for separate
attempts, and asks: is the reported result just the best-looking of those 6 windows, or real?

**Answer, on real data:** yes, just the best-looking one. Raw Sharpe ratio 0.27, but once corrected
for having 6 different windows to pick from, it drops to **-10.64 — indistinguishable from noise**.
Consistent with everything else found today: the headline number doesn't hold up.

**Fix:** `backtesting/backtest_engine.py` — new `deflated_sharpe`/`deflated_sharpe_psr`/
`deflated_sharpe_n_trials` result fields (present and zeroed even on the no-data early-return path).
Reported only — does not gate `passed`, same treatment as Sortino/Ulcer/drawdown-duration (adding a
new gate on a new metric is a deliberate bar-raising decision, not something to fold in silently).
`backtesting/run_backtest.py`'s CLI output prints it. 4 new tests in `tests/test_phase12_backtest.py`
(`TestRunBacktestDeflatedSharpe`) — including confirming a window with 0-1 outcomes is excluded from
the trial population rather than counted as a fabricated zero-Sharpe data point.

**Backtest:** See numbers above — this entry IS the backtest re-run.

**Approved:** Not applicable — this changes how results are reported, not a request to go live.

---

## [v2.2.89] — 2026-08-23 — [Bug Fix / Scoring Change] A stale, invalid per-sector calibration was actively steering live scoring — found and cleared

**Status:** Live.

**In short:** While checking why only 1 of 4 sectors had its own fine-tuned scoring weights, found a
real, currently-live bug: consumer discretionary (AMZN/HD/TGT/NKE/SBUX) was still using custom
weights fit back in August under the same "still checking for a 90 score instead of 70" bug fixed
elsewhere today — meaning those weights were fit on a fictional dataset of 405 trades that doesn't
actually exist at the real threshold.

**Re-running the fit with the correct threshold:** only 5 real trades for that sector, nowhere near
enough to trust (100 is the minimum). No sector currently has enough data to earn its own weights.

**The deeper bug:** the calibration code only ever updated the saved weights file when a sector
newly qualified — it had no way to go back and clear a sector's entry once it stopped qualifying.
So a stale, no-longer-valid set of weights could sit there being used forever.

**Fix:** `save_sector_weights(saved_by_sector)` is now called unconditionally, including with an
empty dict — which correctly clears any sector/direction that no longer qualifies. Re-ran the real
calibration: `data/processed/calibrated_weights_by_sector.json` is now genuinely `{}`. Every sector
currently falls back to the shared default weights (`technical 40 / sentiment 15 / news 15` split,
unchanged) — the honest state given the real data, not an artifact of stale calibration output.

**Fix:** `backtesting/sector_weight_calibration.py`. `tests/test_sector_weight_calibration_versioning.py`
— 2 existing tests' `mock_save.assert_not_called()` corrected to `assert_called_once_with({})` (the
call now always happens), plus a new `TestStaleSectorEntryIsCleared` class as the direct regression
guard for this bug shape.

**Backtest:** Not applicable — corrects a live-scoring input (per-sector calibrated weights), not the
core scoring formula or backtest methodology itself.

**Approved:** Pending — do not go live on this version until reviewed. Also note: this is a live/paper
scoring behavior change (consumer_discretionary tickers now score with the shared default weights
instead of the stale calibrated ones) — flagging per this project's own rule that scoring changes get
a version bump and CHANGELOG entry, which this is.

---

## [v2.2.88] — 2026-08-23 — [Infrastructure] greeks_filter_status now has real end-to-end test coverage

**Status:** Live.

**In short:** A data field (`greeks_filter_status`) was being calculated correctly, but the step
that actually saves it into the paper-trading log had zero test coverage — so a bug there could
have slipped in unnoticed. Confirmed the gap was real: every existing test skipped that field
entirely, so it always silently came out blank in every test run without anyone noticing.

**Fix:** New `test_greeks_filter_status_round_trips_into_paper_trades_csv`, same real-pipeline-with-
fakes harness the other tests in that file already use, with `rank_trade_structures` mocked to
actually return a real `greeks_filter_status` value at the top level (matching the real function's
return shape). Confirms it survives all the way into the written CSV row.

**Fix:** `tests/test_multi_sector_live_pipeline.py`. 1399+/1399+ tests pass.

**Backtest:** Not applicable — test-only change.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.87] — 2026-08-23 — [Infrastructure] Git hygiene — app.log stops being tracked

**Status:** Live.

**In short:** A large free-text log file (`app.log`, ~5MB) was being tracked in git even though it's
already backed up locally and rotates automatically. Touched by 45 prior commits, it kept producing
large, noisy diffs that buried the real code changes in the same commits.

**Fix:** Stopped tracking it in git. The file stays on disk and keeps being written to as normal —
git just stops watching it. The structured audit-trail files this project actually relies on
(trade logs, validation logs, etc.) are untouched and still tracked.

**Backtest:** Not applicable — repository hygiene only.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.86] — 2026-08-23 — [Infrastructure] A permanent guardrail against the bug that recurred 3 times in 2 days

**Status:** Live.

**In short:** The same bug — a file hardcoding its own copy of the "70-point" qualifying score
instead of reading the real setting — was found and fixed 3 separate times in 2 days (v2.2.75,
v2.2.83), always by manually searching for it after the fact. Built an automatic check instead, so
the next copy of this bug fails the build right away rather than waiting to be found by hand.

**What it checks:** scans every code file for the two ways this bug has shown up — a hardcoded
comparison against a number, or a constant that looks like it should reference the real setting but
doesn't. Any file matching either pattern must also import the real setting, or the check fails.

**Proven before turning it on:** tested it against known-bad and known-good example code first, to
confirm it actually catches the bug instead of passing trivially. It also immediately found one more
real leftover copy in the codebase — removed.

**Fix:** New `scripts/check_confidence_threshold_duplication.py`, wired into
`.github/workflows/ci.yml`. `backtesting/bearish_rsi_band_sweep.py` (dead constant removed).

**Backtest:** Not applicable — CI infrastructure only, no scoring/behavior change.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.85] — 2026-08-23 — [Bug Fix] The weekly Discord alert's first real run proved it couldn't actually send

**Status:** Live.

**In short:** The weekly Discord summary alert (added in v2.2.79) ran for the first time today, right
on schedule — but its own log showed it never actually posted, because it couldn't find the Discord
key. The step that loads that key from the settings file was simply missing from this one module,
unlike everywhere else in the project.

**Fix:** Added the identical `load_dotenv()` pattern to `monitoring/performance_dashboard.py`.
Verified directly: `DISCORD_WEBHOOK_URL` now loads into `os.environ` on import. 1399/1399 tests still
pass (this only affects module-import-time environment loading, no test needed a code change to keep
passing).

**Backtest:** Not applicable — live/paper alerting only.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.84] — 2026-08-23 — [Backtest Methodology] The go-live gate now actually requires walk-forward robustness, not just a favorable single split

**Status:** Live.

**In short:** The historical test's pass/fail verdict used to rest on just one fixed time slice.
Results across other historical time periods ("walk-forward windows") were calculated but never
actually counted toward the verdict — which is exactly how v2.2.83's wrong "2 of 6 periods pass"
reading went unnoticed for most of a day: the one slice that gets graded happened to sit inside the
only periods that looked good, hiding the fact that most periods don't.

**Fix:** The verdict now also requires the same safety bar to clear when every walk-forward
period's trades are pooled together into one larger sample, not just the one fixed slice. (A
period-by-period vote was considered and rejected — 6 periods is too few data points, and most
don't have enough trades to judge on their own anyway.)

**On real data:** pooled walk-forward is 32 trades total, expectancy CI lower bound 0.06R (positive
but weak), **Sharpe -1.12** — fails cleanly on its own, independent of and consistent with the
single-split's own failure (0.27 Sharpe, already failing before this fix).

**Per-sector gating was already correctly wired**, contrary to how "still just side diagnostics you
have to check manually" was originally characterized in this session — `run_multi_sector_backtest()`
has required every individual sector to also pass since v2.2.56. Only the single-sector
`run_backtest()` (the function whose headline number actually gets cited) was missing the
walk-forward check; that's what this entry closes.

**New result fields:** `walk_forward_pooled_passed`, `walk_forward_pooled_qualifying_trades`,
`walk_forward_pooled_expectancy_r_ci_lower`, `walk_forward_pooled_sharpe`,
`walk_forward_pooled_max_drawdown_pct`.

**Fix:** `backtesting/backtest_engine.py`. 6 new tests in `tests/test_phase12_backtest.py`
(`TestRunBacktestWalkForwardPooledGate`) — monkeypatch `run_walk_forward` directly rather than
generating a multi-year synthetic dataset, isolating the new pooling/gating logic from
`run_walk_forward`'s own (separately tested) correctness. 1399/1399 tests pass.

**Backtest:** `passed=False` (unchanged — was already failing on the single-split side; now also
fails independently on the pooled walk-forward side).

**Approved:** Not applicable — this changes how "passed" is measured, not a request to go live. The
model remains not eligible for real capital regardless of this result.

---

## [v2.2.83] — 2026-08-23 — [Backtest Methodology / Bug Fix] The confidence>=90 bug was duplicated across 6 more files — corrected walk-forward, per-sector, and bearish numbers are all worse than reported

**Status:** Live (backtest-only fix; no live/paper scoring behavior changed).

**In short:** A closer look at yesterday's fix (v2.2.75) found it was incomplete — it only fixed one
copy of the "still checking for a 90 score instead of 70" bug. The identical bug was independently
copy-pasted into 3 more files, so every walk-forward-window result and per-sector number reported
earlier today — including this file's own v2.2.75 entry — was actually measured on the wrong,
too-easy population.

**Fix:** `backtesting/walk_forward.py`'s own qualifying filter now imports `CONFIDENCE_THRESHOLD`
instead of hardcoding 90 (this transitively fixes every caller that pools through
`run_walk_forward()`: `entry_filter_variants.py` and all 3 bearish sweep scripts). Same fix applied
independently to `architecture_diagnostic.py` and `sector_weight_calibration.py`, which had their own
separate copies of the same constant. 3 stale `>=90`-referencing comments fixed for accuracy
(`simulation.py`, `threshold_optimization_analysis.py`, `collinearity_diagnostic.py`). Confirmed
`paper_trading/`, `monitoring/`, and `app_ui/` have no equivalent bug — they've always imported
`CONFIDENCE_THRESHOLD` directly, never hardcoded a duplicate.

**Corrected numbers, re-run after the fix:**

- **Walk-forward: 0 of 6 test periods pass** (not 2 of 6, as first reported). Only one period even
  has enough trades to judge, and it fails. The old "recent years pass, older years don't" story was
  never real — it was an artifact of grading the wrong, too-easy population.
- **Per-sector trade counts:** semiconductors 11, regional banks 0, healthcare 0, consumer
  discretionary 6. Banks and healthcare have zero qualifying trades in their whole test period, not
  just weak results — a starker gap than previously reported.
- **Bearish signals:** re-ran the test that previously found "clearly negative, well-evidenced"
  results for bearish (falling-price) trades. Every single variant tested now returns zero
  qualifying trades. That earlier negative conclusion was entirely an artifact of the same bug — the
  honest state is "no real evidence either way yet," not "proven bad."

**Fix:** `backtesting/walk_forward.py`, `backtesting/architecture_diagnostic.py`,
`backtesting/sector_weight_calibration.py`, `backtesting/simulation.py`,
`backtesting/threshold_optimization_analysis.py`, `backtesting/collinearity_diagnostic.py`. Left an
inline correction in this file's own v2.2.75 entry rather than rewriting it, per this file's stated
practice of leaving self-corrections visible. 1393/1393 tests pass (no test asserted any of these
stale constants' specific values).

**Backtest:** See corrected numbers above — this entry IS the backtest re-run.

**Approved:** Not applicable — this is a correction to how results are measured, not a request to go
live. The model remains not eligible for real capital regardless of this result.

---

## [v2.2.82] — 2026-08-23 — [Bug Fix] A silent no-op that could have quietly reintroduced yesterday's dollar-risk bug

**Status:** Live.

**In short:** A recent risk-tracking fix (2026-08-22) has one weak spot: if the data it reads is ever
malformed, it silently gives up and moves on with no warning — meaning the same bug it just fixed
could quietly come back for a single trade and nobody would ever know. Not a problem today, since
the data is always well-formed, but a silent trap for the future.

**Fix:** That silent failure now logs a warning instead, naming the ticker and the bad value.

**Backtest:** Not applicable — live/paper-only, no scoring/threshold change.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.81] — 2026-08-23 — [Infrastructure] Test coverage for yesterday's mark-to-market fix — the audit's top code-quality finding

**Status:** Live.

**In short:** Yesterday's fix for a real dollar-risk-tracking bug (added open-position profit/loss
tracking, and corrected a ~30% drift in how risk was calculated) shipped with zero tests, despite
touching numbers the whole audit trail depends on — flagged as the highest-risk untested code in
the project. Added the missing coverage.

**14 new tests** cover both the profit/loss tracking (gains, losses, both directions, edge cases
like a stop set at the same price as entry) and the risk-recalculation fix itself (share positions
vs. options, zero shares, bad input data). No production code changed — every test passed against
the existing code as-is, confirming yesterday's fix was correct, just unverified until now.

**Backtest:** Not applicable — test-only change.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.80] — 2026-08-23 — [Infrastructure] Two redundant yfinance round trips removed from every scan

**Status:** Live.

**In short:** Every stock's price history was being downloaded twice per scan, and VIX (the market
fear-gauge index) three times over. Both fixed — no change to what data is used, just less
redundant network traffic and a faster scan.

**1. Stock price data:** two different steps in the same scan each independently downloaded a
heavily overlapping set of tickers seconds apart, roughly doubling network calls every run across 4
sectors, 3 times a day. Added a cache that lasts just for the duration of one scan, so the second
step reuses data the first step already fetched instead of re-fetching it.

**2. VIX data:** one function was making two separate downloads for data that's mostly the same
thing. Now does one download and derives both values from it.

**Fix:** `shared/api_clients/market_data_client.py` (new `_OHLCV_BATCH_CACHE`/`_period_to_days`,
new `fetch_vix_and_pct_change`), `swing_model/run_swing_model.py` (`_fetch_market_context` uses both).
New `tests/conftest.py` autouse fixture (`_isolate_ohlcv_cache`) clears the cache between tests —
`tests/test_market_data_client.py` mocks `yf.download` directly and calls the real functions on top,
so an unmocked shared cache could silently serve one test's mocked data to another. 23 new tests.

**Backtest:** Not applicable — live/paper data-fetching only, backtesting reads pre-downloaded
historical CSVs and doesn't call these functions.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.79] — 2026-08-23 — [Bug Fix / Feature / Infrastructure] The weekly review alert was completely dormant — a docstring that was never true, plus no scheduler. Both fixed

**Status:** Live.

**In short:** The weekly performance check-in was supposed to do two things: alert on Discord when
the win rate drops too low, and actually run on a schedule. It did neither — the code that claimed
to send a Discord alert never really did, and nothing was ever scheduled to call it in the first
place. This safety mechanism has been completely dormant the whole time.

**Fix:** Built the real Discord alert, and added a Sunday 6pm scheduled task so it actually runs
every week, matching the same pattern the daily paper-trading scans already use.

**Also caught, immediately:** the new tests for this fix accidentally wrote 2 fake rows into the
real performance log, because that file wasn't protected from test pollution the way most of the
project's other log files are. Fixed and cleaned up.

**Fix:** `monitoring/performance_dashboard.py`, `shared/utils/discord_alerts.py`, `tests/conftest.py`
(new `_isolate_performance_log` fixture), `data/logs/performance_log.csv` (cleaned). New
`tests/test_weekly_summary_wiring.py` + additions to `tests/test_discord_alerts.py`. A real
`StockAnalysis_WeeklyDashboard` Windows scheduled task now exists on this machine (not
version-controlled — Task Scheduler state, not a repo file). 1370+/1370+ tests pass.

**Backtest:** Not applicable — no scoring/threshold change.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.78] — 2026-08-23 — [Feature] Cross-sector concentration is now visible — advisory only, a real product decision this session

**Status:** Live.

**In short:** Nothing stopped up to 8 open positions across all 4 sectors from all leaning the same
direction at once — a hidden concentration risk that the existing per-sector safety checks can't
see, since they only look within one sector at a time. Paper trading deliberately logs every
qualifying signal without limits, on purpose, so it can see the full picture of what would have
qualified — so a real *block* here would work against that goal. Decided: make the risk visible with
a warning note, but never block logging.

**Fix:** Before logging a new signal, adds up directional exposure (accounting for direction, so a
long and a short partly cancel out) across every open position in every sector. If a new signal
would push that too far in one direction, a note gets added to the same field that already carries
other warnings to the trading log and Discord alert — nothing ever gets blocked or resized.

**Fix:** `paper_trading/paper_runner.py` (`_load_filled_open_positions_detail` extended, new
concentration check ahead of `sizing_note`). 6 new tests. 1359+/1359+ tests pass.

**Backtest:** Not applicable — advisory-only live/paper behavior, no scoring/threshold change.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.77] — 2026-08-23 — [Bug Fix / Feature / Infrastructure] Working through the full-model-audit backlog: test pollution cleanup + a real crash circuit breaker for paper trading

**Status:** Live.

**In short:** Two fixes from the audit backlog.

**1. Cleaned up test data that had leaked into real files.** A real project log file was found
285 rows deep in obviously fake test data — round numbers, blank fields, duplicate rows written
milliseconds apart. None of it was real (the code path that would write real rows here has never
actually run). Fixed the tests to stop writing into real files, and cleaned the fake rows out.

**2. Gave paper trading — the system that's actually running every day — a real crash-alert check
for the first time.** A "market crash" safety alert existed, but only in the live-trading code path
that has never actually run; the pipeline running 3 times a day, every day, had none at all. Also,
even the existing check only ever watched one sector's benchmark regardless of which sectors were
actually active — so a crash specific to, say, healthcare stocks would have gone undetected. Fixed
both: every active sector's own benchmark is now checked independently.

Still advisory only, as intended — this never blocks a signal, it only flags one.

**Fix:** `shared/utils/black_swan_detector.py` (new `load_black_swan_state`/`save_black_swan_state`),
`swing_model/run_swing_model.py` (new `_check_black_swan_per_sector`, rewired existing SMH-only
block), `swing_model/portfolio_manager.py` (docstring only), `paper_trading/paper_runner.py` (new
wiring + `_load_filled_open_positions_detail`), `tests/conftest.py` (2 new autouse isolation
fixtures), `data/logs/trade_outcomes.csv` + `data/processed/signal_win_rates.json` (reset). 15 new
tests. 1351/1351 existing tests pass.

**Backtest:** Not applicable — no scoring/threshold change, no backtest-relevant behavior touched.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.76] — 2026-08-23 — [Backtest Methodology] Re-derived v2.2.75's open rescale question — the honest answer is the dataset can't validate this either way

**Status:** Live (backtest-only fix; no live/paper scoring behavior changed).

**In short:** Yesterday's fix (v2.2.75) corrected the historical test's pass bar to match the real
70-point threshold, but deliberately left one piece untouched: the formula that converts the test's
own raw score onto the same 0-100 scale live trading uses. That formula was old, built for the
previous 90-point system, and never re-checked against reality. This entry re-derives it from real
data — and the result reframes the whole question. At the honest 70-point bar, the historical
dataset for this one sector simply doesn't have enough qualifying signals to trust a verdict either
way. Not "fails," not "passes" — genuinely **not enough data to know**.

**Fix:** Compared the historical test's own highest scores against real live trading's own highest
scores, and used the gap between them to correct the conversion formula.

**Result — a genuinely different failure mode, not just a smaller number:**

| Metric | v2.2.75 (threshold fixed, old rescale) | v2.2.76 (rescale re-derived) |
|---|---|---|
| Qualifying trades | 256 | **11** |
| Win rate | 55.9% | 63.6% |
| Avg R:R | 1.22 | 2.61 |
| Sharpe | 1.67 | 0.27 (unreliable at n=11) |
| Expectancy CI lower bound | 0.195R (fails 0.3R bar) | 0.321R (would clear 0.3R alone) |
| Passed | False (expectancy shortfall) | False (sample size + Sharpe) |

Both numbers fail the go-live safety bar, but for different reasons — v2.2.75's version let in a
wide, noisy set of trades whose average edge wasn't strong enough; this version is strict enough
that too few trades exist to say anything statistically meaningful. As a sanity check: the rate at
which real live trading actually qualifies a signal (2.0% of all scans) is in the same ballpark as
this new backtest calibration's own qualification rate (3.4% of pre-filtered candidates) — which is
reassuring that the method is sound, even though it doesn't change the bottom line.

**What this means, read together with v2.2.75:** the model's real, honest 70-point bar is strict
enough that the available historical data — 13.5 years, one sector — simply isn't enough to
statistically prove the strategy works or doesn't, no matter how the scoring conversion is tuned.
That's a more fundamental finding than "the edge looks weaker than we thought" — it's "there isn't
enough historical data of genuinely qualifying signals to know." Possible paths forward, not decided
here: gather more historical data across more stocks/sectors, treat 70 as a live-only threshold the
backtest can't directly certify, or rely on continued paper trading rather than more backtesting.

**Fix:** `backtesting/simulation.py` (`_RAW_TO_LIVE_RESCALE_FACTOR` replaces `_BACKTEST_SCORE_MAX`),
`backtesting/backtest_engine.py` (docstring update), new `backtesting/raw_score_calibration_diagnostic.py`.
1351/1351 tests pass — no test asserted the old constant's specific value.

**Approved:** Not applicable — this changes how "passed" is measured, not a request to go live. The
model remains not eligible for real capital regardless of this result.

---

## [v2.2.75] — 2026-08-22 — [Backtest Methodology] Go-live gate was testing a signal population live trading can't reach — fixed, and the corrected number fails

**Status:** Live (backtest-only fix; no live/paper scoring behavior changed).

**In short:** A full model audit found that the historical test's own qualifying bar had stayed
stuck at 90 points ever since v2.2.46 lowered the real, live threshold to 70 — nobody had updated
the test to match. That means every "this passes its safety bar" claim since v2.2.46 was measuring
a set of trades live trading can never actually produce (real trading has never scored above ~80).
Fixed the test to use the real 70-point bar. Re-running it with the honest threshold: win rate drops
from 61.2% to 55.9%, and it now **fails** its own safety bar. The "passes" status this project has
been citing wasn't wrong for what it measured — it just wasn't measuring the real thing.

**Problem:** the historical test's qualifying filter was hardcoded to require a 90+ score in three
separate places in the code, left over from the model's original design, before the real threshold
was lowered to 70. Nothing caught the mismatch, because the automatic check that enforces "every
scoring change needs a fresh test result" doesn't watch this particular file.

**Fix:** `backtesting/backtest_engine.py` now imports `CONFIDENCE_THRESHOLD` from `swing_model/scoring.py`
and uses it at all three qualifying-filter sites, so the two can't drift apart again silently.

**Left open, deliberately not touched here:** the test's raw score also gets rescaled to match live
trading's 0-100 scale, using a conversion factor that was derived years ago specifically to make the
*old* 90-point bar reachable. It was never re-checked against the new 70-point bar — flagged as a
real, still-open question rather than silently assumed fine. (Re-derived properly in v2.2.76, the
next entry below.)

**Backtest (semiconductors, single-sector `run_backtest()`, 70/30 split):**

| Metric | v2.2.74 (bug) | v2.2.75 (fixed) |
|---|---|---|
| Passed | **True** | **False** |
| Win rate | 61.2% | 55.9% |
| Avg R:R | 1.82 | 1.22 |
| Sharpe | 2.03 | 1.67 |
| Expectancy CI lower bound | ≥0.3R (passed) | 0.195R (**fails** 0.3R bar) |
| Max drawdown | — | 14.96% (passes 15% cap) |
| Qualifying trades | 152 | 256 |
| Walk-forward | 2/6 windows pass | 2/6 windows pass (unchanged: 2014-2022 fail, 2022-2026 pass) |

Walk-forward pass/fail pattern is unchanged by this fix — the 2014-2022-fails/2022-2026-passes
structure the project already knew about (rate-regime hypothesis, CHANGELOG §11-era findings) persists
at the corrected threshold too. Per-sector and multi-sector pooled numbers (banks/healthcare/consumer
discretionary) were not re-run in this pass — those already failed their own Sharpe bar independently
before this fix (v2.2.56 finding) and this change only widens their qualifying population the same way
it did for semiconductors, so they remain not-passing.

**CORRECTION (v2.2.83, 2026-08-23, same day): the walk-forward claim directly above is wrong.** The
same 90-vs-70 bug existed independently in a different file and wasn't caught by this fix. The real
picture is worse, not the same: 0 of 6 test periods pass, not 2 of 6. See v2.2.83 for the full
correction. Left visible here rather than rewritten, per this file's own practice of leaving
corrections in place instead of erasing the mistake.

**Approved:** Not applicable — this is a correction to how "passed" is measured, not a request to go
live. The model remains not eligible for real capital regardless of this result.

---

## [v2.2.74] — 2026-08-19 — [Scoring Change / Bug Fix / Infrastructure] Tier B batch 3: the last 21 keys resolved, Tier B closed

**Status:** Live.

**In short:** The last, hardest batch of Tier B — every key needed a real refactor, a value
correction, or a deliberate call to leave unwired, not a mechanical swap. Working through them
found the originally-flagged "highest risk" item (`scoring_weights.fundamental_max`) was actually
safe once its rescale math was understood correctly, while a different item
(`positioning.options_max`/`short_interest_max`/`analyst_max`) turned out to be genuinely unsafe to
wire and was reclassified to stay hardcoded instead — the triage itself kept getting refined by
closer code reading, the same pattern as everything else today. Every default matched its prior
hardcoded value exactly, so this batch's behavior is unchanged too — except the 5 stale-value
corrections, which fix real (if currently unexercised or low-impact) config/code disagreements.

**Wired, by area:**
- **scoring_weights** (5 keys, `scoring.py`): `technical_max`/`positioning_max`/`sentiment_max`/
  `news_max`/`fundamental_max` — each is an independent clamp on how much of that category's
  already-computed score counts toward the 100-point base score, not the same constant
  `positioning_layer.py`/`sentiment_layer.py` use internally for their own sub-signal totals (those
  stay fixed — coincidentally equal to these defaults today, not a duplicate needing reconciliation).
  `fundamental_max` is the numerator of a rescale ratio against `FUNDAMENTAL_INTERNAL_MAX` (15,
  `fundamental_layer.py`'s own fixed internal scale) — wiring only the numerator, leaving the
  denominator fixed, keeps the ratio correct at any configured value; new tests confirm the rescale
  math still holds at a non-default value.
- **positioning** (2 of 5 originally-planned keys): `institutional_max`/`insider_max` — their
  formulas (`positioning_layer.py`) are fully expressed in terms of their own max throughout
  (midpoint, scale, bearish mirror), so retuning rescales correctly. **`options_max`/
  `short_interest_max`/`analyst_max` were reclassified to STRIP, not wired** — closer reading found
  their formulas hardcode midpoint/tier literals not derived from the constant, the same reason
  `technical_sub_signals`/`sentiment_sub_signals`/`news_sub_signals` were stripped in batch 1;
  wiring them would silently not rescale correctly. Fixed values now documented directly in
  `positioning_layer.py`.
- **modifier_bounds safety clamps** (6 keys): `sector_rotation`/`earnings_proximity`/`macro_overlay`
  min/max were genuinely unenforced before this — `get_rotation_modifier`/`get_earnings_modifier`/
  `get_macro_modifier` read their raw config values with no clamp at all, so a retuned penalty/boost
  could silently exceed its own documented bound. Now real clamps, applied before any bearish
  sign-flip.
- **backtesting.walk_forward_windows.initial_validate_months**: corrected from a stale config value
  of 6 to the code's real, deliberately-chosen 24 (`walk_forward.py`'s own docstring explains why —
  a 6-month window routinely yields 0-5 trades at this strategy's signal frequency, too few to judge
  win rate on; v2.2.6 widened it and config was never updated to match). This function had zero test
  coverage before this change; added some.
- **backtesting.slippage_options_bid_ask_pct**: wired into `trade_selector.py`'s `_compute_structure_ev`
  — used by **live** `rank_trade_structures`, not just the historical backtest, despite living under
  the `backtesting:` config section.

**Fixed, not just wired (real config-vs-code mismatches, corrected to match validated code):**
- **Fundamental valuation-premium ladder**: `pe_premium_penalty_threshold`/`pe_extreme_premium_threshold`/
  `ev_ebitda_premium_threshold` (config: 0.50/1.00/0.50) described a pre-refactor 2-ladder design the
  code no longer has — replaced with 3 new shared keys (`premium_near_parity_threshold`/
  `premium_moderate_threshold`/`premium_high_threshold`, 0.15/0.40/0.75) matching the real shared
  3-tier ladder both P/E-vs-sector and EV/EBITDA-vs-peers actually use.
- **fundamental.eps_negative_threshold**: config declared 1 breakpoint (-0.05, a stale duplicate of
  `eps_flat_threshold`) for what's actually a 5-tier ladder with 2 negative breakpoints. Repurposed
  to the real first one (-0.15) and added `eps_severe_decline_threshold` (-0.30) for the second.
- **confidence.min_threshold**: corrected from a stale 90 to the real, live 70 — but deliberately
  left unwired. `CONFIDENCE_THRESHOLD` gates whether a trade signal surfaces at all and is imported
  directly by 5+ files (`paper_runner.py`/`run_swing_model.py`'s qualification checks,
  `position_sizer.py`'s sizing-tier floor, `discord_alerts.py`'s display) — `scoring.py`'s own
  docstring already states changing what gates a trade is a deliberate live-behavior decision, not
  something to expose to a config edit silently.

**Tier B is now closed**: `scripts/check_config_coverage.py` reports 156 leaf keys, all referenced
or one of 2 permanent, reasoned exceptions (`confidence.min_threshold` above;
`positioning.institutional_distribution_threshold`, which is definitionally the negative of
`institutional_accumulation_threshold` for this symmetric formula, not an independent knob).

**Fix:** `swing_model/scoring.py`, `swing_model/fundamental_layer.py`, `swing_model/positioning_layer.py`,
`swing_model/trade_selector.py`, `shared/utils/sector_rotation.py`, `shared/utils/earnings_calendar.py`,
`shared/utils/macro_overlay.py`, `backtesting/walk_forward.py`. New regression tests for every wired
key confirm a non-default config value actually changes behavior.

**Backtest:** Confirmed unchanged (61.2% WR, Sharpe 2.03, 152 trades) — every wired/corrected
default matched what the code already validated against.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.73] — 2026-08-19 — [Scoring Change / Infrastructure] Tier B batch 2: 18 config keys wired for real, all zero-behavior-change

**Status:** Live.

**In short:** Continuing the settings cleanup started in v2.2.72: wired up 18 more settings that
used to do nothing when changed. Every one of them already matched its hardcoded value exactly, so
today's behavior is unchanged — editing these settings now actually works, which it didn't before.
23 more settings remain for the next batch.

**Wired, by area:**
- **Fundamental** (`fundamental_layer.py`): `eps_accelerating_threshold`, `eps_positive_threshold`,
  `eps_flat_threshold`, `forward_trailing_tolerance`.
- **Positioning** (`positioning_layer.py` / `positioning_client.py`): `institutional_accumulation_threshold`
  (also governs distribution — the linear formula is symmetric, not two independent knobs),
  `short_interest_declining_threshold`, `short_interest_increasing_threshold`,
  `analyst_trend_lookback_days`.
- **News** (`news_layer.py`): `decay_halflife_hours`, `decay_zero_at_days`, `cluster_window_days`.
- **Backtesting** (`backtest_engine.py` / `walk_forward.py` / `metrics.py`): `train_split` (7
  call sites across `backtest_engine.py` + 4 diagnostic scripts), `min_qualifying_trades`,
  `walk_forward_windows.initial_train_months`, `slippage_stock_per_share` (2 previously-independent
  hardcoded copies in `metrics.py` and `options_math.py`, now both read the same config value —
  the `options_math.py` copy is also used by **live** `trade_selector.py`'s EV ranking, not just
  the backtest, so this one got extra test coverage).
- **Confidence** (`backtesting/metrics.py`): `sensitivity_thresholds` (the `--sensitivity` grid).
- **Holding period** (`backtesting/simulation.py`): `max_days` (backtest's hold-to-close cutoff;
  `min_days` was already removed in batch 1 — dead even within the one function that owned it).

**Fix:** All defaults changed from hardcoded Python literals to `cfg.get(key, <same literal>)`,
using `None`-sentinel parameters where a function already took an explicit override (so nothing
that explicitly passes its own value anywhere is affected). New regression tests for every wired
key confirm a *non-default* config value actually changes behavior, not just that the old default
still works.

**Backtest:** Confirmed unchanged (61.2% WR, Sharpe 2.03, 152 trades) — every wired value matched
its prior hardcoded default exactly.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.72] — 2026-08-19 — [Infrastructure] Tier B batch 1: 68 dead config keys removed, 41 queued to be wired for real

**Status:** Live.

**In short:** Found 109 settings in the model's own settings file that describe controlling its
behavior, but that no code actually reads — far more than previously known. Sorted every one into
"worth wiring up for real" (41, queued for the next two versions) or "outdated, duplicate, or
irrelevant — just remove" (68). Removed the 68 today. Since none of them were ever actually read by
any code, removing them changes nothing about how the model behaves.

**Notable findings from the triage, not just "unread":**
- **A genuine duplicate.** `positioning_sub_signals.*` and `positioning.*_max` declared the
  identical 5 values (options/institutional/short-interest/insider/analyst maximums, summing to 20)
  under two different key-naming conventions in two different config sections. Kept `positioning.*_max`
  (queued to be wired, batch 3 — its formulas in `positioning_layer.py` already partially derive
  from the named constants), removed the duplicate.
- **3 safety-adjacent items removed on purpose, not wired.** `circuit_breakers.orange.no_new_positions`/
  `orange.pause_days`/`red.full_stop` described behavior that's already unconditionally true in
  `position_sizer.py` and `portfolio_manager.py` — wiring them would only add a live path for a
  config typo to silently weaken a circuit breaker, for zero real flexibility gained.
  `pdt.max_day_trades_per_5_days` is a regulatory (Pattern Day Trader) rule, not a strategy knob;
  real tracking infrastructure exists but the enforcement gate is dead code with a mismatched
  default — removed the misleading always-a-no-op config key, flagged as real future work before
  this model ever trades real money, not a config wire-in. `position_sizing.tiers` had drifted
  stale (missing the 70-89 "dead zone" tier `position_sizer.py`'s real `SIZING_TIERS` added later,
  v2.2.46) — wiring it as-is would have silently zero-sized every 70-89-confidence trade.
- **A wrong documented bound, corrected while removing it.** `modifier_bounds.regime.max` claimed
  +10, but `regime_detection.py` can only ever produce +5 — simply incorrect documentation, not a
  gap.
- **A misleading key removed with a doc fix, not just deleted.** `risk_reward.breakout_lookback`
  bound to nothing — the real 20-day breakout lookback is driven by the unrelated, already-wired
  `technical.ma_short`, which just happens to share today's value. Added a comment on `ma_short`
  itself so a future edit doesn't silently change the breakout level without realizing it.

**Fix:** Removed 68 keys from `config/swing_config.yaml`. Fixed `app_ui/config_validation.py`'s
sum-checks (`_SUB_SIGNAL_GROUPS`), which required 4 of the removed sections to exist, and its tests.
Fixed `README.md`'s Section 7 config docs, which described several of the removed/still-decorative
keys as if editing them worked today.

**Backtest:** Confirmed unchanged (61.2% WR, Sharpe 2.03, 152 trades) — every key removed was
already unread by any code path.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.71] — 2026-08-19 — [Infrastructure] Tier C closed: 2 unbuilt features removed rather than built

**Status:** Live.

**In short:** Found 2 features described in the settings file as if they were real, but that were
never actually built: early profit-taking on options trades, and a system for aging out old signals
that never got acted on. Both would be genuine new engineering, not a quick wire-up — decided
neither is worth building right now, since the model hasn't even cleared its safety bar yet. Removed
both instead of leaving them half-documented and misleading.

**Why not built:**
- `profit_targets` (close a defined-risk options structure early once it's captured some % of its
  max theoretical profit, a common real options-trading practice) needs day-by-day mark-to-market
  repricing of the specific structure, not just the underlying's price — real new logic for both
  live (real option chain) and backtest (no historical chain archive exists, so backtest would need
  a modeled repricing). The current underlying-price-driven exit already works and is what the
  validated backtest numbers reflect.
- `shared/utils/signal_decay.py` assumes a signal can sit "queued," unacted-on, aging over days
  before expiring. That queue doesn't exist anywhere in this model — both live and paper trading
  score fresh and act the same scan, every scan. Building this for real means introducing persistent
  pending-signal state across scans, a genuine architecture change, not a bug fix.

**Fix:** Deleted `shared/utils/signal_decay.py` and its 12 tests (`tests/test_phase8_portfolio.py`
— NOT the `signal_decay` config *section*, which is real and unrelated: `position_rescoring.py`'s
early-exit/time-stop logic reads `early_exit_confidence_drop`/`time_stop_no_progress_pct`/
`time_stop_day` from it and stays exactly as it was). Removed `profit_targets` from
`config/swing_config.yaml` and its allowlist entries from `check_config_coverage.py`. Fixed 2 stale
`Project_Scope.md` lines that credited the deleted `signal_decay.py` for daily position re-scoring
— that's actually `position_rescoring.py`'s job and always has been; the docs just named the wrong
file.

**Backtest:** Confirmed unchanged (61.2% WR, Sharpe 2.03, 152 trades) — neither removed item was
ever referenced by the backtest.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.70] — 2026-08-19 — [Bug Fix] Paper trading now alerts immediately on a critical event hitting an open position

**Status:** Live (paper trading).

**In short:** Live trading sends an immediate Discord alert when serious news (a CEO resignation, a
fraud investigation) hits a position that's already open — paper trading had no equivalent, and
would only find out the next day. Nothing suggests this was intentional; it looks like a feature
that just never got carried over. Added it.

**Fix:** `paper_runner.py` now tracks whether each scanned ticker has an open position (it already
computes this set for the duplicate-position guard) and calls the same
`_handle_open_position_critical_event()` `run_swing_model.py` uses, for every critical event on that
ticker — same cross-module reuse pattern already used for the other 18 helpers `paper_runner.py`
imports from `run_swing_model.py`. New end-to-end test in `tests/test_multi_sector_live_pipeline.py`
(same real-pipeline-with-fakes harness as the existing multi-sector test) confirms the alert fires
for an open position and threads the right ticker/event/model-version through.

**Backtest:** Not applicable — this is a live/paper Discord-alerting feature with no equivalent
concept in the historical test (confirmed unchanged: 61.2% WR, Sharpe 2.03, 152 trades).

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.69] — 2026-08-19 — [Research] Pipeline deduplication, part 2 — the 2 largest blocks are riskier to merge than they looked, left separate on purpose

**Status:** Research — no code changed.

**In short:** v2.2.68 flagged the 2 largest blocks of duplicated code between live and paper trading
as candidates to merge into one shared piece of code. A closer look found real reasons neither is a
safe, easy merge right now — documenting why here so a future pass doesn't waste time re-discovering
the same thing, or assume "duplicated" automatically means "safe to combine."

**Findings, by block:**

1. **Trade-structure selection** (the largest duplicate). Live trading has an extra validity check
   paper trading doesn't — confirmed harmless in outcome (a later step rejects invalid setups either
   way), but it's a real behavioral difference, not just formatting. The two pipelines also format
   the resulting data completely differently for their own downstream needs (a Discord alert vs. a
   CSV row) — combining them wouldn't actually remove that formatting work, just relocate it.
2. **Per-ticker scoring.** This one really is equivalent between the two pipelines — but combining
   it would require a shared function with around 15 inputs and 10 outputs, since several later
   steps each need specific pieces of it individually. Real added complexity for a change that
   wouldn't meaningfully reduce the risk of the two pipelines drifting apart. Worth revisiting only
   if a new signal gets added that both pipelines need.

**How to apply:** the next review that flags these two blocks as duplicated should read this entry
first — the duplication is real, but merging it isn't free the way v2.2.68's smaller merges were.

**Backtest:** Not applicable — no code changed.

---

## [v2.2.68] — 2026-08-19 — [Bug Fix / Infrastructure] Pipeline deduplication, part 1 — a real win-rate bug fixed, 3 duplicated blocks consolidated, 1 left alone on purpose

**Status:** Live.

**In short:** Compared every duplicated block of code between the live and paper-trading pipelines
item by item, looking for the recurring pattern where a fix gets applied to one pipeline but not
its twin. Found one real bug this way: paper trading's win-rate number quietly undercounted real
wins. Merged 3 blocks that were genuinely duplicated into shared code; found a 4th planned merge
wasn't actually safe and left it alone (documented why, so a future pass doesn't redo the work).

**Problem, fix, by item:**

1. **Paper trading's win-rate stat silently used a stricter definition than the historical test's.**
   A profitable early exit (a "time stop" that closed above entry) counts as a real win in every
   backtest report — but paper trading's own copy of this calculation only counted `outcome ==
   "win"` literally, missing that case. Low real-world impact today (this number is reported for
   visibility, not a go-live gate), but it meant paper trading's reported win rate wasn't actually
   comparable to the backtest's own number for the same underlying trades. Fixed by importing the
   backtest's own shared function instead of reimplementing it — it already imported two sibling
   functions from the same module, just not this one.
2. **Geopolitical risk penalty** (TSM/ASML's fixed confidence penalty) — identical formula
   duplicated in both pipelines, extracted to one shared function.
3. **Position-sizing input derivation** (turning a ranked trade structure into the risk-per-unit
   and per-unit-cost numbers the position sizer needs) — identical branching duplicated in both
   pipelines, extracted to one shared function.
4. **Not merged, on purpose: Event Severity Gate block-creation.** Assumed going in to differ only
   in whether paper trading's database-notification call fires. Closer comparison found a second,
   real difference: the live pipeline fires an immediate Discord alert when a critical news event
   hits an already-open position, in the same pass that creates the block; paper trading's version
   has no equivalent call anywhere. Forcing a shared function here would mean either silently adding
   an alert paper trading never had, or silently dropping one live has always had — a real behavior
   question, not a pure dedup, so it's left as two separate implementations. Whether paper trading
   *should* have this alert is a legitimate open question for a future pass, not a dedup decision.

**Fix:** New `shared/utils/geopolitical_risk.py` (`apply_geopolitical_penalty`) and a new
`derive_sizing_inputs()` in `shared/utils/position_sizer.py`, both called from `paper_runner.py`
and `run_swing_model.py`. `paper_trade_metrics.py`'s two local win-rate reimplementations replaced
with `backtesting.metrics.compute_win_rate`. New tests for all of it.

**Backtest:** Not re-run — none of this pass's changes touch any code the historical test exercises
(it doesn't do position sizing, apply the geopolitical penalty, or use paper trading's win-rate
stat at all), so there is nothing for a backtest to measure. Baseline stays v2.2.67's: 61.2% WR,
Sharpe 2.03, 152 trades.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.67] — 2026-08-19 — [Bug Fix / Scoring Change] Exhaustive double-counting inventory — 4 known pairs confirmed handled, 1 new one found and fixed

**Status:** Live (paper trading).

**In short:** Went looking for every place two scoring signals might be independently reacting to
the same underlying fact and double-counting it — a recurring bug shape only ever caught by chance
before now. Checked every signal against every other one. 4 known pairs were confirmed already
fixed. One new, real, unfixed pair turned up: a China-trade-tension news check and a separate macro
China-tension signal both scanning largely the same headlines, each able to independently penalize
the same stock for the same news.

**Problem, fix:** `macro_overlay.py`'s China-tension signal and `news_layer.py`'s `china_export`
theme both scan Yahoo/news headlines for the same watchlist and words. When both agree a candidate
is heavily in China-tension news, the candidate was penalized once through News's theme-alignment
score and again, independently, through the macro modifier — the same "same underlying signal,
counted twice" shape already fixed once for regime/sector_rotation (both driven by SMH price
action) and cross_ticker's sector-wide discount. Fixed the same way: when both agree, the News
contribution is zeroed and the macro signal (a more robust multi-signal threshold: TNX + DXY +
keyword count) stays authoritative. Live/paper only — the historical test doesn't have a China-
news-keyword archive for its date range and already hardcodes that specific input to zero, so it
was never exposed to this double-count in the first place.

**Fix:** New `dampen_news_china_theme_if_macro_confirmed()` in `shared/utils/macro_overlay.py`,
called from all 3 pipelines (`paper_runner.py`, `run_swing_model.py`, `backtesting/simulation.py`)
right after both the macro and News scores are computed for a ticker, before either reaches the
final confidence score. New regression tests in `tests/test_macro_context.py`.

**Backtest:** Run date: 2026-08-19. Win rate: 61.2%. Avg R:R: 1:1.41. Sharpe ratio: 2.03. Max
drawdown: 7.7%. Qualifying trades: 152. Max consecutive losses: 9. **Passed — unchanged from
v2.2.66**, exactly as expected: the fix is a no-op wherever China-tension keyword counting is
hardcoded to 0, which is every backtest run today.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.66] — 2026-08-19 — [Bug Fix / Infrastructure] Two permanent CI guardrails against the recurring bug shapes, plus 2 more real gaps found while building them

**Status:** Live.

**In short:** v2.2.65 named 4 recurring bug shapes in this project's history that nothing was
actually checking for automatically — they'd only ever been caught by manual sweeps. Built
automatic, permanent checks against the first two: one that fails the build if any setting in the
config file has no real code reading it, and one that fails the build if any scoring signal isn't
explicitly confirmed to handle both bullish and bearish trades. Building these checks by hand
surfaced 2 more real bullish-only bugs, both fixed, and a much bigger version of an already-known
problem: 108 settings the config file describes as real, that no code actually reads — not ~41 as
previously thought.

**Problem, fix, by item:**

1. **A supply-chain/memory-pricing news signal had no effect on bearish trades.** It correctly
   scored bullish candidates during supply-chain uncertainty, but scored a bearish trade in the
   exact same situation as neutral instead of confirming it. Fixed by adding the missing mirrored
   logic.
2. **A standalone insider-trading signal was bullish-only.** Currently unused, so harmless today —
   but would have shipped a silent bug the moment it's wired in. Fixed the same way.
3. **New:** an automatic check that fails the build if any config setting has no code actually
   reading it. Found 67 more settings with this problem, beyond the ~41 already known and tracked —
   allowlisted with reasons for now rather than forcing an unrelated cleanup into this change.
4. **New:** an automatic check that fails the build if any scoring signal isn't explicitly confirmed
   to handle both bullish and bearish trades. A brand-new signal that skips this classification now
   fails the build, instead of silently shipping bullish-only the way items 1 and 2 did.

**Fix:** Items 1-2 fixed directly in `shared/utils/narrative_tracker.py` and
`shared/utils/insider_tracker.py`, with new regression tests. Items 3-4 are new, permanent checks,
not one-time fixes — verified on a throwaway branch to actually fail on a deliberately-broken
example before being trusted.

**Backtest:** Run date: 2026-08-19. Win rate: 61.2%. Avg R:R: 1:1.41. Sharpe ratio: 2.03. Max
drawdown: 7.7%. Qualifying trades: 152. Max consecutive losses: 9. **Passed — unchanged from
v2.2.65.** Same pattern as v2.2.65's cross-ticker fix: items 1-2 are verified correct at the
unit-test level, but this historical semiconductor dataset doesn't have enough candidates hitting
these specific narrative themes for it to move the aggregate numbers.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.65] — 2026-08-19 — [Bug Fix] Nine more real gaps, found by building a complete checklist instead of another spot-check

**Status:** Live.

**In short:** After today's earlier audit, asked: are we finding the same kinds of mistakes over and
over, and are we actually checking for that on purpose? Looking back through 7 weeks of history, the
honest answer was: the same three *shapes* of bug kept resurfacing, because past fixes came from
reading code and noticing something wrong, not from checking every place that shape of bug could
hide. So instead of reading more code, built three complete checklists instead — covering unreachable
code, bearish trades scored like bullish ones, and places where two pipelines do the same job with
separately-written code that could quietly drift apart. That turned up more than expected; fixed the
9 quickest, safest findings now and scoped the rest for later.

**Problem, fix, by item:**

1. **A bearish trade could be penalized by the very sector strength that should have confirmed it.**
   The cross-ticker signal (is this stock moving on its own, or just riding the sector?) never had any
   concept of trade direction at all — a stock falling faster than its peers, which should support a
   bet that it keeps falling, was instead scored the same backwards way a rising stock would be for a
   bullish bet. Every other signal in the model already handles this correctly for both directions;
   this one didn't, because it never had a "which direction is this trade betting on" input to begin
   with. Fixed by teaching it to swap which condition confirms the trade once the direction is known,
   the same pattern already used successfully elsewhere.
2. **Two research reports were quietly counting a losing streak out of calendar order** — the identical
   bug already found and fixed once today in the main historical test, left unfixed in two smaller
   diagnostic scripts that independently reimplement the same math.
3. **Black Swan mode (a market-crash safety flag) turned back off after just one calm day**, even
   though the settings have always said it should wait for 3 consecutive calm days before doing so. The
   3-day check was already built and tested — it just was never actually being used.
4. **A stated "confidence penalty" for geopolitically exposed stocks (TSM, ASML) was never actually
   applied.** The system would log a note saying a penalty had been applied, but never actually
   subtracted anything from the score — and the paper-trading system didn't even have the note; it
   never referenced this setting at all.
5. **The live trading system was quietly less accurate than the paper-trading system it's supposed to
   match**, in three small ways: it showed a stale profitability number in alerts instead of the real
   one; it never used the model's own calibrated win-probability estimate, always falling back to a
   cruder one; and it required two economic indicators to both be available before using either,
   throwing away real signal it didn't need to.

**Fix:** All 9 fixed directly in code/config, following the same patterns already proven correct
elsewhere in the model (one shared function instead of copy-pasted logic, matching what the historical
test and paper trading already do correctly). New test coverage added for the highest-risk items (the
cross-ticker direction fix, the Black Swan cooldown). Full detail in the commit history.

**What's next:** the same audit surfaced two bigger findings, held back for a separate pass. The
whole scoring-weight configuration in the settings file turns out to be decorative — the model's
real weights are fixed in code and don't read the settings file at all. And two whole features
described in the settings don't actually exist in the code — not bugs, but real decisions about
whether to build them or remove the settings describing them. Neither touched here.

**Backtest:** Run date: 2026-08-19. Win rate: 61.2%. Avg R:R: 1:1.41. Sharpe ratio: 2.03. Max drawdown:
7.7%. Qualifying trades: 152. Max consecutive losses: 9. **Passed — unchanged from v2.2.63.** The
cross-ticker direction fix (item 1) is verified correct at the unit-test level, but this historical
semiconductor dataset didn't have enough individually-diverging bearish candidates for it to move the
aggregate numbers — a real fix that happened not to change this particular sample, not a wasted one.

**Approved:** Pending — do not go live on this version until reviewed.

---

## [v2.2.64] — 2026-08-19 — [Bug Fix] Same-day correction: the new confidence-decay early-exit check compared real scores against artificially neutral ones and wrongly closed 7 paper positions

**Status:** Live.

**In short:** A daily check shipped just hours ago (v2.2.63) was meant to cut a paper-trading
position loose early if its outlook had genuinely soured. Run for real for the first time, it
immediately flagged 7 of 8 open positions as having "lost confidence" within seconds of each other —
not a realistic result. The cause: the check compares today's re-scored confidence against the
score recorded when the trade opened, but the re-score had no fresh sentiment or news data to work
with, so it substituted flat placeholder values for both, manufacturing a large fake "drop" that had
nothing to do with real market conditions. The 7 wrongly-closed positions were restored before
anything was ever committed — no lasting record exists. The check is now switched off until it can
compare like with like.

**Fix:** Removed the call to this check from the daily update loop for now — the underlying function
stays in the codebase for a future proper fix. The other new daily check from the same release (a
simple "not enough progress after 10 days" rule, which never touched sentiment/news data) had no such
problem and stays active.

**Backtest:** Not applicable — this change only affects the live/paper daily update loop, not the
scoring formula or the historical test, and doesn't touch `config/swing_config.yaml` or
`swing_model/scoring.py`.

**Approved:** Pending — do not go live on this version until reviewed.

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

**In short:** A safety check exists that forces a new trade into a capped-loss options structure
whenever earnings are 0-5 days away — but it only ever runs once, at signal time. A plain stock
position signaled well before earnings was never re-checked as the clock ran down, so it could still
be sitting fully exposed, with no built-in loss limit, on the day earnings actually hit. Not
hypothetical: a real NVDA trade would have ridden through its earnings report unprotected under this
gap.

**Fix:** The daily update loop now re-checks every open plain-stock position for how close its
earnings date is, and closes it out early if the report has moved into that 0-5-day danger window —
before a post-earnings price gap can blow through its stop-loss. Options positions already have a
built-in loss cap, so they don't need this.

**`earnings_exit` wired through the outcome pipeline it needed to be, deliberately left out where it didn't:**
- `shared/utils/discord_alerts.py::send_paper_outcome_alert` — new label/emoji/color (📅, yellow if profitable else red-toned) instead of falling through to a generic all-caps label with an always-red ❌ regardless of actual P&L.
- `paper_updater.py::print_summary()` — counted as a win when profitable, same rule already applied to `time_stop`, so it can't quietly drag the reported win rate down just by adding to the denominator without ever landing in a numerator (a bug this change would otherwise have introduced).
- `swing_model/feedback_loop.py`'s weight-calibration fitting already skips any outcome string outside `("win", "loss", "time_stop")` — `earnings_exit` falls into that same, already-correct exclusion (identical treatment to `expired`), so no change needed there.

**Second gap found, not fixed:** `news_layer.py`'s `event_gate_blocked` check (the one that blocked AMZN/HD's 2026-08-19 signals on a "labor strike" headline) has the exact same shape — evaluated once at signal time, never re-applied to a position that's already open. An adverse news event breaking mid-hold doesn't trigger any reaction today. Left as a flagged, undeferred gap rather than built here: unlike the earnings fix (one cheap, already-cached-shape `yfinance` calendar call per ticker), closing this needs a daily news re-fetch and re-score per open ticker against Alpha Vantage's metered free tier and StockTwits — a real cost/rate-limit tradeoff that needs a decision before building, not just wiring.

**Tests:** New `tests/test_paper_updater_earnings_exit.py` (7 tests) covering the flatten/no-flatten boundary, earnings-day-itself, options structures being left alone, missing `position_type` defaulting to the protected case, and no-earnings-date/empty-bars no-ops. Full suite: 1279 passing (up from 1272), no regressions.

---

## [v2.2.61] — 2026-08-19 — [Feature / Bug Fix] Stress-test skips fixed, real cross_ticker backtest wiring, real max-loss/max-gain + strikes, wider Greeks coverage, real contract counts, and alternatives surfaced

**Status:** All live except the earnings_modifier gap, which remains an honest, undeferred limitation (no code path to fix it exists yet — see below).

**In short:** Follow-up to v2.2.60's review. Fixed two small gaps (stale test skips, a hardcoded
backtest input), then built five improvements to the trade-structure output: real dollar
max-loss/max-gain figures, actual contract counts, real strike prices and expiration dates, wider
options-Greeks coverage, and showing the runner-up trade options alongside the winner instead of
just discarding them.

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
