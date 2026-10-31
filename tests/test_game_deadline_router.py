"""Offline, adversarial real-time game routing tests; no game/device I/O."""
import pytest

from star.game_deadline_router import GameDeadlineRouter


def router(*, device="cpu", warmup=8):
    gate = GameDeadlineRouter(minimum_samples=warmup, reactive_device=device)
    gate.enable(owner_approved=True, game_scope="obby:v2")
    return gate


def train(gate, *, durations=None):
    for i, duration in enumerate(durations or [70] * 8, 1):
        assert gate.record_reactive_latency(
            game_scope="obby:v2", sample_id=i, duration_ms=duration,
            host_measured=True,
        )


def decide(gate, **kwargs):
    params = dict(game_scope="obby:v2", game_active=True,
                  observation_age_ms=120, host_verified=True)
    params.update(kwargs)
    return gate.advise(**params)


def test_disabled_by_default_and_requires_host_permission():
    gate = GameDeadlineRouter()
    assert gate.advise(game_scope="obby:v2", game_active=True,
                       observation_age_ms=1).route == "skip"
    with pytest.raises(PermissionError):
        gate.enable(game_scope="obby:v2")


def test_profiled_fast_route_accepted_only_with_deadline_slack():
    gate = router()
    train(gate)
    verdict = decide(gate)
    assert verdict.route == "reactive"
    assert verdict.remaining_ms == 190
    assert verdict.profiled_p95_ms == 70
    assert not verdict.authorized_to_play and not verdict.authorizes_model_launch


def test_unknown_speed_cannot_assume_inference_is_fast():
    gate = router()
    for i in range(1, 8):
        gate.record_reactive_latency(game_scope="obby:v2", sample_id=i,
                                     duration_ms=30, host_measured=True)
    assert decide(gate).reason == "insufficient_host_latency_samples"


def test_p95_high_tail_prevents_wasted_late_work():
    gate = router()
    train(gate, durations=[30] * 7 + [320])
    verdict = decide(gate)
    assert verdict.route == "skip"
    assert verdict.reason == "reactive_p95_exceeds_scene_slack"
    assert verdict.profiled_p95_ms == 320


def test_scene_age_and_dispatch_reserve_are_hard_limits():
    gate = router()
    train(gate)
    assert decide(gate, observation_age_ms=310).reason == "scene_deadline_expired"
    assert decide(gate, observation_age_ms=280).reason == "reactive_p95_exceeds_scene_slack"
    assert decide(gate, observation_age_ms=350).route == "skip"
    assert decide(gate, observation_age_ms=200).route == "reactive"
    assert decide(gate, observation_age_ms=240).reason == "reactive_p95_exceeds_scene_slack"


def test_active_game_never_routes_slow_teacher():
    gate = router()
    train(gate)
    assert decide(gate, offline_teacher_approved=True).route == "reactive"
    gate.disable()
    gate.enable(owner_approved=True, game_scope="obby:v2")
    assert decide(gate, offline_teacher_approved=True).route == "skip"


def test_offline_teacher_only_with_separate_host_approval():
    gate = router()
    data = dict(game_scope="obby:v2", game_active=False, host_verified=True)
    assert gate.advise(**data).reason == "offline_teacher_not_approved"
    verdict = gate.advise(**data, offline_teacher_approved=True)
    assert verdict.route == "teacher_offline"
    assert not verdict.authorizes_model_launch
    assert gate.advise(**data, offline_teacher_approved=True,
                       gpu_pressure=True).route == "skip"


def test_cpu_fast_path_does_not_require_free_gpu_but_needs_cpu_headroom():
    gate = router(device="cpu")
    train(gate)
    assert decide(gate, gpu_pressure=True).route == "reactive"
    assert decide(gate, cpu_pressure=True).route == "skip"
    gpu_gate = router(device="gpu")
    train(gpu_gate)
    assert decide(gpu_gate, gpu_pressure=True).reason == "hardware_pressure"


