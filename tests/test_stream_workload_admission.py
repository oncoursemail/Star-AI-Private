"""Regression tests for STAR's pure stream workload admission policy."""
import pytest

from star.stream_workload_admission import (
    HostHealth,
    ResourceBudget,
    ResourceVector,
    WorkloadAdmissionController,
    WorkloadLane,
    WorkloadRequest,
)


def make_budget(cpu=100, reserve=30, ram=0, ram_reserve=0, vram=0, vram_reserve=0):
    return ResourceBudget(
        ResourceVector(cpu_millicores=cpu, ram_mb=ram, vram_mb=vram),
        ResourceVector(cpu_millicores=reserve, ram_mb=ram_reserve, vram_mb=vram_reserve),
    )


def make_request(request_id, lane, cpu=0, *, ram=0, vram=0, enqueued=0, deadline=None):
    return WorkloadRequest(
        request_id=request_id,
        lane=lane,
        resources=ResourceVector(cpu_millicores=cpu, ram_mb=ram, vram_mb=vram),
        enqueued_monotonic_ms=enqueued,
        deadline_monotonic_ms=deadline,
    )


def healthy(now=1_000):
    return HostHealth(observed_monotonic_ms=now, realtime_degraded=False)


def degraded(now=1_000):
    return HostHealth(observed_monotonic_ms=now, realtime_degraded=True)


def test_resource_vector_accepts_zero_and_bounded_values():
    assert ResourceVector() == ResourceVector(0, 0, 0)
    assert ResourceVector(1000, 8192, 4096).ram_mb == 8192


@pytest.mark.parametrize("values", [(True, 0, 0), (-1, 0, 0), (0, -1, 0), (0, 0, 1_000_000_001)])
def test_resource_vector_rejects_invalid_units(values):
    with pytest.raises(ValueError):
        ResourceVector(*values)


def test_budget_rejects_reserve_above_capacity():
    with pytest.raises(ValueError, match="reserve"):
        make_budget(cpu=100, reserve=101)


def test_request_rejects_invalid_ids_lanes_and_deadlines():
    with pytest.raises(ValueError, match="request_id"):
        make_request("../unsafe", WorkloadLane.VOICE)
    with pytest.raises(ValueError, match="lane"):
        make_request("valid", "voice")
    with pytest.raises(ValueError, match="deadline"):
        make_request("valid", WorkloadLane.VOICE, enqueued=100, deadline=100)


def test_submission_is_idempotent_while_queued_and_active():
    controller = WorkloadAdmissionController(make_budget())
    request = make_request("voice-1", WorkloadLane.VOICE, cpu=10)
    assert controller.submit(request).status == "queued"
    assert controller.submit(request).status == "queued"
    lease = controller.schedule(1_000, health=healthy())[0]
    active = controller.submit(request)
    assert active.status == "active"
    assert active.lease == lease


def test_queue_capacity_rejects_without_poisoning_the_second_request_id():
    controller = WorkloadAdmissionController(make_budget(), max_queue=1)
    first = make_request("first", WorkloadLane.RESEARCH)
    second = make_request("second", WorkloadLane.RESEARCH)
    assert controller.submit(first).status == "queued"
    assert controller.submit(second).status == "rejected"
    assert controller.cancel_queued("first") is True
    assert controller.submit(second).status == "queued"


def test_priority_orders_audio_voice_interactive_and_research():
    controller = WorkloadAdmissionController(make_budget(cpu=100, reserve=0))
    requests = [
        make_request("research", WorkloadLane.RESEARCH, cpu=1),
        make_request("chat", WorkloadLane.INTERACTIVE, cpu=1),
        make_request("voice", WorkloadLane.VOICE, cpu=1),
        make_request("audio", WorkloadLane.AUDIO, cpu=1),
    ]
    for request in requests:
        controller.submit(request)
    leases = controller.schedule(1_000, health=healthy(), max_admissions=4)
    assert [lease.request_id for lease in leases] == ["audio", "voice", "chat", "research"]


def test_background_cannot_consume_protected_reserve():
    controller = WorkloadAdmissionController(make_budget(cpu=100, reserve=30))
    controller.submit(make_request("background", WorkloadLane.RESEARCH, cpu=71))
    assert controller.schedule(1_000, health=healthy()) == ()
    assert controller.snapshot(1_000, health=healthy()).queued == 1


def test_protected_voice_can_use_the_reserved_slice():
    controller = WorkloadAdmissionController(make_budget(cpu=100, reserve=30))
    controller.submit(make_request("voice", WorkloadLane.VOICE, cpu=30))
    leases = controller.schedule(1_000, health=healthy())
    assert len(leases) == 1
    assert leases[0].request_id == "voice"


