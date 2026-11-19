# Scout notes (max ~150 lines)

## Last run: 2026-11-19
- Run reason: scouting (0 ideas waiting, target 10)
- Ideas at start: 0 (activist-13d-long-day0 and special-dividend-drift-long both DEAD since last run)
- Added 3 new ideas: buyback-announcement-long (8k_8_01), acquirer-stock-deal-short (8k_1_01),
  antitakeover-adoption-short (8k_5_03)
- Pipeline now at 3 ideas
- Screen read to inform decisions: 8k_5_02 undifferentiated -3 to -6 bps (too weak for 15d CFO short),
  8k_1_01 ≈ 0 bps undifferentiated (diluted by targets/cash deals), 8k_5_03 -6 to -16 bps undifferentiated

## Last run: 2026-11-16
- Added 2 new ideas: activist-13d-long-day0 (activist_13d), special-dividend-drift-long (8k_8_01)
  — both since DEAD (train FAIL and Skeptic FAIL respectively)

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
- activist_13d: BOTH angles exhausted (original h3 t 0.17; day-0 re-test t -0.35). DONE.
- 8k_8_01 special-dividend variant: DEAD (Skeptic FAIL t 2.67 < luck bar 2.87); buyback-announcement-long
  now registered as the next variant (same family, holdout 2020-2026 clean)
- 8k_5_02 (officer changes): undifferentiated screen -3 to -6 bps (t -1.09 to -1.45); CFO sudden
  departure considered — academic literature (Mian 2001, Feng 2011) shows long-term underperformance
  (months/years) not 15-day drift; no published edge number for 15-day post-announcement window → skip
- 8k_2_01 acquirer short: short-term screen ≈ 0 bps; evidence weak for 20d hold → skip
  (Note: acquirer-stock-deal-short uses 8k_1_01, the ANNOUNCEMENT not the COMPLETION)
- 8k_5_07 shareholder votes: not in filing_text; undifferentiated signal absent from screen leads; skip
- 8k_3_03 rights changes: screen signal weak even for SHORT; skip

## Day-0 re-test candidates
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
- FOMC pre-announcement drift: rd.fomc() now in catalog; Lucca & Moench (2015) +49 bps in 24hr
  before FOMC; 8 events/yr is below the 60/yr threshold → can't paper-test; deferred
- After-hours earnings negative preannouncement (8k_2_02 subset): close+1 entry misses day-0 reaction;
  residual drift to close+3 likely only 20-30 bps; below threshold
- IPO lockup expiration short: needs lockup expiration dates (not in catalog)
- Russell 2000 reconstitution (new family): addition buys earn ~100-200 bps (Madhavan 2003); BUT needs
  Russell membership history not in catalog (not free); deferred
- CFO sudden departure short (8k_5_02): academic evidence exists but only for long-term (months);
  15-day residual drift post-day-0-close likely only 20-40 bps — below floor; revive if longer holds
  are worth testing or if screen shows better

## Family status (clean holdouts only shown)
| family | status |
|---|---|
| activist_13d | holdout 2016-2026 technically clean but BOTH angles exhausted (t 0.17, t -0.35); done |
| 8k_8_01 | holdout 2020-2026 clean (search 2005-2019 used); buyback-announcement-long registered |
| 8k_1_01 | holdout 2014-2026 clean (3 screen variants only); acquirer-stock-deal-short registered |
| 8k_5_03 | holdout 2014-2026 clean (3 screen variants only); antitakeover-adoption-short registered |
| 8k_1_02 | holdout 2014-2026 clean; screen flat (+4-7 bps); no published edge for 15-day drift |
| 8k_2_01 | holdout 2014-2026 clean; screen flat; completion returns mostly priced at announcement |
| 8k_2_03 | holdout 2014-2026 clean; screen flat; mixed signal without text |
| 8k_5_02 | holdout 2014-2026 clean; screen -3 to -6 bps; 15d edge below floor; skip unless longer hold |
| 8k_5_07 | holdout 2014-2026 clean; not in filing_text; screen not a lead |
| corporate_events | holdout 2018-2026 FAILED; don't use |
| pre_holiday | clean but Director dropped 2 variants; next needs very strong bps evidence |
