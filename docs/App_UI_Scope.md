# StockAnalysis — UI Addendum to Project_Scope.md

**Status:** Draft for review — not yet merged into Project_Scope.md
**Adds to:** v2.2.0 architecture (5-category confidence score — Technical/Market
Positioning/Sentiment/News/Fundamental — Near-Miss alerts, Event Severity Gate, Trade
Selector). Reviewed against current code (`swing_config.yaml`, `run_swing_model.py`,
`paper_runner.py`, `discord_alerts.py`, `notification_router.py`) 2026-07-18; corrections
below replace the earlier v2.0.0-era draft, which described a Reddit-inclusive Sentiment
Ensemble Modifier that no longer exists.

---

## 1. Purpose

Add a local desktop UI that runs alongside the existing pipeline so results, layer
breakdowns, and Discord notifications are viewable without leaving the app, and are
retained across sessions for later review.

This is additive only. No existing scoring logic, config format, or Discord delivery
is changed. The UI is a new consumer of data the pipeline already produces.

## 2. Stack

- **Framework:** PySide6 (Qt for Python) — native desktop window, runs in-process,
  no browser/server/JS toolchain required
- **Persistence:** SQLite, single file (`stockanalysis_history.db`), stdlib `sqlite3`
- **Threading:** Scan runs execute on a background `QThread` so the UI stays responsive;
  results are emitted back to the main thread via Qt signals

## 3. Screens

### 3.1 Results (default view)
- Watchlist tickers (NVDA, AMD, AVGO, TSM, MU, ASML) grouped by outcome category:
  - **Trade Recommended** — score ≥ 90, includes selected trade structure, EV, entry/exit.
    If `event_gate_blocked` is set on this result, show a distinct "⚠️ Active Event" badge
    (same treatment as the orange Discord embed) — the signal still surfaced on its own
    merits (advisory gate, not a veto, since v2.1.1), but the flag must stay visible, not
    buried in a notes string.
  - **Passed Filters, No Trade** — cleared the 90 threshold but filtered out at trade
    selection or portfolio gating (no viable R:R structure, `can_open_new_position`
    denial — correlated-pair limit, max open positions, PDT, circuit breaker state)
  - **Near-Miss** — score in [80, 90) (`NEAR_MISS_THRESHOLD`–`CONFIDENCE_THRESHOLD`,
    added v2.2.0). Awareness-only, never a trade candidate — keep visually distinct
    (e.g. grey, same low-key treatment as its Discord alert) so it can't be mistaken
    for a real signal
  - **No Signal** — below the near-miss floor
