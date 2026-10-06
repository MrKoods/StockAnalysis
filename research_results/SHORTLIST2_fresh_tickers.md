# Fresh-ticker test — pre-registered 2026-10-06 13:30 PDT, BEFORE downloading any of the 463 new tickers

Data: 463 S&P 500 constituents never used in any search (daytrade/sp500_new.csv), same
yfinance windows (1m: 2026-09-08..10-05 + whatever is newly available; 5m: 60 sessions).

Candidates (42):
- C0 locked user rules (1m), C6 (5m close-out, fixed 2R)
- top 20 by search t from the 1m mass scan, top 20 from the 5m mass scan
  (research_results/fresh_ticker_candidates.csv; det_i/exit_i index the mass_*_grid.pkl grids)

Scored with engine.run (per-stock daily limits applied), 1 tick slippage per side.

PASS (per candidate), all of:
1. mean net R >= +0.05 per trade, n >= 300
2. day-clustered t >= 3.0 (Bonferroni for 42 candidates, ~p < 0.05/42 one-sided)
3. mean net R > 0 for longs AND for shorts separately (guards against "market went down")
A PASS here = worth a forward test, not live money.
