# turn-of-month

## Mechanism
Fund flows drive a predictable price cycle at month-end/month-start. Pension funds, 401k contributions, and dividend reinvestment programs concentrate cash deployment in the last 1-2 trading days of the month and first 2-3 days of the next. This buying pressure is structural and repeat-scheduled, not information-driven. The sellers on the last day of the month are short-horizon traders and retail; the buyers are longer-horizon institutions with fixed contribution schedules.

**Who is on the other side?** Momentum short-sellers and month-end window dressers who exit before month close; they provide the liquidity that TOM buyers absorb.

## Evidence
- Ariel (1987) "A Monthly Effect in Stock Returns" - Journal of Financial Economics: documents the TOM effect in US equities 1963-1981
- Lakonishok & Smidt (1988): confirms TOM for DJIA 1897-1986
- McConnell & Xu (2008) "Equity Returns at the Turn of the Month" - Financial Analysts Journal: confirms effect persists post-publication (through 2005); attribute to cash flow timing not data mining
- Ogden (1990): links TOM specifically to coupon/dividend payment timing
- Effect is present across multiple countries (Agrawal & Tandon 1994)

## Rule sketch
- Universe: S&P 500 (large-cap, liquid; costs ~10 bps round trip)
- Entry: buy at close on the LAST trading day of calendar month (T)
- Exit: sell at close on 3rd trading day of new month (T+3 net, 4 trading days held)
- Variants to test: (a) all stocks equally weighted; (b) filter by prior-month return (momentum tilt); (c) S&P 400/600 subsets; (d) exit on T+1 or T+2 instead

## Data
- daily() S&P 500/1500 prices 1999-2026: sufficient (just need OHLCV and calendar dates)
- No additional data sources needed

## Horizon
~4 trading days (end of month + 3 days into new month)

## Cost estimate
~10 bps round trip for S&P 500 names (liquid, ETF-style execution)

## Why it might NOT work
1. Well-known and widely published since 1988 → likely arbitraged away; McConnell & Xu (2008) found it weakening
2. The effect may be concentrated in small/micro-caps and not survive in S&P 500 after costs in recent data
3. Holding all 500 stocks simultaneously is capital-intensive → must be a selection rule or sector tilt for meaningful sizing
4. Post-pandemic fund flows (automatic ETF accumulation, intraday processing) may have removed the calendar timing

## Differs from graveyard
- Overnight reversal (graveyard): buy close, sell next open — totally different signal
- Daily classics (graveyard): pure price pattern rules (RSI2, IBS, gap fade) — no calendar component
- TOM is a structural flow effect with a named mechanism, not a price pattern

## Source
McConnell & Xu (2008): https://www.cfainstitute.org/en/research/financial-analysts-journal/2008/equity-returns-at-the-turn-of-the-month
Ariel (1987): https://doi.org/10.1016/0304-405X(87)90044-5
