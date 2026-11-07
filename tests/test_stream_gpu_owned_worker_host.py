"""Offline host-owned optional GPU process lifecycle regression tests."""
from subprocess import Popen

import pytest

from star.stream_admission import StreamHealthSample
from star.stream_budget import StreamTelemetry
from star.stream_gpu_lease_host_bridge import HostGPUWorkerLeaseBridge
from star.stream_gpu_owned_worker_host import HostOwnedOptionalGPUWorkers
from star.stream_realtime_gpu_leases import RealtimeGPUWorkLeases, WorkLeaseTicket


class FakeOwned(Popen):
    """An in-memory host-owned Popen handle: never starts/kills a real worker."""

    def __init__(self, pid=1880):
        self.pid = pid
        self.code = None
        self.stop_requests = 0
        self.raise_poll = False
        self.raise_stop = False

    def poll(self):
        if self.raise_poll:
            raise OSError("unavailable")
        return self.code

    def terminate(self):
        self.stop_requests += 1
        if self.raise_stop:
            raise OSError("no rights")


class FakeWitness:
    def __init__(self, owned, *, born=3000000.0):
        self.owned = owned
        self.born = born
        self.throw = False

    @property
    def pid(self):
        return self.owned.pid

    def create_time(self):
        if self.throw:
            raise OSError("process query unavailable")
        return self.born

    def is_running(self):
        if self.throw:
            raise OSError("process query unavailable")
        return self.owned.code is None


def sample(at=1000, *, free=6500):
    return StreamHealthSample(
        at, StreamTelemetry(
            live=False, game_active=False, total_vram_mib=8192,
            free_vram_mib=free, game_fps=60, speech_backlog_ms=0,
        ), 0, 0, True,
    )


def fixture(*, process=None, witness=None, os="Windows"):
    leases = RealtimeGPUWorkLeases()
    leases.enable(owner_approved=True)
    assert leases.observe(sample())
    advice = leases.reserve(
        kind="research", vram_mib=500, now_ms=1000, host_verified=True,
    )
    assert advice.ticket
    process = process or FakeOwned()
    witness = witness or FakeWitness(process)
    bridge = HostGPUWorkerLeaseBridge(
        leases, process_factory=lambda _pid: witness,
    )
    owned = HostOwnedOptionalGPUWorkers(
        leases, bridge, system_name=lambda: os,
    )
    return leases, advice.ticket, process, witness, bridge, owned


def test_requires_explicit_host_enable_and_matching_session():
    leases, ticket, p, _, bridge, host = fixture()
    with pytest.raises(PermissionError):
        host.enable()
    with pytest.raises(PermissionError):
        host.enroll_spawned(ticket, p, now_ms=1010, owner_approved=True)
    host.enable(owner_approved=True)
    with pytest.raises(PermissionError):
        host.enroll_spawned(ticket, p, now_ms=1010)
    with pytest.raises(TypeError):
        host.enroll_spawned(ticket, object(), now_ms=1010, owner_approved=True)
    with pytest.raises(ValueError):
        host.enroll_spawned(
            WorkLeaseTicket(ticket.serial, ticket.epoch), p,
            now_ms=1010, owner_approved=True,
        )
    with pytest.raises(TypeError):
        HostOwnedOptionalGPUWorkers(leases, object())
    unrelated = RealtimeGPUWorkLeases()
    with pytest.raises(TypeError):
        HostOwnedOptionalGPUWorkers(unrelated, bridge)


def test_healthy_worker_is_never_terminated_or_mistaken_for_success():
    leases, ticket, p, _, bridge, host = fixture()
    host.enable(owner_approved=True)
    assert host.enroll_spawned(ticket, p, now_ms=1010, owner_approved=True)
    assert bridge.is_pinned(ticket)
    report = host.tick(now_ms=1050)
    assert report.owned_workers == 1
    assert report.stop_requests_sent == report.exits_confirmed == 0
    assert not report.authorizes_execution
    assert not report.authorizes_gameplay
    assert not report.authorizes_broadcast
    assert p.stop_requests == 0
    assert leases.metrics()["outstanding_claims"] == 1


def test_pressure_sends_exactly_one_stop_request_and_waits_for_actual_exit():
    leases, ticket, p, _, bridge, host = fixture()
    host.enable(owner_approved=True)
    assert host.enroll_spawned(ticket, p, now_ms=1010, owner_approved=True)
    assert leases.observe(sample(1100, free=700))
    a = host.tick(now_ms=1100)
    assert (a.stop_requests_sent, a.exits_confirmed) == (1, 0)
    assert p.stop_requests == 1
    assert leases.metrics()["outstanding_claims"] == 1
    b = host.tick(now_ms=1150)
    assert b.stop_requests_sent == 0
    assert p.stop_requests == 1
    p.code = -15
    c = host.tick(now_ms=1190)
    assert c.exits_confirmed == 1
    assert c.owned_workers == 0
    assert leases.metrics()["outstanding_claims"] == 0
    assert not bridge.is_pinned(ticket)


