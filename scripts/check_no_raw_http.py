"""
CI gate: fail if any file OUTSIDE shared/api_clients/ makes a raw outbound
HTTP call (`requests.get`/`requests.post`) or reaches yfinance directly
(`import yfinance` / `yf.`).

Every external data fetch must go through a wrapper in shared/api_clients/ so
that the shared cache (shared/api_clients/cache.py) and the cross-process rate
limiter (shared/api_clients/rate_limiter.py) are always applied. This project
has repeatedly been bitten by one call site diverging from the rest — the
Alpha Vantage counter that undercounted retries (Signal Integrity Audit E.3),
`fundamental_client`'s Finnhub calls that skipped the shared backoff,
`download_historical_news.py` keeping its own copy of the AV day counter. A
new scoring layer that calls `requests.get` directly would silently sit
outside the whole data plane. This is the guardrail that makes that impossible
to add without CI noticing.

Scope: the live scan + paper-trading path (swing_model/, paper_trading/,
shared/utils/, shared/indicators/, monitoring/, app_ui/). backtesting/ and
one-off scripts/ are offline/historical and out of scope. tests/ mock these
libraries directly by design.

Usage:
    python scripts/check_no_raw_http.py
"""

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Only these top-level packages are the live/paper scan path this check guards.
_IN_SCOPE_ROOTS = ("swing_model", "paper_trading", "shared/utils", "shared/indicators", "monitoring", "app_ui")

_ALLOWLIST: dict[str, str] = {
    # Discord webhook posts, not a data API — the one legitimate raw
    # requests.post in the codebase (see the module docstring + conftest's
    # _block_real_discord_sends fixture which is scoped to exactly this).
    "shared/utils/discord_alerts.py": "Discord webhook only, not a data source",
}

_RAW_HTTP = re.compile(r"\brequests\.(get|post|request|Session)\s*\(")
_YFINANCE = re.compile(r"^\s*import\s+yfinance\b|^\s*from\s+yfinance\b|(?<![A-Za-z_])yf\.", re.MULTILINE)


def _looks_like_prose(text: str, pos: int) -> bool:
    """True if the match at `pos` is after a `#` on its line, or the line starts
    with a quote / bullet (docstring or comment prose). Keeps the yf. pattern
    from firing on this codebase's many comments that mention yfinance."""
    line_start = text.rfind("\n", 0, pos) + 1
    before = text[line_start:pos]
    if "#" in before:
        return True
    return before.lstrip().startswith(("'", '"', "* ", "- "))


def _in_scope(path: Path) -> bool:
    rel = path.relative_to(_REPO_ROOT).as_posix()
    return any(rel.startswith(root + "/") for root in _IN_SCOPE_ROOTS)


def check_file(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []
    hits = []
    for m in _RAW_HTTP.finditer(text):
        if _looks_like_prose(text, m.start()):
            continue
        line_no = text.count("\n", 0, m.start()) + 1
        hits.append(f"line {line_no}: raw HTTP call — {m.group(0)!r} (route through shared/api_clients/)")
    for m in _YFINANCE.finditer(text):
        if _looks_like_prose(text, m.start()):
            continue
        line_no = text.count("\n", 0, m.start()) + 1
        frag = m.group(0).strip()
        hits.append(f"line {line_no}: direct yfinance use — {frag!r} (route through shared/api_clients/market_data_client.py)")
    return hits


def main() -> int:
    findings: dict[str, list[str]] = {}
    scanned = 0
    for path in _REPO_ROOT.rglob("*.py"):
        if "__pycache__" in path.parts or not _in_scope(path):
            continue
        scanned += 1
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if rel in _ALLOWLIST:
            continue
        hits = check_file(path)
        if hits:
            findings[rel] = hits

    if findings:
        print(f"::error::check_no_raw_http: {len(findings)} in-scope file(s) bypass shared/api_clients/:")
        for rel, hits in sorted(findings.items()):
            print(f"  - {rel}")
            for hit in hits:
                print(f"      {hit}")
        print(
            "::error::check_no_raw_http: add a wrapper in shared/api_clients/ (so the shared cache "
            "and rate limiter apply) and call that instead. A deliberate exception goes in "
            "_ALLOWLIST with a one-line reason."
        )
        return 1

    print(f"check_no_raw_http: scanned {scanned} in-scope files — OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
