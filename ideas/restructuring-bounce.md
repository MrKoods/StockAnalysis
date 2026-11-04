# restructuring-bounce

## Mechanism
When a company files an 8-K disclosing exit costs or restructuring charges (item 2.05), the market tends to overreact negatively in the short term — pricing in the charge as ongoing bad news. But restructuring announcements are often a "kitchen sink" event: management clears accumulated losses in one go to reset the earnings baseline. Studies find that in the 1-5 days after the announcement, prices partially recover as investors process the forward-looking implication (leaner cost structure, cleaner future earnings). The effect is sharpest for small/mid-cap stocks where analyst coverage is sparser and the initial overreaction is larger.

**Who is on the other side?** Sellers who react to the negative charge headline without recognising the kitchen-sink signalling; momentum algorithms that extrapolate the initial negative reaction.

## Evidence
- Screen (state/screen.md, 2005-2013): 8-K item 2.05 is the 5th-strongest signal in the event screen at 3d: +31.6 bps excess (t=1.79, 940 events). After 20 bps round-trip costs: +11.6 bps. This is for the full S&P 1500; a small/mid-cap subset should have a sharper signal.
- Kinney & Trezevant (1997) JAAF: firms using large special charges (of which restructuring charges are the primary type) show positive subsequent abnormal returns; market initially underweights the cleansing signal.
- Elliott & Shaw (1988) TAR: "big bath" accounting (large one-time write-downs/charges) followed by earnings recovery; market recognises the signal within a few quarters, with partial price recovery beginning in the days surrounding the announcement.
- Restructuring literature (Cascio 2002): ~70% of restructuring announcements lead to improved profitability within 2 years; the market discounts this too aggressively at announcement.

## Rule sketch
- Universe: S&P 400 + S&P 600 (small and mid cap) that file an 8-K with item 2.05
- Entry: buy at open on the SECOND trading day after the 8-K acceptance timestamp (open+1 is too close to the initial reaction; open+2 catches the beginning of the recovery drift)
- Exit: sell at open 3 trading days after entry (open+5 from event)
- Variants: (a) hold 3d vs 5d; (b) add size filter (S&P 600 only); (c) add SPY/sector hedge; (d) filter to filings after market close only
- Expected events (small/mid-cap, train 2005-2013): ~940 total screen events × 50% small/mid-cap ≈ 470 events (52/yr); holdout 2014-2026 clean

## Data
- `filings(forms=['8-K'], items=['2.05'], tickers=small_mid_cap)`: event date + acceptance time
- `daily(tickers)`: OHLCV for entry/exit pricing + size filter
- **Family train period**: 2005-2013 (screen already used this); holdout 2014-2026

## Horizon
3 trading days (open+2 to open+5 from event date)

## Cost estimate
~25-35 bps round trip (small-cap: 30-35 bps; mid-cap: 20-25 bps)

## Why it might NOT work
1. Screen t=1.79 is below the best-of-57 luck threshold (2.84) — the small-cap subset may not be meaningfully sharper
2. Power risk: ~52 events/yr in small/mid-cap subset → ~624 holdout events over 12 years; feasible but researcher must verify
3. Restructuring announcements cluster in market downturns (2008-09, 2020) where small-cap volatility is very high, inflating SE
4. Many 2.05 filings accompany earnings releases (item 2.02 + 2.05 together) — the return may be driven by the earnings surprise, not the restructuring signal

## Differs from graveyard
- Split-announcement-drift (dead): different event type; no kitchen-sink mechanism
- insider-cluster-buys (dead): triggered by insider transactions, not accounting disclosures

## Source
Screen result: state/screen.md (2.05, t=1.79 at 3d, 2005-2013)
Kinney & Trezevant (1997): https://doi.org/10.1177/0148558X9701200201
Elliott & Shaw (1988): https://doi.org/10.2308/accr.1988.63.1.91
