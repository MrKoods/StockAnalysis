# activist-13d-long

## Mechanism
When a hedge fund or activist investor crosses the 5% ownership threshold with intent to influence management, they must file a Schedule 13D with the SEC within 10 days. The 13D discloses the activist's agenda (share buyback, board seats, strategic review, sale of company). Brav, Jiang, Thomas & Partnoy (2008) document a mean abnormal return of +7.2% around initial 13D filings, with continued positive drift over 20+ days as the activist presses their thesis. Klein & Zur (2009) confirm large positive returns for hedge-fund-activist targets.

**Who is on the other side?** Passive institutional holders who do not monitor 13D filings in real time; indexers who must hold the target regardless of corporate events; retail investors who learn of activist involvement from financial media days later.

The stock continues to drift up as: (a) other activists pile in ("wolf pack"), (b) merger-arbitrage funds enter on acquisition likelihood, (c) the company's management proactively announces concessions to forestall proxy fights.

## Evidence
- Brav et al. (2008): 13D filings show +7.2% abnormal return at announcement, with drift continuing 20 days. Sample: 1994-2007.
- Klein & Zur (2009): Hedge fund 13D targets earn +10.2% in the year after filing; entrepreneurial activism earns even more.
- Edmans (2009): Blockholder presence generally positive for firm value; 13D (intent to influence) is the strongest signal.
- Effect is documented as persisting after the Brav et al. paper; activism has grown post-2010 but so has media attention — effect may have attenuated.

## Rule sketch
- Universe: S&P 1500 (the catalog's coverage universe)
- Signal: acceptance of Form SC 13D (NOT SC 13D/A amendments — initial filing only) for a company in the universe
- Entry: buy at CLOSE on the detection day (the day filings() first reports the SC 13D in the SEC daily index — same as dispatch day)
- Exit: sell at close+4 (hold 3 trading days close-to-close)
- Variants to test: (a) 1d hold; (b) 5d hold; (c) SP500 only vs. SP1500; (d) filter: exclude 13Ds filed by existing large holders amending to exactly 5% (new activists only)
- Note: researcher should check that filings() indexes SC 13D by the TARGET company ticker, not the filer's ticker; if `filings(forms=['SC 13D'])` returns few events, try `forms=['13D']` as a variant form name

## Data
- `filings(forms=['SC 13D'], tickers=sp1500)`: event dates (acceptance timestamp); filter to initial SC 13D (not SC 13D/A)
- `daily(tickers)`: OHLCV for entry/exit + return calculation
- **Family**: `activist_13d` (new, entirely clean; no prior screen or researcher use)
- `live for paper?`: filings() is live (SEC daily index each dispatch) — YES

## Horizon
3 trading days (close-to-close, detection day to close+3)

## Cost estimate
S&P 500 targets: ~6.6 bps round trip (close); S&P 400 targets: ~12.0 bps. Expected net: target mean well above costs given documented 700+ bps literature return. Even if attenuated post-publication, a 50-100 bps 3-day mean would clear costs at close entry.

## Expected events
Rough estimate: ~100-250 initial SC 13D filings/year across S&P 1500. Holdout 2014-2026: ~1,200-3,000 events if full universe. Adequate for t >= 3.0 at holdout.

## Why it might NOT work
1. By the time 13D is public (10 days after crossing 5%), much of the stock move has already occurred on rumor/unusual volume; open+T entry captures only residual drift
2. Close-to-close entry requires the filing to be detected at the 2:51 PM dispatch; filings submitted after the daily EDGAR index cutoff appear next weekday
3. Post-publication decay: Brav et al. (2008) is widely cited; arbitrageurs now monitor 13D filings in real time, compressing the window
4. Survivorship: only companies currently in S&P 1500 included; troubled targets that were delisted post-activism are excluded, overstating returns
5. Event count may be lower than estimated if SC 13D targets are rarely in the S&P 1500 universe (activists often target smaller companies)

## Differs from graveyard
- No activist or 13D idea has ever been tested in this codebase
- insider-cluster-buys (dead): Form 4 officer transactions, not institutional activist filings; different family, different universe
- SC 13G (passive 5%+ holder): deferred to "needs data" (Edmans 2009 shows 13G is weak; 13D is the strong signal)

## Source
Brav, A., Jiang, W., Thomas, R. S., & Partnoy, F. (2008). Hedge Fund Activism, Corporate Governance, and Firm Performance. The Journal of Finance, 63(4), 1729–1775. https://doi.org/10.1111/j.1540-6261.2008.01373.x

Klein, A., & Zur, E. (2009). Entrepreneurial Shareholder Activism: Hedge Funds and Other Private Investors. The Journal of Finance, 64(1), 187–229. https://doi.org/10.1111/j.1540-6261.2009.01433.x
