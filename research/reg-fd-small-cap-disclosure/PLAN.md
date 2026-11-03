# reg-fd-small-cap-disclosure — PLAN (pre-registered)

## Hypothesis
A voluntary **Regulation FD disclosure** (8-K item **7.01**) is a company-initiated public release
(investor day, press conference, guidance, material update) delivered to all investors at once. For
**small-cap** names (few analysts, thin institutional coverage) this is meaningful NEW information that
diffuses slowly as under-attentive / retail holders catch up over the next day. We go **LONG** the
small-cap filer at the first tradable open after the 7.01 becomes public and exit a session later.

## Mechanism / who is on the other side
Sellers and holders who do not read SEC filings same-day; retail attention lags institutional attention
by 1–2 days on under-followed names. The adjustment should be larger and slower the smaller / less-covered
the firm — hence small (S&P 600) > mid (S&P 400) > large.

## Prior evidence
- Team event screen (state/screen.md, 2005–2013, FULL S&P 1500): 7.01 is the single best 8-K type —
  **+6.5 bps at 1d, week-t 2.31** (24,024 events); 3d +6.9 (t 1.63); 5d +0.20. Best of 57 → luck t ~2.84,
  so the full-universe signal is NOT established. This idea sharpens it by restricting to the small/mid-cap
  subset where the mechanism predicts a bigger, slower move (large caps dilute it in the pooled screen).
- Heflin, Subramanyam & Zhang (2003), *Accounting Review*: Reg FD raised voluntary disclosure; larger
  uncertainty reduction for small firms. Bailey et al. (2003), *JF*: stronger price impact for
  less-followed firms. Gomes, Gorton & Madureira (2007): firms use 7.01 selectively for positive news.

## Universe
Current S&P 600 (small) and S&P 400 (mid) membership (`rd.universe('sp600'/'sp400')`).
**Survivorship caveat (for the Skeptic):** only *today's* membership is available — no point-in-time index.
A long event signal is biased UP by this (failed/delisted small caps dropped). Flagged; not fixable here.

## Signal, timing, costs (leak-free)
- Event: an 8-K whose item list contains **7.01**, filed by a universe ticker.
  `rd.filings(forms=['8-K'], items=['7.01'], tickers=<universe>)`.
- Signal date = `first_session` (rd's first session whose 09:30 ET open is strictly after SEC acceptance;
  an after-4pm filing → next open). Never `filing_date`. This is the only leak-free entry.
- **Entry:** OPEN of `first_session`. **Exit:** CLOSE `H` sessions later (exit_pos = entry_pos + H).
- **SPY-hedged** long: `gross = (C_exit/O_entry − 1) − (SPY_close_exit/SPY_open_entry − 1)` in bps. The
  harness subtracts `cost_bps`. Dedup to one trade per (ticker, first_session). Drop bars with
  |stock move| > 50% (bad-bar / unadjusted-data guard, matches the screen).
- **cost_bps = 30** — realistic round trip for small caps (idea est. 30–35 small, 20–25 mid). One cost is
  applied to every variant; it is conservative for the mid-cap (S&P 400) variants, which is the safe side.
- **cluster = "day"** — the chosen rule is a 1-session hold scored on its exit date; many events per day
  give a healthy daily sample, and day-clustering is the TEAM.md default for trades exiting each day.

## Variants (6) and why
Grid = universe {S&P 600, S&P 400, S&P 400+600} × hold H {1, 3}. All SPY-hedged long.
- Universe axis tests the core mechanism's monotonicity (smaller cap → bigger move).
- Hold axis: screen favored 1d over 3d; 3d checks persistence.
Only 6 variants (luck t ~1.9) and `chosen` is **pre-registered**, not best-of-train, so the holdout tests a
single hypothesis against the family bar (≥ 3.00).

## chosen (PRE-REGISTERED, matches strategy.py exactly)
**`sp600_h1`** — S&P 600 only, hold 1 session. Smallest-cap = strongest form of the hypothesis; hold 1
= the screen's best-t horizon. The other 5 configs are reported for the Skeptic as a robustness map and
are NEVER carried to the holdout.

## Windows
- Family `8k_7_01` has used only **search 2005–2013** (the event screen). 8-K item codes exist from 2004-08.
- **Train 2005-01-01 .. 2013-12-31** (refine within the screen's search period — allowed; it is not holdout).
- **Holdout 2014-01-01 .. 2026-10-30** — never touched by this family (most-recent = hardest / most
  arbitraged era, the honest test). Daily + filings end 2026-11-02; a buffer leaves room for the 1-day exit.

## What would kill it
- Holdout `sp600_h1` net t < **3.00** (family bar) or mean ≤ 0 → DEAD.
- Known risks the Skeptic should weigh: (1) full-universe screen t (2.31) was below its own luck bar, so
  the edge may not survive even after the small-cap sharpening; (2) many 7.01s piggyback on 2.02 earnings /
  M&A items — this is an "any filing containing 7.01" test (matches the screen), so the measured effect
  blends pure Reg-FD disclosures with event-coincident ones; (3) thin edge vs 30 bps costs; (4) algorithmic
  news scrapers have compressed the retail lag the thesis depends on (why the recent holdout is the real test).

## Promotability
7.01 8-Ks are public the same day and `data/edgar/filings.parquet` (rebuilt by tools/edgar.py every
dispatcher run) carries the exact acceptance time → this CAN be traded live. Small caps file 7.01 often, so
a 20–40 trading-day paper window should fill reasonably (unlike the rare-event split idea). strategy.py
encodes exactly `sp600_h1`, judged at real Webull quotes (`real_hedged_bps`).
