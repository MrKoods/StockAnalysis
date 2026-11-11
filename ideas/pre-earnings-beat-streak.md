# pre-earnings-beat-streak

## Mechanism
Stocks that have beaten analyst EPS consensus 4+ consecutive quarters attract higher institutional
pre-announcement demand than the average stock. Investors with a track record of correctly
anticipating surprise direction accumulate positions before the announcement, concentrating
buying pressure in the 2-day pre-announcement window (close-2 to close-1). The premium should
be systematically larger for consistent beaters than for the unconditional sample because:
(1) the expected surprise is priced incrementally rather than all at once; (2) portfolio managers
overweight high-beat-streak names ahead of their announcement dates.

## Evidence
- Laarits (2020, SSRN 3660814): unconditional pre-announcement premium ~80 bps for the
  close-2 → close-1 window across all S&P 1500 earnings; confirms premium is higher for
  high-attention, high-expectation stocks.
- Gao, Hu & Zhang (2020, SSRN 3595953): "Uncertainty Risk Resolution Before Earnings
  Announcements" — 72% of EAP realized before the announcement; an interquartile increase in
  firm uncertainty (proxied by analyst dispersion, beat track record) is associated with 65 bps
  ADDITIONAL return in the 10-day pre-announcement window.
- Conservative gross edge used on card: 80 bps (Laarits unconditional base as the floor;
  beat-streak conditional version expected to exceed this).

## Rule sketch
1. For each S&P 1500 ticker, before each earnings announcement date from earnings():
   - Look back at the last 4 prior quarters' EPS surprise column.
   - Skip if fewer than 4 prior quarters of data.
   - Only signal if ALL 4 of the last 4 EPS surprises are positive (actual > estimate).
2. Enter at close-2 (2 trading days before announcement date).
3. Exit at close-1 (1 trading day before announcement date).
4. Direction: LONG only.

## Data
- `earnings(tickers)`: announcement dates + EPS estimate/actual/surprise column; last 4
  quarters' surprise used to build the beat streak filter.
- `daily(tickers)`: OHLCV bars for entry/exit close prices.
- No other data needed.

## Expected events
~3,000–5,000 per year across S&P 1500 (roughly 30–40% of ~10,000 annual earnings have
4+ consecutive beats); enough for a holdout to reach t ≥ 3 at the 80 bps effect size.

## Horizon
1d (close-2 to close-1)

## Cost estimate
~15 bps round trip (blended S&P 1500 close-to-close: 6–22 bps depending on index tier).
Net edge estimate: ~65+ bps after costs (using Laarits base as floor).

## Why it might NOT work
- Beat streaks may be priced in by close-2 as institutions already hold the position;
  marginal buyers in the window are smaller and the residual drift is smaller than the
  unconditional effect.
- Consecutive beats partly reflect analyst walk-down (analysts lower estimates pre-report);
  not genuine expectation of surprise → no incremental demand.
- Laarits (2020) documents the UNCONDITIONAL premium; we don't have a published number
  for exactly this 4-beat conditional version; could go either way.

## Differs from graveyard
- Different from `pre-earnings-premium` (same family, broader unconditional): this is a
  SUBSET restricted to consistent-beat companies; tests whether the conditioning improves
  the signal.
- Entirely different from any earnings_events entries (ESUR, EPRE): those use post- or
  during-announcement windows; this exits the day BEFORE the announcement.

## Family status
pre_earnings family — entirely clean; no search periods used yet.
