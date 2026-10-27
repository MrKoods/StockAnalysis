"""Generic paper runner - one scheduled run trades every ACTIVE strategy in strategies/registry.json.

    python tools/paper_runner.py [--date YYYY-MM-DD] [--dry-run] [--only <id>]

Run after the close. For each active strategy:
  1. fill + exit open paper trades from today's daily bars (yfinance, unadjusted OHLC);
  2. if today was a trading session (SPY has today's bar) and the team isn't STOPped, ask the strategy for
     signals using bars up to and including today ONLY, and log them for entry at the next session's open;
  3. score closed trades against the strategy's frozen rule (day-clustered t) and write its status.
Missed days are never back-filled with signals (that would be a backtest, not a paper test).

Strategy contract - strategies/<id>/strategy.py:
    def universe() -> list[str]
    def signals(asof: date, bars: dict[str, pd.DataFrame]) -> list[dict]   # {"ticker", "side": "long"|"short"}
strategies/<id>/spec.json:
    {"family", "hold_sessions": 0 (= exit at the entry day's close) | N, "exit_at": "close"|"open",
     "stop_pct": null|float, "target_pct": null|float, "cost_bps": round-trip, "max_signals_per_day",
     "rule": {"metric": "net_bps"|"hedged_bps", "min_days", "max_days", "pass_mean_bps", "pass_t",
              "early_fail_days": opt, "early_fail_mean_bps": opt}}
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import math
import pickle
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from common import STATE, TEAM, load_json, log, save_json, stopped

REGISTRY = TEAM / "strategies" / "registry.json"
PAPER = TEAM / "paper"
CACHE = STATE / "cache"
FIELDS = ["strategy", "signal_date", "ticker", "side", "status", "entry_date", "entry_px", "exit_date",
          "exit_px", "exit_reason", "gross_bps", "net_bps", "spy_bps", "hedged_bps"]


# ---------- data ----------

def download(tickers: list[str], asof: date) -> dict[str, pd.DataFrame]:
    """Daily unadjusted OHLC for ~400 days to `asof`, cached per day. Pickle, not parquet: Smart App
    Control intermittently blocks pyarrow's DLLs on this machine."""
    tickers = sorted(set(tickers) | {"SPY"})
    key = hashlib.sha1(",".join(tickers).encode()).hexdigest()[:10]
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{asof}-{key}.pkl"
    if path.exists():
        return pickle.loads(path.read_bytes())
    import yfinance as yf
    end = (pd.Timestamp(asof) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    start = (pd.Timestamp(asof) - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
    raw = yf.download(tickers, start=start, end=end, auto_adjust=False, group_by="ticker",
                      progress=False, threads=True)
    out = {}
    for t in tickers:
        try:
            df = raw[t][["Open", "High", "Low", "Close", "Volume"]].dropna(how="all")
        except KeyError:
            continue
        if len(df):
            df.index = pd.to_datetime(df.index).date
            out[t] = df
    path.write_bytes(pickle.dumps(out))
    for old in CACHE.glob("*.pkl"):
        if old.name[:10] < str(asof - pd.Timedelta(days=7).to_pytimedelta()):
            old.unlink(missing_ok=True)
    return out


def truncate(bars: dict[str, pd.DataFrame], asof: date) -> dict[str, pd.DataFrame]:
    """What a strategy may see when signalling on `asof`: nothing after that day's close."""
    return {t: df[df.index <= asof] for t, df in bars.items()}


# ---------- ledger ----------

def ledger_path(sid: str) -> Path:
    return PAPER / f"{sid}.csv"


def read_ledger(sid: str) -> list[dict]:
    p = ledger_path(sid)
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_ledger(sid: str, rows: list[dict]) -> None:
    PAPER.mkdir(parents=True, exist_ok=True)
    with open(ledger_path(sid), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in FIELDS})


# ---------- simulation ----------

def _bps(side: str, entry: float, exit_: float) -> float:
    return (1 if side == "long" else -1) * (exit_ / entry - 1) * 1e4


def advance(row: dict, spec: dict, bars: dict[str, pd.DataFrame], sessions: list[date]) -> dict:
    """Fill and/or exit one trade using sessions up to the last available bar. Pure function."""
    if row["status"] not in ("pending", "open"):
        return row
    row = dict(row)
    sig = date.fromisoformat(row["signal_date"])
    later = [s for s in sessions if s > sig]
    if not later:
        return row
    entry_day = later[0]
    df = bars.get(row["ticker"])
    spy = bars["SPY"]
    if df is None or entry_day not in df.index or pd.isna(df.at[entry_day, "Open"]):
        row.update(status="void", exit_reason="no bar on entry day")
        return row
    entry = float(df.at[entry_day, "Open"])
    row.update(status="open", entry_date=str(entry_day), entry_px=round(entry, 4))
    hold = int(spec.get("hold_sessions", 0))
    path = later[: hold + 1]
    side = row["side"]
    stop, target = spec.get("stop_pct"), spec.get("target_pct")
    sgn = 1 if side == "long" else -1
    stop_px = entry * (1 - sgn * stop / 100) if stop else None
    tgt_px = entry * (1 + sgn * target / 100) if target else None
    exit_px = reason = exit_day = None
    for i, d in enumerate(path):
        if d not in df.index:
            continue
        o, h, l, c = (float(df.at[d, k]) for k in ("Open", "High", "Low", "Close"))
        if i > 0 and stop_px and (o <= stop_px if sgn > 0 else o >= stop_px):
            exit_px, reason, exit_day = o, "stop_gap", d
        elif stop_px and (l <= stop_px if sgn > 0 else h >= stop_px):
            exit_px, reason, exit_day = stop_px, "stop", d          # stop assumed first if both touched
        elif tgt_px and (h >= tgt_px if sgn > 0 else l <= tgt_px):
            exit_px, reason, exit_day = tgt_px, "target", d
        elif i == hold:
            use_open = spec.get("exit_at") == "open" and hold > 0
            exit_px, reason, exit_day = (o if use_open else c), "time", d
        if exit_px is not None:
            break
    if exit_px is None:
        return row
    gross = _bps(side, entry, exit_px)
    net = gross - float(spec.get("cost_bps", 10))
    spy_entry = float(spy.at[entry_day, "Open"])
    spy_exit = float(spy.at[exit_day, "Open" if reason == "time" and spec.get("exit_at") == "open"
                            and hold > 0 else "Close"])
    spy_bps = (spy_exit / spy_entry - 1) * 1e4
    row.update(status="closed", exit_date=str(exit_day), exit_px=round(exit_px, 4), exit_reason=reason,
               gross_bps=round(gross, 2), net_bps=round(net, 2), spy_bps=round(spy_bps, 2),
               hedged_bps=round(net - sgn * spy_bps, 2))
    return row


def score(rows: list[dict], rule: dict) -> dict:
    """Day-clustered stats on closed trades and the frozen verdict."""
    metric = rule.get("metric", "net_bps")
    closed = [r for r in rows if r["status"] == "closed"]
    by_day: dict[str, list[float]] = {}
    for r in closed:
        by_day.setdefault(r["exit_date"], []).append(float(r[metric]))
    daily = [sum(v) / len(v) for v in by_day.values()]
    n = len(daily)
    mean = sum(daily) / n if n else 0.0
    sd = math.sqrt(sum((x - mean) ** 2 for x in daily) / (n - 1)) if n > 1 else 0.0
    t = mean / (sd / math.sqrt(n)) if sd > 0 else 0.0
    if rule.get("early_fail_days") and n >= rule["early_fail_days"] and mean < rule["early_fail_mean_bps"]:
        verdict = "FAIL"
    elif n < rule["min_days"]:
        verdict = "COLLECTING"
    elif mean >= rule["pass_mean_bps"] and t >= rule["pass_t"]:
        verdict = "PASS"
    elif n >= rule["max_days"]:
        verdict = "FAIL"
    else:
        verdict = "CONTINUE"
    return {"metric": metric, "trades": len(closed), "days": n, "mean_bps": round(mean, 2),
            "t": round(t, 2), "open": sum(r["status"] in ("pending", "open") for r in rows),
            "verdict": verdict}


# ---------- strategies ----------

def load_strategy(sid: str):
    path = TEAM / "strategies" / sid / "strategy.py"
    spec_obj = importlib.util.spec_from_file_location(f"strategy_{sid}", path)
    mod = importlib.util.module_from_spec(spec_obj)
    spec_obj.loader.exec_module(mod)
    return mod, load_json(TEAM / "strategies" / sid / "spec.json", {})


def validate_signals(sigs, universe: set[str], cap: int) -> list[dict]:
    out = []
    for s in sigs or []:
        if isinstance(s, dict) and s.get("ticker") in universe and s.get("side") in ("long", "short"):
            out.append({"ticker": s["ticker"], "side": s["side"]})
    return out[:cap]


def run_one(sid: str, asof: date, bars_cache: dict, dry_run: bool) -> dict:
    mod, spec = load_strategy(sid)
    uni = list(mod.universe())
    bars = bars_cache.setdefault(tuple(sorted(uni)), download(uni, asof))
    sessions = sorted(d for d in bars["SPY"].index if d <= asof)
    rows = [advance(r, spec, bars, sessions) for r in read_ledger(sid)]
    traded_today = bool(sessions) and sessions[-1] == asof
    new = 0
    if traded_today and not stopped() and not any(r["signal_date"] == str(asof) for r in rows):
        sigs = validate_signals(mod.signals(asof, truncate(bars, asof)), set(uni),
                                int(spec.get("max_signals_per_day", 20)))
        rows += [{"strategy": sid, "signal_date": str(asof), "status": "pending", **s} for s in sigs]
        new = len(sigs)
    status = score(rows, spec["rule"]) | {"new_signals": new, "asof": str(asof), "traded_today": traded_today}
    if not dry_run:
        write_ledger(sid, rows)
        save_json(PAPER / f"{sid}_status.json", status)
    return status


def run(asof: date, dry_run: bool = False, only: str | None = None) -> dict[str, dict]:
    reg = load_json(REGISTRY, {"strategies": {}})
    results: dict[str, dict] = {}
    bars_cache: dict = {}
    for sid, meta in reg.get("strategies", {}).items():
        if meta.get("status") != "active" or (only and sid != only):
            continue
        try:
            results[sid] = run_one(sid, asof, bars_cache, dry_run)
            log(f"paper {sid}: {results[sid]}", "paper")
        except Exception as e:  # noqa: BLE001 - one broken strategy must not stop the others
            results[sid] = {"verdict": "ERROR", "error": repr(e)[:500]}
            log(f"paper {sid} ERROR {e!r}", "paper")
    if not dry_run:
        save_json(STATE / "paper_status.json", results)
    return results


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default=None)
    a = ap.parse_args()
    d = date.fromisoformat(a.date) if a.date else datetime.now().date()
    for k, v in run(d, a.dry_run, a.only).items():
        print(k, v)
    if not load_json(REGISTRY, {}).get("strategies"):
        print("no strategies registered")
    sys.exit(0)
