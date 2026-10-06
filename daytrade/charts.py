"""One chart per setup, marking every rule step, for eyeball verification."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from . import data  # noqa: E402


def _candles(ax, bars: pd.DataFrame):
    x = range(len(bars))
    up = bars["close"] >= bars["open"]
    colors = ["#26a69a" if u else "#ef5350" for u in up]
    ax.vlines(x, bars["low"], bars["high"], color=colors, linewidth=0.8)
    body_lo = bars[["open", "close"]].min(axis=1)
    body_h = (bars["close"] - bars["open"]).abs().clip(lower=1e-6)
    ax.bar(x, body_h, bottom=body_lo, color=colors, width=0.7)


def plot_setup(s: dict, path, pad_before: int = 40, pad_after: int = 15):
    s = {k: (None if not isinstance(v, (list, tuple)) and pd.isna(v) else v) for k, v in s.items()}
    m1 = data.load(s["ticker"], "1m")
    day = m1[m1.index.date == s["day"]]
    start = s["sweep_start"] - pd.Timedelta(minutes=pad_before)
    stages = ("exit_ts", "entry_ts", "trigger_ts", "choch_ts", "reclaim_close", "sweep_start")
    end_ts = next(s[k] for k in stages if s[k] is not None)
    if s["status"] == "entry_timeout":
        end_ts = s["choch_ts"] + pd.Timedelta(minutes=15)  # show the whole entry window
    end = end_ts + pd.Timedelta(minutes=pad_after)
    bars = day[(day.index >= start) & (day.index <= end)]
    pos = {ts: i for i, ts in enumerate(bars.index)}

    def xi(ts):
        return pos.get(ts, None)

    fig, ax = plt.subplots(figsize=(14, 6.5))
    _candles(ax, bars)
    n = len(bars)
    ax.hlines(s["level"], 0, n - 1, colors="#7e57c2", linestyles="--", linewidth=1.2,
              label=f"{s['level_name']} {s['level']:.2f}")

    if s["sweep_start"] is not None and xi(s["sweep_start"]) is not None:
        x0 = xi(s["sweep_start"])
        x1 = xi(s["reclaim_close"]) if s["reclaim_close"] in pos else n - 1
        ax.axvspan(x0 - 0.5, x1 - 0.5, color="#7e57c2", alpha=0.08, label="sweep -> 5m reclaim close")
    if s["extreme_ts"] is not None and xi(s["extreme_ts"]) is not None:
        ax.plot(xi(s["extreme_ts"]), s["extreme"], "v" if s["direction"] == "short" else "^",
                color="black", ms=9, label=f"sweep extreme {s['extreme']:.2f}")
    if s["swing_ts"] is not None and xi(s["swing_ts"]) is not None:
        ax.plot(xi(s["swing_ts"]), s["swing"], "o", mfc="none", mec="#ff9800", ms=11, mew=2,
                label=f"swing broken {s['swing']:.2f}")
    if s["choch_ts"] is not None and xi(s["choch_ts"]) is not None:
        ax.axvline(xi(s["choch_ts"]), color="#ff9800", linewidth=1, label="CHoCH close")
    if s["zone_lo"] is not None:
        zx0 = xi(s["choch_ts"]) or 0
        ax.fill_between([zx0, n - 1], s["zone_lo"], s["zone_hi"], color="#42a5f5", alpha=0.25,
                        label=f"zone ({s['zone_kind']}) {s['zone_lo']:.2f}-{s['zone_hi']:.2f}")
    if s["entry"] is not None and xi(s["entry_ts"]) is not None:
        xe = xi(s["entry_ts"])
        ax.plot(xe, s["entry"], ">", color="#1565c0", ms=10, label=f"entry {s['entry']:.2f}")
        ax.hlines(s["stop"], xe, n - 1, colors="#c62828", linewidth=1.2, label=f"stop {s['stop']:.2f}")
        if s["tp"] is not None:
            ax.hlines(s["tp"], xe, n - 1, colors="#2e7d32", linewidth=1.2,
                      label=f"TP {s['tp_name']} {s['tp']:.2f}")
    if s["exit_ts"] is not None and xi(s["exit_ts"]) is not None:
        ax.plot(xi(s["exit_ts"]), s["exit"], "X", color="black", ms=10,
                label=f"exit {s['exit_reason']} {s['exit']:.2f}")

    step = max(1, n // 14)
    ax.set_xticks(range(0, n, step))
    ax.set_xticklabels([bars.index[i].strftime("%H:%M") for i in range(0, n, step)], fontsize=8)
    r = f"  net {s['r_net']:+.2f}R" if s["r_net"] is not None else ""
    ax.set_title(f"{s['ticker']} {s['day']}  {s['direction'].upper()}  [{s['status']}]{r}", fontsize=12)
    ax.legend(loc="best", fontsize=8)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
