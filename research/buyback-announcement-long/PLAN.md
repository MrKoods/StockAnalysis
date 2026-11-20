# buyback-announcement-long — pre-registered plan

## Hypothesis
When a company announces an **open-market share repurchase authorization** in an 8-K (item 8.01)
press release, it is a credible signal that management views the shares as undervalued and intends to
buy them. Because repurchase programs are not legally binding, the market discounts the commitment and
**underreacts**; the stock then drifts up over the following weeks as the firm (and short-coverers)
buy into a shrinking float. Ikenberry, Lakonishok & Vermaelen (1995, JFE) document a ~12% four-year
abnormal return concentrated in the first 1-3 months; Peyer & Vermaelen (2009, JFQA) report ~2.4%
four-factor alpha in the first month and show the effect **persists post-publication**.

## Mechanism / who is on the other side
Underreaction to a soft, non-binding commitment. Investors who believe the program may not be executed
(or who treat the pop as the whole story) are slow to price the sustained open-market demand. The firm
itself is the natural buyer, and shorts must cover into a shrinking float — both create multi-week
upward pressure after the announcement day.

## Signal
- Universe: S&P 1500 current members (variants below also cut to S&P 500 PIT and to S&P 400+600).
- Event: an 8-K **item 8.01** whose text (body + attached press release / `exhibit`) matches a
  **pre-registered, FROZEN** share-repurchase regex (case-insensitive), after stripping any
  "repurchase agreement(s)" phrase (repo/financing contracts — not an equity buyback):
  ```
  REPO strip:  repurchase\s+agreements?
  BUYBACK_RE:  share\s+repurchase | stock\s+repurchase | repurchase\s+program |
               repurchase\s+plan | repurchase\s+authoriz |
               authoriz\w*\s+(?:the\s+)?(?:repurchase|buy[-\s]?back) |
               buy[-\s]?back | repurchase\s+of\s+(?:its\s+)?(?:common\s+)?(?:stock|shares)
  ```
  This is **tighter than the idea card's rule #1** ("repurchase" OR "share repurchase program" OR
  "buyback"): a bare "repurchase" also matches debt/note repurchases and repo agreements, so I require
  the word to sit in a share/program/authorization context. The regex is frozen here and is NOT tuned
  on train results — a keyword list tuned on results would be a variant and would raise the luck bar
  (TEAM.md / filing_text docstring). The "repurchase agreement" strip makes the (rare) master-repo 8.01
  unable to satisfy the filter. Rows without downloaded text (`has_text` False, ~2% of 8.01) are skipped.
