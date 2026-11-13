# eap-small-cap-long

## Mechanism
Small-cap stocks earn a systematically higher return on their earnings announcement
days compared to non-announcement days. The mechanism is a risk premium: informed and
index investors reduce exposure before an announcement to avoid directional surprise
risk; those who hold through the announcement (or buy into it) are compensated with
a systematic positive return on the day itself, independent of which way the news goes.
The effect is concentrated in small and mid-cap stocks where:
(1) Individual investor attention is higher (the announcement is a "focal event");
(2) Institutional coverage is thinner, so information asymmetry and uncertainty are larger;
(3) Market makers demand a wider premium for providing liquidity through the event.
Restricting to S&P 600 targets the sub-population where the premium is documented
to be largest and least likely to have been fully arbitraged away.

## Evidence
- Frazzini & Lamont (2007, JFE): "The Earnings Announcement Premium and Trading Volume"
  — earnings announcement days show significantly higher average returns than surrounding
  days; the premium averages ~100 bps on the [-1, 0] window across all stocks. Smaller
  stocks show a larger premium.
  https://doi.org/10.1016/j.jfineco.2006.02.010
- Savor & Wilson (2016, JFE): "Earnings Announcements and Systematic Risk" — stocks earn
  ~200 bps more on announcement days vs. matched non-announcement days after risk
  adjustment; the premium is not explained by beta, size, or value.
  https://doi.org/10.1016/j.jfineco.2015.08.014
- Barber, De George, Lehavy & Trueman (2013, JAR): "The Earnings Announcement Premium
  Around the Globe" — the premium is largest for stocks with high individual investor
  attention (proxied by small size, news coverage, and retail broker activity);
  specifically documents ~120–160 bps for small-cap stocks in the US.
  https://doi.org/10.1111/1475-679X.12023
- Gross edge used: ~120 bps for S&P 600, based on Barber et al. (2013) small-cap
  estimates and Frazzini & Lamont (2007) directional premium estimates.

## Rule sketch
1. Use `earnings(tickers)` to identify upcoming earnings announcement dates for
   all S&P 600 tickers.
2. Enter at close T-1 (close of the trading day BEFORE the announcement date).
3. Exit at close T (the close of the announcement date itself).
   - For after-hours announcements: exit at close T+1 (the next trading day's close),
     since the market reaction happens at the T+1 open. Test both close T and close T+1.
4. Direction: LONG only (the premium is systematic, not tied to surprise direction).
5. No surprise filter — the premium exists regardless of beat/miss on average.
6. Universe: S&P 600 only (smaller stocks where EAP is documented strongest).

## Data
- `earnings(tickers)`: announcement dates + earnings report time (for AM vs PM timing)
  for each S&P 600 ticker.
- `daily(tickers)`: OHLCV bars for close T-1 entry and close T/T+1 exit prices.
- No other data needed.

## Expected events
~600 × 4 ≈ 2,400 per year (S&P 600 tickers × 4 quarterly announcements);
roughly 1,000–1,500 usable after incomplete data filter. High-powered test.

## Horizon
1–2d (close T-1 to close T, or close T-1 to close T+1 for after-hours announcers)

## Cost estimate
~22 bps round trip (S&P 600 close-to-close: half-spread 10.9 bps entry + 10.9 bps exit).
Net edge estimate: ~98 bps after costs (conservative gross ~120 bps).

## Why it might NOT work
- Post-publication decay: Frazzini & Lamont (2007) is widely cited; institutions may
  now fully price in the effect, eliminating the premium.
- Direction risk: individual trades have high variance (announcement = news event); the
  average is positive but many individual trades lose.
- After-hours vs. before-open announcements: if the researcher cannot reliably separate
  these, the exit price choice adds noise. The earnings() loader only provides the date,
  not always a reliable before/after-close flag.
- Survivorship bias: S&P 600 is today's membership; excluded companies with bad
  announcements that left the index inflate the historical premium.
- Overlap with EPRE (V4 live test): EPRE enters at close T-2, exits at close T-1; this
  idea enters at close T-1 and exits at close T — a one-day overlap. If EPRE is live,
  the researcher should note the overlap but they are distinct tests (different entry day).

## Differs from graveyard
- Different from `earnings-announcement-risk-premium` (dropped): that idea used all
  S&P 1500 (not S&P 600 only); the small-cap restriction targets the sub-population
  where the EAP is documented strongest and least arbitraged.
- Different from `pre-earnings-premium` (pre_earnings family, dead): pre-earnings-premium
  exits at close T-1 (the day BEFORE the announcement); this idea holds THROUGH the
  announcement day itself.
- Different from all earnings_events (ESUR/EPRE/PEAD): those use post-announcement
  or post-surprise-direction windows; this is a systematic long through the announcement.
- Family `announcement_premium` — entirely clean, no periods used.

## Family status
announcement_premium — new family, entirely clean, no holdout used.
