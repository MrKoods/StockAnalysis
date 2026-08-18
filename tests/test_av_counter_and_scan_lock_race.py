"""
Tests for the two lost-update race conditions fixed together: news_client.py's
increment_av_call_count() (read-modify-write with no lock, even though
scan_lock.py deliberately allows different scan_types to run concurrently and
all of them hit this same counter) and scan_lock.py's own acquire_scan_lock()
(check-then-write instead of an atomic exclusive-create, so two near-
simultaneous launches could both "win" the lock).

Both are proven under real thread concurrency, not just inspected — a race
condition that "looks fixed" by reading the code isn't actually verified
without exercising it under contention.
"""

import threading

from shared.utils.atomic_io import exclusive_lock
from shared.utils.scan_lock import acquire_scan_lock


class TestExclusiveLockPreventsLostUpdates:
    def test_concurrent_increments_are_not_lost(self, tmp_path):
        counter_file = tmp_path / "counter.json"
        counter_file.write_text("0")
        lock_file = tmp_path / "counter.json.lock"

        def bump():
            with exclusive_lock(lock_file, timeout=5.0):
                current = int(counter_file.read_text())
                # Deliberately widen the read-modify-write window so an
                # unlocked version of this test would reliably lose updates.
                import time
                time.sleep(0.001)
                counter_file.write_text(str(current + 1))

        threads = [threading.Thread(target=bump) for _ in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert int(counter_file.read_text()) == 30

    def test_lock_file_is_cleaned_up_after_use(self, tmp_path):
        lock_file = tmp_path / "x.lock"
        with exclusive_lock(lock_file):
            assert lock_file.exists()
        assert not lock_file.exists()

    def test_stale_lock_is_reclaimed_not_deadlocked(self, tmp_path, monkeypatch):
        lock_file = tmp_path / "x.lock"
        lock_file.write_text("abandoned")
        # Backdate the file's mtime so it reads as older than the timeout.
        import os
        old_time = os.path.getmtime(lock_file) - 100
        os.utime(lock_file, (old_time, old_time))

        with exclusive_lock(lock_file, timeout=1.0, poll_interval=0.01):
            pass  # must not raise/hang — the stale lock gets reclaimed


class TestAvCallCounterIncrementUnderConcurrency:
    def test_concurrent_increments_are_not_lost(self, tmp_path, monkeypatch):
        import shared.api_clients.news_client as nc

        counter_path = tmp_path / "av_call_count.json"
        lock_path = tmp_path / "av_call_count.json.lock"
        monkeypatch.setattr(nc, "_AV_COUNTER_FILE", counter_path)
        monkeypatch.setattr(nc, "_AV_COUNTER_LOCK_FILE", lock_path)

        def bump():
            nc.increment_av_call_count()

        threads = [threading.Thread(target=bump) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert nc.get_av_call_count()["count"] == 20


class TestScanLockNoDoubleAcquire:
    def test_never_two_holders_inside_the_critical_section_at_once(self, tmp_path):
        """
        Real mutual-exclusion proof, not just "the API returns something
        reasonable": every thread races to acquire the SAME lock, and each
        holder sleeps briefly while inside — if the old check-then-write
        TOCTOU bug were still present, two threads launched close enough
        together could both observe "no live lock" and both end up inside
        the critical section simultaneously, which max_concurrent_holders
        would catch as > 1.
        """
        import time

        concurrent_holders = 0
        max_concurrent_holders = 0
        state_lock = threading.Lock()
        start_barrier = threading.Barrier(20)

        def attempt():
            nonlocal concurrent_holders, max_concurrent_holders
            start_barrier.wait()  # maximize the race window at lock-acquire time
            with acquire_scan_lock("post_close", lock_dir=tmp_path) as acquired:
                if not acquired:
                    return
                with state_lock:
                    concurrent_holders += 1
                    max_concurrent_holders = max(max_concurrent_holders, concurrent_holders)
                time.sleep(0.02)
                with state_lock:
                    concurrent_holders -= 1

        threads = [threading.Thread(target=attempt) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert max_concurrent_holders == 1