- `rd.filings(items=['8.01'], tickers=sp1500)` → `rd.filing_text()` → strip → regex filter.
- The signal date is `entry_session` (the first session whose CLOSE is still buyable after SEC accepted
  the 8-K, i.e. day 0 — the 2026-11-13 audit's fix for buying a day late).

## Entry / exit / timing
- **LONG at the CLOSE of `entry_session`** (day 0). The announcement jump happens intraday, before that
  close; buying at the close captures only the *drift* (days +1..+20), which is the documented
  underreaction effect (not the day-0 pop).
- Exit at the close `hold` sessions later (chosen hold = 20 sessions; a 10-session robustness variant).
- Hedge each trade with ITS OWN index fund (SPY / IJH / IJR via `rd.index_of` + `rd.hedge_ticker`) —
  SPY-hedged small caps otherwise carry the small-vs-large swing as noise (2026-11-13).
- Close→close fills (cheap: ~7 sp500 / ~12 sp400 / ~22 sp600 bps round trip). `cost_bps` = 25
  (the harness charges max(25, the real Webull close-spread floor for the universe)). Against a claimed
  ~200 bps/month gross the cost is small.

## Universe / windows / clustering
- `universe` = ["sp500","sp400","sp600"]; the sp500-only variant runs events through
  `rd.pit_filter(events, "entry_session")` (point-in-time membership — required).
- Train **2014-01-01 .. 2019-12-31** (6y), holdout **2020-01-01 .. 2026-10-24** (~6.8y).
  Family `8k_8_01` has used 2005-2013 (the free 8-K screen) and 2014-2019 (the special-dividend train
  run — a *different* 8.01 event, different text filter). The holdout 2020-2026 is clean for the family
  (the special-dividend idea died at the Skeptic BEFORE its holdout was spent).
- Windows chosen **for power**: a holdout slightly longer than the train (holdout/train ≈ 1.14) raises
  the expected holdout t = train_t × sqrt(holdout/train). A longer train would *lower* that ratio and
  hurt power. 2020 (COVID buyback suspensions) and the 2021-2022 buyback wave sit in the holdout — a
  conservative forward test of exactly the regime we would trade.
- `hold_days` = 20 (> 10) → `cluster` = **month** (overlapping 20-session holds make weekly periods
  dependent; the harness enforces month).

## Expected events (power)
Open-market repurchase announcements are frequent: Peyer & Vermaelen cite ~1,000+/yr US-wide; S&P 1500
is roughly half the market, so ≈ 300-700 qualifying 8.01s/yr. Train 6y ≈ 1,800-4,200 events over ~72
month-clusters; holdout ~6.8y similar over ~82 month-clusters. Ample power provided the per-month mean
is consistently positive. Smoke (first train year) is only to confirm counts, not performance.

## Variants (5) — explicit, pre-registered
`CONFIGS` dict, name → (entry_mode, universe, hold). `chosen` is PRE-REGISTERED = `all_sp1500_h20`
(the card's primary rule). The other four are a robustness map for the Skeptic and are NEVER carried to
the holdout.
- `all_sp1500_h20` **(CHOSEN)** — all S&P 1500, day-0 close entry, 20-session hold.
- `all_sp1500_h10` — same, 10-session hold (is the drift front-loaded or does it run the full month?).
- `midsmall_h20` — S&P 400+600 only (smaller, less-arbitraged names: literature finds a stronger drift).
- `all_sp500_h20` — S&P 500 only, PIT-filtered (large-cap; the most-arbitraged, weakest-expected, and
  the survivorship-clean read).
- `e1_sp1500_h20` — enter the CLOSE after `first_session` (a day late). Direct test of how much the
  day-0 close matters; if `e1` ≈ `e0` the entry-timing fix is doing nothing.

The family's prior screen + special-dividend variants are added to the luck bar automatically.

## Costs
`cost_bps` 25 on top of the real-spread floor. Hedged gross; the harness subtracts cost and clusters by
month. No borrow cost (long only).

## What would kill it
- Chosen train t < 2.0 or mean ≤ 0 → dead with no holdout spent.
- Holdout pass chance < 25% → buried without spending the holdout (redesign for more power).
- Holdout t < 3.0 bar (`python tools/budget.py bar 8k_8_01`) or mean ≤ 0 → dead.
- `e1 ≈ e0` would mean the day-0 close entry adds nothing (the drift is slower / later than claimed), or
  that what's left after day 0 is ~cost (the audit's #1 failure mode).
- If the regex counts come out absurdly high in smoke (false positives — 8.01s that merely *mention* a
  repurchase), the signal is too loose; counts (not performance) are visible in smoke before commit.

## Skeptic / risk notes
1. **Post-publication decay.** The ILV / Peyer-Vermaelen effect has been public for 30 years; large-cap
   buybacks are among the most-arbitraged events. The 2020-2026 holdout and the `all_sp500` read are the
   direct tests of whether anything survives today. This is the central risk.
2. **Day-0 close already captures the pop.** We buy at the day-0 close, after the announcement jump. The
   residual drift may be a fraction of the cited full-month alpha. `e0`-vs-`e1` quantifies the timing.
3. **Reminder / completion 8-Ks.** A company may file a later 8.01 that also mentions the repurchase
   (program increase, buyback completed). We do NOT dedup across filings (only drop same-day
   (ticker, entry_session) duplicates), so research and paper stay byte-for-byte identical; a reminder
   entered weeks late captures *less* drift → dilutes the mean → a pass despite it is conservative.
4. **Survivorship.** sp400/sp600/'all' have no PIT list — a long result on `midsmall`/`sp1500` is biased
   up (names that later left the index are absent). The `sp500` variant is PIT-clean; prefer it and the
   `e0`-vs-`e1` read when judging realism. The recent windows limit (not remove) the bias.
5. **Text-filter accuracy.** A simple frozen regex may include an 8.01 that mentions a repurchase in
   passing, or a negotiated (non-open-market) buyback. Monthly clustering + the long holdout are the
   defense; the regex and the repo-strip are frozen pre-registration.

## Promotability (paper)
**Promotable as a true day-0 test.** Day-0 paper trading is built (2026-11-14): `tools/edgar_live.py`
captures today's SEC filings + in-scope 8-K text (~12:40 PT) and `paper_runner.run_day0` fires
`signals()` before the close for `"entry_at": "same_close"` strategies. `strategy.py` reads today's
filings via `edgar_live.filings_asof(asof)` and their text via `edgar_live.text_asof(asof)` (and, for an
8-K accepted after the 15:30 ET cutoff on the prior session whose entry_session is today, falls back to
the archive text parts for just those few accessions), applies the SAME frozen repo-strip + regex, and
goes LONG at today's close when an 8.01 repurchase-authorization entry_session is today. Metric
`real_hedged_bps` (real Webull bid/ask; the runner hedges vs SPY only — research is per-index, noted).
