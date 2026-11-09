# seo-short — pre-registered PLAN

## Hypothesis
When an already-public S&P 1500 company prices a **seasoned equity offering (SEO)** it files a **424B4** (final
prospectus) or **424B5** (shelf prospectus supplement) on EDGAR — the pricing-day disclosure. Issuing equity is
an adverse-selection signal (Myers-Majluf 1984): rational managers issue when they believe the stock is rich.
The stock drifts **down** after the offering.

## Mechanism / evidence
- Myers-Majluf (1984): equity issuance is a negative signal; price should fall around issuance.
- Loughran-Ritter (1997): SEO firms underperform ~-3% over the 5 trading days post-offering (gross); -15% / 3 yr.
- D'Mello-Ferris (2000): ~-2.5% (250 bps) three-day CAR around the SEO pricing.
- Spiess-Affleck-Graves (1995): -1.5% to -3% short-window return at SEO announcement.
- Gross edge targeted: ~150-300 bps over 3-5 trading days — well above the round-trip spread floor.
- **Who's on the other side:** index funds that must hold regardless; retail that doesn't read EDGAR
  prospectuses; longs betting the proceeds get deployed productively.

## Universe, signal, timing
- **Universe:** S&P 1500 (current members; survivorship caveat below). Cost-floor index set
  `["sp500","sp400","sp600"]`.
- **Signal:** SEC acceptance of a **424B4 or 424B5** for a ticker currently in the universe. The signal date is
  `first_session` (first open after SEC accepted the filing — never `filing_date`; an after-close prospectus
  can't be traded until the next open).
- **Entry (SHORT):** at the **CLOSE of the session AFTER `first_session`** (`entry_pos = pos+1`).
- **Exit (cover):** at the **CLOSE H sessions later** (H=3 primary).
- **Return:** SPY-**hedged**, SHORT, close→close GROSS bps `= spy_ret − stock_ret`; harness subtracts cost.
- **cluster:** week (multi-day hold). **metric:** hedged.

### Why one session late (central risk — flagged for the Skeptic + a kill condition)
The paper/live runner is a **once-daily after-close** job: a 424B reaches SEC's daily index (and our
`filings.parquet`) the next weekday, the strategy emits when `first_session == today`, and an after-close
dispatch can only fill the **next** close = `first_session+1`. So research enters `first_session+1` close to
match the paper rule exactly. But the academic drift is **front-loaded around the offering date**; entering ~2
sessions after pricing can eat most of the edge. **Kill signature:** the effect lives only at H=1-style immediacy
and the realized `first_session+1 → +3/+5` window is ~0. (We cannot enter earlier — the open round trip costs
~80-250 bps, far more than the whole edge, and the user's broker has no auction orders.) **CLOSE fills are forced.**

## Variants (12) and the pre-registered choice
form-set {`b4`=['424B4'], `b5`=['424B5'], `both`=['424B4','424B5']} × universe {`sp1500`=sp500+sp400+sp600,
`sp46`=sp400+sp600} × hold H {3, 5}. Names: `<form>_<univ>_h<H>`.
- **`chosen` is PRE-REGISTERED = `both_sp1500_h3`** — the idea card's primary rule: any 424B4/424B5, full
  S&P 1500, the ~3-day academic horizon. Deterministic, so `strategy.py` matches `chosen` exactly. The other 11
  are a robustness map for the Skeptic only and are **never** carried to the holdout.
- `max_variants = 12`; best-of-N luck t ≈ 2.23 (`sqrt(2 ln 12)`).
- Train picks nothing — chosen is fixed in advance. Train reports which variant *looked* best, for the Skeptic.

### Robustness reads (verdicts only, NOT a switch of `chosen`)
- **b4 vs b5.** 424B4 is also the IPO form, and we have **no point-in-time membership**, so a current member's
  *old IPO* 424B4 can leak in. 424B5 (shelf takedown) is almost never an IPO but is diluted by investment-grade
  **debt** shelves. If **b4 ≫ b5**, suspect IPO first-day contamination (IPO pops are positive → they *hurt* a
  short, so this would mean b4's negativity is something else). If both collapse, the blend is debt-diluted noise.
- **sp1500 vs sp46.** If sp1500 is flat but sp46 strong, it's a small/mid-cap effect (research verdict only;
  large-cap SEOs are better-absorbed). One shared cost floor (sp600 close) over-charges sp500 names → conservative.

## Costs
`cost_bps = 25` (close→close sp600 spread floor ~22 + small impact). The harness charges `max(25, real floor)`.
`real_hedged_bps` prices the **spread, not short borrow** — a real-money step needs a borrow check (NOTE in
strategy.py). `pass_mean_bps = 15` leaves borrow room.

## Windows (family `seo_offering` is brand-new — entire history clean)
- **Train:** 2001-01-01 .. 2015-12-31.
- **Holdout:** 2016-01-01 .. 2026-10-24 (most recent = the arbitraged era; the honest test of whether it still
  works. Daily ends 2026-11-06, buffering the close+5 exit.). Holdout evaluates **only `chosen`**, once.

## What would kill it
1. Chosen train t < 2.0 or mean ≤ 0 → dead before any holdout (harness auto-bury).
2. Holdout chosen t < `budget.py bar seo_offering` (floor 3.0) or mean ≤ 0 → dead.
3. The one-session-late window shows ~0 even when an immediate reaction existed → untradeable for this user.
4. b4 ≫ b5 with b5 ≈ 0 → the "signal" is IPO/debt contamination, not the SEO adverse-selection effect.

## Event counts (reported from the smoke run — the idea card's gate)
Idea card requires ≥ ~50 events/yr for power. Smoke (first train year, 2001) prints per-variant trade counts;
if `both_sp1500` is far below ~50 in year 1, power is marginal and that's noted for the Director. (See the
Researcher outbox / notes for the actual smoke counts.)

## Promotability
424B4/424B5 are same-day public; `filings.parquet` is rebuilt each dispatch, so `strategy.py` reads it live and
emits a short when a 424B's first tradable session is today. **PROMOTABLE** (with the borrow + IPO/debt caveats).
Reused the dead `pipe-short` skeleton (SEC-filing SHORT, close→close hedged), swapping the 8-K item-3.02 filter
for the 424B4/424B5 form filter and dropping the ex-event map.
