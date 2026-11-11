# Graveyard - ideas that are dead and why (the Scout checks here before proposing anything)

Pre-team (V3 research, 2026-10-06 .. 10-23; details in StockAnalysis-V3/research_results/RESEARCH_LOG.md):
- **Liquidity sweep reversal** (all forms, 1m/5m/hourly, ~331k variants, user's LSR on SPY/QQQ 8y): no edge; best = luck.
- **C6** (5m sweep, 2R): forward test retired 2026-10-23.
- **Intraday momentum** (first-30 -> last-30): luck. **ORB** (opening range breakout): negative.
- **Daily classics** 2000-2026 (short-term reversal, IBS/RSI2, breakout fade, daily gap fade, overnight reversal): fail hedged holdout.
- **10k random multi-signal blends + ridge models**: typical -4 bps (= costs); 18 shortlisted all fail holdout.
- **Minute library** (17 families, 26.5k configs): no passers on unseen symbols; failed-breakout shorts (ORBF) only theme.
- **Earnings-gap continuation, PEAD/surprise drift (ESUR), analyst rating actions, VIX timing, residual reversal, stocks-in-play ORB**: fail 2018-26 holdout.
- **Hold-the-loser** (EPRE exit variant): win rate up, same expectancy, fatter losses.
Lessons: two look-ahead bugs caught in minute research (bar ordering; filter using post-entry data -> fake t 11.5).
Price/volume patterns on free hourly/daily data are largely exhausted; edges found live in events + small caps.
- **insider-cluster-buys** (2026-10-27): holdout FAIL: t 1.11 vs bar 3.00, 28.76 bps
- **split-announcement-drift** (2026-10-31): holdout FAIL: t 0.99 vs bar 3.00, 78.4 bps
- **reg-fd-small-cap-disclosure** (2026-11-04): Skeptic FAIL: Pre-registered sp600_h1 LONG is train t -2.77 / mean -17.9 bps; small-cap tilt runs opposite to the thesis.
- **analyst-initiation-buy** (2026-11-04): Skeptic FAIL: Pre-registered sp600_h3 LONG is train t -1.28 / mean -19.85 bps; small caps worst not best; also flagged not promotable.
- **restructuring-bounce** (2026-11-05): Skeptic FAIL: Pre-registered chosen sp600_h3 is NEGATIVE on train (t -0.85, mean -24.43 bps); thesis inverted, no variant clears luck 1.67.
- **early-10q-drift** (2026-11-05): Skeptic FAIL: Chosen sp1500_t7_long t 0.99 - below the 2.0 floor and luck 1.89; best variant 1.45 also sub-luck; trade-level mean negative (-9.97). Honest null on a clean new family.
- **turn-of-month** (2026-11-06): train result below the minimum: chosen tom_h3 t 1.37, 21.96 bps after cost 10.0 bps round trip - no holdout spent, no review needed
- **nt-filing-short** (2026-11-06): train result below the minimum: chosen sp54_h3 t 0.04, 1.64 bps after cost 30.0 bps round trip - no holdout spent, no review needed
- **activist-13d-long** (2026-11-07): train result below the minimum: chosen sp1500_h3 t 0.17, 2.37 bps after cost 25.0 bps round trip - no holdout spent, no review needed
- **pipe-short** (2026-11-07): train result below the minimum: chosen sp1500_h3 t -1.57, -31.89 bps after cost 25.0 bps round trip - no holdout spent, no review needed
- **seo-short** (2026-11-09): train result below the minimum: chosen both_sp1500_h3 t -5.92, -36.64 bps after cost 25.0 bps round trip - no holdout spent, no review needed
- **pre-earnings-premium** (2026-11-11): train result below the minimum: chosen h1_sp500 t 0.44, 1.09 bps after cost 8.0 bps round trip - no holdout spent, no review needed
