"""CLI: python -m epre {calendar|signals|evaluate|status} [--dry-run] [--day=YYYY-MM-DD]"""

from __future__ import annotations

import logging
import sys
from datetime import date

from . import calendar, paper


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    cmd = sys.argv[1]
    dry = "--dry-run" in sys.argv
    day = next((date.fromisoformat(a[6:]) for a in sys.argv if a.startswith("--day=")), None)
    if cmd == "calendar":
        calendar.refresh()
    elif cmd == "signals":
        paper.signals(dry, day if dry else None)      # --day replays a date (dry runs only)
    elif cmd == "evaluate":
        paper.evaluate(dry)
    elif cmd == "status":
        print(paper.verdict(paper.load_ledger()))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
