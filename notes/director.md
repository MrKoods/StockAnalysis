# Director notes

## 2026-10-27 (Tue) — forced run
State at start: pipeline empty, 1 registered idea (insider-officer-buys), 0 team paper tests.

Decision: registered + queued **insider-cluster-buys** (>=2 distinct insiders, open-market, 5d window).
- Why over single-officer: single-officer's 2018-26 holdout is burned at a FAILING t2.3 — re-running as-specified
  = peeking. Cluster is a distinct, better-powered formulation with academic support (Lakonishok-Lee) and its own
  unused holdout. The single-officer near-miss is evidence the family has signal; cluster is the natural next test.
- insider-officer-buys left parked at `idea` (not dropped) — revisit only if cluster fails AND a fresh period exists.
- Researcher MUST design the PLAN on a fresh untouched period (2018-26 insider holdout is gone).

Pipeline limit: 1 queued + 1 parked-at-idea (idea stage doesn't count). OK.

### Live tests (from 2026-10-27 scorecard — do not re-derive numbers, read snapshot.txt)
- V2 rank go/no-go: 59/100 closed, mean R -0.019 (bar +0.15), t -0.20. Likely NO-GO. ~mid-Nov.
- V2 threshold: n=27, +0.113R, informational only (no rule).
- V3 ON1 paper: ON TRACK — only test clearing its bar (mean +81.6bps vs +5, t 2.37). 20-day cp ~2026-11-13.
- V3 G2 paper: failing (mean -16bps, t -0.91). 20-day cp ~2026-11-10.
- V3 G2/ON1 forward: too early (t 0.63 / 0.47).
- V4 EPRE: 115 open, 0 closed. Checkpoint A (1000 trades) far out.

### Watch next run
- g2_paper_task.log stale since 2026-10-09 though results update through 10-26 — scorekeeper flagged for ops.
- ~2026-11-10 G2 paper cp (failing), ~2026-11-13 ON1 paper cp (passing), mid-Nov V2 rank go/no-go.
- Saturday = weekly director report due.
- Check insider-cluster-buys progresses to `planned` (Researcher).
