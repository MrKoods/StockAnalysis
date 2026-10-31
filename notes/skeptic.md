# Skeptic notes

## Reviewed
- 2026-10-31 **split-announcement-drift** -> PASS to holdout. Pre-registered h4_r2 (hold 4, fwd
  splits >=2:1), train net t 3.08 (week-clustered) > luck 1.89, 65 bps gross / 282 wks / 395 trades.
  Clean look-ahead (leak-free first_session = open after SEC accepted ts; dated by `announced` not
  filing_date). r2 tier strong at both holds (3.26/3.08) = coherent, not a spike. Survives 1.5x cost.
  Best (h2_r2 3.26) NOT chosen; plan committed before results. First corporate_events family use.
  HOLDOUT WATCH: (1) survivorship (today's SP1500 back-applied) biases LONG up -> marginal t =
  survivorship not edge; (2) only ~812/3189 fwd splits have found announcement -> skews larger;
  (3) IF promoted, strategy.py skips premarket same-day announcements (after-close runner can't trade
  them) -> paper is a thinner SUBSET of backtest, mean may drift. Promotable (unlike insider-cluster).

- 2026-10-27 **insider-cluster-buys** -> PASS to holdout. Pre-registered n2_h5_m75k (NOT best-of-N;
  best was h10 t4.04). Train net t 2.9 > luck 2.23, 82 bps/wk net, 299 wks. Clean on look-ahead
  (filing-date trigger, strictly-next-session open entry), costs (survives 1.5x), sign-stable across
  all 12 variants. Distinct from the family's spent single-officer-$100k holdout (t2.3).

## Watch on the holdout (2014-2017) — for the Holdout Keeper / Director
- **Survivorship**: current sp500/400 applied back to 2006; biases long returns UP. Modest for a
  5-session hedged hold but if the holdout t comes in MARGINAL (just under/over 3.0), read it as
  survivorship, not a real edge. The whole insider family carries this — no point-in-time universe.
- **Thin holdout**: 4 yrs, cluster events rare -> few signal-weeks -> wide CI. A high t on tiny n is
  suspect.
- **DO NOT PROMOTE** this to paper regardless of holdout: only insider source is SEC quarterly bulk
  Form-345 (publishes months late); a 3-5d hold can't fire on time live. Research verdict only until a
  near-real-time Form-4 feed exists (blocked by no-new-paid-services limit). Gate should refuse.

## Standing reminders for future reviews
- insider family holdouts are scarce: one spent (2018-26, single-officer). Cluster idea uses 2014-17.
  Any further insider idea needs a genuinely fresh window or it's dead on arrival (no re-peeking).
- Reported bps/t in train_result are NET (jobs.py:99 subtracts cost_bps) and week-clustered.
- queued next: insider-officer-buys (single officer >=$100k) — will overlap the spent holdout; check
  its window carefully.
