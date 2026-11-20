# antitakeover-adoption-short — pre-registered plan

## Hypothesis
When a board **adopts a stockholder rights plan ("poison pill")** it files an 8-K item 5.03 (charter /
bylaw amendment). The pill entrenches management and removes acquisition-premium optionality. The market
reaction is negative (Ryngaert 1988 JFE: ~-150 bps cumulative abnormal return at announcement) and the
entrenchment literature (Bebchuk-Coates-Subramanian 2002 JLEO; Gompers-Ishii-Metrick 2003 QJE — high
G-Index firms underperform ~85 bps/month) says the market **underreacts**, so the stock drifts DOWN over
the following weeks. We **SHORT** the filer at the **day-0 close** and hold ~15 sessions to capture the
residual post-announcement drift.

## Mechanism / who is on the other side
The day-0 intraday jump down is already in the stock by the close we short at; what is left is a slow
drift as short sellers establish positions, governance-sensitive institutions trim, and proxy advisors
(ISS/Glass Lewis) flag the firm. The other side is passive/index holders who do not react to a
governance event and value investors who treat the pill as neutral.

## Signal
- Universe: S&P 1500 current members (variants cut to S&P 500 PIT and to S&P 400+600).
- Event: an 8-K **item 5.03** whose text (body + attached press release / `exhibit`) satisfies BOTH
  halves of a **FROZEN, pre-registered** filter:
  - `PILL_RE` — the instrument is present: `rights\s+(plan|agreement)|poison\s+pill`.
  - `ADOPT_RE` — a positive adoption indicator: `\badopt` ("adopted / adoption of a … rights plan")
    OR `enter(ed|ing|s)? into` ("entered into a Rights Agreement") OR
    `declar\w* (a )?([a-z-]+ ){0,3}dividend` ("the Board **declared a dividend** of one preferred-share-
    purchase **right** per share" — the formal pill-distribution mechanism, and the single most common
    way a new pill is announced).
