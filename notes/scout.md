# Scout notes (max ~150 lines)

## Last run: 2026-10-29
- Run reason: scheduled scouting (4 ideas waiting, target 5)
- Ideas at start: 4 (insider-officer-buys, turn-of-month, sp-reconstitution, earnings-contagion all at `idea`)
- insider-cluster-buys moved to `dead` since last run (holdout FAIL t=1.11 vs bar 3.00)
- Added 1 new idea: split-announcement-drift â†’ 5 ideas total at `idea` stage (target met)

## What was done
- Wrote ideas/split-announcement-drift.md
- Registered via tools/ideas.py add (succeeded)
- Registry verified: 5 ideas at `idea` stage

## Current ideas at `idea` stage (as of 2026-10-29)
1. insider-officer-buys â€” insider, 1-5d
2. turn-of-month â€” calendar_effects, 4d
3. sp-reconstitution â€” index_events, 3-7d (NEEDS announcement dates scraped from spglobal.com)
4. earnings-contagion â€” earnings_events, 1-3d (needs GICS sector mapping via yfinance)
5. split-announcement-drift â€” corporate_events, 3-5d (NEEDS announcement dates from EDGAR 8-K scrape)

## 2026-10-30 (set by the user's session, not a Scout run)
Rule tightened in prompts/scout.md: only ideas testable with research_data.py alone AND with an untouched
holdout window. Dropped: split-announcement-drift, sp-reconstitution (need scrapes), insider-officer-buys
(insider family has no clean period left). Remaining: turn-of-month, earnings-contagion.
earnings-contagion also DROPPED (user, 2026-10-30): earnings_events searched 2000-2017 and held out
2018-2026 twice (EPRE, ESUR) - no clean window. Don't add more earnings_events ideas.

## Needs data (not registered - the user decides if the data is worth getting)
- sp-reconstitution: S&P 400/600 addition announcement dates (spglobal.com press releases)
- split-announcement-drift: forward-split announcement dates (EDGAR 8-K full-text search)
- any insider idea: a clean insider period no longer exists in the 2006+ SEC data

## Data sourcing notes for Director (older)
- sp-reconstitution: S&P 400/600 announcement dates not in archives; free one-time scrape spglobal.com
- split-announcement-drift: 8-K announcement dates not in archives; EDGAR full-text search "stock split" 8-K filings; yfinance only has effective dates
- earnings-contagion: GICS sector mapping available free via yfinance; no external scrape needed

## Budget state (2026-10-29)
- insider: 2 holdouts used (cluster failed t=1.11; officer-buys still at idea); bar = 3.00
- earnings_events: 4832 variants, 2 holdouts; heavily mined; bar = 3.00
- calendar_effects: 0 holdouts (new family from turn-of-month)
- index_events: 0 holdouts (new family from sp-reconstitution)
- corporate_events: 0 holdouts (new family from split-announcement-drift)

## Areas/sources checked
- Academic: Ikenberry et al 1996, Grinblatt et al 1984, McNichols & Dravid 1990, Desai & Jain 1997 (stock splits)
- Graveyard: no conflicts found for split-announcement-drift (earnings events â‰  corporate events; no split ideas previously tested)
- Considered and rejected: OPEX week (no directional signal without strike data), post-earnings analyst revision (need consensus revision data not in archives), earnings gap fade (too close to graveyard daily gap fade)

## Watch for next run
- Were the 5 `idea` stage ideas queued by Director?
- sp-reconstitution and split-announcement-drift both need data sourcing â€” flag if stalled
- If insider-officer-buys goes to planned/tested, note the insider family now has 2 holdouts; next bar stays 3.00
- If more ideas needed: options-expiry pinning is plausible but needs directional filter; Russell reconstitution (annual, June only) is out-of-horizon
