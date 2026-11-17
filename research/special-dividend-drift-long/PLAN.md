# special-dividend-drift-long — pre-registered plan

## Hypothesis
When a company announces a **special (one-time) cash dividend** in an 8-K (item 8.01), it is a hard,
irreversible signal of excess capital and management confidence. Because specials are infrequent,
lightly covered, and excluded from dividend-yield screens, investors underreact and the stock drifts
up over the following weeks. Ahn (2024, SSRN 7249419) documents ~120 bps abnormal return over days
+2..+20 post-announcement; Lie (2001) and Peyer-Vermaelen (2009) document positive announcement and
post-announcement returns for excess-cash distributions.

## Mechanism / who is on the other side
Underreaction to irregular, non-recurring cash signals: passive holders who don't react to a one-off
event, yield screens that ignore non-recurring dividends, and investors who treat the special as a
one-time windfall rather than a signal. Institutions accumulate over days to meet income mandates.

## Signal
- Universe: S&P 1500 current members (variants below also cut to S&P 500 PIT and to S&P 400+600).
- Event: an 8-K **item 8.01** whose text (body + attached press release / `exhibit`) matches a
  **pre-registered, fixed** regex (case-insensitive):
  `special\s+(?:cash\s+|one[-\s]?time\s+|year[-\s]?end\s+)?dividend`
  (matches "special dividend", "special cash dividend", "special one-time / one time dividend",
  "special year-end dividend"). This regex is frozen here and is NOT tuned on train results — a
  keyword list tuned on results would be a variant and would raise the luck bar (TEAM.md / filing_text
  docstring). Rows without downloaded text (`has_text` False, ~2% of 8.01) are skipped.
