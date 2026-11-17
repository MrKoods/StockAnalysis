# Skeptic review — special-dividend-drift-long (2026-11-17)

**VERDICT: FAIL.** The pre-registered chosen config does not clear the luck bar, and the harness's own
holdout-power estimate says the holdout is likelier to fail than pass. A PASS would waste the family's
one clean 8k_8_01 holdout on a sub-luck result.

## 1. Look-ahead — PASS
Clean. Entry at the CLOSE of `entry_session` (day 0, the audit fix), exit at close `hold` sessions later
(test.py:102-117), close→close throughout — no same-bar open/close leak. Events dated by
`first_session`/`entry_session`, not `filing_date` (test.py:70-75). `searchsorted(..., "left")` with an
exact-date equality guard on both entry and hedge (test.py:84-90, 104-111). sp500 cut uses
`rd.pit_filter(ev_all, "entry_session")` (test.py:166). Regex frozen pre-registration and not tuned on
results (test.py:37-38). Hedge priced on the same entry/exit dates (test.py:125-128).

## 2. Luck — FAIL (primary kill)
`luck_t_best_of_n` = **2.87** over `luck_variants_counted` = **62** (train_result.json:50-51). The
pre-registered chosen `all_sp1500_h20` has t = **2.67** (train_result.json:12) — **below** the
best-of-N luck bar. The Skeptic rule is explicit: the chosen t must be ≥ 2.0 AND *clearly above* the
luck figure. 2.67 < 2.87 fails that outright.
Neighbourhood (train_result.json:7-47): h20 2.67, h10 2.11, midsmall 3.14, sp500 1.45 (n=23), e1 1.95.
The ONLY variant that clears 2.87 is `midsmall_h20` (3.14) — and that is the most survivorship-exposed
cut (see #5). `best_t` 3.14 is barely over the bar; the chosen is under it. e0 (2.67) > e1 (1.95), so
the day-0 entry does add signal — but not enough to lift the chosen above luck.

## 3. Costs & fills — PASS
`cost_bps_used` 25.0 vs floor 21.8 (train_result.json:49-51); plan/spec both close→close
(plan.json:5, spec.json:1). test.py prices close for entry and exit (test.py:117). Trade mean 178.5 bps
survives 1.5× cost (37.5 bps) comfortably. (Caveat, not a cost failure: 178 bps trade mean runs HOT vs
the cited ~120 bps literature — consistent with survivorship inflation, see #5.)

## 4. Sample — borderline PASS
60 month-clusters / 175 trades for the chosen (train_result.json:9-11) — ≥ the 20-period floor.
Tell: period mean **226.0** > trade mean **178.5** (train_result.json:11,14) → the clustered t is
lifted by a few low-count months with big winners (heavy-month composition), not a uniform per-trade
edge. Weakens an already sub-luck t.

## 5. Baseline / survivorship — FAIL-leaning (corroborates #2)
Hedged per-index (SPY/IJH/IJR via `rd.index_of`/`rd.hedge_ticker`, test.py:122-129) — good, no raw beta.
But the edge is **strongest exactly where survivorship bias is worst and weakest where it is clean**:
`midsmall` (sp400+sp600, NO point-in-time list) is the only variant over the luck bar (t 3.14), while
the PIT-clean `all_sp500` cut is t 1.45 on n=23 (train_result.json:32-38). Names that later left the
mid/small indices are absent, biasing those long returns up. This is the signature of a survivorship
artifact, not a robust effect — and it is the cut carrying the headline t.

## 6. Paper match — PASS
spec.json `family` 8k_8_01, `entry_at` "same_close", `exit_at` close, `hold_sessions` 20, `cost_bps` 25
(spec.json:1-2) all match plan.json (plan.json:4-5) and the chosen config (test.py:42). Rule metric
`real_hedged_bps` (spec.json:3). Day-0 `same_close` paper path matches test.py's e0 close entry.

## 7. Graveyard — PASS
Not a rerun. The 8k_8_01 prior use was the undifferentiated 2005-2013 8.01 screen (LONG, t -1.58);
this is a text-filtered special-dividend subset with a distinct mechanism (ideas card:83-90). Train
2014-2019 / holdout 2020-2026 both clean of the 2005-2013 screen window.

## 8. Family — PASS
`family` 8k_8_01 honest; its prior screen variants are already counted in the 62-variant luck bar.
Hedge index matches the universe.

## 9. Power — FAIL (second kill)
`holdout_power.pass_prob` = **0.439** (train_result.json:67). Below 50% → the holdout is **likelier to
fail than pass even if the edge were real**. `expected_holdout_t` 2.85 < bar 3.0 (train_result.json:64-66).
The harness did not bury it (above 25%), but a chosen t under the luck bar + a <50% pass chance is
precisely the "weak PASS wastes the holdout forever" case the Skeptic exists to stop.

## Bottom line
FAIL. The pre-registered chosen t (2.67) is below the best-of-N luck bar (2.87); the only above-bar
variant is the survivorship-dirtiest cut; and the harness puts the holdout pass chance under 50%. The
8k_8_01 holdout is NOT spent (holdouts=0, stays clean). If re-proposed, it needs more power (the chosen
config itself clearing luck, not just midsmall) and a PIT-clean universe where the edge actually shows.