- **Why a positive indicator, not a negative keyword list** (the card sketched "exclude terminate/
  expired/amend/extend"): in an item-5.03 universe those words appear in *genuine adoptions too* — an
  adoption 8-K describes the plan's expiration date, termination and redemption provisions, and 5.03
  itself means "bylaw/charter amendment", so bare "amend"/"expir"/"terminat"/"redeem" would reject most
  real adoptions. Requiring a positive adoption indicator instead naturally keeps out **terminations**
  ("terminated"/"redeemed the rights" — which do not adopt / enter into / declare a dividend of rights).
  Residual contamination (an amendment that still says "adopted"/"declared a dividend", or a rare
  mis-caught termination) only **dilutes** a SHORT edge — amendments are ~neutral and terminations are
  bullish, both of which make the measured short return *worse*, so a holdout pass despite them is
  conservative. Item-5.03 scoping also excludes financing "registration rights agreements" (item-1.01
  events). The filter is frozen here and is **not** tuned on train results (smoke shows counts only).
  An earlier tight `adopt`-adjacency regex was discarded at pre-registration because it missed the
  canonical "declared a dividend of one right … Rights Agreement" phrasing (2 vs 18 events in smoke
  2005) — a correctness fix to the signal definition, made before any performance was seen.
- Rows without downloaded text (`has_text` False) are skipped (`filing_text` covers 5,849 of 11,300
  5.03 items ≈ 52% — see power/selection note below).
- The signal date is `entry_session` (the first session whose CLOSE is still shortable after SEC
  accepted the 8-K before 15:30 ET — day 0, the 2026-11-13 audit's fix for entering a day late).

## Entry / exit / timing
- **SHORT at the CLOSE of `entry_session`** (day 0). The announcement drop is intraday, before that
  close; we capture the *drift* (days +1..+15).
- Cover at the close `hold` sessions later (chosen hold = 15; 10 and 5-session robustness variants).
- Hedge each trade with ITS OWN index fund (SPY / IJH / IJR via `rd.index_of` + `rd.hedge_ticker`).
- Close→close fills (cheap: ~7 sp500 / ~12 sp400 / ~22 sp600 bps round trip). `cost_bps` = 25 (the
  harness charges max(25, the real Webull close-spread floor for the universe); 25 covers sp600's 22 +
  a little impact). **Borrow is NOT priced** by `real_hedged_bps` (spread only) — a short-specific risk
  the Director must confirm before any real money (small caps can be hard-to-borrow).

## Universe / windows / clustering
- `universe` = ["sp500","sp400","sp600"]; the sp500-only variant runs events through
  `rd.pit_filter(events, "entry_session")` (point-in-time membership — required).
- Train **2005-01-01 .. 2013-12-31** (9y; item codes exist from 2004-08; includes the 2008-09
  financial-crisis defensive-pill wave). Holdout **2014-01-01 .. 2026-10-24** (~12.8y; includes the
  2020 COVID "crisis-pill" wave — a large block of adoptions). Family `8k_5_03` has used only 2005-2013
  (the free 8-K screen, 3 variants) — the holdout window is fully clean.
- Windows chosen **for power**: holdout/train ≈ 1.42 raises the expected holdout t =
  train_t × √(holdout/train). A longer train would lower that ratio.
- `hold_days` = 15 (> 10) → `cluster` = **month** (overlapping 15-session holds make weekly periods
  dependent; the harness enforces month). Reported ranking t is month-clustered.

## Expected events (power) — the central risk
Rights-plan adoptions are relatively rare and skew to small / micro caps (the takeover-target,
entrenchment-prone names), many of which are **outside** the S&P 1500. Smoke on the leanest, pre-crisis
year (2005) already gives **18 qualifying sp1500 events** (midsmall 9, sp500-PIT 5). With the 2008-09
and 2020 defensive-pill waves, train 9y ≈ 200–400 events and holdout ~12.8y ≈ 250–500 — ample for the
month clustering (~108 / ~154 month-clusters). Power is comfortable at the sp1500 level; the **sp500-PIT
and midsmall cuts are thinner** (5 and 9 in 2005) and may be underpowered on their own. The harness
computes the holdout pass chance from the chosen (`e0_sp1500_h15`) train t and **buries the idea without
spending the holdout if it is < 25%**. Adoptions declined after the 2010 Delaware ruling made pills
easier to remove, so holdout years outside the 2020 spike may be lean — the Skeptic should check the
month-cluster distribution is not carried by a single wave.

## Variants (6) — explicit, pre-registered
`CONFIGS` dict, name → (entry_mode, universe, hold). `chosen` is PRE-REGISTERED = `e0_sp1500_h15`
(the card's primary rule). The other five are a robustness map for the Skeptic and are NEVER carried to
the holdout.
- `e0_sp1500_h15` **(CHOSEN)** — all S&P 1500, day-0 close short, 15-session hold.
- `e0_sp1500_h10` — 10-session hold (is the drift front-loaded or does it run the full three weeks?).
- `e0_sp1500_h5` — 5-session hold (immediate continuation only?).
- `e0_midsmall_h15` — S&P 400+600 only (entrenchment/G-Index underperformance is stronger in smaller,
  less-covered names; also where more pills are adopted).
- `e0_sp500_h15` — S&P 500 only, PIT-filtered (large-cap; the most-arbitraged, weakest-expected).
- `e1_sp1500_h15` — enter the CLOSE after `first_session` (a session late). Direct test of how much the
  day-0 close entry matters; if `e1` ≈ `e0` the entry-timing fix is doing nothing.

Deliberately dropped (to keep the luck bar low): a "materiality" flag (short only if day-0 reaction < 0)
and a cross-filing dedup variant. The family's prior 3 screen variants are added to the luck bar
automatically.

## Costs
`cost_bps` 25 on top of the real close-spread floor. Hedged gross; the harness subtracts cost and
clusters by month. Borrow cost not modelled (noted above).

## What would kill it
- Chosen train t < 2.0 or mean ≤ 0 → dead with no holdout spent.
- Holdout pass chance < 25% (likely the binding constraint given the sparse event count) → buried
  without spending the holdout; would need a redesign for more power (e.g. a broader universe, which we
  do not have membership history for).
- Holdout t < 3.0 bar or mean ≤ 0 → dead.
- `e1 ≈ e0` → the day-0 close entry adds nothing (drift slower/later than claimed).

## Skeptic / risk notes
1. **Most of the move is priced by day-0 close.** Ryngaert's -150 bps is the full announcement CAR; we
   short at the close *after* that intraday drop, so we are betting only on the ~50–80 bps residual
   drift. If that residual ≤ cost, it dies at train. `e0` vs `e1` and the h5/h10/h15 horizon spread are
   the direct reads.
2. **Survivorship is mixed for this short.** sp400/sp600/'all' have no PIT list; the sp500 variant is
   PIT-clean. For a short, names that later fell out of the index by *declining* are absent (biases the
   result conservative), BUT a pill-adopter that was *acquired anyway* (negotiated deal, price jump up)
   also left the index and is absent — that direction biases a short result **too favourably**. Net
   effect ambiguous; prefer the PIT-clean `e0_sp500_h15` read and the recent-window holdout when judging
   realism, and treat a marginal `midsmall`/`sp1500` pass with caution.
3. **Text-filter precision.** The frozen PILL+ADOPT filter may include an occasional amendment phrased
   as "adopted an amended and restated rights plan", or miss an adoption described only as a "tax
   benefits preservation plan" with no "rights plan/agreement/poison pill" phrase. Contamination by
   non-adoption events dilutes the short edge → a holdout pass despite it is conservative; false
   negatives only cost power. The filter is frozen pre-registration; smoke shows counts only.
4. **Post-2010 decline + 2020 spike.** Event flow is lumpy and regime-dependent. Month clustering + the
   long holdout are the defence, but a pass driven mostly by the 2020 wave would be fragile — the
   Skeptic should check the month-cluster distribution.
5. **Borrow.** `real_hedged_bps` prices the spread, not borrow; small-cap pill adopters can be
   hard-to-borrow. Director confirms borrow availability/cost before real money.

## Promotability (paper)
**Promotable as a true day-0 SHORT test.** Day-0 paper trading is built (2026-11-14):
`tools/edgar_live.py` captures today's SEC filings + in-scope 8-K text (~12:40 PT) and
`paper_runner.run_day0` fires `signals()` before the close for `"entry_at": "same_close"` strategies.
`strategy.py` reads today's filings via `edgar_live.filings_asof(asof)` and their text via
`edgar_live.text_asof(asof)` (falling back to the archive text parts for the rare 8-K accepted after the
15:30 ET cutoff on the prior session whose entry_session is today), applies the SAME frozen regex, and
goes SHORT at today's close when an item-5.03 rights-plan-adoption entry_session is today. Metric
`real_hedged_bps` (real Webull bid/ask; the runner hedges vs SPY only — research is per-index, noted).
