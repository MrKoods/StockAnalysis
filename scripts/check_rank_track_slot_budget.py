"""
CI/audit gate: fail if paper_trading/rank_trades.csv ever holds more than
rank_track.top_n_per_sector signals for the same (signal_date, sector).

The bug this exists to catch (fixed v2.2.100, found 2026-08-25): the rank
track's duplicate guard keyed on (signal_date, ticker), which stopped the
same ticker being logged twice in a day but never stopped a LATER scan from
walking further down that sector's ranking and filling top_n fresh slots.
With three scans a day that logged 3x the configured budget — exactly 6 rows
per sector, 24 in one day against a configured 8.

What makes this worth a standing check rather than a one-off fix is that it
was INVISIBLE from the logs. Every run reported "Rank track: 8 new signal(s)
logged" — the expected number — because each scan only ever counted its own
work. Nothing was wrong in any single run's output; the violation only
existed across runs, in the file. It would have survived to the rank track's
2026-09-19 checkpoint and quietly biased the verdict, since scans 2 and 3
systematically contribute the LOWER-ranked names.

The rank track exists solely to build a clean, comparable dataset for judging
rank-based selection (CHANGELOG v2.2.98), so silent contamination of its
ledger defeats its entire purpose. Same reasoning as
check_confidence_threshold_duplication.py: the manual audit caught it after
the fact, nothing caught it as it happened.

Note this checks the ledger (data), not source (code) — the invariant is a
property of what actually got logged, and a future refactor could reintroduce
the bug through a different code shape while this check still catches it. In
CI the file is normally absent (rank_trades.csv is untracked), so this
no-ops there and does its real work when run against a live ledger.

Usage:
    python scripts/check_rank_track_slot_budget.py
"""

import csv
import sys
from collections import defaultdict
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

# Reads the YAML directly rather than importing the pipeline's load_config —
# same approach as check_config_coverage.py, and keeps this gate from
# depending on the heavy swing_model.indicator_pipeline import chain.
from shared.utils.sector_config import get_ticker_sector_map  # noqa: E402

_CONFIG_PATH = _REPO_ROOT / "config" / "swing_config.yaml"
_RANK_TRADES_CSV = _REPO_ROOT / "paper_trading" / "rank_trades.csv"


def main() -> int:
    if not _RANK_TRADES_CSV.exists():
        print(f"check_rank_track_slot_budget: {_RANK_TRADES_CSV.name} not present — nothing to check.")
        return 0

    try:
        cfg = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"::warning::check_rank_track_slot_budget: could not load config ({exc}) — skipping.")
        return 0

    top_n = int(cfg.get("rank_track", {}).get("top_n_per_sector", 2))
    ticker_sector_map = get_ticker_sector_map(cfg)

    with open(_RANK_TRADES_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("check_rank_track_slot_budget: ledger is empty — nothing to check.")
        return 0

    per_day_sector: dict[tuple[str, str], list[str]] = defaultdict(list)
    unmapped: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        date = row.get("signal_date", "")
        ticker = row.get("ticker", "")
        sector = ticker_sector_map.get(ticker)
        if sector is None:
            unmapped[date].append(ticker)
            continue
        per_day_sector[(date, sector)].append(ticker)

    violations = {k: v for k, v in per_day_sector.items() if len(v) > top_n}

    if unmapped:
        total = sum(len(v) for v in unmapped.values())
        print(
            f"::warning::check_rank_track_slot_budget: {total} row(s) reference a ticker that is not "
            f"in any active sector, so they are NOT budget-checked (a violation could hide among "
            f"them). Usually means the ticker left the watchlist after it was logged:"
        )
        for date, tickers in sorted(unmapped.items()):
            print(f"  - {date}: {', '.join(sorted(tickers))}")

    if violations:
        print(
            f"::error::check_rank_track_slot_budget: {len(violations)} (date, sector) group(s) exceed "
            f"rank_track.top_n_per_sector={top_n} in {_RANK_TRADES_CSV}:"
        )
        for (date, sector), tickers in sorted(violations.items()):
            print(f"  - {date} / {sector}: {len(tickers)} rows (budget {top_n}) — {', '.join(tickers)}")
        print(
            "::error::check_rank_track_slot_budget: the rank track's per-(day, sector) budget is the "
            "one thing that makes its dataset comparable across days. Over-logging biases it toward "
            "lower-ranked names, because the surplus is always picked after the top names are taken "
            "(see CHANGELOG.md v2.2.100). Check _run_rank_track's slot accounting and the "
            "rank_track.scan_type gate before trusting any analysis built on this file."
        )
        return 1

    days = len({d for d, _ in per_day_sector})
    print(
        f"check_rank_track_slot_budget: {len(rows)} row(s) across {days} day(s), "
        f"no (date, sector) group over top_n_per_sector={top_n} — OK."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
