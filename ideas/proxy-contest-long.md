# proxy-contest-long

## Mechanism
When an activist investor files a DFAN14A (non-management definitive proxy statement),
it signals a contested annual meeting: the activist is nominating directors or pushing
shareholder proposals against the board's wishes. For S&P 400+600 companies (mid/small
caps), the DFAN14A filing is typically the FIRST public disclosure of the contest; news
does not pre-leak to Bloomberg before the SEC EDGAR filing the way it does for large caps.
The market underreacts at the close of the filing day because:
(1) DFAN14A is filed after hours in many cases, limiting same-day reaction;
(2) small/mid-cap investors are slower to process new 13F-class filings;
(3) the eventual governance improvement and control premium are under-priced at the
announcement date as research on activist outcomes takes days to disseminate.

## Evidence
- Fos (2017, SSRN 1705707): "The Disciplinary Effects of Proxy Contests" — target companies
  earn an average cumulative abnormal return of ~6.5% around proxy contest announcements
  (measured over a wide event window); the target reacts significantly on the announcement day.
- For S&P 400+600 targets where the DFAN14A IS the announcement: a large portion of the
  6.5% that is not in the pre-filing window is realized in the 1–3 trading days following
  the filing. Conservative short-horizon gross edge estimate: ~100–200 bps over 3 days.
- Listokin (2008, Yale Law): close proxy votes → governance improvements persist for
  2–4 weeks post-announcement.

## Rule sketch
1. Screen filings() for form type DFAN14A filed by any entity for a S&P 400 or S&P 600
   ticker (issuer = that ticker).
2. Enter at close on the day of the DFAN14A acceptance (the filing day).
3. Exit at close+3 (3 trading days later).
4. Direction: LONG target company.
5. Exclude if any earnings announcement is within 3 trading days (avoid earnings contamination).

## Data
- `filings(forms=['DFAN14A'], tickers=sp400+sp600)`: acceptance dates for proxy contest filings.
- `daily(tickers)`: OHLCV bars for entry/exit prices.
- `earnings(tickers)`: used only as exclusion filter.

## Expected events
~20–25 per year in S&P 400+600 based on published proxy contest frequency;
~240–300 events in a 12-year holdout (2014–2026). Researcher must verify DFAN14A
count in filings(); total might also include DEFC14A (contested DEF 14A) and SC 14N
(director nominations by institutional shareholders) — worth testing as variants.

## Horizon
3d (close to close+3)

## Cost estimate
~17 bps round trip (S&P 400 close: ~12 bps; S&P 600 close: ~22 bps; blended ~17 bps).
Net edge estimate: ~83–183 bps after costs.

## Why it might NOT work
- Event count may be lower than estimated if DFAN14A count in S&P 400+600 is <15/yr;
  would leave insufficient holdout power.
- S&P 400 large-cap proxies may leak news to Bloomberg/WSJ pre-filing → Day 0 close
  already prices most of the 6.5%; residual drift below 50 bps.
- Many proxy contests settle quickly (before the meeting date), so the full governance
  premium is not realized in 3 days; resolution timing is uncertain.
- Fos (2017) event window is wide (not specifically the 3-day post-filing window); the
  short-horizon effect size is estimated, not directly cited.

## Differs from graveyard
- Different from `activist-13d-long` (SC 13D initial filing = hostile stake build;
  dead, t=0.17): proxy contests are a later-stage escalation with management confrontation
  that creates direct governance catalyst; also different form type.
- No proxy_contest family entries in the graveyard.

## Family status
proxy_contest — new family, entirely clean.
