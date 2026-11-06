# year-end-loser-reversal

## Mechanism
In late November and December, investors with taxable accounts sell their biggest losers to realize capital losses before year-end, reducing their tax bill. This forced, tax-driven selling depresses prices below fundamental value. When the tax year closes on December 31, the selling pressure disappears — and often reverses as the same investors re-enter. Stocks that suffered the heaviest tax-loss selling pressure bounce the most in early January.

**Who is on the other side?** Tax-motivated sellers who must sell before December 31 regardless of price; institutional funds closing books by year-end for reporting purposes; retail investors doing year-end portfolio rebalancing. The bounce buyer provides liquidity to the tax seller at a discount — capturing the discount as the year turns.

Mid-cap (S&P 400) is the target universe: the small-cap January effect (S&P 600) is the most studied and arbitraged. Mid-cap is less covered by the arbitrage community, potentially preserving more of the tax-loss bounce.

## Evidence
- Reinganum (1983) and Roll (1983): January effect is strongest in stocks with the largest prior-year losses; bid-ask bounce hypothesis insufficient to explain the full effect.
- Poterba & Weisbenner (2001): Tax-loss selling explains a significant portion of the January effect; reinforced by cross-country evidence (effects only where capital gains taxes exist).
- Ritter (1988): Retail investor year-end selling drives most of the January effect in small/mid-cap stocks.
- Wermers (1999): Mutual fund herding on year-end window dressing amplifies selling in losers.
- Note: january-small-cap-reversal (S&P 600) was previously registered and dropped; mid-cap angle specifically untested in this pipeline.

## Rule sketch
- Universe: S&P 400 (mid-cap)
- Signal: stock is down >= 20% year-to-date as of December 24 close (last 5 trading days of year)
- Entry: BUY at CLOSE on December 26 (or the last-but-2 trading day of the year if Dec 26 is not a trading day)
- Exit: sell at CLOSE on the 5th trading day of January
- Variants to test: (a) entry Dec 29 (last full week); (b) threshold 15% vs 25% YTD loss; (c) add momentum filter (only hold positions from prior-year); (d) 3-day hold; (e) SP500 for comparison
- Filter: exclude any ticker that also had an earnings announcement in the Dec 20-Jan 5 window (earnings-driven moves contaminate the tax-loss signal)

## Data
- `daily(tickers)`: YTD return computed from Jan 1 close to Dec 24 close each year; entry/exit prices
- No filings() data needed — pure calendar + price filter
- **Family**: `calendar_effects` (clean except turn-of-month is at `queued` and quarter-end-window-dressing was `dropped` — no holdout used in this family)
- `live for paper?`: daily() is live — YES; paper runner computes YTD return daily

## Horizon
5 trading days (close-to-close, late December to early January)

## Cost estimate
S&P 400 close entry: ~12.0 bps round trip. After costs, any mean > 12 bps is net positive.

## Expected events
In a typical year, 30-80 S&P 400 stocks are down >= 20% YTD (more in bear years, fewer in bull years). Over a 15-year train window (2000-2015): ~600-1,200 events. Over holdout 2016-2026: ~300-800 events. Adequate, but power may be low in strong bull years — researcher should note if most events cluster in 2001-02, 2008-09, 2022.

## Why it might NOT work
1. Effect is well-known and heavily arbitraged; hedge funds and quant managers now provide liquidity to tax sellers in December, limiting the bounce
2. Mid-cap S&P 400 may be as arbitraged as S&P 600 for this specific trade; the effect may have decayed post-2010
3. january-small-cap-reversal was dropped (Director/user decision — may already be known to be priced in)
4. Sample power is uneven: most qualifying events cluster in bear years (2001, 2002, 2008, 2009, 2022); in strong bull years, few stocks qualify, making holdout t volatile
5. Paper-runner timing: year-end entry requires a close trigger on a specific calendar date; the paper runner needs to compute YTD return on the signal day

## Differs from graveyard
- january-small-cap-reversal used S&P 600 (small-cap); this uses S&P 400 (mid-cap) — different universe, different level of arbitrage competition
- No other year-end or tax-loss reversal idea has been tested in this pipeline
- quarter-end-window-dressing (dropped) was about winners + quarterly cadence; this is about losers + annual cadence

## Source
Reinganum, M. R. (1983). The anomalous stock market behavior of small firms in January. Journal of Financial Economics, 12(1), 89–104. https://doi.org/10.1016/0304-405X(83)90029-6

Poterba, J. M., & Weisbenner, S. J. (2001). Capital Gains Tax Rules, Tax-Loss Trading, and Turn-of-the-Year Returns. The Journal of Finance, 56(1), 353–368. https://doi.org/10.1111/0022-1082.00328
