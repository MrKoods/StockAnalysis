"""CLI: python -m daytrade {fetch|backtest|charts}"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from . import backtest, data
from .config import OUTPUT_DIR


def main():
    ap = argparse.ArgumentParser(prog="daytrade")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch", help="download available 1m/5m bars into the archive")
    sub.add_parser("backtest", help="run the strategy and print the summary")
    sub.add_parser("forward", help="update the G2 and ON1 forward-test ledgers (C6 retired 2026-10-23)")
    c = sub.add_parser("charts", help="chart a sample of setups for visual checking")
    c.add_argument("-n", type=int, default=12)
    c.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    data.wait_for_parquet()

    if args.cmd == "fetch":
        summary = data.fetch()
        days = {t: v.get("1m", 0) // 390 for t, v in summary.items()}
        print(f"archived {len(summary)} tickers; ~1m sessions per ticker: {sorted(set(days.values()))}")
        return

    if args.cmd == "forward":
        from . import forward
        from .data import fetch_hourly
        hourly = sorted(set(forward.g2_tickers()) | set(forward.index_tickers("sp600")))
        print("hourly bars updated for", fetch_hourly(hourly), "tickers")
        # C6 retired 2026-10-23 (no edge in 8 years of minute data; forward t -2.16 at 14 sessions).
        # Its ledger data/forward/c6_forward_trades.csv is kept as the record; forward.update() still exists.
        # G2 retired 2026-11-08 (FAILED its day-20 paper check): its forward ledger is no longer extended
        # (user's decision 2026-11-13). The hourly fetch above stays - team research reads those bars.
        # data/forward/g2_forward_trades.csv is kept as the record; forward.update_g2() still exists.
        # ON1 stops with its paper test: the team's dispatcher writes this file when ON1's real-price rule FAILs.
        retired = Path(r"C:\Users\user\Documents\Git\StockAnalysis-Team\state\on1_retired.json")
        if retired.exists():
            print("ON1 retired:", retired.read_text(encoding="utf-8")[:200])
        else:
            print("ON1 (secondary)", json.dumps(forward.update_on1(), default=str))
        return

    df = backtest.run()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUTPUT_DIR / "setups.csv", index=False)

    if args.cmd == "backtest":
        print(json.dumps(backtest.summarize(df), indent=2, default=str))
    else:
        from .charts import plot_setup
        out = OUTPUT_DIR / "charts"
        out.mkdir(exist_ok=True)
        for f in out.glob("*.png"):
            f.unlink()
        # Mostly trades, plus a few setups rejected at late stages, to check the filters too.
        traded = df[df["status"] == "traded"]
        late = df[df["status"].isin(["below_min_r", "entry_timeout", "invalidated_before_entry"])]
        k_late = min(len(late), max(2, args.n // 4))
        sample = list(traded.sample(min(len(traded), args.n - k_late), random_state=args.seed).itertuples(index=False))
        sample += list(late.sample(k_late, random_state=args.seed).itertuples(index=False))
        for i, s in enumerate(sample, 1):
            d = s._asdict()
            plot_setup(d, out / f"{i:02d}_{d['ticker']}_{d['day']}_{d['direction']}_{d['status']}.png")
        print(f"wrote {len(sample)} charts to {out}")


if __name__ == "__main__":
    main()