def test_binding_failure_quarantines_and_stops_original_host_process():
    leases, ticket, p, witness, bridge, host = fixture()
    witness.throw = True
    host.enable(owner_approved=True)
    assert not host.enroll_spawned(ticket, p, now_ms=1010, owner_approved=True)
    assert host.metrics()["quarantined_unbound"] == 1
    assert not bridge.is_pinned(ticket)
    assert host.tick(now_ms=1020).stop_requests_sent == 1
    assert leases.metrics()["outstanding_claims"] == 1
    p.code = -1
    assert host.tick(now_ms=1030).exits_confirmed == 1
    assert leases.metrics()["outstanding_claims"] == 0


def test_identity_uncertainty_stops_only_our_original_handle_not_foreign_pid():
    leases, ticket, p, witness, _, host = fixture()
    host.enable(owner_approved=True)
    assert host.enroll_spawned(ticket, p, now_ms=1010, owner_approved=True)
    witness.born += 100
    assert host.tick(now_ms=1100).stop_requests_sent == 1
    assert p.stop_requests == 1
    assert leases.metrics()["enabled"] is False
    assert leases.metrics()["outstanding_claims"] == 1
    p.code = -15
    assert host.tick(now_ms=1200).exits_confirmed == 1


def test_disable_revokes_without_freeing_a_running_worker():
    leases, ticket, p, _, _, host = fixture()
    host.enable(owner_approved=True)
    assert host.enroll_spawned(ticket, p, now_ms=1010, owner_approved=True)
    host.disable()
    assert host.tick(now_ms=1020).stop_requests_sent == 1
    assert leases.metrics()["outstanding_claims"] == 1
    assert not host.metrics()["enabled"]
    with pytest.raises(RuntimeError):
        host.enable(owner_approved=True)
    p.code = 0
    assert host.tick(now_ms=1030).exits_confirmed == 1
    host.enable(owner_approved=True)


def test_early_process_exit_releases_without_fake_start_evidence():
    leases, ticket, p, _, bridge, host = fixture()
    p.code = 0
    host.enable(owner_approved=True)
    assert host.enroll_spawned(ticket, p, now_ms=1010, owner_approved=True)
    assert leases.metrics()["started"] == 0
    assert leases.metrics()["released"] == 1
    assert not bridge.is_pinned(ticket)
    assert host.metrics()["owned_workers"] == 0


def test_uncertain_poll_fails_closed_without_any_termination():
    leases, ticket, p, _, _, host = fixture()
    host.enable(owner_approved=True)
    assert host.enroll_spawned(ticket, p, now_ms=1010, owner_approved=True)
    p.raise_poll = True
    report = host.tick(now_ms=1040)
    assert report.uncertain_workers == 1
    assert p.stop_requests == 0
    assert leases.metrics()["outstanding_claims"] == 1
    assert leases.metrics()["enabled"] is False


def test_terminate_error_is_not_retried_or_counted_as_stopped():
    leases, ticket, p, _, _, host = fixture()
    host.enable(owner_approved=True)
    assert host.enroll_spawned(ticket, p, now_ms=1010, owner_approved=True)
    assert leases.observe(sample(1100, free=700))
    p.raise_stop = True
    assert host.tick(now_ms=1100).uncertain_workers == 1
    assert p.stop_requests == 1
    assert host.tick(now_ms=1150).stop_requests_sent == 0
    assert p.stop_requests == 1
    assert leases.metrics()["outstanding_claims"] == 1


def test_non_windows_never_sends_process_termination():
    leases, ticket, p, _, _, host = fixture(os="Linux")
    with pytest.raises(RuntimeError):
        host.enable(owner_approved=True)
    assert p.stop_requests == 0
    assert leases.metrics()["outstanding_claims"] == 1


def test_duplicate_pid_and_handle_are_rejected():
    leases, ticket, p, _, _, host = fixture()
    host.enable(owner_approved=True)
    assert host.enroll_spawned(ticket, p, now_ms=1010, owner_approved=True)
    with pytest.raises(ValueError):
        host.enroll_spawned(ticket, p, now_ms=1020, owner_approved=True)


def test_bridge_exact_ticket_pinning_blocks_forged_ticket():
    _, ticket, p, _, bridge, host = fixture()
    host.enable(owner_approved=True)
    assert host.enroll_spawned(ticket, p, now_ms=1010, owner_approved=True)
    assert not bridge.is_pinned(WorkLeaseTicket(ticket.serial, ticket.epoch))
    with pytest.raises(TypeError):
        bridge.is_pinned(object())
