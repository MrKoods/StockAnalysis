"""
SHARED: One cross-process rate limiter for every outbound API host.

Before this, pacing was scattered and inconsistent: sentiment_client.py had a
per-host 2s gap plus a circuit breaker; news_client.py's Alpha Vantage calls
had nothing (the 13s sleep old comments reference was dropped in the
retry-consolidation refactor); sec_edgar_client.py and the yfinance clients
had nothing at all. Three scan processes run per day (Windows Task Scheduler)
plus paper_updater, and they can overlap — so pacing state has to be shared
ACROSS processes, not just across one process's call sites.

Design: a persisted per-host record ``{last_call_ts, date, count}`` guarded by
shared.utils.atomic_io.exclusive_lock. ``acquire(host)`` opens the lock, sleeps
just long enough to honour the host's minimum inter-call interval, bumps the
daily counter, releases. The sleep happens WHILE the lock is held so two
processes can't both decide to fire at once; the lock's own
abandoned-after-timeout reclaim (longer than any interval here) covers a
process killed mid-sleep.

Not a token bucket: a plain minimum-interval + optional daily cap is enough for
these APIs — the binding constraints are Alpha Vantage's 25/day and its ~1
req/s throttle, not a burst allowance — and it is trivially crash-safe: a stale
timestamp just means the next call waits less, or not at all.
"""

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from shared.utils.atomic_io import atomic_write_json, exclusive_lock
from shared.utils.logger import get_logger

logger = get_logger(__name__)

# Referenced by name at call time (not baked into signatures) so tests can
# monkeypatch it and redirect state into a tmp_path — same pattern as
# shared/utils/logger.py's path constants.
_RATELIMIT_DIR = Path("data/cache/ratelimit")


class BudgetExhausted(RuntimeError):
    """Raised by acquire() when a host's daily cap is reached and block_on_cap is False."""


# host -> {min_interval: seconds between calls, daily_cap: max calls/day or None}
# Values are deliberately a little more conservative than each vendor's stated
# ceiling, since the counter is best-effort across processes.
DEFAULT_LIMITS: dict[str, dict] = {
    # 25/day free tier, throttles (HTTP 200 + {"Information": ...}) above ~1 req/s.
    "alphavantage.co":                 {"min_interval": 1.3, "daily_cap": 24},
    # 60 req/min free tier (reported in X-Ratelimit-Limit). 1.1s => ~54/min.
    "finnhub.io":                      {"min_interval": 1.1, "daily_cap": None},
    # RapidAPI free plan, 500,000 req/month hard cap, no hourly sub-limit
    # (verified from headers 2026-08-29). No real pacing concern.
    "stocktwits.p.rapidapi.com":       {"min_interval": 0.4, "daily_cap": None},
    # RapidAPI Pro, 10,000/month (~475/trading-day). Cap the day to stay clear.
    "seeking-alpha.p.rapidapi.com":    {"min_interval": 1.6, "daily_cap": 400},
    # SEC fair-access allows ~10 req/s; stay well under and serialize.
    "www.sec.gov":                     {"min_interval": 0.25, "daily_cap": None},
    "data.sec.gov":                    {"min_interval": 0.25, "daily_cap": None},
    "efts.sec.gov":                    {"min_interval": 0.25, "daily_cap": None},
    # yfinance does not hit one clean host; callers pass host="yfinance".
    "yfinance":                        {"min_interval": 1.0, "daily_cap": None},
}

# Fallback for any host not in the table — gentle, uncapped.
_FALLBACK = {"min_interval": 0.5, "daily_cap": None}

_LOCK_TIMEOUT = 30.0  # comfortably longer than any min_interval above


def host_for_url(url: str) -> str:
    """Return the netloc of `url`, lowercased, for use as a limiter key."""
    return (urlparse(url).netloc or url).lower()


def _limits(host: str) -> dict:
    return DEFAULT_LIMITS.get(host, _FALLBACK)


def _state_path(host: str) -> Path:
    safe = host.replace("/", "_").replace(":", "_")
    return _RATELIMIT_DIR / f"{safe}.json"


def _load(path: Path) -> dict:
    try:
        import json
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def acquire(host: str, *, block_on_cap: bool = False) -> None:
    """
    Block until it is this host's turn to be called, then record the call.

    host: either a bare host key from DEFAULT_LIMITS, or a full URL (its netloc
      is extracted). Pass "yfinance" for yfinance calls.
    block_on_cap: when the daily cap is hit — False (default) raises
      BudgetExhausted so the caller can degrade to a fallback source; True
      sleeps until the next UTC day instead (only sane for a background job).

    Never raises anything except BudgetExhausted. A locking/IO failure logs a
    warning and lets the call through unpaced rather than blocking a scan.
    """
    if "://" in host or "." in host and "/" in host:
        host = host_for_url(host)
    lim = _limits(host)
    path = _state_path(host)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        _RATELIMIT_DIR.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(path.with_suffix(".json.lock"), timeout=_LOCK_TIMEOUT):
            state = _load(path)
            count = int(state.get("count", 0)) if state.get("date") == today else 0

            cap = lim["daily_cap"]
            if cap is not None and count >= cap:
                if not block_on_cap:
                    raise BudgetExhausted(
                        f"{host}: daily cap {cap} reached ({count} calls today)"
                    )
                # Background-job path: wait for the day to roll over.
                _sleep_to_next_utc_day()
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                count = 0

            last_ts = float(state.get("last_call_ts", 0.0))
            wait = lim["min_interval"] - (time.time() - last_ts)
            if wait > 0:
                time.sleep(min(wait, lim["min_interval"]))

            atomic_write_json(path, {
                "date": today,
                "count": count + 1,
                "last_call_ts": time.time(),
            })
    except BudgetExhausted:
        raise
    except Exception as exc:  # locking/IO problem — do not block the scan
        logger.warning(f"rate_limiter: {host}: pacing skipped ({exc})")


def _sleep_to_next_utc_day() -> None:
    now = datetime.now(timezone.utc)
    tomorrow = (now.replace(hour=0, minute=0, second=0, microsecond=0)).timestamp() + 86400
    time.sleep(max(1.0, tomorrow - now.timestamp()))


def usage(host: str) -> dict:
    """Return {date, count, daily_cap, remaining} for `host` — for health checks / observability."""
    if "://" in host:
        host = host_for_url(host)
    lim = _limits(host)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    state = _load(_state_path(host))
    count = int(state.get("count", 0)) if state.get("date") == today else 0
    cap = lim["daily_cap"]
    return {
        "date": today,
        "count": count,
        "daily_cap": cap,
        "remaining": (cap - count) if cap is not None else None,
    }


def note_remaining(host: str, remaining: Optional[int]) -> None:
    """
    Record a vendor-reported remaining-budget hint (e.g. Finnhub's
    X-Ratelimit-Remaining header). Advisory only — logs a warning only when the
    hint is near zero so an about-to-bite budget is visible.

    Note: Finnhub's X-Ratelimit-Remaining counts down within a rolling ONE-MINUTE
    window and resets to the per-minute limit (60) each minute — it is not a
    daily budget. Our 1.1s pacing already caps throughput at ~54/min, so only a
    genuinely tiny value (window nearly spent) is worth a line in the log.
    """
    if remaining is None:
        return
    if "://" in host:
        host = host_for_url(host)
    if remaining <= 2:
        logger.warning(
            f"rate_limiter: {host}: vendor reports only {remaining} calls left in the current window"
        )
