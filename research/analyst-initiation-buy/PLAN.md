# analyst-initiation-buy — pre-registered PLAN

## Hypothesis
When a sell-side analyst **initiates** coverage with a bullish rating (Buy / Outperform /
Overweight / Positive / Accumulate), it creates genuinely new institutional demand: many funds
cannot hold a name until it is covered ("initiation clears the gating requirement"), and the
initiation puts the stock on PMs' screens for the first time. The new buyers *are* the trigger, so
the demand surge cannot be instantly arbitraged. Effect is strongest where coverage is sparse —
small/mid caps. Womack (1996 JF): +3% 1-month drift on Buy initiations; Barber et al. (2001),
Bradley et al. (2003): +2.5% 1-day for small caps, stronger than later upgrades/downgrades.

An initiation is a distinct event from the generic upgrade/downgrade actions that the old V3
"analyst rating actions" work (graveyard) tested and failed: those were re-ratings of *existing*
coverage (opinion change), not new coverage (new gated demand). The `analyst_ratings` family is
completely clean in this team framework (no prior search or holdout — data_catalog.md).

## Mechanism / who is on the other side
The initiating broker is recommending, not selling. The stock typically has no large institutional
covering position to absorb the demand. Sellers are earlier holders who get the pop but were not
positioned around the event.

## Data & signal
- `rd.ratings(tickers)` — yfinance upgrades/downgrades, 2012-09-12 .. 2026-10-20. Columns include
  `GradeDate`, `Firm`, `Action`, `ToGrade`, `FromGrade`. **Verified**: `Action == "init"` is the
  initiation action type (V3 `events.load_ratings` relies on it). Bullish = `ToGrade` (lowercased)
  contains one of: buy, outperform, overweight, positive, accumulate, conviction.
- `rd.daily(tickers)` — split/div-adjusted OHLCV for entry/exit pricing + SPY for the hedge.
- Signal date = `GradeDate` (a **date only** — yfinance gives no intraday time). We therefore enter
  at the OPEN of the **first session strictly after** `GradeDate`, which is leak-free regardless of
  what time of day the rating was published. This is the idea card's "buy at open the day after".

## Rules (exact)
- Universe: S&P 600 (small cap) and S&P 46 = S&P 400+600 (small+mid). Large caps (S&P 500) excluded
  — dense coverage, weakest mechanism, would dilute.
- For each (ticker, GradeDate) with `Action=="init"` and a bullish `ToGrade`: LONG at the OPEN of
  the first session with date > GradeDate; exit at the CLOSE H sessions later.
- Returns are **SPY-hedged GROSS bps**: (stock open→close) − (SPY open→close) over the same window.
  The harness subtracts `cost_bps`.
- Bad-bar guard: drop any trade with |stock open→close| > 50% (unadjusted/erroneous bar).
- De-dup to one trade per (ticker, GradeDate).

## Variants (6) and the pre-registered choice
`universe ∈ {sp600, sp46}` × `hold H ∈ {1, 3, 5}` = 6 configs.
- **`chosen` is PRE-REGISTERED = `sp600_h3`** — smallest caps = strongest form of the gating
  mechanism; 3-day hold matches the idea card horizon and the Barber/Bradley 1–3-day window (we
  enter a day late, so we target the post-announcement drift, not the announcement-day pop). This
  is fixed before any result is seen; it is NOT the best-of-train. The other 5 configs are a
  robustness map for the Skeptic only and are never carried to the holdout.
- Keeping chosen deterministic (not best-t) keeps the holdout a single hypothesis so the luck bar
  stays at the family floor.

## Windows
- Train: **2012-09-12 .. 2019-12-31** (first full ratings history through pre-COVID).
- Holdout: **2020-01-01 .. 2026-10-15** (most recent, untouched; the honest hard test — includes
  the COVID regime and the modern fast-coverage era). `analyst_ratings` has used neither period.
- Daily ends 2026-11-02 and ratings 2026-10-20, so holdout_end 2026-10-15 leaves buffer for the
  3–5-session exit; trades whose exit falls past the cutoff are simply dropped (no leak).

## Costs
`cost_bps = 25` round trip — conservative for S&P 600 small caps on open/close fills (not
auction-only). Applied uniformly to all variants; the sp46 blend (some midcaps) is held to the same
higher bar deliberately.

## Clustering
`week` — chosen is a 3-day hold and busy initiation days create overlapping multi-day trades;
weekly clustering absorbs that cross-trade correlation.

## What would kill it
- Holdout `t` on `sp600_h3` below the family bar (`python tools/budget.py bar analyst_ratings`,
  ≥ 3.0) or non-positive mean bps → dead.
- Train sample too thin to be meaningful (yfinance small-cap rating history is sparse pre-2016) —
  reported but does not change the pre-registered chosen; the holdout (2020+, data-rich) is the gate.

## Known biases (for the Skeptic)
- **Survivorship**: the universe is *today's* S&P 600/400 membership (no point-in-time). A long
  signal is biased UP by this — flagged. Same limitation as all team research.
- **Underwriter conflict**: banks often initiate on names they underwrote (IPO/secondary) as deal
  promotion, not genuine signal — a source of upward bias we cannot filter here.
- **Coarse timestamp**: GradeDate is date-only; the next-session-open entry is the conservative,
  leak-free reading but discards any same-day residual.

## Promotability
**NOT promotable as-is.** The `ratings()` archive is a one-time yfinance snapshot (files last
fetched ~2026-10-23; `events_fetch.py` skips tickers whose file already exists) and yfinance
upgrades/downgrades is itself delayed/incomplete — there is no near-real-time, point-in-time rating
feed. `strategy.py` + `spec.json` encode the frozen rule for the record and will run if a fresh feed
is ever wired in, but the Director should NOT promote this to a paper test until that exists (same
blocker as the insider family). Noted here so the gate decision is explicit.
