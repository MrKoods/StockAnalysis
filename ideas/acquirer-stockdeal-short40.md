# acquirer-stockdeal-short40

**Family:** 8k_1_01  
**Horizon:** 40 days  
**Entry:** entry_session close (day-0 same_close)  
**Direction:** SHORT

## Mechanism
When an acquirer announces a merger paid in its own stock, two forces drag the stock lower over the
months following the announcement: (1) Myers-Majluf (1984) overvaluation signal — managers issue stock
when they believe it is overpriced, so the announcement is a credible negative signal about intrinsic
value; (2) the market digests dilution slowly — earnings-per-share revisions, deal integration costs, and
integration uncertainty continue to suppress the stock for 1–3 months. The 20-day hold (previous idea
`acquirer-stock-deal-short`) captured only the fastest part of this drift and fell below the cost floor
after the initial 3-day reaction was priced by day-0 close. Rau & Vermaelen (1998) show the bulk of
underperformance loads in months 1–3 post-announcement (40–60 trading days), not years 1–3. A 40-day
hold targets this window directly.

## Evidence
- **Rau & Vermaelen (1998) JFE** "Glamour, value and the post-acquisition performance of acquiring firms":
  glamour acquirers in stock deals underperform by ~15% in 3 years; bulk of this loads in months 1–3
  post-announcement (~200 bps in the first 40–60 trading days for the stock-deal cohort)
- **Fuller, Netter & Stegemoller (2002) JF**: acquirers in stock deals earn –1.0% to –3.0% in 3 days
  vs +0.3% in cash deals; the stock-deal drag is a persistent signal, not purely a 3-day event
- **Moeller, Schlingemann & Stulz (2004) JF**: large acquirers in stock deals lose ~200 bps in 3-day
  window; subsequent 2-month CAR is –150 to –250 bps vs benchmark
- Previous team idea `acquirer-stock-deal-short` (dropped): 20-day residual was only ~30–70 bps after
  the initial reaction — cost floor fail. Director drop note explicitly invited 40-day variant to capture
  the Rau-Vermaelen continuation drift. This is that variant.
- Gross edge estimate for 40-day SHORT: ~150–250 bps based on the literature, using the more conservative
  150 bps as the floor estimate.

## Rule sketch
1. Signal: `rd.filings(forms=['8-K'], items=['1.01'])` where `rd.filing_text(df)` body contains  
   ("agree to acquire" OR "agreed to acquire" OR "entered into a merger agreement"  
   OR "announced the acquisition of") AND the filer pays in stock ("shares of common stock"  
   OR "stock consideration" OR "share consideration" OR "stock-for-stock")
2. Exclude filings where the filer is the TARGET ("to be acquired by" OR "tender offer for the company")
3. Exclude all-cash deals ("all cash" OR "all-cash consideration" without stock language)
4. Entry: close of `entry_session` (same_close, day 0)
5. Exit: close 40 trading days later
6. Direction: SHORT
7. Hedge: `rd.hedge_ticker` (SPY / IJH / IJR by index membership)
8. Universe: S&P 1500
9. Cluster returns by month (hold > 10 days; harness enforces)

## Data
- `rd.filings(forms=['8-K'], items=['1.01'])` → entry_session, ticker
- `rd.filing_text(df)` → text column (acquirer + stock consideration filter)
- `rd.daily(tickers)` → entry close (day 0), exit close (day 40)
- `rd.hedge_ticker` → hedge ETF and return
- `rd.pit_filter` for sp500 (applies to acquirers in S&P 500 subset; sp400/sp600 have survivorship caveat)

## Events / year
~160–200 stock-deal announcements/year in S&P 1500 (same as prior idea; 8k_1_01 ~2,000/yr total,
~20% are M&A, ~40% of M&A are stock deals). After text filtering: ~60–100 events/year minimum ✓;
at least 20 distinct days/year ✓. Monthly clustering reduces independent observations to ~12/year;
over 2014–2024 train = ~120 monthly clusters — adequate for a t-test.

## Holdout
8k_1_01 search periods used: **2005–2013 (screen only, 3 variants)**.  
**Available holdout: 2014–2026 (clean, 12 years).**  
Suggested split: train 2014–2020 (7 years, ~700–1,400 events), holdout 2021–2026 (clean).

## Cost estimate
Close-to-close fills: ~6.6 bps RT (SP500 half-spread 3.3 bps; mixed SP400/600 acquirers push this
higher, budget 10–15 bps). Short borrow: ~5–10 bps/month × 2 months = ~10–20 bps additional cost.
Total realistic cost: 20–35 bps per round trip. Gross 150 bps / 35 bps = 4.3× — passes 3× hurdle.
Researcher should include borrow cost in the PLAN's cost model.

## Why it might NOT work
- Text filter accuracy: M&A language varies; false positives (non-M&A agreements) and false negatives
  (stock language in exhibits, not body) will dilute the signal
- By day-0 close, virtually all of the 3-day -1.4% reaction is already priced; 40-day continuation
  could be small or zero in modern markets (Schwert 2000 shows acquirer CARs shrinking post-2000)
- Short borrow cost (10–20 bps/40d) erodes the edge meaningfully; deal completion uncertainty can
  cause sharp acquirer reversals if the deal falls through
- Rau-Vermaelen (1998) used pre-2000 data; publication and arbitrage activity may have eroded the drift
- In a risk-on market, deal synergies are rewarded, not punished → regime-dependent performance

## Differs from graveyard / dropped ideas
- **acquirer-stock-deal-short** (dropped, 8k_1_01): same family and event, 20-day hold — Director
  explicitly noted the 40-day variant as the natural revival. This card answers that invitation.
- **pipe-short** (8k_3_02, dead): PIPE equity placements; different event type
- **activist-13d-long** (dead): activist 13D filings; completely different mechanism
- **seo-short** (dead): seasoned equity offerings; different event and direction
