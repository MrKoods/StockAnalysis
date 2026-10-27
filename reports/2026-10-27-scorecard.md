# Weekly Scorecard — 2026-10-27

Source: state/snapshot.txt (the only valid source for numbers).

---

## V2 Rank Track — go/no-go at 100 closed trades

- Progress: 59/100 closed trades
- Mean R after costs: -0.019 (bar: >= +0.15)
- Week-clustered t: -0.20 over 9 weeks (bar: >= 2.0)
- vs sector ETF: +0.06%/trade (bar: > 0)
- Random-pick control: 12 closed, mean R -0.351

**Honest read: looking weak, likely NO-GO.** Mean R is far below the bar (+0.15) and the t-stat is near zero. 41 more trades needed. At current pace a dramatic reversal is required to pass.

---

## V2 Threshold Track — no checkpoint rule, informational only

- 27 closed trades | mean R +0.113 | win 44% | week-t -0.90

Too early for a formal verdict. Mean is directionally positive but t is negative — sample is small and noisy.

---

## V2 Random-Pick Control — informational only

- 12 closed | mean R -0.290 | week-t +0.41
- Note: 6-trade correlated cluster on 2026-10-23 (all bullish, one market move, -3.18R) — not 6 independent results.

Too early to read.

---

## V3 G2 Paper — checkpoint at 20 days (need mean > 0 bps, day-t >= 2)

- 12 days / 20 | 113 trades | mean -16.1 bps | day-t -0.91
- Last session (2026-10-26): -100.3 bps

**Looking weak.** Mean is negative and t is negative. Eight sessions remain before the 20-day checkpoint (~2026-11-10). Would need a significant string of positive days to pass.

Note: g2_paper_task.log last written 2026-10-09 despite results through 2026-10-26. The paper file is still being updated by some mechanism, but the task log is stale — worth ops investigation if behavior is unexpected.

---

## V3 G2 Forward Test — checkpoint at 40 sessions (need mean > 0, day-t >= 2)

- 14 / 40 sessions | 2,638 trades | mean +0.024 ATR | day-t 0.63

**Too early.** Direction is positive but t is well below 2. 26 sessions to checkpoint.

---

## V3 ON1 Paper — checkpoint at 20 days (need mean >= +5 bps, day-t >= 2)

- 9 days / 20 | 666 trades | mean +81.6 bps | day-t 2.37
- Last session (2026-10-23): +52.2 bps

**On track — the only test currently clearing its bar.** Both mean (+81.6 vs +5 bar) and t (2.37 vs 2.0 bar) are passing. 11 more sessions to the formal checkpoint (~2026-11-13). Can afford some bad days but should be watched.

---

## V3 ON1 Forward Test — checkpoint at 40 sessions (need mean > 0, day-t >= 2)

- 13 / 40 sessions | 949 trades | mean +14.7 bps | day-t 0.47

**Too early.** Direction positive, t is low. 27 sessions to checkpoint.

---

## V4 EPRE Paper Test — checkpoint A at 1,000 closed trades

- 115 signals logged | 0 closed | 1,467 upcoming events in calendar

**Way too early.** Zero closed trades; all 115 are open. Checkpoint A is a long way out.

---

## Team Paper Tests

None active.

---

## Decisions Coming Up

| Date | Test | Event |
|------|------|-------|
| ~2026-11-10 | V3 G2 Paper | 20-day checkpoint (need mean > 0, t >= 2) — currently failing |
| ~2026-11-13 | V3 ON1 Paper | 20-day checkpoint (need mean >= +5 bps, t >= 2) — currently passing |
| ~mid-Nov | V2 Rank | 100-trade go/no-go (need mean >= +0.15, t >= 2) — currently far behind |
