from __future__ import annotations

import pytest

from star.stream_workload_admission import (
    ResourceBudget,
    ResourceVector,
    WorkloadAdmissionController,
)
from star.stream_workload_runtime import StreamWorkloadRuntime
from star.voice.incremental_think_admission import IncrementalThinkAdmissionBridge
from star.voice.think_calibration import ThinkCalibrationPair, ThinkCalibrationSession
from star.voice.think_resource_profile import ThinkResourceProfile

FINGERPRINT = "a" * 64
EPOCH = "boot-2026-11-12-a"


def make_pair(
    sequence: int,
    *,
    baseline_ms: int | None = None,
    active_ms: int | None = None,
    sample_id: str | None = None,
    epoch: str = EPOCH,
    fingerprint: str = FINGERPRINT,
    baseline: ResourceVector | None = None,
    active: ResourceVector | None = None,
) -> ThinkCalibrationPair:
    base_at = baseline_ms if baseline_ms is not None else 1000 + (sequence - 1) * 2000
    active_at = active_ms if active_ms is not None else base_at + 500
    base = baseline or ResourceVector(100, 200, 300)
    measured = active or ResourceVector(200 + sequence, 400 + sequence, 600 + sequence)
    return ThinkCalibrationPair(
        sample_id=sample_id or f"sample-{sequence}",
        sequence=sequence,
        clock_epoch=epoch,
        configuration_fingerprint=fingerprint,
        baseline_monotonic_ms=base_at,
        active_monotonic_ms=active_at,
        baseline=base,
        active=measured,
    )


def make_session(*, min_samples: int = 8, max_samples: int = 64) -> ThinkCalibrationSession:
    return ThinkCalibrationSession(
        session_id="calibration-session",
        configuration_fingerprint=FINGERPRINT,
        clock_epoch=EPOCH,
        started_monotonic_ms=1000,
        min_samples=min_samples,
        max_samples=max_samples,
    )


def add_samples(session: ThinkCalibrationSession, count: int = 8) -> int:
    last_active = 0
    for sequence in range(1, count + 1):
        pair = make_pair(sequence)
        session.add(pair, now_ms=pair.active_monotonic_ms + 10, trusted_host=True)
        last_active = pair.active_monotonic_ms
    return last_active


def test_pair_computes_nonnegative_per_dimension_deltas() -> None:
    pair = make_pair(
        1,
        baseline=ResourceVector(100, 300, 100),
        active=ResourceVector(150, 250, 175),
    )
    assert pair.incremental_resources == ResourceVector(50, 0, 75)


def test_pair_rejects_no_incremental_resource_use() -> None:
    with pytest.raises(ValueError, match="positive incremental"):
        make_pair(
            1,
            baseline=ResourceVector(100, 200, 300),
            active=ResourceVector(100, 200, 300),
        )


def test_pair_rejects_invalid_identifier_sequence_and_fingerprint() -> None:
    with pytest.raises(ValueError, match="sample_id"):
        make_pair(1, sample_id="bad id")
    with pytest.raises(ValueError, match="sequence"):
        make_pair(0)
    with pytest.raises(ValueError, match="SHA-256"):
        make_pair(1, fingerprint="not-a-digest")


def test_pair_rejects_invalid_clock_window() -> None:
    with pytest.raises(ValueError, match="follow its baseline"):
        make_pair(1, baseline_ms=1000, active_ms=1000)
    with pytest.raises(ValueError, match="five minutes"):
        make_pair(1, baseline_ms=1000, active_ms=301001)
    with pytest.raises(ValueError, match="bounded monotonic"):
        make_pair(1, baseline_ms=True, active_ms=1500)  # type: ignore[arg-type]


def test_session_requires_trusted_host() -> None:
    session = make_session()
    pair = make_pair(1)
    with pytest.raises(PermissionError, match="trusted host"):
        session.add(pair, now_ms=pair.active_monotonic_ms + 10, trusted_host=False)


def test_session_rejects_mixed_clock_epoch() -> None:
    session = make_session()
    pair = make_pair(1, epoch="another-boot")
    with pytest.raises(ValueError, match="another host clock epoch"):
        session.add(pair, now_ms=pair.active_monotonic_ms + 10, trusted_host=True)


def test_session_rejects_mixed_inference_configuration() -> None:
    session = make_session()
    pair = make_pair(1, fingerprint="b" * 64)
    with pytest.raises(ValueError, match="another inference configuration"):
        session.add(pair, now_ms=pair.active_monotonic_ms + 10, trusted_host=True)


def test_session_rejects_duplicate_sample_id_and_nonincreasing_sequence() -> None:
    session = make_session()
    first = make_pair(1)
    session.add(first, now_ms=first.active_monotonic_ms + 10, trusted_host=True)
    duplicate = make_pair(2, sample_id=first.sample_id)
    with pytest.raises(ValueError, match="duplicate"):
        session.add(duplicate, now_ms=duplicate.active_monotonic_ms + 10, trusted_host=True)
    old_sequence = make_pair(1, sample_id="sample-replay", baseline_ms=3000, active_ms=3500)
    with pytest.raises(ValueError, match="sequence must increase"):
        session.add(old_sequence, now_ms=3510, trusted_host=True)


def test_session_rejects_overlapping_measurement_windows() -> None:
    session = make_session()
    first = make_pair(1, baseline_ms=1000, active_ms=2000)
    session.add(first, now_ms=2010, trusted_host=True)
    overlapping = make_pair(2, baseline_ms=1999, active_ms=2500)
    with pytest.raises(ValueError, match="must not overlap"):
        session.add(overlapping, now_ms=2510, trusted_host=True)


