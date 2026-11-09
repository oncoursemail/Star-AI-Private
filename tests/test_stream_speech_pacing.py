"""Deterministic, no-audio tests of host-observed natural speech pacing."""

from __future__ import annotations

import math

import pytest

from star.stream_budget import StreamTelemetry
from star.stream_director import SpeechIntent, StreamSignal
from star.stream_persona import event_message
from star.stream_speech_pacing import StreamSpeechPacer
from star.stream_stage import StarStage


def intent(kind: str = "game_success", *, deadline: float = 108.0) -> SpeechIntent:
    return SpeechIntent(
        signal_id="test1",
        kind=kind,
        context="Won a round",
        evidence="observed",
        deadline_at=deadline,
        instruction="brief",
        interrupt_current=False,
        untrusted_context=False,
    )


def observed(pacer: StreamSpeechPacer, *, game=True, stream=True, rate_seconds=0.6, first_id=1, count=8):
    for i in range(count):
        now = 60.0 + i
        assert pacer.observe_audible(
            route_id="cpu-tts-v1",
            sample_id=first_id + i,
            words_spoken=5,
            first_audible_s=now - 5 * rate_seconds,
            finished_audible_s=now,
            now_s=now,
            game_active=game,
            streaming_load=stream,
            host_confirmed=True,
        )


def test_off_by_default_and_never_authorizes_output():
    p = StreamSpeechPacer()
    assert p.advise(intent(), now_s=100, game_active=True, streaming_load=True).status == "disabled"
    assert not p.observe_audible(
        route_id="star-voice",
        sample_id=1,
        words_spoken=5,
        first_audible_s=1,
        finished_audible_s=3,
        now_s=3,
        game_active=True,
        streaming_load=True,
        host_confirmed=True,
    )
    with pytest.raises(PermissionError):
        p.enable(route_id="star-voice")
    p.enable(route_id="star-voice", owner_approved=True)
    advice = p.advise(intent(), now_s=100, game_active=True, streaming_load=True)
    assert advice.status == "no_host_context"
    assert advice.max_words is None
    assert not advice.authorizes_speech and not advice.authorizes_broadcast


def test_p90_audible_calibration_is_regime_scoped():
    p = StreamSpeechPacer()
    p.enable(owner_approved=True, route_id="cpu-tts-v1")
    observed(p, rate_seconds=0.9)
    hot = p.advise(intent(), now_s=100, game_active=True, streaming_load=True, host_context_verified=True)
    cold = p.advise(intent(), now_s=100, game_active=False, streaming_load=False, host_context_verified=True)
    assert hot.status == "bounded"
    assert hot.measured_samples == 8
    assert hot.reason == "host_playout_p90"
    assert hot.max_words < cold.max_words
    assert cold.reason == "conservative_cold_start"


def test_deadline_backlog_and_short_event_yield_to_silence():
    p = StreamSpeechPacer()
    p.enable(owner_approved=True, route_id="a")
    assert (
        p.advise(
            intent(deadline=101), now_s=100, game_active=True, streaming_load=True, host_context_verified=True
        ).status
        == "hold"
    )
    assert (
        p.advise(
            intent(deadline=108),
            now_s=100,
            queued_audio_ms=5500,
            game_active=True,
            streaming_load=True,
            host_context_verified=True,
        ).status
        == "hold"
    )
    assert p.metrics()["deferred"] == 2


def test_unconfirmed_replay_stale_and_clock_rollback_never_train_pacer():
    p = StreamSpeechPacer()
    p.enable(owner_approved=True, route_id="model-a")
    kwargs = dict(
        route_id="model-a",
        sample_id=1,
        words_spoken=10,
        first_audible_s=10,
        finished_audible_s=15,
        now_s=15,
        game_active=True,
        streaming_load=True,
    )
    assert not p.observe_audible(**kwargs)
    assert p.observe_audible(**kwargs, host_confirmed=True)
    assert not p.observe_audible(**kwargs, host_confirmed=True)
    assert not p.observe_audible(**dict(kwargs, sample_id=2, now_s=14), host_confirmed=True)
    assert not p.observe_audible(**dict(kwargs, sample_id=2, now_s=27), host_confirmed=True)
    assert p.metrics()["accepted"] == 1


