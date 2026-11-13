"""Regression tests for STAR's conservative background resource admission policy."""

import pytest

from star.resource_admission import (
    AdmissionAction,
    AdmissionPolicy,
    ResourceSnapshot,
    WorkloadKind,
    WorkloadRequest,
)


def snapshot(**overrides):
    values = {
        "observed_at": 10.0,
        "cpu_percent": 20.0,
        "available_ram_mb": 8192,
        "available_vram_mb": 6144,
        "gpu_percent": 20.0,
        "game_active": False,
        "game_fps": None,
        "audio_underruns": 0,
        "obs_dropped_frames": 0,
        "obs_total_frames": 120,
        "window_seconds": 5.0,
    }
    values.update(overrides)
    return ResourceSnapshot(**values)


def request(**overrides):
    values = {
        "request_id": "background-1",
        "kind": WorkloadKind.BACKGROUND_REASONING,
        "estimated_cpu_percent": 10.0,
        "estimated_ram_mb": 1024,
        "estimated_vram_mb": 1024,
        "estimated_gpu_percent": 10.0,
    }
    values.update(overrides)
    return WorkloadRequest(**values)


def evaluate(req=None, sample=None, policy=None, now=10.5):
    return (policy or AdmissionPolicy()).evaluate(
        req or request(), sample or snapshot(), now_monotonic=now
    )


def test_admits_background_work_when_all_reserves_are_preserved():
    result = evaluate()
    assert result.action is AdmissionAction.ALLOW
    assert result.reason == "within_budget"
    assert result.retry_after_seconds is None


def test_cpu_only_work_does_not_require_gpu_telemetry():
    sample = snapshot(available_vram_mb=None, gpu_percent=None)
    req = request(estimated_vram_mb=0, estimated_gpu_percent=0)
    assert evaluate(req=req, sample=sample).action is AdmissionAction.ALLOW


@pytest.mark.parametrize(
    "kind",
    [
        WorkloadKind.FOREGROUND_INFERENCE,
        WorkloadKind.REALTIME_AUDIO,
        WorkloadKind.TTS_PLAYBACK,
        WorkloadKind.GAME_INPUT,
        WorkloadKind.OBS_CAPTURE,
    ],
)
def test_protected_workloads_are_routed_outside_background_gate(kind):
    bad_sample = snapshot(
        observed_at=0.0,
        cpu_percent=100.0,
        available_ram_mb=0,
        available_vram_mb=0,
        gpu_percent=100.0,
        game_active=True,
        game_fps=1.0,
        audio_underruns=10,
        obs_dropped_frames=20,
        obs_total_frames=120,
    )
    result = evaluate(req=request(kind=kind), sample=bad_sample, now=100.0)
    assert result.action is AdmissionAction.PROTECTED
    assert result.reason == "route_to_protected_lane"


def test_defers_stale_snapshot():
    result = evaluate(sample=snapshot(observed_at=1.0), now=10.0)
    assert result.action is AdmissionAction.DEFER
    assert result.reason == "stale_snapshot"
    assert result.retry_after_seconds == 2.0


def test_defers_snapshot_too_far_in_the_future():
    result = evaluate(sample=snapshot(observed_at=11.0), now=10.0)
    assert result.action is AdmissionAction.DEFER
    assert result.reason == "snapshot_from_future"


def test_defers_after_any_audio_underrun_in_the_measurement_window():
    result = evaluate(sample=snapshot(audio_underruns=1))
    assert result.action is AdmissionAction.DEFER
    assert result.reason == "audio_underrun_observed"


def test_defers_high_obs_drop_rate():
    result = evaluate(sample=snapshot(obs_dropped_frames=2, obs_total_frames=120))
    assert result.action is AdmissionAction.DEFER
    assert result.reason == "obs_drop_rate_high"


def test_defers_obs_drops_when_measurement_window_is_too_small():
    result = evaluate(sample=snapshot(obs_dropped_frames=1, obs_total_frames=30))
    assert result.action is AdmissionAction.DEFER
    assert result.reason == "obs_window_too_small"


def test_accepts_obs_drop_rate_at_or_below_threshold():
    result = evaluate(sample=snapshot(obs_dropped_frames=1, obs_total_frames=120))
    assert result.action is AdmissionAction.ALLOW


def test_defers_when_game_fps_is_unavailable_during_active_gameplay():
    result = evaluate(sample=snapshot(game_active=True, game_fps=None))
    assert result.action is AdmissionAction.DEFER
    assert result.reason == "game_fps_unavailable"


