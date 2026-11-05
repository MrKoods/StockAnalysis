# debt-acceleration-bounce

## Mechanism
An 8-K item 2.04 filing reports that a debt covenant has been triggered, requiring early repayment or renegotiation. The initial market reaction is usually negative — headlines read "debt acceleration" and sellers respond. But for companies that remain in the S&P 1500 (a solvency filter), the act of publicly disclosing the trigger is itself a resolution signal: management is managing the situation, not hiding it. Short-sellers who drove the stock down are overexposed to a likely resolution. This is the same kitchen-sink mechanism as the restructuring-bounce idea (2.05): disclosure of a contained negative event resolves uncertainty and allows the stock to rebound.

**Who is on the other side?** Sellers reacting to the "debt acceleration" headline without differentiating resolved from fatal triggers; systematic short-sellers who flag debt-covenant news.

## Evidence
- Screen (state/screen.md, 2005-2013): 8-K item 2.04 is the 2nd-strongest signal in the event screen at 3d: +60.0 bps excess (t=1.99, 206 events). After 20 bps round-trip costs: +40 bps. 5d also strong: +76.0 bps (t=1.99). These are raw screen numbers; a focused researcher test could refine this.
- 2.04 screen t=1.99 exceeds the restructuring-bounce screen t=1.79 (registered idea); the mechanism is similar but events are rarer and more severe.
- Engelberg, Reed & Ringgenberg (2012) RFS: short sellers close positions rapidly after negative news resolution, creating post-disclosure rallies in stocks that survive the event.
- Ohlson (1980) JAR: distress-resolution bounce is well-documented; companies that file disclosures of contained distress events (and survive to file them) outperform in the subsequent 1-5 days vs the initial reaction.

## Rule sketch
- Universe: S&P 1500
- Signal: 8-K with item 2.04 filed; company is in S&P 1500 at time of filing (solvency filter already applied by universe)
- Entry: buy at open on the NEXT trading day after the 8-K acceptance timestamp is public (open+1)
- Exit: sell at open+4 (3-day hold)
- Variants: (a) small/mid-cap only (more overreaction); (b) filter to after-close filings; (c) 5-day hold (screen shows 5d also t=1.99); (d) add sector hedge

## Data
- `filings(forms=['8-K'], items=['2.04'], tickers=sp1500)`: event date + acceptance time
- `daily(tickers)`: OHLCV for entry/exit + return calculation
- **Family**: `8k_2_04` (screen 2005-2013 used; holdout 2014-2026 clean; 0 search variants consumed by researcher)

## Horizon
3 trading days (open+1 to open+4 from event date)

## Cost estimate
~25-35 bps round trip (small-cap: 30-35 bps; mid-cap: 20-25 bps). After costs at screen rates: +40 bps net — cost-feasible if the effect holds.

## Why it might NOT work
1. Only ~18 events/yr in S&P 1500; holdout has ~230 events over 12 years — moderate power; large SE
2. Screen had only 206 events in 9 years → statistically fragile baseline; t=1.99 is below best-of-57 luck threshold
3. Companies filing 2.04 are financially distressed; large price moves inflate variance, reducing t
4. Survivorship bias: only S&P 1500 survivors appear in our universe; true universe of 2.04 filers includes many subsequent delistings
5. If a 2.04 filing is concurrent with 2.05 restructuring (overlapping items), the return driver is ambiguous — researcher should check for 2.04+2.05 co-filings

## Differs from graveyard
- restructuring-bounce (at idea stage, item 2.05): same mechanism, different severity; 2.04 events are rarer and involve triggered debt defaults vs voluntary restructuring
- split-announcement-drift (dead): entirely different event type
- insider-cluster-buys (dead): transaction-triggered, not disclosure-triggered

## Source
Screen result: state/screen.md (2.04, t=1.99 at 3d, 2005-2013)
Engelberg, Reed & Ringgenberg (2012): https://doi.org/10.1093/rfs/hhr097
Ohlson (1980): https://doi.org/10.2307/2490395
