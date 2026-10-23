# V3 = the research lab

This branch is where trading ideas are TESTED before any of them becomes a model. It is not itself a model.

- `daytrade/research/` - every search, protocol and holdout run (rounds 1-7, ~380k configs). Write-ups and
  pre-registered protocols are in `research_results/` (start with `RESEARCH_LOG.md`).
- An idea that passes a pre-registered holdout graduates to its OWN version branch with its own paper test
  and fixed pass/fail rule. First graduate: the earnings announcement premium -> `Version-4`
  (`../StockAnalysis-V4`, 2026-10-23).
- Still running here until their verdicts (~Nov-Dec 2026): G2 gap fade and ON1 overnight (forward + paper).
  If they fail they are archived and V3 keeps only the lab. Status of every module: `../StockAnalysis-V4/MODULES.md`.
- Retired 2026-10-23: C6 sweep forward test, Dukascopy minute download, minute auto-research (tasks disabled,
  code and data kept).
