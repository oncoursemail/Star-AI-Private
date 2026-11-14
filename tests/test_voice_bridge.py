"""The UI bridge for voice calls: actions in, "voice" events out, one call at a time."""
import json
import threading
import time

import pytest

from star.voice.bridge import VOICE_ACTIONS, VoiceBridge
from star.voice.runtime import Engines
from star.voice.room import CueIntent, CueSource, RoomAction, RoomCue
from star.voice.settings import STAR_VOICE
from voice_fakes import FakeASR, FakeBrain, FakeSpeaker, FakeTTS, FakeVAD, quiet, speech, wait_for

TEXT = "can you hear me star"


class FakeMicrophone:
    """Plays one utterance, then room silence until closed."""

    def __init__(self):
        self.closed = threading.Event()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()

    def close(self):
        self.closed.set()

    def __iter__(self):
        for frame in speech(1, 20) + quiet(40):
            yield frame
        while not self.closed.wait(0.005):
            yield quiet(1)[0]


class ContextSpeaker(FakeSpeaker):
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.stop()


def make_bridge(tmp_path, replies=("Yes, love. I can hear you.",), fail_engines=False,
                room_moderator=None, brain_first_delay=0.0, brain_delay=0.0, tts_seconds_per_word=0.02):
    events, saved, built = [], [], {"engines": 0, "microphones": 0, "input_enabled": None}

    class Factories:
        @staticmethod
        def engines(settings, progress, input_enabled=True):
            built["input_enabled"] = input_enabled
            if fail_engines:
                raise RuntimeError("Voice model file missing: kokoro-v1.0.onnx")
            built["engines"] += 1
            progress("Loading Star's voice")
            return Engines(FakeVAD(), None, FakeASR({1: TEXT}), FakeTTS(seconds_per_word=tts_seconds_per_word), {})

        @staticmethod
        def brain(settings):
            return FakeBrain(list(replies), first_delay=brain_first_delay, delay=brain_delay)

        @staticmethod
        def microphone(device):
            built["microphones"] += 1
            return FakeMicrophone()

        @staticmethod
        def speaker(sample_rate, device):
            return ContextSpeaker()

        @staticmethod
        def devices():
            return [{"index": 0, "kind": "input", "name": "Fake mic", "default": True}]

    bridge = VoiceBridge(lambda call_id, data: events.append((call_id, data)),
                         settings_path=tmp_path / "voice.json",
                         save_turn=lambda user, reply: saved.append((user, reply)), factories=Factories,
                         room_moderator=room_moderator)
    return bridge, events, saved, built


def kinds(events):
    return [data["type"] for _call, data in events]


def test_a_call_started_from_the_ui_streams_events_and_saves_the_turn(tmp_path):
    bridge, events, saved, built = make_bridge(tmp_path)
    started = bridge.handle("voiceStartCall", {"settings": {"voice": "bella", "speed": 0.9, "call_mode": "hands-free"},
                                               "micConsent": True}, "req-7")
    assert started["callId"] == "req-7" and started["settings"]["voice"] == "bella"
    with pytest.raises(RuntimeError, match="already running"):
        bridge.handle("voiceStartCall", {"micConsent": True}, "req-8")
    assert wait_for(lambda: "turn_metrics" in kinds(events))
    assert all(call_id == "req-7" for call_id, _data in events)
    states = [d["state"] for _c, d in events if d["type"] == "state"]
    assert states[:5] == ["starting", "listening", "user_speaking", "thinking", "speaking"]
    assert {"progress", "speech_started", "final_transcript", "assistant_delta", "assistant_sentence"} <= set(kinds(events))
    assert [d["text"] for _c, d in events if d["type"] == "final_transcript"] == [TEXT]
    assert saved == [(TEXT, "Yes, love. I can hear you.")]
    json.dumps([data for _call, data in events])                 # every event must be JSON for the web UI

    status = bridge.handle("voiceStatus", {})
    assert status["inCall"] and status["callId"] == "req-7" and status["state"] in {"listening", "speaking"}
    assert status["audioDiagnostics"] == {"microphone": {}, "speaker": {}}
    assert bridge.handle("voiceSetMuted", {"muted": True}) == {"muted": True}
    assert bridge.handle("voiceInterrupt", {}) == {"interrupted": True}
    assert bridge.handle("voiceStopCall", {}) == {"stopped": True}
    assert kinds(events)[-1] == "ended" and len(events[-1][1]["turns"]) == 1
    assert bridge.handle("voiceStatus", {})["inCall"] is False
    assert bridge.handle("voiceStopCall", {}) == {"stopped": False}

    bridge.handle("voiceStartCall", {"micConsent": True, "settings": {"call_mode": "hands-free"}}, "req-9")                 # second call reuses the loaded engines
    assert wait_for(lambda: ("req-9", {"type": "state", "state": "listening"}) in events)
    bridge.close()
    assert built["engines"] == 1


