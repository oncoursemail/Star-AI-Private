"""Offline lifecycle/race tests for the real asynchronous /proc polling host."""
from __future__ import annotations

import itertools
import threading
import time

import pytest

from star.memory_stall_guard import MemoryStallGuard, MemoryStallSample
from star.memory_stall_polling_host import MemoryPressurePollingHost


def until(condition, seconds=3.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(.008)
    return bool(condition())


def example(ms: float, *, some: float = 0.0) -> MemoryStallSample:
    return MemoryStallSample(
        ms, some, 0.0, 10_000_000, 2_000_000, 100, 100,
    )


def enabled_guard():
    guard = MemoryStallGuard(max_age_ms=1500)
    guard.enable(owner_approved=True)
    return guard


def test_requires_owner_and_enabled_guard():
    guard = MemoryStallGuard()
    host = MemoryPressurePollingHost(guard=guard)
    with pytest.raises(PermissionError):
        host.start()
    with pytest.raises(RuntimeError):
        host.start(owner_approved=True)
    assert not host.status().running
    assert host.status().polls == 0
    assert host.shutdown()


@pytest.mark.parametrize("bad", [0, .1, 3.0, float("nan"), True, "1"])
def test_rejects_unbounded_or_invalid_poll_intervals(bad):
    with pytest.raises((TypeError, ValueError)):
        MemoryPressurePollingHost(guard=enabled_guard(), interval_s=bad)


def test_rejects_unsupported_guard_or_reader():
    with pytest.raises(TypeError):
        MemoryPressurePollingHost(guard=object())
    with pytest.raises(TypeError):
        MemoryPressurePollingHost(guard=enabled_guard(), reader=None)


def test_periodic_sampler_arms_guard_then_shutdown_invalidates_it():
    guard = enabled_guard()
    serial = itertools.count()
    first = time.monotonic() * 1000

    def reader():
        return example(first + next(serial) * 300)

    host = MemoryPressurePollingHost(guard=guard, interval_s=.25, reader=reader)
    assert host.status().polls == 0
    assert not guard.advise("research", now_ms=first).allowed
    host.start(owner_approved=True)
    try:
        assert until(lambda: host.status().accepted >= 2)
        s = host.status()
        assert s.running and s.accepted >= 2
        assert guard.advise("training", now_ms=s.last_sample_ms).allowed
        assert guard.advise("speech", now_ms=s.last_sample_ms).allowed
        with pytest.raises(RuntimeError):
            host.start(owner_approved=True)
    finally:
        assert host.shutdown()
    assert not host.status().running
    assert not guard.advise("training", now_ms=host.status().last_sample_ms).allowed


def test_detects_hot_pressure_and_requires_independent_recovery_windows():
    guard = enabled_guard()
    first = time.monotonic() * 1000
    serial = itertools.count()

    def reader():
        i = next(serial)
        return example(first + i * 300, some=10.0 if i == 2 else 0.0)

    host = MemoryPressurePollingHost(guard=guard, interval_s=.25, reader=reader)
    host.start(owner_approved=True)
    try:
        assert until(lambda: host.status().polls >= 3)
        assert not guard.advise(
            "research", now_ms=host.status().last_sample_ms,
        ).allowed
        assert guard.status()["state"] == "pressured"
        assert until(lambda: host.status().polls >= 6)
        assert guard.advise(
            "research", now_ms=host.status().last_sample_ms,
        ).allowed
    finally:
        assert host.shutdown()


def test_reader_exception_fail_closed_then_recovers():
    guard = enabled_guard()
    first = time.monotonic() * 1000
    serial = itertools.count()

    def reader():
        i = next(serial)
        if i == 1:
            raise OSError("unavailable /proc")
        return example(first + i * 300)

    host = MemoryPressurePollingHost(guard=guard, interval_s=.25, reader=reader)
    host.start(owner_approved=True)
    try:
        assert until(lambda: host.status().polls >= 2)
        assert host.status().failed == 1
        assert not guard.advise(
            "training", now_ms=first + 300,
        ).allowed
        assert until(lambda: host.status().polls >= 4)
        assert guard.advise(
            "training", now_ms=host.status().last_sample_ms,
        ).allowed
    finally:
        assert host.shutdown()


def test_slow_reader_cannot_publish_after_shutdown():
    guard = enabled_guard()
    entered = threading.Event()
    release = threading.Event()

    def slow_reader():
        entered.set()
        release.wait(3)
        return example(time.monotonic() * 1000)

    host = MemoryPressurePollingHost(
        guard=guard, interval_s=.25, reader=slow_reader,
    )
    host.start(owner_approved=True)
    assert entered.wait(1.5)
    # Explicit bounded shutdown refuses to pretend the blocked worker exited.
    assert not host.shutdown(timeout_s=0)
    assert not guard.advise(
        "training", now_ms=time.monotonic() * 1000,
    ).allowed
    release.set()
    assert host.shutdown(timeout_s=2)
    assert host.status().polls == 0  # late observation was discarded
    assert not host.status().running


def test_real_linux_kernel_poll_one_session_when_supported():
    from star.memory_stall_guard import read_linux_stall_sample

    if read_linux_stall_sample() is None:
        pytest.skip("Linux PSI unavailable")
    guard = enabled_guard()
    host = MemoryPressurePollingHost(guard=guard, interval_s=.25)
    host.start(owner_approved=True)
    try:
        assert until(lambda: host.status().accepted >= 2)
        assert host.status().failed == 0
        assert host.status().last_sample_ms is not None
    finally:
        assert host.shutdown()

def test_connected_realtime_brain_admits_only_after_actual_poller_samples():
    """Exercise poller -> guard -> existing QoS/brain, no LLMs or OBS."""
    from star.stream_brain_governor import StreamBrainGovernor
    from star.stream_hardware_telemetry import RealtimeTelemetryHost
    from star.stream_qos import AdaptiveQoS, InferenceJob
    from star.stream_stage import StarStage

    now = [time.monotonic() * 1000]
    cpu = [[100, 1000]]

    hardware = RealtimeTelemetryHost(
        gpu_probe=lambda: {"vram_total_mib": 8192, "vram_used_mib": 1024},
        memory_probe=lambda: (32768, 25000),
        cpu_probe=lambda: tuple(cpu[0]), clock_ms=lambda: now[0],
    )
    guard = enabled_guard()
    qos = AdaptiveQoS()
    brain = StreamBrainGovernor(
        telemetry=hardware, qos=qos,
        stage=StarStage(clock=lambda: now[0] / 1000),
        clock_ms=lambda: now[0], memory_guard=guard,
    )
    brain.enable(owner_approved=True, live=False, game_active=False)
    assert hardware.refresh_hardware()
    cpu[0][0] += 10
    cpu[0][1] += 100
    now[0] += 500
    assert hardware.refresh_hardware()

    def job(number):
        return InferenceJob(
            number, "research", now[0], now[0] + 5000,
            128, 128, "cpu",
        )

    assert brain.admit(job("before")).reason == "pressure_guard_unavailable"
    serial = itertools.count()
    first = time.monotonic() * 1000

    def reader():
        return example(first + next(serial) * 300)

    host = MemoryPressurePollingHost(guard=guard, interval_s=.25, reader=reader)
    host.start(owner_approved=True)
    try:
        assert until(lambda: host.status().accepted >= 2)
        now[0] = max(now[0] + 500, host.status().last_sample_ms + 100)
        cpu[0][0] += 10
        cpu[0][1] += 100
        assert hardware.refresh_hardware()
        admitted = brain.admit(job("after"))
        assert admitted.admitted, admitted.reason
        assert admitted.lease is not None
        assert brain.acknowledge_worker_stopped(
            admitted.lease, worker_stopped=True, succeeded=True,
        )
    finally:
        assert host.shutdown()
    now[0] += 500
    cpu[0][0] += 10
    cpu[0][1] += 100
    assert hardware.refresh_hardware()
    assert brain.admit(job("stopped")).reason == "pressure_guard_unavailable"
    brain.disable()
