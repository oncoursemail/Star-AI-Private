"""Offline memory-pressure tests: no real model launches or OS mutations."""
from __future__ import annotations

from dataclasses import replace

import pytest

from star.memory_stall_guard import (
    MemoryStallGuard, MemoryStallSample, _read_psi, _read_swap,
    read_linux_stall_sample,
)
from star.stream_brain_governor import StreamBrainGovernor
from star.stream_hardware_telemetry import RealtimeTelemetryHost
from star.stream_qos import AdaptiveQoS, InferenceJob
from star.stream_stage import StarStage


def sample(
    ms=1000, *, some=0.0, full=0.0, some_us=1_000_000,
    full_us=200_000, sin=2_000_000, sout=2_000_000,
):
    return MemoryStallSample(ms, some, full, some_us, full_us, sin, sout)


def healthy(guard):
    assert guard.observe(sample())
    assert not guard.advise("training", now_ms=1000).allowed
    assert guard.observe(sample(2000))
    assert guard.advise("training", now_ms=2000).allowed


PSI = ("some avg10=0.00 avg60=0.00 avg300=0.00 total=1000000\n"
       "full avg10=0.00 avg60=0.00 avg300=0.00 total=200000\n")
SWAP = "pgpgin 435\npswpin 2000000\npswpout 2000000\n"


def test_parser_is_strict_and_handles_real_kernel_layout(tmp_path):
    psi = tmp_path / "psi"
    vmstat = tmp_path / "vmstat"
    psi.write_text(PSI)
    vmstat.write_text(SWAP)
    out = read_linux_stall_sample(
        clock_ms=lambda: 2000, psi_path=str(psi), vmstat_path=str(vmstat),
    )
    assert out == sample(2000)
    assert _read_psi(PSI) == (0.0, 0.0, 1_000_000, 200_000)
    assert _read_swap(SWAP) == (2_000_000, 2_000_000)


@pytest.mark.parametrize("invalid", [
    "", "some avg10=1.0 avg60=0 avg300=0 total=10\n",
    PSI + PSI.splitlines()[0] + "\n",
    PSI.replace("avg10=0.00", "avg10=nan", 1),
    PSI.replace("avg10=0.00", "avg10=101.00", 1),
    PSI.replace("some avg10", "noise avg10", 1),
    PSI.replace("total=200000", "total=-1"),
    PSI.replace("avg60=0.00", "avg60=abc\nxxx=1", 1),
])
def test_malformed_psi_never_invents_headroom(tmp_path, invalid):
    psi = tmp_path / "psi"
    vmstat = tmp_path / "vmstat"
    psi.write_text(invalid)
    vmstat.write_text(SWAP)
    assert read_linux_stall_sample(
        psi_path=str(psi), vmstat_path=str(vmstat),
    ) is None


@pytest.mark.parametrize("invalid", [
    "", "pswpin 2\n", "pswpin 1\npswpin 2\npswpout 1\n",
    "pswpin -1\npswpout 0\n", "pswpin a\npswpout 0\n",
])
def test_missing_swap_activity_counters_fail_closed(tmp_path, invalid):
    psi = tmp_path / "psi"
    swap = tmp_path / "vmstat"
    psi.write_text(PSI)
    swap.write_text(invalid)
    assert read_linux_stall_sample(
        psi_path=str(psi), vmstat_path=str(swap),
    ) is None


def test_guard_off_by_default_and_stale_background_denied():
    guard = MemoryStallGuard()
    assert not guard.observe(sample())
    assert not guard.advise("training", now_ms=1000).allowed
    assert guard.advise("speech", now_ms=1000).allowed
    assert guard.advise("commentary", now_ms=1000).allowed
    with pytest.raises(PermissionError):
        guard.enable()
    guard.enable(owner_approved=True)
    healthy(guard)
    assert guard.advise("research", now_ms=5001).reason == "pressure_sample_stale"
    assert guard.advise("vision", now_ms=1500).reason == "pressure_clock_regression"
    guard.disable()
    assert not guard.advise("render", now_ms=2500).allowed


def test_occupied_swap_does_not_mean_active_swap_thrash():
    guard = MemoryStallGuard()
    guard.enable(owner_approved=True)
    healthy(guard)  # 2M cumulative pages swapped in and out: no activity.
    assert guard.status()["state"] == "healthy"
    assert guard.advise("training", now_ms=2050).swap_pages_per_second == 0


@pytest.mark.parametrize("hot", [
    sample(3000, some=7.0),  # PSI recent partial stalls
    sample(3000, full=1.2),  # PSI recent total stalls
    sample(3000, some_us=1_150_000),  # delta: 7.5% of last two seconds
    sample(3000, full_us=224_000),  # delta: 1.2% full
    sample(3000, some=0.5, sin=2_002_000),  # active swap + PSI
])
def test_any_real_stall_blocks_new_optional_jobs(hot):
    guard = MemoryStallGuard()
    guard.enable(owner_approved=True)
    healthy(guard)
    assert guard.observe(hot)
    assert guard.status()["state"] == "pressured"
    assert not guard.advise("research", now_ms=3000).allowed
    assert not guard.advise("vision", now_ms=3000).allowed
    assert guard.advise("speech", now_ms=3000).allowed


def test_swap_churn_without_stalls_is_not_automatically_bad():
    guard = MemoryStallGuard()
    guard.enable(owner_approved=True)
    healthy(guard)
    assert guard.observe(sample(3000, sin=2_100_000))
    assert guard.advise("training", now_ms=3000).allowed


