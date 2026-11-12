# proxy-contest-long -- pre-registered plan

## Hypothesis
When an activist escalates a campaign to a **contested** director election or shareholder proposal, the
dissident files proxy soliciting material with the SEC: first **DFAN14A** (non-management additional soliciting
material -- the opening public shot) and, if it goes to a vote, **DEFC14A** (the dissident's definitive contested
proxy statement). Fos (2017, SSRN 1705707) finds targets earn an average cumulative abnormal return of ~6.5%
around proxy-contest announcements. For S&P 400/600 (mid/small-cap) names the DFAN14A often **is** the first
public disclosure -- the contest does not pre-leak to Bloomberg/WSJ the way large-cap fights do -- so a tradable
residual of the control-premium / governance catalyst may remain in the days after the filing. We go **LONG the
target**, SPY-hedged, for a few days, and test whether that residual survives costs in the arbitraged era.

## Mechanism / who is on the other side
Index/passive holders who must hold the target regardless, and retail/news-driven investors who learn of the
contest days later. Drift continues as merger-arb and event funds enter on sale/settlement odds and as management
concedes (board seats, buyback, strategic review) to forestall the vote. The edge, if real, is the market being
slow to price the governance/control catalyst for small names where the filing is the first signal.

## Data
- `rd.filings(forms=["DFAN14A"])` / `["DEFC14A"]`, `tickers=sp1500` -> proxy soliciting material. EDGAR indexes
  14A soliciting material under the **subject** company, so the universe ticker returned is the **target** of
  the contest (same subject-company indexing confirmed for SC 13D). We keep the **exact** form string to drop
  any `/A` amendments. **Researcher-verify risk** (flagged in the idea note, same as activist-13d/self-tender):
  DFAN14A is not in the catalog's top-12 forms, so the smoke count is the test that `filings()` actually returns
  it for our universe. If the smoke count is ~0, the subject-company indexing does not extend to 14A material and
  the idea dies at data (noted for the Director).
- **Campaign dedup**: a dissident files MANY DFAN14A pieces per contest. An event is only the FIRST filing of a
  campaign per ticker -- a filing counts only if the same ticker had no prior filing of that form in the
  preceding 90 calendar days (sliding window). This isolates the campaign-opening disclosure and prevents
  entering the same contest a dozen times.
- `rd.daily(...)` close-to-close returns + SPY for the hedge.
- Family `proxy_contest` -- brand new, whole history clean (no prior screen or researcher use).

## Exact rules
- Universe: S&P 1500 (sp500 + sp400 + sp600 **current** members).
- Signal: SEC acceptance of a campaign-opening DFAN14A (or DEFC14A) for a universe (target) company. Signal date
  = `first_session` (first session whose 09:30 open is after SEC acceptance) -- never the raw filing timestamp.
- Entry: BUY at the CLOSE of the session **after** `first_session` (first_session+1). This is the earliest close
  a once-daily, after-the-close runner could actually fill (runner fires post-close; the SEC daily index reaches
  our archive the next weekday). We give up the first public-reaction session on purpose.
- Exit: SELL at the CLOSE H sessions later (H = hold).
- Return: SPY-hedged, LONG, close-to-close gross bps = (stock_ret - spy_ret) * 1e4; the harness subtracts cost.
- `cluster`: week (multi-day holds overlap).
- **Earnings-contamination filter NOT applied** (the idea card listed it). Deliberately omitted: it adds a
  second live-data dependency and a look-ahead surface to the frozen rule, and earnings jumps around a contest
  are roughly symmetric noise that the SPY hedge does not remove -- they RAISE variance, not the mean, so
  omitting the filter makes the t-test *harder* to pass (conservative). It could be a future variant if the base
  rule passes.

## Costs
`entry_at`/`exit_at` = close; the plan universe spans sp500/sp400/sp600, so the harness charges the
**most-expensive** index's close->close spread = sp600 ~21.8 bps round trip as a floor. `cost_bps` = 25 (floor +
~3 bps impact for thinner small-cap targets); charged = 25. CONSERVATIVE BIAS: the one shared floor over-charges
the `sp1500` variant (which includes sp500 names whose real close round trip is ~6.6 bps). That penalizes the
large-cap-inclusive variant against the chosen sp46 -- a bias that cannot manufacture an sp46 edge.

## Variants and selection
12 variants: form {DFAN14A, DEFC14A} x universe {sp46 = sp400+sp600, sp1500} x hold {1, 3, 5}.
**chosen is PRE-REGISTERED = `dfan_sp46_h3`**: the earliest contest signal, the mid/small-cap universe the
mechanism actually predicts (the filing IS the announcement there), and the evidence's few-day drift horizon.
The other eleven are a robustness map for the Skeptic only and never go to the holdout. Best-of-12 luck t ~=
2.23 (sqrt(2 ln 12)); the holdout bar from `tools/budget.py bar proxy_contest` dominates anyway.
**SC 14N excluded**: Rule 14a-11 shareholder nominations were vacated in 2011 (Business Roundtable v. SEC); the
form is essentially unused, so it would add an empty variant and raise the luck bar for no signal.

Robustness reads (verdicts for the Skeptic, NOT switches): hold-1 << hold-3/5 would be the signature of a
front-loaded move already gone by our one-session-late entry; sp1500 >> sp46 would contradict the "small caps
don't pre-leak" mechanism (and point to a large-cap effect we can't explain); defc >> dfan would say the edge is
at the definitive-proxy stage, not the opening disclosure.

## Windows
- Train: 2001-01-01 .. 2015-12-31 (EDGAR electronic proxy-material coverage is dense from the early 2000s).
- Holdout: 2016-01-01 .. 2026-10-24 (the most recent, most-arbitraged years = the toughest, most relevant test;
  daily ends 2026-11-06, leaving a buffer for a hold-5 close exit; holdout never used before for this family).

## What would kill it
- Chosen train t < 2.0 or mean <= 0 after cost (auto-dead, no holdout spent).
- Holdout t below `tools/budget.py bar proxy_contest` or mean <= 0.
- Smoke DFAN14A count ~0 -> `filings()` does not return 14A material for our universe -> dead at data.
- Entering one session late (first_session+1) erases the edge (hold-1 << hold-3/5 in train = front-loaded, gone).
- Small/mid-cap-only LONG is the exact inversion that killed reg-fd/analyst-init/restructuring and activist-13d
  (negative or flat train t). This is the central prior-failure risk; the sp1500 variant maps whether large caps
  behave differently.
- Survivorship: only current S&P 1500 members (no point-in-time membership, no delisted targets). Biases a LONG
  result UP -- a pass is NOT conservative on this axis; flagged for the Skeptic.

## Promotability
DFAN14A/DEFC14A filings are public same-day and `data/edgar/filings.parquet` is rebuilt every dispatcher run, so
the rule can trade live. The strategy emits on the day a campaign-opening DFAN14A's first tradable session is
TODAY; the runner enters the next session's close (= first_session+1 close) and exits 3 sessions later. metric
`real_hedged_bps`, pass_mean_bps 15 / pass_t 2.0, 20-40 trading days. Campaign-opening DFAN14As in S&P-1500 names
are uncommon (~20-25/yr across sp46 per the idea card), so the 20-day window may take several months (flagged for
the Director). LONG side -> no borrow caveat.
