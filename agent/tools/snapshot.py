"""
Daily snapshot of every paper-testing ledger in V2, V3 and V4, read from the LIVE folders.

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
V4 = Path(r"C:\Users\user\Documents\Git\StockAnalysis-V4")
DAY = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()

V2_LEDGERS = {"threshold": "paper_trades.csv", "rank": "rank_trades.csv", "random": "random_trades.csv"}
V2_LOGS = ["paper_runner_premarket_task.log", "paper_updater_task.log",
           "paper_runner_midsession_task.log", "paper_runner_task.log"]
V3_LOGS = ["g2_paper_task.log", "on1_paper_task.log", "daytrade_fetch_task.log"]
V4_LOGS = ["epre_calendar_task.log", "epre_signals_task.log", "epre_evaluate_task.log"]


def t_stat(x: pd.Series) -> float:
    x = x.dropna()
    return float(x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))) if len(x) > 1 and x.std(ddof=1) > 0 else float("nan")


def loss_clusters(closed: pd.DataFrame, min_losses: int = 3, lookback_days: int = 7) -> list[str]:
    """Same-day, same-direction losses on recent exit dates. Grouped by exit_date, not by the day the
    updater recorded them, because closures can land in the ledger a day late. Such a cluster is one
    market move hitting correlated positions, so the trades are not independent evidence."""
    if closed.empty:
        return []
    exits = pd.to_datetime(closed["exit_date"], errors="coerce")
    recent = closed[exits >= pd.Timestamp(DAY) - pd.Timedelta(days=lookback_days)]
    lines = []
    for (exit_day, direction), g in recent[recent["achieved_rr"] < 0].groupby(["exit_date", "direction"]):
        if len(g) < min_losses:
            continue
        rest = closed[closed["exit_date"].astype(str) != str(exit_day)]["achieved_rr"]
        lines.append(f"!! loss cluster {exit_day}: {len(g)} {direction} losses on one day "
                     f"({', '.join(g['ticker'])}; {g['achieved_rr'].sum():+.2f}R). Correlated - one market move, "
                     f"not {len(g)} independent results. Mean R excluding that exit day: {rest.mean():+.3f} (n={len(rest)})")
    return lines


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
        for line in loss_clusters(c):
            print("   " + line)
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
    # C6 forward retired 2026-10-23 (ledger kept, no longer updated)
    specs = [("G2 forward", "data/forward/g2_forward_trades.csv", "r_atr", "ATR"),
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
    for root, logs in ((V2 / "data" / "logs", V2_LOGS), (V3 / "data" / "logs", V3_LOGS),
                       (V4 / "data" / "logs", V4_LOGS)):
        for name in logs:
            p = root / name
            if not p.exists():
                print(f"  {name}: missing")
                continue
            tail = p.read_text(encoding="utf-8", errors="replace").splitlines()[-4000:]
            dated = any(re.match(r"\d{4}-\d{2}-\d{2} ", line) for line in tail)
            if dated:
                scope = [line for line in tail if line.startswith(DAY)]
                where = f"{len(scope)} lines today"
            else:  # V3 logs carry no timestamps: judge by write time + the last lines
                scope = tail[-60:]
                mtime = pd.Timestamp(p.stat().st_mtime, unit="s", tz="UTC").tz_convert("America/Los_Angeles")
                where = f"last written {mtime:%Y-%m-%d %H:%M} PT"
            bad = [line for line in scope if pat.search(line)]
            print(f"  {name}: {where}, {len(bad)} error lines" + (f" | e.g. {bad[-1][:160]}" if bad else ""))


def v4_section() -> None:
    """EPRE paper test (V4). The calendar must be refreshed every weekday evening: entries are chosen from it
    two sessions ahead, so a stale calendar silently drops trades. Problems print ACTION NEEDED, which the
    launcher copies into the Discord post."""
    print(f"\n=== V4 earnings-premium paper test (live: {V4}) ===")
    cal = V4 / "data" / "calendar" / "earnings_calendar.csv"
    if not cal.exists():
        print("  ACTION NEEDED: V4 earnings calendar missing - StockAnalysis_V4_EPRE_Calendar has never completed")
    else:
        c = pd.read_csv(cal)
        ref = str(c["refreshed"].max()) if len(c) else "never"
        prev_wd = pd.Timestamp(DAY) - pd.offsets.BDay(1)
        hist = int((c["time_source"] == "history").sum()) if len(c) else 0
        print(f"  calendar: {len(c)} upcoming events, refreshed {ref} ({hist} times from company history)")
        if ref == "never" or pd.Timestamp(ref) < prev_wd:
            print(f"  ACTION NEEDED: V4 earnings calendar is stale (last refreshed {ref}) - the 17:15 refresh "
                  "did not complete; trades two sessions out may be missed.")
    p = V4 / "data" / "paper" / "epre_ledger.csv"
    if not p.exists():
        print("  [EPRE paper] ledger not created yet (first signals 2026-10-26)")
        return
    d = pd.read_csv(p, dtype={"entry_day": str, "exit_day": str, "date_ok": str})
    x = d.dropna(subset=["hedged_bps"])
    print(f"  [EPRE paper] signals logged {len(d)} | open {int(d['hedged_bps'].isna().sum())} "
          f"| new today {int((d['entry_day'] == DAY).sum())}")
    if len(x):
        per_day = x.groupby("exit_day")["hedged_bps"].mean()
        ok = x["date_ok"].dropna().str.lower()
        acc = f"{(ok == 'true').mean():.0%}" if len(ok) else "n/a"
        print(f"  [EPRE paper] closed {len(x)} | hedged mean {x['hedged_bps'].mean():+.1f} bps "
              f"(net unhedged {x['net_bps'].mean():+.1f}) | exit-day t {t_stat(per_day):.2f} ({len(per_day)} days) "
              f"| report-date accuracy {acc} | backtest ~ +19 bps; checkpoints at 1k/3k/6k trades (V4 RULES.md)")
    late = d[d["hedged_bps"].isna() & (pd.to_datetime(d["exit_day"]) < pd.Timestamp(DAY) - pd.offsets.BDay(1))]
    if len(late):
        print(f"  ACTION NEEDED: {len(late)} V4 trade(s) past their exit day are still unscored - evaluate task failing?")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    pd.set_option("display.width", 200)
    print(f"Snapshot for {DAY}\n")
    v2_section()
    v3_section()
    v4_section()
    log_section()