def test_stall_hysteresis_three_distinct_good_windows():
    guard = MemoryStallGuard()
    guard.enable(owner_approved=True)
    healthy(guard)
    assert guard.observe(sample(3000, some=9))
    for n in (4000, 5000):
        assert guard.observe(sample(n))
        assert not guard.advise("training", now_ms=n).allowed
    assert guard.observe(sample(6000))
    assert guard.advise("training", now_ms=6000).allowed


def test_bad_kernel_poll_does_not_unlatch_prior_stall():
    guard = MemoryStallGuard()
    guard.enable(owner_approved=True)
    healthy(guard)
    guard.observe(sample(3000, some=9))
    assert not guard.observe(None)
    assert not guard.advise("research", now_ms=3200).allowed
    assert guard.observe(sample(4000))  # baseline only, not recovery evidence
    assert not guard.advise("research", now_ms=4000).allowed
    for stamp in (5000, 6000):
        assert guard.observe(sample(stamp))
        assert not guard.advise("training", now_ms=stamp).allowed
    assert guard.observe(sample(7000))
    assert guard.advise("training", now_ms=7000).allowed


def test_counter_regression_and_fast_duplicate_cannot_reset_hot_latch():
    guard = MemoryStallGuard()
    guard.enable(owner_approved=True)
    healthy(guard)
    guard.observe(sample(3000, full=2.0))
    assert not guard.observe(sample(3100))  # <200ms
    assert not guard.advise("training", now_ms=3100).allowed
    assert not guard.observe(sample(4000, sin=0))  # counter regression
    assert not guard.advise("training", now_ms=4000).allowed
    assert guard.observe(sample(5000, sin=0))  # new baseline interval
    assert not guard.advise("training", now_ms=5000).allowed


@pytest.mark.parametrize("field,value", [
    ("some_avg10_pct", float("nan")), ("full_avg10_pct", 101),
    ("sampled_ms", True), ("swap_in_pages", -1),
    ("some_total_us", 1), ("full_total_us", 2_000_000),
])
def test_untrusted_or_corrupted_counter_values_rejected(field, value):
    with pytest.raises(ValueError):
        replace(sample(), **{field: value})


def test_invalid_thresholds_and_unsupported_job_names():
    with pytest.raises(ValueError):
        MemoryStallGuard(max_age_ms=100)
    with pytest.raises(ValueError):
        MemoryStallGuard(recovery_samples=1)
    with pytest.raises(ValueError):
        MemoryStallGuard(some_limit_pct=float("nan"))
    with pytest.raises(ValueError):
        MemoryStallGuard().advise("arbitrary_action", now_ms=1000)


def test_real_linux_read_only_sample_if_supported():
    result = read_linux_stall_sample()
    if result is None:
        pytest.skip("Linux PSI/vmstat unavailable in this environment")
    assert result.sampled_ms > 0
    assert 0 <= result.full_avg10_pct <= 100


def test_governor_rejects_background_without_psi_but_not_speech():
    now = [1000.0]
    cpu = [[100, 1000]]

    def cpu_read():
        return tuple(cpu[0])

    hardware = RealtimeTelemetryHost(
        gpu_probe=lambda: {"vram_total_mib": 8192, "vram_used_mib": 1024},
        memory_probe=lambda: (32768, 25000),
        cpu_probe=cpu_read, clock_ms=lambda: now[0],
    )
    guard = MemoryStallGuard()
    guard.enable(owner_approved=True)
    qos = AdaptiveQoS()
    stage = StarStage(clock=lambda: now[0] / 1000)
    brain = StreamBrainGovernor(
        telemetry=hardware, qos=qos, stage=stage,
        clock_ms=lambda: now[0], memory_guard=guard,
    )
    brain.enable(owner_approved=True, live=False, game_active=False)

    assert hardware.refresh_hardware()
    now[0] += 500
    cpu[0][0] += 10
    cpu[0][1] += 100
    assert hardware.refresh_hardware()

    def job(name, kind):
        return InferenceJob(name, kind, now[0], now[0] + 5000, 128, 128, "cpu")

    denial = brain.admit(job("r0", "research"))
    assert denial.reason == "pressure_guard_unavailable"
    assert qos.status()["inflight"] == 0

    speech = brain.admit(job("v0", "speech"))
    assert speech.admitted and speech.lease is not None
    assert brain.acknowledge_worker_stopped(
        speech.lease, worker_stopped=True, succeeded=True
    )

    assert guard.observe(sample(1500))
    assert guard.observe(sample(2000))
    now[0] = 2000
    cpu[0][0] += 10
    cpu[0][1] += 100
    assert hardware.refresh_hardware()
    accepted = brain.admit(job("r1", "research"))
    assert accepted.admitted and accepted.lease is not None
    assert brain.acknowledge_worker_stopped(
        accepted.lease, worker_stopped=True, succeeded=True
    )

    guard.observe(sample(3000, some=10))
    now[0] = 3000
    cpu[0][0] += 10
    cpu[0][1] += 100
    assert hardware.refresh_hardware()
    denial = brain.admit(job("r2", "research"))
    assert denial.reason == "memory_stall_pressured"
    assert qos.status()["inflight"] == 0
    assert brain.admit(job("v2", "speech")).admitted
