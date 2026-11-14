# material-impairment-short — pre-registered PLAN

## Hypothesis
When an S&P 1500 company announces a **material impairment** (goodwill or long-lived-asset writedown) it files an
**8-K item 2.06**. The writedown is an admission that a past acquisition/investment was overvalued and that
management has cut its expectations. The negative price reaction is **not fully priced on the announcement open**,
so the stock **drifts down** over the next 2-3 sessions. We **SHORT** to capture that continuation.

## Mechanism / evidence
- Analyst lag: the impairment *magnitude* is uncertain until sell-side re-models the firm; selling pressure
  builds over 1-2 days (Hirschey & Richardson 2003, TAR — CARs ~-100..-180 bps, analyst reaction lags 1-2 days).
- Co-arrival: 2.06 often lands with an earnings miss (item 2.02); the two reinforce but arrive with different
  delays (8-K same day vs sell-side next day). (Tested both ways — `noearn` variant.)
- Underreaction: retail/momentum holders react late (Li-Shroff-Venkataraman-Zhang 2011 — CARs ~-150 bps in
  [-1,+3], drift extends beyond day 0; Jarva 2009 — ~-120 bps over days 0-3).
- Gross edge targeted: ~100-150 bps SHORT over ~3 days — above the close->close round-trip spread floor.
- **Who's on the other side:** index funds that hold regardless; dip-buyers reading the writedown as "one-time /
  non-cash"; retail that doesn't read 8-Ks.

## Universe, signal, timing
- **Universe:** S&P 1500 (current members; survivorship caveat below). Cost-floor index set
  `["sp500","sp400","sp600"]`.
- **Signal:** SEC acceptance of an **8-K item 2.06** for a ticker in the universe.
- **Entry (SHORT) — day 0:** at the **CLOSE of `entry_session`** (the first session whose close can still be
  shorted after SEC accepted the 8-K — accepted before 15:30 ET that session, else the next session). This is the
  2026-11-13 audit fix: event tests that entered the close AFTER `first_session` bought a day late and lost the
  day-0 move. The drift we want is days **+1..+3 after** this close.
- **Exit (cover):** at the **CLOSE H sessions later** (H=3 primary).
- **Return:** **hedged** SHORT, close->close GROSS bps = `hedge_ret − stock_ret`, each trade hedged with **its own
  index fund** (SPY/IJH/IJR). Harness subtracts cost.
- **cluster:** week (multi-day hold). **metric:** hedged. **hold_days:** 5 (longest variant).

## Variants (9) and the pre-registered choice
Explicit `CONFIGS` dict `name -> (entry_mode, universe, hold, flag)` (no name parsing):
`e0` = `entry_session` close (day 0); `e1` = session after `first_session` close (paper-reachable, see below).
- **`chosen` is PRE-REGISTERED = `e0_sp1500_h3`** — the card's primary rule with the audit's day-0 entry.
  Deterministic, so the holdout runs exactly this. The other 8 are a robustness map for the Skeptic, never
  carried to the holdout.
- `max_variants = 9`; family `8k_2_06` already has **3** search variants booked (the free 8-K screen, LONG
  direction). The harness counts 9 + 3 = **12** for the luck bar → best-of-N luck t ≈ `sqrt(2 ln 12)` ≈ **2.23**.

### Robustness reads (verdicts only, NOT a switch of `chosen`)
- **e0 vs e1 — the central tradeability read.** `e1` enters one session after `first_session`, which is the
  earliest a once-daily **after-close** paper/live runner can fill (see Promotability). If `e1` ≈ 0 while `e0`
  is strong, the edge is **real but untradeable today** — it needs the intraday EDGAR feed built before it can
  be paper-traded. If `e0` is also flat, the whole drift is already priced by the day-0 close.
