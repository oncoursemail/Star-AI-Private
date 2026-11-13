from __future__ import annotations

import pytest

from star.stream_load_governor import GovernorPolicy, StreamLoadGovernor, StreamSample
from star.stream_workload_admission import (
    ResourceBudget,
    ResourceVector,
    WorkloadAdmissionController,
)
from star.stream_workload_runtime import StreamWorkloadRuntime
from star.voice.incremental_thinking import ThinkAction, ThinkDirective
from star.voice.incremental_think_admission import IncrementalThinkAdmissionBridge
from star.voice.think_resource_profile import ThinkResourceProfile

FINGERPRINT = "a" * 64


def measurements() -> tuple[ResourceVector, ...]:
    return tuple(ResourceVector(100 + index, 200 + index, 80 + index) for index in range(8))


def make_profile(
    *,
    calibrated_ms: int = 1000,
    max_age_ms: int = 10_000,
    fingerprint: str = FINGERPRINT,
) -> ThinkResourceProfile:
    return ThinkResourceProfile.from_samples(
        measurements(),
        configuration_fingerprint=fingerprint,
        calibrated_monotonic_ms=calibrated_ms,
        trusted_host=True,
        safety_margin_percent=25,
        max_age_ms=max_age_ms,
    )


def make_runtime() -> StreamWorkloadRuntime:
    admission = WorkloadAdmissionController(
        ResourceBudget(
            capacity=ResourceVector(1000, 4096, 1024),
            realtime_reserve=ResourceVector(600, 2048, 512),
        ),
        lease_ttl_ms=60_000,
    )
    governor = StreamLoadGovernor(GovernorPolicy(recover_windows=1))
    runtime = StreamWorkloadRuntime(admission, governor)
    runtime.observe(
        StreamSample(
            seq=1,
            captured_ms=1000,
            streaming=True,
            gaming=True,
            game_fps_p10=60.0,
            voice_p95_ms=100.0,
            obs_dropped_pct=0.0,
            vram_free_mb=4096,
            audio_underruns=0,
        ),
        now_monotonic_ms=1000,
        trusted_host=True,
    )
    return runtime


def start_directive() -> ThinkDirective:
    return ThinkDirective(
        action=ThinkAction.START,
        utterance_id="calibration-turn",
        revision=0,
        stable_prefix="I want to build a small Roblox game",
        reason="stable_semantic_prefix",
    )


def make_bridge(
    runtime: StreamWorkloadRuntime,
    profile: ThinkResourceProfile,
    *,
    expected_fingerprint: str = FINGERPRINT,
) -> IncrementalThinkAdmissionBridge:
    return IncrementalThinkAdmissionBridge(
        runtime,
        resource_profile=profile,
        configuration_fingerprint=expected_fingerprint,
    )


def test_profile_uses_per_dimension_high_water_plus_ceiling_margin() -> None:
    profile = make_profile()
    assert profile.sample_count == 8
    assert profile.resources == ResourceVector(134, 259, 109)
    assert profile.safety_margin_percent == 25


def test_profile_rejects_fewer_than_eight_samples() -> None:
    with pytest.raises(ValueError, match="8..4096"):
        ThinkResourceProfile.from_samples(
            measurements()[:7],
            configuration_fingerprint=FINGERPRINT,
            calibrated_monotonic_ms=1000,
            trusted_host=True,
        )


def test_profile_rejects_non_vector_measurements() -> None:
    samples = list(measurements())
    samples[-1] = object()  # type: ignore[list-item]
    with pytest.raises(TypeError, match="every calibration sample"):
        ThinkResourceProfile.from_samples(
            samples,
            configuration_fingerprint=FINGERPRINT,
            calibrated_monotonic_ms=1000,
            trusted_host=True,
        )


def test_profile_requires_explicit_trusted_host_assertion() -> None:
    with pytest.raises(PermissionError, match="trusted host"):
        ThinkResourceProfile.from_samples(
            measurements(),
            configuration_fingerprint=FINGERPRINT,
            calibrated_monotonic_ms=1000,
            trusted_host=False,
        )


def test_profile_rejects_malformed_configuration_fingerprint() -> None:
    with pytest.raises(ValueError, match="SHA-256"):
        ThinkResourceProfile.from_samples(
            measurements(),
            configuration_fingerprint="not-a-fingerprint",
            calibrated_monotonic_ms=1000,
            trusted_host=True,
        )


def test_profile_rejects_resource_envelope_overflow() -> None:
    samples = tuple(ResourceVector(900_000_000, 0, 0) for _ in range(8))
    with pytest.raises(ValueError, match="exceeds supported bounds"):
        ThinkResourceProfile.from_samples(
            samples,
            configuration_fingerprint=FINGERPRINT,
            calibrated_monotonic_ms=1000,
            trusted_host=True,
            safety_margin_percent=25,
        )


