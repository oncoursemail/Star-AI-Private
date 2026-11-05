"""Fail closed on host time reversal during opt-in VTuber speech pacing."""
import unittest

from star.stream_director import StreamDirector, StreamSignal


def cue(ident, at):
    return StreamSignal(ident, "game_observation", at, "Observed " + ident,
                        evidence="observed")


class ProactiveClockRollbackTests(unittest.TestCase):
    def make_director(self):
        d = StreamDirector(gap_seconds=0, proactive_limit_per_minute=1)
        d.enable(owner_approved=True)
        return d

    def test_old_host_clock_cannot_reopen_expired_optional_quota(self):
        d = self.make_director()
        self.assertTrue(d.offer(cue("first", 10), now=10))
        self.assertTrue(d.complete(d.propose(now=10), now=10, spoken=True))
        self.assertIsNone(d.propose(now=71))  # The rolling window expired.
        # A wall-clock rollback must not restore the old 11-second timeline.
        self.assertFalse(d.offer(cue("rollback", 11), now=11))
        self.assertIsNone(d.propose(now=11))
        self.assertTrue(d.offer(cue("fresh", 71), now=71))
        self.assertEqual(d.propose(now=71).signal_id, "fresh")

    def test_backward_proposal_cannot_supersede_valid_receipt(self):
        d = self.make_director()
        self.assertTrue(d.offer(cue("first", 10), now=10))
        d.propose(now=10)
        good = d.propose(now=11)
        self.assertIsNotNone(good)
        self.assertIsNone(d.propose(now=10))
        self.assertTrue(d.complete(good, now=11, spoken=True))

    def test_backward_failed_playback_ack_cannot_abandon_event(self):
        d = self.make_director()
        self.assertTrue(d.offer(cue("first", 10), now=10))
        good = d.propose(now=11)
        self.assertIsNotNone(good)
        self.assertFalse(d.complete(good, now=9, spoken=False))
        self.assertEqual(d.metrics()["proactive_pending"], 1)
        self.assertTrue(d.complete(good, now=11, spoken=True))

    def test_clock_guard_opt_out_and_reset_on_disable(self):
        d = self.make_director()
        self.assertIsNone(d.propose(now=200))
        d.disable()
        d.enable(owner_approved=True)
        self.assertTrue(d.offer(cue("new_session", 10), now=10))
        self.assertIsNotNone(d.propose(now=10))
        legacy = StreamDirector(gap_seconds=0, proactive_limit_per_minute=0)
        legacy.enable(owner_approved=True)
        self.assertIsNone(legacy.propose(now=200))
        self.assertTrue(legacy.offer(cue("legacy", 10), now=10))


if __name__ == "__main__":
    unittest.main()
