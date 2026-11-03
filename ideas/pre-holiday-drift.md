# pre-holiday-drift

## Mechanism
Stocks reliably outperform in the 1-2 sessions before major US market holidays. The mechanism is two-sided: (1) short sellers close positions before extended closures to avoid unhedged overnight/weekend exposure, reducing supply; (2) retail and institutional investors deploy cash ahead of holidays when activity is elevated. The effect is not information-driven — it repeats on a fixed calendar schedule with ~8 opportunities per year.

**Who is on the other side?** Short sellers covering before closure and market makers reducing inventory ahead of multi-day gaps.

## Evidence
- Lakonishok & Smidt (1988) "Are Seasonal Anomalies Real? A Ninety-Year Perspective" — DJIA 1897–1986: pre-holiday days earn ~10x the average daily return; most dramatic in trading-day before closure
- Ariel (1990) "High Stock Returns before Holidays: Existence and Evidence on Possible Causes" — Journal of Finance: confirms US equities 1963–1982, identifies reduced selling pressure as mechanism
- Cadsby & Ratner (1992): replicates in 10 international markets, suggesting it is not US-specific
- Effect has been documented as persistent even after publication (Kim & Park 1994 replicate through 1990; Chong et al. 2005 through 2004 for US)

## Rule sketch
- Universe: S&P 1500 (or S&P 500 for large-cap version)
- Entry: buy at close 2 sessions before major NYSE holiday (day T-2)
- Exit: sell at close the session immediately before the holiday (T-1); hold = 1 day
- Variants: (a) T-1 entry / T-1 exit (same-day entry morning, exit afternoon); (b) only large US holidays (Thanksgiving, Christmas, 4th July, New Year) vs. all 8-9 NYSE closures; (c) S&P 600 small-cap subset; (d) add SPY hedge
- Expected events: ~8-9 holidays/year × 1500 stocks × 20+ years = large sample; clusters by holiday-date (~160 independent dates)

## Data
- `daily(tickers)` OHLCV 1999-2026: all that is needed; holiday dates from NYSE calendar (known)
- No additional data sources required

## Horizon
1 trading day (buy T-2 close, sell T-1 close)

## Cost estimate
~10 bps round trip for S&P 500 names; ~20-25 bps for S&P 600 small caps

## Why it might NOT work
1. Very widely published since 1988 — may be fully arbitraged in large caps; small-cap version adds costs
2. The 1-day hold concentrates the effect in a single session; a large news event that day would override the calendar signal
3. Modern ETF arbitrage and algorithmic market-making may have eliminated most pre-close inventory reduction
4. The original evidence is from pre-1990 data; persistence is debated post-2000

## Differs from graveyard
- Turn-of-month (calendar_effects): different trigger (month boundary vs. holiday calendar), different mechanism (fund-flow cycle vs. short-cover), different frequency (12× vs. 8-9× per year)
- Daily classics (graveyard): pure price patterns with no calendar event as trigger
- Overnight reversal (graveyard): 1-day hold but triggered by prior-day price move, not a fixed calendar event

## Source
Lakonishok & Smidt (1988): https://doi.org/10.1111/j.1540-6261.1988.tb04586.x
Ariel (1990): https://doi.org/10.1111/j.1540-6261.1990.tb02424.x