def test_start_failures_are_reported_as_events_and_leave_no_call_behind(tmp_path):
    bridge, events, _saved, _built = make_bridge(tmp_path, fail_engines=True)
    bridge.handle("voiceStartCall", {"micConsent": True}, "req-1")
    assert wait_for(lambda: kinds(events)[-1:] == ["ended"])
    assert "Voice model file missing" in [d for _c, d in events if d["type"] == "error"][0]["message"]
    assert bridge.handle("voiceStatus", {})["inCall"] is False


def test_actions_are_validated_and_settings_round_trip(tmp_path):
    bridge, _events, _saved, _built = make_bridge(tmp_path)
    assert "voiceStartCall" in VOICE_ACTIONS and len(VOICE_ACTIONS) == 14
    with pytest.raises(PermissionError):
        bridge.handle("deleteEverything", {})
    for action in ("voiceInterrupt", "voiceSetMuted"):
        with pytest.raises(RuntimeError, match="No voice call"):
            bridge.handle(action, {})
    with pytest.raises(ValueError):
        bridge.handle("voiceStartCall", {"settings": {"voice": "../x"}}, "bad")
    assert bridge.handle("voiceStatus", {})["inCall"] is False   # a rejected start leaves nothing running

    assert bridge.handle("voiceGetSettings", {})["settings"]["voice"] == STAR_VOICE
    saved = bridge.handle("voiceSaveSettings", {"settings": {"voice": "blend-heart-nicole", "output": "speakers"}})
    assert saved["settings"]["voice"] == "blend-heart-nicole"
    assert json.loads((tmp_path / "voice.json").read_text(encoding="utf-8"))["output"] == "speakers"
    again = bridge.handle("voiceGetSettings", {})
    assert again["settings"]["voice"] == "blend-heart-nicole" and "small.en" in again["choices"]["asr_model"]
    with pytest.raises(ValueError):
        bridge.handle("voiceSaveSettings", {"settings": {"speed": 9}})
    (tmp_path / "voice.json").write_text("{broken", encoding="utf-8")
    assert bridge.handle("voiceGetSettings", {})["settings"]["voice"] == STAR_VOICE     # damaged file -> defaults

    voices = bridge.handle("voiceListVoices", {})["voices"]
    heart = next(v for v in voices if v["id"] == "heart")                # the catalog keeps the audition ids
    assert heart["engine"] == "kokoro" and heart["recipe"] == [["af_heart", 1.0]] and heart["callable"] is True
    assert bridge.handle("voiceListDevices", {})["devices"][0]["name"] == "Fake mic"


def test_status_reports_missing_pieces_without_loading_anything(tmp_path, monkeypatch):
    bridge, _events, _saved, built = make_bridge(tmp_path)
    monkeypatch.setenv("STAR_VOICE_MODELS", str(tmp_path / "no-models"))
    monkeypatch.delenv("STAR_SERVER_URL", raising=False)
    status = bridge.handle("voiceStatus", {})
    assert status["available"] is False and status["serverConfigured"] is False and status["state"] == "idle"
    assert status["missingPackages"] or status["missingModels"]
    assert built["engines"] == 0



def _room_cue(event_id: str) -> RoomCue:
    now = time.monotonic()
    return RoomCue(
        event_id=event_id,
        speaker_id="opaque-viewer-1",
        source=CueSource.CHAT,
        intent=CueIntent.DIRECT_QUESTION,
        addressed_to_star=True,
        confidence=0.99,
        started_at=now - 0.2,
        ended_at=now,
    )


def test_room_host_is_opt_in_and_not_exposed_as_a_frontend_action(tmp_path):
    bridge, events, _saved, _built = make_bridge(tmp_path)
    assert "voiceRoomMessage" not in VOICE_ACTIONS
    bridge.handle("voiceStartCall", {"micConsent": True, "settings": {"call_mode": "hands-free"}}, "plain-call")
    try:
        assert wait_for(lambda: ("plain-call", {"type": "state", "state": "listening"}) in events)
        with pytest.raises(PermissionError, match="not explicitly enabled"):
            bridge.submit_room_message("plain-call", _room_cue("blocked"), "Hello STAR")
        assert bridge.handle("voiceStatus", {})["roomEnabled"] is False
    finally:
        bridge.close()


def test_room_start_requires_explicit_consent_sources_and_chat_moderator(tmp_path):
    bridge, _events, _saved, _built = make_bridge(tmp_path)
    with pytest.raises(PermissionError, match="roomConsent"):
        bridge.handle("voiceStartCall", {
            "micConsent": True,
            "roomSources": ["chat"],
        }, "missing-room-consent")
    with pytest.raises(ValueError, match="moderation callback"):
        bridge.handle("voiceStartCall", {
            "micConsent": True,
            "roomConsent": True,
            "roomSources": ["chat"],
        }, "missing-moderator")
    with pytest.raises(ValueError, match="at least one"):
        bridge.handle("voiceStartCall", {
            "micConsent": True,
            "roomConsent": True,
            "roomSources": [],
        }, "missing-source")
    bridge.close()


