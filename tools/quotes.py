"""Quote Clerk - live Webull bid/ask at the moments our paper trades would really fill.

    python tools/quotes.py capture close     # StockAnalysis_Team_QuoteClose, Mon-Fri 12:56 PT (3:56 PM ET)
    python tools/quotes.py capture open      # StockAnalysis_Team_QuoteOpen,  Mon-Fri 06:31 PT (9:31 AM ET)
    python tools/quotes.py capture open2     # ~9:45 AM ET - run by the Scan Operator's 06:40/06:50 PT tick (no own task)
    python tools/quotes.py on1               # re-price ON1's paper trades at the captured quotes
    python tools/quotes.py etf               # ETF fill costs: close / 9:31 / ~9:45 half-spreads, real overnight
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

from common import LIVE_V3, LIVE_V4, LOGGED_OUT_RX, LOGIN_HELP, STATE, WEBULL_AUTH_RX, WEBULL_HELP, TEAM, load_json, log, now_pt, post, save_json

QUOTES = TEAM / "paper" / "quotes.csv"
QFIELDS = ["date", "when", "ticker", "bid", "ask", "bid_size", "ask_size", "last", "quote_time"]
ON1_LEDGER = LIVE_V3 / "data" / "paper" / "on1_paper_ledger.csv"
EPRE_LEDGER = LIVE_V4 / "data" / "paper" / "epre_ledger.csv"
RULES = TEAM / "team" / "real_price_rules.json"
USAGE = STATE / "usage.csv"
INVALID = TEAM / "paper" / "quote_invalid_symbols.json"     # tickers Webull's quote tool doesn't know
TOOL = "mcp__claude_ai_Webull__get_stock_snapshot"
# Always quoted at every capture (2026-11-23, user-approved plan): measures whether the ETF overnight premium
# (buy the close, sell the open) survives real Webull fills - it needs <= ~1 bp per side. Measurement, not a test.
ETFS = ["SPY", "QQQ", "IWM", "IJR", "MDY", "DIA"]
OPEN2_FROM, OPEN2_UNTIL = (6, 40), (6, 54)        # PT; the Scan Operator ticks at :40 and :50 -> ~9:40-9:52 ET
OPEN2_STATE = STATE / "quotes_open2.json"


# ---------- which tickers ----------

def needs(when: str, today: date) -> list[str]:
    """Tickers whose paper trade fills at this capture.
    close: ON1 picks made today (bought at the close) + team trades that may exit at today's close.
    open:  ON1 picks from the previous session (sold at the open) + team trades entering/exiting at the open.
    open2 (~9:45 ET): the same tickers as open - is a later open fill cheaper than 9:31, the widest minute?
    Every capture also quotes ETFS."""
    out: set[str] = set(ETFS)
    if ON1_LEDGER.exists():
        led = pd.read_csv(ON1_LEDGER, usecols=["day", "ticker"])
        days = sorted(led["day"].unique())
        if when == "close":
            out |= set(led.loc[led["day"] == str(today), "ticker"])
        else:
            prev = [d for d in days if d < str(today)]
            if prev:
                out |= set(led.loc[led["day"] == prev[-1], "ticker"])
    if when == "close" and EPRE_LEDGER.exists():     # EPRE buys at the close and sells at a later close
        e = pd.read_csv(EPRE_LEDGER, usecols=["entry_day", "exit_day", "ticker"])
        out |= set(e.loc[(e["entry_day"] == str(today)) | (e["exit_day"] == str(today)), "ticker"])
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
               if line[:10] >= monday and ",quote_clerk," in line and not line.endswith(",logged_out"))


def prompt(batches: list[list[str]]) -> str:
    lines = [f"You are the Quote Clerk. First load the tool: ToolSearch with query \"select:{TOOL}\".",
             f"Then call {TOOL} once per batch below, with category \"US_STOCK\", extend_hour_required false,",
             "overnight_required false, and symbols exactly as given (comma-separated). If a call fails with",
             "INVALID_SYMBOL [X], call it again for that batch WITHOUT X (repeat if another symbol is named, up to 4",
             "times per batch). Do nothing else: no other tools, no analysis, no retries of a batch that returned",
             "data. When every batch is done, reply DONE."]
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
            # A large result is saved to a file and only a note is streamed ("Full output saved to: X.json" or
            # "Output has been saved to X.txt.") - read the file: a [{type,text}] list, or the raw payload.
            for t in list(texts):
                m = re.search(r"saved to:? (\S+?\.(?:json|txt))(?=\.?\s|\.?$)", t or "")
                if not (m and os.path.exists(m.group(1))):
                    continue
                raw = open(m.group(1), encoding="utf-8").read()
                try:
                    saved = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(saved, list) and saved and isinstance(saved[0], dict) and "symbol" in saved[0]:
                    texts.append(raw)
                elif isinstance(saved, list):
                    texts += [c.get("text", "") for c in saved if isinstance(c, dict)]
                elif isinstance(saved, str):
                    texts.append(saved)
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


def open2_due(now: datetime) -> bool:
    """The Scan Operator's first weekday tick in the open2 window, at most 2 tries a day, none after a success."""
    if now.weekday() >= 5 or not (datetime.strptime("%d:%d" % OPEN2_FROM, "%H:%M").time() <= now.time()
                                  <= datetime.strptime("%d:%d" % OPEN2_UNTIL, "%H:%M").time()):
        return False
    st = load_json(OPEN2_STATE, {})
    return st.get("date") != str(now.date()) or (st.get("tries", 0) < 2 and not st.get("ok"))


