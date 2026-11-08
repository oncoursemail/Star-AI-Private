"""Offline deterministic reservation tests: never launches GPU jobs or OBS."""
from dataclasses import replace
from threading import Thread

import pytest

from star.stream_admission import StreamHealthSample
from star.stream_budget import StreamTelemetry
from star.stream_realtime_gpu_leases import RealtimeGPUWorkLeases, WorkLeaseTicket


def sample(at=1000, *, free=7000, live=False, rehearsal=False,
           game=False, fps=60, backlog=0, render=0, encode=0, verified=True):
    return StreamHealthSample(
        at, StreamTelemetry(
            live=live, game_active=game, free_vram_mib=free,
            total_vram_mib=8192, game_fps=fps, speech_backlog_ms=backlog,
            private_stream_rehearsal=rehearsal,
        ), render, encode, verified,
    )


def enabled(**kwargs):
    gate = RealtimeGPUWorkLeases(**kwargs)
    gate.enable(owner_approved=True)
    return gate


def test_default_off_and_never_grants_execution_permission():
    gate = RealtimeGPUWorkLeases()
    with pytest.raises(PermissionError):
        gate.enable()
    assert not gate.observe(sample())
    denied = gate.reserve(kind="research", vram_mib=512, now_ms=1000, host_verified=True)
    assert denied.ticket is None
    assert not denied.authorizes_execution
    gate.enable(owner_approved=True)
    assert gate.observe(sample())
    advice = gate.reserve(kind="research", vram_mib=512, now_ms=1000, host_verified=True)
    assert isinstance(advice.ticket, WorkLeaseTicket)
    assert not advice.authorizes_execution
    assert not advice.authorizes_gameplay
    assert not advice.authorizes_broadcast


def test_concurrent_reservations_cannot_double_spend_single_free_gpu_snapshot():
    gate = enabled(minimum_unclaimed_mib=1536, max_optional_jobs=3)
    assert gate.observe(sample(free=3000))
    first = gate.reserve(kind="research", vram_mib=1000, now_ms=1000, host_verified=True)
    assert first.ticket is not None
    assert first.available_mib_after_claim == 2000
    denied = gate.reserve(kind="render", vram_mib=500, now_ms=1000, host_verified=True)
    assert denied.ticket is None
    assert denied.reason == "critical_gpu_reserve_protected"
    assert gate.metrics()["outstanding_claims"] == 1


def test_only_host_acknowledged_stop_releases_claim_even_when_revoked():
    gate = enabled()
    gate.observe(sample())
    offer = gate.reserve(kind="training", vram_mib=1024, now_ms=1000, host_verified=True)
    assert offer.ticket
    assert gate.mark_started(offer.ticket, now_ms=1010, host_confirms_worker_started=True)
    assert not gate.release(offer.ticket)
    assert gate.observe(sample(1200, free=800))
    assert offer.ticket in gate.poll(now_ms=1200)
    assert not gate.heartbeat(offer.ticket, now_ms=1210, host_confirms_worker_running=True)
    assert gate.metrics()["outstanding_claims"] == 1
    assert gate.reserve(kind="vision", vram_mib=128, now_ms=1220,
                        host_verified=True).ticket is None
    assert gate.release(offer.ticket, host_confirms_worker_stopped=True)
    assert gate.metrics()["outstanding_claims"] == 0


def test_private_rehearsal_permits_only_bounded_vision_and_revokes_background_study():
    gate = enabled()
    gate.observe(sample())
    research = gate.reserve(kind="research", vram_mib=1024, now_ms=1000, host_verified=True)
    assert research.ticket is not None
    gate.observe(sample(1100, rehearsal=True, game=True))
    assert research.ticket in gate.poll(now_ms=1100)
    assert not gate.reserve(kind="research", vram_mib=64,
                            now_ms=1100, host_verified=True).ticket
    assert gate.release(research.ticket, host_confirms_worker_stopped=True)
    vision = gate.reserve(kind="vision", vram_mib=300, now_ms=1110, host_verified=True)
    assert vision.ticket is not None


@pytest.mark.parametrize("pressure", [
    {"free": 600}, {"fps": 22, "game": True}, {"backlog": 700},
    {"render": 3, "rehearsal": True}, {"encode": 2, "live": True},
])
def test_real_time_pressure_requests_stop_immediately_without_releasing_memory(pressure):
    gate = enabled()
    gate.observe(sample())
    offer = gate.reserve(kind="vision", vram_mib=512, now_ms=1000, host_verified=True)
    assert offer.ticket
    assert gate.observe(sample(1100, **pressure))
    assert offer.ticket in gate.poll(now_ms=1100)
    assert gate.metrics()["outstanding_claims"] == 1


def test_heartbeat_timeout_and_stale_telemetry_revoke_without_automatic_reclaim():
    gate = enabled(lease_timeout_ms=500)
    gate.observe(sample())
    offer = gate.reserve(kind="research", vram_mib=100, now_ms=1000, host_verified=True)
    assert offer.ticket
    assert gate.mark_started(offer.ticket, now_ms=1010, host_confirms_worker_started=True)
    assert gate.heartbeat(offer.ticket, now_ms=1350, host_confirms_worker_running=True)
    assert gate.poll(now_ms=1860) == (offer.ticket,)
    assert not gate.heartbeat(offer.ticket, now_ms=1860, host_confirms_worker_running=True)
    assert gate.metrics()["outstanding_claims"] == 1


