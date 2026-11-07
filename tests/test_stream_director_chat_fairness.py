"""Offline bounded-chat-fairness regressions for the Star stream director.

These are deterministic, no Twitch account, model, voice device or network.
"""
import unittest

from star.stream_director import StreamDirector, StreamSignal


def event(ident: str, *, speaker: str = "viewerA", kind: str = "viewer_question",
          now: float = 10.0, text: str | None = None) -> StreamSignal:
    return StreamSignal(
        signal_id=ident, kind=kind, timestamp=now,
        detail=text or f"Can you explain {ident}?", speaker_id=speaker,
        evidence="reported",
    )


class StreamDirectorChatFairnessTests(unittest.TestCase):
    def make_director(self, **kwargs) -> StreamDirector:
        d = StreamDirector(**kwargs)
        d.enable(owner_approved=True)
        return d

    def test_single_chatter_cannot_fill_shared_queue(self):
        d = self.make_director(max_events=3, max_pending_per_viewer=2)
        accepted = [
            d.offer(event(f"a{i}", text=f"Unique question number {i}"), now=10.0)
            for i in range(25)
        ]
        self.assertEqual(sum(accepted), 2)
        self.assertEqual(d.metrics()["viewer_queue_limited"], 23)
        self.assertTrue(d.offer(event("other", speaker="viewerB", now=10.1), now=10.1))
        self.assertEqual(d.metrics()["queued"], 3)
        first = d.propose(now=10.1)
        self.assertIsNotNone(first)
        self.assertEqual(first.signal_id, "a0")
        self.assertTrue(d.complete(first, now=10.1, spoken=True))
        # Per-viewer spoken cooldown skips the remaining flood entry.
        following = d.propose(now=12.4)
        self.assertIsNotNone(following)
        self.assertEqual(following.signal_id, "other")

    def test_limit_combines_comments_and_questions(self):
        d = self.make_director(max_pending_per_viewer=2)
        self.assertTrue(d.offer(event("comment", kind="viewer_comment"), now=10))
        self.assertTrue(d.offer(event("question"), now=10))
        self.assertFalse(d.offer(event("extra", kind="viewer_comment"), now=10))
        self.assertEqual(d.metrics()["viewer_queue_limited"], 1)
        self.assertTrue(d.offer(event("friend", speaker="viewerB"), now=10))

    def test_a_rejected_flood_does_not_cancel_inflight_speech_intent(self):
        d = self.make_director(max_pending_per_viewer=1)
        self.assertTrue(d.offer(event("first"), now=10))
        prepared = d.propose(now=10)
        self.assertIsNotNone(prepared)
        for i in range(5):
            self.assertFalse(d.offer(event(f"later{i}"), now=10))
        self.assertTrue(d.complete(prepared, now=11, spoken=True))
        self.assertEqual(d.metrics()["completed"], 1)
        self.assertEqual(d.metrics()["queued"], 0)

    def test_expired_messages_release_capacity(self):
        d = self.make_director(max_pending_per_viewer=1)
        self.assertTrue(d.offer(event("old", kind="viewer_comment"), now=10))
        self.assertFalse(d.offer(event("other", now=11), now=11))
        # Viewer comments expire after 20s even without an utterance.
        self.assertTrue(d.offer(event("new", now=31), now=31))
        self.assertEqual(d.metrics()["queued"], 1)
        self.assertGreaterEqual(d.metrics()["expired"], 1)

    def test_owner_and_verified_game_events_are_never_per_viewer_throttled(self):
        d = self.make_director(max_events=3, max_pending_per_viewer=1)
        self.assertTrue(d.offer(event("q1"), now=10))
        self.assertFalse(d.offer(event("q2"), now=10))
        owner = StreamSignal("stop", "owner_interrupt", 10.0, "Stop the audio")
        game = StreamSignal("danger", "game_danger", 10.0, "Observed incoming projectile",
                            evidence="observed")
        self.assertTrue(d.offer(owner, now=10))
        self.assertTrue(d.offer(game, now=10))
        self.assertEqual(d.propose(now=10).kind, "owner_interrupt")

    def test_session_reset_and_privacy_minimal_metrics(self):
        d = self.make_director(max_pending_per_viewer=1)
        self.assertTrue(d.offer(event("first", speaker="sensitiveViewerName"), now=10))
        self.assertFalse(d.offer(event("second", speaker="sensitiveViewerName"), now=10))
        self.assertNotIn("sensitiveViewerName", repr(d.metrics()))
        d.disable()
        d.enable(owner_approved=True)
        self.assertTrue(d.offer(event("fresh", speaker="sensitiveViewerName", now=12), now=12))
        self.assertEqual(d.metrics()["queued"], 1)

    def test_constructor_strict_validation(self):
        for value in (0, 17, -1, True, 1.0, "2", None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    StreamDirector(max_pending_per_viewer=value)
        StreamDirector(max_pending_per_viewer=1)
        StreamDirector(max_pending_per_viewer=16)


if __name__ == "__main__":
    unittest.main()
