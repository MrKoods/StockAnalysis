# Researcher notes

## 2026-10-31 — split-announcement-drift (planned, check+smoke pass)
- Five files in research/split-announcement-drift/ + strategies/split-announcement-drift/.
- Family `corporate_events` (NOT in catalog's used-periods table → whole history clean). Bar 3.00.
- Windows: train 2001-01-01..2017-12-31, holdout 2018-01-01..2026-10-06 (most recent = arbitraged
  era, the hard/honest test). Daily ends 2026-10-06; announcements begin ~2001.
- Signal: FORWARD split (ratio>1), entry at OPEN of rd.splits `first_session` (leak-free), exit CLOSE
  H sessions later. SPY-hedged gross; cost 20 bps; cluster "week".
- 6 variants: H∈{2,4} × ratio tier {r1>1, r2≥2, r3≥3}. chosen PRE-REGISTERED = `h4_r2`.
- Smoke (2001 only): h4_r2 11 trades/10 wk; h*_r3 0 (3:1 rare early) — fine, r3 is robustness only.
- PROMOTABLE (unlike insider): split 8-Ks are same-day public; splits.parquet rebuilt each dispatcher
  run → strategy.py reads it live. BUT forward splits ~30/yr → paper min_days=20 takes many months.

### Data facts learned (reuse next time)
- rd.splits(None) cols: ticker, ex_date, ratio(>1 fwd,<1 rev), announced, announce_form,
  announce_accession, found_by, first_session (NaT if no announcement found). ~812 of 3189 fwd splits
  have an announcement. first_session already leak-free (first open after `announced`, cut at cutoff).
- rd.daily index may not be exactly normalized → normalize both sides + use positional iloc, don't
  trust label equality. Pattern used in test.py _trades.
- strategy.py (NOT static-scanned) reads data/edgar/splits.parquet via parents[2]/data/edgar. bars
  index in paper_runner are datetime.date, not Timestamp.

## 2026-10-27 — insider-cluster-buys (planned, check+smoke pass)
- Five files written in research/insider-cluster-buys/ and strategies/insider-cluster-buys/.
- Windows: train 2006-01-01..2013-12-31, holdout 2014-01-01..2017-12-31. Insider family already
  spent its one holdout on 2018-2026 (v3-insider-buys), so that window is OFF LIMITS for this family.
  Insider data starts 2006 → 2014-2017 is the most recent still-free holdout.
- Signal: >=2 distinct RPTOWNERCIK open-market Form-4 purchases (TRANS_CODE 'P'), each >=$25k, within
  a 5-CALENDAR-DAY window by FILING_DATE (filing-date window = leak-free), total >=$75k. Long next
  open, exit close H sessions later. SPY-hedged gross bps; cost 20 bps; cluster "week".
- `chosen` is PRE-REGISTERED = n2_h5_m75k (not best-of-train). Other 11 configs reported for Skeptic
  robustness only. Keeps holdout a single hypothesis; luck bar = floor 3.0 (K=2).
- Smoke (2006 only): 62-74 trades, 33-37 weekly periods per variant → sample is fine.

### Data facts learned (reuse next time)
- Insider parquet cols: ACCESSION_NUMBER, TRANS_DATE, TRANS_CODE(P/S), TRANS_SHARES,
  TRANS_PRICEPERSHARE, TRANS_ACQUIRED_DISP_CD(A/D), FILING_DATE(%d-%b-%Y), ISSUERTRADINGSYMBOL,
  DOCUMENT_TYPE, RPTOWNERCIK, RPTOWNER_RELATIONSHIP(contains 'Officer'/'Director'), RPTOWNER_TITLE.
  One reporting owner per accession (drop_duplicates in the fetch). V3 blueprint: StockAnalysis-V3/
  daytrade/research/events.py load_insider/ins.
- rd.daily() archive columns are LOWERCASE: open/high/low/close/volume. SPY.parquet exists in daily_max.
- rd.insider(start) loads year>=start.year files and filters FILING_DATE in [start, cutoff].
- jobs.py FORBIDDEN scans test.py only (regex includes `\bopen\(`, read_parquet, Path(, StockAnalysis,
  requests/http). Column string "open" is fine (no paren). strategy.py is NOT scanned.

### Gotchas / watch
- PAPER PROMOTION BLOCKED: only insider source is SEC QUARTERLY bulk files (months of lag) → a 3-5d
  hold cannot trade live off it. strategy.py encodes the rule for the record but says DO NOT PROMOTE
  until a near-real-time Form-4 feed exists. Director should not promote even on a holdout pass.
- Survivorship: only CURRENT sp500/sp400 membership available (no point-in-time). Biases a long
  signal UP; flagged in PLAN for the Skeptic.
- Chicken/egg: strategy.py must equal `chosen`, but chosen is picked during the train run AFTER commit.
  Solved by pre-registering chosen deterministically (n2_h5_m75k) so strategy.py can match exactly.
  Use this pattern for future ideas unless a selection-by-t is truly needed.
- Smoke prints "chosen None" — harness quirk (res['chosen'] only set when phase literally == 'train'/
  'holdout', not 'smoke'). Not a bug.
