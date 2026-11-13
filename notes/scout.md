# Scout notes (max ~150 lines)

## Last run: 2026-11-13
- Run reason: scouting (0 ideas waiting, target 10)
- Ideas at start: 0 (pre-holiday-small-cap-long and earnings-announcement-risk-premium both DROPPED by Director)
- Added 2 new ideas: eap-small-cap-long (announcement_premium), material-impairment-short (8k_2_06)
- Total at `idea` stage after run: 2

## Last run: 2026-11-12
- Run reason: scouting (0 ideas waiting, target 10)
- Ideas at start: 0
- Added 1 new idea: pre-holiday-small-cap-long (pre_holiday) — now DROPPED by Director
- Total at `idea` stage after run: 1

## Last run: 2026-11-11
- Run reason: scouting (2 ideas waiting, target 10)
- Ideas at start: 2 (pre-earnings-premium, issuer-self-tender-long)
- Added 3 new ideas: pre-earnings-beat-streak, proxy-contest-long, earnings-announcement-risk-premium
- Total at `idea` stage after run: 5

## Current ideas at `idea` stage (as of 2026-11-13)
1. eap-small-cap-long — announcement_premium, 1d (LONG; close T-1→close T; Barber et al. 2013 ~120+ bps for S&P 600)
2. material-impairment-short — 8k_2_06, 3d (SHORT; close after filing→close+3; Li et al. 2011 ~150 bps; screen was LONG-only so SHORT is clean)

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

## 8-K space: ALL VIABLE SCREEN LEADS EXHAUSTED
Screen results summary (best-of-57 luck t ~2.84 — no type is a lead at that threshold):
- 7.01 Reg FD: t=2.31 → registered (now DEAD); small-cap tilt ran negative
- 2.04 debt acceleration trigger: t=1.99 (3d) → registered as debt-acceleration-bounce (dropped)
- 2.05 restructuring: t=1.79 (3d) → registered (now DEAD)
- 3.02 unregistered equity sale: t=-1.70 (3d) → registered as pipe-short (now DEAD; wrong direction)
- 3.03 shareholders' rights change: t=-1.98 (1d); gross -24.9 bps; below 50 bps threshold; skip
- 3.01 delisting notice: t=-1.47 (3d); gross -42.6 bps; below 50 bps threshold; skip
- 4.02 restatement: t=-1.13 (5d); gross -51.4 bps; barely meets 50 bps but t too low + only 25/yr + screen period contaminated; skip
- 5.02 director/officer change: t=-1.45 (1d); gross -3.3 bps; way below 50 bps; skip
- 4.01 auditor change: t=-0.26 to -0.45; near-zero; skip
- All other types: t < 1.5 or below 50 bps gross, skip
- 8k_5_01 (change in control): NOT in screen; 384 events/20yr = ~19/yr → too sparse
- 8k_2_06 (material impairment): screen tested LONG only; SHORT not tested → see material-impairment-short idea

## Needs data (not registered - the user decides if the data is worth getting)
- sp-reconstitution: S&P 400/600 addition announcement dates (spglobal.com press releases)
- any insider idea: a clean insider period no longer exists in the 2006+ SEC data
- analyst-upgrade-on-pullback: ratings() has no live feed (ratings source is NO); if live feed added,
  train 2012-2019 / holdout 2020-2026 clean; mechanism: Jegadeesh et al. (2004) show upgrades most
  informative in cold stocks
- 5.02 officer departure vs appointment: needs text parsing to separate departure from appointment direction
- dividend capture: needs a dividend ex-date calendar (not in catalog)
- options expiration pinning reversal: needs options open interest data (not in catalog)
- SC 13G new blockholder: initial SC 13G filing = passive 5%+ holder; Edmans (2009) shows 13D is strong
  but 13G (passive) is weak; deferred
- SEC comment letter short (UPLOAD form): academic support mixed; direction contaminated without text
  parsing; skip unless NLP added
- rights-plan-short (8k_3_03): screen -41.5 bps at 5d (below 50 bps threshold); Ryngaert (1988) avg
  only -34 bps (discriminatory pills -109 bps); direction ambiguous (adoption vs. removal); skip
- proxy contest (DFAN14A): ~15-25 events/year in S&P 1500; too sparse; mixed signal (now DEAD)
- SEO via 424B3: may supplement seo-short; but seo-short is now DEAD; leave alone
- FOMC pre-announcement drift: "80%+ of equity premium earned in 24hr before FOMC" (Lucca & Moench
  2015); mechanism strong; needs FOMC meeting dates from federalreserve.gov (8/yr, free, fixed calendar)
  → researcher could hardcode the calendar directly in a small lookup table in research_data.py;
  NO API needed; just 8 dates/year publicly available; strongly worth adding; per-trade edge ~25-50 bps
  which is BELOW the 50 bps threshold though (8 events/year × 25-50 bps = limited power too)
- special dividend announcement LONG: Hyun Ahn (SSRN 7249419) "The Special-Dividend Drift" finds
  ~1.2% abnormal return over days +2→+20 post-announcement; needs special dividend announcement
  identification from 8-K text (8.01 or press release) → needs text parsing or a dividend calendar
