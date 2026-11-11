# earnings-announcement-risk-premium

## Mechanism
Stocks systematically earn a positive return on their earnings announcement days because
investors require compensation for holding a stock through a known, non-diversifiable risk
event (the announcement). This is an ANNOUNCEMENT RISK PREMIUM — not post-earnings drift
(PEAD) and not pre-announcement positioning. The mechanism:
(1) Investors who would normally hold the stock sell their position before the announcement
    to avoid announcement-day risk, reducing the pre-announcement price;
(2) Those who hold through (or buy the dip) are compensated by systematic positive returns
    on the day of the announcement on average;
(3) The premium is systematic and NOT explained by beta, size, or value factors —
    it is a pure announcement-day risk premium.

## Evidence
- Savor & Wilson (2016, JFE): "Earnings Announcements and Systematic Risk" — stocks earn
  an average of ~200 bps on their own earnings announcement days vs. non-announcement days;
  the premium is robust to risk adjustment and is a compensation for systematic announcement
  uncertainty, not a mispricing.
- Frazzini & Lamont (2007, JFE): "The Earnings Announcement Premium and Trading Volume" —
  earnings announcement days show significantly higher returns than surrounding days; the
  premium averages ~120 bps over the [0, +1] window.
- Gross edge used: ~120–200 bps on a close-1 → close basis (announcement day window).

## Rule sketch
1. Use earnings() to identify announcement dates for all S&P 1500 tickers.
2. Enter at close-1 (close of the trading day BEFORE the announcement date).
3. Exit at close (the close of the announcement date itself).
   - For after-hours announcements: this exit close is the NEXT trading day's close (day+1
     after announcement); the researcher should test both close and close+1 as the exit.
4. Direction: LONG only (the premium is systematic, not dependent on surprise direction).
5. No earnings-surprise filter — the premium exists regardless of beat/miss on average.

## Data
- `earnings(tickers)`: announcement dates for each S&P 1500 ticker.
- `daily(tickers)`: OHLCV bars for close-1 entry and close exit prices.
- No other data needed.

## Expected events
~8,000–10,000 per year (every S&P 1500 earnings announcement); very high-powered test.

## Horizon
1–2d (close-1 to close, or close-1 to close+1 depending on announcement timing)

## Cost estimate
~15 bps round trip (blended S&P 1500 close-to-close: 6–22 bps).
Net edge estimate: ~105–185 bps after costs.

## Why it might NOT work
- If the announcement is after close, the market reaction (up or down) happens at the
  next-day open and the close-1 → close+1 window includes both the premium AND directional
  surprise risk; on average positive, but high variance per trade.
- The premium may have decayed post-publication (Savor & Wilson 2016 is well-known);
  if institutions now buy to capture it, the premium is priced in pre-announcement (shifting
  it into the pre-earnings-premium territory Laarits documents).
- Survivorship bias: S&P 1500 is today's membership; companies with bad surprises that
  left the index are excluded → premium may be overstated.

## Differs from graveyard
- Different from all earnings_events entries (ESUR/EPRE/PEAD): those use post-announcement
  windows or specific surprise-direction filters. This is a SYSTEMATIC LONG THROUGH the
  announcement itself, regardless of direction, capturing the risk premium only.
- Different from `pre-earnings-premium` (pre_earnings family): that idea exits at close-1
  (day before); this enters at close-1 and holds THROUGH the announcement day.
- Family `announcement_premium` — not related to any graveyard entry.

## Family status
announcement_premium — new family, entirely clean.
