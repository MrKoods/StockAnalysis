# Five new strategy families — protocol pre-registered 2026-10-06, BEFORE any scan or download

Goal: up to 3 more forward-test models alongside G2.

Families (hourly bars; slot 0 = 09:30 ... slot 6 = 15:30-16:00):
- XS  cross-sectional morning: rank stocks by morning return (raw or minus the universe average);
      long bottom q / short top q (rev) or the opposite (mom); enter next bar open, exit at a later close
- PER time-of-day periodicity: rank by the stock's average return in slot k over the past N days;
      trade slot k today (enter slot-k open, exit slot-k close)
- ON  overnight: rank by today's return (intraday / last hour / close-to-close, raw or minus market);
      hold close -> next open; plus an all-long baseline
- MR  idiosyncratic intraday mean reversion: stock's move from the open by slot j minus the market's,
      in daily ATR; fade (or follow) moves beyond a threshold; exit at a later close or back at the open
- NR  opening-range breakout only after a narrow day (NR4 / NR7 / inside day)

Costs: 2 bps per side on every trade. Unit: net bps per trade; t = day-clustered (daily sums).

Stage 1 search: S&P 500 + core tickers, sessions < 2025-07-01. Per family, CSCV PBO and a
t-standardized best-of-N luck test are reported (informational).
Stage 2 shortlist: per family, the top config by search t with n >= 2,000, plus the next-best whose
core (non-filter) parameters differ -> max 10 candidates.
Stage 3 holdout (S&P 500, sessions >= 2025-07-01, evaluated once): PASS = mean > 0, t >= 2.6
(Bonferroni for 10), positive in 2025-H2 and in 2026, and positive for longs and shorts separately
when the config trades both.
Stage 4 confirmation (untouched): S&P 400 midcaps and S&P 600 small caps, full ~2 years, evaluated
once each: PASS = mean > 0 with t >= 2.0 in BOTH universes.
Selection: rank Stage-4 survivors by the smaller of the two confirmation t-stats; top 3 (at most one
per family) become forward-test models. If fewer than 3 survive, fewer are selected.
