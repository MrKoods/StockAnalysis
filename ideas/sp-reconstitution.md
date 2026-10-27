# sp-reconstitution

## Mechanism
When S&P announces an addition to the S&P 400 or S&P 600, every passive index fund and ETF tracking that index must purchase the stock before the effective date (typically 5-7 trading days after announcement). This creates a known, concentrated, price-insensitive demand shock. The stock drifts up between announcement day and effective date as front-runners and then index funds buy. After the effective date the effect reverses.

**Who is on the other side?** Pre-announcement sellers and early arbitrageurs who got out; post-effective-date the direction reverses as early buyers exit to index funds.

**Why S&P 400/600, not S&P 500?** The S&P 500 addition effect is heavily arbitraged and often fully priced within minutes of announcement. S&P 400/600 additions involve smaller stocks with less analyst coverage, less intraday arbitrage capital, and longer-duration index fund buying pressure because the affected ETFs (MDY, IJH, IJR, VIOO) have less active front-running by hedge funds.

## Evidence
- Harris & Gurel (1986): founding paper on S&P 500 price pressure; abnormal return 3%+ on addition day
- Shleifer (1986): demand curves for stocks slope down → index additions generate lasting (not temporary) price pressure
- Wurgler & Zhuravskaya (2002): adds with poor substitute securities have larger effects → S&P 400/600 more vulnerable
- Chen, Noronha & Singal (2004): S&P 500 addition effect has decayed; suggests migrating to smaller indices
- Practitioners: known alpha source, especially for S&P 600 (Russell 2000 effect analog)

## Rule sketch
- Signal: stock announced for addition to S&P 400 or S&P 600 (announcement date = A)
- Entry: buy at open on A+1 (day after announcement, before full index-fund buying)
- Exit: sell at open on effective date E (when index funds must have completed buying)
- Typical A→E gap: 5 trading days; test variants of 3, 5, and 7 trading days
- Also test: long addition + short a sector peer (hedged version)

## Data needed
**NOT yet in archives.** Required:
- S&P 400/600 reconstitution announcement dates (not effective dates alone)
- Free source: S&P Global press releases (spglobal.com) — a one-time historical scrape 2006-2026 would yield ~300-400 events per index
- Alternative: academic dataset from CRSP or cleaned CSV on SSRN replication papers
- Effective dates only (no announcement dates) would introduce look-ahead bias — must get announcement dates

## Horizon
3-7 trading days

## Cost estimate
~20-30 bps round trip (S&P 400/600 names; some are illiquid at time of addition since they were previously smaller)

## Why it might NOT work
1. Effect largely arbitraged in S&P 500; S&P 400/600 may be converging to the same fate
2. Requires sourcing historical announcement dates (not a blocker but pre-work needed)
3. Announcement → effective date gap has shortened since 2002 (S&P now moves faster), compressing the window
4. Sample size: ~30-50 additions per year per index → 20 years = ~700 events, reasonable but not huge

## Differs from graveyard
No reconstitution/index-addition idea in graveyard. Mechanism is forced institutional flows, not price patterns or earnings.

## Source
Chen, Noronha & Singal (2004): https://doi.org/10.1093/rof/rfh006
Wurgler & Zhuravskaya (2002): https://doi.org/10.1111/1468-0327.00088
Harris & Gurel (1986): https://doi.org/10.1111/j.1540-6261.1986.tb04550.x
