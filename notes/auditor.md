# Auditor notes

## 2026-10-29 — first audit (mid-week, by hand)
Checked the team's first full pipeline run: insider-cluster-buys → dead. Clean and honest:
plan-before-results order correct, pre-registered config (n2_h5_m75k) honored over the tempting
train-best h10 (t4.04), Skeptic evidence verified at the file:lines it cited, holdout ran once
(t1.11 vs 3.0) and killed it, graveyard+trials+budget+registry all consistent. No red flags.

### Open findings (for next audit — were these acted on?)
- **C1 OPEN**: `insider-officer-buys` parked at `idea`, but NO untouched holdout window remains for
  the insider family (2006-13 train, 2014-17 cluster holdout, 2018-26 officer holdout; data starts
  2006). Director's revival condition ("fresh period exists") can't be met → should be dropped.
  Recommended Director drop it. CHECK NEXT RUN: did it get dropped, or re-queued (the latter would
  head toward a peek).
- **C2 OPEN (structural)**: the team's research data for insiders is SEC quarterly bulk, which lags a
  quarter, so a strategy built on it can't be paper-traded as-is. Promotion correctly BLOCKED in PLAN.
  CORRECTION (from the builder, 2026-10-29): a live feed does NOT need a paid service - SEC EDGAR posts
  Form 4s free within ~2 business days and V2 already fetches Form 4 XML with its SEC user agent. So
  live insider paper-trading is a build task (wire a free EDGAR feed into the team's paper runner), the
  user's call, not a subscription. Watch: no insider idea promotes to paper until that feed exists.
- **C3 CLOSED - not a problem (my error)**: g2_paper_task.log being empty/stale is a KNOWN QUIRK (see
  "Known quirks" in prompts/scorekeeper.md): G2 health = its ledger, which updates. Don't re-flag.

### Things that looked GOOD and I don't need to re-verify unless they change
- Skeptic is doing real work (not rubber-stamping) — evidence was accurate.
- Director reports live tests honestly ("too early" / "likely NO-GO" used correctly).
- No orders, no promotions, registry empty, gate clean.

### Watch calendar
- 2026-11-05 V3 G2 paper 20-day cp (failing). 2026-11-10 AM ON1 paper cp (TEAM.md Key dates).
- mid-Nov V2 rank 100-trade go/no-go (far behind, likely NO-GO).
- Next audit is the regular Saturday slot (after the Director).
