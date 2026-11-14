"""tools/publish.py secret scan - the gate in front of an automatic push to a PUBLIC repo."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import publish

HOOK = "https://discord.com/api/webhooks/123456789012345678/" + "a" * 60


def diff(path: str, *lines: str, start: int = 10) -> str:
    return (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -0,0 +{start},{len(lines)} @@\n"
            + "".join(f"+{l}\n" for l in lines))


def test_clean_diff_passes():
    d = diff("notes/director.md", "EPRE at +23 bps, t 0.37", "token budget: 40 turns", "api_key = os.environ['X']")
    assert publish.scan(d, [], ["supersecretvalue123"]) == []


def test_webhook_blocked_with_location_but_not_the_secret():
    out = publish.scan(diff("reports/x.md", "ok", HOOK, start=5), [], [])
    assert out == ["reports/x.md:6: matches a secret pattern"]
    assert "webhooks" not in out[0]


def test_env_value_blocked_even_without_a_known_pattern():
    out = publish.scan(diff("notes/a.md", "key is Zq9xLm2PvT8wRk4N"), [], ["Zq9xLm2PvT8wRk4N"])
    assert out == ["notes/a.md:10: contains a value from .env"]


def test_anthropic_key_and_assignment_patterns():
    assert publish.scan(diff("t.py", "k = 'sk-ant-api03-" + "x" * 30 + "'"), [], [])
    assert publish.scan(diff("t.py", "API_KEY=" + "A1b2C3d4" * 4), [], [])


def test_removed_lines_are_not_scanned():
    d = f"--- a/x.md\n+++ b/x.md\n@@ -3 +3 @@\n-{HOOK}\n+redacted\n"
    assert publish.scan(d, [], []) == []


def test_secret_file_names_blocked():
    out = publish.scan("", [".env", "tools/a.py", "certs/server.pem", "sub/.env.local"], [])
    assert len(out) == 3


def test_short_env_values_ignored(monkeypatch):
    monkeypatch.setattr(publish, "read_env", lambda: {"A": "true", "B": "x" * 20})
    assert publish.env_values() == ["x" * 20]