- **drop / noearn vs base.** `drop` shorts only impairments with a **negative day-0 reaction** (materiality
  proxy — the card's "is the signal only *large* impairments?"). `noearn` drops 2.06s **co-filed with item 2.02**
  (earnings), isolating the pure impairment from the earnings-miss confound (card risk #1: the gap may already
  price co-filed misses). If base needs `drop`/`noearn` to work, say which impairments carry the edge.
- **sp500 vs sp46.** Impairments skew large acquirers → `sp500` may hold the signal (and is the cheapest to
  trade); if only `sp46` works it's a small/mid-cap effect (research verdict only). One shared cost floor
  (sp600 close ~22) over-charges sp500 names → conservative for them.
- **h2/h3/h5 — horizon.** Is the drift immediate (h2) or does it run to h5?

## Survivorship
- **sp500 variant uses point-in-time membership** (`rd.pit_filter(events, "entry_session")`, required): ~280 of
  today's 503 members have pre-joining history that would otherwise leak in.
- **sp1500 / sp46 have no point-in-time list.** Current-membership bias here **helps a SHORT**: the worst
  impairments — firms wiped out badly enough to leave the index — are **absent entirely**, so the remaining
  sample is tilted toward milder impairments with smaller drift. A pass is therefore **conservative** on this
  axis (unlike a LONG study). Train is 2004-2013 and holdout 2014-2026; the bias cannot be removed without a
  CRSP/Norgate delisted-name set (paid, deferred until something is close).

## Costs
`cost_bps = 25` (close->close sp600 spread floor ~22 + small impact). The harness charges `max(25, real floor)`
for the plan's fill times/indexes. `real_hedged_bps` prices the **spread, not short borrow** — impairment names
can be beaten-down mid/small-caps, some hard-to-borrow, so a real-money step needs a **borrow check** (noted in
strategy.py); `pass_mean_bps = 15` leaves room.

## Windows (family `8k_2_06` — only the 2005-2013 LONG screen used so far; SHORT + holdout 2014-2026 clean)
- **Train:** 2004-09-01 .. 2013-12-31 (8-K item codes exist from 2004-08; overlaps the screen's search window,
  which is allowed for train — only the holdout must be unused).
- **Holdout:** 2014-01-01 .. 2026-10-24 (daily ends 2026-11-13, buffering the close+5 exit). Evaluates **only
  `chosen`**, once.
- **Power / events per year:** ~1,015 item-2.06 filings exist in the archive over 2004-08..2026-11 (~45/yr across
  the S&P 1500 universe; fewer per sub-index). Train ~9.3 yr ≈ ~300-350 events, holdout ~12.8 yr ≈ ~450-500.
  Expected holdout t = train t × √(holdout/train) ≈ train t × 1.17 against the 3.0 bar — ample if the edge holds;
  the harness buries it pre-holdout if the pass chance is < 25%.

## What would kill it
1. Chosen (`e0_sp1500_h3`) train t < 2.0 or mean ≤ 0 → dead before any holdout (harness auto-bury).
2. Holdout pass chance < 25% → buried without spending the holdout (redesign with more events).
3. Holdout chosen t < `budget.py bar 8k_2_06` (floor 3.0) or mean ≤ 0 → dead.
4. `e1` ≈ 0 even when `e0` works → real but untradeable until the intraday EDGAR feed exists.
5. Edge only survives with `noearn` removed (i.e. it's really the co-filed earnings miss, not the impairment).

## Promotability — READ BEFORE A PAPER TEST
The **chosen rule enters at the day-0 (`entry_session`) close.** A once-daily **after-close** dispatch (~2:51 PM
PT) only sees a 2.06 after it reaches SEC's daily index (next weekday), by which time `entry_session`'s close has
already passed — so the after-close paper runner **cannot replicate `chosen`**; the closest it can do is enter the
**next** close (= the `e1` timing). Per `research_data.entry_session`, trading the day-0 close needs an **intraday
EDGAR check (~12:45 PT) that is NOT built yet** — the Director requests it from the user's session **on a holdout
pass**. Until then this is a **research-only** candidate (same posture as insider / analyst-initiation). `strategy.py`
+ `spec.json` are provided for the record and emit the `e1` best-effort short (close entry, hold 3), but are marked
**DO NOT PROMOTE as-is** — the gate must not treat the `e1` paper rule as the `e0` chosen edge. If the `e1`
variant *also* clears train+holdout on its own, the Director may pre-register `e1` as a separate, tradeable-today
paper test. Reused the `seo-short` skeleton (SEC-filing SHORT, close->close hedged), swapping the 424B form filter
for the item-2.06 filter, adding the day-0 `entry_session` entry, per-index hedge, and the drop/noearn diagnostics.
