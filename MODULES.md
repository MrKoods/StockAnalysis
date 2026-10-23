# Module status and cleanup checklist (set 2026-10-23)

Rule: when a module's verdict comes in and it FAILS, (1) keep its code on an archive branch, (2) switch off its
scheduled tasks, (3) remove it from its active branch. Nothing is deleted from git history. Ask the user before
archiving. A module that PASSES stays and moves toward small real money only under its own rules.

| Module | Where | Verdict rule (fixed before data) | Expected verdict | Status |
|---|---|---|---|---|
| EPRE earnings premium (paper) | V4 `epre/` | RULES.md checkpoints A/B/C (1k / 3k / 6k trades) | A ~Jan 2027, B ~mid 2027 | RUNNING from 2026-10-26 |
| V2 rank track | V1 `paper_trading/` | 100 closed trades: GO if mean R >= +0.15, week-t >= 2, beats sector ETF; NO-GO if mean < 0 | ~Dec 2026 | running |
| V2 random-pick control | V1 `random_trades.csv` | baseline for the rank track (no verdict of its own) | with rank track | running |
| V2 threshold track | V1 `paper_trades.csv` | none of its own (data collection) | decide with rank track | running |
| V3 G2 gap fade - forward | V3 `forward.update_g2` | 40 sessions: PASS mean > 0 & day-t >= 2; FAIL mean < 0 | ~early Dec 2026 | running |
| V3 G2 gap fade - paper | V3 `g2_paper.py` | 20-40 days: PASS >= +5 bps & t >= 2; FAIL mean < 0 | ~Nov-Dec 2026 | running |
| V3 ON1 overnight - forward | V3 `forward.update_on1` | 40 sessions: PASS mean > 0 & day-t >= 2; FAIL mean < 0 | ~early Dec 2026 | running |
| V3 ON1 overnight - paper | V3 `on1_paper.py` | 20-40 days: PASS >= +5 bps & t >= 2; FAIL mean < 0 | ~Nov-Dec 2026 | running |
| V3 C6 sweep - forward | V3 `forward.update` | - | - | RETIRED 2026-10-23 (no edge in 8 yrs of minute data; forward t -2.16 at 14 sessions). Ledger kept. |
| V3 Dukascopy minute download + minute research | V3 `dukascopy.py`, `research/minute_auto.py` | - | - | RETIRED 2026-10-23 (no minute strategy passed). Tasks disabled; data kept on disk. |
| V3 research lab | V3 `daytrade/research/` | - | - | KEEP - where new ideas are tested before becoming a version |

If V2's rank track gets NO-GO, the V2 swing model (Version-1) is the candidate for a wipe/archive.
If G2 and ON1 both FAIL, V3 keeps only the research lab.
