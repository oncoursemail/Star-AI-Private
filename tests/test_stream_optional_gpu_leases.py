"""Offline tests: no GPU, OS processes, game, OBS, accounts, or network."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier
import unittest

from star.stream_load_governor import StreamLoadGovernor, StreamLoadSample
from star.stream_optional_gpu_leases import OptionalGpuLeaseGate


def sample(ident: str, time_s: float, *, used_mb: float = 3500,
           render_pct: float = 0) -> StreamLoadSample:
    return StreamLoadSample(
        sample_id=ident, measured_at_s=time_s,
        game_p95_frame_ms=13, game_target_fps=60,
        obs_render_missed_pct=render_pct, obs_encode_skipped_pct=0,
        obs_network_dropped_pct=0, gpu_vram_used_mb=used_mb,
        gpu_vram_total_mb=8192, tts_first_audio_p95_ms=150,
    )


def ready() -> tuple[StreamLoadGovernor, OptionalGpuLeaseGate]:
    gov = StreamLoadGovernor()
    gov.enable(owner_approved=True)
    for time_s in (10, 11, 12):
        assert gov.ingest(sample(f"good-{time_s}", time_s),
                          now_s=time_s, host_verified=True)
    gate = OptionalGpuLeaseGate(gov)
    gate.enable(owner_approved=True)
    return gov, gate


def request(gate: OptionalGpuLeaseGate, *, now_s: float = 12,
            vram_mb: int = 1024) -> object:
    return gate.request(
        work_kind="vision", vram_mb=vram_mb, duration_s=5,
        now_s=now_s, host_verified=True,
    )


class OptionalGpuLeaseTests(unittest.TestCase):
    def test_disabled_by_default_and_owner_must_opt_in(self) -> None:
        gov = StreamLoadGovernor()
        gate = OptionalGpuLeaseGate(gov)
        self.assertEqual(request(gate).reason, "owner_opt_in_required")
        with self.assertRaises(PermissionError):
            gate.enable()
        gate.enable(owner_approved=True)
        self.assertEqual(request(gate).reason, "resource_disabled")
        self.assertFalse(gate.metrics()["admitted"])

    def test_warming_and_stale_data_never_approve_gpu_work(self) -> None:
        gov = StreamLoadGovernor()
        gov.enable(owner_approved=True)
        gate = OptionalGpuLeaseGate(gov)
        gate.enable(owner_approved=True)
        self.assertEqual(request(gate).reason, "resource_telemetry_stale")
        gov.ingest(sample("one", 10), now_s=10, host_verified=True)
        self.assertEqual(request(gate, now_s=10).reason, "resource_warming")
        gov.ingest(sample("two", 11), now_s=11, host_verified=True)
        gov.ingest(sample("three", 12), now_s=12, host_verified=True)
        self.assertEqual(request(gate).action, "admit")

    def test_reservations_cannot_double_spend_observed_vram_headroom(self) -> None:
        _, gate = ready()
        first = request(gate, vram_mb=1800)
        second = request(gate, vram_mb=1800)
        self.assertEqual((first.action, second.action), ("admit", "admit"))
        self.assertEqual(request(gate, vram_mb=300).reason, "vram_reserve_exhausted")
        self.assertEqual(gate.metrics()["outstanding"], 2)
        self.assertFalse(gate.acknowledge_stopped(
            first.lease.lease_id, host_verified=True, physical_worker_stopped=False,
        ))
        self.assertEqual(request(gate, vram_mb=300).reason, "vram_reserve_exhausted")
        self.assertTrue(gate.acknowledge_stopped(
            first.lease.lease_id, host_verified=True, physical_worker_stopped=True,
        ))
        self.assertEqual(request(gate, vram_mb=300).action, "admit")

    def test_near_full_vram_never_enables_second_model(self) -> None:
        gov = StreamLoadGovernor()
        gov.enable(owner_approved=True)
        for time_s in (10, 11, 12):
            gov.ingest(sample(str(time_s), time_s, used_mb=6300),
                       now_s=time_s, host_verified=True)
        gate = OptionalGpuLeaseGate(gov)
        gate.enable(owner_approved=True)
        self.assertEqual(request(gate).reason, "resource_normal")
        self.assertFalse(gate.metrics()["admitted"])

    def test_pressure_revokes_active_and_stop_is_latched_until_witness(self) -> None:
        gov, gate = ready()
        first = request(gate).lease
        self.assertEqual(gate.review(first.lease_id, now_s=12,
                                     host_verified=True).action, "run")
        gov.ingest(sample("hot", 13, render_pct=4), now_s=13,
                   host_verified=True)
        decision = gate.review(first.lease_id, now_s=13, host_verified=True)
        self.assertEqual(decision.action, "stop")
        self.assertEqual(decision.reason, "resource_critical")
        self.assertEqual(gate.metrics()["stop_pending"], 1)
        # Recovered telemetry alone cannot prove the CUDA worker terminated.
        for time_s in (14, 15, 16, 17, 18, 19):
            gov.ingest(sample(f"recovered-{time_s}", time_s),
                       now_s=time_s, host_verified=True)
        self.assertEqual(request(gate, now_s=19).reason, "pending_physical_stop")
        self.assertFalse(gate.acknowledge_stopped(first.lease_id))
        self.assertTrue(gate.acknowledge_stopped(
            first.lease_id, host_verified=True, physical_worker_stopped=True,
        ))
        self.assertEqual(request(gate, now_s=19).action, "admit")

    def test_stale_telemetry_cannot_leave_a_running_gpu_lease(self) -> None:
        _, gate = ready()
        lease = request(gate).lease
        decision = gate.review(lease.lease_id, now_s=16, host_verified=True)
        self.assertEqual(decision.action, "stop")
        self.assertEqual(decision.reason, "resource_telemetry_stale")
        self.assertEqual(request(gate, now_s=16).reason, "pending_physical_stop")

    def test_lease_expiry_never_releases_vram_without_physical_stop(self) -> None:
        gov, gate = ready()
        lease = request(gate).lease
        for time_s in (13, 14, 15, 16, 17):
            gov.ingest(sample(f"keepalive-{time_s}", time_s),
                       now_s=time_s, host_verified=True)
        result = gate.review(lease.lease_id, now_s=17, host_verified=True)
        self.assertEqual((result.action, result.reason), ("stop", "lease_expired"))
        self.assertEqual(gate.metrics()["outstanding"], 1)
        self.assertEqual(request(gate, now_s=17).reason, "pending_physical_stop")

    def test_owner_disable_and_reenable_never_forgets_live_worker(self) -> None:
        _, gate = ready()
        lease = request(gate).lease
        gate.disable()
        self.assertEqual(gate.review(lease.lease_id, now_s=12,
                                     host_verified=True).action, "stop")
        with self.assertRaisesRegex(RuntimeError, "physical workers"):
            gate.enable(owner_approved=True)
        self.assertTrue(gate.acknowledge_stopped(
            lease.lease_id, host_verified=True, physical_worker_stopped=True,
        ))
        gate.enable(owner_approved=True)
        self.assertEqual(request(gate).action, "admit")
        self.assertNotEqual(request(gate).lease, lease)

    def test_clock_rollback_revokes_worker_and_does_not_restore_it(self) -> None:
        _, gate = ready()
        lease = request(gate).lease
        self.assertEqual(gate.review(lease.lease_id, now_s=11,
                                     host_verified=True).reason, "host_clock_reversed")
        self.assertEqual(gate.review(lease.lease_id, now_s=12,
                                     host_verified=True).reason, "host_clock_reversed")
        self.assertEqual(gate.metrics()["stop_pending"], 1)

    def test_source_failure_and_invalid_receipts_fail_closed(self) -> None:
        _, gate = ready()
        self.assertEqual(gate.request(
            work_kind="vision", vram_mb=1024, duration_s=2,
            now_s=1e9, host_verified=False,
        ).reason, "host_not_verified")
        self.assertEqual(request(gate).action, "admit")
        lease_id = "star-gpu-1-1"
        self.assertEqual(gate.review(lease_id, now_s=12,
                                     host_verified=False).action, "stop")
        self.assertEqual(request(gate).reason, "pending_physical_stop")
        self.assertFalse(gate.acknowledge_stopped(
            lease_id, host_verified=False, physical_worker_stopped=True,
        ))
        self.assertFalse(gate.acknowledge_stopped(
            "star-gpu-1-999", host_verified=True, physical_worker_stopped=True,
        ))

    def test_concurrent_requests_cannot_race_for_same_gpu_budget(self) -> None:
        _, gate = ready()
        gate = OptionalGpuLeaseGate(gate._governor, max_workers=2)
        gate.enable(owner_approved=True)
        barrier = Barrier(8)

        def allocate(_: int) -> str:
            barrier.wait()
            return request(gate, vram_mb=1000).action

        with ThreadPoolExecutor(max_workers=8) as pool:
            actions = list(pool.map(allocate, range(8)))
        self.assertEqual(actions.count("admit"), 2)
        self.assertEqual(gate.metrics()["outstanding"], 2)

    def test_invalid_claims_have_strict_types_and_bounds(self) -> None:
        _, gate = ready()
        for kind, memory, duration in (
            ("viewer_chat", 100, 1), ("vision", True, 1),
            ("vision", 0, 1), ("vision", 100, 0),
            ("vision", 100, float("nan")), ("vision", 100, 99),
        ):
            with self.subTest(kind=kind, memory=memory, duration=duration):
                with self.assertRaises(ValueError):
                    gate.request(work_kind=kind, vram_mb=memory,
                                 duration_s=duration, now_s=12, host_verified=True)
        self.assertEqual(gate.metrics()["outstanding"], 0)


if __name__ == "__main__":
    unittest.main()