def test_room_host_auto_dispatches_queued_chat_and_keeps_it_out_of_saved_turns(tmp_path):
    bridge, events, saved, _built = make_bridge(
        tmp_path,
        replies=(
            "Microphone call is working.",
            "The first room answer is deliberately long enough to keep the spoken response active while another viewer asks a question.",
            "I have the next viewer question now.",
        ),
        room_moderator=lambda _cue, _text: True,
        brain_first_delay=0.04,
        brain_delay=0.002,
        tts_seconds_per_word=0.035,
    )
    started = bridge.handle("voiceStartCall", {
        "micConsent": True,
        "roomConsent": True,
        "roomSources": ["chat"],
        "settings": {"call_mode": "hands-free"},
    }, "room-call")
    assert started["roomEnabled"] is True and started["roomSources"] == ["chat"]
    try:
        assert wait_for(lambda: len([d for c, d in events if c == "room-call" and d["type"] == "turn_metrics"]) >= 1)
        assert wait_for(
            lambda: bridge._call is not None
            and bridge._call.session is not None
            and bridge._call.session.state == "listening"
            and not bridge._call.session.busy()
        )
        first = bridge.submit_room_message("room-call", _room_cue("room-first"), "Say hello to the stream.")
        assert first.action is RoomAction.RESPOND
        second = bridge.submit_room_message("room-call", _room_cue("room-second"), "What are we building today?")
        assert second.action is RoomAction.QUEUE

        assert wait_for(lambda: len([d for c, d in events if c == "room-call" and d["type"] == "room_message_received"]) == 2)
        assert wait_for(lambda: len([d for c, d in events if c == "room-call" and d["type"] == "turn_metrics"]) >= 3)
        dispatches = [d for c, d in events if c == "room-call" and d["type"] == "room_dispatch"]
        assert any(d["status"] == "dispatched" and d["event_id"] == "room-second" for d in dispatches)
        assert saved == [(TEXT, "Microphone call is working.")]
        status = bridge.handle("voiceStatus", {})
        assert status["roomEnabled"] is True
        assert status["roomPending"] == 0
        assert status["roomStats"]["accepted"] == 2
        assert status["roomStats"]["dispatch_started"] == 1
    finally:
        bridge.close()



def test_room_only_call_skips_microphone_and_local_asr_vad_loading(tmp_path):
    bridge, events, saved, built = make_bridge(
        tmp_path,
        replies=("A room-only response with no local microphone.",),
        room_moderator=lambda _cue, _text: True,
    )
    started = bridge.handle("voiceStartCall", {
        "roomOnly": True,
        "roomConsent": True,
        "roomSources": ["chat"],
        # No micConsent: room-only mode never opens the microphone.
    }, "room-only-call")
    assert started["roomOnly"] is True and started["roomEnabled"] is True
    try:
        assert wait_for(lambda: ("room-only-call", {"type": "state", "state": "listening"}) in events)
        assert built["engines"] == 1
        assert built["input_enabled"] is False
        assert built["microphones"] == 0
        decision = bridge.submit_room_message(
            "room-only-call",
            _room_cue("room-only-question"),
            "Can you explain what you are building?",
        )
        assert decision.action is RoomAction.RESPOND
        assert wait_for(lambda: any(
            call_id == "room-only-call" and data["type"] == "room_message_received"
            for call_id, data in events
        ))
        assert wait_for(lambda: any(
            call_id == "room-only-call" and data["type"] == "turn_metrics"
            for call_id, data in events
        ))
        status = bridge.handle("voiceStatus", {})
        assert status["roomOnly"] is True and status["roomEnabled"] is True
        assert saved == []
    finally:
        bridge.close()


def test_status_distinguishes_room_only_requirements_from_local_asr(tmp_path, monkeypatch):
    from importlib.machinery import ModuleSpec

    bridge, _events, _saved, _built = make_bridge(tmp_path)
    models = tmp_path / "models"
    models.mkdir()
    (models / "kokoro-v1.0.onnx").write_bytes(b"model")
    (models / "voices-v1.0.bin").write_bytes(b"voices")
    monkeypatch.setenv("STAR_VOICE_MODELS", str(models))

    def fake_find_spec(module):
        return None if module == "faster_whisper" else ModuleSpec(module, loader=None)

    monkeypatch.setattr("star.voice.bridge.importlib.util.find_spec", fake_find_spec)
    try:
        status = bridge.handle("voiceStatus", {})
        assert status["available"] is False
        assert status["missingPackages"] == ["faster-whisper"]
        assert status["roomOnlyAvailable"] is True
        assert status["roomOnlyMissingPackages"] == []
        assert status["roomOnlyMissingModels"] == []
    finally:
        bridge.close()
