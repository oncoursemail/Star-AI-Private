"""Offline, deterministic tests of pinned Windows GPU observation; no GPU required."""

from pathlib import Path
import subprocess

import pytest

from star.stream_admission import StreamHealthSample
from star.stream_budget import StreamTelemetry
from star.stream_realtime_gpu_leases import RealtimeGPUWorkLeases
from star.stream_windows_gpu_probe import (
    GPUProbeUnavailable,
    WindowsGPUHealthObserver,
    WindowsNVIDIAMemoryProbe,
)

UUID = "GPU-3fa85f64-5717-4562-b3fc-2c963f66afa6"


def health(now=1100, *, verified=True, free=7000, total=8192):
    return StreamHealthSample(
        now,
        StreamTelemetry(
            live=False,
            game_active=False,
            free_vram_mib=free,
            total_vram_mib=total,
            game_fps=60,
            speech_backlog_ms=0,
        ),
        0,
        0,
        verified,
    )


def rig(tmp_path, *, stdout=None, returncode=0, error=None, os="Windows", clock=1100.0):
    binary = tmp_path / "nvidia-smi.exe"
    binary.write_bytes(b"fixture: never executed")
    calls = []

    def run(argv, **kw):
        calls.append((argv, kw))
        if error is not None:
            raise error
        return subprocess.CompletedProcess(
            argv,
            returncode,
            stdout if stdout is not None else f"{UUID}, 8192, 6600\n",
            "",
        )

    probe = WindowsNVIDIAMemoryProbe(
        binary,
        UUID,
        system_name=lambda: os,
        run=run,
        monotonic_ms=lambda: clock,
    )
    return probe, calls, binary


def test_pinned_device_safe_exact_arguments(tmp_path):
    probe, calls, binary = rig(tmp_path)
    result = probe.read()
    assert result.total_mib == 8192
    assert result.free_mib == 6600
    assert result.observed_ms == 1100
    assert len(calls) == 1
    argv, options = calls[0]
    assert argv == [
        str(binary),
        "--query-gpu=uuid,memory.total,memory.free",
        "--format=csv,noheader,nounits",
        f"--id={UUID}",
    ]
    assert options["shell"] is False
    assert options["timeout"] <= 2
    assert options["capture_output"] is True
    assert options["stdin"] == subprocess.DEVNULL


def test_owner_must_pin_absolute_executable_and_gpu_uuid(tmp_path):
    p, _, binary = rig(tmp_path)
    with pytest.raises(ValueError):
        WindowsNVIDIAMemoryProbe(Path("nvidia-smi.exe"), UUID)
    with pytest.raises(ValueError):
        WindowsNVIDIAMemoryProbe(binary, "0")
    with pytest.raises(ValueError):
        WindowsNVIDIAMemoryProbe(binary, "GPU-anything;rm -rf")
    with pytest.raises(ValueError):
        WindowsNVIDIAMemoryProbe(binary, UUID, timeout_seconds=0.01)
    with pytest.raises(ValueError):
        WindowsNVIDIAMemoryProbe(binary, UUID, timeout_seconds=float("nan"))
    link = tmp_path / "linked.exe"
    link.symlink_to(binary)
    with pytest.raises(ValueError):
        WindowsNVIDIAMemoryProbe(link, UUID)
    assert p.read().free_mib == 6600


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "NVIDIA-SMI has failed\n",
        f"{UUID}, 8192, N/A\n",
        f"{UUID}, 8192 MiB, 5000 MiB\n",
        f"{UUID}, 8192, 8193\n",
        f"{UUID}, 0, 0\n",
        f"{UUID}, -8192, 5000\n",
        f"{UUID}, 8192, 5000\n{UUID}, 8192, 6000\n",
        "GPU-deadbeef-dead-beef-dead-beefdeadbeef,8192,5000\n",
        f"{UUID}, 8192, 5000, extra\n",
        f"{UUID}, 8192, 5000\nwarning\n",
        "x" * 600,
    ],
)
def test_malformed_mismatched_or_ambiguous_output_never_accepted(tmp_path, stdout):
    probe, _, _ = rig(tmp_path, stdout=stdout)
    with pytest.raises(GPUProbeUnavailable):
        probe.read()


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError("binary disappeared"),
        PermissionError("blocked"),
        subprocess.TimeoutExpired(["nvidia-smi"], 0.9),
    ],
)
def test_timeout_and_os_failures_are_conservative(tmp_path, error):
    probe, _, _ = rig(tmp_path, error=error)
    with pytest.raises(GPUProbeUnavailable):
        probe.read()


def test_nonzero_exit_or_non_windows_denied(tmp_path):
    probe, _, _ = rig(tmp_path, returncode=1)
    with pytest.raises(GPUProbeUnavailable):
        probe.read()
    probe2, calls, _ = rig(tmp_path, os="Linux")
    with pytest.raises(GPUProbeUnavailable):
        probe2.read()
    assert not calls


