# Scout notes (max ~150 lines)

## Last run: 2026-11-06
- Run reason: scouting (0 ideas waiting, target 10)
- Ideas at start: 0 at `idea` stage (turn-of-month and nt-filing-short already `queued`)
- Added 4 new ideas: activist-13d-long (activist_13d), pipe-short (8k_3_02), year-end-loser-reversal (calendar_effects), late-10k-short (10k_timing)
- Total at `idea` stage after run: 4 (target 10; still 6 short — needs more next run)

## Current ideas at `idea` stage (as of 2026-11-06)
1. activist-13d-long — activist_13d, 3d (close entry; Brav et al. 2008 +7.2% at 13D)
2. pipe-short — 8k_3_02, 3d (SHORT; close entry; screen t=-1.70; Brophy et al. 2009)
3. year-end-loser-reversal — calendar_effects, 5d (S&P 400 down>=20% YTD; close Dec 26)
4. late-10k-short — 10k_timing, 3d (SHORT; close entry; exclude NT filers)

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
- analyst-upgrade-on-pullback: ratings() has no live feed (ratings source is NO); if live feed added,
  train 2012-2019 / holdout 2020-2026 clean; mechanism: Jegadeesh et al. (2004) show upgrades most
  informative in cold stocks
- 5.02 officer departure vs appointment: needs text parsing to separate departure from appointment direction
- dividend capture: needs a dividend ex-date calendar (not in catalog)
- options expiration pinning reversal: needs options open interest data (not in catalog)
- SC 13G new blockholder: initial SC 13G filing = passive 5%+ holder; mechanism weaker than 13D
  (activist); February filing cluster is a paper-runner concern; Edmans (2009) shows 13D is strong but
  13G (passive) is weak; deferred

## What is left in 8-K space (for future runs)
Screen results summary (best-of-57 luck t ~2.84 — no type is a lead at that threshold):
- 7.01 Reg FD: t=2.31 → registered (now DEAD); small-cap tilt ran negative
- 2.04 debt acceleration trigger: t=1.99 (3d) → registered as debt-acceleration-bounce (dropped)
- 2.05 restructuring: t=1.79 (3d) → registered (now DEAD)
- 3.02 unregistered equity sale: t=-1.70 (3d) → registered as pipe-short (SHORT, close entry)
- 3.03 shareholders' rights change: t=-1.98 (1d); after 20bps costs = +4.9; too thin; skip
- 3.01 delisting notice: t=-1.47 (3d); after 20bps = +22.6; t too low; skip
- 4.02 restatement: t=-1.13 (5d); after 20bps = +31.4; t too low; skip
- All other types: t < 1.5, skip
- 8k_5_01 (change in control): NOT in screen; 384 events/20yr = ~19/yr → ~180 holdout events; too sparse

## Calendar effects family status
- turn-of-month: at `queued`
- quarter-end-window-dressing: `dropped`
- year-end-loser-reversal: at `idea` (S&P 400, down>=20% YTD)
- All: 0 holdouts used, 0 search variants; family bar = 3.0

## Budget state (2026-11-06)
- activist_13d: new family, entirely clean
- 8k_3_02: search 2005-2013 (screen, 3 variants); holdout 2014-2026 clean
- 10k_timing: new family, entirely clean; early-10k-drift dropped, late-10k-short at idea
- calendar_effects: 0 holdouts, 0 search variants
- 10q_timing: search 2001-2015 (team train run); holdout clean (early-10q-drift DEAD)
- nt_filing: new family; nt-filing-short at queued
- 8k_2_04: search 2005-2013 (screen); holdout 2014-2026 clean
- 8k_7_01: fully mined (screen + train run); small-cap effect ran opposite; don't add more
- earnings_events: 2 holdouts used; NO CLEAN HOLDOUT - don't add more
- corporate_events: 1 holdout used (fail)
- insider: 2 holdouts used; bar = 3.00 (no clean period)
- analyst_ratings: search 2012-2019 (train run); live feed=NO → no more ideas

## Ideas to target next run (need ~6 more to approach 10)
1. Fresh SSRN/arXiv search for 2022-2025 papers on short-horizon event studies — do a WebSearch
2. CORRESP filing (SEC scrutiny signal): filings(forms=['CORRESP']); mechanism speculative (response
   vs. notice ambiguous); skip unless clearer direction found in literature
3. SC 13D/A amendments (activist increases position): same activist_13d family; weaker signal;
   possibly worth testing as a separate variant if activist-13d-long clears train
4. DEF 14A timing (proxy_timing family): proxy filing timing signal; academic support thin; deferred
5. Any fresh 8-K angle requires text parsing (not available)

## Areas/sources checked 2026-11-06
- Screen: re-read; 3.02 pipe-short added based on close-entry economics (screen t=-1.70 viable at 12bps)
- fill_costs.json: confirmed close fills SP500=6.6bps, SP400=12.0bps round trip (much cheaper than open)
- Academic: Brav et al. (2008), Klein & Zur (2009) [activist 13D]; Brophy et al. (2009),
  Chaplinsky & Haushalter (2010) [PIPE short]; Reinganum (1983), Poterba & Weisbenner (2001) [year-end]
  Ettredge et al. (2000), Kinney & McDaniel (1989) [late filer short]
- Catalog: verified activist_13d is a new family; 8k_3_02 holdout clean; 10k_timing clean; calendar_effects clean
- Budget: all new families at bar 3.0; no holdout conflicts

## Watch for next run
- Did Director queue any of today's 4 ideas?
- Need ~6 more ideas to reach target 10; need fresh academic sources — run WebSearch for recent SSRN papers
- pipe-short: researcher needs to verify SHORT direction support in paper_runner.py (same issue as nt-filing-short)
- activist-13d-long: researcher should verify that filings(forms=['SC 13D']) indexes by TARGET company, not filer
- year-end-loser-reversal: january-small-cap-reversal was dropped; Director may drop this too — that's OK
- late-10k-short + nt-filing-short overlap concern: researcher must exclude NT filers from late-10k-short dataset
