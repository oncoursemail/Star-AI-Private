"""Tests for trusted, bounded ingress into an opted-in room call."""
import time

import pytest

from star.voice.call import CallConfig, CallSession
from star.voice.room import CueIntent, CueSource, RoomAction, RoomCue, RoomTurnDirector
from star.voice.room_host import RoomHostConfig, RoomStreamHost
from star.voice.room_payloads import RoomPayloadStore
from voice_fakes import Events, FakeASR, FakeBrain, FakeSpeaker, FakeTTS, FakeVAD


def make_cue(event_id: str, *, source: CueSource = CueSource.CHAT,
             speaker_id: str = "opaque-speaker", now: float | None = None,
             intent: CueIntent = CueIntent.DIRECT_QUESTION, addressed: bool = True,
             resolves_event_id: str | None = None) -> RoomCue:
    ended = time.monotonic() if now is None else now
    return RoomCue(
        event_id=event_id,
        speaker_id=speaker_id,
        source=source,
        intent=intent,
        addressed_to_star=addressed,
        confidence=0.99,
        started_at=ended - 0.2,
        ended_at=ended,
        resolves_event_id=resolves_event_id,
    )


def make_host(config: RoomHostConfig, *, moderate_chat=None, replies=None, clock=time.monotonic,
              tts_seconds_per_word: float = 0.01):
    events = Events()
    brain = FakeBrain(replies or ["Hello, I can hear you."])
    session = CallSession(
        vad=FakeVAD(),
        asr=FakeASR({}),
        brain=brain,
        tts=FakeTTS(seconds_per_word=tts_seconds_per_word),
        speaker=FakeSpeaker(),
        config=CallConfig(partial_transcripts=False),
        on_event=events,
        clock=clock,
        room_director=RoomTurnDirector(),
        room_payload_store=RoomPayloadStore(),
    )
    session.start()
    host = RoomStreamHost(session, config, moderate_chat=moderate_chat, clock=clock)
    return host, session, events, brain


def test_room_host_requires_explicit_sources_and_chat_moderation():
    with pytest.raises(ValueError, match="non-empty frozenset"):
        RoomHostConfig(allowed_sources=frozenset())
    with pytest.raises(ValueError, match="moderation callback"):
        host_config = RoomHostConfig(allowed_sources=frozenset({CueSource.CHAT}))
        make_host(host_config)


def test_disabled_source_is_rejected_before_payload_storage():
    config = RoomHostConfig(allowed_sources=frozenset({CueSource.AUDIO}))
    host, session, _events, _brain = make_host(config)
    try:
        decision = host.submit(make_cue("chat-1"), "Hello STAR")
        assert decision.action is RoomAction.WAIT
        assert decision.reason == "source_not_enabled"
        assert len(session.room_payload_store) == 0
        assert host.stats.rejected_source == 1
    finally:
        host.close()
        session.stop()


def test_chat_moderation_fails_closed_on_rejection_and_exception():
    config = RoomHostConfig(allowed_sources=frozenset({CueSource.CHAT}))
    host, session, _events, _brain = make_host(config, moderate_chat=lambda _cue, _text: False)
    try:
        decision = host.submit(make_cue("rejected"), "spam")
        assert decision.action is RoomAction.IGNORE
        assert decision.reason == "chat_moderation_rejected"
        assert len(session.room_payload_store) == 0
    finally:
        host.close()
        session.stop()

    def broken(_cue, _text):
        raise RuntimeError("moderator unavailable")

    host, session, _events, _brain = make_host(config, moderate_chat=broken)
    try:
        decision = host.submit(make_cue("error"), "question")
        assert decision.action is RoomAction.WAIT
        assert decision.reason == "chat_moderation_error"
        assert host.stats.moderation_errors == 1
        assert len(session.room_payload_store) == 0
    finally:
        host.close()
        session.stop()


def test_audio_source_can_be_used_without_chat_moderator_when_explicitly_enabled():
    config = RoomHostConfig(allowed_sources=frozenset({CueSource.AUDIO}))
    host, session, events, brain = make_host(config)
    try:
        decision = host.submit(make_cue("audio-1", source=CueSource.AUDIO), "Can you hear me?")
        assert decision.action is RoomAction.RESPOND
        assert session.wait_idle(5)
        assert len(brain.requests) == 1
        assert events.of("room_message_received")[0]["source"] == "transcript"
        assert host.stats.accepted == 1
    finally:
        host.close()
        session.stop()


