# material-impairment-short

## Mechanism
When a company announces a material impairment (goodwill writedown, long-lived asset
impairment — SEC 8-K item 2.06), it signals that a past acquisition or investment was
overvalued and that management expectations have been revised sharply downward. The
negative price reaction is not fully captured at the initial announcement open because:
(1) The magnitude of impairment is often uncertain until institutional analysts
    re-model; selling pressure builds over the next 1-3 days as models are updated;
(2) Goodwill impairments often coincide with earnings misses; the two signals reinforce
    each other but arrive with different delays (8-K same day vs. sell-side research
    the next day);
(3) Retail and momentum investors who held the stock react with a lag to the impairment
    signal, amplifying the drift.
The SHORT after close of filing day captures this 2-3 day continuation.

## Evidence
- Li, Shroff, Venkataraman & Zhang (2011): "Causes and Consequences of Goodwill
  Impairment Losses" — CARs of approximately -150 bps in the [-1, +3] window around
  goodwill impairment announcements; the negative drift extends beyond the announcement day.
  https://doi.org/10.1007/s11142-011-9150-2
- Hirschey & Richardson (2003, TAR): "Investor Underreaction to Goodwill Write-offs"
  — documents CARs of approximately -100 to -180 bps around impairment announcements;
  finds that analyst reactions lag by 1-2 days.
  https://doi.org/10.2308/accr.2003.78.3.859
- Jarva (2009): "Do Firms Manage Fair Value Estimates?" — negative post-impairment drift
  averaging ~120 bps over days 0-3 for S&P constituents.
  https://doi.org/10.2308/accr.2009.84.4.1073
- Gross edge used: ~120–150 bps SHORT over 3 days (conservative midpoint of Li et al.
  and Hirschey & Richardson).

## Rule sketch
1. Use `filings(forms=['8-K'], items=['2.06'])` to identify S&P 1500 filings with
   8-K item 2.06 (material impairment announced).
2. Use the filing acceptance_time to determine whether the filing arrived before or
   after market close:
   - Before 4 PM ET close: enter SHORT at close same day (T).
   - After 4 PM ET close: enter SHORT at close T+1 (next day's close, skip the gap).
   Both timing rules should be tested; skip-the-gap (close+1) is a stricter/cleaner rule.
3. Exit: cover SHORT at close T+3 (3 trading days after entry).
4. Direction: SHORT only (consistent with the literature's negative drift finding).
5. Universe: S&P 1500.
6. The researcher may test size cuts (S&P 500/400/600 separately) to find the best
   sub-universe if the aggregate is marginal.

## Data
- `filings(forms=['8-K'], items=['2.06'])`: impairment event dates + acceptance_time
  for before/after-close determination.
- `daily(tickers)`: OHLCV bars for close entry and close T+3 cover prices.
- No other data needed.

## Expected events
~50/year total in full universe; ~25–30/year after S&P 1500 filter.
Over a 12-year holdout (2014-2026): ~300–360 events.
Power is adequate if the gross edge holds (~150 bps / (300 bps vol / sqrt(300)) ≈ t 8.7).

## Horizon
3d (close entry to close T+3)

## Cost estimate
~15 bps round trip (blended S&P 1500 close-to-close: 6–22 bps depending on cap mix).
Net edge estimate: ~105–135 bps after costs.

## Why it might NOT work
- Many item 2.06 filings are filed ALONGSIDE the earnings release (8-K item 2.02);
  the initial price gap already prices most of the impairment news by T+1 open.
  If the researcher enters at the close after the filing, they may be buying into the
  post-gap recovery, not capturing the drift.
- Sparsity risk: 25-30 events/year means a bad year (macro crisis, elevated impairments)
  can skew the entire test; cluster standard errors by quarter.
- Not all 2.06 filings are goodwill impairments; some are smaller operational write-offs
  with limited market impact. The researcher may find the signal is driven only by large
  impairments (testable by filtering on a materiality threshold in the filing count or
  stock price reaction on day T).
- Survivorship bias: S&P 1500 is today's membership; companies impaired so severely they
  left the index are excluded → the remaining sample is biased toward less severe
  impairments with smaller negative drift.

## Differs from graveyard
- Different from `reg-fd-small-cap-disclosure` (8k_7_01, dead): that was a different
  8-K item (7.01) tested LONG; this is item 2.06 tested SHORT.
- Different from `restructuring-bounce` (8k_2_05, dead): item 2.05 is restructuring/
  exit costs; item 2.06 is material impairment — different events, different mechanism,
  opposite direction (restructuring-bounce was LONG; this is SHORT).
- The screen (tools/screen.py) only tests the LONG direction ("buy after the filing").
  This SHORT was NOT tested in the 8k_2_06 screen pass; the negative screen result
  for the LONG direction is consistent with the SHORT working. The SHORT direction and
  holdout 2014-2026 are entirely clean for this family.

## Family status
8k_2_06 — screen (2005-2013) used for LONG direction only. SHORT direction and
holdout 2014-2026 are entirely clean. 3 search variants recorded from screen pass.
