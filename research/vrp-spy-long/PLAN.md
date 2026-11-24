# vrp-spy-long — pre-registered plan

**Family:** cboe_vrp (new family, no periods used — whole history clean)
**Instrument:** SPY only (index-level timing; no single stocks)

## Hypothesis
The variance risk premium — VRP = VIX (implied vol) − realized vol — predicts SPY's forward
~1-month excess return (Bollerslev-Tauchen-Zhou 2009 RFS; Drechsler-Yaron 2011). When VRP is
high relative to its recent norm, the fear premium is rich and equities earn more over the next
~20 sessions; when VRP is low, expected equity returns are below normal. The payer: buyers of
variance insurance (hedgers) overpay in fearful regimes; holding equity through that fear is
compensated.

## Why this is tested LONG/SHORT, not long-only (deviation from the idea card — read this)
The card specifies a LONG-only SPY rule. A long-only SPY test is scientifically void here and
**cannot become an honest paper test**, for one reason: SPY has no hedge instrument (hedging SPY
with SPY is zero), so the paper metric must be `real_bps` = raw SPY return. Raw SPY 20-day returns
are positive on average purely from the equity premium (unconditional monthly t ≈ 2.2 over
2000-2013 with NO signal at all). A long-only raw test would "pass" on beta, not on VRP.

