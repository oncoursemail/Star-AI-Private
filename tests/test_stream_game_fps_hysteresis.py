"""Offline regression coverage for live game-FPS hysteresis, not GPU benchmarks."""
import pytest

from star.stream_budget import StreamTelemetry
from star.stream_qos import AdaptiveQoS, InferenceJob, QoSSnapshot


def snapshot(at, *, fps=60, live=True, game=True):
    return QoSSnapshot(
        at, StreamTelemetry(live, game, 7500, 8192, fps, 0),
        free_ram_mib=16000, cpu_busy_percent=20, cpu_slots=2, gpu_slots=1,
    )


def attempt(q, at, *, kind="speech", device="gpu", fps=60, live=True,
            game=True, sampled=None):
    sample = snapshot(at if sampled is None else sampled, fps=fps, live=live, game=game)
    request = InferenceJob(
        f"lease-{kind}-{at}", kind, at, at + 1500, 100, 300, device,
    )
    return q.admit(request, sample, now_ms=at)


def protected():
    q = AdaptiveQoS()
    q.enable(owner_approved=True)
    first = attempt(q, 100, fps=35)
    assert not first.admitted
    assert q.status()["gpu_voice_fps_guarded"] is True
    return q


def test_near_threshold_fps_never_clears_guard():
    q = protected()
    for t in (200, 700, 1200, 1700, 2200, 2700):
        assert attempt(q, t, fps=55).reason == "protect_low_fps_game_from_gpu_voice"
    assert q.status()["gpu_voice_recovering"] is False


def test_strong_fps_recovery_needs_full_time_window():
    q = protected()
    for t in (200, 700, 1200, 1700):
        assert attempt(q, t).reason == "protect_low_fps_game_from_gpu_voice"
        assert q.status()["gpu_voice_recovering"]
    assert attempt(q, 2200).admitted
    assert not q.status()["gpu_voice_fps_guarded"]


def test_one_strong_sample_followed_by_long_gap_restarts_window():
    q = protected()
    assert not attempt(q, 200).admitted
    assert not attempt(q, 2000).admitted  # >750ms observation gap
    for t in (2500, 3000, 3500):
        assert not attempt(q, t).admitted
    assert attempt(q, 4000).admitted


def test_recovery_interrupted_by_flapping_fps_starts_again():
    q = protected()
    assert not attempt(q, 200).admitted
    assert not attempt(q, 700).admitted
    assert not attempt(q, 1200, fps=56).admitted
    for t in (1700, 2200, 2700, 3200):
        assert not attempt(q, t).admitted
    assert attempt(q, 3700).admitted


def test_backpressure_continues_during_recovery_even_for_unrelated_vision():
    q = protected()
    assert attempt(q, 200, kind="vision", device="gpu").reason == "game_or_voice_backpressure"
    assert attempt(q, 700, kind="commentary", device="cpu").reason == "game_or_voice_backpressure"


def test_cpu_voice_can_continue_while_gpu_protected():
    q = protected()
    voice = attempt(q, 200, device="auto", fps=56)
    assert voice.admitted and voice.device == "cpu"
    assert q.status()["gpu_voice_fps_guarded"]
    assert q.finish(voice.ticket, now_ms=400, succeeded=True)


def test_stale_telemetry_cannot_lift_gpu_voice_guard():
    q = protected()
    for at in (400, 900, 1400, 1900):
        assert not attempt(q, at, sampled=0).admitted
    assert q.status()["gpu_voice_fps_guarded"]
    assert not q.status()["gpu_voice_recovering"]
    assert attempt(q, 2400).reason == "protect_low_fps_game_from_gpu_voice"


def test_full_offline_or_idle_scene_clears_live_game_protection():
    q = protected()
    result = attempt(q, 200, game=False)
    assert result.admitted and result.device == "gpu"
    assert not q.status()["gpu_voice_fps_guarded"]


def test_game_reenables_protection_on_new_fps_drop():
    q = protected()
    assert attempt(q, 200, game=False).admitted
    assert attempt(q, 300, fps=42).reason == "protect_low_fps_game_from_gpu_voice"


def test_disabled_session_resets_only_after_worker_stops():
    q = protected()
    assert not attempt(q, 200, fps=55).admitted
    q.disable()
    q.enable(owner_approved=True)
    assert not q.status()["gpu_voice_fps_guarded"]
    assert attempt(q, 300).admitted


def test_untrusted_reversed_clock_does_not_advance_recovery():
    q = protected()
    assert not attempt(q, 200).admitted
    with pytest.raises(ValueError, match="monotonic"):
        attempt(q, 150)
    assert attempt(q, 700).reason == "protect_low_fps_game_from_gpu_voice"


def test_heartbeat_can_release_guard_without_voice_attempts():
    q = protected()
    for t in (200, 700, 1200, 1700, 2200):
        assert q.observe_telemetry(snapshot(t), now_ms=t)
    assert not q.status()["gpu_voice_fps_guarded"]
    assert attempt(q, 2300).admitted


def test_heartbeat_rejects_old_and_future_sensor_times():
    q = protected()
    assert not q.observe_telemetry(snapshot(0), now_ms=400)
    assert not q.observe_telemetry(snapshot(2000), now_ms=500)
    assert q.status()["gpu_voice_fps_guarded"]
    assert not q.status()["gpu_voice_recovering"]


def test_heartbeat_while_disabled_cannot_build_recovery_history():
    q = protected()
    q.disable()
    assert not q.observe_telemetry(snapshot(200), now_ms=200)
    q.enable(owner_approved=True)
    assert attempt(q, 300).admitted
