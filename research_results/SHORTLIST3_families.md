# Strategy-family holdout rules — pre-registered 2026-10-06, BEFORE any family search results were seen

Families: MOM (intraday momentum/reversal), GAP (gap fade / gap-and-go), ORB (first-hour breakout),
hourly bars, 509 tickers. Search = sessions < 2025-07-01. Holdout = 2025-07-01 .. 2026-10-05.

Shortlist (max 5 configs, chosen from search results only):
1. The top config by day-clustered t (n >= 2,000 trades) of every family whose best config beats
   that family's own best-of-N luck baseline at p < 0.05.
2. Plus the top 2 configs overall by search t (n >= 2,000), whatever the luck test says.
Configs that differ only in a filter that keeps the same trades count once.

Holdout PASS (per config), evaluated once:
- mean net (1 cent/side) return > 0 in ATR units, day-clustered t >= 2.6 (Bonferroni for 5)
- positive for longs and for shorts separately (if the config trades both)
- positive in both halves of the holdout (2025-H2, 2026)
A PASS = forward-test candidate. Never live money on a backtest alone.
