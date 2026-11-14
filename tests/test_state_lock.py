"""common.state_lock / save_json and scan_ops' locked tick (2026-11-13: overlapping ticks could drop each other's state)."""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import pytest

import common
import scan_ops


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "STATE", tmp_path)
    return tmp_path


def test_lock_is_exclusive_and_released(state):
    with common.state_lock("x"):
        assert (state / "x.lock").exists()
        with pytest.raises(common.LockBusy):
            with common.state_lock("x", wait_s=0):
                pass
    assert not (state / "x.lock").exists()
    with common.state_lock("x", wait_s=0):      # free again
        pass


def test_lock_released_on_error(state):
    with pytest.raises(ValueError):
        with common.state_lock("x"):
            raise ValueError
    assert not (state / "x.lock").exists()


def test_stale_lock_from_crashed_run_is_taken_over(state):
    lock = state / "x.lock"
    lock.write_text("999 crashed")
    old = time.time() - 3600
    os.utime(lock, (old, old))
    with common.state_lock("x", wait_s=0, stale_s=900):
        assert "crashed" not in lock.read_text()


def test_save_json_leaves_no_temp_file(tmp_path):
    p = tmp_path / "s.json"
    common.save_json(p, {"a": 1})
    common.save_json(p, {"a": 2})
    assert json.loads(p.read_text()) == {"a": 2}
    assert [f.name for f in tmp_path.iterdir()] == ["s.json"]


def test_scan_ops_tick_skips_when_locked(state, monkeypatch):
    called = []
    monkeypatch.setattr(scan_ops, "_run", lambda dry: called.append(dry) or ["x"])
    monkeypatch.setattr(scan_ops, "state_lock", lambda name: common.state_lock(name, wait_s=0))
    with common.state_lock("scan_ops"):
        assert scan_ops.run() == []              # busy -> skip, no overwrite
    assert called == []
    assert scan_ops.run() == ["x"]


def test_corrupt_state_is_kept_aside_not_silently_reset(tmp_path, monkeypatch):
    f = tmp_path / "scan_ops.json"
    f.write_text('{"issues": [')                 # truncated write
    monkeypatch.setattr(scan_ops, "STATEF", f)
    assert scan_ops._load_state() == {}
    assert not f.exists()
    assert len(list(tmp_path.glob("scan_ops.corrupt-*.json"))) == 1
