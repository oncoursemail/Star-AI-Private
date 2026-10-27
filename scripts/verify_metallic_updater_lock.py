"""Exercise staging ownership in temporary directories without running an update or signing."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from launcher.updates.client import UpdateBusy, UpdateError, Updater  # noqa: E402
from launcher.updates.keys import TrustStore  # noqa: E402


class NoSource:
    def read(self, *_args):
        raise AssertionError("No network, manifest or blob reads are permitted")

    def stream(self, *_args):
        raise AssertionError("No downloads are permitted")


def client(home: Path) -> Updater:
    return Updater(home, NoSource(), TrustStore([]))


def staged(home: Path) -> Path:
    path = home / "staging" / "temporary-owner" / "payload.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("synthetic staged bytes", encoding="utf-8")
    return path


class UpdaterLockChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="metallic-lock-check-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)

    def test_unlocked_constructor_cleans_orphan_and_preserves_backup_recovery(self):
        payload = staged(self.home)
        state = {"schema": 1, "components": {}, "last_sequence": {"stable": 7}}
        (self.home / "state.json").write_text("malformed temporary state", encoding="utf-8")
        backup = self.home / "state.json.bak"
        backup.write_text(json.dumps(state), encoding="utf-8")
        previous = backup.read_bytes()
        up = client(self.home)
        self.assertFalse(payload.exists())
        self.assertFalse((self.home / ".lock").exists())
        self.assertEqual(up.status()["last_sequence"], {"stable": 7})
        self.assertEqual(backup.read_bytes(), previous)

    def test_fresh_and_old_existing_locks_preserve_active_stage_and_status(self):
        for age in (0, 7200):
            with self.subTest(age=age):
                payload = staged(self.home)
                lock = self.home / ".lock"
                lock.write_bytes(b"synthetic existing owner")
                stamp = time.time() - age
                os.utime(lock, (stamp, stamp))
                before = (lock.read_bytes(), lock.stat().st_mtime_ns)
                up = client(self.home)
                self.assertEqual(payload.read_text(encoding="utf-8"), "synthetic staged bytes")
                self.assertEqual(up.status()["components"], {})
                self.assertIsNone(up.installed_version("launcher"))
                self.assertEqual((lock.read_bytes(), lock.stat().st_mtime_ns), before)
                with self.assertRaises(UpdateBusy):
                    with up._locked():
                        self.fail("An existing lock was acquired")
                self.assertTrue(payload.exists())
                self.assertEqual((lock.read_bytes(), lock.stat().st_mtime_ns), before)
                lock.unlink()

    def test_second_instance_is_readable_while_first_holds_lock(self):
        first = client(self.home)
        results = []

        def other_client():
            try:
                second = client(self.home)
                results.append(second.status())
                with second._locked():
                    results.append("unexpected acquisition")
            except UpdateBusy:
                results.append("busy")
            except BaseException as exc:
                results.append(exc)

        with first._locked():
            payload = staged(self.home)
            thread = threading.Thread(target=other_client, daemon=True)
            thread.start()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive(), "Opening a busy status client blocked")
            self.assertEqual(results, [{"channel": "stable", "components": {}, "last_sequence": {}}, "busy"])
            self.assertTrue(payload.exists())
            self.assertTrue((self.home / ".lock").exists())
        self.assertFalse((self.home / ".lock").exists())
        self.assertTrue(payload.exists())
        client(self.home)
        self.assertFalse(payload.exists(), "A later exclusive constructor did not clean the orphan")

    def test_cleanup_runs_with_exclusive_lock_already_present(self):
        observed = []

        def cleanup(up):
            observed.append((up.root / ".lock").exists())
            with self.assertRaises(UpdateBusy):
                with up._locked():
                    self.fail("Cleanup did not have exclusive ownership")

        with patch.object(Updater, "_cleanup_staging", cleanup):
            client(self.home)
        self.assertEqual(observed, [True])
        self.assertFalse((self.home / ".lock").exists())

    def test_cleanup_failures_are_not_misreported_as_busy_and_release_lock(self):
        for failure in (RuntimeError("synthetic cleanup failure"), UpdateError("synthetic update failure")):
            with self.subTest(failure=type(failure).__name__):
                payload = staged(self.home)
                with patch.object(Updater, "_cleanup_staging", side_effect=failure):
                    with self.assertRaises(type(failure)) as caught:
                        client(self.home)
                self.assertIs(caught.exception, failure)
                self.assertTrue(payload.exists())
                self.assertFalse((self.home / ".lock").exists())

    def test_lock_body_exception_releases_only_owned_lock(self):
        up = client(self.home)
        with self.assertRaisesRegex(RuntimeError, "synthetic body failure"):
            with up._locked():
                staged(self.home)
                raise RuntimeError("synthetic body failure")
        self.assertFalse((self.home / ".lock").exists())
        with up._locked():
            self.assertTrue((self.home / ".lock").exists())

    def test_lock_acquisition_oserror_is_not_suppressed_by_constructor(self):
        with patch("launcher.updates.client.os.open", side_effect=PermissionError("synthetic denial")):
            with self.assertRaises(PermissionError):
                client(self.home)
        self.assertFalse((self.home / ".lock").exists())

    def test_busy_error_preserves_existing_update_error_contract(self):
        self.assertTrue(issubclass(UpdateBusy, UpdateError))
        (self.home / ".lock").write_bytes(b"existing owner")
        up = client(self.home)
        with self.assertRaisesRegex(UpdateError, "already running"):
            with up._locked():
                self.fail("Busy updater admitted a second owner")


if __name__ == "__main__":
    unittest.main(verbosity=2)
