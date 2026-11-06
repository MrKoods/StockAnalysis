# turn-of-month -- pre-registered PLAN

## Hypothesis
A predictable monthly seasonal: US large-cap equities earn an abnormally high return in the window
spanning the **last trading day of the calendar month** through the first few trading days of the next
month (the "turn-of-the-month", TOM, effect).

## Mechanism (who is on the other side)
Structural, calendar-scheduled cash inflows concentrate buying at the month turn: 401(k)/pension
contributions, dividend-reinvestment, and coupon/dividend payment timing (Ogden 1990) deploy on fixed
month-end/month-start schedules. The marginal buyers are these long-horizon, schedule-driven institutions;
the sellers are short-horizon traders and month-end window-dressers who exit before the close. Documented
by Ariel (1987), Lakonishok & Smidt (1988), and -- crucially, post-publication, through 2005 --
McConnell & Xu (2008), who attribute it to cash-flow timing rather than data mining.

## This is a LARGE-CAP, RAW, PAPER-TRADABLE test (scoping)
- **Universe = S&P 500 only.** The mechanism (index-fund / 401(k) / DRIP flows) is a large-cap story, and
  large-cap close fills are the only ones cheap enough to survive (Webull close round-trip ~6.6 bps for
  sp500 vs ~22 bps for sp600). I deliberately do NOT test an sp400/sp600 tilt here: a single plan can carry
  only one cost floor, and lumping small-caps in would either over-charge the sp500 result or under-charge
  the small-caps. If large-cap TOM does not survive ~10 bps, the idea is dead for anything the user could
  actually trade cheaply -- small-cap TOM would face >2x the cost.
- **Metric = RAW (unhedged), close-to-close.** TOM is a *market-level* seasonal: the whole market rises
  during the window. Hedging each long vs SPY over the same days would cancel the very effect we are testing
  (SPY has the TOM effect too), leaving only cross-sectional noise. So we measure the raw basket return.
  - **Beta confound (for the Skeptic):** a raw 4-day long also earns the general equity premium
    (~4 bps/day x ~4 days ~ 16 bps gross) regardless of TOM. A positive mean alone is therefore NOT proof
    of a TOM-specific edge. To isolate the seasonal I include a **mid-month placebo** variant (`mid_h3`): a
    raw long of the same universe entered mid-month and held 3 sessions. It earns the same beta but no TOM.
    The TOM edge is real only if `tom_h3` mean clearly **exceeds** the `mid_h3` placebo (the harness scores
    each config separately; the Skeptic should read the *difference*, not just tom_h3 > 0).

## Exact rule
- Universe: current S&P 500 members (rd.universe("sp500")). Equal-weighted -- every member traded each month.
- Entry: **close** of the last NYSE trading day of each calendar month (day T).
- Exit: **close** of the H-th NYSE trading session of the new month (H sessions after entry).
- Per-trade return is the raw close-to-close return in bps; the harness subtracts cost and clusters by week.
- Cluster = **week**. TOM is one independent market-wide event per month, so ~1 weekly cluster per month
  (all 500 names exit the same day). Train 1999-2014 ~ 192 months; holdout 2015-2026 ~ 142 months -- enough
  power for a real, consistent seasonal; too few clusters to chase a weak one (that is the honest risk).

## Universe / timing / costs
- `entry_at` = close, `exit_at` = close, `universe` = ["sp500"]. Real Webull close->close floor ~6.6 bps.
- `cost_bps` = 10 (round trip) -- above the measured spread floor, a conservative liquid-large-cap estimate.
- Signal at T uses only data through T's close; exit is strictly later. No look-ahead: which calendar day is
  month-end is known in advance (it is the calendar, not future prices).

## Variants (6 max; 4 evaluated) and why
Within sp500, equal-weight, raw:
- `tom_h1`, `tom_h2`, `tom_h3` -- exit the 1st / 2nd / 3rd new-month session (horizon robustness).
- `mid_h3` -- **placebo**: enter the middle session of the month, hold 3 (isolates TOM vs plain beta).

**`chosen` is PRE-REGISTERED = `tom_h3`** -- the canonical McConnell-Xu TOM window (month-end close through
the 3rd new-month close), the idea card's stated rule. It is NOT best-of-train. The other three configs are
reported only as a robustness / placebo map and are never carried to the holdout. best-of-N luck t for 4
variants ~ 1.67; the holdout bar is the family floor 3.00 (tools/budget.py bar calendar_effects).

## Windows
- Train: 1999-01-01 .. 2014-12-31 (daily archive starts 1999-01-04).
- Holdout: 2015-01-01 .. 2026-10-31 -- the most recent, most-arbitraged era (the hard, honest test; the
  family `calendar_effects` has no prior used period, so this whole span is clean). Daily data ends
  2026-11-02, leaving a buffer for the +3 exit; the Oct-2026 turn (exits early Nov) simply forms no trade.
- The Dec-2014 turn (entry 2014-12-31, exit early Jan 2015) is scored by its exit date, so it lands only in
  the holdout -- no train/holdout event overlap.

## What would kill it
- Chosen `tom_h3` holdout t < 3.00 or mean <= 0 after 10 bps cost -> dead.
- If `tom_h3` barely clears but is no better than the `mid_h3` placebo -> it is just beta, not TOM (Skeptic
  should fail it): the point estimate must show a real seasonal premium above a comparable mid-month long.
- Known decay: McConnell-Xu already found the effect weakening; a 2015-2026 holdout null is a fully expected,
  honest outcome and a good result.

## Paper promotability (IMPORTANT caveat)
The rule is expressible in the paper contract (close entry on month-end, close exit +3) and strategy.py uses
only the NYSE calendar + daily bars, so it CAN run live. BUT TOM fires once a month and all names share one
exit date, so the paper runner accrues **one clustered "day" per month**: reaching min_days=20 would take
~20 months and max_days=40 ~3+ years. This is effectively a **research-only verdict**; the Director should
treat the train+holdout result as the decision and not expect a timely paper test. Flagged for the Director.
Survivorship: only current S&P 500 membership is available (no point-in-time index) -- a mild upward bias on
a long, noted for the Skeptic.
