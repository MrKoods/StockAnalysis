"""
SHARED: One on-disk, cross-process response cache for the API layer.

The three daily scans (pre-market / mid-session / post-close) run as separate
OS processes and share nothing but a handful of JSON state files. Almost every
external feed — news, per-ticker fundamentals, SEC filings, macro series,
earnings dates — barely changes between those three scans, yet each was
re-fetched from scratch every time. This cache collapses that: a fetcher asks
``cached_call(namespace, key, ttl, fetch_fn)`` and gets the stored value back
whenever it is younger than ``ttl``.

Storage: ``data/cache/<namespace>/<key>.json`` (or ``.pkl`` for non-JSON
values like OHLCV DataFrames), written atomically. No lock on read/write —
``atomic_write_*`` already prevents a torn file, and a rare double-fetch when
two scans miss the same key at the same instant is harmless (the fetch fns are
idempotent). TTLs are the caller's call; ``TTL`` below is a reference table.
"""

import json
import pickle
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from shared.utils.atomic_io import atomic_write_json
from shared.utils.logger import get_logger

logger = get_logger(__name__)

# Monkeypatched to a tmp_path in tests (see tests/conftest.py) — referenced by
# name at call time, same pattern as shared/utils/logger.py.
_CACHE_DIR = Path("data/cache")

# Reference TTLs (seconds). Callers pass an explicit ttl; these document intent
# and give one place to retune. "Until next close" is approximated as 8h — long
# enough that the 2nd/3rd scan of a session reuse, short enough to refresh
# overnight.
_H = 3600
TTL = {
    "ohlcv":              8 * _H,
    "vix":                4 * _H,
    "news":               4 * _H,
    "av_news_sentiment":  4 * _H,
    "stocktwits":         2 * _H,
    "sec_submissions":    20 * _H,
    "sec_companyfacts":   7 * 24 * _H,
    "sec_cik_map":        30 * 24 * _H,
    "fundamental_overview": 10 * 24 * _H,
    "sa_factor_grades":   20 * _H,
    "sa_fundamentals":    7 * 24 * _H,
    "finnhub_recommendation": 7 * 24 * _H,
    "finnhub_peers":      30 * 24 * _H,
    "finnhub_profile":    30 * 24 * _H,
    "earnings_calendar":  7 * 24 * _H,
    "macro_series":       20 * _H,
    "macro_series_slow":  7 * 24 * _H,   # fed funds, CPI — monthly data
}


def _safe(key: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in str(key))[:120]


def _paths(namespace: str, key: str) -> tuple[Path, Path]:
    base = _CACHE_DIR / _safe(namespace) / _safe(key)
    return base.with_suffix(".json"), base.with_suffix(".pkl")


def get(namespace: str, key: str, ttl: float) -> tuple[Optional[Any], Optional[float]]:
    """
    Return (value, age_seconds) if a cache entry for (namespace, key) exists and
    is younger than `ttl`, else (None, None). Never raises.
    """
    json_path, pkl_path = _paths(namespace, key)
    for path, loader in ((json_path, _load_json), (pkl_path, _load_pickle)):
        if not path.exists():
            continue
        try:
            stored_at, value = loader(path)
            age = time.time() - stored_at
            if age <= ttl:
                return value, age
            return None, None
        except Exception as exc:
            logger.warning(f"cache: unreadable entry {namespace}/{key} ({exc}) — ignoring")
            return None, None
    return None, None


def put(namespace: str, key: str, value: Any, *, format: str = "json") -> None:
    """Store `value` for (namespace, key). format='json' (default) or 'pickle'. Never raises."""
    json_path, pkl_path = _paths(namespace, key)
    try:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        stored_at = time.time()
        if format == "pickle":
            tmp = pkl_path.with_suffix(".pkl.tmp")
            tmp.write_bytes(pickle.dumps((stored_at, value)))
            tmp.replace(pkl_path)
            json_path.unlink(missing_ok=True)
        else:
            atomic_write_json(json_path, {
                "stored_at": stored_at,
                "stored_at_iso": datetime.now(timezone.utc).isoformat(),
                "value": value,
            })
            pkl_path.unlink(missing_ok=True)
    except Exception as exc:
        logger.warning(f"cache: failed to store {namespace}/{key} ({exc})")


def cached_call(
    namespace: str,
    key: str,
    ttl: float,
    fetch_fn: Callable[[], Any],
    *,
    format: str = "json",
    store_falsy: bool = False,
) -> Any:
    """
    Return the cached value for (namespace, key) if fresh; otherwise call
    fetch_fn(), store its result, and return it.

    store_falsy: by default a falsy fetch result ([], {}, None) is returned but
      NOT cached, so a transient empty response doesn't get pinned for the whole
      TTL — the next scan retries. Set True for endpoints where empty is a real,
      stable answer worth caching.
    """
    value, age = get(namespace, key, ttl)
    if value is not None:
        logger.debug(f"cache hit {namespace}/{key} (age {age:.0f}s)")
        return value

    result = fetch_fn()
    if store_falsy or not _is_empty(result):
        put(namespace, key, result, format=format)
    return result


def _is_empty(value: Any) -> bool:
    """Truthiness that doesn't choke on a DataFrame/Series (bool(df) raises)."""
    if value is None:
        return True
    if hasattr(value, "empty"):  # DataFrame / Series
        return bool(value.empty)
    try:
        return not value
    except Exception:
        return False


def _load_json(path: Path) -> tuple[float, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return float(data["stored_at"]), data["value"]


def _load_pickle(path: Path) -> tuple[float, Any]:
    stored_at, value = pickle.loads(path.read_bytes())
    return float(stored_at), value


def clear(namespace: Optional[str] = None) -> None:
    """Delete cached entries — one namespace, or everything. For tests / manual invalidation."""
    import shutil
    target = _CACHE_DIR / _safe(namespace) if namespace else _CACHE_DIR
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
