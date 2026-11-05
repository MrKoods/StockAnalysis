# Skeptic review — restructuring-bounce (2026-11-05)

**VERDICT: FAIL.** The pre-registered `chosen` variant came back negative on train.
No holdout spent (8k_2_05 family holdout untouched).

## The killing fact
`chosen = sp600_h3` (train_result.json:8-16): **t −0.85, mean −24.43 bps, n_periods 230, n_trades 316.**
A negative, insignificant chosen variant cannot go to holdout — the hypothesis (small-cap 2.05 filers
*recover* at open+2→open+5) is the opposite of what train shows: the smallest-cap subset keeps *falling*.
The plan's own kill condition (PLAN.md:75: "net t < 3.00 or mean ≤ 0 → DEAD") is met on train.

## Check-by-check
1. **Look-ahead — PASS (test is clean).** Event = 8-K containing item 2.05 (test.py:43). `first_session`
   is rd's first open strictly after SEC acceptance (PLAN.md:38-40), entry = `entry_pos = pos + 1` =
   open+2 (test.py:66), exit = `entry_pos + hold` open (test.py:67,76). Both legs open-to-open, SPY
   hedged on the same two sessions (test.py:82). Dedup one trade per (ticker, first_session)
   (test.py:48). No same-bar, no future dates, no full-sample stat. Leak-free — the signal just isn't there.
2. **Luck — FAIL.** `luck_t_best_of_n` 1.67; best variant (sp46_h5) t 0.99 < luck, and the *chosen*
   variant is t −0.85. Neighbourhood is incoherent/weak: sp600_h3 −0.85, sp600_h5 +0.19, sp46_h3 −0.15,
   sp46_h5 +0.99 — signs flip with hold length, no monotonic small-cap→bigger-recovery structure that the
   thesis predicted. Nothing above 2.0, nothing above luck.
3. **Costs — moot.** cost_bps 35 is a reasonable small-cap both-legs-at-open estimate; irrelevant when
   gross/net are already negative or near-zero.
4. **Sample — adequate (not the problem).** 230 weekly periods / 316 trades for sp600_h3 — the power
   caveat in PLAN.md:80 didn't bite; the edge is simply absent, not just noisy.
5. **Baseline — PASS.** Metric is SPY-hedged (test.py:82), not raw long/beta. Survivorship (today's S&P
   600 applied back, PLAN.md:33) biases a long UP — yet it still prints −24 bps, which only strengthens
   the FAIL (the real, point-in-time number would be worse).
6. **Paper match — moot (not promoting).** Not checked in depth; FAIL on train means no paper.
7. **Graveyard — not a rerun.** First 8k_2_05 family train. Related dead ideas (reg-fd, analyst-init)
   are different families/items. The +31.6 bps / t 1.79 full-S&P-1500 screen cited as prior evidence
   (PLAN.md:21) was itself below its own luck bar (2.84) — the small-cap + delayed-entry "sharpening"
   did not rescue it; it inverted it.

## Pattern (for notes / future small-cap-long ideas)
Third small-cap LONG event idea in a row that comes back NEGATIVE on train (after reg-fd-small-cap and
analyst-initiation). The survivorship-inflated small-cap long tilt keeps running *opposite* the thesis.
early-10q-drift (next in queue) is the same shape — expect the same inversion; check before any holdout.