- Each ticker row expandable to a **layer breakdown** (current 5-category system,
  `scoring_weights` in `swing_config.yaml`, maximums sum to 100):
  - Technical (0–40), Market Positioning (0–20), Sentiment (0–15), News (0–15),
    Fundamental (0–10)
  - Sentiment sub-signals: StockTwits ratio + velocity, Seeking Alpha engagement
    (Reddit was removed from the sentiment layer prior to this UI work — no
    dormant/active flag needed, there's nothing to flag)
  - Regime / sector-rotation / earnings / cross-ticker / seasonality / macro modifiers
    applied on top of the base score (`modifier_bounds` in config) — show these
    alongside the 5 category scores so the breakdown matches what's logged per-ticker
    in the audit trail (`write_audit_entry` in `run_swing_model.py`)
  - Final composite score vs. threshold
- Filter/sort controls: by category, by score, by ticker
- Historical scans browsable via a run-date selector (pulls from DB, not just latest)

### 3.2 Notifications / Alerts feed
- Chronological log of every alert type the pipeline sends: trade, near-miss, health
  check, event-gate triggered/expired, circuit breaker, missed scan, open-position
  critical event (see §5 `notifications.alert_type` for the full list)
- Each entry: timestamp, ticker (nullable — health-check/circuit-breaker alerts aren't
  per-ticker), alert type, payload summary, Discord delivery status (sent/failed).
  Discord and this feed are the only two places alerts surface — there is no email or
  SMS channel, so there's nothing beyond Discord status to track
- Persisted — feed loads from DB on launch, appends live during a run
- Filterable by ticker and by notification type

### 3.3 Config
- Editable view of `swing_config.yaml` (layer weights, thresholds, filter cascade
  parameters)
- Edits write back to the YAML file directly — config remains the single source of
  truth for the pipeline; the DB never stores config, only results/notifications
- Validation before save (e.g. weights sum correctly, thresholds in valid range) to
  prevent a bad edit from silently breaking a run

### 3.4 Run control
- "Run Scan" button, available from any screen, with a **scan-type selector**
  (`pre_market` / `mid_session` / `post_close`) — these carry different Alpha Vantage
  budgets (6 / 6 / 8 calls) and different behavior (missed-scan check on every type,
  health-check alert only on `post_close`), so a single undifferentiated button doesn't
  match how the pipeline actually branches
- Targets `paper_trading/paper_runner.py`, **not** `run_swing_model.py` — every model
  version through v2.2.0 is explicitly marked not-yet-eligible-to-go-live per
  CHANGELOG.md's own versioning rule, and the paper runner is what's actually executed
  daily today. If/when the model goes live, this becomes a config choice, not a
  hardcoded assumption baked into the UI
- **Alpha Vantage budget guard before running:** read `av_call_count.json` (same file
  `_read_av_call_count()` in `run_swing_model.py` already reads) and show "X/25 calls
  used today, this run will use ~Y more." Warn (or block, TBD by user preference at
  build time) if the run would exceed the 25-call daily hard limit. This matters more
  than a generic confirmation dialog — the real risk of an accidental manual run isn't
  the click, it's silently starving a later *scheduled* scan of its AV budget
- Button is **hard-disabled** (not just visually busy) for the duration of a run, not
  merely showing a progress indicator over it — a second concurrent invocation risks
  corrupting one of the shared state files (`position_state.json`,
  `fundamental_state.json`, `positioning_state.json`, `gate_state.json`,
  `av_call_count.json`, `audit_log.csv`) via concurrent writes
- Progress indicator while the background thread runs
- Run completion triggers a UI refresh (new results + notifications appear without
  restarting the app)

## 4. Data flow

```
Pipeline run
   │
   ├─> scoring.py / trade_selector → per-ticker CategoryResult + trade recommendation
   │
   ├─> build_notification() — single shared step
   │        │
   │        ├─> Discord (existing behavior, unchanged) — see note below
   │        └─> SQLite (notifications table)
   │
   └─> DB write (scan_runs, ticker_results, layer_scores tables)
            │
            └─> UI queries DB on launch + subscribes to live updates during a run
```

Key point: **one notification-building step, two delivery targets.** This avoids
duplicating logic between what gets sent to Discord and what gets shown in the UI.

**This is not how alert delivery is structured today, and closing that gap is real
scope, not a side effect.** Currently there is no single `build_notification()` seam —
sends happen from ~7 separate call sites in `run_swing_model.py`/`paper_runner.py`
(`_try_send_trade_alert`, `_try_send_health_check`, `_try_send_event_gate_alert` /
`_expired`, `_try_send_cb_alert`, `_try_send_missed_scan_alert`,
`_handle_open_position_critical_event`). Delivery itself is simple now —
`notification_router.py` just posts to Discord, no priority routing, no email/SMS
escalation — but the multiple call sites are still real. Two implementation paths,
pick one deliberately before building:
1. **Do the consolidation** — introduce the shared `build_notification()` step for
   real, have every call site route through it. Cleanest long-term, but it's a
   refactor of tested, currently-working alert code, not an additive-only change —
   budget real review/test time for it.
2. **Wrap instead of consolidate** — leave the ~7 call sites as-is, add a DB-write
   alongside each one individually. Lower risk to existing behavior, but there are now
   ~7 places that must be kept in sync instead of one, and it's easy for a future new
   alert type to add Discord delivery and forget the DB write.

Recommendation: option 2 first (ships the UI without touching working alert code),
revisit option 1 later if the duplication actually becomes a maintenance problem.

## 5. DB schema (sketch)

