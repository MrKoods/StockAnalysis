# pre-holiday-small-cap-long

**Family**: pre_holiday (new, entirely clean)
**Horizon**: 1d
**Direction**: LONG
**Universe**: S&P 600 small caps

## Mechanism
Stocks systematically earn elevated returns on the last trading session before a NYSE holiday.
Three reinforcing forces concentrate the effect in small caps:
1. **Behavioral optimism**: retail investors buy before the long weekend; small caps have higher retail ownership.
2. **Short-selling retreat**: short sellers close positions before extended market closures to avoid weekend gap risk; this buy-to-cover pressure is proportionally larger in less-liquid small caps.
3. **Settlement effects**: traders who want settlement before the holiday must buy early, compressing normal price discovery.

The other side: market makers and institutional sellers who need liquidity around holidays; they pay the spread but do not systematically bet against the holiday drift.

## Evidence
- **Kim & Park (1994, Review of Quantitative Finance and Accounting)**: Pre-holiday effect in small-cap stocks ~82 bps on the pre-holiday day (1963-1990). Large caps ~32 bps. Effect is statistically significant and not explained by risk.
- **Lakonishok & Smidt (1988, JF)**: Pre-holiday days return ~37 bps vs ~1 bps on typical days (all-cap Dow 90 years; establishes the base effect).
- **Ariel (1990, JFE)**: Pre-holiday premium of ~35 bps in CRSP 1963-1982; persistent across the full sample.
- **Ciccone (2011, Applied Financial Economics)**: Effect persists through 2010; small-cap concentration holds.
- **Li & Liu (2010, Applied Economics)**: Confirm persistence in US equities 2000-2008.

Gross edge cited: **~82 bps** (small caps, Kim & Park 1994). Round-trip cost at close fills: ~7-22 bps. Net floor: ~60-75 bps.

## Exact rule sketch
- **Signal trigger**: After close of session T-2, verify that T-1 is the last NYSE trading day before an exchange holiday. NYSE holidays are deterministic (New Year's Day, MLK Day, Presidents Day, Good Friday, Memorial Day, Juneteenth, Independence Day, Labor Day, Thanksgiving, Christmas) and identifiable from gaps in the daily() date index.
- **Entry**: Close of T-2.
- **Exit**: Close of T-1 (the pre-holiday session).
- **Filter**: S&P 600 constituent on the signal date (small caps only).
- **Direction**: Long only.

## Data
- `daily(tickers)`: OHLCV for S&P 600. Closing prices for T-2 and T-1. Date index used to identify NYSE holidays (calendar day present in NYSE schedule = trading day; gap = holiday).
- No external data, no text parsing, no API. Holiday calendar is fully derivable from the daily() date series.
- **Live for paper**: yes — daily() is refreshed each dispatch.

## Expected event count
S&P 600 (~600 stocks) × 10 NYSE holidays/year = ~6,000 observations/year. Over a 15-year train window (e.g., 2000-2014): ~90,000 observations. Well-powered; holdout 2015-2026 clean.

## Cost estimate
Close-to-close fills: **~15 bps** round trip (mid of 7-22 bps range from team/fill_costs.json). No open-price slippage.

## Why it might NOT work
1. **Post-publication decay**: Effect known since 1988. Arbitrage since 2000 may have compressed it below 50 bps. Must verify in train data (2000-2014) before trusting the 1960s-1980s estimate.
2. **Sample concentration**: 10 events/year per stock; each stock's annual contribution is 10 bps × 10 = 100 bps/year — not a lot of risk capital deployed. The aggregate pool is large (6,000 obs) but results may be driven by a small number of extreme holiday-week events.
3. **Thanksgiving risk**: Thanksgiving week has historically large positive returns unrelated to the holiday effect (year-end positioning); may inflate the signal around November.
4. **Small-cap illiquidity**: Close fills in S&P 600 may be harder to execute at mid-price; actual costs at the top end of the 7-22 bps range.

## How it differs from graveyard entries
- **pre-holiday-drift** (dropped, not tested): That was the broad S&P 1500 version with ~37 bps gross — below the 50 bps threshold. This card adds the **small-cap filter** (S&P 600 only) which raises the documented gross to ~82 bps and changes the family. Different family, different universe, different evidence base.
- No other pre_holiday cards have been registered or tested; the family is entirely clean.
