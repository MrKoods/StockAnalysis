# Skeptic review — insider-cluster-buys (2026-10-27)

Verdict: **PASS** (sends to one holdout 2014–2017, bar t ≥ 3.0). Chosen config is
pre-registered `n2_h5_m75k`; train net t 2.9, net mean 82.63 bps/week, 863 trades / 299 weeks.

## 1. Look-ahead — PASS
- Trigger is measured by **FILING_DATE**, not transaction date (`test.py:57`, `_candidates`
  window `fd-5d < f <= fd` at `test.py:73`). Filings must be public to count — leak-free by design.
- Entry = first session **strictly after** fd: `idx.searchsorted(fd, side="right")` (`test.py:96`);
  exit = close `hold-1` sessions later (`test.py:97-100`). No same-bar/same-day entry.
- No full-sample means/ranks; thresholds are absolute dollar/count constants. Episode dedupe
  consumes the fire even when price data is missing (`test.py:90-91`) — no forward peeking.
- `rd.insider(lo)` pulls from `start-15d` only for the window lookback (`test.py:47`). Fine.

## 2. Luck — PASS
- Chosen `n2_h5_m75k` is **pre-registered, not best-of-train** (`test.py:27,147`; PLAN §Variants).
  Decision is a single hypothesis, so the best-of-N penalty does not apply to it.
- Even so, chosen net t **2.9 > luck_t_best_of_n 2.23** (`train_result.json:105`) and well above the
  2.0 floor. The best-looking variant (n2_h10_m75k, t 4.04) was correctly NOT carried forward.
- Neighbourhood is smooth & sign-stable: all six n2 configs net t 2.75–4.04; all six n3 configs
  positive too (t 1.2–2.6, thinner n). No sign flips → not a lone spike.

## 3. Costs & fills — PASS
- `cost_bps = 20` round-trip, subtracted in harness (`tools/jobs.py:99`); reported bps are **net**.
- Universe is S&P 500 ∪ S&P 400 (liquid mid/large caps), open→close hold — 20 bps is conservative.
- Net per-trade mean 86.62 bps (≈107 gross). At 1.5× cost (30 bps) the edge loses ~10 bps → still
  ~72–76 net. Survives comfortably.

## 4. Sample — PASS (train); holdout thinness is the live risk
- Train: 299 weekly clusters, 863 trades over 2006–2013 (8 yrs). Far above the ≥20-week floor; not
  driven by one year.
- Holdout 2014–2017 (4 yrs) will be materially thinner — flagged for the Holdout Keeper, not a train
  defect.

## 5. Baseline — PASS with caveat
- Metric is **SPY-hedged** gross (`test.py:107`), so market beta is removed — not long-only beta.
- **Survivorship is real and unremovable**: only *current* S&P 500/400 membership is applied back to
  2006 (PLAN §Universe; `_universe` at `test.py:39-41`). For a long signal this biases returns up.
  Magnitude is modest for a 5-session hedged hold (delisting/bankruptcy mostly hits long-horizon
  buy-and-hold, not 5-day hedged windows), so it is unlikely to account for an 82 bps / t 2.9 edge —
  but if the holdout comes in marginal, treat it as survivorship, not signal. Explicitly pre-stated.

## 6. Paper match — PASS (but promotion BLOCKED by data lag)
- `strategies/.../strategy.py` encodes the chosen rule: N_INS=2, MIN_PER_INSIDER=$25k,
  MIN_TOTAL=$75k, WINDOW_DAYS=5 (`strategy.py:23-26`), same FILING_DATE window, same next-session-open
  entry, exit close 5 sessions later (spec `hold_sessions:4` = pos→pos+4 = test.py `hold=5`). Same
  universe (current sp500+sp400). Rule matches `chosen`.
- Promotion correctly blocked: only source is SEC quarterly bulk Form-345 (publishes months late), so
  a 3–5-day hold cannot be traded live (PLAN §Can this become a paper test; `strategy.py:8-10`). This
  is a research-verdict-only idea. The gate/Director must not promote — noted.

## 7. Not a graveyard rerun — PASS
- Graveyard lists no insider-cluster work. The family's one spent holdout was **single-officer buys
  ≥$100k** (v3-insider-buys, t 2.3 near-miss; PLAN §Windows). This idea requires **≥2 distinct
  insiders ≥$25k each** — a distinct signal (independent convergence), not that test under a new name.
  The queued `insider-officer-buys` is the single-officer variant and is also separate.

## Bottom line
No look-ahead, luck, cost, sample, or baseline failure I can establish on train. The only live
weaknesses — survivorship bias and holdout thinness — are pre-declared and go to the holdout bar
(t ≥ 3.0, positive net mean) to resolve. PASS to holdout.