- IPO lockup expiration short: needs IPO lockup expiration dates
- Buyback announcement LONG (via 8-K 8.01 text filter): needs text parsing; 8.01 near-zero without filter
- After-hours earnings release short (8k_2_02 subset, acceptance_time >4PM): Doyle & Magilke (2009)
  shows 100 bps spread early vs late filers BUT close+1 entry means most day-0 reaction is priced;
  residual drift to close+3 may be only 20-30 bps (below 50 bps gross); skip

## Calendar effects family status
- turn-of-month: DEAD (train t=1.37)
- quarter-end-window-dressing: DROPPED (not tested)
- year-end-loser-reversal: at `dropped` (Director dropped; not in `idea` queue any more)
- quarter-end-winner-short: at `dropped` (Director dropped; Carhart 2002)
- train period 1999-2014 used by turn-of-month; holdout 2015-2026 clean
- Family bar = 3.0
- NOTE: Director has dropped 3+ calendar variants without testing; next calendar idea needs very strong direct
  academic evidence with specific bps number before proposing

## New family seo_offering status
- seo-short: DEAD (train t=-5.92; SHORT was -36 bps after cost; LONG was +36 bps but that's below 50 bps gross; skip)
- Entirely mined — don't add more seo_offering ideas

## New family pre_earnings status
- pre-earnings-premium: DEAD (train t=0.44, 1.09 bps after cost)
- pre-earnings-beat-streak: DROPPED by Director
- Family entirely mined — don't add more pre_earnings ideas

## New family self_tender status
- issuer-self-tender-long: DEAD (train t=-1.76, -38.38 bps after cost)
- Entirely mined — don't add more self_tender ideas

## New family proxy_contest status
- proxy-contest-long: DEAD (train t=0.31, 23.9 bps after cost)
- Entirely mined — don't add more proxy_contest ideas

## New family pre_holiday status
- pre-holiday-small-cap-long: DROPPED by Director (2026-11-12); family still clean for new variant
- NOTE: Director has dropped both pre_holiday variants; next pre_holiday idea needs very strong specific bps evidence

## New family announcement_premium status
- earnings-announcement-risk-premium: DROPPED by Director (broader S&P 1500 version)
- eap-small-cap-long: at `idea` (S&P 600 only; Barber et al. 2013 ~120 bps for small caps)
- Family entirely clean; holdout entirely untouched

## New family 8k_2_06 status
- Screen tested LONG direction 2005-2013; no notable screen result (undifferentiated buy was near zero)
- material-impairment-short: at `idea` (SHORT after impairment filing; Li et al. 2011 ~150 bps; holdout 2014-2026 clean)
- SHORT direction and holdout 2014-2026 clean

## Budget state (2026-11-13)
- announcement_premium: entirely clean; 1 idea at `idea` stage (eap-small-cap-long)
- 8k_2_06: screen 2005-2013 used (LONG only); 1 idea at `idea` stage (material-impairment-short)
- pre_holiday: entirely clean; both variants dropped by Director
- pre_earnings: search 2003-2015 (team train run); both ideas dead/dropped; MINED
- self_tender: search 2001-2015 (team train run); issuer-self-tender-long dead; MINED
- proxy_contest: search 2001-2015 (team train run); proxy-contest-long dead; MINED
- seo_offering: search 2001-2015 (team train run); MINED — no more ideas
- calendar_effects: search 1999-2014 (team train run); Director dropped 3 variants; MINED
- 10k_timing: entirely clean; early + late ideas dropped; no viable angle found
- 10q_timing: search 2001-2015 (team train run); MINED
- earnings_events: 2 holdouts used; NO CLEAN HOLDOUT - don't add more
- 8k_X_XX families: ALL screen (2005-2013) used for LONG direction; all viable LONG leads tried
- activist_13d: search 2001-2015 (team train run); dead
- analyst_ratings: search 2012-2019 (team train run); live feed=NO

## Ideas for future runs (need ~8 more after today; sources running low)
1. *** PIPELINE IS CRITICALLY LOW: only 2 ideas in queue. All major 8-K families screened out
   (LONG direction). Remaining SHORT ideas need text parsing. Future ideas need new data
   or literature areas not yet explored. ***
2. Next best bets given current data:
   - 8k_2_06 SHORT was the last clean 8-K angle found (registered today)
   - announcement_premium S&P 600 was the last clean EAP angle found (registered today)
   - 10k_timing has clean holdout but no viable academic angle found yet
   - Material agreement termination (8k_1_02 SHORT): needs text parsing to filter M&A
     terminations from routine contract endings; without text parsing signal too diluted
   - Completed acquisition acquirer SHORT (8k_2_01): unclear if 1-5 day post-close drift
     exists specifically for stock acquirers without text parsing to filter deal type
3. Advocate: user/Director should consider adding FOMC meeting dates (8/yr, free) if they
   want to unblock that angle; per-trade edge may be below 50 bps floor though
