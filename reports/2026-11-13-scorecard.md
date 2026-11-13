# Weekly Scorecard — 2026-11-13 (Friday)

## Live Tests

### V2 Rank track — COLLECTING (88/100 closed, NO-GO likely)
- **Progress**: 88/100 closed trades
- **Deciding numbers** (after costs): mean R +0.070 (need >= +0.15 for GO; < 0 for NO-GO); week-clustered t 0.27 over 12 weeks (need >= 2 for GO); vs sector ETF -0.14%/trade (need > 0 for GO)
- **Outlook (from snapshot)**: last 12 trades must average +0.737R to reach GO; or average < -0.513R for NO-GO. At the current mean of +0.070R this is arithmetic near-impossible. Loss cluster 2026-11-11: 3 bearish losses on one day (AVGO, KLAC, ADI; -4.31R) — correlated, one market move. Mean R excluding that exit day: +0.180.
- **Honest read**: Looking weak. GO requires a +0.737R average on 12 remaining trades — over 10× the current mean. Random control mean is -0.231R after costs, so rank is beating it, but not enough to clear the GO bar. NO-GO is the modal outcome at 100.

---

### V3 G2 paper — RETIRED (FAILED day-20)
- Retired 2026-11-08. Mean -26.2 bps at day 20, day-t -1.58. Rule: FAIL if mean < 0. Dead.

---

### V3 ON1 paper — CONTINUE (day 21/40, looking weak)
- **Progress**: day 21/40
- **Deciding numbers**: mean +5.077 bps (need >= +5 bps AND day-t >= 2 for PASS at day 40; FAIL if mean < 0); day-t 0.18
- **Outlook (from snapshot)**: For PASS (at this sd of 125, need mean >= +39.5 bps and t >= 2): next 19 days must average +77.7 bps/day. Best single day so far: +264.5. For not-FAIL (mean >= 0): next 19 days can average as low as -5.4 bps/day. Last day (11-11): -275.0 bps.
- **Honest read**: Looking weak. Mean just barely above the 0 FAIL floor (+5.1 bps), t at 0.18, and the last session was -275 bps. PASS requires 77.7 bps/day average for 19 more days — not ruled out mathematically (the best day was +264 bps) but very demanding. FAIL is in play if more days like 11-11 occur. A cliff-edge test.

---

### V3 ON1 real-price — COLLECTING (7/15 days, FAIL trajectory)
- **Progress**: 7 of 15 days (514 trades; first day 2026-11-02, last 2026-11-11; next verdict window ~2026-11-24)
- **Deciding numbers**: real mean -85.4 bps (t -1.60); paper mean same trades +1.5 bps; avg half-spread 46.6 bps
- **Rule**: from 15 days PASS if real mean >= +5 bps AND t >= 2; FAIL if mean < 0; otherwise continue. At 30 days: PASS or FAIL.
- **Honest read**: Firmly negative. The spread (~93 bps round-trip) is consuming whatever paper edge exists. Even if paper is barely positive, real-price is -85.4 bps on a solid 514-trade base. Unless there is a dramatic reversal in the next 8 days, real-price will FAIL at day 15. If paper somehow passes at day 40, real-price is likely to veto it. ON1 is currently not tradeable at real Webull prices.

---

### V4 EPRE paper — PASS imminent at checkpoint A (991/1,000)
- **Progress**: 991 closed, 9 from checkpoint A (1,000 trades); hedged mean +23.0 bps; exit-day t 0.37 (12 days); report-date accuracy 95%
- **Checkpoint A rule**: FAIL if hedged mean < -20 bps at 1,000 trades. Current mean is +23.0 bps — would need the last 9 trades to average approximately -4,500 bps to drag it below -20 bps. PASS is virtually certain.
- **Next checkpoint B** (3,000 trades): real money authorized if hedged mean >= +10 bps AND t >= 1 AND date accuracy >= 90%. Current t is 0.37 on 12 exit-days — will grow as exit-day count rises.

### V4 EPRE real-price — VERY PROMISING (452 trades, 5 exit days)
- **Numbers**: real hedged mean +91.7 bps (paper same trades +92.3 bps); spread cost only 12.6 bps; real t 1.48 (5 exit days)
- **Honest read**: Outstanding. Spreads are negligible for EPRE (held 1-2 days, options hedge). Real-price nearly matches paper. If this holds through checkpoint B, the real-money condition is on track. Only 5 exit-days so far — too early to treat t 1.48 as stable.

---

## Decisions Coming Up

### 1. V4 EPRE — Checkpoint A (~this week, ~9 trades away)
- Expected: imminent, possibly as soon as next Tuesday.
- Arithmetic: PASS is essentially certain (+23.0 bps vs -20 bps FAIL bar; +43 bps of cushion on 991 trades).
- After checkpoint A: test continues collecting toward checkpoint B at 3,000 trades. No action needed from user.

### 2. V2 Rank go/no-go (~12 trades away, 2–3 weeks)
- Outlook: last 12 trades must average +0.737R for GO (vs current mean +0.070R). NO-GO requires averaging < -0.513R.
- Neither extreme is likely; most probable outcome is mean stays between 0 and +0.15 → NO-GO by failure to reach bar.
- User decision needed: on NO-GO the rank track closes. On GO the Director proposes a paper test.

### 3. V3 ON1 real-price — verdict window ~2026-11-24 (8 trading days away, 15 days total)
- Currently -85.4 bps on 7 days. Needs to reverse to above 0 to avoid early FAIL.
- If FAIL at 15 days: ON1 is not tradeable at current Webull spreads. The paper test can still run to day 40, but a real-price FAIL means no real money regardless of the paper result.

### 4. V3 ON1 paper — day 40 scored ~Thu 2026-12-10
- Need: 77.7 bps/day average over 19 remaining days to PASS. 
- Not-FAIL (mean >= 0): next 19 days can average as low as -5.4 bps/day.
- Best case: ON1 paper might just survive to day 40, but PASS needs sustained strong performance.