def too_late(when: str, now: datetime) -> str | None:
    """A capture after its valid window (team/schedule.json retry_until + 2 min grace) would record quotes from
    the wrong moment (e.g. after hours, when the PC woke late) - those are worse than no quotes. Skip it."""
    if when == "open2":
        end = datetime.combine(now.date(), datetime.strptime("%d:%d" % OPEN2_UNTIL, "%H:%M").time())             + timedelta(minutes=2)
        return f"quotes open2: skipped - started {now:%H:%M}, after its window" if now > end else None
    j = load_json(TEAM / "team" / "schedule.json", {}).get("jobs", {}).get(
        f"StockAnalysis_Team_Quote{when.capitalize()}", {})
    if not j.get("retry_until"):
        return None
    end = datetime.combine(now.date(), datetime.strptime(j["retry_until"], "%H:%M").time()) + timedelta(minutes=2)
    return (f"quotes {when}: skipped - started {now:%H:%M}, after its {j['at']}-{j['retry_until']} window; "
            f"late quotes would be from the wrong moment, so today is a gap") if now > end else None


def capture(when: str, dry_run: bool = False) -> str:
    today = now_pt().date()
    if today.weekday() >= 5:
        return "quotes: weekend - nothing to capture"
    if not dry_run and (late := too_late(when, now_pt())):
        return late
    tickers = needs(when, today)
    if not tickers:
        return f"quotes {when}: no open paper trades need quotes - Claude not launched"
    cfg = load_json(TEAM / "team" / "roles.json", {})["roles"]["quote_clerk"]
    if not cfg.get("enabled"):
        return "quotes: quote_clerk disabled in team/roles.json"
    if runs_this_week() >= int(cfg.get("weekly_cap", 12)):
        post("ops", f"⚠️ Quote Clerk weekly cap reached - {when} quotes NOT captured today", "Team - Ops Monitor")
        return "quotes: weekly cap reached"
    invalid = set(load_json(INVALID, []))
    skipped = sorted(set(tickers) & invalid)
    tickers = [t for t in tickers if t not in invalid]
    batches = [tickers[i:i + 100] for i in range(0, len(tickers), 100)]
    text = prompt(batches)
    if dry_run:
        return f"[dry-run] {len(tickers)} tickers in {len(batches)} batch(es)\n{text}"
    want, rows, bad, results, res, status, start = set(tickers), {}, set(), [], {}, "failed", time.time()
    # One retry inside the capture window: the Scan Operator ticks every 10 min, so it can never re-run a
    # 3-minute quote window itself - a transient failure (Webull/CLI hiccup) gets its second chance here.
    for attempt in (1, 2):
        todo = sorted(want - set(rows))
        stream = _launch(prompt([todo[i:i + 100] for i in range(0, len(todo), 100)]), cfg, today, when, attempt)
        if re.search(LOGGED_OUT_RX, stream) and not _tool_results(stream):
            status = "logged_out"
            break
        if re.search(WEBULL_AUTH_RX, stream) and not _tool_results(stream):
            status = "webull_auth"          # retrying can't help - only the user can sign the connector back in
            break
        results += _tool_results(stream)
        # Webull doesn't list these. Only from tool results - the prompt's own "INVALID_SYMBOL [X]" example is
        # in the stream too.
        new_bad = {s for line in stream.splitlines() if '"tool_result"' in line
                   for s in re.findall(r"INVALID_SYMBOL[^\[]*\[([A-Z0-9.\-]+)\]", line)}
        if new_bad:
            bad |= new_bad
            save_json(INVALID, sorted(invalid | bad))
            want -= new_bad
        rows |= _rows(_tool_results(stream), want, today, when)
        res = next((json.loads(l) for l in stream.splitlines()[::-1] if l.startswith('{"type":"result"')), res)
        status = "ok" if len(rows) >= 0.9 * len(want) else ("partial" if rows else "failed")
        if status == "ok" or (rows == {} and results) or attempt == 2 or too_late(when, now_pt()):
            break
        log(f"quotes {when}: attempt 1 got {len(rows)}/{len(want)} - retrying once in 30 s", "quotes")
        time.sleep(30)
    if rows:
        new = not QUOTES.exists()
        QUOTES.parent.mkdir(parents=True, exist_ok=True)
        with open(QUOTES, "a", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=QFIELDS)
            if new:
                w.writeheader()
            w.writerows(rows.values())
    if not rows and results:
        status = "market_closed"            # Webull answered, but every quote is from an earlier day (holiday)
    if when == "open2":
        st = load_json(OPEN2_STATE, {})
        st = st if st.get("date") == str(today) else {"date": str(today), "tries": 0}
        st["tries"] += 1
        st["ok"] = st.get("ok") or status in ("ok", "partial", "market_closed")
        save_json(OPEN2_STATE, st)
    new_usage = not USAGE.exists()
    with open(USAGE, "a", encoding="utf-8") as fh:
        if new_usage:
            fh.write("date,role,model,turns,minutes,cost_equiv_usd,status\n")
        fh.write(f"{today},quote_clerk,{cfg['model']},{res.get('num_turns', '')},{(time.time() - start) / 60:.1f},"
                 f"{res.get('total_cost_usd', '')},{status}\n")
    msg = (f"quotes {when}: {len(rows)}/{len(want)} tickers captured ({status})"
           + (f"; {len(skipped) + len(bad)} not on Webull, skipped: {sorted(set(skipped) | bad)[:10]}"
              if skipped or bad else ""))
    if status == "logged_out":
        post("ops", f"🔴 Quote Clerk {when} {today}: NOTHING captured - {LOGIN_HELP} Every team role fails until "
                    f"then.", "Team - Ops Monitor")
    elif status == "webull_auth":
        post("ops", f"🔴 Quote Clerk {when} {today}: NOTHING captured - {WEBULL_HELP} Real-price checks (ON1/EPRE) "
                    f"lose every day until then.", "Team - Ops Monitor")
    elif status in ("partial", "failed"):
        post("ops", f"⚠️ Quote Clerk {when} {today}: only {len(rows)}/{len(want)} quotes captured - those trades "
                    f"fall back to official prices. Log: state/logs/{today}-quote_clerk-{when}.jsonl",
             "Team - Ops Monitor")
    return msg


