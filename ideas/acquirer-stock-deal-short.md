# acquirer-stock-deal-short

**Family:** 8k_1_01  
**Horizon:** 20 days  
**Entry:** entry_session close (day-0 same_close)  
**Direction:** SHORT

## Mechanism
When a company announces it will ACQUIRE another company using its own stock as consideration, it signals
two things simultaneously: (1) winner's curse — the acquirer overpaid to win the auction (Roll 1986);
(2) overvaluation signal — Myers & Majluf (1984) show that managers issue equity only when they believe
it is overvalued. The combined effect is a negative announcement return for the acquirer that continues
to drift negative as: deal uncertainty keeps institutional buyers out; arbitrageurs short the acquirer to
hedge their target-long position; and post-announcement earnings revisions reflect deal integration costs.

## Evidence
- **Moeller, Schlingemann & Stulz (2004) JF** "Firm Size and the Gains from Acquisitions":
  acquirers earn -1.4% in the 3-day announcement window; large-deal stock acquirers worst (-3% to -5%)
- **Fuller, Netter & Stegemoller (2002) JF**: acquirers in stock deals earn -1.0% to -3.0% in 3 days
  vs. +0.3% in cash deals; sample: 3,135 acquisitions 1990–2000
- **Rau & Vermaelen (1998) JFE**: glamour acquirers in stock deals underperform -4% over 3 years;
  bulk of that underperformance loads in the first 20–40 trading days
- Undifferentiated 8k_1_01 screen: ≈ 0 bps (t 0.01–0.24) — diluted by targets (+30% immediate
  reaction), non-M&A agreements, and cash deals (which earn slight positive for acquirer)
- Gross edge estimate for the SHORT: ~100–150 bps over 20 days based on the -1.4% 3-day figure
  and the continuation drift documented in Rau & Vermaelen

## Rule sketch
1. Signal: `rd.filings(forms=['8-K'], items=['1.01'])` where `rd.filing_text(df)` body contains
   ("agree to acquire" OR "agreed to acquire" OR "entered into a merger agreement to acquire"
   OR "announced the acquisition of") AND the filer mentions paying with "shares of common stock"
   OR "stock consideration" OR "share consideration"
2. Exclude filings where the filer is the TARGET (text contains "to be acquired by" OR
   "merger with [acquirer]" OR "tender offer for the company")
3. Exclude all-cash deals (text contains "all cash" OR "cash consideration" without stock language)
4. Entry: close of `entry_session` (same_close)
5. Exit: close 20 trading days later
6. Direction: SHORT
7. Hedge: `rd.hedge_ticker` (SPY / IJH / IJR)
8. Universe: S&P 1500

## Data
- `rd.filings(forms=['8-K'], items=['1.01'])` → entry_session, ticker
- `rd.filing_text(df)` → text column (acquirer + stock consideration filter)
- `rd.daily(tickers)` → entry close, exit close
- `rd.hedge_ticker` → hedge ETF and return

## Events / year
1.01 total ~2,000/yr; M&A-related subset ~20–25% = 400–500/yr; stock (not all-cash) deals ~40% = 160–200/yr.
Minimum 60 events/yr ✓; at least 20 distinct days/yr ✓.

## Holdout
8k_1_01 search periods used: 2005–2013 (screen only, 3 variants).
**Available holdout: 2014–2026 (clean, 12 years).**

## Cost estimate
~15 bps round-trip (close-to-close, mid-to-large cap). Short borrowing cost is not modeled in paper
runner (accrue ~5–10 bps/month additional cost for short leg — researcher should note in PLAN).

## Why it might NOT work
- By day-0 close, most of the 3-day -1.4% reaction has already occurred (announcement is intraday/overnight)
- The residual from day-0 close to day-20 may be only 30–70 bps, close to the cost floor
- Text filtering is complex: M&A language is varied; false positives (non-M&A item 1.01) and false negatives
  (stock deal language buried in exhibits) are likely
- In bull markets (2020–2024), acquirers were often rewarded for growth acquisitions
- After hedging with SPY/IJH/IJR, the idiosyncratic acquirer return may shrink substantially

## Differs from graveyard
- **activist-13d-long / activist-13d-long-day0** (activist_13d, dead): schedule 13D activist investors;
  completely different event and mechanism
- **pipe-short** (8k_3_02, dead): PIPE equity placements; different event (new equity at discount)
- No prior 8k_1_01 test in graveyard beyond the undifferentiated screen
- 8k_1_01 holdout 2014–2026 fully clean (3 screen variants only)
