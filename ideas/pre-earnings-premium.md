# pre-earnings-premium

## Mechanism
Stocks systematically drift UP in the 1-2 trading days BEFORE an earnings announcement and before the news is known. This is a **risk premium**: investors demand compensation for holding through announcement uncertainty. As the announcement approaches, prices rise to equilibrate the marginal investor who would otherwise exit before the event. The premium materialises in the pre-announcement window and then reverses after the news resolves.

Critically, 72% of the full earnings-announcement-period excess return is realised BEFORE the announcement (Ai et al. 2021 "Premium for Heightened Uncertainty"). This is not information leakage — it is a systematic, predictable risk premium that is robust across markets and macro regimes.

**Who is on the other side?** Risk-averse investors who exit (or underweight) positions before scheduled announcements to avoid earnings uncertainty. They effectively pay the pre-announcement premium to holders who absorb the risk.

**How this differs from V4 EPRE:** EPRE enters before the announcement and holds THROUGH it, targeting the EPS-surprise reaction plus pre-announcement premium combined. This idea exits at close-1 (one day before the announcement), capturing ONLY the pre-announcement drift and taking zero earnings-surprise risk. The two ideas trade different windows of the same event.

## Evidence
- Laarits (2020) "Pre-Announcement Risk" SSRN #3443886: documents a significant 24-hour pre-announcement equity premium across scheduled announcements; mechanism is resolution of uncertainty about state of the economy.
- Ai, Bansal & Han (2021) / "Premium for Heightened Uncertainty: Explaining Pre-Announcement Market Returns," ScienceDirect: 72% of the earnings-announcement premium accrues BEFORE the announcement; premium is a compensation for holding through uncertainty, not an information effect. https://www.sciencedirect.com/science/article/abs/pii/S0304405X21004037
- ScienceDirect companion: "Pre-earnings announcement returns and momentum," 2020: strategy of buying winners (pre-announcement momentum) yields 0.58-0.64% per month.
- Pre-announcement premium is distinct from PEAD (which is post-announcement); it has NOT decayed the way classic PEAD has (PEAD is near zero after 2017 for large caps; the pre-announcement risk premium is structural).

## Rule sketch
- Universe: S&P 1500
- Signal: earnings() shows stock has an earnings announcement date = today + 2 trading days
- Entry: LONG at CLOSE of detection day (close-2 relative to announcement)
- Exit: at CLOSE of day -1 (1 trading day before announcement) — avoids all earnings surprise risk
- Hold: 1 trading day (close-to-close)
- Variants to test: (a) all S&P 1500; (b) S&P 500 only (cheapest fills); (c) entry at close-3, exit close-1 (2-day hold); (d) conditioned on prior 5-day momentum positive (buying into existing positive drift per ScienceDirect companion paper)

## Data
- `earnings(tickers)`: announcement dates (live via Yahoo calendar, same as V4)
- `daily(tickers)`: OHLCV for entry/exit close prices
- **Family**: `pre_earnings` (new family, entirely clean — no screen, no prior search, no holdout)
- `live for paper?`: earnings() dates YES (Yahoo calendar, same mechanism as V4 EPRE); daily() YES

## Horizon
1 trading day (close-2 to close-1). Researcher may test 2-day hold (close-3 to close-1).

## Cost estimate
Close-to-close, blended S&P 1500: S&P 500 ~6.4 bps RT, S&P 400 ~12.0 bps RT, S&P 600 ~21.8 bps RT. Net expected: ~37-67 bps after costs if gross is 50-80 bps.

## Expected events
~6,000/year (1,500 tickers × 4 quarterly earnings each). Excellent power — no holdout gap risk.

## Why it might NOT work
1. The pre-announcement premium may have attenuated post-publication (papers published 2020-2021; institutional arbitrage may have compressed the edge since then).
2. V4 EPRE may already be capturing most of the pre-announcement window; if pre-announcement drift is the MAIN driver of EPRE's edge, the two ideas share economic risk.
3. The effect is documented at the MARKET level (avg across all stocks); for individual stocks the per-trade variance is high. With 1d hold and typical stock σ ~150 bps, the t-stat per 6,000 events/year is high — but the per-trade Sharpe is modest.
4. Transaction costs for S&P 600 small-caps (21.8 bps RT close) may erode the edge for small-cap sub-universes.

## Differs from graveyard
- No pre-earnings or pre-announcement idea has ever been tested in this codebase.
- Not related to any dead/dropped idea. EPRE (V4, live paper test) is the closest but targets a different window (announcement + post-announcement, not pre-only).
- Pre_earnings family is entirely clean; no related family (earnings_events is for post-announcement surprise ideas).

## Source
Laarits, T. (2020). Pre-Announcement Risk. SSRN #3443886. https://www.ssrn.com/abstract=3443886

Ai, H., Bansal, R., & Han, S. (2021). Premium for Heightened Uncertainty: Explaining Pre-Announcement Market Returns. Journal of Financial Economics. https://www.sciencedirect.com/science/article/abs/pii/S0304405X21004037
