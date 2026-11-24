"""Patch mode (user 2026-11-21): the Engineer proposes edits to files it may not touch; check proves them on a
scratch copy; only the user's `apply` writes the live files, and a failing apply rolls back."""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import patches  # noqa: E402


def test_hard_limit_files_are_never_patchable_and_scoring_code_is():
    assert patches.allowed("V4/epre/paper.py") is None
    assert patches.allowed("team/tools/quotes.py") is None
    assert patches.allowed("V3/daytrade/forward.py") is None
    for f in ("team/tools/gate.py", "team/tools/engineer.py", "team/tools/patches.py", "team/tools/research_data.py",
              "team/team/schedule.json", "team/registry/ideas.csv", "V4/RULES.md", "V2/anything.py",
              "V4/../StockAnalysis/x.py", "V4/data/paper/epre_ledger.csv"):
        assert patches.allowed(f), f


def _repo(root: Path, files: dict[str, str]) -> Path:
    root.mkdir()
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    for cmd in (["init", "-q"], ["add", "."], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"]):
        subprocess.run(["git", *cmd], cwd=root, capture_output=True)
    return root


def _setup(tmp_path, monkeypatch, test_body: str):
    v4 = _repo(tmp_path / "v4", {"epre/m.py": "def f():\n    return 1\n",
                                 "tests/test_m.py": f"import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__)"
                                                    f".parent.parent / 'epre'))\nimport m\n\ndef test_f():\n{test_body}\n"})
    monkeypatch.setattr(patches, "ROOTS", {"team": tmp_path / "none", "V4": v4, "V3": tmp_path / "none"})
    monkeypatch.setattr(patches, "DIR", tmp_path / "patches")
    patches.DIR.mkdir()
    posts = []
    monkeypatch.setattr(patches, "post", lambda ch, text, who: posts.append(text))
    return v4, posts


def _write(pid: str, edits: list[dict]):
    (patches.DIR / f"{pid}.json").write_text(json.dumps({"title": pid, "why": "test", "edits": edits}))


def test_check_proves_on_a_scratch_copy_and_apply_commits(tmp_path, monkeypatch):
    v4, posts = _setup(tmp_path, monkeypatch, "    assert m.f() == 2")       # the live code fails this test
    _write("fix", [{"file": "V4/epre/m.py", "old": "return 1", "new": "return 2"}])
    assert patches.check("fix")["status"] == "ready"
    assert (v4 / "epre/m.py").read_text() == "def f():\n    return 1\n"      # check never touches the live file
    assert len(posts) == 1 and "patches.py apply fix" in posts[0]
    patches.check("fix")
    assert len(posts) == 1                                                    # posted once, not every dispatch
    assert patches.apply("fix") == 0
    assert "return 2" in (v4 / "epre/m.py").read_text()
    log = subprocess.run(["git", "log", "--oneline"], cwd=v4, capture_output=True, text=True).stdout
    assert "Engineer patch fix" in log
    assert patches.pending() == []


def test_failing_patch_is_not_ready_and_apply_refuses(tmp_path, monkeypatch):
    v4, posts = _setup(tmp_path, monkeypatch, "    assert m.f() == 1")
    _write("bad", [{"file": "V4/epre/m.py", "old": "return 1", "new": "return 3"}])
    assert patches.check("bad")["status"] == "tests_failed" and not posts
    assert patches.apply("bad") == 1 and "return 1" in (v4 / "epre/m.py").read_text()


def test_machinery_patch_applies_itself_after_24h_scoring_patch_never(tmp_path, monkeypatch):
    """User 2026-11-24: machinery-only patches apply themselves 24 h after they are ready (no reject); anything that
    scores a test (V4, quotes, ...) or adds a new kind of reach (network, processes) still waits for the user."""
    from datetime import datetime, timedelta
    v4, posts = _setup(tmp_path, monkeypatch, "    assert m.f() in (1, 2)")
    team = _repo(tmp_path / "team", {"tools/scan_ops.py": "def g():\n    return 1\n",
                                     "tests/test_g.py": "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path("
                                                        "__file__).parent.parent / 'tools'))\nimport scan_ops\n\n"
                                                        "def test_g():\n    assert scan_ops.g() in (1, 2)\n"})
    monkeypatch.setattr(patches, "ROOTS", {"team": team, "V4": v4, "V3": tmp_path / "none"})
    monkeypatch.setattr(patches, "ENG_LOG", tmp_path / "engineer_log.csv")
    _write("mach", [{"file": "team/tools/scan_ops.py", "old": "return 1", "new": "return 2"}])
    _write("score", [{"file": "V4/epre/m.py", "old": "return 1", "new": "return 2"}])
    _write("net", [{"file": "team/tools/scan_ops.py", "old": "return 1", "new": "import urllib  # x\n    return 2"}])
    for pid in ("mach", "score", "net"):
        assert patches.check(pid)["status"] == "ready", pid
    assert "applies ITSELF in 24 h" in posts[0] and "Waits for your yes" in posts[1] and "urllib" in posts[2]
    ready_at = datetime.strptime(json.loads((patches.DIR / "mach.json").read_text())["_status"]["ready_since"],
                                 "%Y-%m-%d %H:%M")
    assert patches.auto_apply_due(ready_at + timedelta(hours=23)) == []           # not yet
    assert patches.auto_apply_due(ready_at + timedelta(hours=25)) == ["mach: auto applied"]
    assert "return 2" in (team / "tools/scan_ops.py").read_text()
    assert "return 1" in (v4 / "epre/m.py").read_text()                          # scoring code: user only
    log = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=team, capture_output=True, text=True).stdout
    assert log.startswith("team-runner: auto-applied Engineer patch mach")       # not counted as a user step-in
    assert ",applied,team/tools/scan_ops.py," in (tmp_path / "engineer_log.csv").read_text()
    assert patches.auto_apply_due(ready_at + timedelta(hours=48)) == []          # "net" moved: live file changed


def test_old_text_must_match_exactly_once_and_live_drift_blocks_apply(tmp_path, monkeypatch):
    v4, _ = _setup(tmp_path, monkeypatch, "    assert m.f() in (1, 2)")
    _write("typo", [{"file": "V4/epre/m.py", "old": "return  1", "new": "return 2"}])
    assert "found 0 times" in patches.check("typo")["problems"][0]
    _write("ok", [{"file": "V4/epre/m.py", "old": "return 1", "new": "return 2"}])
    assert patches.check("ok")["status"] == "ready"
    (v4 / "epre/m.py").write_text("def f():\n    return 1  # someone edited it\n")
    assert patches.apply("ok") == 1                                           # moved since the check -> re-check
