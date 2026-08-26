"""
Migration: bring the paper-trading ledgers' on-disk headers up to date with
paper_runner.py's current _CSV_COLUMNS (adds any column present in
_CSV_COLUMNS but missing from a file's header, blank for historical rows).
Without this, newly appended/rewritten rows use the longer fieldnames list
while the on-disk header stays old and short — csv.DictReader would then map
old header names positionally onto the new rows' shifted values, corrupting
every column after the insertion point for all new signals.

Covers BOTH ledgers. paper_trades.csv and rank_trades.csv share the single
_CSV_COLUMNS list (deliberately — see paper_updater.py's import comment on
why one shared list, not two hand-synced ones), so a schema change always
applies to both; migrating only the threshold track would leave the rank
track's header short and silently corrupt its next append. The rank track
did not exist when this script was first written, which is why it originally
migrated one file.

Columns added by past runs: greeks_filter_status and the mark_price/
mark_date/unrealized_rr/unrealized_pnl_dollars group; most recently
technical_max/sentiment_max/news_max (v2.2.100).

Safe to re-run: each file is skipped once its header already matches.

Run: python -m scripts.migrate_paper_trades_csv_schema
"""
import csv
from pathlib import Path

from paper_trading.paper_runner import (
    PAPER_TRADES_CSV, PAPER_TRADES_LOCK_FILE,
    RANK_TRADES_CSV, RANK_TRADES_LOCK_FILE,
    _CSV_COLUMNS,
)
from shared.utils.atomic_io import exclusive_lock


def _migrate_one(csv_path: Path, lock_path: Path, label: str) -> None:
    if not csv_path.exists():
        print(f"[{label}] {csv_path.name} does not exist yet — nothing to migrate.")
        return

    with exclusive_lock(lock_path, timeout=15.0):
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            old_fieldnames = reader.fieldnames or []
            rows = list(reader)

        missing = [c for c in _CSV_COLUMNS if c not in old_fieldnames]
        if not missing:
            print(f"[{label}] Header already matches _CSV_COLUMNS — nothing to migrate.")
            return

        for row in rows:
            for col in missing:
                row.setdefault(col, "")

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    print(
        f"[{label}] Migrated {len(rows)} row(s) — added columns {missing} — "
        f"header now has {len(_CSV_COLUMNS)} columns."
    )


def main() -> None:
    _migrate_one(PAPER_TRADES_CSV, PAPER_TRADES_LOCK_FILE, "threshold")
    _migrate_one(RANK_TRADES_CSV, RANK_TRADES_LOCK_FILE, "rank")


if __name__ == "__main__":
    main()
