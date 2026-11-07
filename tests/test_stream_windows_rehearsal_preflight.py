"""Offline regression tests: no Windows devices, OBS, games or mic accessed."""
from __future__ import annotations

import subprocess
import sys
import types
import unittest
from unittest.mock import patch

from star.stream_windows_rehearsal_preflight import (
    GpuHeadroom, ProcessWitness, enumerate_windows_processes,
    evaluate_preflight, probe_windows_rehearsal, query_nvidia_gpu,
)


def witnesses() -> tuple[ProcessWitness, ...]:
    return (
        ProcessWitness("obs64.exe", 10, 100.0),
        ProcessWitness("VTube Studio.exe", 11, 101.0),
        ProcessWitness("llama-server.exe", 12, 102.0),
        ProcessWitness("SomeGame.exe", 13, 103.0),
    )


def probe(*, processes=None, gpu=None, identity=(13, 103.0)):
    return probe_windows_rehearsal(
        owner_approved=True, pinned_game_identity=identity,
        system_name=lambda: "Windows",
        process_reader=lambda: witnesses() if processes is None else processes,
        gpu_reader=lambda _: GpuHeadroom(8192, 2800, 60) if gpu is None else gpu,
    )


class TestWindowsRehearsalPreflight(unittest.TestCase):
    def test_candidate_is_not_permission(self):
        result = probe()
        self.assertEqual(result.status, "candidate")
        self.assertEqual(result.reasons, ())
        self.assertTrue(result.candidate_for_nonbroadcast_rehearsal)
        self.assertFalse(result.authorized_to_play)
        self.assertFalse(result.authorized_to_broadcast)
        report = repr(result)
        for value in ("SomeGame.exe", "obs64.exe", "103.0", "llama-server.exe"):
            self.assertNotIn(value, report)

    def test_infrastructure_pid_cannot_double_as_game(self):
        # Regression: the old evaluator declared a rehearsal game-ready when
        # the supposedly pinned game was the ONLY llama-server process.
        for role, pid, created in (("OBS", 10, 100.0),
                                   ("avatar", 11, 101.0),
                                   ("model", 12, 102.0)):
            with self.subTest(role=role):
                report = probe(processes=witnesses()[:3], identity=(pid, created))
                self.assertEqual(report.status, "deferred")
                self.assertTrue(report.pinned_game_seen)
                self.assertIn("pinned_game_is_infrastructure_process", report.reasons)
                self.assertFalse(report.authorized_to_play)
                self.assertFalse(report.authorized_to_broadcast)

    def test_process_aliases_remain_consistent_for_game_collision(self):
        for old, new in (("obs64.exe", "obs.exe"),
                         ("VTube Studio.exe", "VTubeStudio.exe"),
                         ("llama-server.exe", "llama-server")):
            rows = tuple(ProcessWitness(new, p.pid, p.created_unix_s)
                         if p.name == old else p for p in witnesses()[:3])
            collision_pid = next(p for p in rows if p.name == new).pid
            collision_created = next(p for p in rows if p.name == new).created_unix_s
            with self.subTest(alias=new):
                report = probe(processes=rows, identity=(collision_pid, collision_created))
                self.assertEqual(report.status, "deferred")
                self.assertIn("pinned_game_is_infrastructure_process", report.reasons)

    def test_approval_required_before_probes(self):
        with self.assertRaises(PermissionError):
            probe_windows_rehearsal(
                pinned_game_identity=(13, 103.0),
                process_reader=lambda: self.fail("should not read processes"),
            )

    def test_linux_fails_closed_without_reading_probes(self):
        result = probe_windows_rehearsal(
            owner_approved=True, pinned_game_identity=None,
            system_name=lambda: "Linux",
            process_reader=lambda: self.fail("should not read Linux processes"),
        )
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.reasons, ("windows_host_required",))

    def test_no_game_pin_no_game_identity(self):
        result = probe(identity=None)
        self.assertEqual(result.status, "deferred")
        self.assertIn("pinned_game_process_missing_or_restarted", result.reasons)

    def test_recycled_process_pid_rejected(self):
        result = probe(identity=(13, 90.0))
        self.assertFalse(result.pinned_game_seen)
        self.assertEqual(result.status, "deferred")

    def test_unrelated_process_does_not_qualify_avatar(self):
        other = tuple(p for p in witnesses() if p.pid != 11) + (
            ProcessWitness("VTube Studio helper.exe", 50, 500.0),
        )
        result = probe(processes=other)
        self.assertFalse(result.avatar_process_seen)

    def test_ambiguous_duplicate_app_instances_defer(self):
        result = probe(processes=witnesses() + (
            ProcessWitness("obs.exe", 50, 500.0),
            ProcessWitness("llama-server", 51, 501.0),
        ))
        self.assertFalse(result.obs_process_seen)
        self.assertFalse(result.model_process_seen)

    def test_low_vram_and_utilization_defer(self):
        result = probe(gpu=GpuHeadroom(8192, 400, 98))
        self.assertIn("gpu_utilization_high", result.reasons)
        self.assertIn("insufficient_free_gpu_memory", result.reasons)
        self.assertEqual(result.gpu_free_mib, 400)

    def test_process_snapshot_unavailable_is_sanitized(self):
        def broken():
            raise RuntimeError("SECRET_TOKEN=impossible")
        result = probe_windows_rehearsal(
            owner_approved=True, pinned_game_identity=(13, 103.0),
            system_name=lambda: "Windows", process_reader=broken,
        )
        self.assertEqual(result.reasons, ("local_process_snapshot_unavailable",))
        self.assertNotIn("SECRET_TOKEN", repr(result))

    def test_malformed_process_snapshot_is_sanitized(self):
        result = probe(processes=witnesses() + (
            ProcessWitness("duplicate.exe", 13, 103.0),
        ))
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.reasons, ("local_process_snapshot_invalid",))

    def test_gpu_reader_failure_fails_closed(self):
        result = probe_windows_rehearsal(
            owner_approved=True, pinned_game_identity=(13, 103.0),
            system_name=lambda: "Windows", process_reader=witnesses,
            gpu_reader=lambda _: (_ for _ in ()).throw(RuntimeError("API token 123")),
        )
        self.assertEqual(result.reasons, ("gpu_sample_missing",))
        self.assertIsNone(result.gpu_total_mib)
        self.assertNotIn("token", repr(result))

    def test_invalid_gpu_and_input_are_rejected(self):
        for gpu in (GpuHeadroom(8192, 0, 0),):
            self.assertEqual(probe(gpu=gpu).status, "deferred")
        with self.assertRaises(ValueError):
            GpuHeadroom(8192, 9000, 10)
        with self.assertRaises(ValueError):
            GpuHeadroom(8192, 0, True)
        for identity in ((0, 1.0), (13, float("nan")), (13, 0), (13, True)):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                evaluate_preflight(witnesses(), None, pinned_game_identity=identity)
        with self.assertRaises(ValueError):
            probe_windows_rehearsal(owner_approved=True, pinned_game_identity=None,
                                    gpu_index=True)

    def test_unbounded_and_bad_thresholds_rejected(self):
        with self.assertRaises(ValueError):
            evaluate_preflight(
                [ProcessWitness("p", i + 1, 1.0) for i in range(32769)],
                None, pinned_game_identity=None,
            )
        with self.assertRaises(ValueError):
            evaluate_preflight(witnesses(), None, pinned_game_identity=None, gpu_reserve_mib=0)

    def test_gpu_query_is_bounded_and_read_only(self):
        good = subprocess.CompletedProcess([], 0, stdout="GPU-11111111-2222-3333-4444-555555555555, 8192, 5000, 13\n", stderr="")
        with patch("star.stream_windows_rehearsal_preflight.subprocess.run", return_value=good) as call:
            gpu = query_nvidia_gpu(0)
        self.assertEqual((gpu.total_mib, gpu.free_mib, gpu.utilization_pct),
                         (8192, 5000, 13))
        args, kwargs = call.call_args
        self.assertEqual(args[0][0], "nvidia-smi")
        self.assertIn("--query-gpu=uuid,memory.total,memory.free,utilization.gpu", args[0])
        self.assertFalse(kwargs["check"])
        self.assertLessEqual(kwargs["timeout"], 3)
        self.assertNotIn("shell", kwargs)
        for value in ("", "8192,3000\n", "8192,3000,200\n", "8192,3000,20\n1,1,1\n"):
            with self.subTest(value=value), patch(
                "star.stream_windows_rehearsal_preflight.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, stdout=value, stderr=""),
            ), self.assertRaises((ValueError, RuntimeError)):
                query_nvidia_gpu()

    def test_windows_special_system_processes_are_filtered(self):
        # Reproduced on Main: PID 0, missing create_time and empty names
        # are normal Windows OS metadata, not a corrupt host snapshot.
        data = [
            {"name": "Idle", "pid": 0, "create_time": 100.0},
            {"name": "System", "pid": 4, "create_time": 0.0},
            {"name": "", "pid": 5, "create_time": 90.0},
            {"name": "RealApp.exe", "pid": 13, "create_time": 103.0},
        ]
        fake = types.SimpleNamespace(
            process_iter=lambda attrs, ad_value: (
                types.SimpleNamespace(info=row) for row in data
            ),
        )
        with patch.dict(sys.modules, {"psutil": fake}):
            observed = tuple(enumerate_windows_processes())
        self.assertEqual(observed, (ProcessWitness("RealApp.exe", 13, 103.0),))

    def test_invalid_snapshot_raises_in_pure_evaluator(self):
        with self.assertRaises(ValueError):
            evaluate_preflight(
                witnesses() + (ProcessWitness("bad", 10, 200.0),),
                GpuHeadroom(8192, 4000, 10), pinned_game_identity=(13, 103.0),
            )


if __name__ == "__main__":
    unittest.main()
