# early-10q-drift — pre-registered PLAN

## Hypothesis
A company that files its 10-Q **earlier** (by calendar date) than it filed the **same fiscal quarter's**
10-Q one year earlier is sending a voluntary "good news" signal. Managers with bad results delay
disclosure (Chambers & Penman 1984, JAR); Begley & Fischer (1998, JAE) show 10-Q timeliness predicts the
sign of the next earnings surprise and of analyst-forecast revisions, distinct from the surprise itself.
A 10-Q filing is lower-profile than an earnings press release, so the timestamp signal is under-noticed
and the early filer **drifts up** over the next ~1–3 sessions as participants catch on.

**Who is on the other side?** Passive holders who never read the filing timestamp; systematic desks that
react to earnings *dates* but not 10-Q *filing* dates.

## Mechanism of the edge (why it could be real)
The signal is a timing *delta* (this year vs the same quarter a year ago), not the filing itself, so it is
not simply "a 10-Q came out." It is costless-to-observe but attention-scarce, which is the classic shape of
a small under-reaction drift. If it is real it is small (single-digit to low-tens of bps net).

## Signal (pre-registered, leak-free)
- Universe: S&P 1500 (current membership — survivorship caveat below).
- For each 10-Q accepted by SEC at date `Di`, find this ticker's prior 10-Q accepted at `Dj` with
  `(Di − Dj)` in **[300, 430] calendar days** and closest to 365. That window isolates the *same fiscal
  quarter one year prior* while excluding the ~91/182/273-day neighbours and the ~456-day two-years case.
  (Matching by actual prior-filing gap, not calendar quarter, handles companies whose fiscal year ≠ calendar
  year, as the idea card requires.)
- `days_early = (Dj + 1 year) − Di` in calendar days (`>0` = filed earlier than a year ago).
  **5 trading days ≈ 7 calendar days; 10 ≈ 14** — thresholds are stated in calendar days so research and the
  paper strategy compute identically without a session calendar.
- Only the *original* 10-Q counts (form exactly `10-Q`; amendments `10-Q/A` dropped).
- **Signal date / entry**: LONG at the **OPEN of `first_session`** = the first session whose 09:30 ET open is
  after SEC acceptance (research_data computes it; an after-close filing trades the next open). This is "buy
  at open on the next trading day after the acceptance timestamp is public." No same-bar look-ahead: the
  entry open is strictly after acceptance.
- **Exit**: OPEN `H=3` sessions later (= open → open+3 from entry; open+1 → open+4 from the event day).
- Returns are **SPY-hedged, open→open, GROSS** bps; the harness subtracts `cost_bps`.

## Universe / windows / costs
- Family `10q_timing` — **new, entirely clean** (not in the catalog's used-periods table).
- **Train 2001-01-01 … 2015-12-31**, **holdout 2016-01-01 … 2026-10-28** (most recent years = the
  arbitraged era = the honest hard test). Daily bars end 2026-11-02, so the holdout_end leaves a buffer for
  the 3-session exit; filings end 2026-11-04; prior-year matches need ≥1 yr of history (filings from 1993,
  daily from 1999) so 2001 train-start is safe.
- `cost_bps = 20` round trip — S&P 1500 is mostly large/mid-cap; both legs fill at the open auction. 20 is at
  the conservative end of the card's 15–20 estimate.
- `cluster = "week"` — multi-day (3-session) holds overlap, so day-clustering would overstate independence.
- `metric = "hedged"`.

## Variants (6 — small, to keep the luck bar low)
| name | universe | threshold | side |
|---|---|---|---|
| **sp1500_t7_long** (CHOSEN) | S&P 1500 | ≥7 cal days early | long |
| sp1500_t14_long | S&P 1500 | ≥14 | long |
| sp46_t7_long | S&P 400+600 (small/mid) | ≥7 | long |
| sp46_t14_long | S&P 400+600 | ≥14 | long |
| sp1500_t7_short | S&P 1500 | ≤−7 (late filer) | short |
| sp46_t7_short | S&P 400+600 | ≤−7 | short |

`chosen` is **PRE-REGISTERED = `sp1500_t7_long`** (not best-of-train): the broad universe the academic result
is measured on, the base 7-day/≈5-trading-day threshold, long. Hold is fixed at 3 (the card's horizon) to
keep the grid tight. The other five are a robustness map for the Skeptic only and are never carried to the
holdout. `max_variants = 6` → best-of-N luck t ≈ 1.9; the holdout bar is `python tools/budget.py bar
10q_timing` (floor 3.0).

## What would kill it
- Chosen `sp1500_t7_long` holdout t below the budget bar, or mean ≤ 0 → **dead**.
- If the long edge lives only in the ≥14 or small-cap variants but not the chosen broad/≥7 rule, the
  pre-registered hypothesis has failed even if a cousin looks good (that is the point of pre-registering).
- Late-filer short with no symmetry would argue the long result is not a timing effect.

## Honest caveats (for the Skeptic)
1. **Survivorship**: only *current* S&P 1500 membership exists (no point-in-time). Biases a long signal up —
   flagged. The late-filer **short** shares the same universe, a partial internal control.
2. **High event rate** (~1,500–1,800 early filers/yr): if most early filers are simply on a fixed calendar,
   the delta is noise, not news — the ≥14-day variant probes whether a larger delta sharpens the signal.
3. **Content under-scrutiny**: the market may not update on a 10-Q timestamp at all → a true null is a good,
   honest result.
4. **Paper-timing slip**: the SEC daily index reaches our parquet the *next weekday*, so a 10-Q accepted the
   same session can slip one day in live paper trading (research uses the clean `first_session`). Noted in
   strategy.py; the Director weighs it before promoting.
