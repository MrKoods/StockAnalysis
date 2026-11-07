# activist-13d-long -- pre-registered plan

## Hypothesis
When a hedge fund or activist crosses 5% ownership with intent to influence a company, it must file a Schedule
13D within 10 days. The filing is a public signal of activist intent (board seats, buyback, strategic review,
sale). Brav, Jiang, Thomas & Partnoy (2008) document a large positive abnormal return around the **initial**
13D with drift continuing ~20 days; Klein & Zur (2009) confirm large post-filing returns for hedge-fund targets.
We go **LONG the target** over a few days, SPY-hedged, and test whether a tradable residual drift survives costs
in the post-publication (arbitraged) era.

## Mechanism / who is on the other side
Passive/index holders who must hold the target regardless, and retail/news-driven investors who learn of the
activist days later. Drift continues as other activists pile in ("wolf pack"), merger-arb funds enter on
acquisition odds, and management pre-emptively concedes to forestall a proxy fight.

## Data
- `rd.filings(forms=["SC 13D"], tickers=sp1500)` -> schedule 13D filings. EDGAR indexes a schedule under its
  **subject** company, so the universe ticker returned is the **target** of the activist (not the filer). This
  is confirmed by SC 13G being in the catalog's most-common forms, indexed by our universe tickers. We keep the
  **raw** form `== "SC 13D"` to drop SC 13D/A amendments (initial filings only).
- `rd.daily(...)` close-to-close returns + SPY for the hedge.
- Family `activist_13d` -- brand new, whole history clean (no prior screen or researcher use).

## Exact rules
- Universe: S&P 1500 (sp500 + sp400 + sp600 current members).
- Signal: SEC acceptance of an initial SC 13D for a universe (target) company. Signal date = `first_session`
  (first session whose 09:30 open is after SEC acceptance) -- never the filing timestamp.
- Entry: BUY at the CLOSE of the session **after** `first_session` (first_session+1). This is the earliest
  close a once-daily, after-the-close runner could actually fill: the runner fires post-close and the SEC daily
  index reaches our archive the next weekday, so same-day-close entry is impossible to trade. We therefore give
  up the first public-reaction session on purpose.
- Exit: SELL at the CLOSE H sessions later (H = hold).
- Return: SPY-hedged, LONG, close-to-close gross bps = (stock_ret - spy_ret) * 1e4; harness subtracts cost.
- `cluster`: week (multi-day holds overlap).

## Costs
`entry_at`/`exit_at` = close; universe spans sp500/sp400/sp600, so the harness charges the **most expensive**
index's close->close spread = sp600 ~21.8 bps round trip as a floor. `cost_bps` = 25 (floor + ~3 bps impact for
thinner small-cap targets); charged = 25. CONSERVATIVE BIAS: the one shared floor over-charges the sp500-only
variant (real sp500 close round trip ~6.6 bps). That penalizes sp500-only against sp1500 -- a bias AGAINST a
sp500 result, so a sp500 pass would be conservative. Flagged for the Skeptic.

## Variants and selection
6 variants: universe {sp1500, sp500} x hold {1, 3, 5}. **chosen is PRE-REGISTERED = `sp1500_h3`** (the full
activist universe -- activists often target small/mid caps -- and the evidence's few-day drift horizon). The
other five are a robustness map for the Skeptic only and never go to the holdout. Best-of-6 luck t ~= 1.89
(sqrt(2 ln 6)); the holdout bar from `tools/budget.py` dominates anyway.

## Windows
- Train: 2001-01-01 .. 2015-12-31 (EDGAR schedule coverage is dense from the early 2000s).
- Holdout: 2016-01-01 .. 2026-10-24 (the most recent, most-arbitraged years = the toughest, most relevant test;
  daily ends 2026-11-02, leaving a buffer for a hold-5 close exit; holdout never used before for this family).

## What would kill it
- Chosen train t < 2.0 or mean <= 0 after cost (auto-dead, no holdout spent).
- Holdout t below `tools/budget.py bar activist_13d` or mean <= 0.
- Entering one session late (first_session+1) erases the edge -- the central risk: if Brav's abnormal return is
  front-loaded into the announcement session, the residual we can actually trade may be near zero. If the hold-1
  variant is much weaker than hold-3/5 in train, that is the signature of a front-loaded, already-gone move.
- Post-publication decay: real-time 13D monitors may have compressed the window to the announcement bar.
- Survivorship: only current S&P 1500 members (no point-in-time membership, no delisted names). Biases a LONG
  result UP; flagged. A pass is NOT conservative on this axis -- the Skeptic should weight it.

## Promotability
SC 13D filings are public same-day and `data/edgar/filings.parquet` is rebuilt every dispatcher run, so the
rule can trade live. The strategy emits on the day an initial 13D's first tradable session is TODAY; the runner
enters the next session's close (= first_session+1 close) and exits 3 sessions later. metric `real_hedged_bps`,
pass_mean_bps 15 / pass_t 2.0, 20-40 trading days. Initial 13Ds in S&P-1500 names are uncommon, so the 20-day
window may take months (flagged for the Director). LONG side -> no borrow caveat.
