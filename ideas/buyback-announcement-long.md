# buyback-announcement-long

**Family:** 8k_8_01  
**Horizon:** 20 days  
**Entry:** entry_session close (day-0 same_close)  
**Direction:** LONG

## Mechanism
Company announces an open-market share repurchase authorization in an 8-K item 8.01 press release.
Management signals undervaluation (the market over-reacts to uncertainty about whether the buyback will
actually be executed). Investors under-react to the commitment-to-buy signal: repurchase programs are
not legally binding, so market participants discount them even though firms do execute them. The result
is a multi-week upward drift as shares are repurchased in the open market, reducing float and creating
sustained demand. Short sellers who are short must cover into a shrinking float.

## Evidence
- **Ikenberry, Lakonishok & Vermaelen (1995) JFE** "Market Underreaction to Open Market Share Repurchases":
  12% 4-year abnormal return, concentrated in the first 1-3 months (~200 bps in 20 trading days)
- **Peyer & Vermaelen (2009) JFQA** "The Nature and Persistence of Buyback Anomalies":
  2.4% 4-factor alpha in the first month (~200 bps per trade); effect persists post-publication
- Undifferentiated 8.01 screen: -7.6 bps at 5d (t -1.58) — diluted by non-buyback events in "other events"
- special-dividend-drift-long (8k_8_01, same family, dead): different event; Skeptic FAIL not holdout FAIL

## Rule sketch
1. Signal: `rd.filings(forms=['8-K'], items=['8.01'])` where `rd.filing_text(df)` body contains
   "repurchase" OR "share repurchase program" OR "buyback" (case-insensitive)
2. Exclude: mentions of "repurchase agreement" (repo contracts, not equity repurchases)
3. Entry: close of `entry_session` (same_close)
4. Exit: close 20 trading days later
5. Hedge: `rd.hedge_ticker` (SPY / IJH / IJR by market cap)
6. Universe: S&P 1500

## Data
- `rd.filings(forms=['8-K'], items=['8.01'])` → entry_session, ticker
- `rd.filing_text(df)` → text column (keyword filter for repurchase authorization)
- `rd.daily(tickers)` → entry close, exit close
- `rd.hedge_ticker` → hedge ETF and return

## Events / year
500–800 qualifying events/yr (Peyer & Vermaelen cite ~1,000+/yr US-wide; S&P 1500 is ~half the market).
More than 60 events/yr ✓; more than 20 distinct days/yr ✓.

## Holdout
8k_8_01 search periods used: 2005–2013 (screen) + 2014–2019 (special-dividend train run).
**Available holdout: 2020–2026 (clean, 7 years).**

## Cost estimate
~15 bps round-trip (close-to-close, mid-to-large cap S&P 1500 names at Webull).

## Why it might NOT work
- Repurchase programs are not firm commitments; companies can and do cancel them
- Effect has been widely published for 30 years; some alpha decay post-publication
- Day-0 close entry already captures some of the initial pop; residual drift may be smaller than the
  full 200 bps cited (which starts from announcement open, not day-0 close)
- Large-cap buybacks are extremely well-known; institutional front-running may reduce drift

## Differs from graveyard
- **special-dividend-drift-long** (8k_8_01, Skeptic FAIL 2026-11-17): different event (special dividend
  vs. repurchase authorization); different text keyword; buyback frequency ~15× higher
- No other 8.01 buyback test in graveyard or dropped ideas
