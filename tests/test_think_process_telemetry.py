"""Offline tests for process-scoped thinker telemetry and calibration pairing."""
from dataclasses import fields
import os

import pytest

from star.voice.think_process_telemetry import (
    IncompleteProcessTelemetry,
    ProcessCounters,
    ProcessIdentity,
    ProcfsProcessReader,
    ThinkProcessWindowAccumulator,
    WindowsProcessReader,
    build_think_calibration_pair,
    parse_proc_stat,
    read_windows_process_counters,
    system_process_reader,
)

MIB = 1024 * 1024
FINGERPRINT = "a" * 64
EPOCH = "boot-2026-11-12"


def sample(*, cpu: int, ram_mib: int, gpu_mib: int | None,
           pid: int = 4321, start_token: int = 987654) -> ProcessCounters:
    return ProcessCounters(
        ProcessIdentity(pid, start_token),
        cpu,
        ram_mib * MIB,
        None if gpu_mib is None else gpu_mib * MIB,
    )


def make_window(*, sample_id: str, start_ms: int, end_ms: int,
                cpu_start: int, cpu_end: int, ram_mib: int,
                gpu_mib: int | None, identity: ProcessIdentity | None = None,
                epoch: str = EPOCH, fingerprint: str = FINGERPRINT):
    identity = identity or ProcessIdentity(4321, 987654)
    accumulator = ThinkProcessWindowAccumulator(
        sample_id=sample_id,
        identity=identity,
        clock_epoch=epoch,
        configuration_fingerprint=fingerprint,
        started_monotonic_ms=start_ms,
    )
    accumulator.observe(
        ProcessCounters(identity, cpu_start, ram_mib * MIB, None if gpu_mib is None else gpu_mib * MIB),
        at_ms=start_ms,
    )
    accumulator.observe(
        ProcessCounters(identity, cpu_end, ram_mib * MIB, None if gpu_mib is None else gpu_mib * MIB),
        at_ms=end_ms,
    )
    return accumulator.finalize(now_ms=end_ms)


def test_process_identity_rejects_bool_and_invalid_pid():
    with pytest.raises(ValueError):
        ProcessIdentity(True, 10)
    with pytest.raises(ValueError):
        ProcessIdentity(0, 10)
    with pytest.raises(ValueError):
        ProcessIdentity(10, 0)


def test_process_counters_reject_invalid_and_bool_values():
    identity = ProcessIdentity(10, 20)
    with pytest.raises(ValueError):
        ProcessCounters(identity, True, 1024, 0)
    with pytest.raises(ValueError):
        ProcessCounters(identity, 1, -1, 0)
    with pytest.raises(ValueError):
        ProcessCounters(identity, 1, 1024, False)


def test_window_computes_average_cpu_and_observed_memory_peaks():
    identity = ProcessIdentity(4321, 987654)
    accumulator = ThinkProcessWindowAccumulator(
        sample_id="baseline-1",
        identity=identity,
        clock_epoch=EPOCH,
        configuration_fingerprint=FINGERPRINT,
        started_monotonic_ms=1000,
    )
    accumulator.observe(sample(cpu=1_000_000, ram_mib=90, gpu_mib=180), at_ms=1000)
    accumulator.observe(sample(cpu=1_100_000, ram_mib=100, gpu_mib=200), at_ms=1050)
    accumulator.observe(sample(cpu=1_200_000, ram_mib=95, gpu_mib=190), at_ms=1100)
    result = accumulator.finalize(now_ms=1100)
    assert result.cpu_millicores == 200
    assert result.peak_working_set_bytes == 100 * MIB
    assert result.peak_gpu_memory_bytes == 200 * MIB
    assert result.sample_count == 3
    vector = result.to_resource_vector()
    assert (vector.cpu_millicores, vector.ram_mb, vector.vram_mb) == (200, 100, 200)


def test_cpu_millicores_can_exceed_one_core():
    result = make_window(
        sample_id="multi-core", start_ms=1000, end_ms=1100,
        cpu_start=0, cpu_end=2_000_000, ram_mib=50, gpu_mib=10,
    )
    assert result.cpu_millicores == 2000


