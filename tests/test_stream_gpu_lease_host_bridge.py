"""Synthetic host-only process-witness tests. No workers or GPU launched."""
import pytest

from star.stream_admission import StreamHealthSample
from star.stream_budget import StreamTelemetry
from star.stream_gpu_lease_host_bridge import HostGPUWorkerLeaseBridge
from star.stream_realtime_gpu_leases import RealtimeGPUWorkLeases, WorkLeaseTicket


class FakeProcess:
    def __init__(self, pid=1205, born=200000.0):
        self.pid = pid
        self.born = born
        self.running = True
        self.throw = False
        self.queries = 0

    def create_time(self):
        if self.throw:
            raise OSError("unavailable")
        return self.born

    def is_running(self):
        self.queries += 1
        if self.throw:
            raise OSError("unavailable")
        return self.running


def sample(at=1000, *, free=6500, game=False, fps=60):
    return StreamHealthSample(
        at,
        StreamTelemetry(
            live=False, game_active=game, total_vram_mib=8192,
            free_vram_mib=free, game_fps=fps, speech_backlog_ms=0,
        ),
        0, 0, True,
    )


def setup(*, timeout=3000):
    leases = RealtimeGPUWorkLeases(lease_timeout_ms=timeout)
    leases.enable(owner_approved=True)
    assert leases.observe(sample())
    offer = leases.reserve(
        kind="research", vram_mib=1100, now_ms=1000, host_verified=True,
    )
    assert offer.ticket
    fake = FakeProcess()
    bridge = HostGPUWorkerLeaseBridge(
        leases, process_factory=lambda pid: fake,
    )
    return leases, offer.ticket, fake, bridge


def test_bind_requires_owner_and_original_process_identity():
    leases, ticket, fake, bridge = setup()
    with pytest.raises(PermissionError):
        bridge.bind_started(ticket, pid=fake.pid, now_ms=1010)
    with pytest.raises(ValueError):
        bridge.bind_started(ticket, pid=True, now_ms=1010, owner_approved=True)
    assert not bridge.bind_started(
        WorkLeaseTicket(ticket.serial, ticket.epoch), pid=fake.pid,
        now_ms=1010, owner_approved=True,
    )
    assert not bridge.bind_started(
        ticket, pid=999, now_ms=1010, owner_approved=True,
    )
    assert bridge.bind_started(
        ticket, pid=fake.pid, now_ms=1010, owner_approved=True,
    )
    assert not bridge.bind_started(
        ticket, pid=fake.pid, now_ms=1020, owner_approved=True,
    )
    assert bridge.metrics()["pinned"] == 1
    assert leases.metrics()["started"] == 1


def test_healthy_heartbeats_keep_os_bound_lease_live_without_stop_intents():
    leases, ticket, fake, bridge = setup()
    assert bridge.bind_started(ticket, pid=fake.pid, now_ms=1010, owner_approved=True)
    assert bridge.reconcile(now_ms=1100) == ()
    assert bridge.reconcile(now_ms=1210) == ()
    assert leases.metrics()["pending_revocations"] == 0
    assert leases.metrics()["outstanding_claims"] == 1
    assert fake.queries >= 6


def test_realtime_pressure_returns_non_authorizing_stop_intent_until_confirmed_exit():
    leases, ticket, fake, bridge = setup()
    assert bridge.bind_started(ticket, pid=fake.pid, now_ms=1010, owner_approved=True)
    assert leases.observe(sample(1100, free=700))
    intents = bridge.reconcile(now_ms=1100)
    assert len(intents) == 1
    assert intents[0].ticket is ticket
    assert intents[0].pid == fake.pid
    assert not intents[0].authorizes_termination
    assert not intents[0].authorizes_broadcast
    assert leases.metrics()["outstanding_claims"] == 1
    # Sending a stop request does NOT free resources. Only observed exit does.
    assert len(bridge.reconcile(now_ms=1150)) == 1
    fake.running = False
    assert bridge.reconcile(now_ms=1200) == ()
    assert leases.metrics()["outstanding_claims"] == 0
    assert bridge.metrics()["confirmed_stopped"] == 1


def test_process_exception_not_mistaken_for_stop():
    leases, ticket, fake, bridge = setup()
    assert bridge.bind_started(ticket, pid=fake.pid, now_ms=1010, owner_approved=True)
    fake.throw = True
    intents = bridge.reconcile(now_ms=1100)
    assert intents[0].reason == "process_identity_unverified"
    assert leases.metrics()["enabled"] is False
    assert leases.metrics()["outstanding_claims"] == 1
    assert not leases.release(ticket)
    assert len(bridge.reconcile(now_ms=1150)) == 1
    fake.throw = False
    fake.running = False
    assert bridge.reconcile(now_ms=1200) == ()
    assert leases.metrics()["outstanding_claims"] == 0


