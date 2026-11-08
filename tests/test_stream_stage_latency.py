"""Local-only, deterministic timing tests for the streaming stage.

These are timestamps attested by a trusted host, not OBS audio verification.
No microphone, TTS model, network, viewer identity, or GPU is used.
"""
from star.stream_director import StreamDirector, StreamSignal
from star.stream_stage import StarStage


def stage() -> StarStage:
    result = StarStage(
        director=StreamDirector(gap_seconds=0),
        clock=lambda: 10.0,
    )
    result.enable(owner_approved=True)
    return result


def offer_success(s: StarStage, ident: str, at: float):
    assert s.offer(
        StreamSignal(
            ident, "game_success", at, f"independent-checkpoint-{ident}",
            evidence="observed", game_scope="private-lab",
        ),
        now=at,
    )
    plan = s.prepare(now=at)
    assert plan is not None
    return plan


def test_host_playback_latency_is_measured_only_after_audio_ack():
    s = stage()
    p = offer_success(s, "check-a", 10.0)
    assert s.metrics()["host_playback_latency"]["samples"] == 0
    assert s.queue_audio(p, now=10.05)
    assert s.metrics()["host_playback_latency"]["samples"] == 0
    assert s.acknowledge_audible(p, now=10.24)
    trace = s.metrics()["host_playback_latency"]
    assert trace["samples"] == 1
    assert trace["prepare_to_start_p50_ms"] == 240.0
    assert trace["prepare_to_start_p95_ms"] == 240.0
    assert trace["queued_to_start_p95_ms"] == 190.0
    assert trace["source"] == "trusted_host_playback_start_attestation_not_OBS"
    assert s.finish(p, now=10.5, played_to_end=True)
    assert s.metrics()["director"]["completed"] == 1


def test_failed_tts_never_creates_false_playback_sample():
    s = stage()
    p = offer_success(s, "missed-audio", 10.0)
    assert s.queue_audio(p, now=10.01)
    assert s.finish(p, now=10.02)
    trace = s.metrics()["host_playback_latency"]
    assert trace["samples"] == 0
    assert trace["prepare_to_start_p95_ms"] is None
    assert trace["queued_to_start_p95_ms"] is None
    assert s.metrics()["director"]["completed"] == 0


def test_backwards_host_clock_cannot_claim_playback_or_full_completion():
    s = stage()
    p = offer_success(s, "rewind", 20.0)
    assert s.queue_audio(p, now=20.1)
    assert not s.acknowledge_audible(p, now=20.05)
    assert s.metrics()["host_playback_latency"]["samples"] == 0
    assert s.metrics()["phase"] == "idle"
    assert s.metrics()["director"]["completed"] == 0

    later = offer_success(s, "rewind-two", 21.0)
    assert s.queue_audio(later, now=21.1)
    assert s.acknowledge_audible(later, now=21.2)
    assert not s.finish(later, now=21.19, played_to_end=True)
    assert s.metrics()["phase"] == "idle"
    assert s.metrics()["director"]["completed"] == 0
    assert s.metrics()["abandoned"] == 2


def test_replay_window_is_bounded_and_metrics_exclude_raw_identifiers():
    s = stage()
    for n in range(70):
        now = 100.0 + 50 * n
        p = offer_success(s, f"secret-event-{n}", now)
        assert s.queue_audio(p, now=now + 0.01)
        assert s.acknowledge_audible(p, now=now + 0.1 + n * 0.001)
        assert s.finish(p, now=now + 0.3, played_to_end=True)
    trace = s.metrics()["host_playback_latency"]
    assert trace["samples"] == 64
    assert trace["prepare_to_start_p50_ms"] == 137.0
    assert trace["prepare_to_start_p95_ms"] == 166.0
    assert trace["queued_to_start_p95_ms"] == 156.0
    assert "secret-event" not in str(s.metrics())
    assert "independent-checkpoint" not in str(s.metrics())
