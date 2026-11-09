"""Host-only long-session voice health / streaming admission regression tests."""

from dataclasses import replace

import pytest

from star.stream_director import StreamDirector, StreamSignal
from star.stream_long_session_voice_health import (
    LongSessionVoiceHealth,
    ReviewedVoiceTurn,
)
from star.stream_natural_turn_bridge import NaturalTurnBridge
from star.stream_turntaking import VoiceFrame


def turn(index: int, **overrides) -> ReviewedVoiceTurn:
    values = dict(
        turn_id=f"turn{index}",
        measured_at_ms=1000.0 + index * 20_000.0,
        first_audio_latency_ms=240.0,
        voice_consistency=0.95,
        grounded=True,
        repeated=False,
        interruption_respected=True,
    )
    values.update(overrides)
    return ReviewedVoiceTurn(**values)


def feed(health: LongSessionVoiceHealth, *, last_index: int = 15, change=None) -> None:
    for i in range(last_index + 1):
        sample = turn(i)
        if change is not None:
            sample = change(i, sample)
        assert health.ingest(
            sample,
            now_ms=sample.measured_at_ms + 50.0,
            host_verified=True,
        )


def healthy() -> LongSessionVoiceHealth:
    health = LongSessionVoiceHealth()
    health.enable(owner_approved=True)
    feed(health)
    return health


def voice_ready(host: NaturalTurnBridge, at: int = 301000) -> None:
    for ms in range(at - 350, at + 1, 50):
        assert host.observe_voice(VoiceFrame(ms, 50, 0.0, 0.0, True))


def make_signal(kind: str, *, at: int = 301000, name: str = "s") -> StreamSignal:
    return StreamSignal(
        name,
        kind,
        at / 1000,
        "Independent gameplay event.",
        speaker_id="viewer1" if kind.startswith("viewer") else "",
        evidence="observed",
    )


def bridge_advice(host: NaturalTurnBridge, at: int = 301000):
    return host.advise(
        now_ms=at,
        host_playout_active=False,
        gameplay_critical=False,
        output_healthy=True,
    )


def test_disabled_by_default_legacy_behavior():
    health = LongSessionVoiceHealth()
    assert health.advise(now_ms=100).status == "disabled"
    assert health.advise(now_ms=100).allow_optional_commentary
    assert not health.ingest(turn(0), now_ms=1050, host_verified=True)
    with pytest.raises(PermissionError):
        health.enable()
    health.enable(owner_approved=True)
    assert health.advise(now_ms=100).status == "stale"


def test_verified_long_session_requires_frozen_baseline_maturity_and_freshness():
    health = LongSessionVoiceHealth()
    health.enable(owner_approved=True)
    feed(health, last_index=14)
    advice = health.advise(now_ms=281060)
    assert advice.status == "warming"
    assert not advice.allow_optional_commentary
    assert advice.observed_baseline == 8
    assert advice.observed_recent == 7
    last = turn(15)
    assert health.ingest(last, now_ms=301050, host_verified=True)
    advice = health.advise(now_ms=301060)
    assert advice.status == "stable"
    assert advice.allow_optional_commentary
    assert not advice.authorizes_audio
    assert not advice.authorizes_broadcast
    assert health.advise(now_ms=331001).status == "stale"


@pytest.mark.parametrize(
    "update,reason",
    [
        (lambda i, v: replace(v, grounded=False) if i == 15 else v, "unverified_factual_claim"),
        (lambda i, v: replace(v, interruption_respected=False) if i == 15 else v, "interruption_not_respected"),
        (lambda i, v: replace(v, repeated=True) if i in (14, 15) else v, "repeated_spoken_turns"),
        (lambda i, v: replace(v, voice_consistency=0.40) if i >= 11 else v, "voice_consistency_regression"),
        (lambda i, v: replace(v, first_audio_latency_ms=990.0) if i >= 11 else v, "first_audio_latency_regression"),
    ],
)
def test_long_session_degradation_cases(update, reason):
    health = LongSessionVoiceHealth()
    health.enable(owner_approved=True)
    feed(health, change=update)
    advice = health.advise(now_ms=301060)
    assert advice.status == "degraded"
    assert advice.reason == reason
    assert not advice.allow_optional_commentary


@pytest.mark.parametrize(
    "kwargs",
    [
        {"first_audio_latency_ms": float("nan")},
        {"first_audio_latency_ms": True},
        {"voice_consistency": -0.01},
        {"voice_consistency": 1.01},
        {"voice_consistency": float("inf")},
        {"grounded": 1},
        {"repeated": None},
        {"interruption_respected": 0},
        {"turn_id": "my name/PII"},
        {"measured_at_ms": float("inf")},
    ],
)
def test_strict_host_quality_evidence_schema(kwargs):
    with pytest.raises(ValueError):
        turn(0, **kwargs)


