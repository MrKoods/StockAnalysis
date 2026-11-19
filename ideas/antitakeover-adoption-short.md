# antitakeover-adoption-short

**Family:** 8k_5_03  
**Horizon:** 15 days  
**Entry:** entry_session close (day-0 same_close)  
**Direction:** SHORT

## Mechanism
When a company's board adopts a Stockholder Rights Plan ("poison pill"), it installs a mechanism that
makes hostile takeovers prohibitively expensive. This directly harms shareholders in three ways:
(1) eliminates acquisition-premium optionality (a potential acquirer can no longer make a credible offer);
(2) reduces governance pressure — management is entrenched, knowing they cannot easily be replaced via
hostile bid; (3) signals that management fears outside scrutiny (the board wouldn't need a poison pill
if they were confident the stock is fairly valued). The initial announcement reaction is negative and is
followed by a multi-day drift as: short sellers establish positions, governance-sensitive institutions
reduce holdings, and proxy advisors (ISS/Glass Lewis) flag the firm.

## Evidence
- **Ryngaert (1988) JFE** "The Effect of Poison Pill Securities on Shareholder Wealth":
  -1.5% (-150 bps) cumulative abnormal return at announcement; Ryngaert splits this across days -1 to +1,
  with continued negative drift post-day-0 (approximately -50 to -80 bps from day-0 close onward)
- **Bebchuk, Coates & Subramanian (2002) JLEO**: firms with rights plans earn systematically lower
  long-run returns; the market underreacts at adoption, creating medium-term drift
- **Gompers, Ishii & Metrick (2003) QJE**: high-entrenchment (G-Index) firms underperform by 85 bps/month;
  rights plan adoption is a first-order G-Index event (~21 bps per 15-day hold from this estimate)
- Undifferentiated 8k_5_03 screen: -6.7 to -15.9 bps (t -1.42 to -1.63) — diluted by splits and
  routine amendments; rights-plan subset directionally consistent but stronger
- Gross edge estimate (day-0 close entry): ~50–80 bps per trade over 15 days

## Rule sketch
1. Signal: `rd.filings(forms=['8-K'], items=['5.03'])` where `rd.filing_text(df)` body contains
   ("Stockholder Rights Plan" OR "Rights Agreement" OR "Shareholder Rights Plan" OR "Rights Plan")
   NOT ("terminate" OR "expired" OR "amend" OR "amendment" OR "extend")
2. This isolates NEWLY ADOPTED rights plans; excludes amendments, terminations, and expirations
3. Entry: close of `entry_session` (same_close)
4. Exit: close 15 trading days later
5. Direction: SHORT
6. Hedge: `rd.hedge_ticker` (SPY / IJH / IJR)
7. Universe: S&P 1500

## Data
- `rd.filings(forms=['8-K'], items=['5.03'])` → entry_session, ticker
- `rd.filing_text(df)` → text column (rights plan keyword filter); filing_text covers ~52% of 5.03 items
- `rd.daily(tickers)` → entry close, exit close
- `rd.hedge_ticker` → hedge ETF and return

## Events / year
5.03 total ~514/yr; rights-plan adoptions via text filter estimated 100–200/yr (boards adopt them in
clusters during hostile-bid waves). Coverage: filing_text has 5,848 of 11,299 total 5.03 items (52%);
this means ~50–100 qualifying events/yr with text. This is AT the 60/yr floor — researcher should check
actual event count before pre-registering.

## Holdout
8k_5_03 search periods used: 2005–2013 (screen only, 3 variants).
**Available holdout: 2014–2026 (clean, 12 years).**

## Cost estimate
~15 bps round-trip (close-to-close, mid-to-large cap).

## Why it might NOT work
- By day-0 close, most of the -150 bps announcement reaction is already in the stock (news comes out
  at board meeting, often same morning as the 8-K)
- Residual from day-0 close onward may be only 50–80 bps — close to the cost floor
- Rights plan adoptions declined sharply after the Delaware Supreme Court made removal easier (post-2010);
  event count in holdout (2014–2026) may be lower than in train (2005–2013)
- 52% filing_text coverage means ~48% of events cannot be text-filtered — creates selection bias
- Event count may fall below 60/yr after text filter (check at pre-registration)

## Differs from graveyard
- **split-announcement-drift** (dead; a split was filed under 5.03 but is a different event entirely)
- **restructuring-bounce** (8k_2_05, Skeptic FAIL): completely different event type and mechanism
- No prior rights-plan-specific test in graveyard; 8k_5_03 screen was undifferentiated
- 8k_5_03 holdout 2014–2026 fully clean (3 screen variants only)
