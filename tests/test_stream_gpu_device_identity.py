"""Regression tests: a GPU index and identical counters do not prove device identity."""
from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from star.stream_windows_rehearsal_preflight import GpuHeadroom, ProcessWitness, query_nvidia_gpu
from star.stream_windows_resource_window import _WindowSample, evaluate_resource_window, probe_windows_resource_window

GPU_A = "GPU-11111111-2222-3333-4444-555555555555"
GPU_B = "GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def actors() -> tuple[ProcessWitness, ...]:
    return (
        ProcessWitness("obs64.exe", 10, 100.0),
        ProcessWitness("VTube Studio.exe", 11, 101.0),
        ProcessWitness("llama-server.exe", 12, 102.0),
        ProcessWitness("MyGame.exe", 13, 103.0),
    )


def window(uuids: list[str | None]):
    return [
        _WindowSample(i * 0.5, actors(), GpuHeadroom(8192, 3500, 20, device_uuid=uuid))
        for i, uuid in enumerate(uuids)
    ]


class TestGpuDeviceIdentity(unittest.TestCase):
    def test_gpu_swap_identical_capacity_and_metrics_must_defer(self):
        report = evaluate_resource_window(
            window([GPU_A, GPU_A, GPU_B, GPU_B, GPU_B]),
            pinned_game_identity=(13, 103.0),
        )
        self.assertEqual(report.status, "deferred")
        self.assertIn("gpu_device_identity_changed_during_window", report.reasons)
        self.assertNotIn(GPU_A, repr(report))
        self.assertNotIn(GPU_B, repr(report))

    def test_missing_uuid_must_defer_even_with_identical_good_counters(self):
        report = evaluate_resource_window(
            window([GPU_A, GPU_A, None, GPU_A, GPU_A]),
            pinned_game_identity=(13, 103.0),
        )
        self.assertEqual(report.status, "deferred")
        self.assertIn("gpu_device_identity_missing", report.reasons)

    def test_expected_uuid_from_host_pinning_is_enforced(self):
        report = evaluate_resource_window(
            window([GPU_A] * 5),
            pinned_game_identity=(13, 103.0),
            expected_gpu_uuid=GPU_B,
        )
        self.assertEqual(report.status, "deferred")
        self.assertIn("gpu_device_identity_mismatch", report.reasons)
        self.assertNotIn(GPU_B, repr(report))

    def test_normalized_upper_and_lowercase_uuid_are_same_device(self):
        result = evaluate_resource_window(
            window([GPU_B, GPU_B.upper(), GPU_B, GPU_B, GPU_B]),
            pinned_game_identity=(13, 103.0),
            expected_gpu_uuid=GPU_B,
        )
        self.assertEqual(result.status, "candidate")
        self.assertTrue(result.host_processes_stable)

    def test_nvidia_smi_query_carries_uuid_without_shell_execution(self):
        fake = subprocess.CompletedProcess(
            [], 0, stdout=f"{GPU_A}, 8192, 3550, 17\n", stderr=""
        )
        with patch("star.stream_windows_rehearsal_preflight.subprocess.run", return_value=fake) as run:
            gpu = query_nvidia_gpu(0)
        self.assertEqual(gpu.device_uuid, GPU_A.casefold())
        self.assertIn("uuid,memory.total,memory.free,utilization.gpu", " ".join(run.call_args.args[0]))
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_reject_invalid_or_unbounded_uuid_evidence(self):
        for value in ("not-a-gpu", "", GPU_A + "garbage", "MIG-foo", True, 42):
            with self.subTest(value=value), self.assertRaises(ValueError):
                GpuHeadroom(8192, 3500, 20, device_uuid=value)

    def test_probe_rejects_bad_expected_identity_before_any_read(self):
        with self.assertRaises(ValueError):
            probe_windows_resource_window(
                owner_approved=True, pinned_game_identity=(13, 103.0),
                expected_gpu_uuid="invalid",
                system_name=lambda: self.fail("no platform read"),
            )


if __name__ == "__main__":
    unittest.main()
