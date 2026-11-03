"""The end-of-day report in #agent-ops (Mon-Fri, at the end of the dispatch, ~2:51 PM PT on a quiet day).

Script only, zero Claude tokens. One message the user can read top to bottom:

    ✅/🛑 Daily report <day>     - did every job run
    ⚠️ Needs you                  - only when something does
    📈 Live tests                 - each test's numbers + what its next decision still needs (tools/outlook.py)
    💵 Real prices (Webull)       - today's quote captures, ON1 / EPRE re-priced at real bid/ask
    🔁 V2 trades today            - what the threshold / rank tracks opened and closed
    🤖 Team today                 - which roles ran and their headline, research moves (or "quiet day")
    ℹ️ Notes                      - one-time context (e.g. a loss cluster)

Problems are ALSO posted straight away by the Ops Monitor, so a slow research run never delays an alert.
"""
from __future__ import annotations

import re
from datetime import date

import outlook
from common import OUTBOX, STATE, TEAM, load_json, post

LIMIT = 1900   # Discord caps a message at 2,000 characters; longer reports go out as several messages


def _num(rx: str, text: str) -> tuple[str, ...] | None:
    m = re.search(rx, text)
    return m.groups() if m else None


def live_tests(snapshot: str) -> list[str]:
    need = outlook.short(snapshot)
    out = []
    for label in ("ON1 paper", "G2 paper"):
        g = _num(rf"\[{label}\] (\d+) days, \d+ trades \| mean ([+-][\d.]+) bps \| day-t ([+-]?[\w.]+)", snapshot)
        if g:
            out.append(f"• **V3 {label}** - day {g[0]} · mean {float(g[1]):+.1f} bps · t {g[2]}")
            if label in need:
                out.append(f"  ↳ {need[label]}")
    g = _num(r"\[EPRE paper\] closed (\d+) \| hedged mean ([+-][\d.]+) bps.*?exit-day t ([+-]?[\w.]+)", snapshot)
    if g:
        out.append(f"• **V4 EPRE** - {int(g[0]):,}/1,000 trades · hedged {g[1]} bps · t {g[2]}")
        out.append("  ↳ checkpoint A at 1,000 trades: FAIL if hedged mean < -20 bps")
    g = _num(r"COLLECTING \((\d+)/100 closed trades\)\s+mean R after costs ([+-][\d.]+)", snapshot)
    if g:
        out.append(f"• **V2 rank** - {g[0]}/100 trades · {g[1]}R after costs (GO needs +0.15)")
        if "V2 rank" in need:
            out.append(f"  ↳ {need['V2 rank']}")
    g = _num(r"random-pick control: (\d+) closed, mean R after costs ([+-][\d.]+)", snapshot)
    if g:
        out.append(f"• V2 random control - {g[0]} trades · {g[1]}R (the baseline rank must beat)")
    return out


def quote_coverage(today: date) -> str | None:
    p = STATE / "logs" / f"{today}-quotes.log"
    if not p.exists():
        return None
    got = {}
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if m := re.search(r"quotes (open|close): (\d+)/(\d+) tickers captured \((\w+)\)", line):
            got[m.group(1)] = f"{m.group(2)}/{m.group(3)}" + ("" if m.group(4) == "ok" else f" ({m.group(4)})")
    return " · ".join(f"{k} {v}" for k, v in got.items()) or None


