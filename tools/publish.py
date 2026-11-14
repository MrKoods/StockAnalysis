"""Push the team branch to GitHub after a dispatch - only when a secret scan of the outgoing commits is clean.

    python tools/publish.py            # scan + push
    python tools/publish.py --check    # scan only, print what would be pushed

The repo (MrKoods/StockAnalysis) is PUBLIC. So the push is gated:
  - every line ADDED by the unpushed commits is checked against secret patterns AND against the literal values in
    the V2 .env (webhooks, API keys) - the strongest check, since those are the secrets that actually exist;
  - added files named like secrets (.env, *.pem, *.key, id_rsa) block the push outright;
  - a hit blocks the WHOLE push and posts to #agent-ops (file + line number only, never the matched text).
Never forces: a rejected push (remote moved) is reported, not overwritten.
"""
from __future__ import annotations

import re
import sys

from common import git, log, post, read_env

BRANCH = "team"
REMOTE = "origin"
USER = "Team - Ops Monitor"
SECRET_RX = [re.compile(p) for p in (
    r"discord(?:app)?\.com/api/webhooks/\d+/[\w-]{20,}",
    r"sk-ant-[A-Za-z0-9_-]{20,}",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\bgh[pousr]_[A-Za-z0-9]{30,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"(?i)\b(api[_-]?key|secret|password|access[_-]?token)\b\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{24,}",
)]
SECRET_FILE_RX = re.compile(r"(^|/)(\.env(\.\w+)?|id_rsa\w*|[^/]+\.(pem|key|p12|pfx))$")
MIN_ENV_VALUE = 12          # shorter .env values (flags, small numbers) are not secrets and would match anything


def env_values() -> list[str]:
    return sorted({v for v in read_env().values() if len(v) >= MIN_ENV_VALUE}, key=len, reverse=True)


def scan(diff: str, names: list[str], secrets: list[str]) -> list[str]:
    """Problems in an outgoing `git diff -U0` (file + line only - the text itself is never repeated)."""
    out = [f"{n}: file name looks like a secret" for n in names if SECRET_FILE_RX.search(n)]
    path, line_no = "?", 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            path = raw[6:] if raw.startswith("+++ b/") else raw[4:]
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            line_no = int(m.group(1)) if m else 0
        elif raw.startswith("+"):
            text = raw[1:]
            if any(rx.search(text) for rx in SECRET_RX):
                out.append(f"{path}:{line_no}: matches a secret pattern")
            elif any(s in text for s in secrets):
                out.append(f"{path}:{line_no}: contains a value from .env")
            line_no += 1
    return out


def run(dry_run: bool = False) -> str:
    fetch = git("fetch", "-q", REMOTE, BRANCH)
    ahead = git("rev-list", "--count", f"{REMOTE}/{BRANCH}..{BRANCH}")
    if not ahead.isdigit():
        return f"publish: can't compare with {REMOTE}/{BRANCH} ({(fetch or ahead)[:200]})"
    if ahead == "0":
        return "publish: nothing to push"
    rng = f"{REMOTE}/{BRANCH}..{BRANCH}"
    names = git("diff", "--name-only", "--diff-filter=A", rng).splitlines()
    problems = scan(git("diff", "-U0", "--no-color", "--no-ext-diff", rng), names, env_values())
    if problems:
        msg = (f"🔒 **GitHub push BLOCKED** - {len(problems)} possible secret(s) in {ahead} unpushed team commit(s). "
               "Nothing was pushed. Remove them (amend/rewrite the local commits), then the next dispatch pushes:\n"
               + "\n".join(problems[:15]))
        if not dry_run:
            post("ops", msg, USER)
        return "publish: BLOCKED\n" + "\n".join(problems)
    if dry_run:
        return f"publish: clean - would push {ahead} commit(s)"
    out = git("push", "-q", REMOTE, BRANCH)
    if git("rev-list", "--count", f"{REMOTE}/{BRANCH}..{BRANCH}") != "0":
        post("ops", f"⚠️ GitHub push of the team branch failed ({ahead} commit(s) waiting): {out[:300]}\n"
                    "Nothing is lost - the next dispatch tries again.", USER)
        return f"publish: push failed: {out[:300]}"
    return f"publish: pushed {ahead} commit(s)"


if __name__ == "__main__":
    r = run(dry_run="--check" in sys.argv)
    log(r, "dispatch")
