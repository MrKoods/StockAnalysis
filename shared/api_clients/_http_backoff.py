"""
SHARED: Generic HTTP/callable retry-with-backoff used by every API client in
this package.

Was previously six independent hand-written copies (market_data_client.py
and positioning_client.py: byte-for-byte identical; news_client.py,
sec_edgar_client.py, sentiment_client.py, fundamental_client.py: each with
its own drift on top of the same base loop — secret redaction existed in
only 2 of 6, a total-elapsed-time cap in only 1, a circuit breaker in only
1) that had to be manually kept in sync by hand. One shared retry loop now
backs all of them; client-specific behavior (auth headers, JSON vs. raw
Response, secret redaction, per-host rate limiting/circuit breaking) stays
in each client, composed on top of this rather than folded in here — those
are policy decisions specific to one API's quirks, not generic retry
mechanics.

Retry schedule: 30s -> 60s -> 120s by default (this project's schedule since
the first API client was built) — overridable per call via `delays`.
"""

import time
from typing import Any, Callable, Optional

import requests

from shared.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_BACKOFF_DELAYS: tuple[int, ...] = (30, 60, 120)


def retry_with_backoff(
    fn: Callable[[], Any],
    retries: int = 3,
    delays: tuple[int, ...] = DEFAULT_BACKOFF_DELAYS,
    max_total_seconds: Optional[float] = None,
    label: str = "",
    redact: Optional[Callable[[str], str]] = None,
    should_retry: Optional[Callable[[BaseException], bool]] = None,
    on_exhausted: Optional[Callable[[BaseException], None]] = None,
) -> Optional[Any]:
    """
    Call fn() with exponential backoff on any exception. Returns fn()'s
    result, or None once retries (or max_total_seconds/should_retry, if
    given) are exhausted. Never raises.

    retries: max attempts (including the first).
    delays: sleep schedule between attempts. Extra retries beyond
      len(delays) run back-to-back with no sleep.
    max_total_seconds: caps cumulative sleep time — stops retrying early
      (still returns None) if the next delay would exceed this budget, so
      one stalled call can't block a synchronous pipeline indefinitely
      regardless of how many retries are configured. None (default) = no cap.
      (fundamental_client.py: bounds a Finnhub outage to a fixed worst case
      instead of the full 210s ladder per call across a whole watchlist.)
    label: prefixed on every log line — a function name, or something like
      "TICKER: fetch_name" for a per-ticker caller.
    redact: applied to exception text before logging — pass a closure that
      strips this call's own secret (API key/token) out of error text, since
      requests' HTTPError embeds the full request URL/params by default and
      an unredacted 429/403/5xx would otherwise write a live key to disk in
      plaintext (log files, validation_log.csv). None (default) if the call
      has no secret to leak (e.g. SEC EDGAR needs no API key).
    should_retry: optional predicate on the caught exception — return False
      to stop retrying immediately and return None instead of burning the
      rest of the backoff schedule (e.g. sentiment_client.py: a 4xx that
      isn't 429 is a real rejection, not a transient failure). None
      (default) retries every exception, matching every client's behavior
      before this module existed.
    on_exhausted: called with the last exception once retries are genuinely
      exhausted (not on a should_retry-rejected or max_total_seconds-capped
      exit, which are already logged with their own reason) — for a caller
      that needs to do more than log on final failure (e.g.
      fundamental_client.py writes a validation_log.csv entry per ticker).
      None (default) does nothing extra.
    """
    last_exc: Optional[BaseException] = None
    elapsed = 0.0
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            text = redact(str(exc)) if redact else str(exc)
            if should_retry is not None and not should_retry(exc):
                logger.warning(f"[{label}] Request rejected, not retrying: {text}")
                if on_exhausted is not None:
                    on_exhausted(exc)
                return None
            # attempt >= retries - 1: this was the last attempt — no further
            # retry follows, so sleeping here would just waste up to the
            # longest configured delay for nothing. All six original
            # hand-written copies of this loop had this exact waste (slept
            # once more than they ever used); fixed here since consolidating
            # already touches every caller — this only ever makes an
            # exhausted-retries failure return faster, never changes whether
            # a call ultimately succeeds or fails.
            if attempt >= retries - 1 or attempt >= len(delays):
                break
            delay = delays[attempt]
            if max_total_seconds is not None and elapsed + delay > max_total_seconds:
                logger.warning(
                    f"[{label}] Attempt {attempt + 1} failed: {text}. "
                    f"Backoff cap ({max_total_seconds}s) reached — giving up early."
                )
                if on_exhausted is not None:
                    on_exhausted(exc)
                return None
            logger.warning(f"[{label}] Attempt {attempt + 1} failed: {text}. Retrying in {delay}s.")
            time.sleep(delay)
            elapsed += delay

    text = redact(str(last_exc)) if redact and last_exc is not None else str(last_exc)
    logger.error(f"[{label}] All retries exhausted. Last error: {text}")
    if on_exhausted is not None and last_exc is not None:
        on_exhausted(last_exc)
    return None


def http_get_with_backoff(
    url: str,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: int = 15,
    retries: int = 3,
    delays: tuple[int, ...] = DEFAULT_BACKOFF_DELAYS,
    label: str = "",
    redact: Optional[Callable[[str], str]] = None,
    parse_json: bool = True,
    should_retry: Optional[Callable[[BaseException], bool]] = None,
):
    """
    GET url with exponential backoff, built on retry_with_backoff — the
    convenience wrapper for the common "just GET a URL and retry" case
    (news_client.py, sec_edgar_client.py, sentiment_client.py). Clients that
    retry a multi-step callable instead of a single GET (market_data_client.py,
    positioning_client.py, fundamental_client.py — a yfinance call, or one of
    several endpoint types) call retry_with_backoff directly.

    parse_json: True (default) returns resp.json() on success; False returns
    the raw requests.Response (sec_edgar_client.py needs .text/.content for
    XML/Atom parsing, not JSON).

    Returns fn()'s result (parsed JSON or Response) or None — see
    retry_with_backoff for the rest of the parameters.
    """
    def _fetch():
        resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json() if parse_json else resp

    return retry_with_backoff(
        _fetch, retries=retries, delays=delays, max_total_seconds=None,
        label=label, redact=redact, should_retry=should_retry,
    )
