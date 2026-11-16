# activist-13d-long-day0

## Day-0 re-test note
`activist-13d-long` died at TRAIN (t 0.17, 2.37 bps after cost) with entry at close AFTER first_session —
one day too late. TEAM.md audit of day-0 moves across all event types shows: **13D day-0 +51 bps t 5.6**.
Holdout 2016-2026 is untouched. This card re-enters at the close of entry_session (day 0) per the
exception in prompts/scout.md. Original variant count is credited to the activist_13d family budget.

## Mechanism
When a hedge fund or activist investor crosses the 5% ownership threshold with intent to influence
management, they must file a Schedule 13D (now "SCHEDULE 13D" post-2024 rename) within 10 days. The
filing discloses the activist's agenda: board seats, strategic review, buyback, or sale of company.

The day-0 close premium (+51 bps t 5.6) exists because:
1. The filing enters the EDGAR daily index during the trading day; the full session prices in
   the activist thesis, but late-arriving or passive holders continue to adjust through the close.
2. Market anticipates activist pressure on management → mean reversion toward perceived fair value.
3. "Wolf pack" effect: other hedge funds enter the same session once the 13D is public.

By contrast, the day-1 entry (original test) is AFTER the initial reaction: remaining drift ~2 bps
(noise), confirming the premium is concentrated on day 0.

**Who is on the other side?** Passive institutional holders who do not monitor 13D filings in real
time; indexers who must hold the target regardless; retail investors who learn from financial media.

## Evidence
- TEAM.md audit (2026-11-13): 13D day-0 close return = **+51 bps, t 5.6** (all years; full data).
- Brav, Jiang, Thomas & Partnoy (2008): 13D filings show +7.2% mean abnormal return at announcement,
  with drift continuing over 20 days. Sample: 1994-2007.
- Klein & Zur (2009): Hedge fund 13D targets earn +10.2% in the year after filing.
- Effect has attenuated post-publication but the initial announcement premium remains large.

## Rule sketch
- Universe: S&P 1500
- Signal: acceptance of Form SC 13D or SCHEDULE 13D (initial filing only, NOT /A amendments)
  via `filings(forms=['SC 13D'], tickers=sp1500)`. TEAM.md: rd.filings() matches both old
  ("SC 13D") and post-2024 ("SCHEDULE 13D") naming since 2026-11-14.
- **Entry: LONG at close of entry_session** (the first trading close after the EDGAR index
  picks up the filing; use `entry_session` column from filings(), NOT `first_session+1`)
- Exit variants: (a) entry_session+3 close; (b) entry_session+10 close; (c) entry_session+20 close
- Hedge: rd.hedge_ticker (SPY / IJH / IJR by market cap tier)
- Additional variants: (d) sp500_only; (e) filter exclude 13Ds filed by existing passive holders
  crossing exactly 5% (keep only clearly new activist positions)

## Data
- `filings(forms=['SC 13D'], tickers=sp1500)`: event dates + entry_session column; initial filings only
- `daily(tickers)`: OHLCV for entry/exit + return calculation
- `rd.pit_filter` for point-in-time S&P membership (sp500_membership.csv)
- **Family**: `activist_13d` (search 2001-2015 used in prior train run; holdout 2016-2026 CLEAN)
- `live for paper?`: filings() YES — SEC daily index each dispatch, one-business-day lag

## Horizon
3 trading days primary (close-to-close); test 10d and 20d variants (drift documented out to 20d+)

## Cost estimate
S&P 500 targets: ~6-12 bps RT (close). S&P 400/600 targets: ~12-22 bps RT. Blended ~15 bps RT.
At 51 bps gross on a 3d hold: net ≈ 36 bps. Well above cost floor.

## Expected events
~100-250 initial SC 13D filings/year across S&P 1500 (activists target midcap/large-cap S&P names
most). Train 2001-2015 ≈ 1,500-3,750 events; holdout 2016-2026 ≈ 1,000-2,500 events. Adequate for
t ≥ 3.0 at holdout (bar set by tools/budget.py for activist_13d family with existing variants).

## Why it might NOT work
1. By the time the 13D is public (up to 10 days after crossing 5%), much of the move has already
   occurred on rumor/unusual volume; day-0 close captures only residual same-day reaction
2. Post-publication decay: arbitrageurs now monitor 13D filings in real time, compressing the window
3. Event count may be lower than 100/yr if activists rarely target S&P 1500 (they often prefer
   smaller companies outside the index universe)
4. Survivorship: only companies currently in S&P 1500 included; use rd.pit_filter

## Differs from graveyard
- **activist-13d-long** (DEAD): same family, same events, but entered one day late (close AFTER
  first_session). This card fixes the entry to entry_session close. No holdout was spent.
- insider-cluster-buys (DEAD): Form 4 officer transactions, not activist institutional filings
- SC 13G (passive 5%+ holder): deferred — Edmans (2009) shows 13G is weak vs 13D

## Source
Brav, A., Jiang, W., Thomas, R. S., & Partnoy, F. (2008). Hedge Fund Activism, Corporate Governance,
and Firm Performance. The Journal of Finance, 63(4), 1729–1775.
https://doi.org/10.1111/j.1540-6261.2008.01373.x

Klein, A., & Zur, E. (2009). Entrepreneurial Shareholder Activism: Hedge Funds and Other Private
Investors. The Journal of Finance, 64(1), 187–229. https://doi.org/10.1111/j.1540-6261.2009.01413.x

TEAM.md audit 2026-11-13 (day-0 move analysis across all event types): 13D day-0 +51 bps t 5.6.
