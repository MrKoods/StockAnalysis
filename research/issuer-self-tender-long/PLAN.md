# issuer-self-tender-long — pre-registered PLAN

## Hypothesis
When an S&P 1500 company launches a **self-tender offer** (offers to repurchase its own shares at a premium to
market) it files SEC Form **SC TO-I** (Issuer Tender Offer Statement). This is a hard, time-limited
undervaluation signal: management commits to buy a specific number of shares at a specific premium within a
defined tender window. Unlike an open-market buyback (gradual, deniable), the tender is a firm commitment and
creates a near-term **price floor** (no holder tenders below the offer price). The stock drifts **up** in the
days after the filing as arbitrageurs and institutions buy into the floor.

## Mechanism / evidence
- Peyer & Vermaelen (2009), *RFS*: ~+200 bps cumulative abnormal return over the first 3–5 days at tender-offer
  repurchase announcements; undervaluation signal + premium-driven price floor.
- Lie (2005), *J. Acc. & Econ.*: tender-offer repurchases show a materially stronger short-term price reaction
  than open-market repurchases — the commitment mechanism drives the response.
- The floor is **mechanical, not behavioural** (it exists while the offer is open) and is not easily arbitraged
  away, so the effect is expected to be more durable than a pure sentiment anomaly.
- **Who's on the other side:** passive holders who don't monitor filings in real time; retail that doesn't read
  EDGAR; short-sellers forced to cover into the floor.

## Universe, signal, timing
- **Universe:** S&P 1500 (current members; survivorship caveat below). Cost-floor index set
  `["sp500","sp400","sp600"]`.
- **Signal:** SEC acceptance of an **initial SC TO-I** for a ticker currently in the universe. For SC TO-I the
  **filer IS the issuer** (the company buying its own shares), so `filings(tickers=sp1500)` returns the right
  names directly (unlike SC 13D, which is indexed under the subject). We keep **raw form == "SC TO-I"** only,
  dropping `SC TO-I/A` amendments (the initial launch is the event). Signal date is `first_session` (first open
  after SEC accepted the filing — never `filing_date`).
- **Entry (LONG):** at the **CLOSE of the session AFTER `first_session`** (`entry_pos = pos+1`).
- **Exit:** at the **CLOSE H sessions later** (H=3 primary).
- **Return:** SPY-**hedged**, LONG, close→close GROSS bps `= stock_ret − spy_ret`; harness subtracts cost.
- **cluster:** week (multi-day hold). **metric:** hedged.

### Why one session late (central risk — flagged for the Skeptic + a kill condition)
The paper/live runner is a **once-daily after-close** job: an SC TO-I reaches SEC's daily index (and our
`filings.parquet`) the next weekday, the strategy emits when `first_session == today`, and an after-close
dispatch can only fill the **next** close = `first_session+1`. Research therefore enters `first_session+1` close
to match the paper rule exactly. The academic drift is partly **front-loaded around the filing date**; entering
~1–2 sessions later can eat much of the edge. **Kill signature:** the effect lives only at the earliest horizon
and the realized `first_session+1 → +3/+5` window is ~0. We cannot enter earlier — the open round trip costs
~80–250 bps, far more than the whole edge, and the user's broker has no auction orders. **CLOSE fills are forced.**

## Variants (7) and the pre-registered choice
universe {`sp1500`=sp500+sp400+sp600, `sp500`} × hold H {1, 3, 5} (6) plus one momentum-conditioned variant
`sp1500_h3_momneg` (base `sp1500`, H=3, kept only when prior-20-session stock return as of `first_session` < 0 —
the "deeper undervaluation" read from the idea card).
- **`chosen` is PRE-REGISTERED = `sp1500_h3`** — the idea card's primary rule: all S&P 1500, the ~3-day academic
  horizon. Deterministic, so `strategy.py` matches `chosen` exactly. The other 6 are a robustness map for the
  Skeptic only and are **never** carried to the holdout.
- `max_variants = 7`; best-of-N luck t ≈ `sqrt(2 ln 7)` ≈ 1.97.
- Train picks nothing — chosen is fixed in advance. Train reports which variant *looked* best, for the Skeptic.

### Robustness reads (verdicts only, NOT a switch of `chosen`)
- **hold 1 vs 3 vs 5.** Maps the decay. If the edge lives only at H=1 (exit `first_session+2`) and is ~0 by
  H=3/5, the tradable residual after our forced one-session-late entry is too thin — untradeable for this user.
- **sp1500 vs sp500.** Self-tenders skew toward smaller/undervalued names; if sp1500 is strong but sp500 flat,
  the effect is a small/mid-cap one (research verdict only). One shared cost floor (sp600 close) over-charges
  sp500 names → conservative.
- **momneg.** If `sp1500_h3_momneg` ≫ `sp1500_h3`, the edge concentrates in names that were already falling
  (genuine undervaluation / short-cover floor) rather than momentum continuation. A read, not a switch.

## Costs
`cost_bps = 25` (close→close sp600 spread floor ~22 + small impact). The harness charges `max(25, real floor)`
for the plan's `["sp500","sp400","sp600"]` close→close fills. This is a **LONG**, so there is **no short-borrow
concern** (unlike the SEO/PIPE shorts). `pass_mean_bps = 15` on the paper side leaves headroom for spread.

## Windows (family `self_tender` is brand-new — entire history clean)
- **Train:** 2001-01-01 .. 2015-12-31 (SC TO-I replaced SC 13E4 in Jan 2000, so the modern form covers the
  whole train window).
- **Holdout:** 2016-01-01 .. 2026-10-24 (the most recent = the arbitraged era; the honest decay test. Daily ends
  2026-11-06, buffering the close+5 exit). Holdout evaluates **only `chosen`**, once.

## What would kill it
1. Chosen train t < 2.0 or mean ≤ 0 → dead before any holdout (harness auto-bury).
2. Holdout chosen t < `budget.py bar self_tender` (floor 3.0) or mean ≤ 0 → dead.
3. The one-session-late window shows ~0 even when an immediate reaction existed → untradeable for this user.
4. **Event count too low.** Idea card requires ≥ ~20/yr for power. If `filings(forms=["SC TO-I"])` returns too
   few usable rows in the universe (smoke prints per-variant counts), power is marginal — noted for the Director.

## Event counts (reported from the smoke run — the idea card's gate)
Smoke (first train year, 2001) prints per-variant trade counts. If `sp1500_h3` is far below ~20 in year 1, power
is marginal and that's flagged. (See the Researcher outbox / notes for the actual smoke counts.)

## Survivorship (flagged for the Skeptic)
Only **current** S&P 1500 membership is available (no point-in-time index). A self-tender issuer is *not* an
acquisition target, so unlike merger-arb it usually stays listed — but a 2005 self-tenderer later acquired or
delisted is absent. That biases a **LONG** signal **UP**; a pass is **not** fully conservative on survivorship.

## Promotability
SC TO-I is same-day public; `filings.parquet` is rebuilt each dispatch, so `strategy.py` reads it live and emits
a LONG when an initial SC TO-I's first tradable session is today. **PROMOTABLE** (survivorship caveat only; no
borrow issue since it's long). Self-tenders in the S&P 1500 are uncommon (~20–50/yr across the whole universe),
so a 20–40 trading-day paper window may take months. Reused the `seo-short` skeleton (SEC-filing, close→close
hedged), flipped to LONG, swapped the 424B form filter for SC TO-I, added the momentum-conditioned variant.