def test_missing_gpu_is_unknown_not_zero_and_cannot_authorize_calibration():
    result = make_window(
        sample_id="no-gpu", start_ms=1000, end_ms=1100,
        cpu_start=0, cpu_end=100_000, ram_mib=50, gpu_mib=None,
    )
    assert result.peak_gpu_memory_bytes is None
    with pytest.raises(IncompleteProcessTelemetry):
        result.to_resource_vector()


def test_one_missing_gpu_sample_invalidates_the_whole_window():
    identity = ProcessIdentity(4321, 987654)
    accumulator = ThinkProcessWindowAccumulator(
        sample_id="partial-gpu", identity=identity, clock_epoch=EPOCH,
        configuration_fingerprint=FINGERPRINT, started_monotonic_ms=1000,
    )
    accumulator.observe(sample(cpu=0, ram_mib=50, gpu_mib=10), at_ms=1000)
    accumulator.observe(sample(cpu=100_000, ram_mib=55, gpu_mib=None), at_ms=1100)
    accumulator.observe(sample(cpu=200_000, ram_mib=60, gpu_mib=12), at_ms=1200)
    result = accumulator.finalize(now_ms=1200)
    assert result.peak_gpu_memory_bytes is None


def test_zero_gpu_is_a_valid_measured_value_when_provider_confirms_zero():
    result = make_window(
        sample_id="cpu-only", start_ms=1000, end_ms=1100,
        cpu_start=0, cpu_end=100_000, ram_mib=50, gpu_mib=0,
    )
    assert result.to_resource_vector().vram_mb == 0


def test_pid_reuse_or_worker_restart_is_rejected():
    identity = ProcessIdentity(4321, 987654)
    accumulator = ThinkProcessWindowAccumulator(
        sample_id="pid-reuse", identity=identity, clock_epoch=EPOCH,
        configuration_fingerprint=FINGERPRINT, started_monotonic_ms=1000,
    )
    accumulator.observe(sample(cpu=0, ram_mib=10, gpu_mib=10), at_ms=1000)
    replacement = ProcessCounters(ProcessIdentity(4321, 987655), 100_000, 11 * MIB, 11 * MIB)
    with pytest.raises(ValueError, match="identity changed"):
        accumulator.observe(replacement, at_ms=1100)


def test_cpu_counter_rollback_is_rejected():
    identity = ProcessIdentity(4321, 987654)
    accumulator = ThinkProcessWindowAccumulator(
        sample_id="cpu-rollback", identity=identity, clock_epoch=EPOCH,
        configuration_fingerprint=FINGERPRINT, started_monotonic_ms=1000,
    )
    accumulator.observe(sample(cpu=100, ram_mib=10, gpu_mib=10), at_ms=1000)
    with pytest.raises(ValueError, match="moved backwards"):
        accumulator.observe(sample(cpu=99, ram_mib=10, gpu_mib=10), at_ms=1100)


def test_duplicate_timestamp_and_large_sampling_gap_are_rejected():
    identity = ProcessIdentity(4321, 987654)
    accumulator = ThinkProcessWindowAccumulator(
        sample_id="bad-clock", identity=identity, clock_epoch=EPOCH,
        configuration_fingerprint=FINGERPRINT, started_monotonic_ms=1000,
    )
    accumulator.observe(sample(cpu=0, ram_mib=10, gpu_mib=10), at_ms=1000)
    with pytest.raises(ValueError, match="timestamps must increase"):
        accumulator.observe(sample(cpu=1, ram_mib=10, gpu_mib=10), at_ms=1000)
    with pytest.raises(IncompleteProcessTelemetry, match="sampling gap"):
        accumulator.observe(sample(cpu=1, ram_mib=10, gpu_mib=10), at_ms=2200)


