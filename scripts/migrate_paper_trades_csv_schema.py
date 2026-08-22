"""
One-time migration: bring paper_trades.csv's on-disk header up to date with
paper_runner.py's current _CSV_COLUMNS (adds any column present in
_CSV_COLUMNS but missing from the file's header — currently
greeks_filter_status and the mark_price/mark_date/unrealized_rr/
unrealized_pnl_dollars group — blank for historical rows). Without this,
newly appended/rewritten rows use the longer fieldnames list while the
on-disk header stays old and short — csv.DictReader would then map old
header names positionally onto the new rows' shifted values, corrupting
every column after the insertion point for all new signals.

Safe to re-run: exits immediately once the header already matches.

Run: python -m scripts.migrate_add_greeks_filter_status_column
"""
import csv
from pathlib import Path

from paper_trading.paper_runner import PAPER_TRADES_CSV, PAPER_TRADES_LOCK_FILE, _CSV_COLUMNS
from shared.utils.atomic_io import exclusive_lock


def main() -> None:
    if not PAPER_TRADES_CSV.exists():
        print("paper_trades.csv does not exist yet — nothing to migrate.")
        return

    with exclusive_lock(PAPER_TRADES_LOCK_FILE, timeout=15.0):
        with open(PAPER_TRADES_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            old_fieldnames = reader.fieldnames or []
            rows = list(reader)

        missing = [c for c in _CSV_COLUMNS if c not in old_fieldnames]
        if not missing:
            print("Header already matches _CSV_COLUMNS — nothing to migrate.")
            return

        for row in rows:
            for col in missing:
                row.setdefault(col, "")

        with open(PAPER_TRADES_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)

    print(f"Migrated {len(rows)} row(s) — added columns {missing} — header now has {len(_CSV_COLUMNS)} columns.")


if __name__ == "__main__":
    main()
