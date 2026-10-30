# Agent notes (the review agent's memory between runs)

Created 2026-10-14. Keep under ~300 lines; summarize and prune.

## Watch list
- **V2 rank mean R after costs: -0.006** (65/100 closed). GO mathematically unreachable. ABBV options-era +2.422R time-stop (Oct 29) moved mean from -0.058. Frozen at n=100.
- **C6 forward: RETIRED 2026-10-23.** No longer updated or reported.
- **ON1 paper: day-t +1.91** (13 days, mean +53.5 bps). Oct 29 was -81.0 bps — first dip below 2.0 since Oct 23 streak began (was above 2.0 for 5 consecutive reviews). Eval at day 20 = trade day Mon Nov 9, scored at Tue Nov 10 06:45 evaluate. G2 day 20 = Thu Nov 5.
- **V3 G2 paper: day-t -1.36** (16 days, mean -19.6 bps). Worsening but noise. Eval window opens day 20 = Nov 5.
- **Random control: 24 closed** (mean -0.356R after costs). Loss cluster exit Oct 23 already flagged (first seen 2026-10-26 daily).
- **V4 EPRE: 3 exit days** — 388 closed. Hedged mean -6.9 bps (exit-day t -0.39, pure noise). 127 open. Checkpoint A (~1,000 trades) arriving ~Nov 4–7.
- **EPRE calendar refreshed Oct 29** ✓. Today's 17:15 refresh (Oct 30) scheduled after review.
- **Team_Dispatch Oct 29 result 0** — resolved (watch item cleared).
- **Stale V3 universe symbols:** CWEN-A, HLX, LEG returning Yahoo 404s (likely delisted). Low impact; flag for future maintenance pass.

## Open questions (candidates for weekly research)
- V2 rank: bank shorts drove the profit but picked banks did no better than other banks — skill or sector beta?
- V2: which score components (if any) predict R? Earlier IC work found no robust edge.
- V3 G2: does entry slippage cost matter more in less-liquid names specifically? (deferred until n > 100)
- ON1 paper: does day-t hold above 2.0 as evaluation window approaches? (watch daily)

## Research done

### 2026-10-24 weekly — ON1 paper consistency (agent/research/2026-10-24-weekly/on1_paper_analysis.py)
**Q:** Is day-t +2.19 driven by a single outlier?
**Method:** Day-by-day breakdown, drop-one t-stat for each of 8 days.
**Results:** 6/8 days positive. Mean +85.3 bps, std 109.9. Dropping Oct 16 (largest, +311.6 bps) → t=2.13. Three drop-ones fall below t=2 (Oct 14, Oct 21, Oct 22). Day-level win rate 75%.
**Verdict:** Not a single-outlier artifact; fragile at n=8 as expected. Watch for consistency over next 12 days.