def _launch(text: str, cfg: dict, today, when: str, attempt: int) -> str:
    """One headless Quote Clerk run; returns its stream-json output (also saved to state/logs)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "ANTHROPIC"))}
    cmd = [shutil.which("claude") or "claude", "-p", text, "--permission-mode", "dontAsk",
           "--settings", str(TEAM / "team" / "settings" / "quote_clerk.json"), "--model", cfg["model"],
           "--max-turns", str(cfg["max_turns"]), "--output-format", "stream-json", "--verbose",
           "-n", f"team-quote-clerk-{today}-{when}"]
    try:
        r = subprocess.run(cmd, cwd=TEAM, env=env, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=cfg["timeout_min"] * 60)
        stream = r.stdout + r.stderr
    except subprocess.TimeoutExpired as e:
        stream = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
    (STATE / "logs").mkdir(parents=True, exist_ok=True)
    name = f"{today}-quote_clerk-{when}" + ("" if attempt == 1 else f"-{attempt}") + ".jsonl"
    (STATE / "logs" / name).write_text(stream, encoding="utf-8")
    return stream


def _rows(results: list, want: set, today, when: str) -> dict:
    """Usable quotes from Webull tool results: wanted ticker, bid <= ask, quoted today (holiday quotes dropped)."""
    rows = {}
    for d in results:
        sym = str(d.get("symbol", "")).upper()
        qt = d.get("quote_time")
        qday = (datetime.fromtimestamp(int(qt) / 1000).date() if str(qt).isdigit() else None)
        bid, ask = _f(d.get("bid")), _f(d.get("ask"))
        if sym in want and bid and ask and ask >= bid and qday == today:
            rows[sym] = {"date": str(today), "when": when, "ticker": sym, "bid": bid, "ask": ask,
                         "bid_size": d.get("bid_size", ""), "ask_size": d.get("ask_size", ""),
                         "last": d.get("price", ""), "quote_time": qt}
    return rows


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


def epre(write: bool = True) -> dict:
    """V4 EPRE's closed trades re-priced: buy at the ask near the entry close, sell at the bid near the exit
    close; hedged with the ledger's own hedge leg. Its real-money bar (RULES.md checkpoint B, hedged mean
    >= +10 bps) must also hold here - see team/real_price_rules.json."""
    rule = load_json(RULES, {}).get("epre", {})
    if not EPRE_LEDGER.exists():
        return {"verdict": "NO DATA"}
    led = pd.read_csv(EPRE_LEDGER).dropna(subset=["hedged_bps"])
    q = load_quotes()
    rows = []
    for r in led.itertuples():
        buy, sell = q.get((str(r.entry_day), "close", r.ticker)), q.get((str(r.exit_day), "close", r.ticker))
        if buy and sell:
            real = (sell[0] / buy[1] - 1) * 1e4
            rows.append({"exit_day": r.exit_day, "paper_hedged": r.hedged_bps,
                         "real_hedged": real - r.hedge_bps, "cost_bps": r.ret_bps - real})
    out = {"trades": len(rows), "rule": rule.get("text", "")}
    if rows:
        x = pd.DataFrame(rows)
        per_day = x.groupby("exit_day")["real_hedged"].mean()
        sd = per_day.std(ddof=1) if len(per_day) > 1 else 0.0
        out |= {"exit_days": len(per_day), "real_hedged_mean_bps": round(float(x["real_hedged"].mean()), 1),
                "paper_hedged_mean_bps_same_trades": round(float(x["paper_hedged"].mean()), 1),
                "spread_cost_bps": round(float(x["cost_bps"].mean()), 1),
                "real_t": round(float(per_day.mean() / (sd / math.sqrt(len(per_day)))), 2) if sd and sd > 0 else 0.0}
    if write:
        save_json(TEAM / "paper" / "epre_real_price_status.json", out)
    return out


def etf_fills(write: bool = True) -> dict:
    """Per ETF: median half-spread (bps of the ask) at the close, 9:31 and ~9:45 captures, and the real overnight
    return (buy at the close ask, sell at the next open bid) next to the mid-to-mid return. The overnight idea
    needs the two half-spreads to total <= ~2 bps (2005-2017 probe: 1 bp/side IJR beat holding, 2 bp/side dead)."""
    if not QUOTES.exists():
        return {"note": "no quotes yet"}
    q = pd.read_csv(QUOTES)
    q = q[q["ticker"].isin(ETFS)].copy()
    if q.empty:
        return {"note": "no ETF quotes yet"}
    q["half_bps"] = (q["ask"] - q["bid"]) / q["ask"] / 2 * 1e4
    q["mid"] = (q["ask"] + q["bid"]) / 2
    q = q.drop_duplicates(["date", "when", "ticker"], keep="last")
    out = {"bar": "close half-spread + open half-spread <= ~2 bps total for the overnight idea to have a chance"}
    for t in ETFS:
        x = q[q["ticker"] == t]
        if x.empty:
            continue
        row = {w: round(float(x.loc[x["when"] == w, "half_bps"].median()), 2)
               for w in ("close", "open", "open2") if (x["when"] == w).any()}
        row |= {f"days_{w}": int((x["when"] == w).sum()) for w in ("close", "open", "open2")}
        c = x[x["when"] == "close"].set_index("date")
        for w in ("open", "open2"):
            o = x[x["when"] == w].set_index("date")
            days = sorted(c.index)
            nxt = [next((e for e in sorted(o.index) if e > d), None) for d in days]
            pairs = [(d, n) for d, n in zip(days, nxt)                      # one night (a weekend counts as one)
                     if n is not None and (date.fromisoformat(n) - date.fromisoformat(d)).days <= 4]
            if pairs:
                real = [(o.loc[n, "bid"] / c.loc[d, "ask"] - 1) * 1e4 for d, n in pairs]
                mid = [(o.loc[n, "mid"] / c.loc[d, "mid"] - 1) * 1e4 for d, n in pairs]
                row[f"overnight_to_{w}"] = {"nights": len(pairs), "real_mean_bps": round(float(pd.Series(real).mean()), 1),
                                            "mid_mean_bps": round(float(pd.Series(mid).mean()), 1)}
        out[t] = row
    if write:
        save_json(TEAM / "paper" / "etf_fill_status.json", out)
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    if args[:1] == ["capture"]:
        msg = capture(args[1], dry_run="--dry-run" in args)
        log(msg, "quotes")
        # A failed capture must show as a failed task (exit 1): the Scan Operator and Ops Monitor read the exit
        # code, and on 2026-11-13 a logged-out Clerk exited 0 and nothing looked wrong all day.
        sys.exit(1 if re.search(r"\((failed|logged_out|webull_auth)\)", msg) else 0)
    elif args[:1] == ["on1"]:
        print(on1())
    elif args[:1] == ["epre"]:
        print(epre())
    elif args[:1] == ["etf"]:
        print(json.dumps(etf_fills(), indent=1))
    else:
        print(__doc__)
