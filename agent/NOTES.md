# Agent notes (the review agent's memory between runs)

Created 2026-10-14. Keep under ~300 lines; summarize and prune.

## Watch list
- **V2 rank mean R after costs: -0.048** (57/100 closed). Oct 22: ISRG loss -1.000R (options-era), mean dropped from -0.030 → -0.048; week-t -0.23. Research confirmed: entire raw positive mean comes from time-stop exits. Recovery toward +0.15 needs consistently positive results over remaining 43 trades.
- **C6 forward: day-t -2.06** (13/30 sessions, mean -0.270R day-level). Session 13 (Oct 22): +0.247R — improved t from -2.37. Still firmly negative; no early-stop rule; frozen decision at session 30.
- **ON1 paper: day-t +1.91** at 7 days (Oct 21: +140.984 bps; 7-day mean +85.911 bps). Best V3 paper reading yet. 13+ days from 20-day evaluation window.
- **Random control: 11 open, 2 closed** (mean -1.260R after costs, n=2, noise).
- **IntradayFetch pyarrow DLL issue: RESOLVED 2026-10-22 (V3 commit aff8929). Pickle-fallback proposal REJECTED** — one blocked run would replace the archive's history with only the new download window, and load() would prefer that stale .pkl forever (data loss; 1m history beyond Yahoo's 30 days is irreplaceable). Real cause: Smart App Control blocks pyarrow DLLs *intermittently* (Code Integrity events 3077 on Oct 19, Oct 22 00:43 and 14:00); a fresh process loads fine minutes later. Fix: `data.wait_for_parquet()` retries the import in a fresh process 5x/60s before fetch, forward and Dukascopy, and exits non-zero without writing if still blocked. Today's fetch+forward were re-run by hand after the fix. Note the task is `fetch && forward` — when fetch fails, forward does NOT run. If it recurs: a "parquet unavailable (try n/5)" line in daytrade_fetch_task.log is the retry working; only a "still blocked after 5 tries" exit is a real failure.
- **Stale V3 universe symbols:** CWEN-A, HLX, LEG returning Yahoo 404s (likely delisted). Low impact on forward tests; flag for future maintenance pass.

## Open questions (candidates for weekly research)
- V2 rank: bank shorts drove the profit but picked banks did no better than other banks — skill or sector beta?
- V2: which score components (if any) predict R? Earlier IC work found no robust edge.
- V3 G2: does entry slippage cost matter more in less-liquid names specifically? (broader analysis deferred until n > 100)
- V2 rank: what distinguishes time-stop winners from losses? (direction/sector/vix/rsi — could inform future track design; cannot tune live experiment)

## Research done

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
