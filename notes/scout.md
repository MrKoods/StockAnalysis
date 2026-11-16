# Scout notes (max ~150 lines)

## Last run: 2026-11-16
- Run reason: scouting (0 ideas waiting, target 10)
- Ideas at start: 0 (eap-small-cap-long and material-impairment-short both DROPPED by Director since last run)
- Added 2 new ideas: activist-13d-long-day0 (activist_13d), special-dividend-drift-long (8k_8_01)
- Pipeline now at 2 ideas

## Last run: 2026-11-13
- Added 2 ideas: eap-small-cap-long, material-impairment-short — both since DROPPED by Director

## Resolved — don't repeat
- 8-K screen (57 variants, 2005-2013 LONG direction): ALL VIABLE LONG LEADS EXHAUSTED
  (best-of-57 luck t ~2.84; none clear 50 bps gross + mechanism threshold)
- announcement_premium: GONE — both earnings-announcement-risk-premium and eap-small-cap-long dropped;
  holdout burned by EPRE; DO NOT propose more variants
- earnings_events: NO CLEAN HOLDOUT (2 holdouts used by EPRE + ESUR) — don't add more
- pre_earnings, self_tender, proxy_contest, seo_offering, calendar_effects, 10q_timing, analyst_ratings:
  MINED — search periods used, all tested ideas dead or dropped
- 10k_timing: both early (dropped) and late (dropped) angles exhausted; no viable angle
- insider: no clean holdout
- Reg FD (8k_7_01): small-cap tilt ran OPPOSITE to thesis (t=-2.77); skip more variants
- FOMC pre-announcement drift: now in catalog (rd.fomc()), but 8 events/yr fails the 60/yr threshold;
  per-trade edge ~49 bps is AT the floor and can't paper-test; leave in Needs data
- Five straight small-cap-only LONGs came out WRONG direction; next small-cap-only idea needs unusually
  strong specific evidence

## 8-K space: untested angles that remain
- 8k_8_01 SHORT direction: undifferentiated screen was -7.6 bps at 5d (t=-1.58); below floor
- 8k_8_01 text-filtered LONG: special-dividend and buyback-authorization are live ideas (registered
  special-dividend-drift-long; register buyback-announcement-long as a future variant in same family)
- activist_13d: day-0 re-test registered (activist-13d-long-day0); holdout 2016-2026 clean
- 8k_1_01 M&A announcement (target): priced on day-0 before dispatch; residual arb spread only 20-40 bps
- 8k_2_01 acquirer short (stock deals): 116/yr but needs text to identify stock vs cash; 20d edge unclear
- 8k_5_07 shareholder votes: not in filing_text; undifferentiated signal absent from screen leads; skip
- 8k_3_03 rights changes / 8k_5_03 charter amendments: screen signal weak even for SHORT; skip

## Day-0 re-test candidates
- **activist-13d-long-day0** (activist_13d): REGISTERED this run. TEAM.md: 13D day-0 +51 bps t 5.6
- **issuer-self-tender-long-day0** (self_tender): HOLD - TEAM.md shows day-0 +78 bps t 3.8, but
  estimated 20-50 events/yr for S&P 1500 is below the 60/yr minimum; Director/researcher should
  verify actual SC TO-I event count from filings() before registering

## Needs data (not registered — the user decides)
- sp-reconstitution: S&P 400/600 addition announcement dates (spglobal.com press releases)
- analyst-upgrade-on-pullback: ratings() has no live feed; train 2012-2019 / holdout 2020-2026 clean
- dividend capture: needs ex-date calendar (not in catalog)
- options expiration pinning reversal: needs options open interest (not in catalog)
- SC 13G new blockholder: initial passive 5%+ holder; Edmans (2009) weak signal; deferred
- SEC comment letter short (UPLOAD form): direction contaminated without text parsing; skip
- special dividend LARGER size filter: a future variant of special-dividend-drift-long (8k_8_01);
  holds same holdout, register after first variant is queued
- Buyback authorization LONG (8k_8_01 variant): open-market repurchase authorization via 8.01 text
  filter; Peyer & Vermaelen (2009) ~200 bps first month; 500-800 events/yr; register after
  special-dividend-drift-long is queued (same family, would raise holdout bar)
- FOMC pre-announcement drift: rd.fomc() now in catalog; Lucca & Moench (2015) +49 bps in 24hr
  before FOMC; 8 events/yr is below the 60/yr threshold → can't paper-test; deferred
- After-hours earnings negative preannouncement (8k_2_02 subset): close+1 entry misses day-0 reaction;
  residual drift to close+3 likely only 20-30 bps; below threshold
- IPO lockup expiration short: needs lockup expiration dates (not in catalog)

## Family status (clean holdouts only shown)
| family | status |
|---|---|
| activist_13d | holdout 2016-2026 clean; day-0 re-test registered |
| 8k_8_01 | holdout 2014-2026 clean; special-dividend-drift-long registered |
| 8k_1_01 | holdout 2014-2026 clean; no strong angle found without deep M&A text filtering |
| 8k_2_01 | holdout 2014-2026 clean; acquirer short needs text; short-term evidence weak |
| 8k_2_03 | holdout 2014-2026 clean; screen undifferentiated; mixed signal without text |
| 8k_5_03 | holdout 2014-2026 clean; screen weak; needs specific mechanism evidence |
| 8k_5_07 | holdout 2014-2026 clean; not in filing_text; screen not a lead |
| corporate_events | holdout 2018-2026 FAILED; don't use |
| pre_holiday | clean but Director dropped 2 variants; next needs very strong bps evidence |
