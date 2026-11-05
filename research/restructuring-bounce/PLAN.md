# restructuring-bounce — PLAN (pre-registered)

## Hypothesis
When a company files an 8-K disclosing **exit or restructuring costs** (item **2.05**), the headline
is a large one-time charge and the immediate reaction is negative — momentum/news algos and
headline-reading holders sell the charge as ongoing bad news. But a restructuring charge is a
"kitchen-sink" / big-bath signal: management clears accumulated losses in one go and resets the
earnings baseline toward a leaner cost structure. The forward-looking implication (cleaner future
earnings) is under-weighted at announcement, so the price **partially recovers over the next few
sessions**. We go **LONG** the filer, entering AFTER the first reaction has played out, and exit a
few sessions later. The effect is predicted to be sharpest for **small-caps** (sparse coverage →
larger initial overreaction, slower correction).

## Mechanism / who is on the other side
Sellers who react to the negative charge headline without recognising the cleansing signal;
momentum algos that extrapolate the first-day drop. The recovery is the market re-pricing the
forward earnings baseline once the one-time nature of the charge is digested.

## Prior evidence
- Team event screen (state/screen.md, 2005–2013, FULL S&P 1500): **2.05 is the 5th-strongest 8-K at
  3d: +31.6 bps excess, t 1.79, 940 events**; +11.6 bps after 20 bps costs. Best-of-57 luck t ~2.84,
  so the full-universe signal is NOT established — this idea sharpens it by (a) restricting to
  small/mid-cap where the mechanism predicts a bigger/slower move and (b) **delaying entry one extra
  session** (open+2 rather than open+1) to let the first-day overreaction finish before buying the
  recovery drift.
- Kinney & Trezevant (1997) JAAF; Elliott & Shaw (1988) TAR ("big bath"); Cascio (2002): large special
  charges / restructurings are followed by positive abnormal returns and profitability recovery the
  market discounts too aggressively at announcement.

## Universe
Current S&P 600 (small) and S&P 400 (mid) membership (`rd.universe('sp600'/'sp400')`).
**Survivorship caveat (for the Skeptic):** only *today's* membership is available — no point-in-time
index. A long event signal is biased UP by this (failed/delisted small caps are dropped). Flagged; not
fixable with the available data.

## Signal, timing, costs (leak-free)
- Event: an 8-K whose item list contains **2.05**, filed by a universe ticker.
  `rd.filings(forms=['8-K'], items=['2.05'], tickers=<universe>)`.
- `first_session` = rd's first session whose 09:30 ET open is strictly after SEC acceptance (an
  after-close filing → next open). This is open+1 from the event — the earliest tradable session.
- **Entry:** OPEN of the session AFTER `first_session` (= **open+2** from the event). Entering at
  open+1 is too close to the initial reaction; open+2 buys the start of the recovery drift.
  entry_pos = first_session_pos + 1.
- **Exit:** OPEN of the session `H` later (exit_pos = entry_pos + H). For the chosen H=3 that is
  **open+5** from the event. Open-to-open on both legs → both fills are market-on-open auctions.
- **SPY-hedged** long: `gross = (O_exit/O_entry − 1) − (SPY_open_exit/SPY_open_entry − 1)` in bps.
  The harness subtracts `cost_bps`. Dedup to one trade per (ticker, first_session). Drop bars with
  |stock move| > 50% (bad-bar / unadjusted-data guard).
- **cost_bps = 35** — realistic small-cap round trip with BOTH legs at the open auction (idea est.
  30–35 small, 20–25 mid). One cost is applied to every variant; it is conservative for the mid-cap
  (S&P 400+600) variant, which is the safe side.
- **cluster = "week"** — the hold is 3–5 sessions (multi-day), so weekly clustering (TEAM.md default
  for swing holds) is the honest unit; restructuring filings also cluster, so same-week events are
  not independent.

## Variants (4) and why
Grid = universe {S&P 600, S&P 400+600} × hold H {3, 5}. All SPY-hedged long, entry open+2.
- Universe axis tests the core monotonicity (smaller cap → bigger/slower recovery).
- Hold axis: 3 sessions is the idea's primary horizon (open+2→open+5, the screen's 3d window); 5
  checks persistence of the drift.
Only 4 variants (luck t ~1.67) and `chosen` is **pre-registered**, not best-of-train, so the holdout
tests a single hypothesis against the family bar (≥ 3.00).

## chosen (PRE-REGISTERED, matches strategy.py exactly)
**`sp600_h3`** — S&P 600 only, hold 3 sessions (open+2 entry → open+5 exit). Smallest-cap = strongest
form of the hypothesis; H=3 = the screen's 3d horizon where 2.05 showed its edge. The other 3 configs
are reported for the Skeptic as a robustness map and are NEVER carried to the holdout.

## Windows
- Family `8k_2_05` has used only **search 2005–2013** (the event screen). 8-K item codes exist from 2004-08.
- **Train 2005-01-01 .. 2013-12-31** (refine within the screen's search period — allowed; not holdout).
- **Holdout 2014-01-01 .. 2026-10-28** — never touched by this family (most-recent = hardest/most
  arbitraged era, the honest test). Daily ends 2026-11-02; a buffer leaves room for the open+5 exit.

## What would kill it
- Holdout `sp600_h3` net t < **3.00** (family bar) or mean ≤ 0 → DEAD.
- Risks the Skeptic should weigh: (1) full-universe screen t (1.79) was well below its own luck bar
  (2.84) — the small-cap + delayed-entry sharpening may not rescue it; (2) **power** — 2.05 is rare
  (2,097 filings across the full S&P 1500 since 2004); the small-cap subset may give too few weekly
  periods for a stable t, especially in the sp600-only chosen variant — the Skeptic should check the
  period count; (3) 2.05 filings cluster in downturns (2008–09, 2020) where small-cap vol is extreme,
  inflating SE — week-clustering partly addresses this; (4) many 2.05 filings piggyback on 2.02
  earnings — the move may be an earnings-surprise effect, not the restructuring signal (this is an
  "any filing containing 2.05" test); (5) thin edge vs 35 bps costs on two open-auction fills.

## Promotability
2.05 8-Ks are public the same day and `data/edgar/filings.parquet` (rebuilt by tools/edgar.py every
dispatcher run) carries the exact acceptance time → this CAN be traded live. strategy.py encodes
exactly `sp600_h3` (signal on `first_session`, so the once-daily runner enters at the next open =
open+2, exits at the open 3 sessions later), judged at real Webull quotes (`real_hedged_bps`).
**Power caveat:** 2.05 is rare in the S&P 600, so a 20–40 trading-day paper window may take many
months to fill — the Director should expect a slow paper test.
