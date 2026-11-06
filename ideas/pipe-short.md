# pipe-short

## Mechanism
Item 3.02 is filed when a company completes an unregistered equity sale (commonly a PIPE — Private Investment in Public Equity). PIPEs are structured at a discount to market price; they dilute existing shareholders and are typically used by companies that cannot access the public markets at current prices (distressed, speculative, or in need of immediate capital). Placement agents and PIPE investors routinely hedge by shorting the stock before the shares become freely tradeable, creating a persistent downward price drift in the days following the 8-K.

**Who is on the other side?** Retail investors and passive holders who do not parse 8-K item codes; systematic strategies that screen for earnings or balance-sheet signals only; the company itself (which cannot buy back shares during the placement lockup).

## Evidence
- Screen (tools/screen.py, 2005-2013, S&P 1500): item 3.02 excess return at 3-day hold = -37.9 bps vs SPY + stock drift, t = -1.70. After close-entry costs of ~15 bps round trip: net +22.9 bps target.
- Brophy, Ouimet & Sialm (2009): Hedge funds investing in PIPEs earn substantial abnormal returns; they hedge by short-selling the stock, creating documented downward price pressure on the target after announcement.
- Chaplinsky & Haushalter (2010): "Toxic PIPEs" — floating-price convertibles create especially large and persistent negative drift; ordinary fixed-price PIPEs show more moderate but still negative drift.
- Raw screen excess is -37.9 bps with t=-1.70; screen ran only 3 variants (1d/3d/5d) on the 2005-2013 period — family has 0 researcher search variants, full holdout 2014-2026 is clean.

## Rule sketch
- Universe: S&P 1500
- Signal: acceptance of an 8-K with item 3.02 for a company in the universe
- Entry: SHORT at CLOSE on the detection day (dispatch-day close — avoids wide open spreads)
- Exit: cover at close+3 (3-day hold close-to-close)
- Variants to test: (a) 1d hold; (b) 5d hold; (c) SP400+SP600 only (smaller companies do more PIPEs); (d) filter: exclude 3.02 events that co-occur with a 2.02 earnings release (already priced) or a 1.01 large deal (dilution may be strategic)
- Direction: SHORT; researcher must confirm paper_runner.py short support

## Data
- `filings(items=['3.02'], tickers=sp1500)`: event dates (acceptance timestamp)
- `daily(tickers)`: OHLCV for entry/exit + return calculation
- **Family**: `8k_3_02` (screen used 2005-2013 as 3 variants: 1d/3d/5d; holdout 2014-2026 is CLEAN)
- `live for paper?`: filings() is live (SEC daily index each dispatch) — YES

## Horizon
3 trading days (close-to-close, detection day to close+3)

## Cost estimate
Close entry: S&P 500 ~6.6 bps round trip, S&P 400 ~12.0 bps, S&P 600 ~21.8 bps. With S&P 1500 mix ~12-15 bps round trip. Net target ~+22-25 bps per trade.

## Expected events
Catalog: 3,635 total 3.02 events (1993-2026). Screen had 1,251 in 2005-2013. Holdout 2014-2026 ~2,000+ events. Adequate for t >= 3.0.

## Why it might NOT work
1. Many 3.02 filers are small-cap distressed companies trading at very high spreads; in our S&P 1500 universe the PIPE population may be biased toward the least-distressed (weakening the signal)
2. Post-2010, PIPE terms have evolved; "toxic" convertible PIPEs were heavily regulated after SEC scrutiny — the worst cases may be excluded from our universe
3. Screen t=-1.70 is marginal (below 2.0); could be luck at 3 variants (luck threshold ~1.5 for 3 variants, bar barely cleared)
4. Borrowing cost for short is not modelled in the backtest; if the target stock is on hard-to-borrow list (common for distressed names), short may not be executable in paper at Webull
5. 2.05 restructuring (similar mechanism: bad-news overhang) ran NEGATIVE in train research; watch for the same inversion

## Differs from graveyard
- No PIPE or 3.02 idea has been tested in this codebase; graveyard has no overlap
- 8k_2_05 restructuring-bounce (dead) was a LONG idea; this is a SHORT; different mechanism (dilution vs. kitchen-sink)
- analyst-initiation-buy (dead): opposite direction, different signal type

## Source
Brophy, D. J., Ouimet, P. P., & Sialm, C. (2009). Hedge Funds as Investors of Last Resort? The Review of Financial Studies, 22(2), 541–574. https://doi.org/10.1093/rfs/hhn023

Chaplinsky, S., & Haushalter, D. (2010). Financing Under Extreme Uncertainty: Contract Terms and Returns to Private Investments in Public Equity. The Review of Financial Studies, 23(7), 2789–2820. https://doi.org/10.1093/rfs/hhq019
