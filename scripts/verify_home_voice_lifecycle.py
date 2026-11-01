"""Verify local voice lifecycle with fake audio, capture and apps; no devices or calls."""
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star.home.voicelink import HomeVoice, VoiceCall
from star.home.calls import DiscordCalls


class Speaker:
    def __init__(self):
        self.played, self.stops, self.closed = [], 0, 0
    def pending_seconds(self): return 0
    def play(self, pcm, rate): self.played.append(pcm)
    def stop(self): self.stops += 1; self.played.clear()
    def close(self): self.closed += 1


class TTS:
    def __init__(self, delayed=False):
        self.entered, self.release = threading.Event(), threading.Event()
        if not delayed: self.release.set()
    def synthesize(self, text):
        self.entered.set()
        if self.release.wait(2): yield b"fake", 24000


class Candidate:
    def __init__(self):
        self.started, self.stops, self.window = 0, 0, None
        self.session = SimpleNamespace(tts=TTS(), speaker=Speaker(), busy=lambda: False, state="listening")
    def start(self): self.started += 1; return self
    def stop(self): self.stops += 1
    def alive(self): return self.started > 0 and not self.stops
    def attach_window(self, window): self.window = window
    def idle_s(self): return 0


class Checks(unittest.TestCase):
    def setUp(self):
        self.tts, self.speaker = TTS(delayed=True), Speaker()
        self.stopped = False
        self.voice = HomeVoice(voice_factory=lambda: (self.tts, self.speaker))
        self.voice.set_stop_check(lambda: self.stopped)
        self.addCleanup(self._clean)

    def _clean(self):
        self.tts.release.set()
        self.voice.stop()
        if self.voice._line._thread is not None:
            self.voice._line._thread.join(2)

    def _finish_line(self):
        self.tts.release.set()
        self.voice._line._thread.join(2)
        self.assertFalse(self.voice._line.busy())

    def _thread(self, fn):
        errors = []
        def run():
            try: fn()
            except Exception as why: errors.append(why)
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.addCleanup(lambda: thread.join(2))
        return thread, errors

    def test_stop_pending_tts_drops_late_pcm_and_completion(self):
        self.assertTrue(self.voice.speak("A game remark"))
        self.assertTrue(self.tts.entered.wait(1))
        self.stopped = True
        self.voice.stop()
        self._finish_line()
        self.assertEqual(self.speaker.played, [])
        self.assertEqual(self.voice._line.spoken, [])
        self.assertEqual(self.speaker.stops, 1)

    def test_live_stop_predicate_blocks_late_pcm_even_before_watcher_tick(self):
        self.voice.speak("A game remark")
        self.assertTrue(self.tts.entered.wait(1))
        self.stopped = True
        self._finish_line()
        self.assertEqual(self.speaker.played, [])

    def test_stop_flushes_already_queued_pcm_and_closes_generator(self):
        queued, release, closed = threading.Event(), threading.Event(), []
        self.addCleanup(release.set)
        def synthesize(text):
            try:
                yield b"first", 24000
                queued.set(); release.wait(2)
                yield b"late", 24000
            finally:
                closed.append(True)
        self.voice._voice_factory = lambda: (SimpleNamespace(synthesize=synthesize), self.speaker)
        self.voice.speak("Two chunks")
        self.assertTrue(queued.wait(1))
        self.assertEqual(self.speaker.played, [b"first"])
        self.voice.stop(); release.set()
        self.voice._line._thread.join(2)
        self.assertEqual(self.speaker.played, [])
        self.assertEqual(closed, [True])

    def test_call_handoff_flushes_old_line_before_start_and_never_stops_new_speaker(self):
        self.voice.speak("Old game remark")
        self.assertTrue(self.tts.entered.wait(1))
        candidate = Candidate()
        def factory(friend):
            self.assertEqual(self.speaker.stops, 1)
            return candidate
        self.voice._call_factory = factory
        self.voice.start_call({})
        self._finish_line()
        self.assertEqual(self.speaker.played, [])
        self.assertEqual(candidate.session.speaker.stops, 0)
        self.assertTrue(self.voice.in_call())

    def test_stop_during_standalone_factory_closes_unpublished_output(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def factory():
            entered.set(); release.wait(2)
            return self.tts, self.speaker
        self.voice._voice_factory = factory
        thread, errors = self._thread(lambda: self.voice.speak("Late factory"))
        self.assertTrue(entered.wait(1))
        self.voice.stop(); release.set(); thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self.speaker.closed, 1)
        self.assertFalse(self.tts.entered.is_set())

    def test_stop_during_call_factory_never_starts_or_publishes_candidate(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        candidate = Candidate()
        def factory(friend):
            entered.set(); release.wait(2)
            return candidate
        self.voice._call_factory = factory
        thread, errors = self._thread(lambda: self.voice.start_call({}))
        self.assertTrue(entered.wait(1))
        self.assertTrue(self.voice.in_call())
        self.voice.stop(); release.set(); thread.join(2)
        self.assertEqual(len(errors), 1)
        self.assertEqual(candidate.started, 0)
        self.assertEqual(candidate.stops, 1)
        self.assertFalse(self.voice.in_call())

    def test_concurrent_start_is_rejected_without_second_factory(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        calls = []
        def factory(friend):
            calls.append(friend); entered.set(); release.wait(2)
            return Candidate()
        self.voice._call_factory = factory
        thread, errors = self._thread(lambda: self.voice.start_call({"one": True}))
        self.assertTrue(entered.wait(1))
        with self.assertRaises(RuntimeError): self.voice.start_call({"two": True})
        release.set(); thread.join(2)
        self.assertEqual(len(calls), 1)
        self.assertEqual(errors, [])

    def test_failed_call_factory_does_not_leave_startup_busy(self):
        def fail(friend): raise OSError("fixture")
        self.voice._call_factory = fail
        with self.assertRaises(OSError): self.voice.start_call({})
        self.assertFalse(self.voice.in_call())
        candidate = Candidate()
        self.voice._call_factory = lambda friend: candidate
        self.assertIs(self.voice.start_call({}), candidate)

    def test_failed_candidate_cleanup_does_not_leave_startup_busy(self):
        candidate = Candidate()
        def fail(): raise OSError("fixture")
        candidate.start = candidate.stop = fail
        self.voice._call_factory = lambda friend: candidate
        with self.assertRaises(OSError): self.voice.start_call({})
        self.assertFalse(self.voice.in_call())

    def test_stop_before_factory_never_opens_audio(self):
        self.stopped = True
        self.voice._voice_factory = lambda: self.fail("opened audio after STOP")
        self.voice._call_factory = lambda friend: self.fail("opened call after STOP")
        self.assertFalse(self.voice.speak("No"))
        with self.assertRaises(RuntimeError): self.voice.start_call({})

    def test_stop_predicate_failure_stays_silent(self):
        def fail(): raise OSError("fixture")
        self.voice.set_stop_check(fail)
        self.assertFalse(self.voice.speak("No"))
        with self.assertRaises(RuntimeError): self.voice.start_call({})

    def test_stale_call_cleanup_never_detaches_replacement(self):
        old, new = Candidate(), Candidate()
        self.voice._call_factory = lambda friend: old
        self.voice.start_call({})
        self.voice._call_factory = lambda friend: new
        self.voice.start_call({})
        self.voice.end_call(expected=old)
        self.assertIs(self.voice.call, new)
        self.assertEqual(new.stops, 0)

    def test_game_window_survives_call_start(self):
        window = self.voice.window_for("minecraft")
        candidate = Candidate()
        self.voice._call_factory = lambda friend: candidate
        self.voice.start_call({})
        self.assertIs(candidate.window, window)

    def test_blocked_capture_is_closed_without_waiting_for_next_frame(self):
        entered, release = threading.Event(), threading.Event()
        closed, stopped = [], []
        def frames():
            entered.set(); release.wait(2)
            yield b"frame"
        session = SimpleNamespace(start=lambda: None, feed=lambda frame: self.fail("fed after STOP"),
                                  stop=lambda: stopped.append(True))
        call = VoiceCall(session, frames(), closers=(lambda: (closed.append(True), release.set()),))
        call.start(); self.assertTrue(entered.wait(1))
        begin = time.monotonic(); call.stop(); call.stop()
        self.assertLess(time.monotonic() - begin, 1)
        self.assertFalse(call._thread.is_alive())
        self.assertEqual(closed, [True])
        self.assertEqual(stopped, [True])

    def test_blocking_capture_close_cannot_delay_session_or_speaker_stop(self):
        capture_entered, close_entered, release = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)
        stopped, closed = [], []
        speaker = Speaker()
        speaker.play(b"queued", 24000)
        def frames():
            capture_entered.set(); release.wait(2)
            yield b"frame"
        def stop_session():
            self.assertEqual(speaker.stops, 1)
            self.assertEqual(speaker.played, [])
            stopped.append(True)
        def close_capture():
            close_entered.set(); release.wait(2)
            closed.append(True)
        session = SimpleNamespace(start=lambda: None, stop=stop_session, feed=lambda frame: None, speaker=speaker)
        call = VoiceCall(session, frames(), closers=(close_capture,)).start()
        self.assertTrue(capture_entered.wait(1))
        thread, errors = self._thread(call.stop)
        self.assertTrue(close_entered.wait(1))
        self.assertTrue(thread.is_alive())
        self.assertEqual(stopped, [True])
        self.assertEqual(speaker.stops, 1)
        self.assertEqual(speaker.played, [])
        release.set(); thread.join(2); call._thread.join(2)
        self.assertFalse(thread.is_alive() or call._thread.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(closed, [True])

    def test_unstarted_call_cleanup_is_idempotent(self):
        closed = []
        session = SimpleNamespace(stop=lambda: closed.append("session"))
        call = VoiceCall(session, (), closers=(lambda: closed.append("capture"),))
        call.stop(); call.stop()
        self.assertEqual(sorted(closed), ["capture", "session"])
        with self.assertRaises(RuntimeError): call.start()

    def test_one_resource_close_failure_does_not_skip_other_cleanup(self):
        closed = []
        def fail(): raise RuntimeError("fixture")
        session = SimpleNamespace(stop=lambda: closed.append("session"))
        call = VoiceCall(session, (), closers=(fail, lambda: closed.append("speaker")))
        call.stop()
        self.assertEqual(sorted(closed), ["session", "speaker"])

    def test_failed_session_start_still_releases_resources_once(self):
        closed = []
        def fail(): raise RuntimeError("fixture")
        session = SimpleNamespace(start=fail, stop=lambda: closed.append("session"))
        call = VoiceCall(session, (), closers=(lambda: closed.append("capture"),)).start()
        call._thread.join(1); call.stop()
        self.assertEqual(sorted(closed), ["capture", "session"])

    def _coordinator(self, sleep=lambda seconds: None):
        actions, emotions = [], []
        host = SimpleNamespace(focus_window=lambda title: actions.append("focus") or True,
                               key=lambda key: actions.append(key), type_text=lambda text: actions.append("type"),
                               screenshot=lambda: None, click=lambda *args: actions.append("click"))
        calls = DiscordCalls(host, None, self.voice,
                             lambda *args: SimpleNamespace(relationship="friend", blocked=False, muted=False),
                             reader=lambda image: {"incoming_call": True, "caller": "friend", "in_voice_call": True},
                             locator=lambda *args: (1, 1), sleep=sleep,
                             feel=lambda *args, **kwargs: emotions.append(args))
        return calls, actions, emotions

    def test_coordinator_stop_clears_state_without_app_or_emotion_actions(self):
        calls, actions, emotions = self._coordinator()
        calls.friend = "friend"; calls._departed.add("friend")
        calls.situation.in_call = True
        calls.stop(); calls.stop()
        self.assertEqual(calls.friend, "")
        self.assertFalse(calls.situation.in_call or calls._departed)
        self.assertEqual(actions, [])
        self.assertEqual(emotions, [])

    def test_callout_stop_during_navigation_never_clicks_call(self):
        calls, actions, _ = self._coordinator(sleep=lambda seconds: setattr(self, "stopped", True))
        result = calls.callout(SimpleNamespace(sender="friend"))
        self.assertFalse(result["ok"])
        self.assertNotIn("click", actions)
        self.assertNotIn("enter", actions)

    def test_answer_stop_during_wait_never_starts_voice_or_fallback_click(self):
        calls, actions, _ = self._coordinator(sleep=lambda seconds: setattr(self, "stopped", True))
        self.voice._call_factory = lambda friend: self.fail("started call after STOP")
        result = calls.answer(SimpleNamespace(sender="friend"))
        self.assertFalse(result["ok"])
        self.assertNotIn("click", actions)

    def test_stop_during_button_location_prevents_late_click(self):
        calls, actions, _ = self._coordinator()
        def locate(*args):
            self.stopped = True
            return 1, 1
        calls.locator = locate
        self.assertFalse(calls._click("call button"))
        self.assertNotIn("click", actions)

    def test_runtime_dry_run_blocks_native_factories_but_preserves_planning(self):
        from star.home.runtime import Runtime
        opened, planned = [], []
        self.voice._voice_factory = lambda: opened.append("audio") or (self.tts, self.speaker)
        self.voice._call_factory = lambda friend: opened.append("call") or Candidate()
        executor = SimpleNamespace(dry_run=True)
        def chat(messages, tools):
            planned.append((messages, tools))
            return {"content": "A local plan."}
        with tempfile.TemporaryDirectory(prefix="star-dry-voice-") as folder:
            rt = Runtime(Path(folder), {}, executor, SimpleNamespace(), chat=chat,
                         voice=self.voice, emotion=None)
            self.assertFalse(rt.admission_blocked())
            self.assertFalse(self.voice.speak("Preview speech"))
            with self.assertRaises(RuntimeError): self.voice.start_call({})
            self.assertEqual(opened, [])
            self.assertEqual(rt.chat_model()([{"role": "user", "content": "Plan only"}], []),
                             {"content": "A local plan."})
            self.assertEqual(len(planned), 1)
            executor.dry_run = False
            candidate = self.voice.start_call({})
            self.assertIs(self.voice.call, candidate)
            self.assertEqual(opened, ["call"])
            self.voice.stop()

    def test_runtime_dry_run_enabled_during_tts_blocks_late_pcm(self):
        from star.home.runtime import Runtime
        executor = SimpleNamespace(dry_run=False)
        with tempfile.TemporaryDirectory(prefix="star-dry-voice-") as folder:
            Runtime(Path(folder), {}, executor, SimpleNamespace(), voice=self.voice, emotion=None)
            self.assertTrue(self.voice.speak("Before preview"))
            self.assertTrue(self.tts.entered.wait(1))
            executor.dry_run = True
            self._finish_line()
            self.assertEqual(self.speaker.played, [])
            self.assertEqual(self.voice._line.spoken, [])

    def test_camera_dry_run_returns_before_control_or_ui_access(self):
        from star.vtuber.activities import camera_on
        def forbidden(*args): self.fail("Camera or UI accessed in dry run")
        ctx = SimpleNamespace(executor=SimpleNamespace(dry_run=True))
        ctl = SimpleNamespace(data_dir=forbidden, start=forbidden, frames_flowing=forbidden)
        video = SimpleNamespace(ensure=forbidden)
        result = camera_on(ctx, ctl=ctl, video=video)
        self.assertTrue(result["ok"])
        self.assertFalse(result["verified"])
        self.assertEqual(result["evidence"], [])

    def test_camera_dry_run_flip_during_start_stops_before_ui_access(self):
        from star.vtuber.activities import camera_on
        stopped = []
        ctx = SimpleNamespace(executor=SimpleNamespace(dry_run=False), home=Path("unused-fake-home"),
                              interrupt=threading.Event())
        def start(folder):
            ctx.executor.dry_run = True
            return {"alive": True}
        def forbidden(*args): self.fail("Camera verification or UI accessed after dry-run flip")
        ctl = SimpleNamespace(data_dir=lambda: Path("unused-fake-camera"), start=start,
                              stop=stopped.append, frames_flowing=forbidden)
        result = camera_on(ctx, ctl=ctl, video=SimpleNamespace(ensure=forbidden))
        self.assertFalse(result["ok"] or result["verified"])
        self.assertEqual(stopped, [Path("unused-fake-camera")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
