"""Offline, adversarial real-time game routing tests; no game/device I/O."""
from threading import Event, RLock, Thread

import pytest

from star.game_deadline_router import GameDeadlineRouter


def router(*, device="cpu", warmup=8):
    gate = GameDeadlineRouter(minimum_samples=warmup, reactive_device=device)
    gate.enable(owner_approved=True, game_scope="obby:v2")
    return gate


def train(gate, *, durations=None):
    for i, duration in enumerate(durations or [70] * 8, 1):
        assert gate.record_reactive_latency(
            game_scope="obby:v2", sample_id=i, sample_host_ms=i * 100, duration_ms=duration,
            host_measured=True,
        )


def decide(gate, **kwargs):
    params = dict(game_scope="obby:v2", game_active=True,
                  observation_age_ms=120, now_host_ms=1000, host_verified=True)
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
        gate.record_reactive_latency(game_scope="obby:v2", sample_id=i, sample_host_ms=i * 100,
                                     duration_ms=30, host_measured=True)
    assert decide(gate).reason == "insufficient_recent_latency_samples"


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
            game_scope="another_game", sample_id=index, sample_host_ms=index * 100, duration_ms=30,
            host_measured=True)
        assert not gate.record_reactive_latency(
            game_scope="obby:v2", sample_id=index, sample_host_ms=index * 100, duration_ms=30,
            host_measured=False)
    assert decide(gate).route == "skip"
    assert gate.advise(game_scope="another_game", game_active=True,
                       observation_age_ms=1, host_verified=True).route == "skip"
    assert gate.advise(game_scope="obby:v2", game_active=True,
                       observation_age_ms=1, host_verified=False).route == "skip"


def test_replay_same_id_fails_and_cannot_warm_fake_samples():
    gate = router()
    assert gate.record_reactive_latency(game_scope="obby:v2", sample_id=1, sample_host_ms=1 * 100,
                                        duration_ms=50, host_measured=True)
    for _ in range(20):
        assert not gate.record_reactive_latency(game_scope="obby:v2", sample_id=1, sample_host_ms=1 * 100,
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
            gate.record_reactive_latency(game_scope="obby:v2", sample_id=1, sample_host_ms=1 * 100,
                                         duration_ms=invalid, host_measured=True)
    with pytest.raises(ValueError):
        decide(gate, cpu_pressure=1)
    with pytest.raises(ValueError):
        gate.record_reactive_latency(game_scope="obby:v2", sample_id=True, sample_host_ms=True * 100,
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
            game_scope="obby:v2", sample_id=index, sample_host_ms=index * 100, duration_ms=50,
            completed=True, host_measured=True,
        )
    assert gate.record_reactive_latency(
        game_scope="obby:v2", sample_id=8, sample_host_ms=8 * 100, duration_ms=200,
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
            game_scope="obby:v2", sample_id=1, sample_host_ms=1 * 100, duration_ms=20,
            completed=1, host_measured=True,
        )


def test_old_model_timings_expire_before_live_game_decision():
    gate = router()
    train(gate)
    assert decide(gate, now_host_ms=1000).route == "reactive"
    # No replayed or historically fast sample can fill today's window.
    stale = decide(gate, now_host_ms=18000)
    assert stale.reason == "insufficient_recent_latency_samples"
    for i in range(9, 16):
        assert gate.record_reactive_latency(
            game_scope="obby:v2", sample_id=i, sample_host_ms=16500 + 100 * i,
            duration_ms=55, host_measured=True,
        )
    assert decide(gate, now_host_ms=18100).reason == "insufficient_recent_latency_samples"
    assert gate.record_reactive_latency(
        game_scope="obby:v2", sample_id=16, sample_host_ms=18100,
        duration_ms=55, host_measured=True,
    )
    assert decide(gate, now_host_ms=18200).route == "reactive"


def test_out_of_order_timing_clock_and_future_samples_fail_closed():
    gate = router()
    train(gate)
    assert not gate.record_reactive_latency(
        game_scope="obby:v2", sample_id=9, sample_host_ms=800,
        duration_ms=1, host_measured=True,
    )
    assert gate.metrics()["replays"] == 1
    assert decide(gate, now_host_ms=799).reason == "host_clock_before_samples"
    assert decide(gate, now_host_ms=1000).route == "reactive"
    assert gate.record_reactive_latency(
        game_scope="obby:v2", sample_id=9, sample_host_ms=900,
        duration_ms=80, host_measured=True,
    )


def test_live_route_requires_host_clock_and_valid_sample_age():
    gate = router()
    train(gate)
    assert decide(gate, now_host_ms=None).reason == "host_clock_missing"
    for bad in (True, -1, float("nan"), float("inf"), 10**100):
        with pytest.raises(ValueError):
            decide(gate, now_host_ms=bad)
        with pytest.raises(ValueError):
            gate.record_reactive_latency(
                game_scope="obby:v2", sample_id=9, sample_host_ms=bad,
                duration_ms=80, host_measured=True,
            )
    for bad in (1, 240, float("nan"), 60001, True):
        with pytest.raises(ValueError):
            GameDeadlineRouter(max_latency_sample_age_ms=bad)


def test_host_clock_rollback_does_not_revive_expired_game_speed_profile():
    gate = router()
    train(gate)
    assert decide(gate, now_host_ms=1000).route == "reactive"
    assert decide(gate, now_host_ms=18000).reason == "insufficient_recent_latency_samples"
    # A broken/restarted host clock must not turn old samples into fresh ones.
    assert decide(gate, now_host_ms=1000).reason == "host_clock_reversed"
    assert decide(gate, now_host_ms=18001).reason == "insufficient_recent_latency_samples"
    # Session re-enablement explicitly clears clock history and old samples.
    gate.disable()
    gate.enable(owner_approved=True, game_scope="obby:v2")
    train(gate)
    assert decide(gate, now_host_ms=1000).route == "reactive"


def test_session_enable_cannot_erase_a_racing_latency_sample_timestamp():
    class _PauseAfterUnlock:
        def __init__(self):
            self.inner = RLock()
            self.released = Event()
            self.resume = Event()
            self.pause_once = True

        def __enter__(self):
            self.inner.acquire()
            return self

        def __exit__(self, _type, _value, _traceback):
            self.inner.release()
            if self.pause_once:
                self.pause_once = False
                self.released.set()
                if not self.resume.wait(timeout=3):
                    raise AssertionError("test failed to release enable")

    gate = GameDeadlineRouter()
    lock = _PauseAfterUnlock()
    # Instrument the lock boundary to make the previously narrow race
    # deterministic, rather than relying on scheduling luck.
    gate.__dict__["_lock"] = lock
    errors = []

    def enable_in_thread():
        try:
            gate.enable(owner_approved=True, game_scope="obby:v2")
        except Exception as exc:
            errors.append(exc)

    thread = Thread(target=enable_in_thread, daemon=True)
    thread.start()
    try:
        assert lock.released.wait(timeout=3)
        assert gate.record_reactive_latency(
            game_scope="obby:v2", sample_id=1, sample_host_ms=100,
            duration_ms=50, host_measured=True,
        )
    finally:
        lock.resume.set()
        thread.join(timeout=3)
    assert not thread.is_alive()
    assert not errors
    # Previously the timestamp reset OUTSIDE enable's lock, so a second
    # sample could be accepted with a smaller time and a larger sample ID.
    assert not gate.record_reactive_latency(
        game_scope="obby:v2", sample_id=2, sample_host_ms=90,
        duration_ms=40, host_measured=True,
    )
    assert gate.metrics()["replays"] == 1
