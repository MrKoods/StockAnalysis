"""Run the strategy over the archive and summarize results."""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import data
from .config import DEFAULT, UNIVERSE, Params
from .levels import build_5m, day_levels
from .strategy import scan_day


def run(tickers: list[str] | None = None, p: Params = DEFAULT) -> pd.DataFrame:
    """Every swept level as one row; `status == "traded"` rows are the trades."""
    rows = []
    for t in tickers or UNIVERSE:
        m1 = data.load(t, "1m")
        if not len(m1):
            continue
        levels = day_levels(build_5m(m1, data.load(t, "5m")))
        for day, g in m1.groupby(m1.index.date):
            if day not in levels:
                continue  # no previous session -> no PDH/PDL
            setups = scan_day(t, day, g, levels[day], p)
            _apply_limits(setups, p)
            rows += [s.to_dict() for s in setups]
    return pd.DataFrame(rows)


def _apply_limits(setups, p: Params) -> None:
    """Per ticker per session: one open trade at a time, at most N trades."""
    busy_until = None
    taken = 0
    for s in sorted((s for s in setups if s.status == "candidate"), key=lambda s: s.entry_ts):
        if taken >= p.max_trades_per_day:
            s.status = "skipped_daily_cap"
        elif busy_until is not None and s.entry_ts <= busy_until:
            s.status = "skipped_open_trade"
        else:
            s.status = "traded"
            taken += 1
            busy_until = s.exit_ts


def day_cluster_ci(trades: pd.DataFrame, col: str = "r_net", n: int = 5000, seed: int = 0):
    """95% CI of mean R, resampling whole sessions (trades on one day aren't independent)."""
    if trades.empty:
        return (np.nan, np.nan)
    groups = [g[col].to_numpy() for _, g in trades.groupby("day")]
    rng = np.random.default_rng(seed)
    means = []
    for _ in range(n):
        pick = rng.integers(0, len(groups), len(groups))
        means.append(np.concatenate([groups[i] for i in pick]).mean())
    return tuple(np.percentile(means, [2.5, 97.5]))


def summarize(df: pd.DataFrame) -> dict:
    tr = df[df["status"] == "traded"]
    out = {
        "funnel": df["status"].value_counts().to_dict(),
        "trades": len(tr),
        "days": int(df["day"].nunique()) if len(df) else 0,
    }
    if len(tr):
        out.update(
            win_rate=float((tr["r_net"] > 0).mean()),
            mean_r_gross=float(tr["r_gross"].mean()),
            mean_r_net=float(tr["r_net"].mean()),
            ci95_r_net=day_cluster_ci(tr),
            mean_r_net_tp2=float(tr["r_net_tp2"].mean()),
            exit_reasons=tr["exit_reason"].value_counts().to_dict(),
            zone_kinds=tr["zone_kind"].value_counts().to_dict(),
            median_risk_cents=float(tr["risk"].median() * 100),
            **_concentration(tr),
        )
        out["verdict"] = verdict(out)
    return out


def _concentration(tr: pd.DataFrame) -> dict:
    """Is the result carried by a couple of tickers, days, or outlier trades?"""
    by_t = tr.groupby("ticker")["r_net"].sum().sort_values(ascending=False)
    by_d = tr.groupby("day")["r_net"].sum().sort_values(ascending=False)
    total = tr["r_net"].sum()
    return {
        "mean_r_net_ex_best2_tickers": float(tr[~tr["ticker"].isin(by_t.index[:2])]["r_net"].mean()),
        "mean_r_net_ex_best2_days": float(tr[~tr["day"].isin(by_d.index[:2])]["r_net"].mean()),
        "mean_r_net_ex_best5_trades": float(tr["r_net"].sort_values().iloc[:-5].mean()),
        "total_r_net": float(total),
        "tickers_traded": int(tr["ticker"].nunique()),
    }


def verdict(s: dict) -> str:
    """Pass bar fixed in the test plan (2026-10-05) before any run."""
    m = s["mean_r_net"]
    robust = min(s["mean_r_net_ex_best2_tickers"], s["mean_r_net_ex_best2_days"]) > 0
    if s["trades"] >= 100 and m >= 0.10 and robust:
        return "PASS: worth more data"
    if m < 0 or s["mean_r_net_ex_best5_trades"] < 0 <= m:
        return "FAIL"
    return "INCONCLUSIVE"
