"""Public-chat cancellation checks using only fake models, readers and speakers.

Run with the repository's Python. No accounts, network, devices or model loads.
The ordinary VoiceLine demonstration records why that route is unsuitable for
public chat; the bridge checks enforce that it never uses that route.
"""
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star.home import control
from star.home.streamchat import StreamChat
from star.home.voicelink import VoiceLine


class Checks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="star-public-audio-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.entered, self.release = threading.Event(), threading.Event()
        self.pcm, self.requests, self.pending = [], [], []
        self.current = True
        self.during = lambda: None
        owner = self

        class DelayedTTS:
            def synthesize(self, text):
                owner.entered.set()
                if owner.release.wait(2):
                    yield b"fake-pcm", 24000

        speaker = SimpleNamespace(pending_seconds=lambda: 0,
                                  play=lambda pcm, rate: self.pcm.append((pcm, rate)))
        self.line = VoiceLine(lambda: (DelayedTTS(), speaker, None))
        self.addCleanup(self._finish_line)
        voice = SimpleNamespace(in_call=lambda: False, _line=self.line, speak=self.line.say)
        self.queue = SimpleNamespace(pop=lambda: SimpleNamespace(message_id="one", text="What is that?"),
                                     current=lambda identifier: self.current, clear=self._clear)
        self.reader = SimpleNamespace(queue=self.queue, status=lambda: {})

        def chat(messages, tools):
            self.requests.append((messages, tools))
            self.during()
            return {"content": "A constellation cat."}

        self.rt = SimpleNamespace(home=self.home,
                                  config={"stream_chat": {"enabled": True, "respond": True}},
                                  executor=SimpleNamespace(dry_run=False),
                                  situation=SimpleNamespace(in_moment=False), voice=voice,
                                  chat_model=lambda: chat,
                                  hooks={"stream_chat_moderate": lambda message: True,
                                         "stream_reply_moderate": lambda text: True})
        self.ctx = SimpleNamespace(interrupt=threading.Event())
        self.bridge = StreamChat(self.rt, reader=self.reader, emit=lambda event: None)

    def _clear(self):
        self.current = False

    def _finish_line(self):
        self.release.set()
        if self.line._thread is not None:
            self.line._thread.join(3)

    def _connect(self, result=True):
        def speak(text, valid):
            self.pending.append((text, valid))
            return result
        self.rt.hooks["stream_chat_speak"] = speak

    def test_direct_ordinary_line_has_no_public_validity_contract(self):
        # Historical failure reproduced entirely with fakes: a late TTS chunk
        # survives STOP. This intentionally demonstrates the unsupported route.
        self.assertTrue(self.line.say("Fixture only"))
        self.assertTrue(self.entered.wait(1))
        control.stop(self.home)
        self._clear()
        self.release.set()
        self._finish_line()
        self.assertEqual(self.pcm, [(b"fake-pcm", 24000)])

    def test_bridge_never_falls_back_to_ordinary_voice_line(self):
        result = self.bridge.read(self.ctx)
        self.assertEqual(self.requests, [])
        self.assertFalse(self.entered.is_set())
        self.assertFalse(self.line.busy())
        self.assertEqual(self.pcm, [])
        self.assertFalse(result["verified"])

    def test_guarded_hook_receives_live_validity_and_never_uses_ordinary_line(self):
        self._connect()
        result = self.bridge.read(self.ctx)
        self.assertEqual(len(self.pending), 1)
        self.assertTrue(self.pending[0][1]())
        self.assertFalse(self.entered.is_set())
        self.assertFalse(result["verified"])

    def test_late_invalidation_prevents_fake_playback(self):
        changes = ("stop", "interrupt", "deletion", "private_call", "game", "busy",
                   "respond_off", "enabled_off", "dry_run", "hook_removed",
                   "moderator_removed", "output_moderator_removed", "config_replaced", "close")
        # Every case gets a fresh fixture because STOP and shutdown are sticky.
        for name in changes:
            with self.subTest(name=name):
                case = Checks()
                case.setUp()
                try:
                    case._connect()
                    case.bridge.read(case.ctx)
                    self.assertEqual(len(case.pending), 1)
                    text, valid = case.pending[0]
                    if name == "stop": control.stop(case.home)
                    elif name == "interrupt": case.ctx.interrupt.set()
                    elif name == "deletion": case._clear()
                    elif name == "private_call": case.rt.voice.in_call = lambda: True
                    elif name == "game": case.rt.situation.in_moment = True
                    elif name == "busy": case.rt.voice._line = SimpleNamespace(busy=lambda: True)
                    elif name in ("respond_off", "enabled_off"):
                        case.rt.config["stream_chat"][name.removesuffix("_off")] = False
                    elif name == "dry_run": case.rt.executor.dry_run = True
                    elif name == "hook_removed": case.rt.hooks.pop("stream_chat_speak")
                    elif name == "moderator_removed": case.rt.hooks.pop("stream_chat_moderate")
                    elif name == "output_moderator_removed": case.rt.hooks.pop("stream_reply_moderate")
                    elif name == "config_replaced": case.rt.config["stream_chat"] = {"enabled": False, "respond": False}
                    elif name == "close": case.bridge.close()
                    played = []
                    if valid():
                        played.append(text)
                    self.assertEqual(played, [])
                    self.assertFalse(case.entered.is_set())
                finally:
                    case.doCleanups()

    def test_hook_return_must_be_exact_true(self):
        self._connect(result=1)
        result = self.bridge.read(self.ctx)
        self.assertEqual(self.bridge.status()["reply_queued"], 0)
        self.assertNotIn("queued one", result["summary"])

    def test_disabling_during_model_does_not_schedule_public_speech(self):
        self._connect()
        self.during = lambda: self.rt.config["stream_chat"].update(respond=False)
        self.bridge.read(self.ctx)
        self.assertEqual(self.pending, [])
        self.assertFalse(self.entered.is_set())

    def test_guard_fails_closed_if_reader_validation_raises(self):
        self._connect()
        self.bridge.read(self.ctx)
        def fail(identifier):
            raise RuntimeError("fixture validation unavailable")
        self.queue.current = fail
        self.assertFalse(self.pending[0][1]())

    def test_reader_stop_supports_wait_for_real_client_backoff(self):
        calls = []
        def run(stop):
            calls.append(stop.is_set())
            self.bridge.close()
            calls.append(stop.wait(0.01))
        self.reader.run = run
        thread = threading.Thread(target=self.bridge.background, daemon=True)
        thread.start()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(calls, [False, True])
        self.assertEqual(self.bridge.status()["errors"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
