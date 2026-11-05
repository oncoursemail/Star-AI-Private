"""Opt-in 60-second proactive speech cadence: pure planning, no OBS/TTS/game I/O."""
import unittest

from star.stream_director import StreamDirector, StreamSignal
from star.stream_stage import StarStage


def cue(ident, kind="game_observation", at=10, *, scope="", speaker=""):
    return StreamSignal(ident, kind, at, f"Observed moment {ident}",
                        speaker_id=speaker, evidence="observed",
                        game_scope=scope)


class ProactiveCadenceTests(unittest.TestCase):
    def director(self, limit=2):
        d = StreamDirector(gap_seconds=0, viewer_cooldown=0,
                           proactive_limit_per_minute=limit)
        d.enable(owner_approved=True)
        return d

    def speak(self, d, event, *, at=None, spoken=True):
        t = event.timestamp if at is None else at
        self.assertTrue(d.offer(event, now=t))
        chosen = d.propose(now=t)
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.signal_id, event.signal_id)
        self.assertTrue(d.complete(chosen, now=t, spoken=spoken))

    def test_default_off_preserves_legacy_cadence(self):
        d = self.director(limit=0)
        for i in range(10):
            self.speak(d, cue(f"fast{i}", at=10 + i))
        self.assertEqual(d.metrics()["proactive_recent_60s"], 0)
        self.assertEqual(d.metrics()["proactive_budget_suppressed"], 0)

    def test_spoken_not_proposed_or_failed_candidates_spend_the_budget(self):
        d = self.director(limit=1)
        event = cue("a")
        self.assertTrue(d.offer(event, now=10))
        self.assertEqual(d.propose(now=10).signal_id, "a")
        self.assertEqual(d.propose(now=10).signal_id, "a")
        self.assertEqual(d.metrics()["proactive_recent_60s"], 0)
        self.assertTrue(d.complete(d.propose(now=10), now=10, spoken=False))
        self.assertEqual(d.metrics()["proactive_recent_60s"], 0)
        self.speak(d, cue("b", at=11))
        self.assertEqual(d.metrics()["proactive_recent_60s"], 1)

    def test_timed_silence_with_real_rolling_window(self):
        d = self.director()
        self.speak(d, cue("first", at=10))
        self.speak(d, cue("second", kind="game_success", at=11))
        self.assertTrue(d.offer(cue("third", at=12), now=12))
        self.assertIsNone(d.propose(now=12))
        self.assertEqual(d.metrics()["proactive_budget_suppressed"], 1)
        self.assertEqual(d.metrics()["proactive_recent_60s"], 2)
        # A blocked cue must never be narrated after it has expired.
        self.assertIsNone(d.propose(now=71))
        self.assertEqual(d.metrics()["proactive_recent_60s"], 0)
        self.speak(d, cue("new", at=71))

    def test_urgent_and_viewer_questions_remain_available(self):
        d = self.director(limit=1)
        self.speak(d, cue("narration", at=10))
        self.speak(d, cue("question", kind="viewer_question",
                          at=11, speaker="viewer-1"))
        self.speak(d, cue("danger", kind="game_danger", at=12))
        self.speak(d, cue("owner", kind="owner_interrupt", at=13))
        self.assertEqual(d.metrics()["proactive_recent_60s"], 1)
        self.assertTrue(d.offer(cue("chatter", kind="viewer_comment",
                                     speaker="viewer-2", at=14), now=14))
        self.assertIsNone(d.propose(now=14))

    def test_speaker_chat_comments_share_budget_with_game_reactions(self):
        d = self.director(limit=1)
        self.speak(d, cue("chatter", kind="viewer_comment",
                          at=10, speaker="viewer-1"))
        self.assertTrue(d.offer(cue("game", at=11), now=11))
        self.assertIsNone(d.propose(now=11))
        # New authenticated viewer question is still allowed.
        self.speak(d, cue("question", kind="viewer_question", at=12,
                          speaker="viewer-2"))

    def test_scene_switch_cannot_reset_audible_cadence(self):
        d = self.director(limit=1)
        d.bind_game_scope("obby.one", owner_approved=True)
        self.speak(d, cue("old_game", scope="obby.one", at=10))
        d.bind_game_scope("obby.two", owner_approved=True)
        self.assertTrue(d.offer(cue("new_game", scope="obby.two", at=11),
                                now=11))
        self.assertIsNone(d.propose(now=11))

    def test_disable_reenable_flushes_only_new_session(self):
        d = self.director(limit=1)
        self.speak(d, cue("old", at=10))
        d.disable()
        self.assertEqual(d.metrics()["proactive_recent_60s"], 0)
        d.enable(owner_approved=True)
        self.speak(d, cue("new", at=11))
        self.assertEqual(d.metrics()["proactive_recent_60s"], 1)

    def test_backward_host_ack_cannot_reopen_the_quota(self):
        d = self.director(limit=2)
        self.speak(d, cue("first", at=10))
        event = cue("second", at=11)
        self.assertTrue(d.offer(event, now=11))
        intent = d.propose(now=11)
        self.assertIsNotNone(intent)
        self.assertFalse(d.complete(intent, now=9, spoken=True))
        self.assertEqual(d.metrics()["proactive_recent_60s"], 1)
        self.assertTrue(d.complete(intent, now=11, spoken=True))
        self.assertEqual(d.metrics()["proactive_recent_60s"], 2)

    def test_invalid_limits_and_legacy_opt_out(self):
        for invalid in (True, 1.5, "2", -1, 13, None):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                StreamDirector(proactive_limit_per_minute=invalid)
        for valid in (0, 1, 12):
            StreamDirector(proactive_limit_per_minute=valid)

    def test_stage_wiring_honors_optional_silence_without_audio(self):
        current = [10.0]
        d = self.director(limit=1)
        stage = StarStage(director=d, clock=lambda: current[0])
        stage.enable(owner_approved=True)
        self.assertTrue(stage.offer(cue("one", at=10)))
        first = stage.prepare(now=10)
        self.assertIsNotNone(first)
        self.assertTrue(stage.queue_audio(first, now=10))
        self.assertTrue(stage.acknowledge_audible(first, now=10))
        self.assertTrue(stage.finish(first, now=10, played_to_end=True))
        current[0] = 11
        self.assertTrue(stage.offer(cue("two", at=11)))
        self.assertIsNone(stage.prepare(now=11))
        self.assertEqual(d.metrics()["proactive_recent_60s"], 1)


if __name__ == "__main__":
    unittest.main()
