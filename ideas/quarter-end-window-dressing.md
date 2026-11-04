# quarter-end-window-dressing

## Mechanism
Mutual fund and institutional managers are evaluated on their portfolio holdings at each quarter-end. To show high-performing stocks in their reported holdings, they buy stocks that have recently risen (prior-quarter or prior-60-day winners) in the final 1-3 trading days of each quarter — a practice documented as "window dressing" or "leaning for the tape." This creates temporary buying pressure that inflates winner prices at quarter-end. The effect exists in all 4 quarters, giving 4× the event count of a January-only calendar strategy.

**Who is on the other side?** Long-term holders who sell into the temporary buying pressure; arbitrageurs who recognise the effect but face timing uncertainty about its exact duration.

## Evidence
- Carhart, Kaniel, Musto & Reed (2002) Journal of Finance "Leaning for the Tape: Evidence of Gaming Behavior in Equity Mutual Funds": documented average 0.28% abnormal returns for winner stocks in the final day of the quarter, with reversal in the first few days of the new quarter. Effect is concentrated in December but present in all quarters.
- Sias (2007) FAJ "Window-Dressing, Tax-Loss Selling, and Momentum Profit Seasonality": momentum strategy profits are significantly higher in quarter-ending months; linked to institutional window dressing. Strongest in stocks with high institutional ownership.
- Haugen & Lakonishok (1988) "The Incredible January Effect": documented that institutional window dressing in December drives part of the turn-of-year effect; the quarterly version generalises this.
- Ng & Wang (2004) SSRN "Institutional Trading and the Turn-of-The-Year Effect": institutional investors buy prior-year winners and sell prior-year losers around year-end; trading patterns confirm window dressing.

## Rule sketch
- Universe: S&P 1500 stocks in the top quintile of 60-day price return (prior-60-day winners)
- Entry: buy at close 2 trading days before each quarter-end (i.e., T-2 relative to 3/31, 6/30, 9/30, 12/31; the actual last trading day if the calendar date falls on a weekend/holiday)
- Exit: sell at close on the last trading day of the quarter (hold = 2 days)
- Variants: (a) hold 1d vs 2d vs 3d; (b) top quintile vs top decile momentum; (c) SPY-hedged return; (d) large cap only vs full S&P 1500
- Expected events: 4 quarters/yr × ~300 eligible stocks (top 20% of 1500) = ~1,200 events/yr (well-powered)

## Data
- `daily(tickers)`: OHLCV for 60-day momentum computation and entry/exit pricing
- Calendar computation only: quarter-end dates derivable from date alone (no additional data needed)
- **Family**: calendar_effects (same as turn-of-month; 0 holdouts used); train 2000-2017; holdout 2018-2026

## Horizon
2 trading days (close T-2 to close T=0, i.e., last day of quarter)

## Cost estimate
~10-15 bps round trip (S&P 1500 is predominantly large/mid cap; liquid names)

## Why it might NOT work
1. Effect has been widely studied and published since 2002 — may have been partially arbitraged away by hedge funds that now front-run it
2. The window dressing motive weakens as passive investing grows (passive managers don't window dress)
3. The 60-day momentum filter overlaps with the momentum anomaly — hard to separate the calendar component from the base momentum edge
4. December has the strongest effect (also has tax-loss selling); the other 3 quarters may be weak, diluting the annual average

## Differs from graveyard
- turn-of-month (idea stage): different calendar trigger (last day of month, not quarter) and no momentum filter; different mechanism (payment timing vs. window dressing)
- Earnings gap continuation (graveyard): event-driven by earnings, not calendar

## Source
Carhart et al. (2002): https://doi.org/10.1111/1540-6261.00492
Sias (2007): FAJ 63(6), "Window-Dressing, Tax-Loss Selling, and Momentum Profit Seasonality"
Ng & Wang (2004): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=426900
