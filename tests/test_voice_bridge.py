"""The UI bridge for voice calls: actions in, "voice" events out, one call at a time."""
import json
import threading

import pytest

from star.voice.bridge import VOICE_ACTIONS, VoiceBridge
from star.voice.runtime import Engines
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


def make_bridge(tmp_path, replies=("Yes, love. I can hear you.",), fail_engines=False):
    events, saved, built = [], [], {"engines": 0}

    class Factories:
        @staticmethod
        def engines(settings, progress):
            if fail_engines:
                raise RuntimeError("Voice model file missing: kokoro-v1.0.onnx")
            built["engines"] += 1
            progress("Loading Star's voice")
            return Engines(FakeVAD(), None, FakeASR({1: TEXT}), FakeTTS(seconds_per_word=0.02), {})

        @staticmethod
        def brain(settings):
            return FakeBrain(list(replies))

        @staticmethod
        def microphone(device):
            return FakeMicrophone()

        @staticmethod
        def speaker(sample_rate, device):
            return ContextSpeaker()

        @staticmethod
        def devices():
            return [{"index": 0, "kind": "input", "name": "Fake mic", "default": True}]

    bridge = VoiceBridge(lambda call_id, data: events.append((call_id, data)),
                         settings_path=tmp_path / "voice.json",
                         save_turn=lambda user, reply: saved.append((user, reply)), factories=Factories)
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
    assert "voiceStartCall" in VOICE_ACTIONS and len(VOICE_ACTIONS) == 18      # 14 + 4 role-play voice library actions
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


def test_character_library_actions_refuse_clones(tmp_path):
    bridge, _events, _saved, _built = make_bridge(tmp_path)
    bridge.handle("voiceSaveSettings", {"settings": {"expressive_home": str(tmp_path / "expr")}})
    out = bridge.handle("voiceCreateCharacter", {"name": "Brine", "description": "A gruff old sea captain, deep voice."})
    assert [c["name"] for c in out["characters"]] == ["Brine"] and "whisper" in out["styles"]
    with pytest.raises(PermissionError, match="consent"):
        bridge.handle("voiceCreateCharacter", {"name": "Sam", "kind": "clone"})
    cid = out["characters"][0]["id"]
    assert bridge.handle("voiceUpdateCharacter", {"id": cid, "style": "serious"})["characters"][0]["style"] == "serious"
    assert bridge.handle("voiceDeleteCharacter", {"id": cid})["characters"] == []
