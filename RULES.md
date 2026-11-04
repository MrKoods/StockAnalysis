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

## Amendment 2026-11-04 - stocks that stopped trading (approved by the user)
Why: the frozen 2026-10-06 list keeps stocks that were later bought out, and Yahoo keeps listing an "upcoming
report" for them. V4 bought ACA on 2026-10-28 (Arcosa, delisted 2026-10-23) and WBD, HLX, RAMP on 2026-11-03 -
trades nobody could have made, which could never be scored. This changes data hygiene, not the strategy: a
stock that cannot be bought is not a trade.
- Signals: a candidate is dropped if it has no daily bar on the entry day or the 2 sessions before, or if it
  was bought out in the last 30 days (Form 25 within 3 days of an 8-K item 5.01, from the team's SEC archive).
  If the price download itself looks broken (SPY missing, or most candidates missing), nothing is dropped on price.
- Scoring: a trade is VOID (ledger column `void` says why) when its stock has no price on the entry day, or no
  price on the exit day after having one on entry - decided 2 sessions later, and only when SPY/IJH/IJR do have
  prices for that day. Void trades count as neither open nor closed and are excluded from every checkpoint.
- First voids: ACA (decided 2026-11-04), WBD, HLX, RAMP (on their 2026-11-05 evaluation). Before this rule no trade
  had been scored on a stock that had stopped trading (KVUE, delisted 2026-11-02, was a normal 10-28 -> 10-30 trade).