def test_background_can_use_capacity_left_after_protected_work_consumes_reserve():
    controller = WorkloadAdmissionController(make_budget(cpu=100, reserve=30))
    controller.submit(make_request("voice", WorkloadLane.VOICE, cpu=30))
    controller.submit(make_request("research", WorkloadLane.RESEARCH, cpu=70))
    leases = controller.schedule(1_000, health=healthy(), max_admissions=2)
    assert [lease.request_id for lease in leases] == ["voice", "research"]


def test_nonprotected_interactive_work_cannot_borrow_reserve():
    controller = WorkloadAdmissionController(make_budget(cpu=100, reserve=30))
    controller.submit(make_request("chat-too-large", WorkloadLane.INTERACTIVE, cpu=71))
    assert controller.schedule(1_000, health=healthy()) == ()
    controller.submit(make_request("chat-fits", WorkloadLane.INTERACTIVE, cpu=70))
    leases = controller.schedule(1_000, health=healthy())
    assert [lease.request_id for lease in leases] == ["chat-fits"]


def test_degraded_host_admits_only_protected_lanes():
    controller = WorkloadAdmissionController(make_budget(cpu=100, reserve=0))
    for request in (
        make_request("audio", WorkloadLane.AUDIO, cpu=1),
        make_request("chat", WorkloadLane.INTERACTIVE, cpu=1),
        make_request("research", WorkloadLane.RESEARCH, cpu=1),
    ):
        controller.submit(request)
    leases = controller.schedule(1_000, health=degraded())
    assert [lease.request_id for lease in leases] == ["audio"]
    snapshot = controller.snapshot(1_000, health=degraded())
    assert snapshot.deferred_for_health == 2


def test_stale_health_blocks_nonprotected_work():
    controller = WorkloadAdmissionController(make_budget(), health_max_age_ms=500)
    controller.submit(make_request("research", WorkloadLane.RESEARCH, cpu=1))
    assert controller.schedule(1_000, health=healthy(now=0)) == ()


def test_missing_health_fails_closed_for_nonprotected_work_but_not_audio():
    controller = WorkloadAdmissionController(make_budget(cpu=100, reserve=0))
    controller.submit(make_request("audio", WorkloadLane.AUDIO, cpu=1))
    controller.submit(make_request("research", WorkloadLane.RESEARCH, cpu=1))
    leases = controller.schedule(1_000, health=None)
    assert [lease.request_id for lease in leases] == ["audio"]


def test_expired_queued_request_is_removed_before_admission():
    controller = WorkloadAdmissionController(make_budget())
    controller.submit(make_request("late", WorkloadLane.VOICE, cpu=1, deadline=1_100))
    assert controller.schedule(1_100, health=healthy(now=1_100)) == ()
    snapshot = controller.snapshot(1_100, health=healthy(now=1_100))
    assert snapshot.queued == 0
    assert snapshot.expired_queued == 1


def test_expired_lease_releases_capacity_and_cannot_be_released_twice():
    controller = WorkloadAdmissionController(make_budget(cpu=10, reserve=0), lease_ttl_ms=100)
    controller.submit(make_request("voice", WorkloadLane.VOICE, cpu=10))
    lease = controller.schedule(1_000, health=healthy())[0]
    controller.submit(make_request("next", WorkloadLane.VOICE, cpu=10))
    with pytest.raises(PermissionError, match="confirmed"):
        controller.release(lease.lease_id, 1_100, host_confirmed_stopped=False)
    snapshot = controller.snapshot(1_100, health=healthy(now=1_100))
    assert snapshot.active == 1
    assert snapshot.expired_active_leases == 1
    assert controller.schedule(1_100, health=healthy(now=1_100)) == ()
    assert controller.release(lease.lease_id, 1_101, host_confirmed_stopped=True) is True
    assert controller.schedule(1_102, health=healthy(now=1_102))[0].request_id == "next"


def test_explicit_release_frees_capacity_for_next_request():
    controller = WorkloadAdmissionController(make_budget(cpu=10, reserve=0))
    controller.submit(make_request("first", WorkloadLane.VOICE, cpu=10))
    first = controller.schedule(1_000, health=healthy())[0]
    controller.submit(make_request("second", WorkloadLane.VOICE, cpu=10))
    assert controller.schedule(1_001, health=healthy(now=1_001)) == ()
    assert controller.release(first.lease_id, 1_002, host_confirmed_stopped=True) is True
    assert controller.schedule(1_003, health=healthy(now=1_003))[0].request_id == "second"


def test_request_id_cannot_be_replayed_after_release():
    controller = WorkloadAdmissionController(make_budget(cpu=10, reserve=0))
    request = make_request("once", WorkloadLane.VOICE, cpu=1)
    controller.submit(request)
    lease = controller.schedule(1_000, health=healthy())[0]
    assert controller.release(lease.lease_id, 1_001, host_confirmed_stopped=True) is True
    assert controller.submit(request).status == "duplicate"


