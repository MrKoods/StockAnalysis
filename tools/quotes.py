"""Quote Clerk - live Webull bid/ask at the moments our paper trades would really fill.

    python tools/quotes.py capture close     # StockAnalysis_Team_QuoteClose, Mon-Fri 12:56 PT (3:56 PM ET)
    python tools/quotes.py capture open      # StockAnalysis_Team_QuoteOpen,  Mon-Fri 06:31 PT (9:31 AM ET)
    python tools/quotes.py on1               # re-price ON1's paper trades at the captured quotes
    python tools/quotes.py capture close --dry-run    # print the tickers + prompt, launch nothing

Why: paper tests fill at the official open/close. Webull (via its connector) takes LIMIT orders only - no
market-on-open/close - so a real trade buys near the ask and sells near the bid. This measures that cost.

How: the script decides the tickers (zero tokens), then launches the Quote Clerk - Claude Haiku, headless, whose
only allowed tool is Webull's get_stock_snapshot (<= 100 symbols per call). The numbers are read straight from the
tool results in Claude's output stream, never retyped by the model. Results: paper/quotes.csv (committed;
irreplaceable live data). Each run is logged in state/usage.csv as role quote_clerk, under its own weekly cap.
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import date, datetime, timedelta

import pandas as pd

from common import LIVE_V3, STATE, TEAM, load_json, log, now_pt, post, save_json

QUOTES = TEAM / "paper" / "quotes.csv"
QFIELDS = ["date", "when", "ticker", "bid", "ask", "bid_size", "ask_size", "last", "quote_time"]
ON1_LEDGER = LIVE_V3 / "data" / "paper" / "on1_paper_ledger.csv"
RULES = TEAM / "team" / "real_price_rules.json"
USAGE = STATE / "usage.csv"
TOOL = "mcp__claude_ai_Webull__get_stock_snapshot"


# ---------- which tickers ----------

def needs(when: str, today: date) -> list[str]:
    """Tickers whose paper trade fills at this capture.
    close: ON1 picks made today (bought at the close) + team trades that may exit at today's close.
    open:  ON1 picks from the previous session (sold at the open) + team trades entering/exiting at the open."""
    out: set[str] = set()
    if ON1_LEDGER.exists():
        led = pd.read_csv(ON1_LEDGER, usecols=["day", "ticker"])
        days = sorted(led["day"].unique())
        if when == "close":
            out |= set(led.loc[led["day"] == str(today), "ticker"])
        else:
            prev = [d for d in days if d < str(today)]
            if prev:
                out |= set(led.loc[led["day"] == prev[-1], "ticker"])
    import paper_runner as pr
    reg = load_json(pr.REGISTRY, {"strategies": {}})
    for sid, meta in reg.get("strategies", {}).items():
        if meta.get("status") == "active":
            out |= {r["ticker"] for r in pr.read_ledger(sid) if r["status"] in ("pending", "open")}
    return sorted(out)


# ---------- the Clerk ----------

def runs_this_week() -> int:
    if not USAGE.exists():
        return 0
    monday = (now_pt().date() - timedelta(days=now_pt().weekday())).isoformat()
    return sum(1 for line in USAGE.read_text(encoding="utf-8").splitlines()[1:]
               if line[:10] >= monday and ",quote_clerk," in line)


def prompt(batches: list[list[str]]) -> str:
    lines = [f"You are the Quote Clerk. First load the tool: ToolSearch with query \"select:{TOOL}\".",
             f"Then call {TOOL} once per batch below, with category \"US_STOCK\", extend_hour_required false,",
             "overnight_required false, and symbols exactly as given (comma-separated). Do nothing else: no",
             "other tools, no analysis, no retries of a batch that returned data. When every batch is done, reply DONE."]
    lines += [f"Batch {i}: {','.join(b)}" for i, b in enumerate(batches, 1)]
    return "\n".join(lines)


def _tool_results(stream: str) -> list:
    """Every JSON payload returned by the Webull tool, taken verbatim from the stream-json output."""
    out = []
    for line in stream.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") != "user":
            continue
        for part in ev.get("message", {}).get("content", []) or []:
            if not isinstance(part, dict) or part.get("type") != "tool_result":
                continue
            content = part.get("content")
            texts = [content] if isinstance(content, str) else [c.get("text", "") for c in content or []
                                                                if isinstance(c, dict)]
            # A large result (> ~64KB) is saved to a file and only a preview is streamed - read the file.
            for t in list(texts):
                m = re.search(r"Full output saved to: (\S+\.(?:json|txt))", t or "")
                if m and os.path.exists(m.group(1)):
                    saved = json.loads(open(m.group(1), encoding="utf-8").read())
                    texts += [saved] if isinstance(saved, str) else [c.get("text", "") for c in saved
                                                                     if isinstance(c, dict)]
            for t in texts:
                try:
                    data = json.loads(t)
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(data, list):
                    out += [d for d in data if isinstance(d, dict) and "symbol" in d]
    return out


def _f(x) -> float | None:
    try:
        v = float(x)
        return v if math.isfinite(v) and v > 0 else None
    except (TypeError, ValueError):
        return None


def capture(when: str, dry_run: bool = False) -> str:
    today = now_pt().date()
    if today.weekday() >= 5:
        return "quotes: weekend - nothing to capture"
    tickers = needs(when, today)
    if not tickers:
        return f"quotes {when}: no open paper trades need quotes - Claude not launched"
    cfg = load_json(TEAM / "team" / "roles.json", {})["roles"]["quote_clerk"]
    if not cfg.get("enabled"):
        return "quotes: quote_clerk disabled in team/roles.json"
    if runs_this_week() >= int(cfg.get("weekly_cap", 12)):
        post("ops", f"⚠️ Quote Clerk weekly cap reached - {when} quotes NOT captured today", "Team - Ops Monitor")
        return "quotes: weekly cap reached"
    batches = [tickers[i:i + 100] for i in range(0, len(tickers), 100)]
    text = prompt(batches)
    if dry_run:
        return f"[dry-run] {len(tickers)} tickers in {len(batches)} batch(es)\n{text}"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "ANTHROPIC"))}
    cmd = [shutil.which("claude") or "claude", "-p", text, "--permission-mode", "dontAsk",
           "--settings", str(TEAM / "team" / "settings" / "quote_clerk.json"), "--model", cfg["model"],
           "--max-turns", str(cfg["max_turns"]), "--output-format", "stream-json", "--verbose",
           "-n", f"team-quote-clerk-{today}-{when}"]
    start = time.time()
    try:
        r = subprocess.run(cmd, cwd=TEAM, env=env, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=cfg["timeout_min"] * 60)
        stream = r.stdout
    except subprocess.TimeoutExpired as e:
        stream = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
    (STATE / "logs").mkdir(parents=True, exist_ok=True)
    (STATE / "logs" / f"{today}-quote_clerk-{when}.jsonl").write_text(stream, encoding="utf-8")
    want, rows = set(tickers), {}
    results = _tool_results(stream)
    for d in results:
        sym = str(d.get("symbol", "")).upper()
        qt = d.get("quote_time")
        qday = (datetime.fromtimestamp(int(qt) / 1000).date() if str(qt).isdigit() else None)
        bid, ask = _f(d.get("bid")), _f(d.get("ask"))
        if sym in want and bid and ask and ask >= bid and qday == today:   # stale (holiday) quotes are dropped
            rows[sym] = {"date": str(today), "when": when, "ticker": sym, "bid": bid, "ask": ask,
                         "bid_size": d.get("bid_size", ""), "ask_size": d.get("ask_size", ""),
                         "last": d.get("price", ""), "quote_time": qt}
    if rows:
        new = not QUOTES.exists()
        QUOTES.parent.mkdir(parents=True, exist_ok=True)
        with open(QUOTES, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=QFIELDS)
            if new:
                w.writeheader()
            w.writerows(rows.values())
    res = next((json.loads(l) for l in stream.splitlines()[::-1] if l.startswith('{"type":"result"')), {})
    status = "ok" if len(rows) >= 0.9 * len(tickers) else ("partial" if rows else "failed")
    if not rows and results:
        status = "market_closed"            # Webull answered, but every quote is from an earlier day (holiday)
    new_usage = not USAGE.exists()
    with open(USAGE, "a", encoding="utf-8") as fh:
        if new_usage:
            fh.write("date,role,model,turns,minutes,cost_equiv_usd,status\n")
        fh.write(f"{today},quote_clerk,{cfg['model']},{res.get('num_turns', '')},{(time.time() - start) / 60:.1f},"
                 f"{res.get('total_cost_usd', '')},{status}\n")
    msg = f"quotes {when}: {len(rows)}/{len(tickers)} tickers captured ({status})"
    if status in ("partial", "failed"):
        post("ops", f"⚠️ Quote Clerk {when} {today}: only {len(rows)}/{len(tickers)} quotes captured - those trades "
                    f"fall back to official prices. Log: state/logs/{today}-quote_clerk-{when}.jsonl",
             "Team - Ops Monitor")
    return msg


# ---------- real-price scoring ----------

def load_quotes() -> dict[tuple[str, str, str], tuple[float, float]]:
    """(date, when, ticker) -> (bid, ask); the last capture wins."""
    if not QUOTES.exists():
        return {}
    q = pd.read_csv(QUOTES)
    return {(str(r.date), r.when, r.ticker): (float(r.bid), float(r.ask)) for r in q.itertuples()}


def on1(write: bool = True) -> dict:
    """ON1's paper trades re-priced: buy at the ask just before the close, sell at the bid just after the open."""
    rule = load_json(RULES, {}).get("on1", {})
    if not ON1_LEDGER.exists():
        return {"verdict": "NO DATA"}
    led = pd.read_csv(ON1_LEDGER).dropna(subset=["bps", "next_day"])
    q = load_quotes()
    rows = []
    for r in led.itertuples():
        buy, sell = q.get((str(r.day), "close", r.ticker)), q.get((str(r.next_day), "open", r.ticker))
        if buy and sell:
            ask, bid = buy[1], sell[0]
            rows.append({"day": r.day, "ticker": r.ticker, "paper_bps": r.bps,
                         "real_bps": round((bid / ask - 1) * 1e4, 1),
                         "spread_bps": round(((buy[1] - buy[0]) / buy[1] + (sell[1] - sell[0]) / sell[1]) / 2 * 1e4, 1)})
    if not rows:
        out = {"verdict": "COLLECTING", "days": 0, "trades": 0, "note": "no trade has both a close and an open quote yet"}
    else:
        x = pd.DataFrame(rows)
        per_day = x.groupby("day")["real_bps"].mean()
        n = len(per_day)
        sd = per_day.std(ddof=1) if n > 1 else 0.0
        t = float(per_day.mean() / (sd / math.sqrt(n))) if sd and sd > 0 else 0.0
        m = float(x["real_bps"].mean())
        if n < rule.get("min_days", 15):
            verdict = "COLLECTING"
        elif m >= rule.get("pass_mean_bps", 5) and t >= rule.get("pass_t", 2.0):
            verdict = "PASS"
        elif m < 0 or n >= rule.get("max_days", 30):
            verdict = "FAIL"
        else:
            verdict = "CONTINUE"
        out = {"verdict": verdict, "days": n, "trades": len(x), "real_mean_bps": round(m, 1), "real_t": round(t, 2),
               "paper_mean_bps_same_trades": round(float(x["paper_bps"].mean()), 1),
               "avg_half_spread_bps": round(float(x["spread_bps"].mean()) / 2, 1),
               "first_day": str(x["day"].min()), "last_day": str(x["day"].max())}
    out["rule"] = rule.get("text", "")
    if write:
        save_json(TEAM / "paper" / "on1_real_price_status.json", out)
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["capture"]:
        msg = capture(args[1], dry_run="--dry-run" in args)
        log(msg, "quotes")
    elif args[:1] == ["on1"]:
        print(on1())
    else:
        print(__doc__)
