# Director notes

## Resolved - don't repeat (TEAM.md "Settled facts" has the detail)
- 2026-11-10 = POWER LOSS (09:52-15:23), a gap, nothing to fix. quotes.py too_late guard exists since 11-11.
- G2 retired (tasks off). ON1 auto-retires on its real-price FAIL (dispatcher does it). Don't ask the user.
- V3/V4 are read-only: the team can't retire G2/ON1 via gate (no gate entry); that's the user's V3 session.
- earnings_events / earnings-announcement-premium holdout is SPENT (EPRE Round-7 t4.0 incl S&P 600 + ESUR,
  both on 2018-26). Any "announcement premium" / pre-earnings / EPRE-shaped idea = a live-edge duplicate -> drop,
  don't queue. V4 EPRE's universe is the full 1,490 S&P 500/400/600 (RULES.md).
- Veins now exhausted here: calendar (every variant dropped on cadence/mining), single-8-K LONG (all screened
  out, screen luck-t 2.84 beats nothing), pre_earnings, self_tender, proxy_contest, seo_offering, 10k/10q_timing,
  insider (no clean period). Remaining 8-K angles need text parsing we don't have.
- Un-paper-tradable cadence (<~20 trade-days/yr: calendar, pre-holiday) can NEVER build a 20-40d paper test -> drop.
- Small-cap-ONLY LONG keeps inverting and killing ideas (reg-fd, analyst-init, restructuring, activist-13d,
  proxy-contest). If an idea is a small-cap-only long, require the Researcher to test full S&P 1500 too.
- The gate refuses any metric but real_bps/real_hedged_bps; a paper PASS with real-price FAIL/COLLECTING = "not yet".

## How I queue (the standing rule)
Fill to <=2 in research only with ideas whose raw edge clears the ~25 bps cost floor WITH MARGIN (Auditor Rec-1,
accepted 11-14). Be strict: drop weak/duplicate ideas, leave the pipeline short rather than pad it; the Scout
refills every weekday. Every drop note states the reason (the Scout reads state/dropped_ideas.md).

## reports/2026-11-14-auditor.md — my response
- **Rec 1 (USER) — C8: event-research vein exhausted, 0 paper promotions in 6 wks; build 8-K/press-release NLP or
  redirect.** Not mine to action — carried to the user (outbox 11-17). Note: special-dividend-drift-long (queued
  today) exercises the filing_text() text-filter path on already-held 8-K text — a partial step toward the NLP
  unlock with no new data. Agree the single-8-K/small-cap-event vein is dry; the two ideas queued today are the
  differentiated kind (day-0 premium re-test; text-filtered drift), not more undifferentiated single-8-K tests.
- **Rec 2 (me) — confirm a day-0-entry 8-K idea can be paper-replicated before queuing (C9): ACCEPTED, and now
  resolved.** The day-0 paper-trading infra was BUILT 2026-11-14 (same day as this audit — TEAM.md settled fact):
  edgar_live.filings_asof + paper_runner.run_day0 price entry_session-close ("entry_at":"same_close") strategies
  before the 12:56 Quote Clerk. So entry_session-close 8-K/13D ideas ARE now paper-replicable; C9's dead-end risk
  is closed. Both ideas queued today use day-0 close entry and clear this.
- **Rec 3 (Engineer) — no action needed: not mine.** Noted; machinery fixes sound.

## reports/2026-11-07-auditor.md — my response
- **Rec 1 (me) — single-8-K/low-event vein near-exhausted; bias the queue to edges clearing the cost floor with
  margin: ACCEPTED, and acted on.** 11-14 queued material-impairment-short (~150 bps gross vs ~30 bps short cost);
  dropped eap-small-cap-long (EPRE duplicate). The vein did exhaust on schedule. This is now a standing rule above.
- Rec 2 (Scorekeeper, scorecard after-cost pairing): Scorekeeper retired 11-13; the scorecard is a script now and
  the 11-13 one pairs +0.070R after costs with the +0.15 after-cost bar. Resolved, not mine to act on.
- Rec 3 (User, ON1 paper PASS != tradeable): carried to the user; ON1 real-price now -85.4 bps/7d, FAIL-trajectory.

## Prior auditor reports — closed
- 2026-10-29 & 2026-10-31: queue-replenishment + insider-verdict-only + Quote-Clerk recs all addressed/resolved
  (see reports/2026-10-31-director.md and 2026-11-07-director.md). Don't reopen.

## Live tests — current read (from scripts; don't copy numbers into notes, re-read snapshot.txt)
- V2 rank: NO-GO near-certain at 100 trades (~11-20..25). On NO-GO the rank track closes (user's call).
- V3 ON1 paper: cliff-edge, barely above FAIL floor. ON1 real-price: FAIL trajectory, verdict ~11-24 -> auto-retire.
- V4 EPRE paper: cp A CROSSED 11-17 at 1,003 trades = CONTINUE (+29.0 bps hedged >= -20 FAIL floor; cp A is
  FAIL-only, authorizes nothing). Continues to cp B (3,000 trades) where small real money is first possible.
- V4 EPRE real-price: the bright spot (+91.7 bps, 12.6 bps spread, t 1.48 on 5 exit days - too early to trust t).
  Real-money gate = cp B AND the real-price condition. Nothing for the user to do yet.

## Watch next run
- Pipeline now 2/2 (queued 11-17: activist-13d-long-day0, special-dividend-drift-long). Both should move to
  `planned`; confirm the Researcher honors day-0 entry_session close + (special-div) text-filter false-positive check
  and event-count/power. Don't queue more until room reopens.
- V2 rank go/no-go at 100 (~11-20..25); ON1 real-price verdict ~11-24 (did the dispatcher auto-retire on FAIL?).
- Two quote captures FAILED 11-17 (QuoteOpen 06:31, QuoteClose 12:56, result 1) - Engineer to diagnose (likely
  logged-out again per 11-13 settled fact); not mine. Ops already alerted.
- Saturday = weekly report + read/respond to the newest Auditor report.
</content>
</invoke>
