# special-dividend-drift-long

## Mechanism
When a company announces a **special (one-time) cash dividend**, it signals that management has excess
capital with no better internal investment use and believes the stock is undervalued. Unlike regular
dividends (which are persistent commitments), a special dividend is an irreversible cash commitment
made in a single announcement — a hard, credible signal of management confidence.

**Drift mechanism (why day+2 to day+20, not just day 0):** Investor underreaction to irregular cash
flow signals. Special dividends are infrequent, receive less analyst coverage than regular dividends,
and are excluded from most dividend-yield screens (no recurring yield), so they are slower to be
fully priced. Retail investors and passive index funds trade after the news disseminates; institutional
investors accumulate over days to meet income mandates.

**Who is on the other side?** Investors who mistake the special dividend for a one-time windfall
rather than a signal of ongoing undervaluation; passive holders who don't react to irregular corporate
events; systematic strategies that filter on regular dividend yield only.

## Evidence
- **Hyun Ahn (2024), "The Special-Dividend Drift," SSRN 7249419**: documents ~**120 bps abnormal
  return over days +2 to +20** post-announcement. Sample covers CRSP common stocks. Mechanism:
  limited arbitrage due to infrequency + institutional underreaction to non-recurring signals.
- Lie (2001): special dividend announcements have significantly positive abnormal returns at
  announcement and in the month following. Documents premium vs regular dividend announcements.
- Peyer & Vermaelen (2009): all forms of "excess cash" distribution create positive drift; special
  dividends are the clearest unconditional signal (vs. buybacks, which can be rescinded).

## Rule sketch
- Universe: S&P 1500 members
- Signal: `filing_text(df)` where item = '8.01' AND body text contains "special dividend" OR
  "special cash dividend" OR "special one-time dividend" (case-insensitive). Filter to initial
  announcement (not ex-date or payment-date notices, which restate information). Use
  `filings(items=['8.01'], tickers=sp1500)` → merge with `filing_text()` for text filter.
- **Entry: LONG at close of entry_session** (day 0 — the same close as the filing; avoids
  expensive open fills; most of the announcement-day jump is in the open/intraday move, not the
  close-to-close increment, so day-0 close entry captures the drift only)
- Exit: entry_session + 20 closes (20 trading day hold)
- Hedge: rd.hedge_ticker per stock (SPY / IJH / IJR)
- Variants: (a) all S&P 1500; (b) S&P 400+600 midcap/small-cap only (Ahn reports stronger drift
  for less-covered smaller stocks); (c) filter: announced pre-market (acceptance_time before 09:30 ET)
  vs after-hours; (d) hold 10d vs 20d

## Data
- `filings(items=['8.01'], tickers=sp1500)`: event dates + entry_session; acceptance_time for
  time-of-day variant
- `filing_text(df)`: 8.01 body text — filter for "special dividend" / "special cash dividend"
  (83,715 entries in catalog; covers all 8.01 items since 2004-08)
- `daily(tickers)`: OHLCV for entry/exit
- `rd.pit_filter` for point-in-time S&P membership
- **Family**: `8k_8_01` (screen 2005-2013 used for UNDIFFERENTIATED LONG — that is a different
  signal from this text-filtered subset; train window 2014-2020 is clean; holdout 2021-2026 CLEAN)
- `live for paper?`: filings() + filing_text: YES — edgar_text updated each dispatch (newest first)

## Horizon
20 trading days (close-to-close). Close fills make the round-trip cost minimal at this horizon.

## Cost estimate
S&P 1500 close-to-close blended: ~8-15 bps RT. At 120 bps gross: net ≈ 105-112 bps. 8× the cost
floor. Excellent margin.

## Expected events
S&P 1500 special dividends: estimated 50-120/year (varies by tax cycle; 2012 had a surge ahead of
fiscal-cliff changes). Over a 7-year train (2014-2020) ≈ 350-840 events. Holdout 2021-2026 ≈
300-720 events. Adequate for t ≥ 3.0 at holdout.

Monthly clustering (hold > 10 days → cluster by month per TEAM.md): 7 train years × 12 months =
84 months; with 50-120 events/yr, ~4-10 events per month → non-empty cluster proportion high.

## Why it might NOT work
1. **Text filter accuracy**: 8.01 items are heterogeneous; a simple keyword filter may include
   false positives (e.g., "declares quarterly dividend and special dividend" vs. pure specials).
   Researcher should inspect a sample and add exclusion keywords if needed.
2. **Post-publication decay**: Ahn's 2024 paper is recent; if the drift has not yet been widely
   arbitraged, the effect should be intact. But the effect may already decay in 2021-2026 holdout.
3. **Announcement-day vs filing-day lag**: companies sometimes issue the press release pre-market
   before filing the 8-K; in those cases, entry at day-0 close still captures the drift (the
   announcement effect is the SAME DAY move, drift is days +2 to +20).
4. **Low event count in some years**: if the 2021-2026 holdout has fewer special dividends (post-
   COVID corporate caution), power may be lower than estimated. Researcher should count events first.
5. **Tax-year clustering**: large spikes in 2012 (fiscal cliff) create within-year clustering; the
   monthly clustered t-stat handles this, but the holdout 2021-2026 may not have that spike.

## Differs from graveyard
- No prior idea tested special dividends specifically
- eap-small-cap-long (DROPPED): earnings-announcement premium — entirely different event and mechanism
- material-impairment-short (DEAD): 8k_2_06 impairment SHORT — different item type, different direction
- restructuring-bounce (DEAD): 8k_2_05 LONG — different mechanism; no cash distribution signal
- The text-filtered 8.01 signal for special dividends is different from the undifferentiated 8.01
  screen signal (which tested ALL 8.01 events LONG and was not a lead at t=-1.58 for 5d hold).
  The special-dividend subset has a specific, documented mechanism not present in the aggregate.

## Source
Ahn, H. (2024). The Special-Dividend Drift. SSRN Working Paper 7249419.
https://ssrn.com/abstract=7249419

Lie, E. (2001). Detecting Abnormal Operating Performance: Revisited. Financial Management, 30(2), 77–91.

Peyer, U., & Vermaelen, T. (2009). The Nature and Persistence of Buyback Anomalies.
Review of Financial Studies, 22(4), 1693–1745. https://doi.org/10.1093/rfs/hhn107
