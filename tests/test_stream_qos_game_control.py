"""Regression tests for the explicit game-control inference lane.

These tests use deterministic synthetic host timings. They do not run a model,
dispatch game input, or claim real hardware performance.
"""
import pytest

from star.stream_budget import StreamTelemetry
from star.stream_qos import AdaptiveQoS, InferenceJob, QoSSnapshot


def snapshot(
    at: int,
    *,
    live: bool = True,
    game: bool = True,
    fps: float = 60,
    backlog: float = 0,
    vram: float = 6000,
    cpu: float = 20,
    cpu_slots: int = 2,
    gpu_slots: int = 1,
) -> QoSSnapshot:
    return QoSSnapshot(
        at,
        StreamTelemetry(live, game, vram, 8192, fps, backlog),
        16000,
        cpu,
        cpu_slots,
        gpu_slots,
    )


def job(
    ident: str,
    at: int,
    *,
    kind: str = "game_control",
    device: str = "auto",
    ttl: int = 1600,
) -> InferenceJob:
    return InferenceJob(
        ident,
        kind,
        at,
        at + ttl,
        128,
        384,
        device,
    )


def ready() -> AdaptiveQoS:
    scheduler = AdaptiveQoS()
    scheduler.enable(owner_approved=True)
    return scheduler


def train_route(
    scheduler: AdaptiveQoS,
    *,
    device: str,
    duration_ms: int,
    kind: str = "game_control",
    start_ms: int = 1000,
    steps: int = 5,
) -> None:
    """Synthetic acknowledgements, not a hardware measurement."""
    for index in range(steps):
        at = start_ms + index * 3000
        offer = scheduler.admit(
            job(f"cal-{kind}-{device}-{index}", at, kind=kind, device=device),
            snapshot(at, live=False, game=True),
            now_ms=at,
        )
        assert offer.admitted, offer.reason
        assert offer.device == device
        assert scheduler.finish(
            offer.ticket,
            now_ms=at + duration_ms,
            succeeded=True,
        )


def test_game_control_requires_active_game_calibration() -> None:
    scheduler = ready()
    result = scheduler.admit(
        job("uncalibrated", 1000),
        snapshot(1000, live=True, game=True),
        now_ms=1000,
    )
    assert not result.admitted
    assert result.reason == "no_calibrated_deadline_safe_route_or_headroom"


def test_game_control_uses_cpu_route_under_game_and_voice_pressure() -> None:
    scheduler = ready()
    train_route(scheduler, device="cpu", duration_ms=220)

    result = scheduler.admit(
        job("control-under-pressure", 17000, ttl=1000),
        snapshot(17000, live=True, game=True, fps=38, backlog=300),
        now_ms=17000,
    )

    assert result.admitted
    assert result.device == "cpu"
    assert result.predicted_p95_ms == 220
    assert result.reason == "measured_p95_with_headroom"


def test_game_control_prefers_cpu_even_when_gpu_route_is_faster() -> None:
    scheduler = ready()
    train_route(scheduler, device="cpu", duration_ms=320)
    train_route(scheduler, device="gpu", duration_ms=100, start_ms=17000)

    result = scheduler.admit(
        job("prefer-cpu", 34000),
        snapshot(34000, live=True, game=True, fps=60),
        now_ms=34000,
    )

    assert result.admitted
    assert result.device == "cpu"
    assert result.predicted_p95_ms == 320


def test_gpu_game_control_is_rejected_when_game_is_under_pressure() -> None:
    scheduler = ready()
    train_route(scheduler, device="gpu", duration_ms=120)

    result = scheduler.admit(
        job("gpu-under-pressure", 17000, device="gpu"),
        snapshot(17000, live=True, game=True, fps=35),
        now_ms=17000,
    )

    assert not result.admitted
    assert result.reason == "no_calibrated_deadline_safe_route_or_headroom"


def test_gpu_is_a_measured_fallback_when_cpu_is_saturated_and_game_is_healthy() -> None:
    scheduler = ready()
    train_route(scheduler, device="gpu", duration_ms=140)

    result = scheduler.admit(
        job("gpu-fallback", 17000),
        snapshot(17000, live=True, game=True, fps=60, cpu=96),
        now_ms=17000,
    )

    assert result.admitted
    assert result.device == "gpu"
    assert result.predicted_p95_ms == 140


def test_game_control_deadline_must_fit_measured_tail_latency() -> None:
    scheduler = ready()
    train_route(scheduler, device="cpu", duration_ms=500)

    result = scheduler.admit(
        job("short-deadline", 17000, ttl=500),
        snapshot(17000, live=True, game=True),
        now_ms=17000,
    )

    assert not result.admitted
    assert result.reason == "no_calibrated_deadline_safe_route_or_headroom"


def test_game_control_admission_is_not_a_game_input_permission() -> None:
    scheduler = ready()
    train_route(scheduler, device="cpu", duration_ms=180)

    result = scheduler.admit(
        job("advisory-only", 17000),
        snapshot(17000),
        now_ms=17000,
    )

    assert result.admitted
    assert not hasattr(result, "dispatch")
    assert not hasattr(result, "input")
    assert scheduler.status()["completed"] == 5


