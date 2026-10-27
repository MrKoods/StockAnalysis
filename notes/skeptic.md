# Skeptic notes

## Reviewed
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
