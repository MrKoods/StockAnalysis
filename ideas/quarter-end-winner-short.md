# quarter-end-winner-short

## Mechanism
Mutual funds and institutional investors engage in "window dressing" — buying recent winners and selling losers before each quarter-end to make their reported portfolios look better. This creates artificial buying pressure on top-performing stocks on the last 1-2 days of each quarter. When the quarter ends and reporting is complete, that artificial demand evaporates, causing a reversal in the first 1-3 trading days of the new quarter.

Carhart et al. (2002) document this in the Journal of Finance: mutual fund managers systematically inflate quarter-end prices of recent winners by ~0.9% (90 bps) on the last trading day of the quarter, with a corresponding reversal in the first few days of the new quarter. The signal fires 4× per year (end of March, June, September, December).

**Who is on the other side?** Window-dressing institutional managers who have already locked in their quarter-end portfolio for reporting; index funds tracking stale quarter-end weights; retail investors who buy recent winners.

**Differs from quarter-end-window-dressing (dropped):** The dropped idea was LONG the winners going into quarter-end (riding the dressing). This idea is the REVERSE: SHORT the same winners AFTER quarter-end to capture the reversal when institutional buying stops. Different entry side, different timing, different direction.

## Evidence
- Carhart, M.M., Kaniel, R., Musto, D. & Reed, A.V. (2002): "Leaning for the Tape: Evidence of Gaming Behavior in Equity Mutual Funds," Journal of Finance, 57(2), 661–693. Last-day quarter-end return inflation of ~0.9% (90 bps); reversal 1-3 days into new quarter.
- Duong, T.X. & Meschke, F. (2020): "The Rise and Fall of Portfolio Pumping among U.S. Mutual Funds," Journal of Corporate Finance. Find continued evidence of quarter-end return inflation post-2000, with partial attenuation post-2010.
- Bhattacharyya, S. & Nanda, V. (2013): Theory model showing equilibrium portfolio pumping generates 60-90 bps in winners on last day, with reversal.
- Gross edge: ~90 bps from Carhart et al. (2002). After SP400 close costs (~12 bps RT): net ~78 bps per event.

## Rule sketch
- Universe: S&P 1500
- Signal: on the LAST TRADING DAY of each calendar quarter (last NYSE session of March, June, September, December), identify stocks in the top-N (N=50 to 100) by 20-day or 30-day price return within the S&P 1500 universe
- Entry: SHORT at CLOSE on that last-quarter-day session (same-day close entry); paper runner should support "entry at close on signal day"
- Exit: cover at close+3 (3 sessions into new quarter)
- Timing: signal fires 4× per year; each signal covers ~50-100 stocks → ~200-400 "event-stock" pairs per year
- Variants to test: (a) top-30d vs top-20d return for ranking; (b) top-50 vs top-100 stocks; (c) SP500 only; (d) 5-day hold; (e) SP400+600 (smaller caps may have stronger window-dressing effect)
- Note: entry must be at the SAME session's close (not next open), otherwise the reversal from open of day 1 of new quarter is missed. Flag this for paper runner implementation.

## Data
- `daily(tickers)`: OHLCV for 30-day rolling return (ranking) and entry/exit prices
- Calendar: NYSE holiday calendar (last trading day of each quarter)
- **Family**: `calendar_effects` (search period 1999-2014 used by turn-of-month train run; holdout 2015-2026 clean)
- `live for paper?`: daily(tickers) is live — YES

## Horizon
3 trading days (close-to-close, signal day close to close+3). Signal fires quarterly.

## Cost estimate
S&P 1500 close entry. For large-cap (SP500): ~6.6 bps RT; SP400: ~12.0 bps; SP600: ~21.8 bps. If targeting SP400+600 (where dressing effect may be stronger): ~15 bps RT. Net edge ~75 bps.

## Expected events
4 quarter-ends × 50-100 stocks = 200-400 event-stock pairs per year. Over holdout 2015-2026 (11 years): ~2,200-4,400 event-pairs. Excellent statistical power.

## Why it might NOT work
1. Effect may have attenuated post-2010 as ETFs dominate (ETFs don't window dress) and algorithmic traders close the arbitrage
2. The reversal depends on institutional calendar behavior; if funds shift to fiscal-year-end cycles (not calendar quarter), the signal weakens
3. Some winners have genuine momentum (continuing the run): hard to separate window-dressed winners from real-momentum ones without additional conditioning
4. Carhart et al. (2002) studied 1985-1995; Duong & Meschke (2020) find partial decay. Post-2015 (the holdout period) may show a significantly attenuated effect
5. Short borrowing cost for high-momentum stocks can be elevated (they are frequently shorted)

## Differs from graveyard
- quarter-end-window-dressing (dropped): that idea was LONG winners going INTO quarter-end. This is SHORT winners AFTER quarter-end. Different direction, different entry side, different mechanism phase. The dropped idea was dropped by the user before testing, not because it failed.
- turn-of-month (dead): different calendar trigger (month-end vs quarter-end); different mechanism (risk-on inflows vs window dressing)
- year-end-loser-reversal (at `idea`): different direction (buy losers vs short winners); different season (year-end vs all quarter-ends)

## Source
Carhart, M.M., Kaniel, R., Musto, D. & Reed, A.V. (2002). Leaning for the Tape: Evidence of Gaming Behavior in Equity Mutual Funds. Journal of Finance, 57(2), 661–693.
Duong, T.X. & Meschke, F. (2020). The Rise and Fall of Portfolio Pumping among U.S. Mutual Funds. Journal of Corporate Finance.
