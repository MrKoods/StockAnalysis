# activist-13d-long-day0 -- pre-registered plan

## Hypothesis
An activist/hedge fund crossing 5% ownership with intent to influence must file a Schedule 13D (renamed
"SCHEDULE 13D" by SEC in late 2024). Brav, Jiang, Thomas & Partnoy (2008) and Klein & Zur (2009) document a
large positive abnormal return around the **initial** 13D with drift continuing ~20 days. We go **LONG the
target**, hedged, holding a few days.

## Why this is a NEW idea in a dead family (the audit's day-0 re-proposal)
`activist-13d-long` DIED at train (t 0.17, +2.4 bps after cost). The 2026-11-13 audit decomposed event returns:
the **13D day-0 move is +51 bps t 5.6**, and ~nothing is left after it. The dead idea entered one session too
late -- at the CLOSE **after** `first_session` -- so its first held session was already day +1, skipping the
day-0 drift. This re-test changes **exactly one thing**: it enters at the **CLOSE of `entry_session`** (day 0 --
the first session whose close is still buyable after SEC accepted the filing). The first held session is then the
day-0 drift the late entry missed. Windows, cost, week cluster and universe are kept identical to the dead idea so
the two are directly comparable; the family's prior 6 variants are added to the luck bar by the harness. The
holdout 2016-2026 was **never spent** (the dead idea auto-died at train).

Interpretation guard for the Skeptic/Director: the +51/t 5.6 is a **raw, un-hedged, un-clustered** full-sample
decomposition. This test hedges each trade with its own index fund, charges the sp600 close spread as a floor,
and clusters by week -- so the train t will be far below 5.6 even if the effect is entirely real. Judge it against
the holdout bar, not against 5.6.

## Mechanism / who is on the other side
Passive/index holders who must hold the target regardless, and retail/news-driven investors who learn of the
activist days later. Drift continues as other activists pile in ("wolf pack"), merger-arb funds enter on
acquisition odds, and management pre-emptively concedes to forestall a proxy fight.

## Data
- `rd.filings(forms=["SC 13D"], tickers=sp1500)` -> Schedule 13D filings; EDGAR indexes the schedule under its
  **subject** (target) company, so the universe ticker returned is the activist's target. Keep
  `rd.form_std(form) == "SC 13D"` for **initial** filings only: form_std maps the post-2024 `SCHEDULE 13D` back
  to `SC 13D` (and `.../A` to `SC 13D/A`), so this keeps initial filings across the rename and drops `/A`
  amendments. (The DEAD idea filtered the raw form `== "SC 13D"` and so missed every post-2024 initial 13D --
  TEAM.md. This test fixes that.)
- Signal dates: `entry_session` (day-0 close, the chosen rule) and `first_session` (for the e1 late-entry read).
- `rd.daily(...)` close-to-close; `rd.index_of` + `rd.hedge_ticker` for the per-index hedge (SPY/IJH/IJR).
- Family `activist_13d`: train 2001-2015 already used by the dead idea; **holdout 2016-2026 is clean**.

## Exact rules (chosen = e0_sp1500_h3)
- Universe: S&P 1500 (current sp500 + sp400 + sp600 members).
- Signal: SEC acceptance of an initial Schedule 13D for a universe (target) company.
- Entry: BUY at the **CLOSE of `entry_session`** (day 0 -- SEC accepted the filing before 15:30 ET that session).
- Exit: SELL at the CLOSE 3 sessions later.
- Return: hedged LONG close->close gross bps = (stock_ret - own-index-fund_ret) * 1e4; harness subtracts cost.
- `cluster`: week (holds up to 5 overlap within a week).

## Costs
`entry_at`/`exit_at` = close; universe spans sp500/sp400/sp600, so the harness charges the **most expensive**
index's close->close spread (sp600 ~21.8 bps RT) as a floor. `cost_bps` = 25 (floor + ~3 bps impact for thinner
small-cap targets). CONSERVATIVE BIAS: the single floor over-charges the sp500-only variant (true sp500 close RT
~6.6 bps), biasing **against** the sp500 read -- flagged for the Skeptic.

