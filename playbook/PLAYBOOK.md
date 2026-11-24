# Team playbook - where to look and how to research (the Strategist's living document)

<!-- FIXED BY THE USER - START (tools/playbook.py rewrites this; edits are undone) -->
## Fixed by the user (the Strategist cannot change this section)
- Goal: make money trading, reached through this team running and improving itself (2026-11-14).
- No real money until a pre-registered test passes its frozen rule. Agents never place orders.
- Account $20k (< $25k pattern-day-trader line): real money only for rules that hold overnight or longer.
- Options are allowed (defined-risk), forward-recorded only (paper/options) - no free option history.
- Costs are real Webull spreads (team/fill_costs.json); an idea needs gross edge >= 3x its round-trip cost
  (code-enforced in tools/ideas.py). Holdouts are used once; luck bars count every variant ever tried.
- Ask the user before paying for any data or service. Cadence (Scout Mondays to 5 ideas, 1 idea in research at a
  time) is the user's setting in tools/dispatch.py - propose changes, don't assume them.
<!-- FIXED BY THE USER - END -->

Who reads this: the Scout (before proposing), the Director (before queueing or dropping), the Researcher (before
writing a plan). Where this file and a role's prompt disagree on WHERE to look or HOW to research, this file wins;
on limits and rules, the prompt and TEAM.md win. The Strategist rewrites everything below the fixed section once a
month from the evidence in state/review_pack.md, and logs each change at the bottom.

## Search priorities (best first)
1. **Risk premia and forced flows in index ETFs**, held at least overnight: overnight vs intraday ETF returns
   (waiting on measured ETF spreads - `python tools/quotes.py etf`), month-end / rebalance flows, macro-
   announcement premia (FOMC: `rd.fomc()`). Why first: the one survivor in ~400,000 variants (EPRE) is a risk
   premium; ETF spreads are ~1 bp, single stocks 7-250 bps.
2. **Volatility-premium timing** (VIX vs realized, term structure - `rd.cboe()`), as forward-recorded option
   rules on paper/options. Selling options unconditionally is ~equity beta (2007-17 CBOE indexes): only a timed or
   selective rule that clears the hurdle at the recorded spreads counts.
3. **Longer holds (10-60 days) at the close** on slow mechanisms, whole S&P 1500.

## Stop or deprioritize (evidence)
- Single 8-K event types, single-stock holds <= 5 days: 19+ ideas, mean chosen t about -0.2, none survived.
- Small-cap-only longs: five in a row came out the wrong direction.
- Families with no clean holdout left (state/data_catalog.md) - announcement_premium, earnings_events, insider.

## Research methods (lessons)
- **Winner's curse is large**: ideas that reached a holdout kept ~35% of their chosen train t (mean train t 3.0 ->
  holdout 1.05). Expect a train t of ~3 to become ~1. Plans should be powered for a holdout t of half the train t
  or less, use few variants, and state in PLAN.md the holdout t they expect.
- Prefer ideas with a published, replicated effect and a named payer (who is on the other side and why).
- Day-0 entry matters for event ideas: a day late, the move is usually priced.

## Open questions the team can't answer without new data
- (Strategist: keep this short - one line each: what, which data, free or paid. Paid = a proposal to the user.)

## Change log (newest first; one line per change: date - what - evidence)
- 2026-11-24 - first version, written in the user's session from the 2026-11-21 deep review and the 2026-11-23
  direction (TEAM.md "Where the search goes").
