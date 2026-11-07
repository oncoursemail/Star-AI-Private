"""Offline integration tests: synthetic scores, no game or TTS was connected."""
import unittest

from star.game_skill_memory import Episode, GameSkillMemory
from star.stream_moment_memory import GameMoment, StreamMomentMemory
from star.game_stream_bridge import GameStreamBridge


SHA = "b" * 64


def make_episode(*, session="run1", seq=1, state="boss", action="jump",
                 success=True, unsafe=False, evidence_sha256=SHA):
    return Episode("obby", session, seq, state, action, success, unsafe,
                   350, evidence_sha256)


def make_moment(*, session="run1", seq=1, kind="victory", topic="boss",
                evidence_sha256=SHA, occurred_ms=1000, event_id="event1"):
    return GameMoment(session, event_id, seq, kind, topic, occurred_ms, evidence_sha256)


class BridgeTests(unittest.TestCase):
    def test_host_verification_gate(self):
        b = GameStreamBridge()
        with self.assertRaises(PermissionError):
            b.ingest(make_episode(), make_moment())
        self.assertEqual(b.summary()["scored_episodes"], 0)

    def test_declaration_does_not_grant_game_controls(self):
        b = GameStreamBridge()
        b.ingest(make_episode(), independently_verified_by_host=True)
        self.assertFalse(hasattr(b, "press_key"))
        self.assertFalse(hasattr(b, "broadcast"))
        self.assertFalse(hasattr(b, "train_model"))

    def test_episode_without_story_is_valid(self):
        b = GameStreamBridge()
        receipt = b.ingest(make_episode(), independently_verified_by_host=True)
        self.assertTrue(receipt.skill_recorded)
        self.assertFalse(receipt.moment_queued)
        self.assertEqual(receipt.moment_status, "not_requested")
        self.assertIsNone(b.offer_commentary("run1", 1100, audience_can_hear=True))

    def test_record_valid_correlated_story(self):
        b = GameStreamBridge()
        r = b.ingest(make_episode(), make_moment(),
                     independently_verified_by_host=True)
        self.assertEqual(r.moment_status, "queued")
        self.assertEqual(b.summary()["observed_moments"], 1)

    def test_story_mismatch_never_mutates_game_memory(self):
        kwargs = [
            dict(session="other"),
            dict(seq=2),
            dict(topic="menu"),
            dict(evidence_sha256="a"*64),
        ]
        for k in kwargs:
            with self.subTest(k=k):
                b = GameStreamBridge()
                with self.assertRaises(ValueError):
                    b.ingest(make_episode(), make_moment(**k),
                             independently_verified_by_host=True)
                self.assertEqual(b.summary()["scored_episodes"], 0)

    def test_false_victory_or_failure_rejected(self):
        for ep, cue in [
            (make_episode(success=False), make_moment(kind="victory")),
            (make_episode(success=False), make_moment(kind="recovery")),
            (make_episode(success=True), make_moment(kind="failure")),
            (make_episode(success=False, unsafe=True), make_moment(kind="surprise")),
            (make_episode(success=False, unsafe=True), make_moment(kind="recovery")),
        ]:
            b = GameStreamBridge()
            with self.subTest(ep=ep, cue=cue), self.assertRaises(ValueError):
                b.ingest(ep, cue, independently_verified_by_host=True)
            self.assertEqual(b.summary()["scored_episodes"], 0)

    def test_non_episode_or_non_moment(self):
        b = GameStreamBridge()
        with self.assertRaises(TypeError):
            b.ingest({"fake": True}, independently_verified_by_host=True)
        with self.assertRaises(TypeError):
            b.ingest(make_episode(), {"fake": True}, independently_verified_by_host=True)
        self.assertEqual(b.summary()["scored_episodes"], 0)

    def test_optional_narrative_overflow_keeps_real_score(self):
        b = GameStreamBridge(moments=StreamMomentMemory(max_moments=1))
        b.ingest(make_episode(), make_moment(), independently_verified_by_host=True)
        r = b.ingest(make_episode(seq=2), make_moment(seq=2, kind="discovery",
               event_id="event2", occurred_ms=1200),
               independently_verified_by_host=True)
        self.assertEqual(r.moment_status, "moment_rejected")
        self.assertEqual(b.summary()["scored_episodes"], 2)
        self.assertEqual(b.summary()["observed_moments"], 1)
        self.assertEqual(b.summary()["dropped_optional_moments"], 1)
        with self.assertRaises(ValueError):
            b.ingest(make_episode(seq=2), independently_verified_by_host=True)
        self.assertEqual(b.summary()["scored_episodes"], 2)

    def test_story_replay_dropped_not_scored_as_bad_action(self):
        b = GameStreamBridge()
        b.ingest(make_episode(), make_moment(), independently_verified_by_host=True)
        r = b.ingest(make_episode(seq=2), make_moment(seq=2, event_id="event1",
               occurred_ms=1100), independently_verified_by_host=True)
        self.assertEqual(r.moment_status, "moment_rejected")
        self.assertEqual(b.summary()["scored_episodes"], 2)

    def test_cold_advice_abstains_and_practice_isolated(self):
        b = GameStreamBridge()
        self.assertIsNone(b.recommend("obby", "boss", ("jump",)).action)
        self.assertIsNone(b.recommend("obby", "boss", ("jump",),
                                       mode="practice").action)
        choice = b.recommend("obby", "boss", ("jump",),
                             mode="practice", sandbox_approved=True)
        self.assertEqual(choice.action, "jump")
        self.assertEqual(choice.mode, "practice")

    def test_independent_evidence_enables_action_advice(self):
        b = GameStreamBridge()
        for n in range(1, 41):
            b.ingest(make_episode(session=f"run{n}"),
                     independently_verified_by_host=True)
        self.assertEqual(b.recommend("obby", "boss", ("jump",)).action, "jump")
        self.assertIsNone(b.recommend("other", "boss", ("jump",)).action)

    def test_known_unsafe_action_never_recommended(self):
        b = GameStreamBridge()
        for n in range(1, 40):
            b.ingest(make_episode(session=f"run{n}"),
                     independently_verified_by_host=True)
        b.ingest(make_episode(session="run40", success=False, unsafe=True),
                 independently_verified_by_host=True)
        self.assertIsNone(b.recommend("obby", "boss", ("jump",)).action)

    def test_unheard_audio_is_not_counted_spoken(self):
        b = GameStreamBridge()
        b.ingest(make_episode(), make_moment(), independently_verified_by_host=True)
        offer = b.offer_commentary("run1", 1100, audience_can_hear=True)
        self.assertIsNotNone(offer)
        self.assertEqual(b.summary()["completed_event_references"], 0)
        self.assertTrue(b.finish_commentary("run1", offer.ticket, audible=False,
                                            now_ms=1200))
        self.assertEqual(b.summary()["completed_event_references"], 0)
        new = b.offer_commentary("run1", 1300, audience_can_hear=True)
        self.assertIsNotNone(new)
        self.assertNotEqual(offer.ticket, new.ticket)

    def test_audible_audio_commits_and_cooldown_applies(self):
        b = GameStreamBridge()
        b.ingest(make_episode(), make_moment(), independently_verified_by_host=True)
        offer = b.offer_commentary("run1", 1100, audience_can_hear=True)
        self.assertTrue(b.finish_commentary("run1", offer.ticket, audible=True,
                                            now_ms=1150))
        self.assertEqual(b.summary()["completed_event_references"], 1)
        self.assertFalse(b.finish_commentary("run1", offer.ticket, audible=True,
                                             now_ms=1200))
        self.assertIsNone(b.offer_commentary("run1", 1200, audience_can_hear=True))

    def test_pending_offer_is_stable_until_stop(self):
        b = GameStreamBridge()
        b.ingest(make_episode(), make_moment(), independently_verified_by_host=True)
        one = b.offer_commentary("run1", 1100, audience_can_hear=True)
        self.assertEqual(one, b.offer_commentary("run1", 1200,
                         audience_can_hear=True))
        self.assertTrue(b.interrupt("run1"))
        self.assertFalse(b.finish_commentary("run1", one.ticket, audible=True,
                                             now_ms=1250))
        again = b.offer_commentary("run1", 1300, audience_can_hear=True)
        self.assertNotEqual(one.ticket, again.ticket)
        self.assertEqual(b.summary()["completed_event_references"], 0)

    def test_no_permission_produces_no_story(self):
        b = GameStreamBridge()
        b.ingest(make_episode(), make_moment(), independently_verified_by_host=True)
        self.assertIsNone(b.offer_commentary("run1", 1100))
        self.assertEqual(b.summary()["completed_event_references"], 0)

    def test_canceled_failure_then_actual_comeback(self):
        b = GameStreamBridge()
        b.ingest(make_episode(success=False),
                 make_moment(kind="failure"), independently_verified_by_host=True)
        first = b.offer_commentary("run1", 1100, audience_can_hear=True)
        b.finish_commentary("run1", first.ticket, audible=False, now_ms=1200)
        b.ingest(make_episode(seq=2, success=True),
                 make_moment(seq=2, kind="recovery", event_id="event2",
                             occurred_ms=4000), independently_verified_by_host=True)
        second = b.offer_commentary("run1", 4200, audience_can_hear=True)
        self.assertEqual(second.cue.kind, "callback")
        self.assertEqual(second.cue.event_ids, ("event1", "event2"))
        b.finish_commentary("run1", second.ticket, audible=True, now_ms=4250)
        self.assertEqual(b.summary()["completed_event_references"], 2)
        self.assertIsNone(b.offer_commentary("run1", 15000, audience_can_hear=True))

    def test_failure_from_other_state_cannot_be_comeback(self):
        b = GameStreamBridge()
        b.ingest(make_episode(success=False, state="start"),
                 make_moment(topic="start", kind="failure"),
                 independently_verified_by_host=True)
        b.ingest(make_episode(seq=2),
                 make_moment(seq=2, kind="recovery", event_id="event2",
                             occurred_ms=4000), independently_verified_by_host=True)
        offer = b.offer_commentary("run1", 4200, audience_can_hear=True)
        self.assertEqual(offer.cue.kind, "recovery")

    def test_cue_expiration_invalidates_late_speech(self):
        b = GameStreamBridge()
        b.ingest(make_episode(), make_moment(), independently_verified_by_host=True)
        offer = b.offer_commentary("run1", 1100, audience_can_hear=True)
        self.assertFalse(b.finish_commentary("run1", offer.ticket,
                         audible=True, now_ms=20000))
        self.assertEqual(b.summary()["completed_event_references"], 0)

    def test_pending_not_eligible_when_audience_is_off(self):
        b = GameStreamBridge()
        b.ingest(make_episode(), make_moment(), independently_verified_by_host=True)
        offer = b.offer_commentary("run1", 1100, audience_can_hear=True)
        self.assertIsNone(b.offer_commentary("run1", 1150))
        self.assertTrue(b.interrupt("run1"))
        self.assertFalse(b.finish_commentary("run1", offer.ticket,
                                             audible=True, now_ms=1160))

    def test_invalid_ack_does_not_commit(self):
        b = GameStreamBridge()
        b.ingest(make_episode(), make_moment(), independently_verified_by_host=True)
        offer = b.offer_commentary("run1", 1100, audience_can_hear=True)
        for bad in ("1", True, -1):
            with self.assertRaises(ValueError):
                b.finish_commentary("run1", bad, audible=True, now_ms=1110)
        with self.assertRaises(ValueError):
            b.finish_commentary("run1", offer.ticket, audible="yes", now_ms=1110)
        self.assertEqual(b.summary()["completed_event_references"], 0)


if __name__ == "__main__":
    unittest.main()
