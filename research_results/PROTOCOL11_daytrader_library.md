# Round 6: the day-trader strategy library — pre-registered 2026-10-07 19:15 PDT, BEFORE any run

Goal (user, 2026-10-07): test every setup an expert day trader would use, tens of thousands of
variants, and return only strategies good enough to paper trade.

Data: Dukascopy 1-minute bars (free, validated), regular hours, 2018-01 .. latest. No usable volume.

Instruments (fixed now):
- SEARCH:       SPY, QQQ, AAPL, MSFT, NVDA, AMZN   sessions 2018-01-01 .. 2022-12-31
- HOLDOUT:      the same six                         sessions 2023-01-01 .. latest  (evaluated once)
- CONFIRMATION: DIA, GOOGL, TSLA, AMD, NFLX, XOM, IWM, JPM, BAC, INTC, GLD, TLT, XLF, XLE
                (whichever Dukascopy serves), full period 2018-01 .. latest, evaluated once.
                None of these is used by any search.
Note: SPY/QQQ 2023+ was already used once in PROTOCOL10 for ORB/IMOM/NB/GAPM configs; the
confirmation set is therefore the primary arbiter.

Families (17), each = entry logic x exit grid; at most one trade per direction per session:
 ORB    opening-range breakout (5/15/30/60 min; close-break or stop-order touch)
 ORBF   failed opening-range breakout -> fade back through the range
 GAPGO  gap-and-go (gap 0.25-1.5 ATR; enter at open or after 5/15/30 min, optional confirmation)
 GAPFILL gap fade toward the previous close / half gap (G2 family)
 PULL   opening-drive first pullback continuation
 DRIVEF opening-drive fade
 HOD    high/low-of-day breakout after 10:30 / 11:30 / 13:00
 PDB    previous-day high/low breakout continuation (the opposite of the sweep)
 RETEST break-and-retest of the previous-day high/low
 MEAN   stretch from the session average price (TWAP proxy for VWAP) -> fade
 OSC    5-minute RSI(2)/RSI(14)/Bollinger extremes -> fade
 MAX    5-minute EMA crossovers (9/21, 5/20, 20/50)
 RS     intraday relative strength vs SPY (momentum or reversion), non-SPY instruments
 PWR    power hour: open->14:30/15:00 move continues or reverses into the close
 LUNCH  morning move fades over lunch
 NR15   15-minute narrow-range bar breakout
 SWEEP  the user's sweep idea, tweaked: levels PDH/PDL, previous close, opening-range H/L,
        morning HOD/LOD; reclaim 1/5/15 min; with/without confirmation; several stops/targets
Common filters (known before entry): none, long only, short only, with/against the 20-day trend,
with/against the gap, wide/narrow first-30-minute range, open inside/outside yesterday's range.

Costs: ETFs 1 bp/side, stocks 2 bps/side. Metric: net bps per trade, excess over the instrument's
own drift for the holding time. t-stat on per-session summed bps.

Stage 1 search: every config on SEARCH; per family report median, best t, t-standardized
best-of-N luck p and CSCV PBO.
Stage 2 shortlist: per family the top 3 by search t with n >= 300 and distinct core parameters,
identical-trade duplicates skipped (max 51).
Stage 3 holdout: PASS = mean > 0, t >= 3.1 (Bonferroni for 51), positive in 2023-24 and 2025-26,
positive in at least 4 of the 6 instruments, positive for each side traded.
Stage 4 confirmation: pooled CONFIRMATION set: mean > 0, t >= 2.0, positive in >= 60% of
instruments, and still positive at DOUBLE costs.

"Good enough to paper trade" = passes Stages 3 and 4. Those are reported with exact rules,
instruments, expected bps/trade and trades/month, ranked by confirmation t; at most one per family.
If none pass, that is the answer.

Bug fix + rerun (2026-10-07 ~20:00): the first run's "wide/narrow first-30-minute range" filters
used minutes 09:30-09:59 even for trades entered before 10:00 (look-ahead: ORB search t 11.5,
holdout t 11.8 - impossible). Fixed (the feature is undefined for entries before 10:00), and a
regression test now perturbs each trade's post-entry data and requires every filter feature to be
unchanged (proven to fail on the buggy code: 9 families). Stages 1-3 rerun with identical rules;
the first run's numbers are kept as library_search_BUGGY.log and were not used for any choice.
