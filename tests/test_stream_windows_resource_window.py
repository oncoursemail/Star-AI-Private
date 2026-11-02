"""Offline adversarial tests: no OBS, VTube Studio, game, or GPU is accessed."""
from __future__ import annotations

import unittest

from star.stream_windows_rehearsal_preflight import GpuHeadroom, ProcessWitness
from star.stream_windows_resource_window import (
    _WindowSample, evaluate_resource_window, probe_windows_resource_window,
)


GPU_UUID = "GPU-11111111-2222-3333-4444-555555555555"


def gpu_with_id(total: int, free: int, utilization: int) -> GpuHeadroom:
    return GpuHeadroom(total, free, utilization, device_uuid=GPU_UUID)


def witnesses() -> tuple[ProcessWitness, ...]:
    return (
        ProcessWitness("obs64.exe", 10, 100.0),
        ProcessWitness("VTube Studio.exe", 11, 101.0),
        ProcessWitness("llama-server.exe", 12, 102.0),
        ProcessWitness("MyGame.exe", 13, 103.0),
    )


def sample(at: float, gpu: GpuHeadroom | None = None, *, processes=None) -> _WindowSample:
    if gpu is None:
        gpu = gpu_with_id(8192, 3500, 35)
    return _WindowSample(at, witnesses() if processes is None else processes, gpu)


def evaluate(samples=None):
    if samples is None:
        samples = [sample(i * 0.5) for i in range(5)]
    return evaluate_resource_window(samples, pinned_game_identity=(13, 103.0))


class Clock:
    def __init__(self) -> None:
        self.value = 500.0
        self.sleeps = 0

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        self.value += seconds