```sql
scan_runs (
  run_id INTEGER PRIMARY KEY,
  run_timestamp TEXT,
  scan_type TEXT,        -- 'pre_market' | 'mid_session' | 'post_close'
  config_snapshot TEXT   -- always stored (see §6 decision) — full raw swing_config.yaml
                          -- text as used for this run, not a hash
)

ticker_results (
  result_id INTEGER PRIMARY KEY,
  run_id INTEGER REFERENCES scan_runs,
  ticker TEXT,
  category TEXT,           -- 'trade_recommended' | 'passed_no_trade' | 'near_miss' | 'no_signal'
  composite_score REAL,
  trade_structure TEXT,    -- nullable
  expected_value REAL,     -- nullable
  event_gate_blocked INTEGER,   -- 0/1 — advisory flag (v2.1.1), independent of category;
                                 -- a 'trade_recommended' row can still have this set to 1
  event_gate_trigger TEXT  -- nullable, matched trigger text when event_gate_blocked=1
)

layer_scores (
  layer_score_id INTEGER PRIMARY KEY,
  result_id INTEGER REFERENCES ticker_results,
  layer_name TEXT,          -- 'technical' | 'market_positioning' | 'sentiment' | 'news' | 'fundamental'
                             -- (the 5 scored categories — see §3.1) plus modifier rows:
                             -- 'regime' | 'sector_rotation' | 'earnings' | 'cross_ticker'
                             -- | 'seasonality' | 'macro_overlay'
  score REAL,
  detail_json TEXT          -- layer-specific breakdown, e.g. individual indicator contributions
)

notifications (
  notification_id INTEGER PRIMARY KEY,
  run_id INTEGER REFERENCES scan_runs,
  ticker TEXT,               -- nullable — health_check and circuit_breaker alerts
                              -- aren't per-ticker, don't force a value here
  alert_type TEXT,           -- 'trade' | 'near_miss' | 'health_check' | 'event_gate_triggered'
                              -- | 'event_gate_expired' | 'circuit_breaker' | 'missed_scan'
                              -- | 'open_position_critical_event'
  timestamp TEXT,
  payload_json TEXT,
  discord_status TEXT        -- 'sent' | 'failed' | 'skipped' — the only delivery channel;
                              -- no email/SMS, so no other status columns are needed
)
```

Note: `source_layer` from the original sketch is replaced with `alert_type` above — a
clearer name for what the column actually distinguishes.

## 6. Decisions (previously open questions)

- **`config_snapshot` per run: yes — store the full raw YAML text, not a hash.**
  `swing_config.yaml` is ~450 lines / ~10KB; at 3 scans/day that's roughly 11MB/year
  even storing full text every time, trivial for SQLite. Raw text (not a hash) is what
  makes the ablation/diffing use case actually usable later, and it fits how this
  project already treats config as an audit artifact — every scoring-relevant change
  already requires a version bump + backtest entry in CHANGELOG.md, so having the exact
  YAML behind every stored result extends that same accountability model into the DB.
- **Retention: keep everything indefinitely, no pruning.** Same math as above — even
  years of history at 6-ticker/3-scans-a-day scale stays in the low tens of MB total.
  Not worth building a retention policy for a problem that won't materialize at this
  watchlist size. Revisit only if the watchlist grows by an order of magnitude.
- **"Run Scan" confirmation: skip the generic "are you sure?" modal — replace it with
  the Alpha Vantage budget guard described in §3.4.** A confirmation dialog protects
  against the wrong risk. The real risk is a manual run silently consuming AV budget
  that a later *scheduled* scan needs — `post_close` alone uses 8 of the 25 daily
  calls. Show live budget usage before running and warn/block if the run would exceed
  it, and hard-disable the button for the duration of the run (also in §3.4) so a
  double-click can't trigger a second concurrent run against the same state files.

## 7. Explicitly out of scope for this addition

- No live/streaming updates mid-scan beyond a progress indicator (no per-layer live
  ticking — results appear when the run completes)
- No remote/multi-device access — local desktop app only
- No changes to scoring logic, filter cascade, or Discord message format
