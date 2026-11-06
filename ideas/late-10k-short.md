# late-10k-short

## Mechanism
Companies that file their annual 10-K report later than they did in the prior year are likely managing bad news. The delay is not extreme enough to trigger an NT 10-K notification (which requires an explicit warning) but is a softer signal of internal friction: accounting issues, auditor disagreements, complex adjustments, or management reluctance. Ettredge, Lee & Scholz (2000) show that late annual report filers have higher subsequent negative earnings surprises; Kinney & McDaniel (1989) show late filers have higher rates of restatements and internal-control failures.

**How this differs from nt-filing-short (queued):** NT 10-K = company explicitly discloses it cannot file on time — a strong, public signal. Late-10K-short = company filed its 10-K, but later relative to its own prior-year filing date — a weaker, implicit signal covering a larger population of companies with less obvious problems.

**Who is on the other side?** Investors who process 10-K filings only by absolute date (did it file before the SEC deadline?), not by company-specific timing trends; passive holders indifferent to filing-date shifts.

## Evidence
- Ettredge, Lee & Scholz (2000): Companies filing annual reports later than their own prior-year trend experience higher rates of analyst downward revisions and larger negative earnings surprises in the subsequent two quarters.
- Dechow, Ge & Schrand (2010): Survey shows accruals quality is negatively related to filing delay relative to prior year.
- Family 10k_timing is ENTIRELY CLEAN (no screen, no researcher search variants, no holdout used).
- Note: early-10k-drift (long side of the same family, buy early filers) is at `dropped` stage — this is the opposite direction (short late filers), different mechanism and direction.

## Rule sketch
- Universe: S&P 1500
- Signal: 10-K filing acceptance date is >= 7 trading days later than the same company's prior-year 10-K acceptance date (computed from filings() historical data)
- Entry: SHORT at CLOSE on the detection day (dispatch-day close)
- Exit: cover at close+3 (3-day hold close-to-close)
- Variants to test: (a) >= 5-day lag; (b) >= 10-day lag (tighter filter); (c) SP500 only; (d) 5-day hold
- Filter: EXCLUDE tickers that also filed an NT 10-K in the same fiscal year window, to avoid overlap with nt-filing-short and prevent double-counting. Also exclude tickers with concurrent 8-K 2.02 (earnings in same window).
- Alternative calendar: researcher may prefer to measure lag relative to fiscal year-end (days after fiscal year-end to 10-K filing) rather than year-over-year company comparison, to control for company-specific fiscal year calendars

## Data
- `filings(forms=['10-K'], tickers=sp1500)`: event dates (acceptance timestamp) for current and prior-year 10-K
- `filings(forms=['NT 10-K'], tickers=sp1500)`: to identify and exclude NT filers (overlap filter)
- `daily(tickers)`: OHLCV for entry/exit + return calculation
- **Family**: `10k_timing` (entirely clean — no prior screen, no researcher variants, no holdout used)
- `live for paper?`: filings() is live (SEC daily index each dispatch) — YES

## Horizon
3 trading days (close-to-close, detection day to close+3)

## Cost estimate
S&P 1500 close entry: S&P 500 ~6.6 bps, S&P 400 ~12.0 bps round trip mix. Expected net: depends on mean drift.

## Expected events
10-K filings: ~1,460/year in S&P 1500 (1 per company). ~20-30% filing later than prior year = ~300-450 events/year. Over holdout 2016-2026: ~3,000-4,500 events. Well-powered. After NT filter and other exclusions, may drop by 10-15%.

## Why it might NOT work
1. Most filing-date variation is innocuous: staff changes, minor complexity, holiday timing, change in auditor, leap year — not all late filers are hiding bad news
2. NT-filing-short (queued) may already capture the relevant signal; the incremental population (late-but-not-NT) may be noisy
3. Measuring year-over-year filing day shift introduces noise when companies change fiscal year end or change from accelerated to non-accelerated filer status
4. The 7-day threshold is arbitrary; a wide search over thresholds would inflate the variant count and require a higher holdout bar
5. nt-filing-short (queued) is for open+1 entry and was designed for large-cap (S&P 500); this uses close entry for S&P 1500 — researcher should be clear about which test is which to avoid confusion

## Differs from graveyard
- nt-filing-short (queued, not dead): different signal — NT = explicit warning; this = relative timing shift. Researcher should run these as separate ideas with NT excluded from this dataset to keep them independent
- early-10k-drift (dropped): opposite direction (buy early, not short late); same family; will not be confused
- No late-10K or filing-delay-short idea has previously been researched in this codebase

## Source
Ettredge, M., Lee, C., & Scholz, S. (2000). The appearance of SEC accounting and auditing enforcement releases and earnings restatements. Journal of Accounting and Economics, 28(2), 149–176.

Kinney, W. R., & McDaniel, L. S. (1989). Characteristics of Firms Correcting Previously Reported Quarterly Earnings. Journal of Accounting and Economics, 11(1), 71–93. https://doi.org/10.1016/0165-4101(89)90014-1