class TestResourceStabilityWindow(unittest.TestCase):
    def test_stable_window_is_candidate_not_permission(self):
        result = evaluate()
        self.assertEqual(result.status, "candidate")
        self.assertEqual(result.sample_count, 5)
        self.assertEqual(result.observed_span_ms, 2000)
        self.assertEqual(result.gpu_min_free_mib, 3500)
        self.assertEqual(result.gpu_max_utilization_pct, 35)
        self.assertTrue(result.host_processes_stable)
        self.assertFalse(result.authorized_to_play)
        self.assertFalse(result.authorized_to_broadcast)
        self.assertTrue(result.candidate_for_nonbroadcast_rehearsal)
        for forbidden in ("MyGame.exe", "obs64.exe", "103.0", "llama-server.exe"):
            self.assertNotIn(forbidden, repr(result))

    def test_infrastructure_only_window_cannot_claim_stable_game(self):
        infra_only = witnesses()[:3]
        for pid, creation in ((10, 100.0), (11, 101.0), (12, 102.0)):
            with self.subTest(infrastructure_pid=pid):
                report = evaluate_resource_window(
                    [sample(i * 0.5, processes=infra_only) for i in range(5)],
                    pinned_game_identity=(pid, creation),
                )
                self.assertEqual(report.status, "deferred")
                self.assertFalse(report.host_processes_stable)
                self.assertIn("pinned_game_is_infrastructure_process", report.reasons)
                self.assertFalse(report.authorized_to_play)
                self.assertFalse(report.authorized_to_broadcast)

    def test_transient_vram_crash_cannot_be_averaged_out(self):
        samples = [sample(i * 0.5) for i in range(5)]
        samples[2] = sample(1.0, gpu_with_id(8192, 260, 3))
        result = evaluate(samples)
        self.assertEqual(result.status, "deferred")
        self.assertEqual(result.gpu_min_free_mib, 260)
        self.assertIn("insufficient_free_gpu_memory", result.reasons)

    def test_short_gpu_busy_spike_fails_preflight(self):
        samples = [sample(i * 0.5) for i in range(5)]
        samples[3] = sample(1.5, gpu_with_id(8192, 4500, 99))
        result = evaluate(samples)
        self.assertIn("gpu_utilization_high", result.reasons)
        self.assertEqual(result.gpu_max_utilization_pct, 99)

    def test_gpu_index_change_or_driver_counter_inconsistency(self):
        samples = [sample(i * 0.5) for i in range(5)]
        samples[3] = sample(1.5, gpu_with_id(12288, 6500, 15))
        result = evaluate(samples)
        self.assertIn("gpu_total_changed_during_window", result.reasons)
        self.assertEqual(result.status, "deferred")

    def test_very_short_and_irregular_times_are_rejected(self):
        fast = [sample(i * 0.01) for i in range(5)]
        self.assertIn("sampling_window_too_short", evaluate(fast).reasons)
        self.assertIn("irregular_sample_cadence", evaluate(fast).reasons)
        gap = [sample(t) for t in (0, 0.5, 1.0, 6.0, 6.5)]
        self.assertIn("irregular_sample_cadence", evaluate(gap).reasons)

    def test_changed_game_pid_creation_time_during_window(self):
        samples = [sample(i * 0.5) for i in range(5)]
        changed = tuple(
            ProcessWitness(p.name, p.pid, 200.0) if p.pid == 13 else p
            for p in witnesses()
        )
        samples[3] = sample(1.5, processes=changed)
        report = evaluate(samples)
        self.assertIn("process_identity_changed_during_window", report.reasons)
        self.assertIn("pinned_game_process_missing_or_restarted", report.reasons)
        self.assertFalse(report.host_processes_stable)

    def test_obs_restarts_even_when_alias_still_matches(self):
        changed = tuple(p for p in witnesses() if p.pid != 10)
        changed += (ProcessWitness("obs.exe", 90, 190.0),)
        samples = [sample(i * 0.5) for i in range(5)]
        samples[2] = sample(1.0, processes=changed)
        report = evaluate(samples)
        self.assertEqual(report.status, "deferred")
        self.assertIn("process_identity_changed_during_window", report.reasons)

    def test_intermediate_process_ambiguity_does_not_disappear(self):
        samples = [sample(i * 0.5) for i in range(5)]
        samples[2] = sample(
            1.0,
            processes=witnesses() + (ProcessWitness("obs.exe", 90, 190.0),),
        )
        self.assertIn("obs_process_missing_or_ambiguous", evaluate(samples).reasons)

    def test_missing_middle_gpu_sample_fails_closed_and_hides_partial_peak(self):
        samples = [sample(i * 0.5) for i in range(5)]
        samples[2] = _WindowSample(1.0, witnesses(), None)
        result = evaluate(samples)
        self.assertEqual(result.status, "deferred")
        self.assertIn("gpu_sample_missing", result.reasons)
        self.assertIsNone(result.gpu_min_free_mib)
        self.assertIsNone(result.gpu_max_utilization_pct)

    def test_invalid_host_timestamps_and_processes_rejected(self):
        for bad_time in (float("nan"), -1.0, True, 10**20):
            samples = [sample(i * 0.5) for i in range(5)]
            samples[2] = sample(bad_time)
            with self.subTest(bad_time=bad_time), self.assertRaises(ValueError):
                evaluate(samples)
        samples = [sample(i * 0.5) for i in range(5)]
        samples[2] = sample(1.0, processes=witnesses() + (witnesses()[0],))
        with self.assertRaises(ValueError):
            evaluate(samples)

    def test_missing_required_process_is_not_reported_stable(self):
        missing_obs = tuple(p for p in witnesses() if p.pid != 10)
        samples = [sample(i * 0.5, processes=missing_obs) for i in range(5)]
        report = evaluate(samples)
        self.assertFalse(report.host_processes_stable)
        self.assertIn("obs_process_missing_or_ambiguous", report.reasons)

    def test_unbounded_process_generator_fails_closed(self):
        clock = Clock()

        def unbounded():
            for pid in range(1, 40000):
                yield ProcessWitness("other.exe", pid, 100.0)

        report = probe_windows_resource_window(
            owner_approved=True, pinned_game_identity=(13, 103.0),
            system_name=lambda: "Windows",
            process_reader=unbounded,
            gpu_reader=lambda _: gpu_with_id(8192, 3200, 20),
            monotonic_clock=clock.now, sleeper=clock.sleep,
        )
        self.assertEqual(report.status, "unavailable")
        self.assertEqual(report.reasons, ("resource_window_evidence_invalid",))

    def test_window_size_is_bounded(self):
        for count in (0, 2, 10):
            with self.subTest(count=count), self.assertRaises(ValueError):
                evaluate([sample(i * 0.5) for i in range(count)])

    def test_probe_requires_explicit_approval_before_any_read(self):
        with self.assertRaises(PermissionError):
            probe_windows_resource_window(
                pinned_game_identity=(13, 103.0),
                system_name=lambda: self.fail("no platform probe without approval"),
            )

    def test_linux_probe_avoids_all_process_and_gpu_readers(self):
        report = probe_windows_resource_window(
            owner_approved=True, pinned_game_identity=(13, 103.0),
            system_name=lambda: "Linux",
            process_reader=lambda: self.fail("no process access"),
            gpu_reader=lambda _: self.fail("no GPU access"),
        )
        self.assertEqual(report.status, "unavailable")
        self.assertEqual(report.reasons, ("windows_host_required",))

    def test_trusted_probe_collects_five_temporally_distinct_samples(self):
        clock = Clock()
        seen: list[int] = []
        result = probe_windows_resource_window(
            owner_approved=True, pinned_game_identity=(13, 103.0),
            system_name=lambda: "Windows",
            process_reader=witnesses,
            gpu_reader=lambda index: (seen.append(index) or gpu_with_id(8192, 3200, 20)),
            monotonic_clock=clock.now,
            sleeper=clock.sleep,
        )
        self.assertEqual(result.status, "candidate")
        self.assertEqual(result.sample_count, 5)
        self.assertEqual(clock.sleeps, 4)
        self.assertEqual(seen, [0, 0, 0, 0, 0])

    def test_bad_gpu_read_sample_defers_without_leaking_exception(self):
        clock = Clock()
        counter = 0

        def gpu(_index: int) -> GpuHeadroom:
            nonlocal counter
            counter += 1
            if counter == 3:
                raise RuntimeError("SECRET_CONTEXT_VALUE")
            return gpu_with_id(8192, 3200, 20)

        result = probe_windows_resource_window(
            owner_approved=True, pinned_game_identity=(13, 103.0),
            system_name=lambda: "Windows",
            process_reader=witnesses, gpu_reader=gpu,
            monotonic_clock=clock.now, sleeper=clock.sleep,
        )
        self.assertEqual(result.status, "deferred")
        self.assertIn("gpu_sample_missing", result.reasons)
        self.assertNotIn("SECRET_CONTEXT_VALUE", repr(result))

    def test_malformed_windows_probe_stays_sanitized(self):
        clock = Clock()
        result = probe_windows_resource_window(
            owner_approved=True, pinned_game_identity=(13, 103.0),
            system_name=lambda: "Windows",
            process_reader=lambda: witnesses() + (witnesses()[0],),
            gpu_reader=lambda _: gpu_with_id(8192, 3200, 20),
            monotonic_clock=clock.now, sleeper=clock.sleep,
        )
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.reasons, ("resource_window_evidence_invalid",))

    def test_invalid_parameter_validation_before_read(self):
        for invalid in (0, True, 10):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                probe_windows_resource_window(
                    owner_approved=True, pinned_game_identity=None,
                    sample_count=invalid,
                    process_reader=lambda: self.fail("no reads"),
                )
        with self.assertRaises(ValueError):
            probe_windows_resource_window(
                owner_approved=True, pinned_game_identity=None,
                sample_spacing_s=float("inf"),
            )


if __name__ == "__main__":
    unittest.main()
