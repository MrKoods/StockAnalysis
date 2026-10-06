# Overnight-reversal confirmation — pre-registered 2026-10-06, BEFORE running it

Deviation note: under PROTOCOL5 this config failed Stage 3 (holdout t 2.24 < 2.6), so it would
not advance. It is given a separate, independent test here because it is the only family with a
coherent positive region (PBO 0.01) and a positive holdout in both halves -- the same situation G2
was in before its midcap test. This is the ONLY extra test run from round 1.

Config ON1 (exact): each day, rank stocks by their last-hour return (close of the 13:30 bar ->
the 16:00 close); buy the bottom 5% at the close, sell at the next session's open. Long only.
Costs 2 bps per side (closing and opening auctions).

Data: S&P 400 midcaps and S&P 600 small caps, full ~2 years; ranks computed within each universe.
PASS: mean net > 0 with day-clustered t >= 2.0 in BOTH universes, and mean > 0 in both years
(sessions before / from 2025-07-01) in both universes.