def test_pid_reuse_not_evidence_of_original_worker_termination():
    leases, ticket, fake, bridge = setup()
    assert bridge.bind_started(ticket, pid=fake.pid, now_ms=1010, owner_approved=True)
    fake.born += 120
    intents = bridge.reconcile(now_ms=1110)
    assert intents[0].reason == "process_identity_unverified"
    assert leases.metrics()["outstanding_claims"] == 1
    assert leases.metrics()["enabled"] is False


def test_unconfirmed_stop_keeps_lease_reserved_after_disable():
    leases, ticket, fake, bridge = setup()
    assert bridge.bind_started(ticket, pid=fake.pid, now_ms=1010, owner_approved=True)
    bridge.disable()
    intents = bridge.reconcile(now_ms=1050)
    assert intents[0].ticket is ticket
    with pytest.raises(RuntimeError):
        leases.enable(owner_approved=True)
    assert bridge.metrics()["pinned"] == 1
    fake.running = False
    assert bridge.reconcile(now_ms=1100) == ()
    leases.enable(owner_approved=True)


def test_natural_worker_exit_released_with_os_witness_even_without_revocation():
    leases, ticket, fake, bridge = setup()
    assert bridge.bind_started(ticket, pid=fake.pid, now_ms=1010, owner_approved=True)
    fake.running = False
    assert bridge.reconcile(now_ms=1020) == ()
    assert bridge.metrics()["confirmed_stopped"] == 1
    assert leases.metrics()["released"] == 1


def test_bad_process_evidence_blocks_enrollment_without_lying_about_stop():
    leases, ticket, fake, bridge = setup()
    fake.throw = True
    assert not bridge.bind_started(
        ticket, pid=fake.pid, now_ms=1010, owner_approved=True,
    )
    assert bridge.metrics()["pinned"] == 0
    assert leases.metrics()["outstanding_claims"] == 1
    assert leases.metrics()["started"] == 0


def test_failed_heartbeat_disables_entire_optional_session():
    leases, ticket, fake, bridge = setup(timeout=500)
    assert bridge.bind_started(ticket, pid=fake.pid, now_ms=1010, owner_approved=True)
    assert leases.observe(sample(1500))
    intents = bridge.reconcile(now_ms=2000)
    assert len(intents) == 1
    assert leases.metrics()["pending_revocations"] == 1
    assert leases.metrics()["outstanding_claims"] == 1


def test_faked_invalid_process_handle_and_clock_rollbacks_cannot_free_claim():
    leases, ticket, fake, bridge = setup()
    assert bridge.bind_started(ticket, pid=fake.pid, now_ms=1100, owner_approved=True)
    assert bridge.reconcile(now_ms=1200) == ()
    assert len(bridge.reconcile(now_ms=1100)) == 1
    assert leases.metrics()["outstanding_claims"] == 1
    assert not bridge.metrics().get("pid")
    assert not bridge.metrics().get("born_unix_s")


def test_multiple_workers_unknown_one_revokes_others():
    leases = RealtimeGPUWorkLeases(max_optional_jobs=2)
    leases.enable(owner_approved=True)
    leases.observe(sample())
    a = leases.reserve(kind="research", vram_mib=500, now_ms=1000, host_verified=True)
    b = leases.reserve(kind="vision", vram_mib=500, now_ms=1000, host_verified=True)
    assert a.ticket and b.ticket
    processes = {111: FakeProcess(pid=111), 222: FakeProcess(pid=222)}
    bridge = HostGPUWorkerLeaseBridge(
        leases, process_factory=lambda pid: processes[pid],
    )
    assert bridge.bind_started(a.ticket, pid=111, now_ms=1010, owner_approved=True)
    assert bridge.bind_started(b.ticket, pid=222, now_ms=1010, owner_approved=True)
    processes[111].throw = True
    intents = bridge.reconcile(now_ms=1100)
    assert {x.pid for x in intents} == {111, 222}
    assert leases.metrics()["outstanding_claims"] == 2
    processes[111].throw = False
    processes[111].running = False
    processes[222].running = False
    assert bridge.reconcile(now_ms=1200) == ()
    assert leases.metrics()["outstanding_claims"] == 0