def test_session_rejects_future_stale_and_predating_samples() -> None:
    session = make_session()
    future = make_pair(1, baseline_ms=1000, active_ms=2000)
    with pytest.raises(ValueError, match="future-dated"):
        session.add(future, now_ms=1999, trusted_host=True)
    stale = make_pair(1, baseline_ms=1000, active_ms=2000)
    with pytest.raises(ValueError, match="stale"):
        session.add(stale, now_ms=32_001, trusted_host=True)
    predating = make_pair(1, baseline_ms=900, active_ms=1000)
    with pytest.raises(ValueError, match="predates"):
        session.add(predating, now_ms=1010, trusted_host=True)


def test_session_default_target_is_thirty_samples() -> None:
    session = ThinkCalibrationSession(
        session_id="default-session",
        configuration_fingerprint=FINGERPRINT,
        clock_epoch=EPOCH,
        started_monotonic_ms=1000,
    )
    assert session.summary(now_ms=1000)["minimum_samples"] == 30


def test_session_requires_minimum_samples_before_finalizing() -> None:
    session = make_session(min_samples=8)
    add_samples(session, 7)
    with pytest.raises(ValueError, match="insufficient paired"):
        session.finalize(now_ms=14_510)


def test_finalize_builds_high_water_profile_and_binds_epoch() -> None:
    session = make_session(min_samples=8)
    last_active = add_samples(session, 8)
    profile = session.finalize(now_ms=last_active + 10)
    assert profile.sample_count == 8
    assert profile.clock_epoch == EPOCH
    assert profile.resources == ResourceVector(135, 260, 385)
    assert profile.resources_for(
        now_ms=last_active + 11,
        expected_configuration_fingerprint=FINGERPRINT,
        expected_clock_epoch=EPOCH,
    ) == profile.resources


def test_epoch_bound_profile_rejects_missing_or_different_epoch() -> None:
    session = make_session(min_samples=8)
    last_active = add_samples(session, 8)
    profile = session.finalize(now_ms=last_active + 10)
    assert profile.rejection_reason(
        now_ms=last_active + 11,
        expected_configuration_fingerprint=FINGERPRINT,
    ) == "clock_epoch_required"
    assert profile.rejection_reason(
        now_ms=last_active + 11,
        expected_configuration_fingerprint=FINGERPRINT,
        expected_clock_epoch="boot-after-restart",
    ) == "clock_epoch_mismatch"


def test_session_rejects_stale_latest_sample_at_finalize() -> None:
    session = make_session(min_samples=8)
    last_active = add_samples(session, 8)
    with pytest.raises(ValueError, match="latest calibration sample is stale"):
        session.finalize(now_ms=last_active + 30_001)


def test_session_rejects_samples_after_maximum_duration() -> None:
    session = ThinkCalibrationSession(
        session_id="short-session",
        configuration_fingerprint=FINGERPRINT,
        clock_epoch=EPOCH,
        started_monotonic_ms=1000,
        min_samples=8,
        max_duration_ms=1000,
    )
    pair = make_pair(1)
    with pytest.raises(TimeoutError, match="maximum duration"):
        session.add(pair, now_ms=2001, trusted_host=True)


def test_session_enforces_capacity_and_closes_after_finalize() -> None:
    session = make_session(min_samples=8, max_samples=8)
    last_active = add_samples(session, 8)
    with pytest.raises(OverflowError, match="capacity"):
        pair = make_pair(9)
        session.add(pair, now_ms=pair.active_monotonic_ms + 10, trusted_host=True)
    session.finalize(now_ms=last_active + 10)
    with pytest.raises(RuntimeError, match="already closed"):
        pair = make_pair(9)
        session.add(pair, now_ms=pair.active_monotonic_ms + 10, trusted_host=True)


def test_abort_discards_samples_and_closes_session() -> None:
    session = make_session()
    add_samples(session, 2)
    assert session.abort() is True
    assert session.summary(now_ms=6000)["samples"] == 0
    assert session.abort() is False
    with pytest.raises(RuntimeError, match="already closed"):
        session.finalize(now_ms=6000)


def test_epoch_bound_bridge_requires_matching_clock_epoch() -> None:
    session = make_session(min_samples=8)
    last_active = add_samples(session, 8)
    profile = session.finalize(now_ms=last_active + 10)
    runtime = StreamWorkloadRuntime(
        WorkloadAdmissionController(
            ResourceBudget(capacity=ResourceVector(1000, 4096, 1024))
        )
    )
    with pytest.raises(ValueError, match="clock_epoch is required"):
        IncrementalThinkAdmissionBridge(
            runtime,
            resource_profile=profile,
            configuration_fingerprint=FINGERPRINT,
        )
    with pytest.raises(ValueError, match="must match"):
        IncrementalThinkAdmissionBridge(
            runtime,
            resource_profile=profile,
            configuration_fingerprint=FINGERPRINT,
            clock_epoch="wrong-boot",
        )
    bridge = IncrementalThinkAdmissionBridge(
        runtime,
        resource_profile=profile,
        configuration_fingerprint=FINGERPRINT,
        clock_epoch=EPOCH,
    )
    assert bridge.metrics()["queued"] == 0


def test_legacy_profile_remains_compatible_without_clock_epoch() -> None:
    profile = ThinkResourceProfile.from_samples(
        tuple(ResourceVector(10 + i, 20 + i, 30 + i) for i in range(8)),
        configuration_fingerprint=FINGERPRINT,
        calibrated_monotonic_ms=1000,
        trusted_host=True,
    )
    assert profile.clock_epoch is None
    assert profile.resources_for(
        now_ms=1001,
        expected_configuration_fingerprint=FINGERPRINT,
    ) == profile.resources