def test_game_control_rejects_invalid_device_and_kind() -> None:
    with pytest.raises(ValueError, match="unknown inference kind"):
        InferenceJob("unknown", "game_action", 1, 100, 128, 384)

    with pytest.raises(ValueError, match="device must be"):
        job("bad-device", 1, device="remote")



def test_game_control_is_not_priority_when_no_game_is_active() -> None:
    scheduler = ready()
    result = scheduler.admit(
        job("no-active-game", 1000),
        snapshot(1000, live=True, game=False, backlog=300),
        now_ms=1000,
    )
    assert not result.admitted
    assert result.reason == "game_or_voice_backpressure"



def test_idle_game_control_samples_do_not_certify_live_game_route() -> None:
    scheduler = ready()
    for index in range(5):
        at = 1000 + index * 3000
        offer = scheduler.admit(
            job(f"idle-cal-{index}", at, device="cpu"),
            snapshot(at, live=False, game=False),
            now_ms=at,
        )
        assert offer.admitted
        assert scheduler.finish(
            offer.ticket,
            now_ms=at + 180,
            succeeded=True,
        )

    result = scheduler.admit(
        job("live-after-idle-calibration", 17000),
        snapshot(17000, live=True, game=True),
        now_ms=17000,
    )

    assert not result.admitted
    assert result.reason == "no_calibrated_deadline_safe_route_or_headroom"
    assert "game_control:cpu:idle" in scheduler.status()["route_p95_ms"]
    assert "game_control:cpu:game_active" not in scheduler.status()["route_p95_ms"]


def test_live_non_speech_cpu_work_preserves_a_speech_slot() -> None:
    scheduler = ready()
    train_route(scheduler, device="cpu", duration_ms=220)

    one_slot = scheduler.admit(
        job("control-one-slot", 17000, device="cpu"),
        snapshot(17000, live=True, game=True, cpu_slots=1),
        now_ms=17000,
    )
    assert not one_slot.admitted

    two_slots = scheduler.admit(
        job("control-two-slots", 17000, device="cpu"),
        snapshot(17000, live=True, game=True, cpu_slots=2),
        now_ms=17000,
    )
    assert two_slots.admitted
    assert two_slots.device == "cpu"
    assert scheduler.status()["speech_cpu_reserve_slots"] == 1


def test_speech_can_use_reserved_slot_while_game_control_is_running() -> None:
    scheduler = ready()
    train_route(scheduler, device="cpu", duration_ms=220)
    train_route(
        scheduler, kind="speech", device="cpu", duration_ms=180, start_ms=17000
    )

    control = scheduler.admit(
        job("control-first", 34000, device="cpu"),
        snapshot(34000, live=True, game=True, cpu_slots=2),
        now_ms=34000,
    )
    assert control.admitted

    speech = scheduler.admit(
        job("speech-reserved-slot", 34000, kind="speech", device="cpu"),
        snapshot(34000, live=True, game=True, cpu_slots=2),
        now_ms=34000,
    )
    assert speech.admitted
    assert speech.device == "cpu"

    second_control = scheduler.admit(
        job("control-cannot-take-speech-slot", 34000, device="cpu"),
        snapshot(34000, live=True, game=True, cpu_slots=2),
        now_ms=34000,
    )
    assert not second_control.admitted


def test_speech_cpu_reserve_does_not_reduce_private_rehearsal_capacity() -> None:
    scheduler = ready()
    train_route(scheduler, device="cpu", duration_ms=220)

    result = scheduler.admit(
        job("private-one-slot", 17000, device="cpu"),
        snapshot(17000, live=False, game=True, cpu_slots=1),
        now_ms=17000,
    )
    assert result.admitted
    assert result.device == "cpu"


def test_speech_cpu_reserve_configuration_is_strictly_bounded() -> None:
    with pytest.raises(ValueError, match="speech_cpu_reserve_slots"):
        AdaptiveQoS(speech_cpu_reserve_slots=True)
    with pytest.raises(ValueError, match="speech_cpu_reserve_slots"):
        AdaptiveQoS(speech_cpu_reserve_slots=-1)
    with pytest.raises(ValueError, match="speech_cpu_reserve_slots"):
        AdaptiveQoS(speech_cpu_reserve_slots=9)


def test_live_speech_occupancy_does_not_double_count_the_reserved_slot() -> None:
    scheduler = ready()
    train_route(scheduler, device="cpu", duration_ms=220)
    train_route(
        scheduler, kind="speech", device="cpu", duration_ms=180, start_ms=17000
    )

    speech = scheduler.admit(
        job("speech-first", 34000, kind="speech", device="cpu"),
        snapshot(34000, live=True, game=True, cpu_slots=2),
        now_ms=34000,
    )
    assert speech.admitted and speech.device == "cpu"

    control = scheduler.admit(
        job("control-uses-unoccupied-slot", 34000, device="cpu"),
        snapshot(34000, live=True, game=True, cpu_slots=2),
        now_ms=34000,
    )
    assert control.admitted and control.device == "cpu"

    over_capacity = scheduler.admit(
        job("control-over-capacity", 34000, device="cpu"),
        snapshot(34000, live=True, game=True, cpu_slots=2),
        now_ms=34000,
    )
    assert not over_capacity.admitted
