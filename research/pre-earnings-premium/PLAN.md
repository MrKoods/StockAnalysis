# pre-earnings-premium — pre-registered plan

## Hypothesis & mechanism
A stock earns a **risk premium in the 1-2 sessions BEFORE a scheduled earnings announcement**.
Risk-averse investors reduce exposure before an announcement to avoid the uncertainty; they pay the
holders who absorb that risk. The premium accrues in the pre-announcement window and is unrelated to
the surprise itself (we are flat before the number prints). Laarits (2020, "Pre-Announcement Risk",
SSRN 3443886) documents a significant 24-hour pre-announcement equity premium; Ai, Bansal & Han
(2021, JFE) find **72% of the earnings-period excess return accrues BEFORE the release**.

**Distinct from V4 EPRE.** EPRE enters before the announcement and holds *through* it (earnings-surprise
+ pre-announcement premium combined). This idea **exits at the close of A-1** (one session before the
announcement session A) and takes **zero earnings-surprise risk** — it isolates only the pre-announcement
drift. The two trade different windows of the same event.

## Rule (chosen = `h1_sp500`)
- **Universe:** S&P 500 only (see "Why sp500 only").
- **Signal:** stock has a scheduled earnings announcement on session **A**.
- **Entry:** LONG at the **CLOSE of A-2** (two sessions before A).
- **Exit:** at the **CLOSE of A-1** (one session before A). Hold = 1 session, close→close.
- **Return:** SPY-hedged gross bps on the long side (`stock_ret − spy_ret`, close→close). The harness
  subtracts cost. Hedging isolates the firm-specific pre-announcement drift from market beta: firms
  announce on staggered days, so the market leg is noise that hedging removes (raises t).

## Why sp500 only (a deliberate, pre-registered scope — not a data limit)
The documented premium is at most tens of bps over a 1-day hold. A plan carries **one** cost floor =
its most expensive index at its fill times. Close→close round-trip spreads measured at Webull are
~6.4 bps (sp500), ~12 (sp400), ~22 (sp600). At a 1-session hold the premium **cannot survive** sp400/sp600
costs, and mixing those indexes into the plan would over-charge every sp500 trade at the sp600 floor.
The team only trades real-Webull-fillable edges, so I scope to the cheapest close fills (sp500) — the
only universe where this premium has a tradable shot. "Edge too small for sp400/sp600 costs" is a
documented outcome, not an untested claim.

## Variants (4) — only `chosen` goes to the holdout
| name | hold | hedged | extra |
|---|---|---|---|
| **`h1_sp500`** (chosen) | 1 (close A-2 → close A-1) | yes | — |
| `h2_sp500` | 2 (close A-3 → close A-1) | yes | is a 2-session pre-window better? |
| `h1_mom_sp500` | 1 | yes | prior-5-session return > 0 at entry (buy pre-announcement winners) |
| `h1_raw_sp500` | 1 | no (raw) | market-level vs firm-specific premium |

**`chosen` is PRE-REGISTERED = `h1_sp500`** — the idea card's primary rule: the cleanest single
pre-announcement session (Laarits' 24h window), lowest cost exposure. It is **not** picked by best
train t. best-of-N luck t ≈ 1.67 (4 variants). The other three are a robustness map for the Skeptic,
never carried to the holdout:
- `h1_raw ≫ h1_sp500` → the effect is market beta during earnings season, not a firm-specific risk
  premium (and would not be separately tradable) — a research read, NOT a switch of chosen.
- `h2 ≫ h1` → the edge is not in the final 24h.
- `h1_mom ≫ h1` → it is a momentum effect, not an uncertainty premium.

## Universe / fills / costs
- `entry_at` = close, `exit_at` = close, `universe` = ["sp500"]. Real-spread floor ≈ 6.4 bps RT.
- `cost_bps` = 8 (floor + ~1.6 bps impact buffer; charged = max(8, floor)).
- `cluster` = **day**: earnings cluster into ~4 seasons/yr, so many names share one exit date and are
  positively correlated within a day. Day-clustering is required so the t is not inflated by that.
- `metric` = hedged (paper judged at `real_hedged_bps`).

## Windows (family `pre_earnings` — entirely clean, no prior search/holdout)
- **Train:** 2003-01-01 … 2015-12-31.
- **Holdout:** 2016-01-01 … 2026-10-24 (the recent, arbitraged, post-publication era — this directly
  tests the main decay risk below; buffer before earnings data ends 2026-11-02 / daily ends 2026-11-06).
- Trades are scored by **exit date**.

## What would KILL it (kill conditions)
1. **Chosen train t < 2.0 or mean ≤ 0** → dead automatically (no holdout spent).
2. **Holdout t < budget bar (floor 3.0) or mean ≤ 0** → dead. The 2016+ holdout is the real test: if
   train passes but the holdout collapses, the premium was arbitraged away after the 2020-21 papers.
3. Net ≤ 0 after the 8 bps close cost at the 1-session hold → not tradable for this user.

## Central risks (for the Skeptic)
1. **Scheduling look-ahead (the main one).** Entering at close A-2 assumes the announcement date A was
   *known* two sessions ahead. Companies normally pre-announce earnings dates weeks out, and Yahoo's
   stored date is the realized one; a 2-session lead is short enough that the date is almost always
   already confirmed, but some reports are "estimated" and shift. Our data has no confirmed/estimated
   flag, so this cannot be fully removed in backtest — flagged, not mitigated. (The paper test is
   leak-free: V4's live calendar only ever shows the scheduled date.)
2. **Survivorship.** Only *current* S&P 500 membership exists (no point-in-time), biasing a LONG
   signal UP — a pass is NOT conservative on this axis. The Skeptic should weight it.
3. **BMO/AMC timing.** We use the announcement's calendar session A and exit at close A-1; this is safe
   whether the report is before-open or after-close (we are flat a full session before an AMC release,
   and before the next-morning open for a BMO release). No time-of-day field is needed for safety.
4. **Overlap with V4 EPRE.** EPRE already trades this event window-adjacent; if the pre-announcement
   drift is EPRE's main driver the two share economic risk. This test holds a *different* (pre-only)
   window, so a pass here is still informative, but the Director should treat them as correlated.

## Promotability
PROMOTABLE. Earnings dates are scheduled/public; V4 EPRE refreshes a nightly Yahoo calendar
(`data/calendar/earnings_calendar.csv`). `strategy.py` reads that live feed and emits a LONG on `asof`
when a stock's next report session is exactly the 3rd NYSE session after `asof` → the runner enters
close(asof+1) = A-2 and exits close(asof+2) = A-1 (hold 1, close→close). Future sessions are counted on
a self-contained NYSE holiday calendar. ~2000 S&P 500 reports/yr clustered into earnings weeks → a
20-40 trading-day window fills in a few months. `spec` entry_at=close, exit_at=close, hold_sessions=1,
metric `real_hedged_bps`, pass_mean_bps 5 / pass_t 2.0, 20-40 days. `max_signals_per_day`=25 caps the
busiest earnings days (noted — a few peak days are under-sampled; the clerk cannot quote more).
