# EPRE paper test - rules fixed 2026-10-23, BEFORE the first paper trade

Strategy: the earnings announcement premium, exactly as tested in V3 PROTOCOL12 (config EPRE (1, "through",
"none")): buy at the close two sessions before the reaction session, sell at the reaction session's close.
Reaction session = the first session whose open can reflect the report (before 09:30 ET -> that day,
otherwise the next session). Long only. No stop. No filters. Universe = the 1,490 S&P 500/400/600 stocks used
in the research (data/universe, frozen 2026-10-06 lists, ETFs excluded).

Research evidence (2018-01 .. 2026-10 holdout, evaluated once): 48,526 trades, +18.8 bps/trade after costs,
hedged, t 4.0; positive in 2018-21 and 2022-26 and in each index. Caveats: profit comes from the overnight report
gap only, lives in the less-liquid half, per-trade sd ~8%, three negative years, survivorship (current
constituents) not ruled out.

## Scoring (every qualifying trade, not just the ones posted to Discord)
- Entry/exit = official daily closes (Yahoo, split/dividend adjusted, fetched together at scoring time).
- Costs per side: S&P 500 3 bps, S&P 400 5 bps, S&P 600 8 bps (as in the research).
- hedged_bps = (stock return - mean of SPY/IJH/IJR return over the same closes) x 1e4 - costs.
- t-stat: clustered by exit day (mean per exit day, then t of those means).
- date_ok = after the fact, the report really did make exit_day its reaction session (implementation check).

## Decision rule (do not change after the first trade)
- Checkpoint A, >= 1,000 closed trades: FAIL and stop if mean hedged < -20 bps. Otherwise continue.
- Checkpoint B, >= 3,000 closed trades: FAIL if mean < 0. SMALL REAL MONEY OK if mean >= +10 bps AND day-t >= 1.0
  AND report-date accuracy >= 90%. Otherwise continue.
- Checkpoint C, >= 6,000 closed trades: PASS if mean >= +10 bps and day-t >= 2.0; otherwise FAIL.

Why these numbers: with sd ~8% per trade the research edge (+19 bps) only reaches t ~2 after roughly
6,000 live trades (~1-1.5 years at ~5,500 trades/year). Checkpoint A stops early only on clearly bad results
(~6% chance of wrongly stopping a real +19 bps edge). Checkpoint B allows small money when the estimate is
consistent with the research and execution is sound, without claiming proof.

## Real-money sizing if B or C allows it (guidance, decided by the user)
20+ equal positions, no single position > 5% of the account (one report gap can be -30% or worse).