## Variants and selection (5)
`e0`=entry_session close (day 0); `e1`=session after first_session close (the dead idea / what an after-close
runner fills without the live feed). universe {sp1500, sp500}; hold {1,3,5}.
- `e0_sp1500_h3` -- **CHOSEN** (card primary horizon, day-0 entry).
- `e0_sp1500_h1` -- pure day-0 drift (the single first held session). If h1 >> h3/h5, the edge is one day.
- `e0_sp1500_h5` -- horizon out to 5 days.
- `e0_sp500_h3` -- large-cap only (point-in-time membership via `rd.pit_filter`).
- `e1_sp1500_h3` -- late entry; should **reproduce the dead idea's ~0**. e0 vs e1 is the audit's whole claim.
Chosen is **pre-registered** (not best-of-N), so the best-of-5 luck t (~1.79) does not gate it; the holdout bar
from `tools/budget.py` (3.0) dominates. hold_days = 5 -> week clustering is allowed (no month rule).

## Windows
- Train: 2001-01-01 .. 2015-12-31 (dense EDGAR schedule coverage from the early 2000s; reused from the dead idea).
- Holdout: 2016-01-01 .. 2026-10-24 (most recent, most-arbitraged years; clean for this family; daily ends
  ~2026-11-13, leaving a buffer for a hold-5 close exit).

## Expected events / power
Initial 13Ds on S&P-1500 names: ~100-250/yr (activists skew to mid/large caps in-index). Train ~1,500-3,750
events; holdout ~1,000-2,500. Holdout is ~0.86x the train length, so expected holdout t = train t x sqrt(0.86);
to clear the bar at >=25% power the chosen train t needs to be ~3+. If the day-0 effect is real and large this is
plausible; if the "+51" is intraday-only (priced by the close we buy at), even the day-0-close entry sees ~0 and
the harness buries the idea without spending the holdout. That is the honest central risk below.

## What would kill it
- Chosen train t < 2.0 or mean <= 0 after cost (auto-dead, no holdout spent).
- Holdout power < 25% (buried without spending the holdout) or holdout t below the bar / mean <= 0.
- **Central risk**: the +51 bps day-0 move may be priced INTO the entry_session close itself (it happened during
  the session, before the close we buy at). Then even a day-0-close entry captures only the residual *next-day*
  drift -- which may be the same ~0 the dead idea found. e0_h1 vs e1_h3 is the direct test: if e0_h1 is also ~0,
  the premium is intraday and untradeable at any close.
- Survivorship: sp1500 uses today's membership (no PIT list for sp400/sp600); biases a LONG result **up**. The
  sp500 variant uses `rd.pit_filter` (unbiased). Flagged -- a non-PIT pass is not conservative on this axis.

## Promotability (day-0 paper IS now built)
The chosen e0 rule is tradeable: day-0 paper trading was built 2026-11-14 (`tools/edgar_live.py` captures today's
filings ~12:40 PT with a 15:30 ET cutoff; `paper_runner.run_day0` places `entry_at: "same_close"` buys for the
day's close before the 12:56 Quote Clerk). `strategy.py` emits a signal when an initial 13D's `entry_session` is
today and buys at today's close, exits 3 sessions later. Metric `real_hedged_bps`, pass_mean_bps 15 / pass_t 2.0,
20-40 trading days.
- **Hedge mismatch (note, not a blocker)**: research hedges per-index (SPY/IJH/IJR); the paper runner hedges
  `real_hedged_bps` vs **SPY only** (fixed infra). For in-index activist targets this is usually close; the
  Director weighs it before any real-money step. Same gap applies to every event strategy here.
- Initial 13Ds in S&P-1500 are ~0.4-1/day, so 20 scored trades may take ~1-2 months (flagged for the Director).
- LONG side -> no borrow caveat.
