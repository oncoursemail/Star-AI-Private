"""Workload-isolated calibration tests for real-time Star gaming and VTuber voice.

These offline fixtures do not measure a real game, OBS, GPU or speech device.
"""
from __future__ import annotations

import pytest

from star.stream_budget import StreamTelemetry
from star.stream_qos import AdaptiveQoS, InferenceJob, QoSSnapshot


def snapshot(at: float, *, game: bool, live: bool = False,
             private: bool = False) -> QoSSnapshot:
    return QoSSnapshot(
        at, StreamTelemetry(live, game, 6200, 8192, 60, 0),
        16000, 30, private_stream_rehearsal=private,
    )


def inference(identifier: str, at: float, *, kind: str = "vision",
              device: str = "gpu", ttl: float = 800) -> InferenceJob:
    return InferenceJob(identifier, kind, at, at + ttl, 100, 256, device)


def calibrate(q: AdaptiveQoS, *, prefix: str, game: bool,
              live: bool = False, private: bool = False,
              kind: str = "vision", device: str = "gpu",
              duration: float = 300) -> None:
    for i in range(5):
        at = 1000 + i * 3000
        result = q.admit(
            inference(f"{prefix}-{i}", at, kind=kind, device=device,
                      ttl=duration + 500),
            snapshot(at, game=game, live=live, private=private),
            now_ms=at,
        )
        assert result.admitted, result.reason
        assert q.finish(result.ticket, now_ms=at + duration, succeeded=True)


def enabled() -> AdaptiveQoS:
    q = AdaptiveQoS()
    q.enable(owner_approved=True)
    return q


def test_game_without_obs_never_certifies_live_game_vision_latency() -> None:
    q = enabled()
    calibrate(q, prefix="game", game=True, duration=300)
    assert q.status()["route_p95_ms"]["vision:gpu:game_only"] == 300
    denied = q.admit(inference("live", 17000),
                     snapshot(17000, game=True, live=True), now_ms=17000)
    assert not denied.admitted
    assert denied.reason == "no_calibrated_deadline_safe_route_or_headroom"


def test_private_rehearsal_certifies_matching_live_game_load() -> None:
    q = enabled()
    calibrate(q, prefix="private", game=True, private=True, duration=300)
    assert q.status()["route_p95_ms"]["vision:gpu:game_stream"] == 300
    admitted = q.admit(inference("live", 17000),
                       snapshot(17000, game=True, live=True), now_ms=17000)
    assert admitted.admitted
    assert admitted.predicted_p95_ms == 300
    assert admitted.device == "gpu"


def test_rehearsal_must_include_game_to_certify_live_game() -> None:
    q = enabled()
    calibrate(q, prefix="stream-only", game=False, private=True)
    denied = q.admit(inference("live-game", 17000),
                     snapshot(17000, game=True, live=True), now_ms=17000)
    assert not denied.admitted
    assert "vision:gpu:stream_only" in q.status()["route_p95_ms"]


def test_live_streaming_latency_does_not_certify_game_only_or_idle() -> None:
    q = enabled()
    calibrate(q, prefix="live", game=False, live=True,
              kind="speech", device="cpu", duration=900)
    # A nonlive game session has different performance demands.
    result = q.admit(
        inference("game", 17000, kind="speech", device="cpu", ttl=400),
        snapshot(17000, game=True), now_ms=17000,
    )
    assert result.admitted
    assert result.predicted_p95_ms is None  # unmeasured, never borrowed
    assert "speech:cpu:stream_only" in q.status()["route_p95_ms"]


def test_game_only_speech_p95_not_used_to_claim_fast_stream_speech() -> None:
    q = enabled()
    calibrate(q, prefix="game-speech", game=True,
              kind="speech", device="cpu", duration=1200)
    # An unmeasured speech route can still be attempted when the host has
    # sufficient slack. It is not described as a measured-fast route.
    result = q.admit(
        inference("live-speech", 17000, kind="speech", device="cpu", ttl=600),
        snapshot(17000, game=True, live=True), now_ms=17000,
    )
    assert result.admitted
    assert result.reason == "unmeasured_host_must_verify"
    assert result.predicted_p95_ms is None


def test_matched_private_speech_p95_rejects_unachievable_live_deadline() -> None:
    q = enabled()
    calibrate(q, prefix="slow-private-speech", game=True, private=True,
              kind="speech", device="cpu", duration=1200)
    refused = q.admit(
        inference("live-too-short", 17000, kind="speech", device="cpu", ttl=600),
        snapshot(17000, game=True, live=True), now_ms=17000,
    )
    assert not refused.admitted


def test_live_game_speech_is_separate_from_non_game_live_speech() -> None:
    q = enabled()
    calibrate(q, prefix="non-game-live", game=False, live=True,
              kind="speech", device="cpu", duration=1100)
    attempt = q.admit(
        inference("gaming-speech", 17000, kind="speech", device="cpu", ttl=700),
        snapshot(17000, game=True, live=True), now_ms=17000,
    )
    assert attempt.admitted and attempt.predicted_p95_ms is None


@pytest.mark.parametrize("invalid", [1, "yes", None, 0.0, [], {}])
def test_rehearsal_flag_requires_a_real_boolean(invalid: object) -> None:
    with pytest.raises(ValueError, match="trusted host bool"):
        QoSSnapshot(
            1000, StreamTelemetry(False, True, 6200, 8192, 60, 0),
            16000, 30, private_stream_rehearsal=invalid,
        )


def test_conflicting_private_and_live_flags_rejected() -> None:
    with pytest.raises(ValueError, match="cannot also be private"):
        snapshot(1000, live=True, game=True, private=True)


def test_route_calibration_remains_disabled_without_opt_in() -> None:
    q = AdaptiveQoS()
    result = q.admit(inference("not-enabled", 1000),
                     snapshot(1000, game=True, private=True), now_ms=1000)
    assert not result.admitted
    assert result.reason == "owner_opt_in_missing"
