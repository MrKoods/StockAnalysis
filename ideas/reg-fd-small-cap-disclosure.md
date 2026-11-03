# reg-fd-small-cap-disclosure

## Mechanism
Regulation FD (2000) mandates simultaneous public disclosure; companies that voluntarily file a 7.01 (Reg FD disclosure) are signalling to ALL investors at once — press conferences, investor days, analyst meetings. For large-cap stocks, this information arrives in an already-efficient market where sell-side analysts model the company continuously. For small/mid-cap stocks (fewer analysts, less institutional ownership), a 7.01 filing provides meaningful NEW information to investors who had no other way to access it. The price adjustment should be larger and slower for under-followed names.

**Who is on the other side?** Sellers who do not read SEC filings same-day; retail investors who lag institutional attention by 1-2 days on small-cap names.

## Evidence
- Screen (state/screen.md, 2005-2013): 7.01 is the BEST-performing 8-K type in the event screen: +6.5 bps at 1d (t=2.31, 24,024 events). No other event type exceeds t=2.0. After 20 bps costs: -13.5 bps on the FULL universe (large caps dilute the signal). The small-cap subset should have a higher gross return and cleaner holdout.
- Heflin, Subramanyam & Zhang (2003) "Regulation FD and the Financial Information Environment" — Accounting Review: found Reg FD increased the amount of voluntary disclosure; small firms had larger uncertainty reductions after filings
- Bailey et al. (2003) "Regulation FD and Market Behavior around Earnings Announcements" — Journal of Finance: Reg FD voluntary disclosures had stronger price impact on small/less-followed firms
- Gomes, Gorton & Madureira (2007): firms use 7.01 selectively to disclose positive developments; voluntary disclosure signals management confidence

## Rule sketch
- Universe: S&P 400 + S&P 600 (mid and small cap; ~1,000 stocks) that file a 7.01 8-K
- Entry: buy at open on the first trading day after the 7.01 filing acceptance timestamp (if filed after 4 PM ET, buy next open; if before 4 PM, same-day open may be missed — use day+1 open to be conservative)
- Exit: sell at open 1 trading day later (hold = 1 day)
- Variants: (a) hold 1d vs 3d; (b) S&P 600 only vs S&P 400+600; (c) filter filings by text length (longer filings = more substantive disclosure); (d) add SPY/sector hedge
- Expected events (small/mid cap subset, train 2005-2013): ~8,000-10,000 events (40-50% of 24,024 total 7.01 filings are mid/small cap)

## Data
- `filings(forms=['8-K'], items=['7.01'], tickers=small_mid_cap)`: filing date + acceptance time
- `daily(tickers)`: OHLCV for entry/exit pricing
- **Family train period**: 2005-2013 (screen already used this — the train run will refine within this period); holdout 2014-2026

## Horizon
1 trading day (open+1 to open+2)

## Cost estimate
~20-25 bps round trip for mid-cap; ~30-35 bps small-cap (use mid-cap universe for first test to keep costs ~20 bps)

## Why it might NOT work
1. The full-sample screen signal (t=2.31) is below the best-of-57 luck threshold (2.84) — small-cap subset may not sharpen it enough to reach t>3 in holdout
2. Many 7.01 filings accompany earnings releases or M&A announcements (which also carry other items); the independent Reg FD disclosure may be rarer than the raw count suggests
3. After costs (20-25 bps), the edge is thin — requires the small-cap gross return to be meaningfully above the full-sample +6.5 bps
4. Algorithmic news scrapers have reduced the retail information lag that this idea depends on

## Differs from graveyard
- Earnings gap continuation (graveyard): triggered by price gap at earnings, not an SEC filing; different mechanism
- Analyst rating actions (graveyard): analyst opinion change, not a company-initiated disclosure event
- Split-announcement-drift (dead): different event type (corporate action vs. voluntary disclosure)

## Source
Screen result: state/screen.md (7.01, t=2.31 at 1d, 2005-2013)
Heflin et al. (2003): https://doi.org/10.2308/accr.2003.78.1.1
Bailey et al. (2003): https://doi.org/10.1111/1540-6261.00580