def real_prices(today: date) -> list[str]:
    out = []
    if q := quote_coverage(today):
        out.append(f"• Quotes captured: {q}")
    on1 = load_json(TEAM / "paper" / "on1_real_price_status.json", {})
    if on1.get("days"):
        out.append(f"• **ON1 at real prices** - {on1['verdict']} · day {on1['days']}/15 · real {on1['real_mean_bps']:+.1f} bps "
                   f"vs paper {on1['paper_mean_bps_same_trades']:+.1f} on the same trades · t {on1['real_t']}")
    elif on1:
        out.append(f"• ON1 at real prices - {on1.get('verdict', '?')}: {on1.get('note', 'no data yet')}")
    epre = load_json(TEAM / "paper" / "epre_real_price_status.json", {})
    if epre.get("exit_days"):
        out.append(f"• EPRE at real prices - {epre['trades']} trades · real hedged {epre['real_hedged_mean_bps']:+.1f} bps "
                   f"vs paper {epre['paper_hedged_mean_bps_same_trades']:+.1f} · t {epre['real_t']}")
    elif epre:
        out.append("• EPRE at real prices - no closed trade with both quotes yet")
    return out


def v2_trades(snapshot: str) -> list[str]:
    out, track = [], None
    for raw in snapshot.splitlines():
        line = raw.strip()
        if m := re.match(r"\[(threshold|rank|random)\] closed", line):
            track = m.group(1)
        elif track in ("threshold", "rank") and (m := re.match(r"(new signals|closed) \d{4}-\d{2}-\d{2}: (.*)", line)):
            what = "new signals" if m.group(1) == "new signals" else "closed"
            out.append(f"• {track} {what}: " + m.group(2).replace(" (shares)", "")[:300])
    return out or ["• none"]


def team_today(today: date, pipeline: list[str]) -> list[str]:
    out = []
    for role, r in load_json(STATE / "role_runs.json", {}).items():
        if r.get("date") != str(today):
            continue
        if r.get("status") == "ok":
            f = OUTBOX / f"{role}.txt"
            head = f.read_text(encoding="utf-8").strip().splitlines()[0][:160] if f.exists() else "(no headline)"
            out.append(f"• {role.capitalize()}: {head}")
        else:
            out.append(f"• {role.capitalize()}: did NOT finish ({r.get('status')})")
    out += [f"• Research: {p}" for p in pipeline]
    if not out:
        return ["• Quiet day - no Claude role needed (nothing broke, no checkpoint, nothing scheduled)"]
    return out + ["  (full posts in #agent-director / #agent-research)"]


def compose(today: date, f, pipeline: list[str]) -> str:
    head = (f"🛑 **Daily report {today:%a %m-%d}** - {len(f.alerts)} problem(s)" if f.alerts else
            f"✅ **Daily report {today:%a %m-%d}** - all {f.tasks_checked} scheduled jobs ran OK")
    parts = [head]
    if f.alerts:
        parts.append("**⚠️ Needs you**\n" + "\n".join(f"• {a}" for a in f.alerts))
    if lt := live_tests(f.snapshot):
        parts.append("**📈 Live tests**\n" + "\n".join(lt))
    if rp := real_prices(today):
        parts.append("**💵 Real prices (Webull)**\n" + "\n".join(rp))
    parts.append("**🔁 V2 trades today**\n" + "\n".join(v2_trades(f.snapshot)))
    parts.append("**🤖 Team today**\n" + "\n".join(team_today(today, pipeline)))
    if f.notes:
        parts.append("**ℹ️ Notes**\n" + "\n".join(f"• {n}" for n in f.notes))
    return "\n\n".join(parts)


def chunks(text: str, limit: int = LIMIT) -> list[str]:
    """Split at section breaks (then lines) so no message passes Discord's limit."""
    out, cur = [], ""
    for block in text.split("\n\n"):
        for piece in ([block] if len(block) <= limit else block.splitlines()):
            sep = "\n\n" if piece is block else "\n"
            if cur and len(cur) + len(sep) + len(piece) > limit:
                out.append(cur)
                cur = ""
            cur = f"{cur}{sep}{piece}" if cur else piece[:limit]
    return out + ([cur] if cur else [])


def send(today: date, f, pipeline: list[str], dry_run: bool = False) -> str:
    text = compose(today, f, pipeline)
    for part in chunks(text):
        post("ops", part, "Team - Daily Report", dry_run)
    return text
