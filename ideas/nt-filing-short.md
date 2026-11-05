# nt-filing-short

## Mechanism
When a company cannot file its 10-K or 10-Q by the SEC deadline, it must submit a "Notification of Late Filing" (Form NT 10-K or NT 10-Q). The notification is a public disclosure that management cannot certify the financials on time. Ettredge, Lee & Scholz (2000) show that NT filers subsequently report larger negative earnings surprises and experience downward analyst forecast revisions. Kinney & McDaniel (1989) show late filers have higher rates of subsequent financial restatements and internal-control weaknesses. The market underreacts at the NT filing date — investors often wait for the actual filing before trading — creating a 1-3 day negative drift window for informed short-sellers.

**Who is on the other side?** Passive holders who do not monitor NT filings in real time; systematic strategies that wait for the actual 10-K/Q before reacting; retail investors who don't distinguish NT from the actual filing.

## Evidence
- Ettredge, Lee & Scholz (2000) CAR: NT 10-K filers show a mean abnormal return of approximately −50 to −70 bps in the 2 days after the NT filing; analysts revise earnings forecasts downward in the 10 days following.
- Kinney & McDaniel (1989) TAR: late annual report filers have a 3.5× higher rate of subsequent auditor change and restatement vs timely filers.
- NT filings are a NEW family (`nt_filing`) — no prior research in this codebase; entire history clean.

## Rule sketch
- Universe: S&P 500 only (large cap, to keep borrow cost manageable; small-cap borrowing on distressed names is prohibitive)
- Signal: acceptance of Form NT 10-K or NT 10-Q for a company in the universe
- Entry: SHORT at open on the next trading day after the NT acceptance timestamp is public (open+1)
- Exit: cover at open+4 (3-day hold)
- Variants: (a) extend to S&P 1500 for research only (wider sample, borrow cost not modelled in backtest); (b) 5-day hold; (c) filter out NT filings that are concurrent with an 8-K 2.02 (earnings release) — those are already priced
- Note: paper_runner.py needs direction='short' in the strategy config; flag for researcher

## Data
- `filings(forms=['NT 10-K', 'NT 10-Q'], tickers=sp500)`: event date + acceptance time
- `daily(tickers)`: OHLCV for entry/exit + return calculation
- **Family**: `nt_filing` (new, entirely clean; no prior screen or researcher use)
- `live for paper?`: filings() is live (SEC daily index each dispatch) — YES

## Horizon
3 trading days (open+1 to open+4 from event date)

## Cost estimate
~15-20 bps round trip for S&P 500 (liquid names; borrow cost assumed standard; small-cap borrow excluded by universe filter). Net target: needs mean drift > 20 bps after costs.

## Why it might NOT work
1. Many NT filers resolve the issue quickly (file the actual report within 15 days); stock bounces after filing, partially or fully reversing the short
2. S&P 500 filter restricts universe to large liquid firms where analysts notice NT filings immediately — the underreaction window may be very short
3. Borrow cost for distressed names is hard to estimate; paper-runner borrow cost model may not be accurate
4. NT filings often accompany known issues (pending restatements announced elsewhere); the negative drift may already be in the price
5. paper_runner.py currently only supports long direction by default — researcher must verify short support in the engine

## Differs from graveyard
- No NT filing idea has ever been tested in this codebase
- insider-cluster-buys (dead): entirely different family and mechanism
- analyst-initiation-buy (dead): analyst-driven positive signal, not regulatory-filing-driven negative signal

## Source
Ettredge, Lee & Scholz (2000): https://doi.org/10.1506/EQ8K-J2X7-NHKF-C0BW
Kinney & McDaniel (1989): https://doi.org/10.2308/accr.1989.64.4.709
