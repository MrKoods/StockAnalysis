import subprocess

import pytest

from daytrade import data

BLOCKED = "ImportError: DLL load failed while importing _parquet: An Application Control policy has blocked this file."


def _fake_runs(monkeypatch, stderrs):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", stderrs[len(calls) - 1])

    monkeypatch.setattr(subprocess, "run", run)
    return calls


def test_wait_for_parquet_real_import_succeeds():
    data.wait_for_parquet(tries=1, wait=0)


def test_wait_for_parquet_recovers_after_block(monkeypatch):
    calls = _fake_runs(monkeypatch, [BLOCKED, BLOCKED, ""])
    data.wait_for_parquet(tries=5, wait=0)
    assert len(calls) == 3


def test_wait_for_parquet_gives_up_without_touching_archive(monkeypatch):
    calls = _fake_runs(monkeypatch, [BLOCKED] * 3)
    with pytest.raises(SystemExit):
        data.wait_for_parquet(tries=3, wait=0)
    assert len(calls) == 3


def test_cli_exits_nonzero_when_blocked(monkeypatch):
    """The scheduled task must see a failure (so alerts fire) and must not run fetch."""
    import sys

    from daytrade import __main__ as cli

    _fake_runs(monkeypatch, [BLOCKED] * 5)
    monkeypatch.setattr(data, "fetch", lambda: pytest.fail("fetch ran while parquet was blocked"))
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(sys, "argv", ["daytrade", "fetch"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code not in (0, None)
