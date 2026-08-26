"""
One-time backfill: populate technical_max/sentiment_max/news_max on paper-trading
rows logged before v2.2.100 added those columns.

WHY THESE ARE RECOVERABLE AT ALL
scoring.py's live_weights path rescales technical/sentiment/news to the calibrated
fraction of their shared 70-point pool, which MOVES each category's real ceiling
(deliberately, and deliberately not re-clamped — see scoring.py's "Deliberately NOT
re-clamped" note). Until v2.2.100 the denominator was never stored, so a row like
AMZN 2026-08-19 (sentiment_score=26.1 against a nominal max of 15) read as a scoring
bug rather than a 0.4 sentiment weight raising the real cap to 28.

The weights themselves are not in the ledger, but they ARE in git, and only one
calibration was ever live:

  * Global (data/processed/calibrated_weights.json) has never had a "last_calibrated"
    key, and load_live_weights_if_calibrated() returns None without one. So the global
    path NEVER reweighted anything, for any row. Nominal maxes apply.

  * Per-sector (calibrated_weights_by_sector.json) held exactly one entry —
    consumer_discretionary {technical 0.4, sentiment 0.4, news 0.2} — written
    2026-08-15 (946646f) and deleted 2026-08-23 (a085942, "clear a stale, invalid
    per-sector calibration that was actively steering live scoring"). It used the old
    flat pre-direction schema, which load_live_weights_if_calibrated() reads as that
    sector's BULLISH weights only; a bearish lookup falls through to global, i.e. None.

    pool = 40 + 15 + 15 = 70, w_sum = 1.0
      technical_max = 70 * 0.4 = 28.0
      sentiment_max = 70 * 0.4 = 28.0
      news_max      = 70 * 0.2 = 14.0

So: consumer_discretionary + bullish + signal_date in [2026-08-15, 2026-08-23) gets
the calibrated maxes; every other row gets nominal 40/15/15.

CONFIDENCE CHECKS (all passed at time of writing, and re-asserted below)
  * Exactly the 3 rows this rule marks as calibrated are the only 3 in the ledger whose
    stored scores exceed their nominal maxes. No false positives, no misses.
  * No row anywhere violates its derived max.
  * AMZN appears on BOTH sides of the window (2026-08-07 sentiment 4.7, fits nominal 15;
    2026-08-19 sentiment 26.1, needs 28) — same ticker and sector, so the window
    boundary alone separates them. An independent check that the dates are right.

Refuses to overwrite any non-blank value, so it is safe to re-run and cannot clobber
values written by a live scan.

Run: python -m scripts.backfill_score_maxes [--apply]
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml  # noqa: E402

from paper_trading.paper_runner import (  # noqa: E402
    PAPER_TRADES_CSV, PAPER_TRADES_LOCK_FILE,
    RANK_TRADES_CSV, RANK_TRADES_LOCK_FILE,
    _CSV_COLUMNS,
)
from shared.utils.atomic_io import exclusive_lock  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _REPO_ROOT / "config" / "swing_config.yaml"

_NOMINAL = {"technical_max": 40.0, "sentiment_max": 15.0, "news_max": 15.0}
_CALIBRATED = {"technical_max": 28.0, "sentiment_max": 28.0, "news_max": 14.0}
_CAL_SECTOR = "consumer_discretionary"
_CAL_DIRECTION = "bullish"
_CAL_START, _CAL_END = "2026-08-15", "2026-08-23"


def _ticker_sector_map() -> dict[str, str]:
    cfg = yaml.safe_load(_CONFIG_PATH.read_text(encoding="utf-8"))
    sectors = (cfg.get("watchlist") or {}).get("sectors") or {}
    return {t: name for name, s in sectors.items() for t in (s.get("tickers") or [])}


def _maxes_for(row: dict, tmap: dict[str, str]) -> dict[str, float]:
    calibrated = (
        tmap.get(row.get("ticker", "")) == _CAL_SECTOR
        and row.get("direction") == _CAL_DIRECTION
        and _CAL_START <= row.get("signal_date", "") < _CAL_END
    )
    return _CALIBRATED if calibrated else _NOMINAL


def _process(csv_path: Path, lock_path: Path, label: str, apply: bool) -> int:
    if not csv_path.exists():
        print(f"[{label}] {csv_path.name} does not exist — nothing to do.")
        return 0

    tmap = _ticker_sector_map()

    with exclusive_lock(lock_path, timeout=15.0):
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        changed = 0
        for row in rows:
            maxes = _maxes_for(row, tmap)
            for col, value in maxes.items():
                if (row.get(col) or "").strip():
                    continue  # never overwrite a real value
                row[col] = f"{value:.1f}"
                changed = changed + 1 if col == "technical_max" else changed

            # Re-assert the invariant this backfill exists to make legible: a
            # stored score must never exceed the denominator it was graded
            # against. If this trips, the derivation above is wrong for this row
            # and writing it would launder a bad number into the ledger.
            for score_col, max_col in (
                ("technical_score", "technical_max"),
                ("sentiment_score", "sentiment_max"),
                ("news_score", "news_max"),
            ):
                raw = (row.get(score_col) or "").strip()
                if not raw:
                    continue
                if float(raw) > float(row[max_col]) + 0.01:
                    raise SystemExit(
                        f"[{label}] ABORT: {row['signal_date']} {row['ticker']} has "
                        f"{score_col}={raw} > {max_col}={row[max_col]}. The derivation in this "
                        f"script does not explain this row — investigate before backfilling."
                    )

        if not apply:
            print(f"[{label}] DRY RUN — would backfill {changed} row(s). Re-run with --apply.")
            return changed

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)

    print(f"[{label}] Backfilled {changed} row(s).")
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = parser.parse_args()

    _process(PAPER_TRADES_CSV, PAPER_TRADES_LOCK_FILE, "threshold", args.apply)
    _process(RANK_TRADES_CSV, RANK_TRADES_LOCK_FILE, "rank", args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
