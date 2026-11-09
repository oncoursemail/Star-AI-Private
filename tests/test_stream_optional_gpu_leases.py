"""Offline tests: no GPU, OS processes, game, OBS, accounts, or network."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
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
    gate.enable(
        owner_approved=True, host_verified=True, optional_workers_quiescent=True,
    )
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
        with self.assertRaisesRegex(PermissionError, "native optional-worker sweep"):
            gate.enable(owner_approved=True)
        self.assertEqual(request(gate).reason, "owner_opt_in_required")
        gate.enable(
            owner_approved=True, host_verified=True, optional_workers_quiescent=True,
        )
        self.assertEqual(request(gate).reason, "resource_disabled")
        self.assertFalse(gate.metrics()["admitted"])

    def test_warming_and_stale_data_never_approve_gpu_work(self) -> None:
        gov = StreamLoadGovernor()
        gov.enable(owner_approved=True)
        gate = OptionalGpuLeaseGate(gov)
        gate.enable(
            owner_approved=True, host_verified=True, optional_workers_quiescent=True,
        )
        self.assertEqual(request(gate, now_s=10).reason, "resource_telemetry_stale")
        gov.ingest(sample("one", 10), now_s=10, host_verified=True)
        self.assertEqual(request(gate, now_s=10).reason, "resource_warming")
        gov.ingest(sample("two", 11), now_s=11, host_verified=True)
        gov.ingest(sample("three", 12), now_s=12, host_verified=True)
        self.assertEqual(request(gate).action, "admit")

    def test_reservations_cannot_double_spend_observed_vram_headroom(self) -> None:
        _, gate = ready()
        first = request(gate, vram_mb=1300)
        second = request(gate, vram_mb=1300)
        self.assertEqual((first.action, second.action), ("admit", "admit"))
        self.assertEqual(request(gate, vram_mb=500).reason, "vram_reserve_exhausted")
        self.assertEqual(gate.metrics()["outstanding"], 2)
        self.assertFalse(gate.acknowledge_stopped(
            first.lease.lease_id, host_verified=True, physical_worker_stopped=False,
        ))
        self.assertEqual(request(gate, vram_mb=500).reason, "vram_reserve_exhausted")
        self.assertTrue(gate.acknowledge_stopped(
            first.lease.lease_id, host_verified=True, physical_worker_stopped=True,
        ))
        self.assertEqual(request(gate, vram_mb=500).action, "admit")

    def test_near_full_vram_never_enables_second_model(self) -> None:
        gov = StreamLoadGovernor()
        gov.enable(owner_approved=True)
        for time_s in (10, 11, 12):
            gov.ingest(sample(str(time_s), time_s, used_mb=6300),
                       now_s=time_s, host_verified=True)
        gate = OptionalGpuLeaseGate(gov)
        gate.enable(
            owner_approved=True, host_verified=True, optional_workers_quiescent=True,
        )
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
            gate.enable(
                owner_approved=True, host_verified=True, optional_workers_quiescent=True,
            )
        self.assertTrue(gate.acknowledge_stopped(
            lease.lease_id, host_verified=True, physical_worker_stopped=True,
        ))
        gate.enable(
            owner_approved=True, host_verified=True, optional_workers_quiescent=True,
        )
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
        lease_id = request(gate).lease.lease_id
        self.assertEqual(gate.review(lease_id, now_s=12,
                                     host_verified=False).action, "stop")
        self.assertEqual(request(gate).reason, "pending_physical_stop")
        self.assertFalse(gate.acknowledge_stopped(
            lease_id, host_verified=False, physical_worker_stopped=True,
        ))
        self.assertFalse(gate.acknowledge_stopped(
            "star-gpu-invalid-999", host_verified=True, physical_worker_stopped=True,
        ))

    def test_concurrent_requests_cannot_race_for_same_gpu_budget(self) -> None:
        gov, _ = ready()
        gate = OptionalGpuLeaseGate(gov, max_workers=2)
        gate.enable(
            owner_approved=True, host_verified=True, optional_workers_quiescent=True,
        )
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


    def test_invalid_verified_review_time_revokes_all_and_latches_stop(self) -> None:
        for invalid in (float("nan"), float("inf"), -1, True, "bad", None):
            with self.subTest(invalid=invalid):
                _, gate = ready()
                one = request(gate).lease
                two = request(gate, vram_mb=256).lease
                self.assertEqual(
                    gate.review(one.lease_id, now_s=invalid, host_verified=True).reason,
                    "host_clock_invalid",
                )
                self.assertEqual(gate.metrics()["stop_pending"], 2)
                self.assertEqual(gate.review(
                    two.lease_id, now_s=12, host_verified=True,
                ).action, "stop")
                self.assertEqual(request(gate).reason, "pending_physical_stop")
                # Even a healthy host sample cannot silently release memory.
                self.assertTrue(gate.acknowledge_stopped(
                    one.lease_id, host_verified=True, physical_worker_stopped=True,
                ))
                self.assertEqual(request(gate).reason, "pending_physical_stop")
                self.assertTrue(gate.acknowledge_stopped(
                    two.lease_id, host_verified=True, physical_worker_stopped=True,
                ))

    def test_invalid_verified_request_time_quarantines_existing_workers(self) -> None:
        _, gate = ready()
        original = request(gate).lease
        rejected = gate.request(
            work_kind="vision", vram_mb=256, duration_s=1,
            now_s=float("nan"), host_verified=True,
        )
        self.assertEqual((rejected.action, rejected.reason),
                         ("reject", "host_clock_invalid"))
        self.assertEqual(gate.review(
            original.lease_id, now_s=12, host_verified=True,
        ).reason, "host_clock_invalid")
        self.assertEqual(gate.metrics()["outstanding"], 1)

    def test_telemetry_adapter_crash_cannot_leave_live_leases_approved(self) -> None:
        gov, gate = ready()
        original = request(gate).lease
        with patch.object(gov, "recommend", side_effect=RuntimeError("private error")):
            decision = gate.review(original.lease_id, now_s=12,
                                   host_verified=True)
            self.assertEqual((decision.action, decision.reason),
                             ("stop", "resource_observer_failed"))
            self.assertEqual(request(gate).reason, "pending_physical_stop")
        self.assertNotIn("private error", decision.reason)
        self.assertEqual(gate.metrics()["stop_pending"], 1)
        self.assertFalse(gate.acknowledge_stopped(
            original.lease_id, host_verified=True, physical_worker_stopped=False,
        ))
        self.assertEqual(gate.metrics()["outstanding"], 1)

    def test_new_host_requires_sweep_even_with_healthy_telemetry(self) -> None:
        gov, previous = ready()
        old = request(previous).lease
        restarted = OptionalGpuLeaseGate(gov)
        self.assertEqual(request(restarted).reason, "owner_opt_in_required")
        for kwargs in (
            {"host_verified": True},
            {"optional_workers_quiescent": True},
            {"host_verified": True, "optional_workers_quiescent": False},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(PermissionError):
                restarted.enable(owner_approved=True, **kwargs)
        self.assertFalse(restarted.metrics()["enabled"])
        self.assertEqual(request(restarted).reason, "owner_opt_in_required")
        self.assertTrue(previous.acknowledge_stopped(
            old.lease_id, host_verified=True, physical_worker_stopped=True,
        ))
        # A real native process sweep is required here; the synthetic test
        # models its independently checked assertion.
        restarted.enable(
            owner_approved=True, host_verified=True, optional_workers_quiescent=True,
        )
        self.assertEqual(request(restarted).action, "admit")

    def test_restart_receipts_never_reuse_id_or_release_new_worker(self) -> None:
        gov, previous = ready()
        old = request(previous).lease
        self.assertTrue(previous.acknowledge_stopped(
            old.lease_id, host_verified=True, physical_worker_stopped=True,
        ))
        with patch("star.stream_optional_gpu_leases.secrets.token_hex",
                   return_value="f" * 32):
            restarted = OptionalGpuLeaseGate(gov)
        restarted.enable(
            owner_approved=True, host_verified=True, optional_workers_quiescent=True,
        )
        fresh = request(restarted).lease
        self.assertNotEqual(old.lease_id, fresh.lease_id)
        self.assertFalse(restarted.acknowledge_stopped(
            old.lease_id, host_verified=True, physical_worker_stopped=True,
        ))
        self.assertEqual(restarted.metrics()["outstanding"], 1)
        self.assertEqual(restarted.review(
            fresh.lease_id, now_s=12, host_verified=True,
        ).action, "run")

    def test_untrusted_sweep_claims_are_not_accepted(self) -> None:
        gov = StreamLoadGovernor()
        gate = OptionalGpuLeaseGate(gov)
        for bad in (1, None, "yes"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                gate.enable(
                    owner_approved=True, host_verified=bad,
                    optional_workers_quiescent=True,
                )
            with self.subTest(quiescent=bad), self.assertRaises(ValueError):
                gate.enable(
                    owner_approved=True, host_verified=True,
                    optional_workers_quiescent=bad,
                )
        self.assertFalse(gate.metrics()["enabled"])


if __name__ == "__main__":
    unittest.main()
