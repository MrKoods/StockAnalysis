# Agent notes (the review agent's memory between runs)

Created 2026-10-14. Keep under ~300 lines; summarize and prune.

## Watch list
- Monitor random control fills: confirm ≤ 2 per sector stays enforced as trades start filling.
- V2 rank mean R after costs dropped to +0.083 (was +0.132) — 3 bad closures Oct 14 (TXN, CFR, GILD).
  Need recovery toward +0.15 threshold over next ~50 trades.
- C6 forward trending negative: 8 days, mean −0.302R, t −1.42. Not significant yet (30-session bar).
  Watch closely — if it reaches −0.5R average it may be worth flagging as failing direction.
- ON1 forward: verify advances to Oct 14 in tomorrow's snapshot (after tonight's Dukascopy + IntradayFetch).

## Open questions (candidates for weekly research)
- V2 rank: is the profit from the 15-day time stop alone? (target hit 3/61, stops -27R, time stops +29R)
- V2 rank: bank shorts drove the profit but picked banks did no better than other banks — skill or sector beta?
- V2: which score components (if any) predict R? Earlier IC work found no robust edge.
- V3 G2: does the edge survive realistic open-auction costs in less-liquid names?

## Research done
(none yet)

## Log

### 2026-10-13 daily review
- All tasks OK (result 0). First agent run.
- Pre-market: 1 transient SA /symbols/get-factor-grades empty-body error; scan completed fine.
- V2 rank: 7 new options signals (last options-regime scan). shares_only takes effect 2026-10-14.
  Snapshot "!! not shares" warning is a known false positive on transition day.
- V3 G2 paper: +102.7 bps today; 3 sessions, mean +33.4 bps, t 0.63 (too early).
- V3 ON1 paper: 74 signals logged, bps column unfilled; first evaluate 2026-10-14 06:45.
- No bugs found. No fixes proposed.

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