def test_custom_critical_reserve_revokes_existing_optional_work_when_headroom_falls():
    gate = enabled(minimum_unclaimed_mib=2500)
    gate.observe(sample(free=6200))
    offered = gate.reserve(kind="vision", vram_mib=500, now_ms=1000, host_verified=True)
    assert offered.ticket
    # Existing worker remains charged even though the sample's headroom drops.
    gate.observe(sample(1100, free=2400))
    assert offered.ticket in gate.poll(now_ms=1100)
    assert gate.metrics()["outstanding_claims"] == 1


def test_stale_telemetry_blocks_new_work_even_when_lease_slot_is_empty():
    gate = enabled()
    gate.observe(sample())
    assert gate.reserve(kind="render", vram_mib=128, now_ms=3000,
                        host_verified=True).ticket is None
    assert gate.metrics()["outstanding_claims"] == 0


def test_clock_rollback_invalidates_leases_without_making_ttl_longer():
    gate = enabled()
    gate.observe(sample())
    first = gate.reserve(kind="research", vram_mib=512, now_ms=1300, host_verified=True)
    assert first.ticket
    assert first.ticket in gate.poll(now_ms=1200)
    assert not gate.mark_started(first.ticket, now_ms=1250, host_confirms_worker_started=True)
    assert gate.metrics()["clock_rollbacks"] == 2
    assert gate.metrics()["pending_revocations"] == 1


def test_disable_keeps_unconfirmed_work_outstanding_and_reenable_fails_closed():
    gate = enabled()
    gate.observe(sample())
    first = gate.reserve(kind="research", vram_mib=512, now_ms=1000, host_verified=True)
    assert first.ticket
    gate.disable()
    assert first.ticket in gate.poll(now_ms=1050)
    with pytest.raises(RuntimeError):
        gate.enable(owner_approved=True)
    assert gate.release(first.ticket, host_confirms_worker_stopped=True)
    gate.enable(owner_approved=True)
    gate.observe(sample(2000))
    assert not gate.mark_started(first.ticket, now_ms=2000, host_confirms_worker_started=True)
    second = gate.reserve(kind="vision", vram_mib=100, now_ms=2000, host_verified=True)
    assert second.ticket
    assert second.ticket != first.ticket


def test_forged_equal_fields_ticket_does_not_release_live_claim():
    gate = enabled()
    gate.observe(sample())
    first = gate.reserve(kind="research", vram_mib=512, now_ms=1000, host_verified=True)
    assert first.ticket
    forged = WorkLeaseTicket(first.ticket.serial, first.ticket.epoch)
    assert not gate.release(forged, host_confirms_worker_stopped=True)
    assert not gate.mark_started(forged, now_ms=1010, host_confirms_worker_started=True)
    assert gate.metrics()["outstanding_claims"] == 1


def test_unverified_and_replayed_telemetry_does_not_clear_pressure():
    gate = enabled()
    assert gate.observe(sample(free=1200))
    assert not gate.observe(sample(1000, verified=True, free=7000))
    assert not gate.observe(sample(1600, verified=False, free=7000))
    assert gate.reserve(kind="vision", vram_mib=100, now_ms=1100,
                        host_verified=True).ticket is None


def test_bad_types_and_bounds_rejected():
    with pytest.raises(ValueError):
        RealtimeGPUWorkLeases(max_optional_jobs=True)
    with pytest.raises(ValueError):
        RealtimeGPUWorkLeases(max_sample_age_ms=250)
    gate = enabled()
    gate.observe(sample())
    for k, v in [("gameplay", 256), ("research", 0), ("research", True)]:
        with pytest.raises(ValueError):
            gate.reserve(kind=k, vram_mib=v, now_ms=1000, host_verified=True)
    with pytest.raises(ValueError):
        gate.poll(now_ms=float("nan"))
    with pytest.raises(TypeError):
        gate.observe("viewer text")  # type: ignore[arg-type]


def test_parallel_requests_never_exceed_gpu_or_slot_limits():
    gate = enabled(max_optional_jobs=2, minimum_unclaimed_mib=2000)
    gate.observe(sample(free=4200))
    results = []

    def worker():
        results.append(gate.reserve(kind="research", vram_mib=1500,
                                    now_ms=1000, host_verified=True))

    threads = [Thread(target=worker) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(r.ticket is not None for r in results) == 1
    assert gate.metrics()["outstanding_claims"] == 1


def test_stale_old_snapshot_cannot_be_made_healthy_by_repeated_client_poll():
    gate = enabled()
    gate.observe(sample())
    offer = gate.reserve(kind="vision", vram_mib=100, now_ms=1000, host_verified=True)
    assert offer.ticket
    gate.poll(now_ms=2499)
    assert offer.ticket in gate.poll(now_ms=2501)
    assert not gate.heartbeat(offer.ticket, now_ms=2502, host_confirms_worker_running=True)


def test_sample_validator_rejects_invalid_crossed_rehearsal_live_mode():
    with pytest.raises(ValueError):
        replace(sample(), telemetry=StreamTelemetry(
            live=True, private_stream_rehearsal=True, game_active=True,
            free_vram_mib=1000, total_vram_mib=8192,
            game_fps=50, speech_backlog_ms=0,
        ))