def test_invalid_host_receipts_and_nonfinite_times_rejected():
    p = StreamSpeechPacer()
    p.enable(owner_approved=True, route_id="v1")
    baseline = dict(
        route_id="v1",
        sample_id=1,
        words_spoken=5,
        first_audible_s=1,
        finished_audible_s=3,
        now_s=3,
        game_active=True,
        streaming_load=True,
        host_confirmed=True,
    )
    for patch in (
        dict(sample_id=True),
        dict(words_spoken=2),
        dict(first_audible_s=math.nan),
        dict(now_s=math.inf),
        dict(game_active=1),
        dict(host_confirmed=1),
    ):
        with pytest.raises(ValueError):
            p.observe_audible(**{**baseline, **patch})

    assert p.metrics()["accepted"] == 0
    for patch in (dict(finished_audible_s=1), dict(finished_audible_s=200)):
        assert not p.observe_audible(**{**baseline, **patch})
    assert p.metrics()["accepted"] == 0


def test_route_reset_erasures_and_new_session_cold_start():
    p = StreamSpeechPacer()
    p.enable(owner_approved=True, route_id="cpu-tts-v1")
    observed(p)
    assert (
        p.advise(
            intent(), now_s=100, game_active=True, streaming_load=True, host_context_verified=True
        ).measured_samples
        == 8
    )
    with pytest.raises(RuntimeError):
        p.enable(owner_approved=True, route_id="v2")
    p.disable()
    p.enable(owner_approved=True, route_id="v2")
    assert (
        p.advise(
            intent(), now_s=100, game_active=True, streaming_load=True, host_context_verified=True
        ).measured_samples
        == 0
    )


def test_persona_word_guidance_is_optional_user_level_data():
    original = event_message(intent())
    bounded = event_message(intent(), max_words=12)
    assert original["role"] == bounded["role"] == "user"
    assert "spoken words" not in original["content"]
    assert "12 spoken words" in bounded["content"]
    assert "Won a round" in bounded["content"]
    for value in (True, 3, 65, 7.4):
        with pytest.raises(ValueError):
            event_message(intent(), max_words=value)


def telemetry(backlog: float = 0) -> StreamTelemetry:
    return StreamTelemetry(
        live=False,
        game_active=True,
        free_vram_mib=4000,
        total_vram_mib=8192,
        game_fps=60,
        speech_backlog_ms=backlog,
        private_stream_rehearsal=True,
    )


def test_stage_uses_pacer_only_when_opted_in_and_host_telemetry_present():
    p = StreamSpeechPacer()
    p.enable(owner_approved=True, route_id="cpu-tts-v1")
    observed(p, rate_seconds=0.9)
    stage = StarStage(clock=lambda: 100.0, speech_pacer=p)
    stage.enable(owner_approved=True)
    signal = StreamSignal(
        "win-one",
        "game_success",
        100.0,
        "Checkpoint cleared!",
        evidence="observed",
        game_scope="obby.v3",
    )
    assert stage.offer(signal, now=100.0)
    plan = stage.prepare(now=100.0, telemetry=telemetry(), current_game_scope="obby.v3")
    assert plan is not None
    assert "spoken words" in plan.context_record
    assert plan.expression == "joy"
    assert not plan.context_record.startswith("system")


def test_stage_defers_impossible_danger_commentary_without_speaking():
    p = StreamSpeechPacer()
    p.enable(owner_approved=True, route_id="voice")
    stage = StarStage(clock=lambda: 100.0, speech_pacer=p)
    stage.enable(owner_approved=True)
    assert stage.offer(
        StreamSignal("danger-one", "game_danger", 100.0, "Hazard!", evidence="observed", game_scope="obby.v3"),
        now=100.0,
    )
    assert stage.prepare(now=100.0, telemetry=telemetry(240), current_game_scope="obby.v3") is None
    assert stage.metrics()["pacing_deferred"] == 1