def test_finalization_requires_fresh_observations_and_minimum_duration():
    identity = ProcessIdentity(4321, 987654)
    short = ThinkProcessWindowAccumulator(
        sample_id="short", identity=identity, clock_epoch=EPOCH,
        configuration_fingerprint=FINGERPRINT, started_monotonic_ms=1000,
    )
    short.observe(sample(cpu=0, ram_mib=10, gpu_mib=10), at_ms=1000)
    short.observe(sample(cpu=1, ram_mib=10, gpu_mib=10), at_ms=1050)
    with pytest.raises(ValueError, match="at least 100 ms"):
        short.finalize(now_ms=1050)

    stale = ThinkProcessWindowAccumulator(
        sample_id="stale", identity=identity, clock_epoch=EPOCH,
        configuration_fingerprint=FINGERPRINT, started_monotonic_ms=1000,
    )
    stale.observe(sample(cpu=0, ram_mib=10, gpu_mib=10), at_ms=1000)
    stale.observe(sample(cpu=100, ram_mib=10, gpu_mib=10), at_ms=1100)
    with pytest.raises(IncompleteProcessTelemetry, match="stale"):
        stale.finalize(now_ms=2200)


def test_window_capacity_and_abort_are_one_shot():
    identity = ProcessIdentity(4321, 987654)
    accumulator = ThinkProcessWindowAccumulator(
        sample_id="bounded", identity=identity, clock_epoch=EPOCH,
        configuration_fingerprint=FINGERPRINT, started_monotonic_ms=1000,
        max_samples=2,
    )
    accumulator.observe(sample(cpu=0, ram_mib=10, gpu_mib=10), at_ms=1000)
    accumulator.observe(sample(cpu=100, ram_mib=10, gpu_mib=10), at_ms=1100)
    with pytest.raises(OverflowError):
        accumulator.observe(sample(cpu=200, ram_mib=10, gpu_mib=10), at_ms=1200)

    assert accumulator.abort() is True
    assert accumulator.abort() is False
    with pytest.raises(RuntimeError):
        accumulator.finalize(now_ms=1200)


def test_pair_produces_incremental_resource_vector_for_existing_calibrator():
    baseline = make_window(
        sample_id="base", start_ms=1000, end_ms=1100,
        cpu_start=1_000_000, cpu_end=1_100_000,
        ram_mib=100, gpu_mib=200,
    )
    active = make_window(
        sample_id="active", start_ms=1200, end_ms=1300,
        cpu_start=1_200_000, cpu_end=1_500_000,
        ram_mib=150, gpu_mib=250,
    )
    pair = build_think_calibration_pair(
        sample_id="cal-1", sequence=1, baseline=baseline, active=active,
    )
    assert pair.cpu_delta == 200
    assert pair.ram_delta == 50
    assert pair.vram_delta == 50
    assert pair.incremental_resources.cpu_millicores == 200


def test_pair_rejects_process_lifetime_epoch_and_configuration_mismatch():
    baseline = make_window(
        sample_id="base", start_ms=1000, end_ms=1100,
        cpu_start=0, cpu_end=100_000, ram_mib=100, gpu_mib=100,
    )
    changed_pid = make_window(
        sample_id="pid-new", start_ms=1200, end_ms=1300,
        cpu_start=0, cpu_end=200_000, ram_mib=120, gpu_mib=120,
        identity=ProcessIdentity(4321, 999999),
    )
    with pytest.raises(ValueError, match="same process lifetime"):
        build_think_calibration_pair(sample_id="x", sequence=1, baseline=baseline, active=changed_pid)

    changed_epoch = make_window(
        sample_id="epoch-new", start_ms=1200, end_ms=1300,
        cpu_start=0, cpu_end=200_000, ram_mib=120, gpu_mib=120,
        epoch="boot-next",
    )
    with pytest.raises(ValueError, match="clock epoch"):
        build_think_calibration_pair(sample_id="x", sequence=1, baseline=baseline, active=changed_epoch)

    changed_config = make_window(
        sample_id="config-new", start_ms=1200, end_ms=1300,
        cpu_start=0, cpu_end=200_000, ram_mib=120, gpu_mib=120,
        fingerprint="b" * 64,
    )
    with pytest.raises(ValueError, match="inference configuration"):
        build_think_calibration_pair(sample_id="x", sequence=1, baseline=baseline, active=changed_config)


