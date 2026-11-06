# nt-filing-short — pre-registered PLAN

## Hypothesis
When a company cannot file its 10-K or 10-Q on time it must file a **Notification of Late Filing**
(Form **NT 10-K** / **NT 10-Q**). That notice is a public admission that management cannot certify the
financials on schedule. Ettredge, Lee & Scholz (2000) show NT filers then report larger negative earnings
surprises and draw downward analyst revisions (−50 to −70 bps CAR in the 2 days after the NT); Kinney &
McDaniel (1989) tie late filing to higher restatement / internal-control-weakness rates. The market
**underreacts at the NT date** (many wait for the actual report), leaving a short-side drift window.

## Mechanism / who is on the other side
Passive holders who don't monitor NT filings in real time; systematic strategies that react only to the
actual 10-K/Q; retail who don't distinguish an NT from the real filing. We take the informed short.

## Universe
S&P 500 + S&P 400 (large + **mid** cap), current membership (survivorship caveat below). The idea's own
note scopes shorts to large caps for borrow reasons; pure S&P 500 is likely too sparse (large caps rarely
file late), so the pre-registered config adds mid caps — still borrowable, not micro-cap distressed. S&P 600
(small cap) is **excluded**: borrow on distressed micro caps is prohibitive and unmodellable here.

## Signal and timing (close fills — this edge cannot pay for the open)
- Signal: a universe ticker's **NT 10-K or NT 10-Q** is accepted by SEC. The event day is `first_session`
  (the first session whose 09:30 open is after acceptance — leak-free; never `filing_date`).
- **Entry: SHORT at the CLOSE of the session AFTER `first_session`** (one session after the first reaction).
- **Exit: cover at the CLOSE H sessions later.**
- Why close, not the idea's open+1: the measured CAR is only ~50–70 bps, but a Webull **open** round trip
  on this universe costs ~80 bps (no retail auction orders) — more than the entire edge. A **close** round
  trip costs ~7–12 bps. An open-entry version is untradable for this user, so it is not even tested. The
  cost of entering one session late (missing part of the drift) is the honest price of a tradable fill, and
  is the central risk (see kill conditions).
- Returns are **SPY-hedged GROSS** bps, short side: `gross = spy_ret − stock_ret` (close→close over the hold).
  The harness subtracts `cost_bps`. This matches paper_runner's short hedged definition
  (`hedged = real_bps − sgn·spy_bps`, sgn = −1).

## Costs
`cost_bps = 30` round trip. The real-spread floor for close→close on sp500/sp400 is ~12 bps; 30 bps adds
headroom for **short-borrow** on a stressed name (a 3-session hold at ~15–20% annualised borrow ≈ 12–18 bps)
plus slippage. Borrow is the key uncertainty — flagged as a kill test by the idea. cluster = **week**
(multi-day holds; NT events are sporadic).

## Variants (5; `max_variants` 8)
universe ∈ {`sp500`, `sp54` = sp500+sp400} × hold H ∈ {2, 3}, plus one robustness filter on the chosen
config that **excludes NT filings concurrent (±2 cal days) with an 8-K item 2.02 earnings release** (those
are arguably already priced):
1. `sp500_h2`  2. `sp500_h3`  3. `sp54_h2`  4. **`sp54_h3` (chosen)**  5. `sp54_h3_ex202`

**`chosen` is PRE-REGISTERED = `sp54_h3`** — the broadest tradable universe (large+mid) and the evidence's
~3-day drift horizon. The other four are a robustness map for the Skeptic and are never carried to the
holdout. best-of-N luck t ≈ 1.79.

## Windows
- Train **2005-01-01 .. 2017-12-31** (8-K item codes — needed for the ex202 variant — exist from 2004-08).
- Holdout **2018-01-01 .. 2026-10-24** — the most recent, most-arbitraged era = the hardest, most honest
  test; a period the `nt_filing` family (new) has never used. Daily bars end 2026-11-02, leaving a buffer
  for the last close+3 exits; the few events too close to the end simply drop (no look-ahead).

## What would kill it
- Chosen train t < 2.0 or mean ≤ 0 (auto-buried by the harness, no holdout spent).
- Holdout t < 3.0 (family bar) or mean ≤ 0.
- If `sp54_h3` ≤ `sp54_h3_ex202` AND the ex202 version is weak, the "signal" is just concurrent earnings
  being priced — a confound, not an NT effect (flag for Skeptic).
- NT forms not present in the archive → smoke shows ~0 trades → the idea dies (idea's stated gate).

## Caveats for the Skeptic
- **Entering one session after `first_session` (close)** may miss most of the 2-day CAR — the drift could
  be gone by then. This is the honest cost of a retail-tradable fill.
- **Survivorship**: only *current* S&P 500/400 membership exists. A company that filed NT and was later
  delisted (the worst outcomes) is NOT in today's index — this biases a SHORT signal **against** us
  (we miss the biggest drops), so a pass here is conservative; a fail could be partly survivorship.
- **Borrow is not in the paper metric**: `real_hedged_bps` prices the spread (bid/ask) but NOT short
  borrow. The paper `pass_mean_bps` is sized (15 bps) so a pass still clears a plausible borrow cost, but
  the Director must confirm real borrow before any real-money step.
- Many NT filers file the actual report within ~15 days and bounce — the short can reverse.
