# Round 5: MINUTE-level families on free Dukascopy data — pre-registered 2026-10-07, BEFORE any data arrived

Data: Dukascopy BID 1-minute candles (no account), regular hours only, 2018-01 onward.
Validated against Yahoo hourly bars for SPY: median |diff| 0.25 bps, hourly-return corr 0.9999.
Dukascopy volume is CFD volume, not exchange volume -> no volume- or VWAP-based rules.

Split (fixed now):
- Search:       SPY + QQQ, sessions 2018-01-01 .. 2022-12-31
- Holdout:      SPY + QQQ, sessions 2023-01-01 .. latest, evaluated once
- Confirmation: DIA + every single stock downloaded (AAPL MSFT NVDA AMZN GOOGL TSLA AMD NFLX XOM
                and any of IWM JPM BAC INTC that Dukascopy serves), 2018-01-01 .. latest, evaluated once

Families
- IMOM  intraday momentum (Gao-Han-Li-Zhou): return over an early window (prev close -> 10:00, or
        open -> 10:00) predicts a late window (15:30 -> 16:00, or 15:00 -> 16:00); trade the late
        window in the early window's direction (or against); optional |early| threshold, optional
        "same sign as the 12:00-15:30 return" confirmation
- ORB   opening-range breakout: range of the first 5 / 15 / 30 minutes; enter on the first 1-minute
        close beyond it (or in the direction of the first candle at range end); stop = other side,
        middle, or 0.1 / 0.25 daily ATR; target 1R / 2R / 5R / none; flat at 15:59
- NB    noise-boundary momentum (Zarattini et al. style): bands = open x (1 +- k x average absolute
        move from the open at the same minute over the prior 14 sessions), k in {0.5, 1, 1.5};
        checks every 15 / 30 / 60 minutes; long above the upper band, short below the lower;
        exit when back inside the band, or at the close
- GAPM  the G2 gap fade at minute resolution: gap >= 0.25 / 0.5 / 1.0 daily ATR, fade at the
        09:30 open (or at 09:35 / 10:00), target previous close, stop none / 0.5 / 1 ATR, exit at
        11:00 / 13:30 / 16:00; with or without the 20-day trend filter
- LSR   the user's Liquidity Sweep Reversal, locked 1-minute rules (v3.2.0 + the 2026-10-05 rule
        choices), and the C6 5-minute variant, re-run over eight years

Metric: net bps per trade after costs (ETFs 1 bp/side, stocks 2 bps/side), measured as EXCESS over
the instrument's own unconditional mean return for the identical clock window in the evaluated
period (removes drift; for stocks also report excess over SPY in the same window). t-stat by
session (no overlap within a session's single trade per config; multiple trades/session summed).

Stage 1: all configs on the search set; luck test + CSCV PBO reported.
Stage 2: per family, top 2 by search t with n >= 300 trades (distinct core params; identical-trade
duplicates skipped). LSR's two locked variants are added regardless (no search).
Stage 3 holdout: PASS = mean > 0, t >= 2.8 (Bonferroni for <= 12), positive in 2023-2024 and in
2025-2026, positive in SPY and in QQQ separately.
Stage 4 confirmation: pooled over DIA + stocks: mean > 0, t >= 2.0, and positive in at least 60% of
the individual instruments.
Selection: up to 3 by confirmation t, at most one per family.
