# early-10k-drift

## Mechanism
Companies that file their annual 10-K report significantly EARLIER than in the prior year are signalling management confidence in their results. Filing takes internal effort to finalise audit and sign-off; a company in distress or with accounting complications delays. Chambers & Penman (1984) established that early filers tend to have positive earnings surprises and that the market partially adjusts to this signal slowly — especially for small/mid-cap stocks where analyst coverage is sparse. The filing date itself is a low-noise signal (it requires positive intent from management, not just a price move) and is publicly available on EDGAR the moment it is accepted.

**Who is on the other side?** Investors who have not screened EDGAR for new 10-K filings and don't recognise the early-filing signal; small-cap stocks with low institutional monitoring where information diffuses over days, not minutes.

## Evidence
- Chambers & Penman (1984) Journal of Accounting Research "Timeliness of Reporting and the Stock Price Reaction to Earnings Announcements": early 10-K filers (relative to fiscal year end) have significantly higher cumulative abnormal returns than late filers; the difference persists for several trading days after filing, particularly for small firms.
- Begley & Fischer (1998) Review of Accounting Studies "Lags in the Dissemination of Earnings Announcements from Journals to the Broad Public": information from early filers disseminates slowly for under-followed stocks; market reaction continues 3-5 days post-filing.
- General literature (Francis et al. 2002, Sengupta 1998): timeliness of financial reporting is associated with better corporate governance and lower information asymmetry; in the cross-section, early filers systematically outperform late filers over short horizons.

## Rule sketch
- Universe: S&P 1500 stocks that file a 10-K at least 10 calendar days earlier than their prior-year 10-K filing date (year-over-year improvement in filing speed)
- Entry: buy at open on the first trading day after the 10-K acceptance timestamp (if filed after 4 PM ET, buy next open)
- Exit: sell at open 3 trading days later
- Early-filer definition: compare each 10-K acceptance date to the same company's prior-year 10-K acceptance date; early = ≥ 10 days earlier than last year's date (alternative: ≥ 15 days)
- Variants: (a) 10-day vs 15-day threshold; (b) small-cap only (S&P 600) vs full S&P 1500; (c) add SPY/sector hedge; (d) hold 3d vs 5d
- Expected events: S&P 1500 × 1 10-K/yr × ~25% are early filers ≈ 375 events/yr (well-powered)

## Data
- `filings(forms=['10-K'], tickers=sp1500)`: filing date + acceptance timestamp (year-over-year comparison to identify early filers; both current and prior-year 10-K dates come from this single loader)
- `daily(tickers)`: OHLCV for entry/exit pricing
- **Family**: `10k_timing` (new family; no prior usage — entire history clean); train 1999-2017 (daily() starts 1999); holdout 2018-2026

## Horizon
3 trading days (open+1 to open+4 from filing date)

## Cost estimate
~15-25 bps round trip (S&P 1500 mix; mid/large cap ≈ 15 bps, small cap ≈ 30 bps)

## Why it might NOT work
1. The year-over-year comparison is a noisy proxy — a company may file early one year for idiosyncratic reasons (audit firm change, easy year), not because of persistent positive quality
2. The filing date may already trigger an immediate market reaction on day 0 (same day as filing); the drift may be concentrated there and not persist to day 1-3
3. Fiscal year-end changes or restatements can make year-over-year filing date comparison unreliable for some companies
4. The original Chambers & Penman (1984) effect was documented 40+ years ago; modern EDGAR real-time feeds mean large-cap early filers are priced immediately, limiting the drift to small caps only

## Differs from graveyard
- PEAD / ESUR (graveyard): triggered by earnings surprise magnitude; this idea is triggered by filing timing only, not the EPS number; different mechanism (timeliness signal vs. surprise magnitude)
- split-announcement-drift (dead): different event type and mechanism

## Source
Chambers & Penman (1984): https://doi.org/10.2307/2490712
Begley & Fischer (1998): https://doi.org/10.1023/A:1009634011393
Sengupta (1998) TAR: "Corporate Disclosure Quality and the Cost of Debt"
