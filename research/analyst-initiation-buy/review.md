# Skeptic review — analyst-initiation-buy — 2026-11-04

**VERDICT: FAIL.** Same failure mode as reg-fd: the pre-registered LONG has negative train
expectancy, and the idea is in any case flagged NOT promotable (no real-time rating feed).

## The kill (luck / edge — check 2)
Pre-registered chosen = `sp600_h3` (plan.json; PLAN.md:44). Train result:
mean **−19.85 bps**, week-clustered t **−1.28**, trade_mean −24.22 (train_result.json:16-22).
- Hypothesis is a LONG on bullish initiations with a *positive* drift (PLAN.md:3-10).
- Chosen is negative; a chosen train t must be ≥ +2.0 and above luck (1.89). It is −1.28.
- The whole sp600 leg is negative at every hold: sp600_h1 −19.5 (t −1.77), sp600_h3 −19.85 (t −1.28),
  sp600_h5 −16.6 (t −0.86). The sp46 blends hover near zero (−1.4 to +2.6, |t| ≤ 0.74) — i.e. the
  "strongest in small caps" prediction is again inverted: small caps are the *worst*, not the best.
- Best-looking variant is sp46_h5 at t +0.19 — indistinguishable from noise and far below luck 1.89.
  Nothing here is tradeable in the hypothesized direction.

## Promotability — independently fatal
PLAN.md:82-88 states this is **NOT promotable as-is**: `ratings()` is a one-time yfinance snapshot,
no near-real-time point-in-time initiation feed exists (same blocker as the insider family). Even a
hypothetical train/holdout pass could not become a paper test. With a negative train on top, dead.

## Other checks
1. **Look-ahead — pass.** GradeDate is date-only; entry at the OPEN of the first session strictly
   after GradeDate is leak-free regardless of publish time (PLAN.md:29-31). Dedup one per
   (ticker, GradeDate); SPY-hedged same window.
3. **Costs — n/a.** cost_bps 25 reasonable; gross is already deeply negative.
4. **Sample — thin but not the issue.** sp600 only 1,645 trades over 358 week-periods across 2012-19;
   yfinance small-cap rating history is sparse pre-2016 (plan acknowledges). The sign is consistent and
   strongly negative, so this is not a thin-sample fluke that a richer holdout would rescue.
5. **Baseline — pass.** SPY-hedged. Survivorship + underwriter-conflict both bias a long UP
   (PLAN.md:74-80), so the true long edge is worse than measured. Reinforces FAIL.
6. **Paper match — n/a.** strategy.py/spec encode the frozen rule for the record only (not promotable).
7. **Graveyard — ok.** Distinct from the dead V3 upgrade/downgrade work (re-ratings, not initiations);
   `analyst_ratings` family had no prior search or holdout. But no holdout should be spent — train is a
   clear loser and the idea can't be paper-traded anyway.

## For the record
Honestly constructed and honestly reported (pre-registered chosen, biases + non-promotability flagged
up front). The initiation-drift LONG is simply not present in this universe/era — if anything negative.
Do NOT spend the analyst_ratings holdout.
