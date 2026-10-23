# Round 7: EVENT-DRIVEN + residual families, 0-5 day holds — pre-registered 2026-10-23, BEFORE any event data is scored

Why: rounds 1-6 (~370k configs) tested only price/volume patterns. No information-event signal was ever
tested. Horizon = day trade OR swing of at most 5 sessions (user: a wrong day trade may be held up to 5 days,
so both are one model).

Data (all free): daily bars 1999-2026-10-06 for 1,507 current S&P 500/400/600 stocks + 15 ETFs (yfinance,
adjusted). Earnings dates with time of day + EPS surprise (yfinance get_earnings_dates, back to ~2000).
Analyst rating changes (yfinance upgrades_downgrades, ~2012+). Insider open-market trades (SEC Form 3/4/5
data sets, 2006Q1+, codes P/S). VIX/VIX3M (yfinance). Known bias: current constituents only (survivorship);
mitigated by hedging, and called out for long-only results.

Costs (per side, tiered by liquidity; harsher than rounds 1-6): S&P 500 3 bps, S&P 400 5 bps, S&P 600 8 bps,
ETFs 1 bp.

Metric: HEDGED net bps/trade = sign x (trade return - equal-weight universe return over identical entry/exit
points) x 1e4 - round-trip cost. RRV family: hedge = beta x its own sector ETF (beta and ETF chosen from the
prior 252 sessions only). MAC family (ETF timing): excess over the same ETF's unconditional mean for equal-length
windows in the same period. NW t (lag = max hold) on the daily series of summed bps by entry date.
RAW after-cost P&L is reported alongside and must also be positive for any recommendation.

Event timing (no look-ahead): earnings day 0 = first session whose OPEN can reflect the report (time < 09:30 ET
-> that session; otherwise next session). Insider: the filing date is public possibly after the close -> earliest
entry = next session's open. Analyst action: entry = next session's open after the action's calendar date.
Filters use only data through the prior close for open entries, through the entry close for close entries.

Families
- EGAP  earnings reaction: |day-0 open gap| >= g ATR (0.5,1,2,3); follow / fade; entry day-0 open, day-0 close,
        day-1 open; exit day-0 close (day trade) or day 1/2/3/5 close; filters none / volume confirm
        (close entries) / day-0 close confirms gap (close entries) / surprise sign agrees / liquid half.
- ESUR  EPS surprise drift: surprise >= s% (0,5,10,25) long, <= -s% short, both; entry day-0 close / day-1 open;
        hold 1,2,3,5.
- EPRE  pre-earnings run-up (announcement premium): long at close of day -k (k 1,2,3,5), exit at close of day -1
        or at day-0 close (holding through the report); filters none / prior-20d loser / prior-20d winner.
- INS   insider open-market buys (P) / sells (S): value >= $25k/$100k/$500k/$1M; officer-only or any; cluster >=1/2/3
        distinct insiders in 10 days; prior-20d return filter none/negative; entry next open; hold 1,2,3,5.
        Buys long, sells short.
- ANL   analyst rating actions: upgrade long / downgrade short / initiations (both); price-target change
        filter none / >=10%; same-day multi-firm cluster; excluding +-3 sessions of earnings or not;
        entry next open; hold 1,2,3,5 (exit at close).
- RRV   residual (sector-hedged) short-term reversal: k-day residual return (1,2,3,5) vs best-correlated SPDR,
        tails 5/10%, hold 1,2,3,5, entry close / next open, long-short, plus long-only/short-only.
- MAC   ETF timing on SPY QQQ IWM: VIX term structure (VIX/VIX3M > 1, >1.05), VIX 1-day jump >= 10/20%,
        VIX >= 30, SPY down >= 2/3% day; long at close, hold 1,2,3,5.
- HOLDL user overlay ("if the day trade is wrong, hold up to 5 days"): for every day-trade config above
        (exit day-0 close), twin = if losing at day-0 close, keep holding until back to >= entry at a close or
        5 sessions, whichever first. Reported for every day-trade config as a paired comparison; not a
        separate candidate unless it passes the same bars.

Stage 1 search: 2000-01-01 .. 2017-12-31 (ANL 2012..2017; INS 2006..2017), all three stock universes pooled.
Stage 2 shortlist: per family top-3 configs by search NW t (n >= 300; MAC n >= 60), distinct core params,
        identical-trade duplicates skipped. Luck baseline: per family, 200 random-sign / random-date shuffles
        of the same trade count -> p-value of the best search t.
Stage 3 holdout: 2018-01-01 .. 2026-10-06, evaluated ONCE. PASS = hedged mean > 0, NW t >= 3.0
        (Bonferroni, <= ~24 candidates), positive in 2018-2021 and 2022-2026, positive in each of S&P 500 /
        400 / 600 separately, long and short sides each positive when both traded, raw after-cost mean > 0,
        and for close entries the next-open twin must have positive holdout mean.
Stage 5 economics for any passer: trades/day, capital-constrained portfolio (equal weight, max 10 concurrent),
        annual return, max drawdown, worst month, sensitivity to 2x costs.

## Addendum (2026-10-23, before any EORB result): EORB - "stocks in play" first-hour breakout (day trade)
Inspired by Zarattini/Barbon/Aziz (2024) ORB-on-stocks-in-play. Free 5-minute history is too short, so
hourly bars (2023-11 .. 2026-10, ~1,500 stocks): in play = earnings day 0, or first-hour volume >= 3x/5x
its 14-day average; signal = 09:30-10:30 bar direction with |move| >= 0/0.25/0.5 ATR; follow/fade; entry
10:30; exit 12:30 / close / day+1 close / day+3 close; optional stop at the first-hour bar's far extreme;
gap-agrees filter; size filter (all / S&P 500 / 400+600). Hedge = SPY same interval; tiered costs.
Search < 2025-07-01; holdout >= 2025-07-01 once for the top 6 distinct cores: PASS = mean > 0, NW t >= 2.6,
raw > 0, both sides positive.
