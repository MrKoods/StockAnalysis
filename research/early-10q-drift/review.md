# Skeptic review — early-10q-drift (2026-11-05)

**VERDICT: FAIL.** Honest null. Chosen variant insignificant, below the 2.0 floor and below the luck
bar. No holdout spent (10q_timing family is clean/untouched).

## The killing fact
`chosen = sp1500_t7_long` (train_result.json:8-15): **t 0.99**, below the ≥2.0 floor and below
`luck_t_best_of_n` 1.89. Best of all six variants (sp1500_t14_long) is only **t 1.45 — still under
luck**. Nothing clears. Plan kill condition (PLAN.md:65) met.

Extra tell: chosen `trade_mean_bps` is **−9.97** while the week-clustered `mean_bps` is +20.33. The
positive period mean is carried by a few high-count weeks; equal-weighting trades is *negative*. That is
the opposite of a robust under-reaction drift — the "edge" is unstable week-composition, not a per-event
signal. t 0.99 already says so.

## Check-by-check
1. **Look-ahead — PASS (clean).** The timing delta is built only from PAST filings: for each 10-Q at
   `Di`, the prior-year match `Dj` is scanned backwards over earlier filings (test.py:63-71), `days_early
   = (Dj + 1yr) − Di` (test.py:74) — both dates known at `Di`. Entry = OPEN of `first_session` (first
   open strictly after SEC acceptance, test.py:94-106); exit = open+3 (test.py:97). SPY hedge on the same
   two sessions (test.py:112). Only original 10-Q, amendments dropped (test.py:52). Dedup per
   (ticker, acc_day) (test.py:55). No leak.
2. **Luck — FAIL.** chosen t 0.99 < 2.0 and < luck 1.89; best variant 1.45 < luck. The grid is a
   coherent-but-null map: long t's 0.99/1.45/0.48/0.81, shorts 0.37/0.19 — larger threshold (≥14) lifts
   it slightly but never to significance, and the small/mid universe is weaker, not stronger. No config
   is tradeable.
3. **Costs — moot.** cost_bps 20 is fair for S&P-1500 both-legs-at-open; irrelevant at t 0.99.
4. **Sample — ample (not the problem).** chosen n_periods 452 / n_trades 2965. Plenty of power; the
   signal is simply ~zero. (High event rate was flagged as a dilution risk, PLAN.md:72-74 — borne out.)
5. **Baseline — PASS.** SPY-hedged (test.py:112). Survivorship biases the long UP (PLAN.md:71) yet it
   still can't clear t 1.0 — the real point-in-time number would be weaker, reinforcing FAIL. The
   late-filer short (the plan's internal control) is also null (t 0.37/0.19), so there is no symmetric
   timing effect — consistent with "no edge" rather than "we mislabelled the sign."
6. **Paper match — moot (not promoting).**
7. **Graveyard — not a rerun.** First 10q_timing family train; distinct item/mechanism from the dead
   small-cap event ideas.

## Note
Unlike restructuring-bounce / reg-fd / analyst-init, this is NOT the small-cap-long inversion — the
broad long is weakly positive, just insignificant. A genuine, well-powered null on a clean new family.
Pre-registration worked: the slightly-better ≥14 cousin (t1.45) was correctly NOT chosen and is itself
sub-luck, so there is nothing to chase.
