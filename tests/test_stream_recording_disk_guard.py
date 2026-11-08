"""Deterministic fault injection for recording headroom; never records media."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from star.stream_recording_disk_guard import RecordingDiskGuard


_MIB = 1024 * 1024


class RecordingDiskGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name).resolve())
        self.free_mib = 20_000
        self.calls = 0

    def reader(self, path: str) -> object:
        self.assertEqual(path, self.path)
        self.calls += 1
        return SimpleNamespace(total=100_000 * _MIB, free=self.free_mib * _MIB)

    def guard(self, **kwargs) -> RecordingDiskGuard:
        return RecordingDiskGuard(self.path, disk_reader=self.reader, **kwargs)

    def test_never_reads_before_owner_approval(self) -> None:
        guard = self.guard()
        self.assertEqual(self.calls, 0)
        with self.assertRaises(PermissionError):
            guard.check()
        self.assertEqual(self.calls, 0)
        self.assertFalse(guard.metrics()["recording_authorized"])
        self.assertFalse(guard.metrics()["broadcast_authorized"])

    def test_recording_estimate_includes_os_reserve(self) -> None:
        guard = self.guard()
        advice = guard.check(owner_approved=True)
        # 8 GiB OS reserve + 30 min @ 12 Mbps (video+audio combined).
        self.assertGreaterEqual(advice.required_mib, 8192 + 2500)
        self.assertLess(advice.required_mib, 8192 + 2700)
        self.assertEqual(advice.free_mib, 20_000)
        self.assertEqual(advice.status, "candidate")
        self.assertFalse(advice.stop_recording_requested)
        self.assertFalse(advice.recording_authorized)
        self.assertFalse(advice.broadcast_authorized)

    def test_main_disk_like_low_space_defers_nonbroadcast_recording(self) -> None:
        self.free_mib = 1650
        guard = self.guard()
        advice = guard.check(owner_approved=True)
        self.assertEqual(advice.status, "deferred")
        self.assertEqual(advice.reason, "insufficient_recording_disk_headroom")
        self.assertTrue(guard.metrics()["revoked"])
        self.assertFalse(advice.recording_authorized)
        # Freeing disk does not resume an already revoked episode.
        self.free_mib = 40_000
        self.assertEqual(guard.check(owner_approved=True).reason, "recording_storage_revoked")
        self.assertEqual(self.calls, 1)

    def test_drop_during_recording_asks_trusted_host_to_stop(self) -> None:
        guard = self.guard()
        self.assertEqual(guard.check(owner_approved=True).status, "candidate")
        self.free_mib = 100
        stop = guard.check(owner_approved=True, remaining_seconds=5,
                           recording_active=True)
        self.assertTrue(stop.stop_recording_requested)
        self.assertEqual(stop.status, "deferred")
        self.assertFalse(stop.recording_authorized)
        self.assertTrue(guard.check(owner_approved=True,
                                    recording_active=True).stop_recording_requested)

    def test_read_failure_is_sanitized_and_revokes(self) -> None:
        guard = RecordingDiskGuard(self.path, disk_reader=lambda _: (_ for _ in ()).throw(
            OSError("secret recordings in personal path")
        ))
        advice = guard.check(owner_approved=True, recording_active=True)
        self.assertEqual(advice.status, "unavailable")
        self.assertEqual(advice.reason, "recording_disk_probe_unavailable")
        self.assertTrue(advice.stop_recording_requested)
        self.assertNotIn("personal", repr(advice))
        self.assertNotIn(self.path, repr(advice))

    def test_missing_or_symlink_output_never_promoted(self) -> None:
        missing = RecordingDiskGuard(str(Path(self.path) / "not_existing"),
                                     disk_reader=self.reader)
        self.assertEqual(missing.check(owner_approved=True).status, "unavailable")
        self.assertEqual(self.calls, 0)
        alias = Path(self.path) / "shortcut"
        alias.symlink_to(self.path, target_is_directory=True)
        guard = RecordingDiskGuard(str(alias), disk_reader=self.reader)
        self.assertEqual(guard.check(owner_approved=True).status, "unavailable")
        self.assertEqual(self.calls, 0)

    def test_invalid_free_space_measurements_are_rejected(self) -> None:
        for total, free in ((12, 13), (12, -1), (True, 1), (12, 1.5),
                            (1 << 64, 1), (None, 1)):
            with self.subTest(total=total, free=free):
                guard = RecordingDiskGuard(self.path, disk_reader=lambda _:
                    SimpleNamespace(total=total, free=free))
                self.assertEqual(guard.check(owner_approved=True).status, "unavailable")

    def test_invalid_budget_horizon_and_permissions(self) -> None:
        for kwargs in ({"reserve_mib": 0}, {"bitrate_mbps": True},
                       {"maximum_seconds": 10}, {"maximum_seconds": 20_000}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.guard(**kwargs)
        for kwargs in ({"remaining_seconds": -1},
                       {"remaining_seconds": 1801}, {"remaining_seconds": 1.5},
                       {"recording_active": 1}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.guard().check(owner_approved=True, **kwargs)

    def test_relative_and_network_paths_rejected_before_disk_io(self) -> None:
        for path in ("not/absolute", "//server/share", "", "a" * 1500):
            with self.subTest(path=path[:16]), self.assertRaises(ValueError):
                RecordingDiskGuard(path, disk_reader=self.reader)
        self.assertEqual(self.calls, 0)

    def test_estimate_decreases_only_with_host_remaining_horizon(self) -> None:
        guard = self.guard()
        long = guard.check(owner_approved=True, remaining_seconds=1800)
        short = guard.check(owner_approved=True, remaining_seconds=0)
        self.assertGreater(long.required_mib, short.required_mib)
        self.assertEqual(short.required_mib, 8192)


if __name__ == "__main__":
    unittest.main()