def test_legacy_stage_and_missing_host_load_do_not_inject_pacing_guidance():
    def make_stage(pacer=None):
        stage = StarStage(clock=lambda: 100.0, speech_pacer=pacer)
        stage.enable(owner_approved=True)
        assert stage.offer(
            StreamSignal(
                "question", "viewer_question", 100, "What next?", evidence="reported", speaker_id="viewer-one"
            ),
            now=100,
            moderated=True,
        )
        return stage

    p = StreamSpeechPacer()
    p.enable(owner_approved=True, route_id="voice")
    legacy = make_stage()
    guarded = make_stage(p)
    old = legacy.prepare(now=100)
    new = guarded.prepare(now=100)
    assert old is not None and new is not None
    assert "spoken words" not in old.context_record
    assert "spoken words" not in new.context_record


def test_wrong_voice_route_cannot_contaminate_samples():
    p = StreamSpeechPacer()
    p.enable(owner_approved=True, route_id="cpu-tts-v1")
    assert not p.observe_audible(
        route_id="different-speaker",
        sample_id=1,
        words_spoken=5,
        first_audible_s=10,
        finished_audible_s=13,
        now_s=13,
        game_active=True,
        streaming_load=True,
        host_confirmed=True,
    )
    assert p.metrics()["accepted"] == 0


def test_stage_exposes_and_enforces_machine_readable_word_budget_before_tts():
    p = StreamSpeechPacer()
    p.enable(owner_approved=True, route_id="cpu-tts-v1")
    observed(p, rate_seconds=0.9)
    stage = StarStage(clock=lambda: 100.0, speech_pacer=p)
    stage.enable(owner_approved=True)
    assert stage.offer(
        StreamSignal(
            "win-budget", "game_success", 100.0, "Checkpoint cleared!",
            evidence="observed", game_scope="obby.v3",
        ),
        now=100.0,
    )
    plan = stage.prepare(now=100.0, telemetry=telemetry(), current_game_scope="obby.v3")
    assert plan is not None and plan.max_words is not None
    too_long = " ".join(["word"] * (plan.max_words + 1))
    rejected = stage.review_response(plan, too_long, now=100.0)
    assert not rejected.eligible
    assert rejected.reason == "response_exceeds_word_budget"
    assert rejected.spoken_words == plan.max_words + 1
    assert rejected.max_words == plan.max_words
    assert not rejected.authorizes_audio and not rejected.authorizes_broadcast

    accepted = stage.review_response(plan, "We got it!", now=100.0)
    assert accepted.eligible
    assert accepted.reason == "within_word_budget"
    assert accepted.spoken_words == 3
    assert not accepted.authorizes_audio and not accepted.authorizes_broadcast


def test_stage_response_budget_counts_speakable_text_and_rejects_stale_plan():
    stage = StarStage(clock=lambda: 100.0)
    invalid = stage.review_response(None, "Hello.", now=100.0)
    assert not invalid.eligible and invalid.reason == "invalid_stage_plan"
    stage.enable(owner_approved=True)
    assert stage.offer(
        StreamSignal(
            "viewer-budget", "viewer_question", 100.0, "What happened?",
            evidence="reported", speaker_id="viewer-one",
        ),
        now=100.0,
        moderated=True,
    )
    plan = stage.prepare(now=100.0)
    assert plan is not None and plan.max_words is None
    advice = stage.review_response(
        plan, "Hello **there** — see [the notes](https://example.invalid).", now=100.0,
    )
    assert advice.eligible
    assert advice.reason == "legacy_unbounded"
    assert advice.spoken_words == 5
    assert not advice.authorizes_audio and not advice.authorizes_broadcast

    assert stage.queue_audio(plan, now=100.0)
    stale = stage.review_response(plan, "Too late.", now=100.0)
    assert not stale.eligible
    assert stale.reason == "stale_or_nonprepared_plan"