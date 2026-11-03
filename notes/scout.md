# Scout notes (max ~150 lines)

## Last run: 2026-11-03
- Run reason: scouting (1 idea waiting, target 10)
- Ideas at start: 1 (turn-of-month at `idea`; split-announcement-drift and sp-reconstitution both dead/dropped)
- Added 4 new ideas: pre-holiday-drift, january-small-cap-reversal, reg-fd-small-cap-disclosure, analyst-initiation-buy
- Total at `idea` stage after run: 5 (turn-of-month + 4 new)
- Still 5 short of target 10; next run should add 4 more

## Current ideas at `idea` stage (as of 2026-11-03)
1. turn-of-month — calendar_effects, 4d
2. pre-holiday-drift — pre_holiday, 1d (NYSE holiday calendar trigger)
3. january-small-cap-reversal — january_reversal, 5d (annual; power-limited ~20 year-clusters)
4. reg-fd-small-cap-disclosure — 8k_7_01, 1d (screen best of all types t=2.31; small-cap subset)
5. analyst-initiation-buy — analyst_ratings, 3d (verify "Initiated" action type in ratings() loader)

## 2026-10-30 (set by the user's session, not a Scout run)
Rule tightened in prompts/scout.md: only ideas testable with research_data.py alone AND with an untouched
holdout window. Dropped: split-announcement-drift, sp-reconstitution (need scrapes), insider-officer-buys
(insider family has no clean period left). Remaining: turn-of-month, earnings-contagion.
earnings-contagion also DROPPED (user, 2026-10-30): earnings_events searched 2000-2017 and held out
2018-2026 twice (EPRE, ESUR) - no clean window. Don't add more earnings_events ideas.

## 2026-10-30: SEC company-event data added (see state/data_catalog.md)
rd.filings() = every SEC filing + 8-K item codes since 2004 (officer changes, deals, restatements,
buybacks...); rd.splits() = splits with announcement dates. Each 8-K event type is a NEW family
with its whole history clean except screen (2005-2013) already used.

## Needs data (not registered - the user decides if the data is worth getting)
- sp-reconstitution: S&P 400/600 addition announcement dates (spglobal.com press releases)
- any insider idea: a clean insider period no longer exists in the 2006+ SEC data
- analyst initiation (registered but flagged): verify ratings() loader has "Initiated" action type distinct from upgrades

## What is left untested in 8-K space (for next runs)
Screen results summary (best-of-57 luck t ~2.84 — no type is a lead):
- 7.01 Reg FD: t=2.31 (closest to threshold) → registered as small-cap subset idea
- 2.04 debt acceleration trigger: t=1.93-1.99 (5d, 3d); only ~205 events in 9y = very sparse, power risk
- 2.05 restructuring/exit costs: t=1.79 (3d); +11.6 bps after 20 bps costs for small-cap subset; worth a card
- 3.03 shareholders' rights change: t=-1.76 to -1.98 (short side); shorts cost more → thin after costs
- 4.02 restatement: t=-0.96 to -1.13 (short side); sparse (329 events); thin after costs; skip
- All other types: t < 1.5, skip

Ideas to target next run (up to 4 more needed to reach ~9 ideas, still below target 10):
1. restructuring-announcement (8k_2_05): small-cap 3d, +11.6 bps after costs, t=1.79 in full sample
2. quarter-end-window-dressing (calendar/daily): buy prior-month winners last 2 days of quarter, sell at quarter+1; mechanism = institutional window dressing (Carhart et al. 2002)
3. material-agreement-momentum (8k_1_01): 1.01 is flat on average but a subset (large deals, specific sectors) may differ — only if a mechanism is found in literature
4. Any SSRN/arXiv paper with new mechanism not covered above — do a web search next run

## Budget state (2026-11-03)
- analyst_ratings: 0 holdouts, 0 search variants (new family, clean)
- pre_holiday: 0 holdouts, 0 search variants (new family, clean)
- january_reversal: 0 holdouts, 0 search variants (new family, clean)
- 8k_7_01: search 2005-2013 (screen); holdout 2014-2026 clean
- calendar_effects: 0 holdouts (turn-of-month at idea)
- insider: 2 holdouts used; bar = 3.00
- earnings_events: 2 holdouts used; NO CLEAN HOLDOUT - don't add more
- corporate_events: 1 holdout used (fail)

## Areas/sources checked 2026-11-03
- Academic: Lakonishok & Smidt (1988), Ariel (1990) [holidays]; Reinganum (1983), Keim (1983), Ritter (1988) [January]; Heflin et al. (2003), Bailey et al. (2003) [Reg FD]; Womack (1996), Barber et al. (2001) [analyst initiation]
- Graveyard: no conflicts found for any new idea; analyst-initiation differs from generic "analyst rating actions" (new coverage vs. opinion change)
- Screen: 7.01 is the only 8-K type near the luck threshold; registered as reg-fd-small-cap-disclosure

## Watch for next run
- Was analyst-initiation-buy's "Initiated" action type verified in ratings() loader?
- Were the 5 ideas queued by Director?
- Need 5 more ideas to reach target 10; add up to 4 next run
- Consider: restructuring-announcement (2.05), quarter-end-window-dressing, SSRN search for new mechanisms