def test_profile_rejects_invalid_margin_and_age() -> None:
    with pytest.raises(ValueError, match="safety_margin_percent"):
        ThinkResourceProfile.from_samples(
            measurements(),
            configuration_fingerprint=FINGERPRINT,
            calibrated_monotonic_ms=1000,
            trusted_host=True,
            safety_margin_percent=True,  # type: ignore[arg-type]
        )
    with pytest.raises(ValueError, match="max_age_ms"):
        ThinkResourceProfile.from_samples(
            measurements(),
            configuration_fingerprint=FINGERPRINT,
            calibrated_monotonic_ms=1000,
            trusted_host=True,
            max_age_ms=100,
        )


def test_profile_is_usable_only_for_matching_configuration() -> None:
    profile = make_profile()
    assert profile.resources_for(
        now_ms=1100,
        expected_configuration_fingerprint=FINGERPRINT,
    ) == profile.resources
    assert profile.resources_for(
        now_ms=1100,
        expected_configuration_fingerprint="b" * 64,
    ) is None


def test_profile_expires_instead_of_reusing_stale_measurements() -> None:
    profile = make_profile(max_age_ms=1000)
    assert profile.rejection_reason(
        now_ms=2001,
        expected_configuration_fingerprint=FINGERPRINT,
    ) == "profile_stale"
    assert profile.resources_for(
        now_ms=2001,
        expected_configuration_fingerprint=FINGERPRINT,
    ) is None


def test_future_dated_profile_fails_closed() -> None:
    profile = make_profile(calibrated_ms=2000)
    assert profile.rejection_reason(
        now_ms=1999,
        expected_configuration_fingerprint=FINGERPRINT,
    ) == "profile_from_future"
    assert profile.resources_for(
        now_ms=1999,
        expected_configuration_fingerprint=FINGERPRINT,
    ) is None


def test_profile_rejects_invalid_clock_and_expected_fingerprint() -> None:
    profile = make_profile()
    with pytest.raises(ValueError, match="monotonic"):
        profile.resources_for(
            now_ms=True,  # type: ignore[arg-type]
            expected_configuration_fingerprint=FINGERPRINT,
        )
    with pytest.raises(ValueError, match="SHA-256"):
        profile.resources_for(now_ms=1100, expected_configuration_fingerprint="bad")


def test_bridge_queues_the_calibrated_resource_envelope() -> None:
    runtime = make_runtime()
    profile = make_profile()
    bridge = make_bridge(runtime, profile)

    result = bridge.apply(start_directive(), now_ms=1100)
    assert result.status == "queued"

    leases = runtime.schedule(1100)
    assert len(leases) == 1
    launch = bridge.accept_lease(leases[0], now_ms=1100)
    assert launch is not None
    assert launch.lease.resources == profile.resources


def test_bridge_rejects_stale_profile_without_static_fallback() -> None:
    runtime = make_runtime()
    profile = make_profile(max_age_ms=1000)
    bridge = make_bridge(runtime, profile)

    result = bridge.apply(start_directive(), now_ms=2001)
    assert result.status == "rejected"
    assert result.reason == "resource_profile_stale_or_mismatched"
    assert runtime.schedule(2001) == ()
    assert bridge.metrics()["profile_unusable"] == 1


def test_bridge_rejects_configuration_mismatch_without_static_fallback() -> None:
    runtime = make_runtime()
    profile = make_profile()
    bridge = make_bridge(runtime, profile, expected_fingerprint="b" * 64)

    result = bridge.apply(start_directive(), now_ms=1100)
    assert result.status == "rejected"
    assert runtime.schedule(1100) == ()


def test_bridge_releases_granted_lease_if_profile_expires_before_launch() -> None:
    runtime = make_runtime()
    profile = make_profile(max_age_ms=1000)
    bridge = make_bridge(runtime, profile)

    assert bridge.apply(start_directive(), now_ms=1100).status == "queued"
    leases = runtime.schedule(1100)
    assert len(leases) == 1
    assert runtime.snapshot(1100).active == 1

    # The scheduler granted capacity, but no process has been launched yet.
    assert bridge.accept_lease(leases[0], now_ms=2101) is None
    assert runtime.snapshot(2101).active == 0
    assert bridge.metrics()["profile_unusable"] == 1


def test_bridge_requires_exactly_one_resource_source() -> None:
    runtime = make_runtime()
    with pytest.raises(ValueError, match="exactly one"):
        IncrementalThinkAdmissionBridge(runtime)
    with pytest.raises(ValueError, match="exactly one"):
        IncrementalThinkAdmissionBridge(
            runtime,
            resources=ResourceVector(1, 1, 1),
            resource_profile=make_profile(),
            configuration_fingerprint=FINGERPRINT,
        )
