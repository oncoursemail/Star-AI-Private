"""Real SoundOutput lifecycle and buffers over fake PortAudio; no devices/models/calls."""
from contextlib import ExitStack
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from star.home import voicestack
from star.home.calls import DiscordCalls
from star.home.voicelink import HomeVoice
from star.senses import routes
from star.senses.output import SoundOutput


class Stream:
    def __init__(self, fail=False, **kwargs):
        self.kwargs, self.fail = kwargs, fail
        self.starts = self.stops = self.closes = 0
        self.active = False
    def start(self):
        self.starts += 1
        if self.fail: raise RuntimeError("fixture output startup failure")
        self.active = True
    def stop(self): self.stops += 1; self.active = False
    def close(self): self.closes += 1; self.active = False
    def pump(self, frames=2400):
        out = np.zeros((frames, self.kwargs["channels"]), dtype=np.float32)
        if self.active: self.kwargs["callback"](out, frames, None, None)
        return out


class TTS:
    def synthesize(self, text): yield b"\x00\x20" * 2400, 24000


class Checks(unittest.TestCase):
    def setUp(self):
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        self.streams, self.sources, self.fail_devices = [], [], set()
        self.construct_fail_devices = set()
        self.session_stops = self.brain_closes = self.warm_stops = 0
        self.settings = SimpleNamespace(monitor_device="", system_extra="", max_reply_tokens=80)
        self.tts = TTS()
        self.brain = SimpleNamespace(close=self._close_brain)
        self.warm = SimpleNamespace(stop=self._stop_warm)
        self.session = None
        self.device_list = [
            {"index": 4, "name": "CABLE Input", "kind": "output", "host": "Windows WASAPI", "rate": 24000, "channels": 1},
            {"index": 5, "name": "Owner monitor", "kind": "output", "host": "Windows WASAPI", "rate": 24000, "channels": 1},
        ]
        owner = self
        class Source:
            def __init__(self): self.closed = 0; owner.sources.append(self)
            def frames(self): return iter(())
            def close(self): self.closed += 1
        self.Source = Source
        for target, value in (
            ("star.voice.devices._sounddevice", lambda: SimpleNamespace(OutputStream=self._stream)),
            ("star.senses.routes.query_devices", lambda: self.device_list),
            ("star.home.voicestack._settings", lambda config: self.settings),
            ("star.home.voicestack._engines", lambda settings: SimpleNamespace(tts=self.tts)),
            ("star.home.voicestack._speaker", lambda speaker: speaker),
            ("star.voice.runtime.make_brain", lambda settings: self.brain),
            ("star.home.runtime.home_brain", lambda *args, **kwargs: self.brain),
            ("star.senses.instant.build_pc_session", self._build),
            ("star.senses.capture.LoopbackSource", Source),
        ):
            self.patches.enter_context(patch(target, value))

    def _stream(self, **kwargs):
        if kwargs["device"] in self.construct_fail_devices:
            raise RuntimeError("fixture stream construction failure")
        stream = Stream(fail=kwargs["device"] in self.fail_devices, **kwargs)
        self.streams.append(stream)
        return stream
    def _close_brain(self): self.brain_closes += 1
    def _stop_warm(self): self.warm_stops += 1
    def _stop_session(self): self.session_stops += 1
    def _build(self, settings, engines, speaker, **kwargs):
        self.session = SimpleNamespace(tts=engines.tts, speaker=speaker, stop=self._stop_session,
                                       start=lambda: None, feed=lambda frame: None,
                                       config=SimpleNamespace(emotion_person="owner", emotion_partner_adult=None))
        return self.session, self.warm

    def _assert_drains(self, speaker, stream):
        for pcm, rate in self.tts.synthesize("Fixture only"):
            speaker.play(pcm, rate)
        before = speaker.pending_seconds()
        out = stream.pump()
        self.assertGreater(before, 0)
        self.assertGreater(float(np.max(np.abs(out))), 0.01)
        self.assertLess(speaker.pending_seconds(), before)

    def test_actual_soundoutput_construction_alone_is_inactive(self):
        output = SoundOutput(device=4, rate=24000, channels=1)
        self.assertEqual(self.streams[0].starts, 0)
        self.assertFalse(self.streams[0].active)
        output.close()

    def test_standalone_factory_starts_actual_output_exactly_once_and_drains_tts(self):
        tts, speaker = voicestack.voice_factory({})()
        self.assertIs(tts, self.tts)
        self.assertIsInstance(speaker, SoundOutput)
        self.assertEqual(self.streams[0].starts, 1)
        self.assertEqual(self.streams[0].closes, 0)
        self._assert_drains(speaker, self.streams[0])
        speaker.close()
        self.assertEqual(self.streams[0].closes, 1)

    def test_call_factory_starts_output_before_session_and_transfers_ownership(self):
        original = self._build
        def build(*args, **kwargs):
            self.assertTrue(self.streams[0].active)
            return original(*args, **kwargs)
        with patch("star.senses.instant.build_pc_session", build):
            call = voicestack.call_factory({})({"name": "Fixture"})
        self.assertEqual(self.streams[0].starts, 1)
        self.assertEqual(self.streams[0].closes, 0)
        self.assertEqual(self.sources[0].closed, 0)
        self.assertEqual((self.session_stops, self.brain_closes, self.warm_stops), (0, 0, 0))
        self._assert_drains(call.session.speaker, self.streams[0])
        call.stop(); call.stop()
        self.assertEqual(self.streams[0].closes, 1)
        self.assertEqual(self.sources[0].closed, 1)
        self.assertEqual((self.session_stops, self.brain_closes, self.warm_stops), (1, 1, 1))

    def test_explicit_monitor_starts_both_outputs_and_closes_both(self):
        self.settings.monitor_device = "Owner monitor"
        _, speaker = voicestack.voice_factory({})()
        self.assertEqual([stream.starts for stream in self.streams], [1, 1])
        for pcm, rate in self.tts.synthesize("Fixture"):
            speaker.play(pcm, rate)
        self.assertTrue(all(np.max(np.abs(stream.pump())) > 0.01 for stream in self.streams))
        speaker.close()
        self.assertEqual([stream.closes for stream in self.streams], [1, 1])

    def test_start_failure_closes_stream_and_never_publishes_speaker(self):
        self.fail_devices.add(4)
        with self.assertRaises(RuntimeError): voicestack.voice_factory({})()
        self.assertEqual((self.streams[0].starts, self.streams[0].closes), (1, 1))

    def test_monitor_start_failure_closes_both_owned_streams(self):
        self.settings.monitor_device = "Owner monitor"
        self.fail_devices.add(5)
        with self.assertRaises(RuntimeError): voicestack.voice_factory({})()
        self.assertEqual([stream.closes for stream in self.streams], [1, 1])
        self.assertFalse(any(stream.active for stream in self.streams))

    def test_missing_monitor_is_refused_before_any_stream_is_created(self):
        self.settings.monitor_device = "Missing monitor"
        with self.assertRaises(routes.RouteMissing): voicestack.voice_factory({})()
        self.assertEqual(self.streams, [])

    def test_monitor_constructor_failure_closes_the_already_created_cable(self):
        self.settings.monitor_device = "Owner monitor"
        self.construct_fail_devices.add(5)
        with self.assertRaises(RuntimeError): voicestack.voice_factory({})()
        self.assertEqual(len(self.streams), 1)
        self.assertEqual((self.streams[0].starts, self.streams[0].closes), (0, 1))

    def test_standalone_wrapper_failure_closes_started_stream(self):
        with patch.object(voicestack, "_speaker", side_effect=RuntimeError("fixture wrapper")):
            with self.assertRaises(RuntimeError): voicestack.voice_factory({})()
        self.assertEqual(self.streams[0].closes, 1)

    def test_brain_factory_failure_closes_started_output(self):
        with patch("star.voice.runtime.make_brain", side_effect=RuntimeError("fixture brain")):
            with self.assertRaises(RuntimeError): voicestack.call_factory({})({})
        self.assertEqual(self.streams[0].closes, 1)

    def test_session_build_failure_closes_brain_and_started_output(self):
        with patch("star.senses.instant.build_pc_session", side_effect=RuntimeError("fixture session")):
            with self.assertRaises(RuntimeError): voicestack.call_factory({})({})
        self.assertEqual(self.streams[0].closes, 1)
        self.assertEqual(self.brain_closes, 1)

    def test_capture_constructor_failure_cleans_all_acquired_resources(self):
        with patch("star.senses.capture.LoopbackSource", side_effect=RuntimeError("fixture capture")):
            with self.assertRaises(RuntimeError): voicestack.call_factory({})({})
        self.assertEqual(self.streams[0].closes, 1)
        self.assertEqual((self.session_stops, self.brain_closes, self.warm_stops), (1, 1, 1))

    def test_frames_factory_failure_also_closes_capture(self):
        with patch.object(self.Source, "frames", side_effect=RuntimeError("fixture frames")):
            with self.assertRaises(RuntimeError): voicestack.call_factory({})({})
        self.assertEqual(self.sources[0].closed, 1)
        self.assertEqual(self.streams[0].closes, 1)

    def test_call_constructor_failure_closes_all_returned_resources(self):
        with patch.object(voicestack, "VoiceCall", side_effect=RuntimeError("fixture call")):
            with self.assertRaises(RuntimeError): voicestack.call_factory({})({})
        self.assertEqual(self.sources[0].closed, 1)
        self.assertEqual(self.streams[0].closes, 1)
        self.assertEqual((self.session_stops, self.brain_closes, self.warm_stops), (1, 1, 1))

    def test_configured_host_brain_path_also_starts_and_closes_output(self):
        call = voicestack.call_factory({"brain_url": "http://127.0.0.1:1"})({})
        self.assertEqual(self.streams[0].starts, 1)
        call.stop()
        self.assertEqual(self.streams[0].closes, 1)

    def test_output_failure_never_reports_connected_or_starts_camera(self):
        self.fail_devices.add(4)
        voice = HomeVoice(call_factory=voicestack.call_factory({}))
        cameras = []
        calls = DiscordCalls(None, None, voice, lambda *args: None,
                             reader=lambda image: {}, locator=lambda *args: None,
                             on_connected=cameras.append)
        calls._friend_info = lambda name: {"name": name}
        result = calls._connect("Fixture", {"in_voice_call": True})
        self.assertFalse(result["ok"])
        self.assertFalse(voice.in_call() or calls.situation.in_call)
        self.assertEqual(cameras, [])
        self.assertEqual(self.streams[0].closes, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
