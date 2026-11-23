# vrp-spy-long

**Family:** cboe_vrp  
**Horizon:** 20 days  
**Entry:** close (signal computed from that day's VIX and 20-day trailing realized vol)  
**Direction:** LONG SPY (index-level, not individual stocks)

## Mechanism
The variance risk premium (VRP) is the compensation investors earn for bearing variance (volatility)
risk: VRP = VIX (implied vol) − realized_vol (past 20 trading days, annualized). When VRP is high,
option sellers are richly compensated, and the economy is offering a large risk premium for holding
equities. Bollerslev, Tauchen & Zhou (2009) show that VRP strongly predicts equity excess returns at
the 1–3 month horizon: a 1-unit increase in VRP predicts ~10–15 bps higher next-month S&P 500 return.
The mechanism: elevated VRP signals heightened uncertainty and risk aversion; as that aversion
normalizes, equities mean-revert upward. This is distinct from pure "VIX is high → buy stocks" (a
level effect) because VRP controls for the REALIZED volatility environment — high VIX in a genuinely
volatile market is neutral; high VIX when realized vol is low signals an excess fear premium.

## Evidence
- **Bollerslev, Tauchen & Zhou (2009) RFS** "Expected Stock Returns and Variance Risk Premia":
  VRP explains 1–2% of next-month S&P 500 return variation; in-sample predictive t > 3; annualized
  Sharpe of a VRP-timed strategy ~0.5–0.7 vs unconditional ~0.4. High-VRP months earn ~80–120 bps
  above average; estimated 50–100 bps per 20-day trade in the top VRP tercile.
- **Drechsler & Yaron (2011) RFS** "What's vol got to do with it?": VRP is the main driver of the
  equity premium; when VRP is in the top quartile, subsequent 1-month equity returns are 100–150 bps
  above the bottom quartile.
- **Carr & Wu (2009) JF** "Variance Risk Premiums": VRP is persistently positive (~5 annualized
  percentage points on average), confirming the structural demand for variance insurance.
- Out-of-sample evidence: post-publication replication studies (Martin 2017 "What is the Expected
  Return on the Market?") confirm the VRP-return link, though the effect size has modestly shrunk.
  Conservative post-publication estimate: ~40–60 bps per 20-day high-VRP trade.
- **Family overlap note**: pre-team work tested "VIX timing" that failed the 2018–2026 holdout (see
  graveyard pre-team section). That signal was likely a VIX LEVEL threshold (VIX > 20/25/30 → buy);
  VRP conditions on VIX minus realized vol (not level), so it is a different signal. cboe() is a new
  data source just added to the catalog. Researcher should verify the specific pre-team VIX signal
  before spending holdout, and treat the 2016–2026 holdout with appropriate skepticism given the
  adjacent pre-team failure.

## Rule sketch
1. Signal: each trading day, compute:
   - `IV = cboe('VIX')[date]` (annualized implied vol, %)
   - `RV = std(daily_returns(SPY, past 20 sessions)) × sqrt(252)` (annualized realized vol, %)
   - `VRP = IV − RV`
2. Entry condition: `VRP > threshold` (threshold to be chosen in train; likely 4–8 annualized %)
3. Entry: buy SPY at that day's close
4. Exit: sell SPY at close 20 trading days later (regardless of VRP on exit day)
5. Direction: LONG
6. No hedge (SPY IS the index; short-vol hedge would be a different strategy)
7. If still in a prior 20-day position on a new signal day, researcher can either skip (no overlap)
   or treat as a continuous "in/out" regime signal (the latter needs careful clustering)
8. Cluster by month (hold > 10 days; harness enforces)

## Data
- `rd.cboe(['VIX'])` → daily VIX closing level
- `rd.daily(['SPY'])` → SPY close for realized vol computation AND for entry/exit prices
- No other sources needed

## Events / year
VRP > 4% (approximate median) on roughly 50% of trading days → ~125 signal days/year. The regime
interpretation (enter on signal, exit after 20 days, no overlap) gives ~12 non-overlapping trades/year
when signal is "on" for most of the year. With monthly clustering and a 20-day hold: ~12 monthly
clusters/year → 12 × 20 years = 240 clusters in a 2000–2019 train period — adequate.
Passes 20 distinct days/year ✓. For trade-count threshold (60/year): ~12 non-overlapping 20-day trades
is below 60 on its own. If the signal fires discretely (enter each day VRP > threshold, 1-day hold):
~125 1-day trades/year. Researcher should choose the overlapping-entry or non-overlapping interpretation
in the PLAN and verify ≥60 independent events under the chosen rule.

## Holdout
cboe_vrp is a new family; full VIX history (1990–present) is clean.  
**Suggested split:** train 2000–2017 (18 years), holdout 2018–2026 (8 years).  
**Caveat:** pre-team "VIX timing" tested 2018–2026 and failed. If VRP is too similar to that signal,
the 2018–2026 holdout period is effectively already seen. The researcher should verify what the
pre-team signal was (ask the Engineer to retrieve it from the V3 research log if needed) before
spending holdout. Alternatively: train 2000–2015, holdout 2016–2026, to maximise distance from the
pre-team work.

## Cost estimate
SPY is a mega-cap ETF. Close fills: SP500 half-spread ≈ 3.3 bps at close → RT ≈ 6.6 bps.
SPY itself will be considerably cheaper (~0.5–1 bps half-spread at close); the team does not yet
have SPY-specific spread data (ETF quote capture began 2026-11-23). Using 7 bps RT as a conservative
bound: 50 bps gross / 7 bps cost = 7.1× — comfortably passes 3× hurdle even at the conservative rate.

## Why it might NOT work
- VRP predicting short-term returns is a statistical regularity with modest R² (~1–2%); noise is high
  and the edge is diffuse — not a crisp "event" signal
- The pre-team "VIX timing" (a related signal) already failed the 2018–2026 holdout; if VRP and VIX
  level are correlated enough, the same fundamental failure applies
- VRP is highest in market crashes (2008, 2020) — a few large events dominate the t-statistic; the
  holdout may not contain a sufficient crash for the signal to shine
- Publication of the Bollerslev-Tauchen-Zhou result (2009) itself attracted capital; timing-based
  strategies using VIX tend to degrade post-publication as arbitrageurs front-run them
- For SPY as a single instrument, monthly clustering reduces the effective sample to ~12 observations/year;
  holdout power may be low

## Differs from graveyard / dropped ideas
- **VIX timing** (pre-team, graveyard): likely a VIX LEVEL threshold (VIX > N → buy); this idea
  uses VRP = VIX − realized_vol, conditioning on the EXCESS of implied over realized vol
- **daily_short_term** (exhausted: search 2000–2026): price/volume patterns on individual stocks;
  this uses cboe() as a NEW data source for an index-level signal — different loader, different family
- **turn-of-month** (dead, calendar_effects): calendar-driven, not vol-premium-driven
- No prior cboe() family has been registered or searched in this pipeline