### 2026-10-24 weekly — V2 rank time-stop vs loss predictors (agent/research/2026-10-24-weekly/rank_timestop_analysis2.py)
**Q:** Which signal features distinguish time-stop exits from losses?
**Method:** Mann-Whitney U tests on 6 features (VIX, RSI, rs_zscore, mom_5d, technical_score, confidence) for time_stop (n=26) vs loss (n=27). Direction analysis.
**Results:** Only mom_5d reached p=0.04 (time-stops have slightly negative momentum vs losses' slightly positive). With 6 features tested, this is expected by chance. No other feature p<0.10. Bearish time-stop rate 54.5% vs bullish 40%, p=0.31. All 56 closed are options-era.
**Verdict:** No robust predictor found. Outcome appears to be random short-term price movement. Context: time-stops exit at mean 11.5 days (hitting the 15-day limit); losses exit at mean 4.3 days (stopping out quickly).

### 2026-10-24 weekly — V2 rank go/no-go trajectory (agent/research/2026-10-24-weekly/rank_gonogo_trajectory.py)
**Q:** Is GO (+0.15R at n=100) mathematically reachable?
**Method:** Simple arithmetic from current total R and required future per-trade mean.
**Results:** Required mean for remaining 43 trades: +0.412R/trade. At current mix projected final mean ≈ -0.047R. Even 100% time-stop future → only +0.277R (requires implausible run).
**Verdict:** GO unreachable at current trajectory. Not a change — experiment runs to n=100.

### 2026-10-24 weekly — V4 EPRE calendar readiness (agent/research/2026-10-24-weekly/epre_preview2.py)
**Q:** How many signals on first EPRE run? When does checkpoint A arrive?
**Results:** Monday Oct 26: 117 signals (reaction Oct 28). Week 1: ~514 trades. Week 2: ~474. Checkpoint A (~1,000) may arrive ~Nov 7.
**Note:** RULES.md "1-1.5 years" is annual-average-based; peak earnings season is ~5× denser.

### 2026-10-17 weekly — C6 forward trajectory (agent/research/2026-10-17-c6-trajectory/)
**Q:** How close to t = −2.0 is C6 and at what pace?
**Method:** Day-level mean r_net, cumulative t-stat, projection at current mean/std.
**Results:** Day-level mean −0.265R, std 0.471R. Sessions 2–4 and 7–9 all negative; day 1 (+0.629R) only positive outlier. Projection: t = −2.0 at session 13 (4 more bad sessions).
**Verdict:** Primary watch item for next week. No action (not at threshold yet; no early trigger in frozen rules).

### 2026-10-17 weekly — V2 rank time-stop attribution (agent/research/2026-10-17-rank-timestop/)
**Q:** Is the rank track's near-zero mean R driven by time-stop exits?
**Method:** Group closed 53 rank trades by outcome. Decompose total R contribution.
**Results:** Time-stop exits (n=25): mean +0.818R. Loss exits (n=25): mean −1.105R. Total R = +0.54R, of which +20.45R from time stops and −19.91R from everything else. Without time stops: −0.711R/trade. Formal 3R target hit twice.
**Verdict:** CONFIRMED. The model's near-zero mean is entirely the 15-day time stop acting as a soft exit. No formal edge in target hitting. Relevant context for go/no-go at n=100.

### 2026-10-17 weekly — G2 paper open-auction slippage (earlier session; NOTES already had this)
**Verdict:** Inconclusive at n=57. Mean 2-min delay cost −5.9 bps/day. No action.

## Log

### 2026-10-30 daily review
- All tasks result 0. Team_Dispatch Oct 29 result 0 — watch item resolved.
- V2 rank: 3 new closures (exit Oct 29): ABBV time_stop +2.422R (options-era Oct 8), AVGO time_stop -0.220R (shares), MCD earnings_exit +1.234R (shares). TGT expired NaN (not counted). Mean after costs: -0.058 → -0.006 (65/100). Move driven by ABBV's single options-era result. Week-t -0.25. GO unreachable. 8 new signals today (all shares).
- V2 random: 2 new closures (22→24); mean after costs -0.447 → -0.356R. 8 new signals.
- V3 ON1 paper day 13 (Oct 29 scored: -81.035 bps): mean +53.491 bps, day-t +1.91 (down from 2.06). First dip below 2.0 in 5 reviews.
- V3 G2 paper day 16 (Oct 30: -64.956 bps): mean -19.563 bps, day-t -1.36 (from -1.11). Noise.
- G2 forward day 18: t +0.65 (noise). ON1 forward day 17: t +0.70 (noise).
- V4 EPRE 3rd exit day: ~100 new closures → 388 closed. Hedged mean -6.9 bps (was -14.9), exit-day t -0.39 (3 days). 111 new signals today (515 total, 127 open). Calendar refreshed Oct 29; Oct 30 17:15 refresh runs after this review.
- No bugs. No fixes proposed.
- Note: snapshot.py passes absolute V2 paths to rank_verdict.compute_verdict() correctly. Earlier check_rank_delta.py script accidentally read stale agent-workspace ledger (RANK_TRADES_CSV is a relative Path). Numbers from snapshot.py are authoritative.

### 2026-10-29 daily review
- All tasks result 0. Team_Dispatch scheduled first run 14:50 PT (267011 = never run, not a failure). EPRE log files 0 lines (expected by design). EPRE calendar confirmed refreshed Oct 28 17:15.
- V4 EPRE day 2 exits: 173 new closures (Oct 29 exit day, hedged mean +11.6 bps vs Oct 28's -54.8 bps). Combined 288 closed, hedged mean -14.9 bps (exit-day t -0.65). Report-date accuracy 97.6% (7/288 mismatches — still well above 90% checkpoint B floor). 116 open; 14 new signals. 404 total.
- V2 rank: 3 new closures (59→62): MU time_stop -0.756R, PFE earnings_exit -0.600R, ZION loss -1.000R (all shares, all Oct 28 exits). Mean after costs -0.019 → -0.058. Week-t -0.64 (track), -0.92 (go/no-go). GO still unreachable.
- V2 random: 5 new closures (17→22); mean after costs -0.491 → -0.447. Week-t -1.77 (noise). Loss cluster Oct 23 not re-flagged (already reported Oct 26).
- V3 ON1 paper day 12 (Oct 28 scored: -95.526 bps): mean +61.021 bps, day-t +2.06 (down from 2.64). Fifth consecutive day above t=2.0.
- V3 G2 paper day 15 (Oct 29: -7.680 bps): mean -16.706 bps, day-t -1.11. Noise.
- G2 forward day 17: t +0.50 (noise). ON1 forward day 16: t +0.80 (noise).
- No bugs. No fixes proposed.

### 2026-10-28 daily review
- All tasks result 0. No error lines. EPRE log files (signals/evaluate) show 0 lines today — confirmed by design: the evaluate code only calls log.info() on "nothing to score yet" / "prices not available"; when it scores trades it posts to Discord + writes ledger silently. Signals only logs dropped-ticker events.
- V4 EPRE first closures: 115 trades (Oct 26 signal batch) scored. Hedged mean -54.8 bps, per-trade std ~760 bps, 1 exit day (t=nan). Pure noise; backtest expected ~+19 bps. 102 new signals logged (Oct 28 batch). 390 total, 275 open. Report-date accuracy 100%.
- V2 rank: no new closures (59/100); mean -0.019R after costs unchanged. Week-t shifted -0.20 → +0.07 (week-boundary re-clustering, no new trades). New signals: 8 rank, 2 threshold (all shares).
- V2 random: 3 new closures (14→17 closed); mean after costs worsened -0.358 → -0.491R.
- V3 ON1 paper day 11 (Oct 27 scored: +67.607 bps): mean +75.061 bps, day-t +2.64 (up from 2.42). Fourth consecutive day above t=2.0.
- V3 G2 paper day 14 (Oct 28: +28.500 bps): mean -17.385 bps, day-t -1.07 (improved from -1.22). Still noise.
- G2 forward day 16: t +0.25 (noise). ON1 forward day 15: t +0.84 (noise). ON1 forward still 2 days behind (Dukascopy disabled).
- No bugs. No fixes proposed.

### 2026-10-27 daily review
- All tasks result 0. No error lines. EPRE calendar confirmed refreshed Oct 26 (resolves yesterday's watch item). Today's 17:15 EPRE calendar refresh runs after this review.
- V4 EPRE day 2: 173 new signals (288 total open). 3 tickers dropped for shifted report dates (LXP Oct 27, GHC+CHCO Oct 26) — normal. EPRE evaluate: "nothing to score yet" — correct.
- V2 rank: no new closures (59/100); mean -0.019R after costs, week-t -0.20. GO still unreachable. 8 new rank signals, 4 threshold, 6 random (all shares bullish).
- V2 random: 2 new closures (12→14 closed); mean -0.358R after costs. Loss cluster (Oct 23) not re-reported (already flagged Oct 26).
- V3 ON1 paper day 10 (Oct 26: +23.727 bps): mean +75.806 bps, day-t +2.42 (up from 2.37). Holding above 2.0 for third consecutive review despite below-mean day.
- V3 G2 paper day 13 (Oct 27: -77.310 bps): mean -21.115 bps, day-t -1.22 (from -0.91). Worsening but still noise.
- G2 forward day 15 (last bar Oct 26): t +0.45 (noise). ON1 forward day 14 (last bar Oct 23): t +0.53 (noise). ON1 forward 2 trading days behind — expected, Dukascopy disabled.
- No bugs. No fixes proposed.

### 2026-10-26 daily review
- All tasks result 0. No error lines. V4 EPRE first signals ran at 12:38 PT (15:38 ET, within MOC window) — 115 signals logged, all open. EPRE evaluate ran at 13:45 (nothing to score; reactions Oct 28+). EPRE calendar last refreshed Oct 23; 17:15 refresh runs after review.
- Random track: 7 new closures processed today (from weekend). Loss cluster exit 2026-10-23: 6 bullish losses (ABBV, ONB, TMO, BMY, CFR, UMBF; -3.18R) — first time seen; one correlated move. Random 12 closed, mean -0.351R after costs; mean excl. Oct 23: -0.390R (n=5).
- V2 rank: 2 new closures (57→59); mean improved -0.048 → -0.019R after costs, week-t -0.20. GO still unreachable.
- V3 ON1 paper day 9: mean +81.6 bps, day-t +2.37 (up from 2.19). Oct 23 was +52.2 bps (positive but below mean). Holding above 2.0. G2 paper day 12: -100.3 bps today, mean -16.1 bps, day-t -0.91 (noise).
- G2 forward day 14: t +0.63 (noise). ON1 forward day 13: t +0.47 (noise).
- No bugs. No fixes proposed.

### 2026-10-24 weekly research
- All tasks result 0; V4 EPRE tasks (signals, evaluate) never run — expected, first run Monday.
- V2 rank 57/100, mean -0.048R after costs, week-t -0.45. Trajectory: GO unreachable (+0.412R/trade needed for remaining 43). Random control 5 closed, mean -0.448R (noise).
- C6 forward session 14/30: day-t -2.16, deepening. Frozen at session 30.
- ON1 paper 8 days: day-t +2.19, mean +85.3 bps, 6/8 positive. Not outlier-driven (drop-one Oct 16 → t=2.13). Evaluation window day 20.
- G2 paper 11 days: day-t -0.49, noise. G2 forward 13 days: day-t +0.73, noise. ON1 forward 12 days: day-t +0.53, noise.
- V4 EPRE: 117 signals expected Monday; checkpoint A may arrive ~Nov 7.
- Research: ON1 paper consistency (not outlier-driven, fragile); rank time-stop predictors (none found); rank go/no-go trajectory (unreachable); EPRE calendar preview.
- No proposals. No bugs.

### 2026-10-23 daily review
- All tasks result 0. Dukascopy last ran Oct 22 (today's run at 18:00 not yet due). 2 transient Yahoo news errors for KEY — non-impacting, recurring pattern.
- V2 rank: no new closures (57/100); mean -0.048R after costs; week-t -0.45. 20 new shares signals (5 threshold, 7 rank, 8 random).
- Random: 3 new closures (5 total, mean -0.448R after costs, noise).
- C6 forward session 14: -0.140R; day-t -2.16 (deepened from -2.06). Mean improved -0.270 → -0.260R.
- G2 forward session 13: mean +0.034 ATR, t +0.73. ON1 forward session 12: mean +17.889 bps, t +0.53. Both noise.
- G2 paper day 11: -64.922 bps; mean -8.863 bps, day-t -0.49. Noise.
- ON1 paper day 8: mean +85.266 bps, day-t **+2.19** (t crossed +2.0). Last day Oct 22: +80.750 bps. 12+ days from evaluation window.
- No bugs. No fixes proposed.

### 2026-10-22 daily review (second run, 21:46)
- All V2/V3 tasks result 0. IntradayFetch: earlier DLL block resolved by aff8929; re-ran 21:44, session 13 now available. Dukascopy result 0 (ran 18:00–18:55, 20 tickers). 1 SA pre-market empty-body (recurring transient).
- CWEN-A, HLX, LEG returning Yahoo 404s during yfinance fetch (likely delisted). Low impact; logged for future cleanup.
- V2 rank: ISRG closure already processed; no new closures today. 57/100; mean after costs -0.048; week-t -0.23. 4 threshold, 6 rank, 8 random signals (all shares).
- C6 forward session 13: +0.247R; day-t -2.06 (improved from -2.37). mean -0.270R.
- G2 forward session 13: mean +0.034 ATR, t +0.73 (noise).
- ON1 forward session 12: mean +17.943 bps, t +0.54 (noise). Last day Oct 21: -165.870 bps.
- G2 paper day 10: +15.814 bps (mean -3.553 bps, t -0.16, noise).
- ON1 paper day 7: mean +85.911 bps, day-t 1.91. Last day Oct 21: +140.984 bps.
- Random control: 2 closed, mean -1.260R after costs (noise).
- No bugs. No fixes proposed.

### 2026-10-21 daily review
- All tasks result 0 (DailyReview 267009 = currently running, expected).
- Zero error lines in all V2 and V3 logs today.
- V2 rank: 2 new closures — PNFP bearish time_stop -0.551R (options-era), TJX bullish win +2.596R (options-era, 3rd rank win). Rank now 56/100; mean after costs -0.030 (improved from -0.067); week-t -0.44.
- 15 new signals today (all shares): 1 threshold (KEY), 7 rank (ADI/KEY/FITB/UNH/PFE/TJX/AMZN bullish), 7 random.
- C6 forward session 12: -0.433R; day-t -2.37 (deepened from -2.07 at session 11). No early-stop rule; frozen decision at session 30.
- G2 paper day 9: -42.190 bps (day-t -0.25, noise). G2 forward day 11: day-t +0.20, noise.
- ON1 paper day 6 (Oct 20 scored): -18.466 bps; 6-day mean +76.774 bps, day-t 1.47.
- ON1 forward day 10: day-t +0.82, noise.
- Random control: 10 open, 0 closed — no read yet.
- Loss cluster (Oct 15, 6 bearish losses) already flagged Oct 16 — not re-reported.
- No bugs. No fixes proposed.

### 2026-10-20 daily review
- All tasks result 0 (DukascopyDownload not yet due at 14:45). Pre-market 1 transient SA empty-body error — same recurring pattern, scan completed fine.
- No new V2 closures — rank still 54/100.
- 15 new signals today (all shares): 1 threshold (UNH, superseding Oct 19 UNH), 6 rank (AMAT bearish, MTB bearish, UNH/PFE/HD/AMZN bullish), 8 random.
- C6 forward session 11: -0.214R; day-t -2.07. t crossed -2.0 exactly as projected on Oct 19. No early-stop rule; frozen decision at session 30.
- G2 paper day 8: -0.090 bps (noise). G2 forward last bar Oct 19 (+0.088 ATR, 10-day mean +0.012).
- ON1 paper last scored Oct 19 (+42.377 bps); 5-day mean +95.565 bps, t 1.61. New Oct 20 signals logged (not yet scored).
- ON1 forward last bar Oct 16 (4 days behind — Dukascopy lag).
- No bugs. No fixes proposed.

### 2026-10-19 daily review
- All 13 tasks result 0. No errors in V2 or V3 logs.
- No new V2 closures Oct 17-19. UMBF (Oct 16 exit, -1.0R loss) processed Oct 17 — bumped rank to 54 closed; NOTES watch list was stale at 53.
- 15 new signals today (all shares): 1 threshold (UNH), 6 rank, 8 random.
- C6 forward session 10: -0.293R; day-t -1.91 (was -1.69 at session 9). Projection to t=-2.0 updated to session 11 (one more bad session), earlier than the Oct 17 estimate of session 13.
- G2 paper day 7: +3.930 bps (noise). ON1 paper: no new scored day (last was Oct 16 at +311 bps).
- G2 forward last bar Oct 16 (1 trading day behind); ON1 forward last bar Oct 15. C6 shows Oct 19 (daily re-run label — actual bar data is through Oct 17 Friday).
- No bugs. No fixes proposed.

### 2026-10-17 weekly research (second pass — snapshot.py available)
- snapshot.py ran successfully. All numbers authoritative.
- Research 1: C6 forward trajectory. Day-level mean −0.265R, std 0.471R. Projected t = −2.0 at session 13 (4 more bad sessions next week). Watch Mon–Thu.
- Research 2: V2 rank time-stop attribution. Time-stop exits (n=25) provide 100% of positive R (+20.45R). Without them, track averages −0.711R/trade. 3R target hit only twice. Context for go/no-go at n=100.
- All 7 tracks collecting within frozen rules. No proposals.
- WeeklyDashboard missed Oct 11 (machine asleep); next run Oct 18 18:00.

### 2026-10-17 weekly research (first pass — snapshot blocked)
- snapshot.py blocked. Used Oct 16 daily report numbers. Research: G2 open-auction slippage (−5.9 bps, inconclusive).

### 2026-10-13 daily review
- All tasks OK (result 0). First agent run.
- Pre-market: 1 transient SA /symbols/get-factor-grades empty-body error; scan completed fine.
- V2 rank: 7 new options signals (last options-regime scan). shares_only takes effect 2026-10-14.
  Snapshot "!! not shares" warning is a known false positive on transition day.
- V3 G2 paper: +102.7 bps today; 3 sessions, mean +33.4 bps, t 0.63 (too early).
- V3 ON1 paper: 74 signals logged, bps column unfilled; first evaluate 2026-10-14 06:45.
- No bugs found. No fixes proposed.

### 2026-10-16 daily review
- All 12 tasks OK (result 0). WeeklyResearch result 267011 = never run (first run tomorrow Sat Oct 17).
- 6 options-era trades processed as losses by today's 8:07 AM EOD updater (closed Oct 15):
  BKNG, VRTX, SBUX, TFC bearish options (-1.000R each); FITB, ZION bearish hit stop-loss same day.
  This is why yesterday's snapshot showed 47 closed but today shows 53.
- V2 rank mean R after costs: +0.083 → -0.048 (53 closed). Raw mean +0.010. Week-t -0.61.
- 16 new signals today across 3 tracks (6 rank, 2 threshold, 8 random) — all shares.
- Random track: 2 open fills (ORLY -0.121R, QCOM -0.863R); 0 closed.
- C6 forward: 9 days, mean -0.314R, day-t -1.69. Recent: -0.087, -0.785, -0.379.
- G2 paper day 6: +44.022 bps. 6-day mean -1.116 bps, day-t -0.04. Noise.
- ON1 paper 3 scored days: mean +41.050 bps, day-t 0.91. Noise.
- G2 forward: 8 days, mean -0.018 ATR, day-t -0.23. ON1 forward: 7 days, mean -14.047 bps, day-t -0.54.
- Minute research: GAPM/LSR_1m/C6_5m all failed stage3. Stage4 empty.
- No bugs. No fixes proposed.

### 2026-10-15 daily review
- All 14 tasks OK (result 0). Zero error lines in all V2 and V3 logs.
- 19 new signals across 3 tracks (threshold 4, rank 7, random 8) — all shares. No non-shares violations.
- No V2 trades closed today. Three rank closures on 2026-10-14: TXN time_stop −0.235R, CFR time_stop −0.008R,
  GILD loss −1.442R. All options-era. Rank mean R after costs dropped to +0.083 from +0.132.
- V2 rank go/no-go: 47/100, mean +0.083 after costs, t −0.67 (8 wks). Still COLLECTING.
- 6 rank + 1 threshold rows have achieved_rr beyond −1.2R (range −1.28 to −1.75, all 'loss'); pre-existing
  gap-throughs, not data bugs. No duplicate rows in any ledger.
- V3 G2 paper day 5: −52.1 bps (SARO −365, EEFT −184, OZK −163). 5-day mean −9.4 bps, t −0.28. Noise.
- V3 ON1 paper: Oct 14 scored (+120.7 bps, 73 trades). Oct 15 signals logged (not scored yet).
- V3 forward: C6 8d −0.302R t −1.42, G2 7d +0.006 ATR t 0.03, ON1 6d −10.3 bps t −0.34. All noise.
- Confirmed: rank_verdict.py cost model uses stop-distance-adjusted R (not flat −0.02) which explains
  gap between raw mean (+0.139) and after-costs mean (+0.083).
- No bugs found. No fixes proposed.

### 2026-10-14 daily review
- All tasks OK (result 0). Zero error lines in all V2 task logs.
- Shares transition confirmed: all 6 new rank signals + 2 threshold signals are position_type=shares.
  Random control first run: 7 signals all shares; QCOM blocked by event gate (export restriction).
- ON1 paper first evaluate at 06:45: bps filled for 74 Oct-13 signals, mean −34.1 bps. Pipeline OK.
- G2 paper day 4: −90.78 bps (NTAP −347, ON −397, TOST −407 bps; gap-fades that continued). 4-day
  mean +1.5 bps, t ≈ 0 — noise.
- Forward data lags: C6 through Oct 14 (yfinance 5m), G2 through Oct 13 (hourly archive drops
  today's bars), ON1 through Oct 12 (Dukascopy downloaded through prior day). All expected.
- WeeklyDashboard result 2147946720 on Oct 11 (Sat) — machine asleep; pre-existing, not a bug.
- V2 rank go/no-go: 44/100 closed, mean R after costs +0.132 (need ≥+0.15), t −0.63. Collecting.
- No bugs found. No fixes proposed.
