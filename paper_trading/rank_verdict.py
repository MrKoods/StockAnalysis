"""
Go / no-go verdict for trading the rank track with real money.

The rule lives in config (rank_track.go_no_go) and was fixed 2026-10-13,
before the data it judges — see that block's comment. This module only
applies it:

  * mean R after costs  — each closed trade's achieved_rr minus a round-trip
    cost (cost_per_side x 2, as a fraction of price) converted to R through
    that trade's own stop distance
  * week-clustered t    — trades opened the same week move together (same
    market, same sectors), so they're averaged per fill week first and the
    t-stat is taken across weeks, not across trades
  * vs sector ETF       — each trade's return minus its sector ETF's return
    over the same fill->exit days, signed by the trade's side

The random-pick control (random_trades.csv) is summarised next to it for
context; it is deliberately not one of the conditions (it started later and
has far fewer trades).

Usage:
    python -m paper_trading.rank_verdict
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

import pandas as pd

from paper_trading.paper_runner import RANDOM_TRADES_CSV, RANK_TRADES_CSV
from shared.api_clients.market_data_client import fetch_ohlcv_since
from shared.utils.sector_config import get_ticker_benchmark
from swing_model.indicator_pipeline import load_config


def _closed(csv_path: Path) -> pd.DataFrame:
    if not csv_path.exists():
        return pd.DataFrame()
    d = pd.read_csv(csv_path)
    d = d[pd.to_numeric(d.get("achieved_rr"), errors="coerce").notna()].copy()
    for col in ("achieved_rr", "fill_price", "exit_price", "stop_loss"):
        d[col] = pd.to_numeric(d[col], errors="coerce")
    return d.dropna(subset=["fill_price", "exit_price", "stop_loss"])


def _net_r(d: pd.DataFrame, cost_per_side: float) -> pd.Series:
    risk_frac = (d["fill_price"] - d["stop_loss"]).abs() / d["fill_price"]
    return d["achieved_rr"] - (2 * cost_per_side) / risk_frac


def _week_t(d: pd.DataFrame, values: pd.Series) -> tuple[Optional[float], int]:
    weekly = values.groupby(pd.to_datetime(d["fill_date"]).dt.to_period("W")).mean()
    n = len(weekly)
    if n < 2 or weekly.std(ddof=1) == 0:
        return None, n
    return float(weekly.mean() / (weekly.std(ddof=1) / math.sqrt(n))), n


def _vs_sector_etf(d: pd.DataFrame, cfg: dict) -> Optional[float]:
    if d.empty:
        return None
    start = (pd.to_datetime(d["fill_date"]).min() - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    prices: dict[str, Optional[pd.Series]] = {}
    excess = []
    for r in d.itertuples():
        etf = get_ticker_benchmark(cfg, r.ticker)
        if not etf:
            continue
        if etf not in prices:
            bars = fetch_ohlcv_since(etf, start)
            prices[etf] = bars["Close"] if bars is not None and len(bars) else None
        s = prices[etf]
        if s is None:
            continue
        s.index = pd.to_datetime(s.index).tz_localize(None)
        a, b = s.asof(pd.Timestamp(r.fill_date)), s.asof(pd.Timestamp(r.exit_date))
        if pd.isna(a) or pd.isna(b) or a <= 0:
            continue
        side = -1.0 if r.direction == "bearish" else 1.0
        excess.append(side * (r.exit_price / r.fill_price - 1) - side * (b / a - 1))
    return float(sum(excess) / len(excess)) if excess else None


def compute_verdict(cfg: Optional[dict] = None,
                    rank_csv: Path = RANK_TRADES_CSV, random_csv: Path = RANDOM_TRADES_CSV) -> dict:
    cfg = cfg if cfg is not None else load_config()
    rule = cfg.get("rank_track", {}).get("go_no_go", {})
    min_n = int(rule.get("min_closed_trades", 100))
    min_r = float(rule.get("min_mean_r", 0.15))
    min_t = float(rule.get("min_week_t", 2.0))
    cost = float(rule.get("cost_per_side", 0.001))

    d = _closed(rank_csv)
    out: dict = {"n": len(d), "min_n": min_n}
    if d.empty:
        out["verdict"] = "COLLECTING"
        out["text"] = f"Rank-track go/no-go: collecting (0/{min_n} closed trades)."
        return out

    net = _net_r(d, cost)
    week_t, weeks = _week_t(d, net)
    vs_etf = _vs_sector_etf(d, cfg)
    out.update({"mean_r_net": float(net.mean()), "week_t": week_t, "weeks": weeks, "vs_etf": vs_etf})

    ctrl = _closed(random_csv)
    if not ctrl.empty:
        out["random_n"] = len(ctrl)
        out["random_mean_r_net"] = float(_net_r(ctrl, cost).mean())

    if len(d) < min_n:
        out["verdict"] = "COLLECTING"
    elif out["mean_r_net"] < 0:
        out["verdict"] = "NO-GO"
    elif out["mean_r_net"] >= min_r and week_t is not None and week_t >= min_t and vs_etf is not None and vs_etf > 0:
        out["verdict"] = "GO"
    else:
        out["verdict"] = "KEEP COLLECTING"

    t_txt = f"{week_t:.2f}" if week_t is not None else "n/a"
    etf_txt = f"{vs_etf:+.2%}" if vs_etf is not None else "n/a"
    lines = [
        f"Rank-track go/no-go: {out['verdict']} ({len(d)}/{min_n} closed trades)",
        f"  mean R after costs {out['mean_r_net']:+.3f} (need >= {min_r:+.2f}) | "
        f"week-clustered t {t_txt} over {weeks} weeks (need >= {min_t:g}) | "
        f"vs sector ETF {etf_txt}/trade (need > 0)",
    ]
    if "random_n" in out:
        lines.append(f"  random-pick control: {out['random_n']} closed, mean R after costs {out['random_mean_r_net']:+.3f}")
    else:
        lines.append("  random-pick control: no closed trades yet")
    out["text"] = "\n".join(lines)
    return out


if __name__ == "__main__":
    print(compute_verdict()["text"])
