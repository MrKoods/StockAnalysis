# Diagnosis 2026-11-11

## 1. SA /symbols/get-factor-grades — empty body, all retries exhausted

**What broke**: Seeking Alpha factor-grades API returned an empty (non-JSON) body at 05:30 PT during the premarket semiconductor fundamental fetch.

**Log sequence** (`StockAnalysis/data/logs/paper_runner_premarket_task.log`, lines 37184-37186):
```
05:30:12 WARNING  [SA /symbols/get-factor-grades] Attempt 1 failed: Expecting value: line 1 column 1 (char 0). Retrying in 30s.
05:30:46 WARNING  [SA /symbols/get-factor-grades] Attempt 2 failed: Expecting value: line 1 column 1 (char 0). Retrying in 60s.
05:31:48 ERROR    [SA /symbols/get-factor-grades] All retries exhausted. Last error: Expecting value: line 1 column 1 (char 0)
```

**Code path**: `shared/api_clients/seeking_alpha_client.py:104` calls `_sa_get("/symbols/get-factor-grades", {"symbol": ticker.lower()})`. Empty body → `json.loads("")` raises `ValueError: Expecting value: line 1 column 1 (char 0)`. The backoff module (`shared/api_clients/_http_backoff.py`) retried twice (30s + 60s) then gave up. `get_factor_grades()` returned `{}` per line 122-123.

**Cause**: Transient Seeking Alpha API outage (~05:30 PT premarket). Empty body (not a 4xx/5xx) suggests the SA RapidAPI endpoint returned a blank response, possibly a momentary timeout or rate limit at their gateway level.

**Effect on data**: Minimal. The fundamental pipeline fell back to "EPS growth trend carried forward, not AV-refreshed" for NVDA, AMD, ASML (AMAT had already succeeded before the SA call). All sector pipelines completed: 11/11, 12/12, 14/14 tickers processed successfully. 2 paper signals were logged (KEY, PFE). No trades lost. Fundamental scores for NVDA/AMD/ASML use stale (cached) SA factor grades for today's premarket scan.

**Fix suggestion**: No code change needed — the graceful fallback worked as designed. This is a recurring pattern of transient empty-body responses from SA at premarket hours (see also the similar RapidAPI empty-body warning for MCD at line 37635-37636, handled with the no-retry path). If SA is consistently unreliable before 05:30 PT, the Engineer could consider bumping the cache TTL for `sa_factor_grades` so a valid prior-day response is used without making a live call during the first premarket batch.

---

## 2. ON1 paper — day-20 checkpoint

See outbox for verdict. Full numbers in state/snapshot.txt.
