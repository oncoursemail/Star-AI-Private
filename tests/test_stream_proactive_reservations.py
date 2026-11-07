"""Prevent simultaneous optional narration plans from oversubscribing a speech budget."""
import unittest

from star.stream_director import StreamDirector, StreamSignal


def signal(sid, kind, t, scope=""):
    return StreamSignal(sid, kind, t, "Moment " + sid,
                        game_scope=scope, evidence="observed")


class ProactiveReservationTests(unittest.TestCase):
    def make_director(self, limit=1):
        director = StreamDirector(gap_seconds=0,
                                  proactive_limit_per_minute=limit)
        director.enable(owner_approved=True)
        return director

    def test_unconfirmed_proposal_reserves_capacity_for_other_candidates(self):
        d = self.make_director()
        a = signal("a", "game_observation", 10)
        b = signal("b", "game_success", 10.1)
        self.assertTrue(d.offer(a, now=10))
        first = d.propose(now=10)
        self.assertEqual(first.signal_id, "a")
        self.assertTrue(d.offer(b, now=10.1))
        # b has HIGHER priority; it may not overbook an already planned
        # optional audio turn, even though no speech has been confirmed.
        second = d.propose(now=10.1)
        self.assertEqual(second.signal_id, "a")
        self.assertEqual(d.metrics()["proactive_recent_60s"], 0)
        self.assertEqual(d.metrics()["proactive_pending"], 1)
        self.assertFalse(d.complete(first, now=10.1, spoken=True))
        self.assertTrue(d.complete(second, now=10.1, spoken=False))
        self.assertEqual(d.metrics()["proactive_pending"], 0)
        self.assertEqual(d.propose(now=10.1).signal_id, "b")

    def test_two_pending_plans_cannot_reserve_a_third_slot(self):
        d = self.make_director(limit=2)
        a = signal("a", "game_observation", 10)
        b = signal("b", "game_success", 10.1)
        c = signal("c", "game_success", 10.2)
        for event in (a, b, c):
            self.assertTrue(d.offer(event, now=event.timestamp))
        first = d.propose(now=10)
        self.assertEqual(first.signal_id, "a")
        second = d.propose(now=10.1)
        self.assertEqual(second.signal_id, "b")
        self.assertEqual(d.metrics()["proactive_pending"], 2)
        self.assertNotEqual(d.propose(now=10.2).signal_id, "c")
        # Earlier distinct reservation remains valid even when a different
        # pending plan has been re-proposed.
        self.assertTrue(d.complete(first, now=10.2, spoken=True))
        self.assertEqual(d.metrics()["proactive_recent_60s"], 1)
        self.assertEqual(d.metrics()["proactive_pending"], 1)
        self.assertTrue(d.complete(d.propose(now=10.2), now=10.2, spoken=True))
        self.assertEqual(d.metrics()["proactive_recent_60s"], 2)
        self.assertIsNone(d.propose(now=10.2))

    def test_urgent_viewer_question_bypasses_pending_optional_reservation(self):
        d = self.make_director()
        a = signal("optional", "ambient", 10)
        self.assertTrue(d.offer(a, now=10))
        self.assertEqual(d.propose(now=10).signal_id, "optional")
        question = StreamSignal("q", "viewer_question", 10.1, "Question",
                                speaker_id="authenticated_viewer")
        self.assertTrue(d.offer(question, now=10.1))
        self.assertEqual(d.propose(now=10.1).signal_id, "q")
        self.assertEqual(d.metrics()["proactive_pending"], 1)

    def test_expiry_drops_pending_reservation(self):
        d = self.make_director()
        a = signal("a", "game_success", 10)
        b = signal("b", "game_observation", 11)
        self.assertTrue(d.offer(a, now=10))
        first = d.propose(now=10)
        self.assertTrue(d.offer(b, now=11))
        self.assertNotEqual(d.propose(now=11).signal_id, "b")
        self.assertEqual(d.propose(now=17.1).signal_id, "b")
        self.assertFalse(d.complete(first, now=17.1, spoken=True))
        self.assertEqual(d.metrics()["proactive_pending"], 1)

    def test_game_handoff_releases_only_old_game_reservation(self):
        d = self.make_director()
        d.bind_game_scope("room.one", owner_approved=True)
        old = signal("old", "game_success", 10, "room.one")
        self.assertTrue(d.offer(old, now=10))
        planned = d.propose(now=10)
        d.bind_game_scope("room.two", owner_approved=True)
        self.assertEqual(d.metrics()["proactive_pending"], 0)
        self.assertFalse(d.complete(planned, now=11, spoken=True))
        new = signal("new", "game_success", 11, "room.two")
        self.assertTrue(d.offer(new, now=11))
        self.assertEqual(d.propose(now=11).signal_id, "new")

    def test_giant_clock_is_rejected_as_value_error(self):
        d = self.make_director()
        with self.assertRaises(ValueError):
            d.propose(now=10 ** 1000)


if __name__ == "__main__":
    unittest.main()
