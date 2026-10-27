# insider-cluster-buys

## Mechanism
When multiple different corporate insiders (officers + directors) independently purchase shares of the same company in the same rolling 5-day window, the information signal is far stronger than a single insider purchase. Each insider has separate private information channels; independent convergence on buying is unlikely to be coincidence. The market often fails to fully aggregate these signals promptly because Form 4 filings arrive staggered over 2-business-day windows and are scattered across EDGAR.

**Who is on the other side?** Retail and short-term institutional sellers who miss the clustering in SEC filings; they provide liquidity the cluster signal can exploit.

**Differs from insider-officer-buys (queued):** That idea buys after a single officer purchase >= $100k. This idea requires >= 2 distinct insiders (any combination of officers and directors) each making >= $25k open-market purchases within the same 5-calendar-day window. A single large purchase does not trigger it; independent convergence is required.

## Evidence
- Seyhun (1998) "Investment Intelligence from Insider Trading" (MIT Press): cluster buys generate higher abnormal returns than isolated buys
- Lakonishok & Lee (2001) "Are Insider Trades Informative?" - RFS: directors + officers together beat either group alone
- Jeng, Metrick & Zeckhauser (2003): open-market purchases (not exercises) are the informative signal; cluster amplifies this
- Practitioners: cluster insider buying is a standard screen at many long/short equity funds

## Rule sketch
- Universe: S&P 500 + S&P 400 (mid/large cap)
- Signal: on date D, there are >= 2 distinct insiders with open-market BUY transactions for the same ticker in the 5-calendar-day window ending D, each >= $25k, total cluster >= $75k
- Entry: buy at open on D+1 (day after last filing day)
- Exit: sell at close on D+5 (hold 5 trading days)
- Variants: threshold on n_insiders (2 vs 3), dollar threshold, hold period (3/5/10 days)

## Data
- insider() from SEC Form 3/4/5, 2006+: contains transaction_type, shares, price, insider role
- daily() for price data
- No additional data needed; all in V3 archives

## Horizon
3-5 trading days

## Cost estimate
~15 bps round trip (mid-cap; lower liquidity than pure S&P 500)

## Why it might NOT work
1. The insider family already has 1 holdout used (and insider-officer-buys is queued) - fresh test periods are limited
2. Cluster events are rare → small sample, wide confidence intervals
3. SEC 2-day filing window means cluster is sometimes recognized by the market before we see it
4. Insiders sometimes buy cooperatively for non-informational reasons (employee share purchase plans, scheduled 10b5-1 plans)

## Differs from graveyard
- Graveyard mentions no insider cluster analysis; insider family had 1 holdout (result unknown from context)
- Single-officer buys are queued as a separate idea; this is a distinct signal requiring independent confirmation from multiple insiders

## Source
Seyhun (1998) Investment Intelligence from Insider Trading, MIT Press
Lakonishok & Lee (2001): https://doi.org/10.1093/rfs/14.1.79
