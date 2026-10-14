"""
Daily snapshot of every paper-testing ledger in V2 and V3, read from the LIVE folders.

The review agent works in its own git worktree (StockAnalysis-agent), whose tracked copies of the
ledgers are stale. This script always reads the live files by absolute path, so the numbers the
agent reviews are the ones the scheduled tasks actually wrote. Read-only: it writes nothing.

    python agent/tools/snapshot.py            # today
    python agent/tools/snapshot.py 2026-10-14 # as of a given day ("new"/"closed" use that date)
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

V2 = Path(r"C:\Users\user\Documents\Git\StockAnalysis")
V3 = Path(r"C:\Users\user\Documents\Git\StockAnalysis-V3")
DAY = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()

V2_LEDGERS = {"threshold": "paper_trades.csv", "rank": "rank_trades.csv", "random": "random_trades.csv"}
V2_LOGS = ["paper_runner_premarket_task.log", "paper_updater_task.log",
           "paper_runner_midsession_task.log", "paper_runner_task.log"]
V3_LOGS = ["g2_paper_task.log", "on1_paper_task.log", "daytrade_fetch_task.log"]


def t_stat(x: pd.Series) -> float:
    x = x.dropna()
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 1 and x.std(ddof=1) > 0 else float("nan")


def v2_section() -> None:
    print(f"=== V2 swing model (live: {V2}) ===")
    for track, name in V2_LEDGERS.items():
        p = V2 / "paper_trading" / name
        if not p.exists():
            print(f"[{track}] ledger not created yet")
            continue
        d = pd.read_csv(p)
        c = d[d["achieved_rr"].notna()]
        filled_open = d[d["fill_date"].notna() & d["outcome"].isna()]
        pending = d[d["fill_date"].isna() & d["outcome"].isna()]
        new = d[d["signal_date"].astype(str) == DAY]
        closed_today = c[c["exit_date"].astype(str) == DAY]
        weekly = c.groupby(pd.to_datetime(c["fill_date"]).dt.to_period("W"))["achieved_rr"].mean()
        print(f"[{track}] closed {len(c)} | mean R {c['achieved_rr'].mean():+.3f} | win {(c['achieved_rr'] > 0).mean():.0%} "
              f"| week-t {t_stat(weekly):.2f} ({len(weekly)} wks) | open {len(filled_open)} "
              f"(unreal {filled_open['unrealized_rr'].sum():+.2f}R) | pending {len(pending)}")
        print(f"   outcomes: {d['outcome'].fillna('open/pending').value_counts().to_dict()}")
        if len(new):
            print(f"   new signals {DAY}: " + ", ".join(f"{r.ticker} {r.direction} ({r.position_type})" for r in new.itertuples()))
        if len(closed_today):
            print(f"   closed {DAY}: " + ", ".join(f"{r.ticker} {r.outcome} {r.achieved_rr:+.2f}R" for r in closed_today.itertuples()))
        if "position_type" in d and len(new):
            bad = new[new["position_type"].fillna("") != "shares"]
            if len(bad):
                print(f"   !! {len(bad)} new row(s) not 'shares' although shares_only is on: {bad['ticker'].tolist()}")
    try:
        sys.path.insert(0, str(V2))
        from paper_trading.rank_verdict import compute_verdict
        cfg = yaml.safe_load((V2 / "config" / "swing_config.yaml").read_text(encoding="utf-8"))
        v = compute_verdict(cfg, rank_csv=V2 / "paper_trading" / "rank_trades.csv",
                            random_csv=V2 / "paper_trading" / "random_trades.csv")
        print("   " + v["text"].replace("\n", "\n   "))
    except Exception as exc:  # the verdict also fetches ETF prices; a failure must not hide the rest
        print(f"   go/no-go verdict unavailable: {exc}")


def v3_section() -> None:
    print(f"\n=== V3 day-trading model (live: {V3}) ===")
    specs = [("C6 forward", "data/forward/c6_forward_trades.csv", "r_net", "R"),
             ("G2 forward", "data/forward/g2_forward_trades.csv", "r_atr", "ATR"),
             ("ON1 forward", "data/forward/on1_forward_trades.csv", "bps", "bps"),
             ("G2 paper", "data/paper/g2_paper_ledger.csv", "bps_at_0932_entry", "bps"),
             ("ON1 paper", "data/paper/on1_paper_ledger.csv", "bps", "bps")]
    for label, rel, col, unit in specs:
        p = V3 / rel
        if not p.exists():
            print(f"[{label}] not created yet")
            continue
        d = pd.read_csv(p).dropna(subset=[col])
        if d.empty:
            print(f"[{label}] no scored rows yet")
            continue
        per_day = d.groupby("day")[col].mean()
        print(f"[{label}] {d['day'].nunique()} days, {len(d)} trades | mean {d[col].mean():+.3f} {unit} "
              f"| day-t {t_stat(per_day):.2f} | last day {per_day.index[-1]}: {per_day.iloc[-1]:+.3f}")


def log_section() -> None:
    print("\n=== Task log health (lines dated today with ERROR / Traceback) ===")
    pat = re.compile(r"ERROR|Traceback|CRITICAL")
    for root, logs in ((V2 / "data" / "logs", V2_LOGS), (V3 / "data" / "logs", V3_LOGS)):
        for name in logs:
            p = root / name
            if not p.exists():
                print(f"  {name}: missing")
                continue
            tail = p.read_text(encoding="utf-8", errors="replace").splitlines()[-4000:]
            dated = any(re.match(r"\d{4}-\d{2}-\d{2} ", l) for l in tail)
            if dated:
                scope = [l for l in tail if l.startswith(DAY)]
                where = f"{len(scope)} lines today"
            else:  # V3 logs carry no timestamps: judge by write time + the last lines
                scope = tail[-60:]
                mtime = pd.Timestamp(p.stat().st_mtime, unit="s", tz="UTC").tz_convert("America/Los_Angeles")
                where = f"last written {mtime:%Y-%m-%d %H:%M} PT"
            bad = [l for l in scope if pat.search(l)]
            print(f"  {name}: {where}, {len(bad)} error lines" + (f" | e.g. {bad[-1][:160]}" if bad else ""))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    pd.set_option("display.width", 200)
    print(f"Snapshot for {DAY}\n")
    v2_section()
    v3_section()
    log_section()
