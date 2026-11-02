"""Regression coverage for workload-bound realtime inference profiles.

No models, games, microphones, OBS, or physical inputs are used.
"""
import pytest

from star.game_deadline_router import GameDeadlineRouter
from star.game_realtime_loop import RealtimeGameLoop
from star.game_action_gate import GameFrame, GameScope
from star.stream_budget import StreamTelemetry


def record(router: GameDeadlineRouter, indices: range, *, live: bool) -> None:
    for i in indices:
        assert router.record_reactive_latency(
            game_scope="game:episode", sample_id=i, sample_host_ms=i * 100,
            duration_ms=50, host_measured=True, stream_live=live,
        )


def advise(router: GameDeadlineRouter, *, live: bool, at: float):
    return router.advise(
        game_scope="game:episode", game_active=True,
        observation_age_ms=80, now_host_ms=at,
        host_verified=True, stream_live=live,
    )


def test_strict_profile_rejects_idle_timings_as_live_game_speed():
    router = GameDeadlineRouter(
        minimum_samples=8, strict_workload_profile=True,
    )
    router.enable(owner_approved=True, game_scope="game:episode")
    record(router, range(1, 9), live=False)
    assert advise(router, live=False, at=1000).route == "reactive"
    under_stream = advise(router, live=True, at=1001)
    assert under_stream.route == "skip"
    assert under_stream.reason == "insufficient_matching_workload_latency_samples"
    record(router, range(9, 17), live=True)
    assert advise(router, live=True, at=1800).route == "reactive"
    # Restarting a session cannot borrow either earlier profile.
    router.disable()
    router.enable(owner_approved=True, game_scope="game:episode")
    assert advise(router, live=True, at=1900).route == "skip"


def test_strict_profiles_distinguish_load_and_validate_flags():
    router = GameDeadlineRouter(minimum_samples=5, strict_workload_profile=True)
    router.enable(owner_approved=True, game_scope="game:episode")
    record(router, range(1, 6), live=True)
    assert advise(router, live=False, at=800).reason == (
        "insufficient_matching_workload_latency_samples"
    )
    assert advise(router, live=True, at=801).route == "reactive"
    with pytest.raises(ValueError):
        GameDeadlineRouter(strict_workload_profile=1)
    with pytest.raises(ValueError):
        router.record_reactive_latency(
            game_scope="game:episode", sample_id=6, sample_host_ms=700,
            duration_ms=30, host_measured=True, stream_live=1,
        )
    # With the optional mode off, legacy idle measurements remain available.
    legacy = GameDeadlineRouter(minimum_samples=5)
    legacy.enable(owner_approved=True, game_scope="game:episode")
    record(legacy, range(1, 6), live=False)
    assert advise(legacy, live=True, at=800).route == "reactive"


def test_realtime_loop_propagates_stream_workload_to_strict_router():
    router = GameDeadlineRouter(minimum_samples=5, strict_workload_profile=True)
    loop = RealtimeGameLoop(router=router)
    scope = GameScope("game", "v1", "episode")
    loop.start(scope, ("jump",), owner_approved=True)
    for i in range(1, 6):
        assert loop.record_reactive_latency(
            sample_id=i, sample_host_ms=i * 100, duration_ms=50,
            host_measured=True, stream_live=False,
        )
    telemetry = StreamTelemetry(True, True, 4000, 8192, 60, 0)
    def frame(i: int, captured: float) -> GameFrame:
        return GameFrame(scope, i, captured, "a" * 64, True, True, 0.95)
    denied = loop.offer(
        frame(1, 1000), now_ms=1100, host_verified=True,
        stream_live=True, telemetry=telemetry,
    )
    assert denied.reason == "insufficient_matching_workload_latency_samples"
    for i in range(6, 11):
        assert loop.record_reactive_latency(
            sample_id=i, sample_host_ms=i * 100 + 1000,
            duration_ms=50, host_measured=True, stream_live=True,
        )
    accepted = loop.offer(
        frame(2, 2100), now_ms=2200, host_verified=True,
        stream_live=True, telemetry=telemetry,
    )
    assert accepted.route == "reactive"
    assert accepted.authorizes_model_launch is False
    assert accepted.authorized_to_play is False
