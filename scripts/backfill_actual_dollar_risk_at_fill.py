"""
One-time backfill: recompute actual_dollar_risk for currently-open ("shares"
position_type, fill_date set, outcome still blank) trades using the real
fill_price instead of the zone-midpoint entry_price it was frozen at signal
time. paper_updater.py now does this automatically at the moment a fill is
first confirmed (see the fill-confirmation block), but trades already filled
before that shipped are stuck with the old, less accurate figure until they
happen to close — this brings them in line immediately so today's unrealized
P&L is accurate rather than waiting on each trade's own close.

Does NOT touch closed trades — their pnl_dollars was already computed and
reported (Discord alert, prior chat answers) with the old figure; rewriting
a closed trade's booked result silently is a different, more sensitive
action than correcting a still-open position's live mark, so it's out of
scope here.

Run once: python -m scripts.backfill_actual_dollar_risk_at_fill
"""
import csv

from paper_trading.paper_runner import PAPER_TRADES_CSV, PAPER_TRADES_LOCK_FILE, _CSV_COLUMNS
from shared.utils.atomic_io import exclusive_lock


def main() -> None:
    if not PAPER_TRADES_CSV.exists():
        print("paper_trades.csv does not exist yet — nothing to backfill.")
        return

    with exclusive_lock(PAPER_TRADES_LOCK_FILE, timeout=15.0):
        with open(PAPER_TRADES_CSV, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        changed = []
        for row in rows:
            if (row.get("outcome") or "").strip():
                continue  # closed — out of scope, see docstring
            if row.get("position_type") != "shares":
                continue
            fill_price_raw = (row.get("fill_price") or "").strip()
            fill_date_raw = (row.get("fill_date") or "").strip()
            stop_raw = (row.get("stop_loss") or "").strip()
            size_raw = (row.get("position_size") or "").strip()
            if not (fill_price_raw and fill_date_raw and stop_raw and size_raw):
                continue
            try:
                fill_price = float(fill_price_raw)
                stop_loss = float(stop_raw)
                shares = int(size_raw)
            except ValueError:
                continue
            if shares <= 0:
                continue
            old = (row.get("actual_dollar_risk") or "").strip()
            new = f"{shares * abs(fill_price - stop_loss):.2f}"
            if old != new:
                changed.append((row["ticker"], row["signal_date"], old, new))
                row["actual_dollar_risk"] = new

        if changed:
            with open(PAPER_TRADES_CSV, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
                writer.writeheader()
                for row in rows:
                    writer.writerow(row)

    if changed:
        print(f"Backfilled {len(changed)} row(s):")
        for ticker, signal_date, old, new in changed:
            print(f"  {ticker} {signal_date}: actual_dollar_risk {old or '(blank)'} -> {new}")
    else:
        print("Nothing to backfill — all open shares positions already fill-price-anchored.")


if __name__ == "__main__":
    main()