def test_defers_when_game_fps_is_below_floor():
    result = evaluate(sample=snapshot(game_active=True, game_fps=48.0))
    assert result.action is AdmissionAction.DEFER
    assert result.reason == "game_fps_below_floor"


def test_cpu_budget_includes_estimated_workload():
    result = evaluate(
        req=request(estimated_cpu_percent=70.0),
        sample=snapshot(cpu_percent=20.0),
    )
    assert result.action is AdmissionAction.DEFER
    assert result.reason == "cpu_budget_exceeded"


def test_ram_reserve_must_remain_after_admission():
    result = evaluate(
        req=request(estimated_ram_mb=7000),
        sample=snapshot(available_ram_mb=8192),
    )
    assert result.action is AdmissionAction.DEFER
    assert result.reason == "ram_reserve_would_be_breached"


def test_exact_ram_reserve_is_allowed():
    result = evaluate(
        req=request(estimated_ram_mb=6144),
        sample=snapshot(available_ram_mb=8192),
    )
    assert result.action is AdmissionAction.ALLOW


def test_vram_reserve_must_remain_after_admission():
    result = evaluate(
        req=request(estimated_vram_mb=5000),
        sample=snapshot(available_vram_mb=6144),
    )
    assert result.action is AdmissionAction.DEFER
    assert result.reason == "vram_reserve_would_be_breached"


def test_exact_vram_reserve_is_allowed():
    result = evaluate(
        req=request(estimated_vram_mb=4608),
        sample=snapshot(available_vram_mb=6144),
    )
    assert result.action is AdmissionAction.ALLOW


def test_gpu_budget_includes_estimated_workload():
    result = evaluate(
        req=request(estimated_gpu_percent=70.0),
        sample=snapshot(gpu_percent=20.0),
    )
    assert result.action is AdmissionAction.DEFER
    assert result.reason == "gpu_budget_exceeded"


def test_gpu_work_defers_if_gpu_telemetry_is_missing():
    result = evaluate(sample=snapshot(available_vram_mb=None, gpu_percent=None))
    assert result.action is AdmissionAction.DEFER
    assert result.reason == "gpu_telemetry_unavailable"


def test_custom_policy_can_be_tuned_from_measured_hardware():
    policy = AdmissionPolicy(
        max_cpu_percent_after_admission=90.0,
        min_available_ram_mb=1024,
        min_available_vram_mb=512,
        max_gpu_percent_after_admission=90.0,
        min_game_fps=45.0,
    )
    result = evaluate(
        req=request(estimated_cpu_percent=70.0, estimated_ram_mb=2048,
                    estimated_vram_mb=4096, estimated_gpu_percent=70.0),
        sample=snapshot(cpu_percent=20.0, available_ram_mb=4096,
                        available_vram_mb=5120, gpu_percent=20.0),
        policy=policy,
    )
    assert result.action is AdmissionAction.ALLOW


def test_rejects_boolean_percentages():
    with pytest.raises(TypeError, match="cpu_percent must be a number"):
        snapshot(cpu_percent=True)


def test_rejects_boolean_memory_values():
    with pytest.raises(ValueError, match="available_ram_mb"):
        snapshot(available_ram_mb=True)


def test_rejects_obs_drop_count_greater_than_total():
    with pytest.raises(ValueError, match="cannot exceed"):
        snapshot(obs_dropped_frames=2, obs_total_frames=1)


def test_rejects_untrusted_workload_kind_strings():
    with pytest.raises(TypeError, match="WorkloadKind"):
        request(kind="realtime_audio")


def test_rejects_empty_request_id():
    with pytest.raises(ValueError, match="request_id"):
        request(request_id="  ")


def test_rejects_non_finite_snapshot_values():
    with pytest.raises(ValueError, match="cpu_percent"):
        snapshot(cpu_percent=float("nan"))


def test_rejects_invalid_policy_limits():
    with pytest.raises(ValueError, match="max_obs_drop_rate"):
        AdmissionPolicy(max_obs_drop_rate=1.5)


def test_rejects_invalid_evaluation_clock():
    with pytest.raises(ValueError, match="now_monotonic"):
        evaluate(now=float("nan"))



def test_normalizes_request_id_before_it_can_be_used_as_an_idempotency_key():
    req = request(request_id="  background-1  ")
    assert req.request_id == "background-1"


def test_snapshot_window_must_be_positive_and_finite():
    with pytest.raises(ValueError, match="window_seconds"):
        snapshot(window_seconds=0)
    with pytest.raises(ValueError, match="window_seconds"):
        snapshot(window_seconds=float("inf"))
