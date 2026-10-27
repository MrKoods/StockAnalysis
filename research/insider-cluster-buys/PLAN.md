# insider-cluster-buys — pre-registered plan

## Hypothesis
When **≥2 distinct corporate insiders** independently file open-market *purchases* of the same
stock inside a short window, the combined signal is more informative than any single buy, and the
market under-reacts because Form-4 filings arrive staggered across EDGAR. We go long and hold a few
days. (Seyhun 1998; Lakonishok & Lee 2001 — directors+officers together beat either alone.)

## Mechanism / who is on the other side
Independent convergence of insiders on buying is unlikely to be coincidence; each has a separate
private-information channel. Liquidity is supplied by retail and short-horizon institutional sellers
who do not aggregate the scattered filings in time.

## Universe
Current S&P 500 ∪ S&P 400 (mid/large cap, `rd.universe("sp500") | rd.universe("sp400")`), intersected
with names that have daily bars. **Known limitation (survivorship):** only *current* index membership
is available — no point-in-time constituents. For a long signal this biases returns **upward**
(survivors did better), so the holdout bar + Skeptic should treat a marginal result as suspect. Stated
here deliberately; it cannot be removed with the data we have.

## Signal (frozen)
- Non-derivative Form-4/4A rows with `TRANS_CODE == "P"` (open-market purchase, acquired code "A").
- `val = TRANS_SHARES × TRANS_PRICEPERSHARE`; a distinct insider = `RPTOWNERCIK`.
- **Cluster window = 5 calendar days measured by FILING_DATE, not transaction date.** A cluster is only
  tradable once its filings are *public*; using filing dates makes the trigger strictly leak-free (the
  idea card's "5-day transaction window" is implemented this way for no-look-ahead).
- For a filing date `fd`: sum each insider's purchases in `(fd−5d, fd]`; count insiders whose window
  total ≥ **$25k** (`MIN_PER_INSIDER`). Trigger when that count ≥ `N_INS` **and** the qualifying total
  ≥ `MIN_TOTAL`. One trigger per 5-day episode per ticker (dedupe: skip a fire within 5 days of the
  previous fire for that ticker), applied per variant.

## Entry / exit timing
Long at the **open of the first session strictly after `fd`** (never same-day — a filing can land any
time that day). Exit at the **close** `HOLD` trading sessions later (entry day = session 0, exit at the
close of session `HOLD−1`). Long only.

## Costs
`cost_bps = 20` round trip — conservative for a mix that includes S&P 400 mid-caps (idea card guessed
~15). The SPY hedge leg's cost is not separately charged (small, and it makes the net slightly
optimistic by <1 bp — noted). The harness subtracts cost; `test.py` returns **SPY-hedged gross bps**
(stock open→close return minus SPY open→close over the identical window), matching how the paper
runner computes `hedged_bps`.

## Statistics
`cluster = "week"` (multi-day holds). Cluster events are rare, so expect a modest number of
signal-weeks — a thin holdout is a real risk (idea risk #2). The holdout must clear the insider-family
bar `python tools/budget.py bar insider` = **3.0** (K=2, floor dominates).

## Variants tried (12) and the pre-registered choice
Grid: `N_INS ∈ {2,3}` × `HOLD ∈ {3,5,10}` × `MIN_TOTAL ∈ {$75k,$150k}`, with `MIN_PER_INSIDER = $25k`
fixed → 12 configs, named `n{N}_h{H}_m{K}k`.

**`chosen` is pre-registered, NOT best-of-train:** `chosen = n2_h5_m75k` — the canonical cluster
definition (≥2 insiders, ≥$25k each, ≥$75k total, 5-day hold) straight from the idea card and the
literature. The other 11 are reported in the train result **only** as a robustness/sensitivity map for
the Skeptic (does the sign survive tightening N_INS, raising the dollar bar, changing the hold?). They
are *not eligible* to become `chosen`. This keeps the holdout a single pre-registered hypothesis, so
the best-of-N luck penalty does not apply to the decision config.

## Windows (holdout never used by this family)
The insider family already spent its one holdout on **2018–2026** (v3-insider-buys, officer buys
≥$100k, t 2.3 near-miss). This test therefore uses a **clean, earlier** holdout:
- Train: **2006-01-01 → 2013-12-31** (insider data starts 2006).
- Holdout: **2014-01-01 → 2017-12-31** (no overlap with 2018–2026; the most recent window still free).

## What would kill it
- Holdout chosen-config t < 3.0, or non-positive mean net bps.
- Sign flips or evaporates across the robustness variants (fragile = luck).
- Skeptic finds look-ahead, survivorship inflation large enough to explain the edge, or too few
  signal-weeks to trust the t.

## Can this become a paper test? — BLOCKED (read before promoting)
The frozen rule is encoded in `strategies/insider-cluster-buys/` for the record, **but it should NOT be
promoted to a live paper test yet.** The only insider source the team has is SEC's **quarterly bulk**
Form-345 datasets, which publish months after the quarter. A 3–5-day-hold signal cannot be traded off
data that lags a quarter — the live strategy would almost never fire on time, so a paper run would be
invalid, not merely slow. Promotion requires a near-real-time Form-4 feed (e.g. EDGAR full-text/RSS
ingest) the team cannot add under current limits (no new paid services/keys). Until then this idea can
only deliver a **research verdict** (train → Skeptic → one holdout), which is itself worth having.
