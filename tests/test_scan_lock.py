"""
Tests for shared/utils/scan_lock.py — the mutex preventing the same scan_type
from running twice concurrently, built after tracing 2026-08-04's retail-
sector dropout to an externally-triggered post-close restart every ~5 minutes.
"""

import json
import os
from datetime import datetime, timedelta, timezone

from shared.utils.scan_lock import acquire_scan_lock, _MAX_LOCK_AGE_SECONDS


class TestAcquireScanLock:
    def test_first_acquire_succeeds(self, tmp_path):
        with acquire_scan_lock("post_close", lock_dir=tmp_path) as acquired:
            assert acquired is True
            assert (tmp_path / "post_close.lock").exists()

    def test_lock_file_removed_after_successful_run(self, tmp_path):
        with acquire_scan_lock("post_close", lock_dir=tmp_path):
            pass
        assert not (tmp_path / "post_close.lock").exists()

    def test_lock_file_contains_pid_and_timestamp(self, tmp_path):
        with acquire_scan_lock("post_close", lock_dir=tmp_path):
            data = json.loads((tmp_path / "post_close.lock").read_text(encoding="utf-8"))
            assert data["pid"] == os.getpid()
            assert "started_at_utc" in data

    def test_second_acquire_while_first_still_running_is_rejected(self, tmp_path):
        with acquire_scan_lock("post_close", lock_dir=tmp_path) as first:
            assert first is True
            with acquire_scan_lock("post_close", lock_dir=tmp_path) as second:
                assert second is False

    def test_different_scan_types_do_not_block_each_other(self, tmp_path):
        with acquire_scan_lock("post_close", lock_dir=tmp_path) as a:
            with acquire_scan_lock("pre_market", lock_dir=tmp_path) as b:
                assert a is True
                assert b is True

    def test_stale_lock_by_age_is_reclaimed(self, tmp_path):
        lock_path = tmp_path / "post_close.lock"
        old_time = datetime.now(timezone.utc) - timedelta(seconds=_MAX_LOCK_AGE_SECONDS + 60)
        lock_path.write_text(
            json.dumps({"pid": os.getpid(), "started_at_utc": old_time.isoformat()}),
            encoding="utf-8",
        )
        with acquire_scan_lock("post_close", lock_dir=tmp_path) as acquired:
            assert acquired is True

    def test_lock_held_by_dead_pid_is_reclaimed(self, tmp_path):
        lock_path = tmp_path / "post_close.lock"
        # A PID essentially guaranteed not to correspond to a live process.
        lock_path.write_text(
            json.dumps({"pid": 999999999, "started_at_utc": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8",
        )
        with acquire_scan_lock("post_close", lock_dir=tmp_path) as acquired:
            assert acquired is True

    def test_corrupt_lock_file_treated_as_stale(self, tmp_path):
        lock_path = tmp_path / "post_close.lock"
        lock_path.write_text("not valid json{{{", encoding="utf-8")
        with acquire_scan_lock("post_close", lock_dir=tmp_path) as acquired:
            assert acquired is True

    def test_lock_dir_created_if_missing(self, tmp_path):
        nested = tmp_path / "nested" / "dir"
        with acquire_scan_lock("post_close", lock_dir=nested) as acquired:
            assert acquired is True
            assert (nested / "post_close.lock").exists()

    def test_recently_held_alive_pid_lock_is_not_reclaimed(self, tmp_path):
        lock_path = tmp_path / "post_close.lock"
        lock_path.write_text(
            json.dumps({"pid": os.getpid(), "started_at_utc": datetime.now(timezone.utc).isoformat()}),
            encoding="utf-8",
        )
        with acquire_scan_lock("post_close", lock_dir=tmp_path) as acquired:
            assert acquired is False
        # Rejection must not delete a lock this call didn't acquire.
        assert lock_path.exists()

    def test_exception_inside_with_block_still_releases_lock(self, tmp_path):
        lock_path = tmp_path / "post_close.lock"
        try:
            with acquire_scan_lock("post_close", lock_dir=tmp_path):
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        assert not lock_path.exists()
