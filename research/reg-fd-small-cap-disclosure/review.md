# Skeptic review — reg-fd-small-cap-disclosure — 2026-11-04

**VERDICT: FAIL.** The pre-registered chosen config has strongly NEGATIVE train expectancy, and
the core mechanism is refuted (the hypothesis predicts the opposite sign of what the data shows).

## The kill (luck / edge — check 2)
Pre-registered chosen = `sp600_h1` (plan.json / test.py:25). Its train result:
mean **−17.9 bps**, day-clustered t **−2.77**, trade_mean −10.96 (train_result.json:8-15).
- The hypothesis is a **LONG** with a *positive* expected drift (PLAN.md:7-8, test.py:81 `gross` long).
- The chosen config is significantly negative. Plan's own kill rule is "mean ≤ 0 → DEAD" (PLAN.md:61);
  the chosen direction is not merely zero, it is reliably losing on train.
- A chosen train t must be ≥ +2.0 and clearly above luck (1.89). It is −2.77. Fails outright.
- No post-hoc flip to short: the hypothesis, plan and strategy.py are all committed LONG; reversing
  the sign after seeing the result is a new, unregistered hypothesis.

## Mechanism refuted (makes this worse, not a near-miss)
Every variant is negative, and the small-cap tilt the thesis depends on runs the WRONG way:
- sp600_h1 −17.9 (t −2.77), sp400_h1 −16.69 (t −2.52), sp46_h1 −17.77 (t −3.68) — all 1-day longs
  strongly negative (train_result.json). The prior full-S&P-1500 screen cited in the plan showed 7.01
  = **+6.5 bps 1d** (PLAN.md:17-19). So the positive pooled-screen signal was driven by the large caps
  the plan excluded; the small/mid subset the mechanism says should be *strongest positive* is in fact
  the most negative. The thesis is inverted by its own data. Clean, decisive kill.

## Other checks (not the deciding factor, recorded for completeness)
1. **Look-ahead — pass.** Entry at `first_session` open (rd's first session strictly after SEC
   acceptance), exit at close H later; SPY hedge over the same window (test.py:51-82). Events dated by
   `first_session`, not `filing_date` (test.py:42-48). Dedup one per (ticker, first_session). Leak-free.
3. **Costs — n/a.** cost_bps 30 is reasonable for small-cap open/close; irrelevant when gross is
   already −17.9 before an extra cost.
4. **Sample — pass (not the issue).** 7,820 trades over 2,095 day-periods; ample. The negative result
   is not a thin-sample artifact.
5. **Baseline — pass.** SPY-hedged, so not market beta. Survivorship (current S&P 600 back-applied)
   biases a long UP — the true long edge is even more negative than measured. Reinforces FAIL.
6. **Paper match — pass.** strategy.py encodes sp600_h1 long, enter first_session open, hold 1
   (strategy.py:1-16,79). Matches test.py chosen. (Immaterial given the FAIL.)
7. **Graveyard — ok.** First `8k_7_01` holdout attempt; the full-universe screen was search-only, not a
   spent holdout. But no holdout should be spent on a config the train already shows is a loser.

## For the record
Honest, well-constructed plan (pre-registered chosen, survivorship flagged, promotable). It did exactly
its job: the sharpened small-cap LONG hypothesis is false on train. Do NOT spend the 8k_7_01 holdout.