- `rd.filings(items=['8.01'], tickers=sp1500)` → `rd.filing_text()` → regex filter.
- The signal date is `entry_session` (the first session whose CLOSE is still buyable after SEC accepted
  the 8-K, i.e. day 0 — the 2026-11-13 audit's fix for buying a day late).

## Entry / exit / timing
- **LONG at the CLOSE of `entry_session`** (day 0). The announcement jump happens intraday, before that
  close; buying at the close captures only the *drift* (days +1..+20), which is the documented effect.
- Exit at the close `hold` sessions later (chosen hold = 20 sessions; a 10-session robustness variant).
- Hedge each trade with ITS OWN index fund (SPY / IJH / IJR via `rd.index_of` + `rd.hedge_ticker`) —
  SPY-hedged small caps otherwise carry the small-vs-large swing as noise (2026-11-13).
- Close→close fills (cheap: ~7 sp500 / ~12 sp400 / ~22 sp600 bps round trip). `cost_bps` = 25
  (the harness charges max(25, the real Webull close-spread floor for the universe)). At a claimed
  ~120 bps gross over 20 days the cost is a rounding error.

## Universe / windows / clustering
- `universe` = ["sp500","sp400","sp600"]; the sp500-only variant runs events through
  `rd.pit_filter(events, "entry_session")` (point-in-time membership — required).
- Train **2014-01-01 .. 2019-12-31** (6y), holdout **2020-01-01 .. 2026-10-24** (~6.8y).
  Family `8k_8_01` has used only 2005-2013 (the free 8-K screen) — both windows are clean.
- Windows chosen **for power**: a long holdout relative to the train (holdout/train ≈ 1.14) raises the
  expected holdout t = train_t × sqrt(holdout/train). A longer train would *lower* that ratio and hurt
  power. The 2012 fiscal-cliff special-dividend surge is excluded from BOTH windows (it would inflate a
  train estimate that the holdout cannot reproduce). COVID-2020 and the post-COVID regime sit in the
  holdout — a conservative forward test of exactly the environment we would trade.
- `hold_days` = 20 (> 10) → `cluster` = **month** (overlapping 20-session holds make weekly periods
  dependent; the harness enforces month).

## Expected events (power)
S&P 1500 specials ≈ 50-120/yr (tax-cycle dependent). Train 6y ≈ 300-720 events over ~72 month-clusters;
holdout ~6.8y ≈ 340-820 events over ~82 month-clusters. Ample power provided the per-month mean is
consistently positive. Smoke (first train year) is only to confirm counts, not performance.

## Variants (5) — explicit, pre-registered
`CONFIGS` dict, name → (entry_mode, universe, hold). `chosen` is PRE-REGISTERED = `all_sp1500_h20`
(the card's primary rule). The other four are a robustness map for the Skeptic and are NEVER carried to
the holdout.
- `all_sp1500_h20` **(CHOSEN)** — all S&P 1500, day-0 close entry, 20-session hold.
- `all_sp1500_h10` — same, 10-session hold (is the drift front-loaded or does it run the full month?).
- `midsmall_h20` — S&P 400+600 only (Ahn: stronger drift in less-covered smaller names).
- `all_sp500_h20` — S&P 500 only, PIT-filtered (large-cap; the most-arbitraged, weakest-expected).
- `e1_sp1500_h20` — enter the CLOSE after `first_session` (a day late). Direct test of how much the
  day-0 close matters; if `e1` ≈ `e0` the entry-timing fix is doing nothing.

I deliberately DROP the card's "pre-market vs after-hours acceptance" variant to keep the luck bar low
(fewer variants is better). The family's prior screen variants are added to the luck bar automatically.

## Costs
`cost_bps` 25 on top of the real-spread floor. Hedged gross; the harness subtracts cost and clusters by
month. No borrow cost (long only).

## What would kill it
- Chosen train t < 2.0 or mean ≤ 0 → dead with no holdout spent.
- Holdout pass chance < 25% → buried without spending the holdout (redesign for more power).
- Holdout t < 3.0 bar or mean ≤ 0 → dead.
- `e1 ≈ e0` would mean the day-0 close entry adds nothing (the drift is slower / later than claimed).
- If the regex counts come out absurdly high in smoke (false positives — 8.01s that merely *mention*
  specials), the signal is too loose; counts (not performance) are visible in smoke and may be checked
  before commit.

## Skeptic / risk notes
1. **Reminder 8-Ks**: a company may file a second 8.01 ("board declares" / ex-date) that also matches.
   We do NOT dedup across filings (only drop same-day (ticker, entry_session) duplicates), so research
   and paper stay byte-for-byte identical. A reminder entered weeks later captures *less* drift, which
   dilutes the mean — so a holdout pass despite it is conservative. (A deduped robustness variant was
   not spent, to keep the luck bar low.)
2. **Survivorship**: sp400/sp600/'all' have no PIT list — a long result on `midsmall`/`sp1500` is biased
   up (names that later left the index are absent). The sp500 variant is PIT-clean. Prefer the sp500 and
   `e0`-vs-`e1` reads when judging realism. The recent windows limit (not remove) the bias.
3. **Post-publication decay**: Ahn (2024) is recent; the 2020-2026 holdout may already show decay.
4. **Text-filter accuracy**: a simple regex may include an 8.01 that mentions a special dividend in
   passing. Monthly clustering + the long holdout are the defense; the regex is frozen pre-registration.

## Promotability (paper)
**Promotable as a true day-0 test.** Day-0 paper trading is built (2026-11-14): `tools/edgar_live.py`
captures today's SEC filings + in-scope 8-K text (~12:40 PT) and `paper_runner.run_day0` fires
`signals()` before the close for `"entry_at": "same_close"` strategies. `strategy.py` reads today's
filings via `edgar_live.filings_asof(asof)` and their text via `edgar_live.text_asof(asof)` (and, for an
8-K accepted after the 15:30 ET cutoff on the prior session whose entry_session is today, falls back to
the archive text parts for just those few accessions), applies the SAME frozen regex, and goes LONG at
today's close when an 8.01 special-dividend entry_session is today. Metric `real_hedged_bps` (real Webull
bid/ask; the runner hedges vs SPY only — research is per-index, noted).
