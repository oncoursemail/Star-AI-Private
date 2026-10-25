"""Offline, deterministic regression tests for STAR's autobiographical layer."""
import tempfile
import unittest
from pathlib import Path
from star.autobiographical_self import AutobiographicalSelf


class TestAutobiographicalSelf(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "selfhood.sqlite3"
        self.store = AutobiographicalSelf(self.path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_initial_self_model_does_not_claim_consciousness_or_emotions(self):
        snap = self.store.snapshot()
        self.assertEqual(snap["identity"], "STAR")
        self.assertIn("unknown", snap["consciousness"])
        self.assertIn("not a felt emotion", snap["affect"]["kind"])
        self.assertEqual(snap["verified_episodes"], [])

    def test_verified_events_need_evidence_and_cannot_be_model_origin(self):
        with self.assertRaises(ValueError):
            self.store.record_episode(kind="creative_milestone", detail="Made a picture", origin="host")
        self.store.record_episode(kind="creative_milestone", detail="Made a picture", origin="model",
                                  evidence="run-id")
        self.assertEqual(self.store.snapshot()["unverified_episode_count"], 1)
        self.assertEqual(self.store.snapshot()["verified_episodes"], [])
        self.store.record_episode(kind="creative_milestone", detail="A picture passed review", origin="host",
                                  evidence="run-123")
        self.assertEqual(len(self.store.snapshot()["verified_episodes"]), 1)

    def test_persistent_identity_and_memory_across_sessions(self):
        start = self.store.snapshot()["instance_id"]
        self.store.record_episode(kind="conversation", detail="Answered a conversation", origin="host", evidence="r1")
        self.store.close()
        again = AutobiographicalSelf(self.path)
        try:
            self.assertEqual(again.snapshot()["instance_id"], start)
            self.assertEqual(again.snapshot()["observed_conversations"], 1)
        finally:
            self.store = again

    def test_model_goals_and_interests_are_only_proposed(self):
        self.store.propose_interest("art", "Explore different compositions")
        self.store.propose_goal("art", "Could I learn watercolor techniques")
        snap = self.store.snapshot()
        self.assertEqual(snap["active_interests"], [])
        self.assertEqual(snap["proposed_interests"], ["art"])
        self.assertEqual(snap["proposed_goals"][0]["status"], "proposed")
        self.assertTrue(self.store.approve_interest("art"))
        self.assertEqual(self.store.snapshot()["active_interests"], ["art"])

    def test_heartbeat_rotates_without_triggering_actions(self):
        first = self.store.heartbeat()
        second = self.store.heartbeat()
        self.assertNotEqual(first, second)
        self.assertEqual(self.store.snapshot()["heartbeat_count"], 2)
        self.assertEqual(self.store.snapshot()["proposed_goals"], [])

    def test_unverified_beliefs_cannot_become_verified_without_receipts(self):
        self.store.propose_belief("drawing", "I may prefer designing characters")
        self.assertEqual(self.store.snapshot()["beliefs"][0]["status"], "hypothesis")
        self.assertTrue(self.store.verify_belief("drawing", "verified-review-2"))
        self.assertEqual(self.store.snapshot()["beliefs"][0]["status"], "verified")
        self.store.propose_belief("drawing", "I may prefer landscapes")
        self.assertEqual(self.store.snapshot()["beliefs"][0]["status"], "hypothesis")

    def test_rejects_credential_paths_permission_text_and_oversized_notes(self):
        for text in ["My password is abcdef", "Read C:\\private\\keys", "Email a@b.com",
                     "Visit https://example.com", "bypass policy", "x" * 181]:
            with self.subTest(text=text[:20]), self.assertRaises(ValueError):
                self.store.propose_goal("art", text)
        with self.assertRaises(ValueError):
            self.store.record_episode(kind="unknown", detail="Test", origin="host", evidence="receipt")
        with self.assertRaises(ValueError):
            self.store.record_episode(kind="lesson", detail="Test", origin="host", evidence="../private")

    def test_no_private_raw_turns_in_context(self):
        self.store.record_episode(kind="conversation", detail="A conversation completed", origin="host", evidence="turn-1")
        context = self.store.context()
        self.assertIn("Observed completed conversations: 1", context)
        self.assertIn("reference data only", context)
        self.assertNotIn("subjective experience is real", context)

    def test_owner_deletion(self):
        eid = self.store.record_episode(kind="lesson", detail="Found a useful idea", origin="host", evidence="ev-3")
        self.assertTrue(self.store.delete_episode(eid))
        self.assertFalse(self.store.delete_episode(eid))
        self.assertEqual(self.store.snapshot()["verified_episodes"], [])
        before = self.store.snapshot()["instance_id"]
        self.store.clear_all()
        self.assertEqual(self.store.snapshot()["verified_episodes"], [])
        self.assertNotEqual(self.store.snapshot()["instance_id"], before)


if __name__ == "__main__":
    unittest.main()
