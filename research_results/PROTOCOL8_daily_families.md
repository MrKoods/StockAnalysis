# Route 2: short-horizon DAILY families — protocol pre-registered 2026-10-06, BEFORE any download

Data: yfinance daily bars (auto-adjusted for splits/dividends), from 2000. Universes: current S&P 500
(stocks only), S&P 400, S&P 600, plus 15 ETFs (SPY QQQ IWM DIA, 9 sector SPDRs, TLT, GLD).
Known bias: current constituents only (survivorship). Mitigated by the hedged metric below.

Metric (stock families): HEDGED net bps per trade = sign x (trade return - equal-weight universe
return over the identical entry/exit points) x 1e4 - 4 (2 bps per side). Raw also reported.
ETF calendar family: excess over the same ETF's average return for windows of equal length in the
evaluated period. t-stats: Newey-West (lag = max holding days) on the daily series of summed bps by
entry date.

Families
- REV  cross-sectional reversal/momentum on past k-day return (k 1,2,3,5,10), tails q 5/10/20%,
       hold 1,2,3,5 days, entry at the close or the next open
- MRV  time-series mean reversion: RSI(2) / internal bar strength / N down closes in a row; optional
       200-day trend filter; exit on close above the 5-day average (max 10 days) or after 1/3/5 days
- ONX  overnight: buy losers/winners (intraday or close-to-close) at the close, sell next open; all-long
- GAPD daily gap fade/go (the G2 mechanism over 25 years): gap >= 0.25-1.5 ATR, trend filter
       none / 20-day / 200-day, exit same-day close or next close, previous-close target (fade)
- BRK  close at an N-day high/low (N 5,10,20,55): follow or fade, hold 1,3,5,10 days
- CAL  ETF calendar: turn-of-month windows, pre-holiday day, day-of-week

Stage 1 search: S&P 500 stocks (ETFs for CAL), 2000-01-01 .. 2017-12-31.
Stage 2 shortlist: per family the top config by search t (n >= 2,000; CAL n >= 200) + next-best with
different core params; identical-trade duplicates skipped.
Stage 3 holdout: S&P 500 2018-01-01 .. 2026-10-05, evaluated once. PASS = hedged mean > 0,
NW t >= 2.7 (Bonferroni for <= 12 candidates), positive in 2018-2021 and in 2022-2026, positive for
long and short sides separately when both are traded; for close-entry configs the next-open-entry
twin must also have a positive holdout mean (guards the signal-at-the-close look-ahead).
CAL is judged on its ETFs in the same holdout period.
Stage 4 confirmation: S&P 400 and S&P 600, 2018 .. 2026, once each: hedged mean > 0, NW t >= 2.0
in both (CAL: no Stage 4; needs t >= 2.7 at Stage 3).
Selection: top 3 by the smaller confirmation t, at most one per family.

Amendment (2026-10-06, before any scan): ONX enters at the close by construction and has no
next-open twin, and CAL uses no price signal; both are exempt from the twin rule. ONX's signal
uses the closing price it trades at; that limitation is reported, not hidden.

Bug fix + rerun (2026-10-07): the first run computed filter features (200-day trend, ATR%,
liquidity) from the ENTRY session's close, which an open-entry trade cannot know (look-ahead; it
made "with_trend" select trades that had already won: search t up to 33). Fixed to use the prior
close for open entries; regression test added. Stages 1-4 are rerun unchanged. The first run's
holdout numbers were seen but nothing was tuned on them; the rerun applies the identical rules.
