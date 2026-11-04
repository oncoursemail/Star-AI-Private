"""Adversarial, offline tests for the passive Windows GPU diagnosis."""
from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import math
import unittest

from star.stream_gpu_budget_diagnostic import (
    GpuBudgetTick, assess_gpu_budget, main, probe_windows_gpu_budget,
)
from star.stream_windows_rehearsal_preflight import GpuHeadroom

UUID = "GPU-11111111-1111-1111-1111-111111111111"
OTHER = "GPU-22222222-2222-2222-2222-222222222222"


def readings(free: int = 3200, *, used_util: int = 25,
             device: str | None = UUID, total: int = 8192,
             count: int = 5, spacing: float = .5) -> list[GpuBudgetTick]:
    return [
        GpuBudgetTick(100 + i * spacing,
                      GpuHeadroom(total, free, used_util, device_uuid=device))
        for i in range(count)
    ]


class GpuBudgetTests(unittest.TestCase):
    def test_healthy_is_only_preflight_never_admission(self) -> None:
        result = assess_gpu_budget(readings())
        self.assertEqual(result.status, "preflight_only")
        self.assertEqual(result.unreserved_mib, 1664)
        self.assertEqual(result.samples, 5)
        self.assertEqual(result.observed_span_ms, 2000)
        self.assertFalse(result.may_launch_new_gpu_workers)
        self.assertFalse(result.authorizes_gameplay)
        self.assertFalse(result.authorizes_broadcast)
        self.assertFalse(result.verified_game_fps)

    def test_main_like_saturated_state(self) -> None:
        result = assess_gpu_budget(readings(64, used_util=99))
        self.assertEqual(result.status, "saturated")
        self.assertEqual(result.unreserved_mib, 0)
        self.assertEqual(result.proposed_placement, "do_not_start_new_gpu_work")

    def test_one_low_free_spike_cannot_be_averaged_away(self) -> None:
        ticks = readings(5000)
        ticks[2] = GpuBudgetTick(101, GpuHeadroom(8192, 150,
                                               81, device_uuid=UUID))
        result = assess_gpu_budget(ticks)
        self.assertEqual(result.status, "saturated")
        self.assertEqual(result.minimum_free_mib, 150)

    def test_compute_contention_without_vram_contention(self) -> None:
        ticks = readings(5500)
        ticks[-1] = GpuBudgetTick(102, GpuHeadroom(8192, 5500,
                                                 100, device_uuid=UUID))
        self.assertEqual(assess_gpu_budget(ticks).status, "constrained")

    def test_voice_placement_is_only_candidate(self) -> None:
        self.assertEqual(assess_gpu_budget(readings(1800)).status, "constrained")
        self.assertEqual(
            assess_gpu_budget(readings(1800)).proposed_placement,
            "prefer_cpu_voice_after_quality_benchmark",
        )

    def test_output_does_not_expose_gpu_identity(self) -> None:
        report = assess_gpu_budget(readings())
        dump = report.to_json()
        parsed = json.loads(dump)
        self.assertNotIn(UUID, dump)
        self.assertNotIn("device_uuid", dump)
        self.assertNotIn("process", dump)
        self.assertFalse(parsed["authorizes_broadcast"])

    def test_gpu_uuid_and_capacity_changes_invalidate_window(self) -> None:
        ticks = readings()
        ticks[2] = GpuBudgetTick(101, GpuHeadroom(
            8192, 3200, 12, device_uuid=OTHER))
        self.assertEqual(assess_gpu_budget(ticks).status, "unavailable")
        ticks[2] = GpuBudgetTick(101, GpuHeadroom(
            12288, 3200, 12, device_uuid=UUID))
        self.assertEqual(assess_gpu_budget(ticks).status, "unavailable")

    def test_gpu_uuid_is_required_throughout(self) -> None:
        self.assertEqual(
            assess_gpu_budget(readings(device=None)).status, "unavailable",
        )
        ticks = readings()
        ticks[-1] = GpuBudgetTick(102, GpuHeadroom(8192, 3500, 12))
        self.assertEqual(assess_gpu_budget(ticks).status, "unavailable")

    def test_replayed_overlapping_and_large_clock_gaps_are_not_healthy(self) -> None:
        for times in ([100, 100.5, 100.5, 101, 101.5],
                      [100, 100.5, 100.2, 101, 101.5],
                      [100, 100.5, 106, 106.5, 107]):
            ticks = readings()
            ticks = [GpuBudgetTick(t, x.gpu) for t, x in zip(times, ticks)]
            self.assertEqual(assess_gpu_budget(ticks).status, "unavailable")

    def test_window_must_cover_real_time(self) -> None:
        self.assertEqual(
            assess_gpu_budget(readings(count=3, spacing=.2)).status,
            "unavailable",
        )
        self.assertEqual(
            assess_gpu_budget(readings(count=3, spacing=.4)).status,
            "preflight_only",
        )

    def test_oversized_or_missing_samples_rejected(self) -> None:
        for n in (0, 1, 2, 10, 11):
            with self.assertRaises(ValueError):
                assess_gpu_budget(readings(count=n))
        with self.assertRaises(ValueError):
            assess_gpu_budget(iter(readings(count=11)))

    def test_invalid_schema_and_options_rejected(self) -> None:
        for reserve in (-2, True, 511, 20000, 1536.2):
            with self.assertRaises(ValueError):
                assess_gpu_budget(readings(), reserve_mib=reserve)
        for voice in (-1, True, 9000):
            with self.assertRaises(ValueError):
                assess_gpu_budget(readings(), optional_voice_mib=voice)
        with self.assertRaises(ValueError):
            assess_gpu_budget(readings(), max_util_pct=101)
        with self.assertRaises(ValueError):
            assess_gpu_budget(readings()[:2] + ["untrusted", *readings()[3:]])

    def test_invalid_time_is_never_accepted(self) -> None:
        for value in (True, math.nan, math.inf, -1, "100"):
            with self.assertRaises(ValueError):
                GpuBudgetTick(value, readings()[0].gpu)

    def test_opt_in_prevents_all_hardware_calls(self) -> None:
        called: list[int] = []
        with self.assertRaises(PermissionError):
            probe_windows_gpu_budget(
                gpu_reader=lambda i: (called.append(i), readings()[0].gpu)[1],
                system_name=lambda: "Windows",
            )
        self.assertFalse(called)

    def test_non_windows_returns_unavailable_without_touching_gpu(self) -> None:
        def fail(_: int) -> GpuHeadroom:
            raise AssertionError("GPU tool should not run")
        result = probe_windows_gpu_budget(
            owner_approved=True, system_name=lambda: "Linux",
            gpu_reader=fail,
        )
        self.assertEqual(result.status, "unavailable")

    def test_real_reader_invoked_for_all_samples_and_output_sanitized(self) -> None:
        calls: list[int] = []
        times = iter([200, 200.5, 201, 201.5, 202])
        result = probe_windows_gpu_budget(
            owner_approved=True, index=1,
            gpu_reader=lambda i: (calls.append(i), readings(2600)[0].gpu)[1],
            system_name=lambda: "Windows", clock=lambda: next(times),
            sleeper=lambda _: None,
        )
        self.assertEqual(calls, [1] * 5)
        self.assertEqual(result.status, "preflight_only")
        self.assertNotIn(UUID, result.to_json())

    def test_missed_middle_reader_sample_is_not_hidden(self) -> None:
        counter = 0
        def fail_third(_: int) -> GpuHeadroom:
            nonlocal counter
            counter += 1
            if counter == 3:
                raise RuntimeError("SECRET-PATH-AND-CREDENTIAL")
            return readings()[0].gpu
        result = probe_windows_gpu_budget(
            owner_approved=True, system_name=lambda: "Windows",
            gpu_reader=fail_third, clock=lambda: 100.0,
            sleeper=lambda _: None,
        )
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(counter, 3)
        self.assertNotIn("SECRET", result.to_json())

    def test_monotonic_clock_failure_is_not_partial_success(self) -> None:
        report = probe_windows_gpu_budget(
            owner_approved=True, system_name=lambda: "Windows",
            gpu_reader=lambda _: readings()[0].gpu,
            clock=lambda: math.nan, sleeper=lambda _: None,
        )
        self.assertEqual(report.status, "unavailable")

    def test_cli_no_observe_flag_never_samples(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            status = main([])
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(output.getvalue())["status"], "unavailable")

    def test_cli_invalid_options_fail_closed(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["--observe", "--samples", "1"])
        self.assertEqual(status, 2)
        self.assertEqual(
            json.loads(output.getvalue())["reasons"],
            ["invalid_probe_configuration"],
        )


if __name__ == "__main__":
    unittest.main()