def test_pair_rejects_overlapping_windows_and_unavailable_gpu():
    baseline = make_window(
        sample_id="base", start_ms=1000, end_ms=1150,
        cpu_start=0, cpu_end=100_000, ram_mib=100, gpu_mib=100,
    )
    active_overlap = make_window(
        sample_id="overlap", start_ms=1100, end_ms=1200,
        cpu_start=0, cpu_end=200_000, ram_mib=120, gpu_mib=120,
    )
    with pytest.raises(ValueError, match="must not overlap"):
        build_think_calibration_pair(sample_id="x", sequence=1, baseline=baseline, active=active_overlap)

    active_unknown_gpu = make_window(
        sample_id="unknown", start_ms=1200, end_ms=1300,
        cpu_start=0, cpu_end=200_000, ram_mib=120, gpu_mib=None,
    )
    with pytest.raises(IncompleteProcessTelemetry):
        build_think_calibration_pair(sample_id="x", sequence=1, baseline=baseline, active=active_unknown_gpu)


def test_proc_stat_parser_handles_parentheses_in_process_name():
    tail = ["S"] + ["0"] * 21
    tail[11] = "20"      # utime
    tail[12] = "10"      # stime
    tail[19] = "12345"   # starttime
    tail[21] = "50"      # rss pages
    text = "123 (worker ) with parens) " + " ".join(tail)
    result = parse_proc_stat(123, text, page_size=4096, clock_ticks=100)
    assert result.identity == ProcessIdentity(123, 12345)
    assert result.cpu_time_100ns == 3_000_000
    assert result.working_set_bytes == 50 * 4096
    assert result.gpu_memory_bytes is None


def test_proc_stat_parser_rejects_wrong_pid_truncation_and_negative_values():
    with pytest.raises(ValueError, match="PID"):
        parse_proc_stat(123, "124 (worker) S", page_size=4096, clock_ticks=100)
    with pytest.raises(ValueError, match="truncated"):
        parse_proc_stat(123, "123 (worker) S 1", page_size=4096, clock_ticks=100)

    tail = ["S"] + ["0"] * 21
    tail[11] = "-1"
    tail[19] = "12345"
    tail[21] = "50"
    with pytest.raises(ValueError, match="negative"):
        parse_proc_stat(123, "123 (worker) " + " ".join(tail), page_size=4096, clock_ticks=100)


def test_procfs_reader_reads_only_explicit_pid(tmp_path):
    pid_dir = tmp_path / "321"
    pid_dir.mkdir()
    tail = ["S"] + ["0"] * 21
    tail[11] = "10"
    tail[12] = "5"
    tail[19] = "777"
    tail[21] = "25"
    (pid_dir / "stat").write_text("321 (star thinker) " + " ".join(tail), encoding="ascii")
    reader = ProcfsProcessReader(
        proc_root=tmp_path,
        page_size=4096,
        clock_ticks=100,
        gpu_memory_probe=lambda pid, start: 12 * MIB,
    )
    result = reader.read(321)
    assert result is not None
    assert result.identity == ProcessIdentity(321, 777)
    assert result.gpu_memory_bytes == 12 * MIB
    assert reader.read(999) is None


def test_gpu_provider_failure_is_unknown_not_a_zero_allocation():
    tail = ["S"] + ["0"] * 21
    tail[11] = "10"
    tail[19] = "777"
    tail[21] = "25"
    result = parse_proc_stat(
        321,
        "321 (worker) " + " ".join(tail),
        page_size=4096,
        clock_ticks=100,
        gpu_memory_probe=lambda pid, start: (_ for _ in ()).throw(OSError("provider down")),
    )
    assert result.gpu_memory_bytes is None


def test_windows_reader_is_inert_on_non_windows_and_factory_is_platform_specific():
    if os.name != "nt":
        assert read_windows_process_counters(123) is None
        assert WindowsProcessReader().read(123) is None
        assert isinstance(system_process_reader(), ProcfsProcessReader)


def test_process_telemetry_schema_contains_no_names_paths_or_command_lines():
    names = {item.name for item in fields(ProcessCounters)}
    assert names == {"identity", "cpu_time_100ns", "working_set_bytes", "gpu_memory_bytes"}
    assert not {"name", "path", "command_line", "username", "transcript"} & names
