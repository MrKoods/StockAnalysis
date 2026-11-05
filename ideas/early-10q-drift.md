# early-10q-drift

## Mechanism
Chambers & Penman (1984) showed that companies filing their annual report earlier than expected signal positive news — managers with bad results delay disclosures. Begley & Fischer (1998) confirm the effect extends to 10-Q filings: early quarterly filers have better earnings surprises and lower accruals. A stock that files its 10-Q at least 5 days before the same quarter's filing in the prior year is sending a voluntary "good news" signal to investors who pay attention to filing timestamps. Because 10-Q processing is lower-profile than earnings press releases, the signal is under-noticed, creating a drift over 1-3 days as market participants catch on.

**Who is on the other side?** Passive investors who miss the filing timestamp signal; systematic strategies that only react to earnings dates, not 10-Q filing dates.

## Evidence
- Chambers & Penman (1984) JAR: annual-report early filers outperform late filers in the 60 days surrounding filing; mechanism generalises across reporting periods.
- Begley & Fischer (1998) JAE: 10-Q timeliness predicts the sign of subsequent earnings surprise and analyst forecast revision; early-filing effect is distinct from earnings surprise itself.
- Analogous idea `early-10k-drift` (10k_timing family) is at `idea` stage with strong academic support; 10-Q is 4× more frequent and allows tighter test windows.

## Rule sketch
- Universe: S&P 1500
- Signal: 10-Q acceptance date is >=5 trading days earlier than the same quarter's 10-Q acceptance date one year prior (compare Q1 FY2015 vs Q1 FY2014, etc.)
- Entry: buy at open on the next trading day after the 10-Q acceptance timestamp is public
- Exit: sell at open+3 (3 trading days after entry open)
- Variants: (a) >=10 days early threshold; (b) small/mid-cap only; (c) SPY hedge; (d) also test late filers (>=5 days LATER than prior year) as a short

## Data
- `filings(forms=['10-Q'], tickers=sp1500)`: acceptance date per company per quarter
- `daily(tickers)`: OHLCV for entry/exit pricing + size filter
- **Family**: `10q_timing` (new, entirely clean)
- Note: match quarter by fiscal quarter number (not calendar quarter), since fiscal years vary across companies

## Horizon
3 trading days (open+1 to open+4 from event date)

## Cost estimate
~15-20 bps round trip (mostly large/mid-cap S&P 1500 names)

## Why it might NOT work
1. Many companies file on a highly regular schedule (same week each year); the "early vs prior year" delta may be noisy rather than informative
2. Some 10-Qs are filed early simply because the company has a simple business (less information content in the signal)
3. 10-Q content is less scrutinised than 10-K; the market may not update on the filing timestamp at all
4. High event rate (~1,500-1,800/yr early filers) could dilute the signal if most early filers are systematic, not news-driven
5. Same family as `early-10k-drift`; a combined 10-K + 10-Q timeliness test by the researcher may be more efficient

## Differs from graveyard
- early-10k-drift (at idea stage, different form type): 10-Q gives quarterly frequency vs annual; separate idea
- No prior test on 10-Q timeliness in this codebase

## Source
Chambers & Penman (1984): https://doi.org/10.2307/2490966
Begley & Fischer (1998): https://doi.org/10.1016/S0165-4101(98)00009-8
