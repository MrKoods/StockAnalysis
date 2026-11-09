# seo-short

## Mechanism
When an already-public S&P 1500 company prices a follow-on equity offering, it is issuing new shares at or near current market price. Myers & Majluf (1984) show that equity issuance is a negative signal: rational managers only issue when they believe the stock is overvalued. The offering prospectus (424B4 or 424B5 on EDGAR) is the pricing-day disclosure. Loughran & Ritter (1997) find that SEO firms underperform by ~-3% in the first 3-5 trading days post-offering and by -15% over the following 3 years. D'Mello & Ferris (2000) show -2.5% in the 3-day window around the offering date.

**Who is on the other side?** Long investors who believe the offering proceeds will be deployed productively; index funds that must own the stock regardless; retail participants who don't track EDGAR prospectus filings.

**Differs from pipe-short (8k_3_02, dead):** PIPEs (8k_3_02) are unregistered private placements to hedge funds at a discount — the sophisticated hedge fund buyer signals that the company may be undervalued from their perspective. Public equity offerings (424B4/424B5) are priced at market; there is no sophisticated buyer signalling value. The academic evidence is consistently negative for public SEOs but mixed for PIPEs.

## Evidence
- Myers, S.C. & Majluf, N. (1984): Adverse selection model predicts equity issuance is negative signal; stock should decline at announcement.
- Loughran, T. & Ritter, J.R. (1997): SEOs underperform by ~-3% in the 5 trading days after the offering date (gross); -15% over 3 years. SSRN.
- D'Mello, R. & Ferris, S.P. (2000): 3-day CAR around SEO pricing is -2.5% (250 bps). Journal of Financial Economics.
- Spiess, D.K. & Affleck-Graves, J. (1995): Short-window (5-day) return at SEO announcement: -1.5% to -3%. Journal of Financial Economics.
- Gross edge: ~150-300 bps over 3-5 trading days. Well above the 50-bps threshold.

## Rule sketch
- Universe: S&P 1500
- Signal: acceptance of a 424B4 or 424B5 SEC filing for a ticker that is currently in the S&P 1500 universe (excludes IPOs by construction; they would not be in S&P 1500 at filing time)
- Entry: SHORT at CLOSE on detection day (the dispatch-day close after the EDGAR filing appears in the daily index)
- Exit: cover at close+3
- Variants to test: (a) 424B4 only; (b) 424B5 only; (c) both combined; (d) SP500 vs SP400+600; (e) 5-day hold
- Note: researcher should check event counts for each sub-form. If 424B5 events are sparse in S&P 1500, expand to include 424B3 (shelf pricing supplement). Many large-cap follow-on offerings also appear as 424B3.
- If the researcher can distinguish common equity offerings from debt/preferred (e.g., by checking the cover page for "Common Stock"), prioritize equity-only. If not, the blended result should still be net negative (debt SEOs are mildly negative: ~-50 bps; equity SEOs ~-300 bps).

## Data
- `filings(forms=['424B4','424B5'], tickers=sp1500)`: event dates (prospectus pricing day)
- `daily(tickers)`: OHLCV for entry/exit + return calculation
- **Family**: `seo_offering` (entirely new — no screen, no researcher variants, no holdout used)
- `live for paper?`: filings() is live (SEC daily index each dispatch) — YES

## Horizon
3 trading days (close-to-close, detection day to close+3). Can extend to 5 days.

## Cost estimate
Expected mix of SP400/SP600 close entries (SP500 companies rarely do follow-on equity offerings once at scale). Round trip: ~12-22 bps. Net edge: ~130-290 bps (highly viable).

## Expected events
Rough estimate: 100-300 follow-on equity pricing events per year in S&P 1500. Over holdout period (10+ years): 1,000-3,000 events. Well-powered IF the researcher can confirm the event counts. Researcher MUST report event counts first — if too sparse (< 50/year), power is marginal.

## Why it might NOT work
1. The offering date effect is widely known; algorithmic traders may already short at the EDGAR filing instant, leaving little residual edge by close
2. 424B4/424B5 includes non-equity securities (debt, preferred, hybrids) that dilute the negative signal; requires subgroup analysis
3. Survivorship bias: S&P 1500 companies that did equity offerings and then delisted are excluded from our universe, possibly upward-biasing the negative return estimate
4. Post-2015 market microstructure: increased short borrowing costs for mid/small-cap SEO stocks can eat into the edge
5. Offering discount (SEOs priced below current market to attract buyers) is typically small (~2-3%), limiting the downward move

## Differs from graveyard
- pipe-short (dead): different mechanism — public offering vs. private placement; different academic literature; public SEOs consistently negative whereas PIPEs have offsetting sophisticated-investor signal
- No SEO (424B4/424B5) idea has been registered or researched before

## Source
Loughran, T. & Ritter, J.R. (1997). The Operating Performance of Firms Conducting Seasoned Equity Offerings. Journal of Finance, 52(5), 1823–1850.
D'Mello, R. & Ferris, S.P. (2000). The Information Effects of Analyst Activity at the Announcement of New Equity Issues. Financial Management.
Myers, S.C. & Majluf, N.S. (1984). Corporate Financing and Investment Decisions When Firms Have Information That Investors Do Not Have. Journal of Financial Economics, 13(2), 187–221.