@pytest.mark.parametrize("clock", [-1, float("nan"), float("inf"), 1e20])
def test_invalid_monotonic_clock(tmp_path, clock):
    probe, _, _ = rig(tmp_path, clock=clock)
    with pytest.raises(GPUProbeUnavailable):
        probe.read()


def test_broken_symlink_or_missing_executable_fails_before_launch(tmp_path):
    probe, calls, path = rig(tmp_path)
    path.unlink()
    with pytest.raises(GPUProbeUnavailable):
        probe.read()
    assert calls == []


def test_live_gpu_memory_overrides_host_guess_and_admits_with_headroom(tmp_path):
    probe, _, _ = rig(tmp_path)
    leases = RealtimeGPUWorkLeases()
    leases.enable(owner_approved=True)
    observer = WindowsGPUHealthObserver(probe, leases)
    assert observer.observe(health(free=700)).accepted
    admitted = leases.reserve(
        kind="vision",
        vram_mib=500,
        now_ms=1100,
        host_verified=True,
    )
    assert admitted.ticket is not None
    assert admitted.available_mib_after_claim == 6600 - 500


def test_actual_low_vram_blocks_optional_worker_even_if_host_signals_guess_high(tmp_path):
    probe, _, _ = rig(tmp_path, stdout=f"{UUID}, 8192, 400\n")
    leases = RealtimeGPUWorkLeases()
    leases.enable(owner_approved=True)
    observer = WindowsGPUHealthObserver(probe, leases)
    result = observer.observe(health(free=7900))
    assert result.accepted and not result.authorizes_execution
    advice = leases.reserve(
        kind="vision",
        vram_mib=200,
        now_ms=1100,
        host_verified=True,
    )
    assert advice.ticket is None
    assert leases.metrics()["outstanding_claims"] == 0


def test_unverified_host_signals_disable_optional_admission_without_polling(tmp_path):
    probe, calls, _ = rig(tmp_path)
    leases = RealtimeGPUWorkLeases()
    leases.enable(owner_approved=True)
    observer = WindowsGPUHealthObserver(probe, leases)
    res = observer.observe(health(verified=False))
    assert not res.accepted
    assert not calls
    assert not leases.metrics()["enabled"]


def test_clock_skew_disables_optional_admission(tmp_path):
    probe, _, _ = rig(tmp_path, clock=2800)
    leases = RealtimeGPUWorkLeases()
    leases.enable(owner_approved=True)
    observer = WindowsGPUHealthObserver(probe, leases)
    res = observer.observe(health())
    assert not res.accepted
    assert not leases.metrics()["enabled"]


def test_probe_failure_revokes_existing_worker_without_releasing_claim(tmp_path):
    data = {"stdout": f"{UUID}, 8192, 6600\n"}
    binary = tmp_path / "nvidia-smi.exe"
    binary.write_bytes(b"fixed")
    now = {"ms": 1100.0}

    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0, data["stdout"], "")

    probe = WindowsNVIDIAMemoryProbe(
        binary,
        UUID,
        system_name=lambda: "Windows",
        run=run,
        monotonic_ms=lambda: now["ms"],
    )
    leases = RealtimeGPUWorkLeases()
    leases.enable(owner_approved=True)
    observer = WindowsGPUHealthObserver(probe, leases)
    assert observer.observe(health()).accepted
    ticket = leases.reserve(
        kind="vision",
        vram_mib=500,
        now_ms=1100,
        host_verified=True,
    ).ticket
    assert ticket is not None
    data["stdout"] = "not a GPU record"
    now["ms"] = 1200.0
    result = observer.observe(health(1200))
    assert not result.accepted
    assert leases.metrics()["outstanding_claims"] == 1
    assert leases.poll(now_ms=1200) == (ticket,)
    assert not leases.metrics()["enabled"]
    assert not leases.release(ticket, host_confirms_worker_stopped=False)
    assert leases.release(ticket, host_confirms_worker_stopped=True)


def test_disabled_ledger_cannot_be_activated_by_gpu_poll(tmp_path):
    probe, _, _ = rig(tmp_path)
    leases = RealtimeGPUWorkLeases()
    res = WindowsGPUHealthObserver(probe, leases).observe(health())
    assert not res.accepted
    assert not leases.metrics()["enabled"]


def test_host_sample_live_and_obs_pressure_are_not_silently_erased(tmp_path):
    probe, _, _ = rig(tmp_path)
    leases = RealtimeGPUWorkLeases()
    leases.enable(owner_approved=True)
    local = StreamHealthSample(
        1100,
        StreamTelemetry(True, True, 7000, 8192, 30, 400),
        5,
        2,
        True,
    )
    assert WindowsGPUHealthObserver(probe, leases).observe(local).accepted
    assert (
        leases.reserve(
            kind="vision",
            vram_mib=200,
            now_ms=1100,
            host_verified=True,
        ).ticket
        is None
    )