def test_stale_cross_game_or_unverified_timing_is_not_used():
    gate = router()
    for index in range(1, 9):
        assert not gate.record_reactive_latency(
            game_scope="another_game", sample_id=index, duration_ms=30,
            host_measured=True)
        assert not gate.record_reactive_latency(
            game_scope="obby:v2", sample_id=index, duration_ms=30,
            host_measured=False)
    assert decide(gate).route == "skip"
    assert gate.advise(game_scope="another_game", game_active=True,
                       observation_age_ms=1, host_verified=True).route == "skip"
    assert gate.advise(game_scope="obby:v2", game_active=True,
                       observation_age_ms=1, host_verified=False).route == "skip"


def test_replay_same_id_fails_and_cannot_warm_fake_samples():
    gate = router()
    assert gate.record_reactive_latency(game_scope="obby:v2", sample_id=1,
                                        duration_ms=50, host_measured=True)
    for _ in range(20):
        assert not gate.record_reactive_latency(game_scope="obby:v2", sample_id=1,
                                                duration_ms=1, host_measured=True)
    assert gate.metrics()["timing_samples"] == 1
    assert gate.metrics()["replays"] == 20
    assert decide(gate).route == "skip"


def test_session_reset_invalidates_prior_inference_profile():
    gate = router()
    train(gate)
    assert decide(gate).route == "reactive"
    gate.disable()
    gate.enable(owner_approved=True, game_scope="obby:v3")
    assert gate.advise(game_scope="obby:v3", game_active=True,
                       observation_age_ms=100, host_verified=True).route == "skip"
    assert gate.metrics()["timing_samples"] == 0


def test_malformed_flags_and_times_rejected():
    gate = router()
    for invalid in (float("nan"), float("inf"), -1, True, 10**100):
        with pytest.raises(ValueError):
            decide(gate, observation_age_ms=invalid)
    for invalid in (True, 0, float("nan"), 5001):
        with pytest.raises(ValueError):
            decide(gate, max_observation_age_ms=invalid)
    for invalid in (0, True, float("inf")):
        with pytest.raises(ValueError):
            gate.record_reactive_latency(game_scope="obby:v2", sample_id=1,
                                         duration_ms=invalid, host_measured=True)
    with pytest.raises(ValueError):
        decide(gate, cpu_pressure=1)
    with pytest.raises(ValueError):
        gate.record_reactive_latency(game_scope="obby:v2", sample_id=True,
                                     duration_ms=30, host_measured=True)
    with pytest.raises(ValueError):
        GameDeadlineRouter(minimum_samples=True)
    with pytest.raises(ValueError):
        GameDeadlineRouter(reactive_device="cloud")
    with pytest.raises(RuntimeError):
        gate.enable(owner_approved=True, game_scope="new_game")


def test_no_identifying_data_in_aggregate_metrics():
    gate = router()
    train(gate)
    assert set(gate.metrics()) == {"measured", "timeouts", "replays", "reactive", "skipped",
                                   "offline_teacher", "enabled", "timing_samples",
                                   "reactive_p95_ms"}


def test_timed_out_inference_is_counted_as_slow_not_silently_discarded():
    gate = router()
    for index in range(1, 8):
        assert gate.record_reactive_latency(
            game_scope="obby:v2", sample_id=index, duration_ms=50,
            completed=True, host_measured=True,
        )
    assert gate.record_reactive_latency(
        game_scope="obby:v2", sample_id=8, duration_ms=200,
        completed=False, host_measured=True,
    )
    assert gate.metrics()["timeouts"] == 1
    assert gate.metrics()["timing_samples"] == 8
    assert decide(gate).reason == "reactive_p95_exceeds_scene_slack"
    assert gate.metrics()["reactive_p95_ms"] == 5000


def test_non_boolean_completion_is_rejected():
    gate = router()
    with pytest.raises(ValueError):
        gate.record_reactive_latency(
            game_scope="obby:v2", sample_id=1, duration_ms=20,
            completed=1, host_measured=True,
        )