def test_rate_limit_is_bounded_per_opaque_speaker_and_source():
    config = RoomHostConfig(
        allowed_sources=frozenset({CueSource.CHAT}),
        max_events_per_source=10,
        max_events_per_speaker=1,
    )
    moderated = []

    def moderate(item, _text):
        moderated.append(item.event_id)
        return True

    host, session, _events, _brain = make_host(config, moderate_chat=moderate)
    try:
        first = host.submit(make_cue("first"), "First question")
        second = host.submit(make_cue("second"), "Second question")
        assert first.action is RoomAction.RESPOND
        assert second.action is RoomAction.WAIT
        assert second.reason == "room_rate_limited"
        assert host.stats.rejected_rate == 1
        assert moderated == ["first"]
        assert len(session.room_payload_store) == 0
    finally:
        host.close()
        session.stop()


def test_oversized_text_is_rejected_before_call_session():
    config = RoomHostConfig(
        allowed_sources=frozenset({CueSource.CHAT}),
        max_text_bytes=8,
    )
    host, session, _events, _brain = make_host(config, moderate_chat=lambda _cue, _text: True)
    try:
        decision = host.submit(make_cue("large"), "This message is too large")
        assert decision.action is RoomAction.WAIT
        assert decision.reason == "room_message_too_large"
        assert len(session.room_payload_store) == 0
        assert host.stats.rejected_oversize == 1
    finally:
        host.close()
        session.stop()


def test_host_close_revokes_ingress_and_clears_rate_limit_state():
    config = RoomHostConfig(allowed_sources=frozenset({CueSource.AUDIO}))
    host, session, _events, _brain = make_host(config)
    host.close()
    try:
        decision = host.submit(make_cue("after-close", source=CueSource.AUDIO), "Too late")
        assert decision.action is RoomAction.WAIT
        assert decision.reason == "room_host_closed"
        assert host.closed
        assert host.stats.rejected_closed == 1
    finally:
        session.stop()


def test_rate_limit_rejects_invalid_host_clock_without_accepting_content():
    clock_value = [float("nan")]
    config = RoomHostConfig(allowed_sources=frozenset({CueSource.AUDIO}))
    host, session, _events, _brain = make_host(config, clock=lambda: clock_value[0])
    try:
        decision = host.submit(make_cue("bad-clock", source=CueSource.AUDIO), "Question")
        assert decision.action is RoomAction.WAIT
        assert decision.reason == "host_clock_unavailable"
        assert len(session.room_payload_store) == 0
    finally:
        host.close()
        session.stop()


def test_invalid_opaque_speaker_id_is_rejected_before_rate_limit_state():
    config = RoomHostConfig(allowed_sources=frozenset({CueSource.AUDIO}))
    host, session, _events, _brain = make_host(config)
    try:
        item = make_cue("invalid-speaker", source=CueSource.AUDIO, speaker_id="x" * 129)
        decision = host.submit(item, "Question")
        assert decision.action is RoomAction.WAIT
        assert decision.reason == "invalid_room_cue"
        assert host.stats.rejected_invalid == 1
        assert len(host._speaker_times) == 0
    finally:
        host.close()
        session.stop()


def test_duplicate_provider_event_is_dropped_before_moderation():
    moderated = []
    config = RoomHostConfig(allowed_sources=frozenset({CueSource.CHAT}))

    def moderate(item, _text):
        moderated.append(item.event_id)
        return True

    host, session, _events, _brain = make_host(config, moderate_chat=moderate)
    try:
        item = make_cue("provider-redelivery")
        first = host.submit(item, "One viewer message")
        second = host.submit(item, "One viewer message")
        assert first.action is RoomAction.RESPOND
        assert second.action is RoomAction.IGNORE
        assert second.reason == "duplicate_room_event"
        assert moderated == ["provider-redelivery"]
        assert host.stats.rejected_duplicate == 1
    finally:
        host.close()
        session.stop()



def test_human_resolution_stops_matching_room_reply_without_speaking_again():
    config = RoomHostConfig(allowed_sources=frozenset({CueSource.AUDIO}))
    host, session, _events, brain = make_host(
        config,
        replies=["I can explain the solution in much more detail."],
        tts_seconds_per_word=0.2,
    )
    try:
        first = host.submit(
            make_cue("question-1", source=CueSource.AUDIO, speaker_id="viewer-a"),
            "What happened?",
        )
        assert first.action is RoomAction.RESPOND
        assert wait_for(lambda: session.speaker.pending_seconds() > 0, timeout=2)

        resolution = host.submit(
            make_cue(
                "resolution-1",
                source=CueSource.AUDIO,
                speaker_id="viewer-b",
                intent=CueIntent.HUMAN_RESOLUTION,
                addressed=False,
                resolves_event_id="question-1",
            ),
            "Another viewer already answered that question.",
        )
        assert resolution.action is RoomAction.STOP
        assert resolution.reason == "human_resolved_request"
        assert session.wait_idle(5)
        assert len(brain.requests) == 1
        assert session.turns[0].interrupt_reason == "room_human_resolved_request"
        assert session.speaker.stops >= 1
    finally:
        host.close()
        session.stop()
