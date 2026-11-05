# Diagnosis 2026-11-05

## Item 1: V4 EPRE — 1 row with |ret_bps| > 5000 bps AND |net_bps| > 5000 bps

**Row:** `epre_ledger.csv` line 831

| field | value |
|---|---|
| ticker | VCYT |
| entry_day | 2026-11-03 |
| exit_day | 2026-11-05 |
| report_day | 2026-11-04 |
| bmo | False (reported after close 11-04) |
| time_source | history |
| entry_close | 50.29 |
| exit_close | 24.0 |
| ret_bps | -5227.7 |
| net_bps | -5243.7 |
| hedged_bps | -4955.0 |
| date_ok | True |

**Cause:** VCYT dropped ~52.3% from $50.29 (11-03 close) to $24.0 (11-05 close) on its earnings reaction
day. The report landed after hours on 11-04 (bmo=False), making 11-05 the reaction session. This is a
genuine post-earnings gap-down, not a data error. The numbers are internally consistent:

- ret_bps = (24.0/50.29 - 1) × 10000 = -5227.7 ✓
- net_bps = ret_bps - costs (2 × 8 bps for sp600) = -5227.7 - 16 = -5243.7 ✓
- hedge_bps = -288.6 matches every other 2026-11-05 trade (index down 2.89% that day) ✓
- hedged_bps = net_bps - hedge_bps = -5243.7 - (-288.6) = -4955.1 ≈ -4955.0 ✓

The integrity threshold BPS_MAX = 5000 (`tools/integrity.py:23`) is a conservative heuristic. Post-earnings
crashes of 50%+ are rare but real for small-cap healthcare/diagnostics companies. The RULES.md itself
notes "one report gap can be -30% or worse".

**Effect on data:** This trade is already included in the snapshot (836 closed, hedged mean +28.7 bps).
Without it: (836 × 28.7 + 4955.0) / 835 = **+34.6 bps**. Impact is real but the trade is valid if the
price is correct.

**Code reference:** `epre/paper.py:313-319` — exit_close is fetched from Yahoo Finance via yfinance
(`auto_adjust=True`). The $24.0 value is the Yahoo-adjusted close.

**Action needed (USER):** Verify VCYT exit close on 2026-11-05 against Webull (or any independent
source). If $24.0 is correct, the trade is valid — no fix needed; `integrity_seen.json` now records it
as known and it will not re-alert. If the Yahoo price is wrong, the row will need manual correction and
re-scoring of `hedged_bps`.

**Suggested fix (if Yahoo price is wrong):** correct `exit_close` in the ledger and rerun
`python -m epre evaluate --dry-run` to see the corrected values; then update the ledger by hand.
No code change needed in integrity.py — the threshold is working as designed (flag first, human verifies).

---

## Checkpoint: V3 G2 paper — day 20

**Numbers from state/snapshot.txt:**
- Days: 20/40
- Trades: 189
- Mean: -33.453 bps/day
- Day-t: -2.05
- Last day (2026-11-05): -92.389 bps

**Rule (frozen, TEAM.md):** At day 20 — PASS if mean >= +5 bps AND day-t >= 2; **FAIL if mean < 0**;
else continue to day 40.

**Verdict: FAIL**

Mean is -33.453 bps < 0. The FAIL condition triggers immediately. The day-t of -2.05 confirms the
negative result is not noise. The Outlook section of snapshot.txt confirms: reaching breakeven by day 40
would require the next 20 days to average +34.7 bps/day; the best single day so far was +102.7 bps.

G2 is dead. The Director should retire the paper test per normal pipeline process.