def test_active_limit_bounds_even_zero_resource_requests():
    controller = WorkloadAdmissionController(make_budget(cpu=100, reserve=0), max_active=1)
    controller.submit(make_request("one", WorkloadLane.AUDIO))
    controller.submit(make_request("two", WorkloadLane.AUDIO))
    leases = controller.schedule(1_000, health=healthy(), max_admissions=2)
    assert len(leases) == 1
    assert controller.snapshot(1_000, health=healthy()).queued == 1


def test_max_admissions_bounds_each_scheduler_tick():
    controller = WorkloadAdmissionController(make_budget(cpu=100, reserve=0))
    for index in range(3):
        controller.submit(make_request(f"task-{index}", WorkloadLane.AUDIO))
    assert len(controller.schedule(1_000, health=healthy(), max_admissions=2)) == 2
    assert len(controller.schedule(1_001, health=healthy(now=1_001), max_admissions=1)) == 1


def test_active_background_work_is_not_preempted_for_late_critical_request():
    controller = WorkloadAdmissionController(make_budget(cpu=100, reserve=30))
    controller.submit(make_request("research", WorkloadLane.RESEARCH, cpu=70))
    research = controller.schedule(1_000, health=healthy())[0]
    controller.submit(make_request("voice", WorkloadLane.VOICE, cpu=50))
    assert controller.schedule(1_001, health=healthy(now=1_001)) == ()
    snapshot = controller.snapshot(1_001, health=healthy(now=1_001))
    assert snapshot.active == 1
    assert dict(snapshot.active_by_lane)["research"] == 1
    assert research.request_id == "research"


def test_future_enqueued_request_waits_until_its_monotonic_time():
    controller = WorkloadAdmissionController(make_budget(cpu=100, reserve=0))
    controller.submit(make_request("future", WorkloadLane.AUDIO, cpu=1, enqueued=1_100))
    assert controller.schedule(1_000, health=healthy()) == ()
    assert controller.schedule(1_100, health=healthy(now=1_100))[0].request_id == "future"


def test_monotonic_clock_regression_is_rejected():
    controller = WorkloadAdmissionController(make_budget())
    controller.snapshot(1_000, health=healthy())
    with pytest.raises(ValueError, match="backwards"):
        controller.schedule(999, health=healthy(now=999))


def test_snapshot_is_aggregate_and_contains_no_request_identifiers():
    controller = WorkloadAdmissionController(make_budget(cpu=100, reserve=30))
    controller.submit(make_request("private-id", WorkloadLane.RESEARCH, cpu=1))
    snapshot = controller.snapshot(1_000, health=healthy())
    assert snapshot.queued == 1
    assert all("private-id" not in repr(value) for value in vars(snapshot).values())
    assert dict(snapshot.queued_by_lane)["research"] == 1


def test_cancel_only_removes_queued_work():
    controller = WorkloadAdmissionController(make_budget(cpu=100, reserve=0))
    controller.submit(make_request("queued", WorkloadLane.RESEARCH))
    assert controller.cancel_queued("queued") is True
    controller.submit(make_request("active", WorkloadLane.AUDIO))
    lease = controller.schedule(1_000, health=healthy())[0]
    assert controller.cancel_queued("active") is False
    assert controller.release(lease.lease_id, 1_001) is True


def test_seen_request_ledger_is_bounded():
    controller = WorkloadAdmissionController(make_budget(), max_seen_requests=1)
    controller.submit(make_request("first", WorkloadLane.RESEARCH))
    controller.cancel_queued("first")
    with pytest.raises(RuntimeError, match="replay ledger"):
        controller.submit(make_request("second", WorkloadLane.RESEARCH))


def test_invalid_health_and_lease_identifiers_are_rejected():
    controller = WorkloadAdmissionController(make_budget())
    controller.submit(make_request("voice", WorkloadLane.VOICE))
    with pytest.raises(TypeError, match="HostHealth"):
        controller.schedule(1_000, health=object())
    lease = controller.schedule(1_000, health=healthy())[0]
    with pytest.raises(ValueError, match="lease_id"):
        controller.release("../not-a-lease", 1_001, host_confirmed_stopped=True)
    assert controller.release(lease.lease_id, 1_001) is True


def test_capacity_is_enforced_independently_for_cpu_ram_and_vram():
    budget = make_budget(cpu=100, reserve=0, ram=2048, ram_reserve=0, vram=1024, vram_reserve=0)
    controller = WorkloadAdmissionController(budget)
    controller.submit(make_request("too-much-vram", WorkloadLane.VOICE, cpu=1, ram=1, vram=1025))
    assert controller.schedule(1_000, health=healthy()) == ()
