# Scout notes (max ~150 lines)

## Last run: 2026-11-04
- Run reason: scouting (1 idea waiting, target 10)
- Ideas at start: 1 (turn-of-month at `idea`; analyst-initiation-buy queued; reg-fd-small-cap-disclosure awaiting_review)
- Added 3 new ideas: restructuring-bounce, quarter-end-window-dressing, early-10k-drift
- Total at `idea` stage after run: 4 (turn-of-month + 3 new)
- Still 6 short of target 10; next run should add up to 4 more

## Current ideas at `idea` stage (as of 2026-11-04)
1. turn-of-month — calendar_effects, 4d
2. restructuring-bounce — 8k_2_05, 3d (kitchen-sink recovery; screen t=1.79; small-cap subset)
3. quarter-end-window-dressing — calendar_effects, 2d (institutional window dressing; Carhart 2002)
4. early-10k-drift — 10k_timing, 3d (early annual filer = confidence signal; Chambers & Penman 1984)

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
- 5.02 officer departure vs appointment: needs text parsing to separate departure from appointment direction
- dividend capture: needs a dividend ex-date calendar (not in catalog)
- options expiration pinning reversal: needs options open interest data (not in catalog)

## What is left in 8-K space (for future runs)
Screen results summary (best-of-57 luck t ~2.84 — no type is a lead at that threshold):
- 7.01 Reg FD: t=2.31 → registered as reg-fd-small-cap-disclosure
- 2.04 debt acceleration trigger: t=1.99 (3d); but only ~23/yr events (276 holdout) — marginal power; mechanism "disclosure resolves distress uncertainty" is plausible but weak; skip unless researcher wants to try
- 2.05 restructuring: t=1.79 (3d) → registered as restructuring-bounce
- 3.03 shareholders' rights change: t=-1.98 (1d); short side, thin after costs; skip
- All other types: t < 1.5, skip

## Calendar effects family status (2026-11-04)
- turn-of-month: at `idea` stage
- quarter-end-window-dressing: at `idea` stage (2 ideas in calendar_effects OK; 0 holdouts used so far)
- Both use same family; each would use 1 holdout look if tested; family bar = 3.0

## Ideas to target next run (need ~4 more to approach 10)
1. Any remaining 8-K types not yet considered — but most below t=1.5; 2.04 is the only marginal one remaining
2. SSRN/arXiv: search for specific effects using filings() that aren't event-screen-based
   - e.g., multiple 8-K items filed simultaneously as a complexity signal?
   - e.g., 1.01 material agreement announcement timing (after hours vs. during session)?
3. 10-Q analog to early-10k-drift: early quarterly filers? Same family (10k_timing) — researcher can combine both
4. Cross-asset: sector rotation using capital flow (Webull get_stock_capital_flow) — but this is not in research_data.py catalog
5. Any new mechanism from SSRN search next run: focus on "event-driven anomalies", "SEC filings", "small cap"

## Budget state (2026-11-04)
- 8k_2_05: search 2005-2013 (screen); holdout 2014-2026 clean
- calendar_effects: 0 holdouts, 0 search variants (turn-of-month + quarter-end-window-dressing both at idea)
- 10k_timing: new family, entire history clean
- analyst_ratings: 0 holdouts, 0 search variants (new family, clean)
- 8k_7_01: search 2005-2013 (screen + train); holdout 2014-2026 clean
- earnings_events: 2 holdouts used; NO CLEAN HOLDOUT - don't add more
- corporate_events: 1 holdout used (fail)
- insider: 2 holdouts used; bar = 3.00 (no clean period)

## Areas/sources checked 2026-11-04
- Academic: Kinney & Trezevant (1997), Elliott & Shaw (1988) [restructuring/kitchen-sink]
  Carhart et al. (2002), Sias (2007), Haugen & Lakonishok (1988) [window dressing]
  Chambers & Penman (1984), Begley & Fischer (1998) [10-K timeliness]
- Screen: re-read screen.md; 2.05 is the best remaining lead after 7.01
- SSRN search done: 8-K trading gap paper (Cohen et al.) - not directly testable; Q-end window dressing confirmed in literature
- Graveyard: no conflicts found for any new idea; 10k_timing is completely new family

## Watch for next run
- Did Director queue restructuring-bounce, quarter-end-window-dressing, early-10k-drift?
- Was analyst-initiation-buy's "Initiated" action verified in ratings() loader?
- Need ~4 more ideas to reach target 10; consider: 8-K timing-of-filing ideas, SSRN search for new mechanism
- Check if reg-fd-small-cap-disclosure passed Skeptic; if so, pipeline is moving
