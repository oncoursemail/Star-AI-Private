"""Synthetic parity checks for a private, stream-equivalent Windows rehearsal.

These fixtures NEVER claim a real GPU, OBS recording, audible voice or game.
Unlike a live stream, a private rehearsal can probe an unmeasured vision route,
but only while observing the same resource protections and sampling limits.
"""
from __future__ import annotations

import pytest

from star.stream_budget import StreamTelemetry
from star.stream_qos import AdaptiveQoS, InferenceJob, QoSSnapshot


def snap(at: float, *, private: bool = True, game: bool = True,
         vram: float = 6200, fps: float = 60,
         live: bool = False) -> QoSSnapshot:
    return QoSSnapshot(
        at, StreamTelemetry(live, game, vram, 8192, fps, 0),
        16000, 20, private_stream_rehearsal=private,
    )


def job(name: str, at: float, *, kind: str = "vision",
        device: str = "gpu", ttl: float = 1000,
        vram: float = 256) -> InferenceJob:
    return InferenceJob(name, kind, at, at + ttl, 100, vram, device)


@pytest.fixture
def qos() -> AdaptiveQoS:
    q = AdaptiveQoS()
    q.enable(owner_approved=True)
    return q


@pytest.mark.parametrize("kind", ["research", "training", "render"])
def test_private_rehearsal_defers_background_competition(
    qos: AdaptiveQoS, kind: str,
) -> None:
    refusal = qos.admit(job("bg-" + kind, 1000, kind=kind), snap(1000),
                       now_ms=1000)
    assert not refusal.admitted
    assert refusal.reason == "protect_private_rehearsal_from_background_work"
    assert qos.status()["inflight"] == 0
    # A true offline session can still test otherwise-admissible tasks.
    offline = qos.admit(job("offline-" + kind, 2000, kind=kind),
                        snap(2000, private=False), now_ms=2000)
    assert offline.admitted


def test_private_rehearsal_caps_vision_at_one_hz_but_can_calibrate(
    qos: AdaptiveQoS,
) -> None:
    first = qos.admit(job("first-vision", 1000), snap(1000), now_ms=1000)
    assert first.admitted
    assert first.reason == "unmeasured_host_must_verify"
    assert qos.finish(first.ticket, now_ms=1100, succeeded=True)
    second = qos.admit(job("too-soon", 1500), snap(1500), now_ms=1500)
    assert not second.admitted
    assert second.reason == "private_vision_at_most_one_hz"
    allowed = qos.admit(job("after-one-second", 2000), snap(2000), now_ms=2000)
    assert allowed.admitted


def test_private_game_gpu_headroom_matches_real_stream(
    qos: AdaptiveQoS,
) -> None:
    # 1,700 MiB free cannot fit a 256 MiB model AND the 1,536 MiB reserve.
    denied = qos.admit(job("under-reserve", 1000), snap(1000, vram=1700),
                       now_ms=1000)
    assert not denied.admitted
    assert denied.reason == "no_calibrated_deadline_safe_route_or_headroom"
    accepted = qos.admit(job("healthy-headroom", 2000), snap(2000, vram=6200),
                         now_ms=2000)
    assert accepted.admitted


def test_private_rehearsal_rejects_stale_host_sample(
    qos: AdaptiveQoS,
) -> None:
    # Private recording must not get the relaxed 2-second offline sensor TTL.
    denied = qos.admit(job("stale-sensor", 1400), snap(1000), now_ms=1400)
    assert not denied.admitted
    assert denied.reason == "host_telemetry_stale_or_future_dated"
    normal_offline = qos.admit(job("offline-sensor", 1500),
                               snap(1100, private=False), now_ms=1500)
    assert normal_offline.admitted


def test_private_rehearsal_rejects_old_job_even_with_new_sensor(
    qos: AdaptiveQoS,
) -> None:
    denied = qos.admit(job("old-work", 1000, ttl=2500),
                       snap(2400), now_ms=2400)
    assert not denied.admitted
    assert denied.reason == "job_stale"
    offline = qos.admit(job("offline-old-work", 1000, ttl=2500),
                        snap(2400, private=False), now_ms=2400)
    assert offline.admitted


def test_private_low_fps_protects_gpu_voice_and_allows_cpu(
    qos: AdaptiveQoS,
) -> None:
    denied = qos.admit(
        job("gpu-voice", 1000, kind="speech"),
        snap(1000, fps=38), now_ms=1000,
    )
    assert not denied.admitted
    assert denied.reason == "protect_low_fps_game_from_gpu_voice"
    cpu = qos.admit(
        job("cpu-voice", 1100, kind="speech", device="cpu"),
        snap(1100, fps=38), now_ms=1100,
    )
    assert cpu.admitted
    assert cpu.device == "cpu"


def test_private_low_fps_requires_sustained_recovery(
    qos: AdaptiveQoS,
) -> None:
    first = qos.admit(job("first", 100, kind="speech"),
                      snap(100, fps=40), now_ms=100)
    assert not first.admitted
    for at in (200, 700, 1200, 1700):
        recovering = qos.admit(
            job(f"recover-{at}", at, kind="speech"),
            snap(at, fps=60), now_ms=at,
        )
        assert not recovering.admitted
    # 200 -> 2200 is a stable 2-second recovery window.
    admitted = qos.admit(
        job("recovered", 2200, kind="speech"),
        snap(2200, fps=60), now_ms=2200,
    )
    assert admitted.admitted


def test_private_game_voicing_prefers_cpu_under_contention(
    qos: AdaptiveQoS,
) -> None:
    result = qos.admit(
        job("auto-voice", 1000, kind="speech", device="auto"),
        snap(1000), now_ms=1000,
    )
    assert result.admitted and result.device == "cpu"


def test_private_status_never_grants_broadcast_permission(
    qos: AdaptiveQoS,
) -> None:
    row = qos.admit(job("sample", 1000), snap(1000), now_ms=1000)
    assert row.admitted
    assert not hasattr(row, "authorized_to_broadcast")
    assert qos.status()["enabled"] is True