def test_unverified_replayed_or_clock_reversed_evidence_fail_closed():
    health = healthy()
    assert not health.ingest(
        turn(16),
        now_ms=321050,
        host_verified=False,
    )
    assert health.advise(now_ms=321050).status == "faulted"
    assert not health.ingest(
        turn(16),
        now_ms=321050,
        host_verified=True,
    )
    health.disable()
    health.enable(owner_approved=True)
    assert health.ingest(turn(0), now_ms=1050, host_verified=True)
    assert not health.ingest(turn(0), now_ms=1050, host_verified=True)
    assert health.advise(now_ms=1050).status == "faulted"
    health.disable()
    health.enable(owner_approved=True)
    assert health.ingest(turn(0), now_ms=1050, host_verified=True)
    assert health.advise(now_ms=1049).status == "faulted"


def test_evidence_future_stale_or_capture_gap_faults():
    for sample, now_ms in (
        (turn(0), 900),
        (turn(0), 9000),
    ):
        h = LongSessionVoiceHealth()
        h.enable(owner_approved=True)
        assert not h.ingest(sample, now_ms=now_ms, host_verified=True)
        assert h.advise(now_ms=now_ms).status == "faulted"
    h = LongSessionVoiceHealth()
    h.enable(owner_approved=True)
    assert h.ingest(turn(0), now_ms=1050, host_verified=True)
    gap = turn(1, measured_at_ms=130001)
    assert not h.ingest(gap, now_ms=130010, host_verified=True)
    assert h.advise(now_ms=130010).status == "faulted"


def test_disabled_and_rearmed_session_cannot_reuse_old_stable_profile():
    h = healthy()
    assert h.advise(now_ms=301100).allow_optional_commentary
    h.disable()
    assert h.advise(now_ms=301100).status == "disabled"
    h.enable(owner_approved=True)
    assert not h.advise(now_ms=301100).allow_optional_commentary
    assert h.metrics()["baseline"] == 0
    assert "turn_id" not in h.metrics()


@pytest.mark.parametrize("value", [True, None, "8", float("nan"), -1, 1e20])
def test_invalid_clock_rejected(value):
    h = LongSessionVoiceHealth()
    with pytest.raises(ValueError):
        h.advise(now_ms=value)


def test_director_optional_filter_preserves_genuine_question_and_danger():
    director = StreamDirector(gap_seconds=0)
    director.enable(owner_approved=True)
    for kind in ("ambient", "viewer_question", "game_danger"):
        assert director.offer(make_signal(kind, at=301000, name=kind), now=301)
    candidate = director.propose(
        now=301,
        optional_commentary_allowed=False,
    )
    assert candidate is not None
    assert candidate.kind == "game_danger"
    assert director.complete(candidate, now=301, spoken=True)
    candidate = director.propose(now=301, optional_commentary_allowed=False)
    assert candidate is not None
    assert candidate.kind == "viewer_question"
    assert director.complete(candidate, now=301, spoken=True)
    assert director.propose(now=301, optional_commentary_allowed=False) is None
    assert director.propose(now=301, optional_commentary_allowed=True).kind == "ambient"
    with pytest.raises(ValueError):
        director.propose(now=301, optional_commentary_allowed=1)


def test_bridge_warming_suppresses_ambient_but_preserves_viewer_question():
    health = LongSessionVoiceHealth()
    health.enable(owner_approved=True)
    bridge = NaturalTurnBridge(voice_health=health)
    bridge.enable(owner_approved=True)
    voice_ready(bridge)
    assert bridge.offer(make_signal("ambient", name="ambient"), now_ms=301000)
    assert bridge_advice(bridge).action == "hold"
    assert bridge.offer(make_signal("viewer_question", name="question"), now_ms=301000)
    advice = bridge_advice(bridge)
    assert advice.action == "prepare"
    assert advice.intent.kind == "viewer_question"
    assert not advice.authorizes_playback


def test_bridge_revalidates_inflight_optional_speech_after_quality_regression():
    health = healthy()
    bridge = NaturalTurnBridge(
        voice_health=health,
        single_flight_tts=True,
        require_preplay_recheck=True,
    )
    bridge.enable(owner_approved=True)
    voice_ready(bridge, at=301050)
    assert bridge.offer(make_signal("ambient", at=301050), now_ms=301050)
    intent = bridge_advice(bridge, at=301050).intent
    assert intent is not None
    assert health.ingest(
        turn(16, measured_at_ms=301100, grounded=False),
        now_ms=301100,
        host_verified=True,
    )
    assert bridge.observe_voice(VoiceFrame(301100, 50, 0.0, 0.0, True))
    reviewed = bridge.revalidate_prepared(
        intent,
        now_ms=301100,
        host_playout_active=False,
        gameplay_critical=False,
        output_healthy=True,
        pcm_output_ready=True,
        host_verified=True,
    )
    assert reviewed.reason == "long_session_voice_health_hold"
    assert not reviewed.authorizes_playback
    assert not bridge.complete(intent, now_ms=301110, host_confirmed_spoken=True)


def test_director_not_affected_without_health_guard():
    bridge = NaturalTurnBridge()
    bridge.enable(owner_approved=True)
    voice_ready(bridge)
    assert bridge.offer(make_signal("ambient"), now_ms=301000)
    assert bridge_advice(bridge).action == "prepare"


def test_validation_strict_voice_guard_constructor():
    with pytest.raises(TypeError):
        NaturalTurnBridge(voice_health=object())
