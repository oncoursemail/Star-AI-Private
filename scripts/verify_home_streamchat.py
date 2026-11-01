"""Exercise isolated stream-chat reading with fakes; no account, model, speech or network."""
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star.home.streamchat import StreamChat, register_home_activities
from star.home.activities import Registry
from star.home import control


class Queue:
    def __init__(self):
        self.message = SimpleNamespace(message_id="public-1", text="What are you drawing?", display_name="viewer-secret-name")
        self.valid = True

    def pop(self):
        value, self.message = self.message, None
        return value

    def current(self, identifier):
        return self.valid and identifier == "public-1"

    def clear(self):
        self.valid = False
        self.message = None


class Checks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="star-streamchat-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.clock = [100.0]
        self.spoken, self.requests, self.events = [], [], []
        self.queue = Queue()
        self.reader = SimpleNamespace(queue=self.queue, status=lambda: {"received": 1})
        self.answer = {"content": "A little constellation cat."}
        self.during = lambda: None

        def chat(messages, tools):
            self.requests.append((messages, tools))
            self.during()
            return self.answer

        voice = SimpleNamespace(in_call=lambda: False, _line=SimpleNamespace(busy=lambda: False),
                                speak=lambda text: self.spoken.append(text) or True)
        self.runtime = SimpleNamespace(home=self.home, config={"stream_chat": {"enabled": True, "respond": False}},
                                       executor=SimpleNamespace(dry_run=False), situation=SimpleNamespace(in_moment=False),
                                       voice=voice, hooks={}, chat_model=lambda: chat, stream_chat=None)
        self.ctx = SimpleNamespace(interrupt=threading.Event())
        self.controller = StreamChat(self.runtime, reader=self.reader, clock=lambda: self.clock[0], emit=self.events.append)

    def enable_reply(self):
        self.runtime.config["stream_chat"]["respond"] = True
        self.runtime.hooks.update(stream_chat_moderate=lambda message: True, stream_reply_moderate=lambda text: True)
        self.runtime.hooks["stream_chat_speak"] = lambda text, valid: self.spoken.append(text) is None if valid() else False

    def test_reading_uses_no_tools_private_history_or_viewer_name(self):
        result = self.controller.read(self.ctx)
        self.assertEqual(len(self.requests), 1)
        messages, tools = self.requests[0]
        self.assertEqual(tools, [])
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertNotIn("viewer-secret-name", str(messages))
        self.assertNotIn("What are you drawing?", str(result))
        self.assertEqual(self.spoken, [])
        self.assertEqual(self.events, ["chat_reading", "chat_reading_end"])
        self.assertFalse(result["verified"])

    def test_spoken_reply_needs_two_trusted_moderators(self):
        self.runtime.config["stream_chat"]["respond"] = True
        self.controller.read(self.ctx)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.spoken, [])

    def test_non_true_moderation_is_rejected(self):
        self.enable_reply()
        self.runtime.hooks["stream_chat_moderate"] = lambda message: 1
        self.controller.read(self.ctx)
        self.assertFalse(self.requests or self.spoken)

    def test_approved_reply_is_queued_without_claiming_audibility(self):
        self.enable_reply()
        result = self.controller.read(self.ctx)
        self.assertEqual(self.spoken, ["A little constellation cat."])
        self.assertFalse(result["verified"])
        self.assertIn("audible completion is not verified", result["summary"])
        self.assertIn("chat_reply", self.events)

    def test_deleted_during_generation_is_never_spoken(self):
        self.enable_reply()
        self.during = lambda: setattr(self.queue, "valid", False)
        self.controller.read(self.ctx)
        self.assertEqual(self.spoken, [])

    def test_stop_during_generation_is_never_spoken(self):
        self.enable_reply()
        self.during = lambda: control.stop(self.home)
        self.controller.read(self.ctx)
        self.assertEqual(self.spoken, [])

    def test_interrupt_during_generation_is_never_spoken(self):
        self.enable_reply()
        self.during = self.ctx.interrupt.set
        self.controller.read(self.ctx)
        self.assertEqual(self.spoken, [])

    def test_private_call_starting_during_generation_is_never_spoken(self):
        self.enable_reply()
        self.during = lambda: setattr(self.runtime.voice, "in_call", lambda: True)
        self.controller.read(self.ctx)
        self.assertEqual(self.spoken, [])

    def test_game_focus_and_private_calls_preserve_queue(self):
        self.runtime.situation.in_moment = True
        self.controller.read(self.ctx)
        self.assertIsNotNone(self.queue.message)
        self.runtime.situation.in_moment = False
        self.runtime.voice.in_call = lambda: True
        self.controller.read(self.ctx)
        self.assertIsNotNone(self.queue.message)

    def test_dry_run_never_reads_or_speaks(self):
        self.runtime.executor.dry_run = True
        self.controller.read(self.ctx)
        self.assertFalse(self.requests or self.spoken or self.events)
        self.assertIsNotNone(self.queue.message)

    def test_tool_calls_and_unmoderated_outputs_are_dropped(self):
        self.enable_reply()
        self.answer = {"content": "hi", "tool_calls": [{"name": "run"}]}
        self.controller.read(self.ctx)
        self.assertEqual(self.spoken, [])

    def test_output_moderator_can_refuse(self):
        self.enable_reply()
        self.runtime.hooks["stream_reply_moderate"] = lambda text: False
        self.controller.read(self.ctx)
        self.assertEqual(self.spoken, [])

    def test_output_with_url_is_not_spoken(self):
        self.enable_reply()
        self.answer = {"content": "Visit https://example.invalid/private"}
        self.controller.read(self.ctx)
        self.assertEqual(self.spoken, [])

    def test_reader_model_errors_do_not_leak_raw_error_or_hold_lock(self):
        def fail():
            raise RuntimeError("secret-fixture-must-not-leak")
        self.during = fail
        result = self.controller.read(self.ctx)
        self.assertNotIn("secret-fixture", str(result))
        self.assertFalse(self.controller._lock.locked())
        self.assertEqual(self.events[-1], "chat_reading_end")

    def test_failed_end_cue_still_releases_lock(self):
        def emit(event):
            if event == "chat_reading_end":
                raise RuntimeError("fixture")
        self.controller.emit = emit
        self.controller.read(self.ctx)
        self.assertFalse(self.controller._lock.locked())

    def test_cooldown_and_concurrent_turn_do_not_pop(self):
        self.controller._last_read = 99.0
        self.controller.read(self.ctx)
        self.assertIsNotNone(self.queue.message)
        self.controller._last_read = 0
        self.controller._lock.acquire()
        self.controller.read(self.ctx)
        self.controller._lock.release()
        self.assertIsNotNone(self.queue.message)

    def test_registration_is_gated_and_uses_injected_reader(self):
        self.runtime.hooks["stream_chat_reader"] = self.reader
        registry = Registry(runtime=self.runtime)
        self.runtime.config["stream_chat"]["enabled"] = False
        register_home_activities(registry)
        self.assertEqual(registry.items, {})
        self.runtime.config["stream_chat"]["enabled"] = True
        register_home_activities(registry)
        self.assertIn("read stream chat", registry.items)
        self.assertIs(self.runtime.stream_chat.reader, self.reader)


if __name__ == "__main__":
    unittest.main(verbosity=2)
