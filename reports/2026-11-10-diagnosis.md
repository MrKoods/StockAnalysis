# Diagnosis 2026-11-10

## Failure: Team_QuoteClose

**Result code:** 2147946720 (0x800710E0 — Windows kills process via TerminateProcess)

### Timeline
- 10:00 AM PT: last scan_ops entry before the gap — machine went to sleep
- 12:56 PM PT: scheduled QuoteClose window
- 15:30 PM PT: machine woke; Windows Task Scheduler ran the missed task; scan_ops resumed and detected the failure

### What the script did (and didn't do)
`tools/quotes.py capture close` was invoked. `needs("close", today)` returned ~19 tickers:
- 19 EPRE trades with `exit_day = 2026-11-10` (OXY, TDG, TTWO, HIMS, HRB, NOVT, ONTO, QLYS,
  SANM, SLAB, CWEN, CWST, GSHD, LIF, LQDA, MARA, NHI, SBH, TDW — lines 969–987 of epre_ledger.csv)
- 0 ON1 picks with `day = 2026-11-10` (ledger has no 11-10 entries; ON1 makes picks at 15:35–15:50 ET
  which is after the quote capture window)

The script passed the "no tickers" early-exit, loaded configs from `team/roles.json`, and launched the
`claude` subprocess (`subprocess.run(cmd, timeout=240)` at `tools/quotes.py:168`). Windows killed
`python.exe` before the subprocess could return — before `state/logs/2026-11-10-quote_clerk-close.jsonl`
was written (line 175), before `state/usage.csv` was updated, and before `state/logs/2026-11-10-quotes.log`
was written via `log()`.

### Why Windows killed the process
Error 0x800710E0 is the exit code Windows Task Scheduler injects when it terminates a process via
`TerminateProcess()`. The machine woke from a 5.5-hour sleep at ~15:30 PT. The task was run immediately
on wake ("run as soon as possible after a missed start"). Windows either:
(a) killed the task because the system was not fully resumed, or
(b) killed it due to a Task Scheduler "stop if running longer than" limit configured shorter than
    the claude subprocess needed.

scan_ops.json shows `gave_up:StockAnalysis_Team_QuoteClose = true` with two issue entries — the task
was attempted twice (possibly once at 12:56 during a brief wake and once at 15:30 when properly awake).

### Effect on data
- **No data lost.** quotes.csv was not modified; the EPRE ledger is unchanged.
- **Missed capture.** The 19 EPRE exit-day trades above will not be re-priceable (they needed today's
  closing bid/ask for their exit leg). These trades ARE in the EPRE paper ledger with `hedged_bps`
  scored, but they will not appear in `paper/epre_real_price_status.json`.
- **ON1 unaffected.** No ON1 close picks for 11-10 were due; the open capture ran fine (73/73, ok).

### Current real-price status (from dispatch at 15:30)
- ON1 real-price: 5 days, 368 trades, real_mean -24.2 bps, paper_mean (same trades) +71.3 bps,
  avg half-spread 49.3 bps, real_t -0.54. Verdict: COLLECTING (need 15 days).
  Spread gap ≈ 95.5 bps/trade. Direction is negative at 5 days — worth watching.
- EPRE real-price: 447 trades, 4 exit days, real_hedged_mean +82.5 bps, paper +82.6 (spread 12.2 bps),
  real_t 1.05. No verdict gate — feeds checkpoint B condition.

### Suggested fix
**User action needed:** `python tools/quotes.py capture close` can be run manually right now.
Webull provides the official closing price after hours; `qday == today` will still pass. This would
recover close quotes for the 19 EPRE exit-day tickers before they go stale (Webull intraday quotes
expire overnight). Without this, the 11-10 exit batch is permanently a real-price gap.

The Engineer cannot fix the root cause (Windows Task Scheduler policy) — that is a Windows task
configuration the user controls. The sleep/wake behavior can be addressed by configuring the
QuoteClose task to "do not start if the trigger time was missed by more than 1 hour", which would
prevent the late wake-run entirely and make the gap explicit rather than causing a failed close-time run.