The honest, literature-faithful, and promotable design isolates the premium from beta:
**long SPY when VRP is above its trailing norm, short SPY when below.** Under the null (VRP has no
predictive power) the long and short legs sample the same return distribution with equal frequency,
so the equity premium **cancels** and E[gross] = 0. A positive mean is the VRP predictive edge and
nothing else. This is exactly the BTZ predictive content, expressed as a tradeable, beta-neutral
rule. Short SPY overnight is tradeable on a Webull margin account (holds are 20 sessions → no PDT
issue; no options needed). The real-money step (user's) needs a margin account for the short legs.

## Exact rule
Each session t:
1. `RV_t` = annualized 20-session realized vol of SPY = std(daily log returns, last 20) × √252 × 100.
2. `VRP_t` = `VIX_t` (CBOE close) − `RV_t`, in annualized vol points.
3. `z_t` = (VRP_t − trailing mean of VRP) / (trailing std of VRP), window = `zwin` sessions, all ≤ t.
4. Side: **long** if `z_t > k`, **short** if `z_t < −k`, else flat (skip).
5. Entry: the **next session's close** (t+1). Using the next close means VIX_t's 16:15 ET close is
   already known before entry → no look-ahead (cboe() docstring warning respected).
6. Exit: the close 20 sessions after entry (t+21). Hold = 20 sessions.
7. Gross per trade = side × (SPY_exit / SPY_entry − 1) × 1e4 (raw signed; harness subtracts cost).
8. Overlapping daily entries, **clustered by month** (hold > 10 → harness enforces month clustering;
   month-clustering is the standard mitigation for overlapping 20-day returns).

Overlapping daily entries (not non-overlapping monthly) are used deliberately: a non-overlapping
monthly rule produces ~1 trade/month, which could never accumulate enough closed trades for the
20-45 day paper test. Daily entries give ~1 exit/day in paper while month-clustering keeps the
research t honest (~12 clusters/year).

## Universe and cost
`universe: ["sp500","sp400"]` — SPY is not an sp500/sp400/sp600 constituent; this field only sets the
real-spread cost FLOOR. `["sp500"]` alone is avoided because it would force rd.pit_filter (membership
filtering), which deletes SPY (SPY is not an index member). The floor for ["sp500","sp400"] at
close/close is **12 bps round trip** (sp400 close half-spread 6.0 × 2) — this **overcharges SPY ~6-12×**
(SPY's true close spread is ~0.5-1 bp/side, ~1-2 bp round trip). The harness will charge 12 bps RT.
Clearing the test at 12 bps is therefore a conservative, strong result; the paper test charges SPY's
real captured spread via `real_bps`, far lower. `cost_bps: 2` is my own SPY estimate (dominated by the
12-bp floor in research; used only as the quote-fallback half-spread in paper).

Fills: entry close / exit close (never the open — the open spread is 40-130 bps and would swamp any
edge). Holding period 20 sessions makes even the 12-bp floor small per trade.

## Variants (6; chosen pre-registered, NOT best-of-train)
`k ∈ {0.0, 0.5, 1.0}` × `zwin ∈ {126, 252}` = 6 configs.
- **chosen = `k0_z126`** (median split, 6-month standardization), fixed in advance. Rationale: the BTZ
  effect is monotone in VRP, so a median split (k=0) captures the core with maximum power and trades
  every session (long or short); zwin=126 is chosen over 252 because the paper runner downloads only
  ~400 calendar days (~275 sessions) — 126+20 warm-up fits comfortably, 252+20 does not. strategy.py
  mirrors `k0_z126` exactly.
- The other 5 are **robustness** reads: does the edge strengthen with selectivity (higher k) and is it
  stable across the standardization window (126 vs 252)? They are reported but do not change `chosen`.
6 variants → best-of-N luck t ≈ 1.9 (family has no prior search variants — new family).

## Windows and power
- **Train: 2000-01-01 .. 2013-12-31** (14y). SPY daily from 1999-01 and VIX from 1990 give warm-up.
- **Holdout: 2014-01-01 .. 2026-10-31** (~12.8y), clean for cboe_vrp (new family).
- Calendar ratio holdout/train ≈ 0.92 → expected holdout t ≈ train t × 0.96. The underpowered gate
  (needs expected holdout t ≥ ~2.33, i.e. train t ≥ ~2.43, for pass_prob ≥ 0.25) will bury this
  WITHOUT spending the holdout if the train t is weak. Holdout bar = 3.0 (first holdout in the family).
- **Expected magnitudes (stated for pre-registration):** BTZ high-vs-low monthly spread ~100-150 bps;
  a median-split long/short captures a fraction, I expect ~20-50 bps gross per 20-day trade in train.
  Winner's-curse guidance (holdout keeps ~35% of train t): if train t ≈ 2.5-3.0, expect holdout
  t ≈ 1.0-1.3 — **below the 3.0 bar**. This idea most likely dies at the holdout even if the train
  looks good; that is the honest expectation, not a prediction of success.

## Survivorship
SPY-only; no cross-sectional membership question, so pit_filter is not applicable (and would wrongly
delete SPY). No survivorship inflation: SPY is a continuously-traded ETF over the whole window.

## Adjacency to the dead pre-team "VIX timing" (honesty note)
Pre-team "VIX timing" failed a 2018-2026 holdout (graveyard; exact rule not retrievable without the
Engineer — likely a VIX LEVEL threshold, VIX > N → buy). This idea differs: (a) it conditions on
VRP = VIX − realized vol, demeaned by a trailing window — not a VIX level; (b) it is beta-neutral
long/short, not long-only; (c) cboe_vrp is a new family. **But my holdout 2014-2026 overlaps the
2018-2026 period where a related signal failed.** I never saw the pre-team results and tuned nothing
to them; 2014-2017 is genuinely fresh; and a failure here would be confirmatory, not a false pass.
The residual risk is a false PASS if VRP accidentally fits 2018-2026 — disclosed here for the Skeptic.

## What would kill it
- Train chosen t < 2.0 or mean ≤ 0 after the 12-bp cost → dead at train (no holdout).
- Expected holdout t < 2.33 → buried underpowered (no holdout spent).
- Holdout t < 3.0 or mean ≤ 0 → dead (the likely outcome).
- Skeptic: the long/short construction is beta-neutral by design (null → 0), so a positive result is
  not equity beta; the main risks the Skeptic should press are (i) residual cross-month overlap
  inflating t, (ii) a few crisis months (2008, 2020) dominating, (iii) the 2018-2026 adjacency above.

## Promotable?
Yes. `real_bps` on a long/short SPY signal isolates timing even in paper; SPY is quoted by the Quote
Clerk (ETF captures). strategy.py = chosen `k0_z126`, entry at next session's close, hold 20, exit close.
