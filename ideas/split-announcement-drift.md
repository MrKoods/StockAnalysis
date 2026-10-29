# split-announcement-drift

## Mechanism
When a company announces a forward stock split, the stock tends to drift upward over the next few days through the effective date. Three forces drive this:

1. **Management confidence signal**: boards only split when they expect continued appreciation; the announcement resolves uncertainty about management's long-term view.
2. **Retail accessibility demand**: the prospect of a lower per-share price attracts new retail buyers who face psychological or brokerage minimum-lot barriers at high prices; demand builds between announcement and effective date.
3. **Analyst attention reset**: splits trigger coverage updates and price-target revisions; incremental buy-side attention arrives over the 1-2 weeks following announcement.

**Who is on the other side?** Short-term traders who sell the announcement-day pop (treating it as a "buy the rumor, sell the news" event) provide the liquidity; the drift happens as their exits are absorbed by longer-horizon retail/institutional buyers who act on the news gradually.

## Evidence
- Grinblatt, Masulis & Titman (1984) JFE: abnormal returns around split announcements in both announcement window and the period preceding the effective date.
- Ikenberry, Rankine & Stice (1996) JFQA: post-announcement drift persists 1 year for splits; short-window (days) component significant; effect larger for smaller firms.
- McNichols & Dravid (1990) JF: split factor predicts post-split earnings revisions upward → rational updating drives part of the drift.
- Desai & Jain (1997) JF: long-run abnormal returns after splits, with significant short-window component around announcement and effective date.
- Note: these are pre-2010 studies; post-publication arbitrage likely compressed long-horizon returns but short-window (< 5 day) drift is harder to arbitrage quickly.

## Rule sketch
- Universe: S&P 500/400/600 constituents that announce a forward split (ratio >= 2:1)
- Signal day: the announcement date (from EDGAR 8-K filing, item 8.01 or press release)
- Entry: buy at next open after announcement
- Exit: sell at close on announcement date + 4 trading days (or at effective split date if sooner)
- Direction: LONG only (split announcements are systematically positive signals; reverse splits are different and excluded)
- Variants: (a) exit on +2 days vs +4 days vs effective date; (b) filter by split factor (3:1+ vs 2:1); (c) market-cap tier (mid vs large)

## Data
- daily() OHLCV 1999-2026: sufficient for returns measurement
- **Announcement dates**: NOT in current archives. Need to source from SEC EDGAR 8-K filings (free, one-time extraction). EDGAR full-text search for "stock split" in 8-K filings 1999-2026 with accepted date. We have SEC_EDGAR_USER_AGENT available. This is a one-time scrape; the Researcher would need to build it as a preprocessing step.
- Alternative: Webull `get_stock_filings` for recent splits as a sanity check; yfinance has effective dates (not announcement dates) — announcement dates require EDGAR.

## Horizon
3-5 trading days (announcement open to announcement+4 or effective date close)

## Cost estimate
~15-20 bps round trip (S&P 500 large caps near 10 bps; mid/small caps 20-30 bps; splits are often large-cap or mid-cap high-flyers with good liquidity)

## Why it might NOT work
1. Low event frequency: S&P 1500 produces ~50-150 splits per year — small sample, especially post-2010 when high-priced tech stocks (NVDA, AMZN) dominate; t-stat power is limited.
2. Announcement-day pop may fully price the drift in one day; subsequent drift small.
3. Post-publication effect decay: well-known since 1984 → arb funds may have compressed it, especially the easily-traded large-cap component.
4. Effective-date reversals: some evidence of mean reversion at the exact effective date as arbitrageurs unwind; need to exit before or at the date, not after.
5. EDGAR 8-K announcement dates require non-trivial scraping and may miss same-day press releases (PR filed before 8-K).

## Differs from graveyard
- Earnings-gap continuation (graveyard): based on earnings surprise direction, not a corporate structural event; different signal and holding window.
- PEAD/ESUR (graveyard): earnings surprise drift; no connection to split calendar.
- Daily gap fade (graveyard): price-pattern rule with no event filter; split announcements are rare named events with a stated mechanism.
- Insider ideas (graveyard/queue): SEC Form 4 insider transactions; split announcements are Form 8-K corporate events — different source, different mechanism.

## Source
Ikenberry, Rankine & Stice (1996): https://doi.org/10.2307/2329108
Grinblatt, Masulis & Titman (1984): https://doi.org/10.1016/0304-405X(84)90034-6
