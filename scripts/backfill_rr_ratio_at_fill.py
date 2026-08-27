"""
One-time backfill: populate rr_ratio_at_fill on rows that were already filled
before v2.2.105 added the column.

paper_updater.py stamps it at the moment a fill is confirmed, so without this
every trade filled to date would keep a blank forever — including the two
closed trades and eight open positions that make up the entire performance
record so far.

Pure arithmetic from fields already on the row (fill_price, stop_loss,
target), so there is nothing to reconstruct and no ambiguity: unlike the
stop/target recompute, this cannot be confused by 2dp rounding, because it
reads the stored values rather than trying to infer the inputs that produced
them.

Only fills blanks — never overwrites a value the updater already wrote.

Run: python -m scripts.backfill_rr_ratio_at_fill [--apply]
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from paper_trading.paper_runner import (  # noqa: E402
    PAPER_TRADES_CSV, PAPER_TRADES_LOCK_FILE,
    RANK_TRADES_CSV, RANK_TRADES_LOCK_FILE,
    _CSV_COLUMNS,
)
from shared.utils.atomic_io import exclusive_lock  # noqa: E402


def _rr_at_fill(row: dict):
    """Reward:risk measured from the real fill, or None if not computable."""
    try:
        fill = float(row["fill_price"])
        stop = float(row["stop_loss"])
        target = float(row["target"])
    except (KeyError, TypeError, ValueError):
        return None
    risk = abs(fill - stop)
    if risk <= 0:
        return None
    reward = (fill - target) if row.get("direction") == "bearish" else (target - fill)
    return reward / risk


def _process(csv_path: Path, lock_path: Path, label: str, apply: bool) -> int:
    if not csv_path.exists():
        print(f"[{label}] {csv_path.name} does not exist — nothing to do.")
        return 0

    with exclusive_lock(lock_path, timeout=15.0):
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        changed = []
        for row in rows:
            if not (row.get("fill_date") or "").strip():
                continue                       # never filled — nothing to measure
            if (row.get("rr_ratio_at_fill") or "").strip():
                continue                       # already set — never overwrite
            value = _rr_at_fill(row)
            if value is None:
                print(f"[{label}]   {row.get('ticker')}: not computable — skipped")
                continue
            row["rr_ratio_at_fill"] = f"{value:.2f}"
            changed.append((row.get("ticker"), row.get("rr_ratio"), row["rr_ratio_at_fill"]))

        if not apply:
            print(f"[{label}] DRY RUN — would backfill {len(changed)} row(s). Re-run with --apply.")
            for t, planned, actual in changed:
                print(f"[{label}]   {t:<6} planned {planned:>6} -> at fill {actual:>6}")
            return len(changed)

        if changed:
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)

    print(f"[{label}] Backfilled {len(changed)} row(s).")
    for t, planned, actual in changed:
        print(f"[{label}]   {t:<6} planned {planned:>6} -> at fill {actual:>6}")
    return len(changed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = parser.parse_args()
    _process(PAPER_TRADES_CSV, PAPER_TRADES_LOCK_FILE, "threshold", args.apply)
    _process(RANK_TRADES_CSV, RANK_TRADES_LOCK_FILE, "rank", args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
