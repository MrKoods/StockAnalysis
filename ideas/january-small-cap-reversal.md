# january-small-cap-reversal

## Mechanism
Institutional investors sell their worst-performing stocks in December to crystallize tax losses before year-end. This abnormal selling pressure depresses prices below fair value. In the first few days of January, the sellers are done and the buying resumes — prices partially reverse. The effect is concentrated in small-cap stocks (less analyst coverage, less ETF-driven repricing) and in the prior year's biggest losers (maximum selling pressure during December).

**Who is on the other side?** Institutions that harvested losses in December; they are not sellers in early January, so the market clears at a higher price.

## Evidence
- Reinganum (1983) "The Anomalous Stock Market Behavior of Small Firms in January" — Journal of Financial Economics: documents January premium for small firms 1963-1979
- Keim (1983) "Size-Related Anomalies and Stock Return Seasonality" — Journal of Financial Economics: ~25% of annual size premium earned in first 5 days of January
- Roll (1983) "Vas ist Das? The Turn-of-the-Year Effect and the Return Premia of Small Firms" — Journal of Portfolio Management: tax-loss hypothesis
- Ritter (1988) "The Buying and Selling Behavior of Individual Investors at the Turn of the Year" — Journal of Finance: confirms institutional tax-loss selling in December and reversal in January
- Booth & Keim (2000): some persistence through 1990s even after publication; weakened but not eliminated

## Rule sketch
- Universe: S&P 600 small-cap stocks that declined ≥15% over the prior calendar year (Oct 1 to Dec 15 to avoid very recent events)
- Entry: buy at close on last trading day of December (Dec 31 or last NYSE session)
- Exit: sell at close on 5th trading day of January
- Variants: (a) loss threshold 10% vs 20% vs 30%; (b) hold 3 vs 5 vs 10 days; (c) add price momentum (losers that have ALSO started to stabilize in Dec); (d) full S&P 600 without loss filter as comparison
- Expected events: ~100-200 qualifying stocks/year × 20+ years = 2,000-4,000 total; each year is 1 cluster (n ≈ 20 independent annual observations — researcher must cluster by year)
- **Power note**: with only ~20 annual clusters, a t-test requires a strong per-year signal (>0.5 Sharpe annualized). This idea is borderline on power — researcher should run a bootstrap or calendar-year t-test

## Data
- `daily(tickers)` OHLCV 1999-2026: prior-year return computed from Dec 31 close to Dec 31 close; entry/exit are closes on specific calendar dates
- No additional data sources required

## Horizon
~5 trading days (Dec 31 close to Jan 5-7 close)

## Cost estimate
~25 bps round trip for S&P 600 small-cap names

## Why it might NOT work
1. Very widely known since 1983 — large institutions pre-empt the January reversal by buying in late December, pulling the return forward or eliminating it
2. Only 1 trade per stock per year → ~20 annual clusters, so statistical power is marginal unless the effect is large
3. Tax-loss harvesting has become more efficient (wash-sale rule circumvention via ETFs) → less year-end distortion
4. ETF-based index investing has reduced the ability to selectively sell individual losers; S&P 600 membership is well-tracked by passive funds

## Differs from graveyard
- Turn-of-month (registered idea): monthly cycle driven by pension fund flows, not tax-loss selling; triggers 12 times/year vs 1 time
- Daily classics (graveyard): pure price-pattern rules with no calendar/structural basis
- Overnight reversal (graveyard): 1-day hold based on prior price move, not calendar + prior-year performance

## Source
Keim (1983): https://doi.org/10.1016/0304-405X(83)90025-9
Reinganum (1983): https://doi.org/10.1016/0304-405X(83)90026-0
Ritter (1988): https://doi.org/10.1111/j.1540-6261.1988.tb04565.x
