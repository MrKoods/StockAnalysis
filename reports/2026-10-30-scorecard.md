# Weekly Scorecard — 2026-10-30

Source: state/snapshot.txt (run 2026-10-30).

---

## V2 Rank Track — COLLECTING (65/100 closed trades)
- Progress: 65/100 closed (+6 this week from 59)
- Mean R after costs: -0.006 (need >= +0.15)
- Week-clustered t: -0.25 over 10 weeks (need >= 2)
- vs sector ETF: -0.15%/trade (need > 0)
- Random-pick control: 24 closed, mean R -0.356 — rank is beating random but both are negative
- **Read: Looking weak.** Mean is essentially flat at -0.006 but far from +0.15 target. t near zero, not trending toward 2. 35 trades to go. Very unlikely to PASS unless something sharp and consistent emerges.

## V2 Threshold Track — Tracking only (no formal checkpoint yet)
- 31 closed, mean R +0.328, week-t 0.27
- Read: Too early; too few closed trades and week-t noise.

---

## V3 G2 Paper — COLLECTING (16/20 days to first checkpoint)
- 16 days, 152 trades, mean -19.563 bps, day-t -1.36
- Last day (2026-10-30): -64.956 bps
- Checkpoint at day 20 = Thu 2026-11-05 (scored 10:45 PT). Rule: FAIL if mean < 0.
- **Read: Heading to FAIL.** Mean is -19.6 bps with 4 days left. Would need 4 strong positive days to turn mean positive. Likely FAIL at the 20-day checkpoint.

## V3 G2 Forward — Tracking only
- 18 days, 3517 trades, mean +0.023 ATR, day-t 0.65
- Read: Too early; noise.

---

## V3 ON1 Paper — COLLECTING (13/20 days to first checkpoint)
- 13 days, 962 trades, mean +53.491 bps, day-t 1.91
- Last day (2026-10-29): -81.035 bps
- Checkpoint at day 20 = Mon 2026-11-09 (scored Tue 2026-11-10 06:45 PT). Rule: PASS if mean >= +5 bps AND t >= 2; FAIL if mean < 0.
- **Read: Softening but still the best live test.** t dropped from 2.37 (9 days) to 1.91 (13 days), mean dropped from +81.6 to +53.5 bps. Still positive, still near the bar. Needs t >= 2 AND mean >= +5 bps at day 20 — achievable but no longer comfortable. Last day was -81 bps — one more bad day could drop t under the threshold.

## V3 ON1 Forward — Tracking only
- 17 days, 1241 trades, mean +17.688 bps, day-t 0.70
- Read: Too early; noise.

## V3 ON1 Real-Price — COLLECTING (0 days; no quotes captured yet)
- Status: COLLECTING; 0 trade-days with both open and close quotes
- Quote Clerk captured: 1 attempt on 2026-10-30, status = FAILED (state/usage.csv)
- Rule activates at 15 days (PASS if mean >= +5 bps and day-t >= 2)
- **Read: Not yet running.** The Quote Clerk failed its first capture today. No real-price data yet. Cannot assess spread cost vs paper. This must be working before ON1 paper can be considered tradeable.

---

## V4 EPRE Paper — COLLECTING (388/1000 to checkpoint A)
- 388 closed trades (up from 0 last week — test is now accumulating)
- Hedged mean: -6.9 bps | exit-day t: -0.39 (3 days) | report-date accuracy: 97%
- Checkpoint A at 1,000 closed trades: FAIL if hedged mean < -20 bps
- Backtest benchmark: ~+19 bps hedged
- **Read: Too early; not alarming yet.** At -6.9 bps the model is underperforming its backtest but well above the -20 bps FAIL line. Only 3 exit days of data so t is meaningless. Watch the hedged mean trend. Report-date accuracy at 97% is strong.

---

## Decisions Coming Up
| Date | Event |
|---|---|
| Thu 2026-11-05 | V3 G2 paper 20-day checkpoint — likely FAIL (mean -19.6 bps) |
| Mon–Tue 2026-11-09/10 | V3 ON1 paper 20-day checkpoint — PASS/CONTINUE/FAIL (t 1.91, mean +53 bps; borderline) |
| ~Dec 2026 | V2 rank 100-trade go/no-go (est. ~5–6 more weeks at current pace) |
| ~Dec 2026 | V3 G2 paper 40-day checkpoint (if survives day 20 — currently unlikely) |
| ~Dec 2026 | V3 ON1 paper 40-day checkpoint |
| Ongoing | V4 EPRE checkpoint A at 1,000 closed trades |
