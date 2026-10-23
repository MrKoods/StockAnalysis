# StockAnalysis V4 - earnings announcement premium (EPRE)

A small, single-purpose model. Buy a stock at the close two sessions before the session that first reacts
to its earnings report, and sell at that reaction session's close. It came out of the V3 research lab
(PROTOCOL12, 2026-10-23). It is the only strategy so far to pass a pre-registered out-of-sample test
(2018-2026: +18.8 bps/trade after costs, hedged, t 4.0). Paper only until RULES.md says otherwise.

| Command | When (scheduled, Pacific) | What |
|---|---|---|
| `python -m epre calendar` | weekdays 17:15 | refresh next earnings date + time for ~1,490 stocks (~30 min) |
| `python -m epre signals` | weekdays 12:38 (15:38 ET) | Discord: BUY-at-close / SELL-at-close lists; logs every trade |
| `python -m epre evaluate` | weekdays 13:45 (16:45 ET) | score trades whose exit close happened; Discord results + verdict |
| `python -m epre status` | any time | print the running verdict |

Add `--dry-run` to print instead of posting/writing (`signals --dry-run --day=YYYY-MM-DD` replays a date).

Files: `epre/` code, `data/universe/` frozen index lists, `data/calendar/earnings_calendar.csv`,
`data/paper/epre_ledger.csv` (the paper record), `RULES.md` (fixed decision rule), `MODULES.md`
(status and cleanup dates for every model across V2/V3/V4). Only `.env` key needed: `DISCORD_WEBHOOK_URL`.
