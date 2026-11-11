# issuer-self-tender-long

## Mechanism
When a company launches a **self-tender offer** (offers to repurchase its own shares from shareholders at a premium to market price), it signals to the market that management believes the stock is undervalued. The tender offer creates a hard price floor (no shareholder will tender below the offer price, so the stock cannot trade significantly below it). Arbitrageurs and institutional investors buy shares in the days after the announcement to capture the spread between market price and tender price.

Unlike open-market buybacks (which are gradual and deniable), self-tender offers are firm commitments: the company publicly offers to buy a specific number of shares at a specific premium within a defined tender period. The undervaluation signal is therefore hard and time-limited, generating concentrated short-term buying pressure.

**Who is on the other side?** Passive holders who do not monitor for corporate announcements immediately; retail sellers who don't track tender offer filings; short-sellers who must cover into the price floor.

## Evidence
- Peyer & Vermaelen (2009) "The Nature and Persistence of Buyback Anomalies," Review of Financial Studies: documents +200 bps cumulative abnormal return at tender offer repurchase announcements for the first 3-5 days. Mechanism: undervaluation signal + price floor from tender premium.
- Lie (2005) "Operating Performance Following Open Market Share Repurchase Announcements," Journal of Financial Economics: tender offer repurchases show significantly stronger short-term price reaction than open-market repurchases — the commitment mechanism drives stronger market response.
- Mechanism is durable: the price floor mechanism is mechanical, not behavioural, and cannot be easily arbitraged away (the floor exists as long as the offer is open).

## Rule sketch
- Universe: S&P 1500 members
- Signal: `filings(forms=['SC TO-I'], tickers=sp1500)` — company files SEC Form SC TO-I (Issuer Tender Offer Statement, i.e., company buying its OWN shares via tender). This is NOT SC TO-T (third-party tender, which has survivorship bias issues).
- Entry: LONG at CLOSE of the SC TO-I filing date (after the market has had the full trading day to react to the pre-market or intraday filing; avoids expensive open fills)
- Exit: CLOSE+3
- Hold: 3 trading days (close-to-close)
- Variants: (a) all S&P 1500; (b) S&P 500 only; (c) close+5 exit; (d) condition on prior 20d momentum < 0 (deeper undervaluation signal)
- Note: researcher must verify SC TO-I is queryable from filings(); if the form type is not in the index, this idea needs data sourcing.

## Data
- `filings(tickers, forms=['SC TO-I'])`: event date and acceptance time for issuer self-tenders. Researcher must confirm SC TO-I is accessible via filings() in research_data.py.
- `daily(tickers)`: OHLCV close prices for entry/exit
- **Family**: `self_tender` (new family, entirely clean — no prior screen, no search, no holdout)
- `live for paper?`: filings() YES (SEC daily index each dispatch, one-day lag)

## Horizon
3 trading days (close-to-close, detection day to close+3).

## Cost estimate
Close-to-close, blended S&P 1500: ~6.4-21.8 bps RT depending on index. At 13 bps blended: net = gross - 13 bps.

## Expected events
S&P 1500 self-tender offers: estimated 20-50/year (self-tenders are less common than open-market buybacks). Over 25 train years = 500-1,250 events. Power: at 75 bps signal and σ ~300 bps, 500 events gives t ≈ 5.6; 250 holdout events gives t ≈ 3.9 (above bar 3.0). Researcher must verify actual event count from filings() before committing to this family.

## Why it might NOT work
1. **Low event count**: if SC TO-I events in S&P 1500 are fewer than 20/year, power may be insufficient. Researcher should check counts first.
2. **Day-0 pricing**: if the full tender premium is already priced at close of day 0 (after premarket announcement), residual drift to close+3 may be only 20-30 bps — below the gross threshold. The 200 bps Peyer & Vermaelen figure includes the initial announcement-day jump.
3. **Form availability**: SC TO-I may be in the SEC daily index (filings()) but needs researcher verification that filings(forms=['SC TO-I']) returns usable rows.
4. **Deal completion risk**: very low for self-tenders (the issuer controls execution), but if a company withdraws the tender offer (rare), returns would reverse sharply on a small number of events, adding noise.
5. **Survivorship bias**: minimal — the issuer (the repurchasing company) stays in S&P 1500 after the tender. Unlike acquisition targets, the repurchasing company is not delisted.

## Differs from graveyard
- No self_tender family test has been run. No prior test used SC TO-I.
- split-announcement-drift (DEAD): entirely different — split-announcement was for forward stock splits (5.03 8-K), not self-tenders. Different corporate action, different mechanism.
- activist-13d-long (DEAD): different — SC 13D = third-party acquires 5%+ stake; SC TO-I = company buying back its own shares.
- pipe-short (DEAD): different direction and mechanism — PIPE is a dilutive equity sale; SC TO-I is a buyback at premium.
- Not related to any dead or dropped idea.

## Source
Peyer, U., & Vermaelen, T. (2009). The Nature and Persistence of Buyback Anomalies. Review of Financial Studies, 22(4), 1693–1745.

Lie, E. (2005). Operating Performance Following Open Market Share Repurchase Announcements. Journal of Accounting and Economics, 39(3), 411–436.
