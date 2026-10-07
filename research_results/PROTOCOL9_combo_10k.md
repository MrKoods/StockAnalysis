# Round 4: 10,000 multi-signal combination models + 8 ridge models — pre-registered 2026-10-07, BEFORE any run

Data: hourly bars (slot 0 = 09:30 ... slot 6 = 15:30-16:00), S&P 500 (+core) for search/holdout,
S&P 400 and S&P 600 for confirmation. Same split: search < 2025-07-01, holdout >= 2025-07-01.

Windows (entry -> exit): open->10:30 close, open->13:30, open->16:00, 10:30->13:30, 10:30->16:00,
12:30->16:00, 16:00 close->next open, 16:00 close->next day 10:30.

Signals (only information available before the entry; each converted to a per-session
cross-sectional rank-z): gap/ATR, previous-day return/ATR, 5-day return/ATR, previous-day internal
bar strength, previous-day last-hour return, (prev close - 20d average)/ATR, previous-day relative
volume, ATR/price; plus, when the window starts at 10:30 or later: first-hour return/ATR and
first-hour relative volume; when it starts at 12:30 or later: open->12:30 return/ATR; when it
starts at the close: open->close return/ATR, last-hour return, day relative volume.

Random model: pick a window, 2-4 eligible signals, a weight for each from {-1, -0.5, +0.5, +1},
a tail q in {5, 10, 20%}, and a side in {both, long-only, short-only}; score = weighted sum of
rank-z; long the top q, short the bottom q. 10,000 models, seed 20261007.
Ridge models: per window, ridge regression (alpha 10) of the hedged forward return on all eligible
signals, fit on search sessions only; trade top/bottom 10%, both sides.

Metric: HEDGED net bps per trade = sign x (trade return - equal-weight universe return over the
identical window) x 1e4 - 4 (2 bps/side). t = per-session summed bps (windows do not overlap
within a model).

Stage 1 (search): all 10,008 models scored on search sessions; best-of-N luck test and CSCV PBO
reported for the random set.
Stage 2 (shortlist): top 10 random models by search t with n >= 3,000 (identical-trade duplicates
skipped) + all 8 ridge models = 18 candidates.
Stage 3 (S&P 500 holdout, once): PASS = hedged mean > 0, t >= 2.9 (Bonferroni for 18), positive in
2025-H2 and 2026, and positive on each side traded.
Stage 4 (S&P 400 and S&P 600, full period, once each): hedged mean > 0 and t >= 2.0 in both.
Selection: up to 3 by the smaller confirmation t, no two from the same window.
