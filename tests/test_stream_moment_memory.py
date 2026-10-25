"""Offline stream event test fixtures; no stream or speech is produced."""
import unittest

from star.stream_moment_memory import GameMoment, StreamMomentMemory

SHA = "a" * 64


def m(*, session="stream1", event_id="event1", seq=1, kind="discovery", topic="boss",
      occurred_ms=1000, evidence_sha256=SHA):
    return GameMoment(session, event_id, seq, kind, topic, occurred_ms, evidence_sha256)


class StreamMomentMemoryTests(unittest.TestCase):
    def test_no_broadcast_permission_by_default(self):
        book = StreamMomentMemory()
        book.observe(m(), trusted_game_adapter=True)
        self.assertIsNone(book.next_cue("stream1", 2000))

    def test_no_fabricated_cue_without_events(self):
        self.assertIsNone(StreamMomentMemory().next_cue("stream1", 5000, audience_can_hear=True))

    def test_host_telemetry_required(self):
        book = StreamMomentMemory()
        with self.assertRaises(PermissionError):
            book.observe(m())

    def test_valid_reaction_from_evidence(self):
        book = StreamMomentMemory()
        book.observe(m(), trusted_game_adapter=True)
        cue = book.next_cue("stream1", 2000, audience_can_hear=True)
        self.assertEqual(cue.kind, "discovery")
        self.assertEqual(cue.event_ids, ("event1",))
        self.assertNotIn("human memory", cue.brief)

    def test_no_repeat_reaction(self):
        book = StreamMomentMemory()
        book.observe(m(), trusted_game_adapter=True)
        book.next_cue("stream1", 2000, audience_can_hear=True)
        self.assertIsNone(book.next_cue("stream1", 20000, audience_can_hear=True))

    def test_cooldown_limits_speech(self):
        book = StreamMomentMemory()
        book.observe(m(), trusted_game_adapter=True)
        book.observe(m(event_id="event2", seq=2, occurred_ms=3000), trusted_game_adapter=True)
        book.next_cue("stream1", 4000, audience_can_hear=True)
        self.assertIsNone(book.next_cue("stream1", 6000, audience_can_hear=True))
        self.assertEqual(book.next_cue("stream1", 13000, audience_can_hear=True).event_ids, ("event1",))

    def test_real_comeback_story_callback(self):
        book = StreamMomentMemory()
        book.observe(m(kind="failure"), trusted_game_adapter=True)
        book.observe(m(event_id="event2", seq=2, occurred_ms=9000, kind="recovery"), trusted_game_adapter=True)
        cue = book.next_cue("stream1", 10000, audience_can_hear=True)
        self.assertEqual(cue.kind, "callback")
        self.assertEqual(cue.event_ids, ("event1", "event2"))

    def test_comeback_follows_prior_reaction(self):
        book = StreamMomentMemory()
        book.observe(m(kind="failure"), trusted_game_adapter=True)
        self.assertEqual(book.next_cue("stream1", 2000, audience_can_hear=True).kind, "failure")
        book.observe(m(event_id="event2", seq=2, occurred_ms=14000, kind="recovery"), trusted_game_adapter=True)
        self.assertEqual(book.next_cue("stream1", 15000, audience_can_hear=True).kind, "callback")

    def test_cross_topic_not_a_comeback(self):
        book = StreamMomentMemory()
        book.observe(m(kind="failure", topic="start"), trusted_game_adapter=True)
        book.observe(m(event_id="event2", seq=2, kind="recovery", topic="boss", occurred_ms=9000), trusted_game_adapter=True)
        self.assertEqual(book.next_cue("stream1", 10000, audience_can_hear=True).kind, "recovery")

    def test_cross_session_cannot_mingle(self):
        book = StreamMomentMemory()
        book.observe(m(kind="failure"), trusted_game_adapter=True)
        book.observe(m(session="stream2", event_id="event2", kind="recovery"), trusted_game_adapter=True)
        self.assertEqual(book.next_cue("stream2", 3000, audience_can_hear=True).kind, "recovery")

    def test_stale_events_silence(self):
        book = StreamMomentMemory(max_age_ms=1000)
        book.observe(m(), trusted_game_adapter=True)
        self.assertIsNone(book.next_cue("stream1", 3000, audience_can_hear=True))

    def test_future_events_silence(self):
        book = StreamMomentMemory()
        book.observe(m(occurred_ms=10000), trusted_game_adapter=True)
        self.assertIsNone(book.next_cue("stream1", 9000, audience_can_hear=True))

    def test_repeated_or_out_of_order_denied(self):
        book = StreamMomentMemory()
        book.observe(m(seq=3), trusted_game_adapter=True)
        with self.assertRaises(ValueError):
            book.observe(m(seq=2, event_id="event2"), trusted_game_adapter=True)

    def test_duplicate_event_id_denied_even_with_new_seq(self):
        book = StreamMomentMemory()
        book.observe(m(), trusted_game_adapter=True)
        with self.assertRaises(ValueError):
            book.observe(m(seq=2, occurred_ms=2000), trusted_game_adapter=True)

    def test_callback_consumes_failure_also(self):
        book = StreamMomentMemory()
        book.observe(m(kind="failure"), trusted_game_adapter=True)
        book.observe(m(event_id="event2", seq=2, occurred_ms=9000, kind="recovery"), trusted_game_adapter=True)
        self.assertEqual(book.next_cue("stream1", 10000, audience_can_hear=True).kind, "callback")
        self.assertIsNone(book.next_cue("stream1", 20000, audience_can_hear=True))

    def test_backward_event_time_denied(self):
        book = StreamMomentMemory()
        book.observe(m(occurred_ms=3000), trusted_game_adapter=True)
        with self.assertRaises(ValueError):
            book.observe(m(seq=2, occurred_ms=2000, event_id="event2"), trusted_game_adapter=True)

    def test_capacities_fails_closed(self):
        book = StreamMomentMemory(max_moments=1)
        book.observe(m(), trusted_game_adapter=True)
        with self.assertRaises(OverflowError):
            book.observe(m(seq=2, event_id="event2"), trusted_game_adapter=True)
        book2 = StreamMomentMemory(max_sessions=1)
        book2.observe(m(), trusted_game_adapter=True)
        with self.assertRaises(OverflowError):
            book2.observe(m(session="stream2"), trusted_game_adapter=True)

    def test_invalid_moments(self):
        for bad in [dict(session="../../"), dict(seq=True), dict(kind="win-in-real-life"),
                    dict(occurred_ms=-5), dict(evidence_sha256="banana"), dict(topic=""), dict(event_id=" with spaces")]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                m(**bad)

    def test_invalid_limits(self):
        with self.assertRaises(ValueError):
            StreamMomentMemory(min_gap_ms=-1)
        with self.assertRaises(ValueError):
            StreamMomentMemory(max_age_ms=500)

    def test_context_not_leaked(self):
        book = StreamMomentMemory()
        book.observe(m(), trusted_game_adapter=True)
        cue = book.next_cue("stream1", 1001, audience_can_hear=True)
        self.assertEqual(cue.event_ids, ("event1",))
        self.assertEqual(set(book.summary()), {"moments", "sessions", "cues"})

    def test_external_speech_still_requires_gate(self):
        book = StreamMomentMemory()
        book.observe(m(), trusted_game_adapter=True)
        cue = book.next_cue("stream1", 2000, audience_can_hear=True)
        self.assertFalse(hasattr(cue, "audio"))
        self.assertFalse(hasattr(book, "broadcast"))


if __name__ == "__main__":
    unittest.main()
