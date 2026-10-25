"""Offline real-time control tests: no game, network, media or microphones."""
from __future__ import annotations

import unittest

from star.realtime_signal import LiveInbox, PlaybackGate, Signal


def sig(name: str, lane: str, *, observed: int = 1000, age: int = 10000,
        key: str | None = None) -> Signal:
    return Signal(name, lane, observed, observed + age, name, key)


class InboxTests(unittest.TestCase):
    def test_disabled_by_default_and_validation(self):
        inbox = LiveInbox()
        self.assertEqual(inbox.offer(sig("a", "owner"), now_ms=1000), "disabled")
        self.assertIsNone(inbox.take(now_ms=1000))
        with self.assertRaises(ValueError):
            sig("a", "other")
        with self.assertRaises(ValueError):
            sig("raw user text", "chat")
        with self.assertRaises(ValueError):
            Signal("a", "chat", True, 100, "a")
        with self.assertRaises(ValueError):
            Signal("a", "chat", 100, 100, "a")
        with self.assertRaises(ValueError):
            sig("a", "chat", key="room")

    def test_priority_and_deadline_expiry(self):
        inbox = LiveInbox(enabled=True)
        for item in (sig("view", "vision"), sig("reply", "chat"),
                     sig("game", "game"), sig("urgent", "urgent_game"),
                     sig("owner", "owner")):
            self.assertEqual(inbox.offer(item, now_ms=1000), "admitted")
        self.assertEqual([inbox.take(now_ms=1001).event_id for _ in range(5)],
                         ["owner", "urgent", "game", "reply", "view"])
        self.assertIsNone(inbox.take(now_ms=1001))
        self.assertEqual(inbox.offer(sig("old", "game", observed=1000, age=10), now_ms=1010), "expired")
        self.assertEqual(inbox.offer(sig("new", "game", observed=1000, age=20), now_ms=1000), "admitted")
        self.assertIsNone(inbox.take(now_ms=1020))
        self.assertEqual(inbox.metrics()["expired"], 1)

    def test_chat_fairness_applies_only_to_nonurgent_game_events(self):
        inbox = LiveInbox(enabled=True, game_burst=2)
        for i in range(5):
            inbox.offer(sig(f"g{i}", "game", observed=1000 + i), now_ms=1005)
        inbox.offer(sig("viewer", "chat"), now_ms=1005)
        inbox.offer(sig("alert", "urgent_game"), now_ms=1005)
        self.assertEqual([inbox.take(now_ms=1006).event_id for _ in range(4)],
                         ["alert", "g0", "g1", "viewer"])

    def test_stale_vision_coalescing_and_atomic_rejection(self):
        inbox = LiveInbox(enabled=True, capacity=1)
        self.assertEqual(inbox.offer(sig("f1", "vision", observed=1000, key="screen"), now_ms=1000), "admitted")
        self.assertEqual(inbox.offer(sig("f2", "vision", observed=999, key="screen"), now_ms=1000), "out_of_order")
        self.assertEqual(inbox.metrics()["pending"], 1)
        self.assertEqual(inbox.offer(sig("f2", "vision", observed=1002, key="screen"), now_ms=1002), "admitted")
        self.assertEqual(inbox.metrics()["coalesced"], 1)
        self.assertEqual(inbox.take(now_ms=1003).event_id, "f2")

    def test_capacity_preserves_owner_and_allows_urgent_preemption(self):
        inbox = LiveInbox(enabled=True, capacity=2)
        inbox.offer(sig("back", "background"), now_ms=1000)
        inbox.offer(sig("viewer", "chat"), now_ms=1000)
        self.assertEqual(inbox.offer(sig("owner", "owner"), now_ms=1000), "admitted")
        self.assertEqual(inbox.metrics()["capacity_evicted"], 1)
        self.assertEqual(inbox.offer(sig("newbg", "background"), now_ms=1000), "full")
        self.assertEqual([inbox.take(now_ms=1000).event_id for _ in range(2)], ["owner", "viewer"])

    def test_same_id_update_duplicate_future_and_disable_clears(self):
        inbox = LiveInbox(enabled=True)
        sample = sig("frame", "vision", key="screen")
        self.assertEqual(inbox.offer(sample, now_ms=1000), "admitted")
        self.assertEqual(inbox.offer(sample, now_ms=1000), "duplicate")
        self.assertEqual(inbox.offer(sig("frame", "vision", observed=1001, key="screen"), now_ms=1001), "admitted")
        self.assertEqual(inbox.offer(sig("future", "chat", observed=2000), now_ms=1000), "future")
        inbox.disable()
        self.assertEqual(inbox.metrics()["pending"], 0)
        self.assertIsNone(inbox.take(now_ms=2000))

    def test_lane_cap_and_no_overflow(self):
        inbox = LiveInbox(enabled=True, capacity=64)
        for i in range(30):
            inbox.offer(sig(f"f{i}", "vision", observed=1000+i), now_ms=1030)
        self.assertLessEqual(inbox.metrics()["pending"], 2)
        self.assertGreater(inbox.metrics()["lane_evicted"], 0)


class PlaybackTests(unittest.TestCase):
    def test_opt_in_and_explicit_ticket_lifetime(self):
        gate = PlaybackGate()
        with self.assertRaises(PermissionError):
            gate.open_session("show")
        gate = PlaybackGate(enabled=True)
        gate.open_session("show")
        ticket = gate.begin_turn(now_ms=100, ttl_ms=25)
        self.assertTrue(gate.allows(ticket, now_ms=124))
        self.assertFalse(gate.allows(ticket, now_ms=125))
        gate.interrupt()
        self.assertFalse(gate.allows(ticket, now_ms=110))
        self.assertTrue(gate.allows(gate.begin_turn(now_ms=111), now_ms=111))

    def test_new_session_id_cannot_replay_old_audio(self):
        gate = PlaybackGate(enabled=True)
        gate.open_session("same")
        old = gate.begin_turn(now_ms=100)
        gate.close_session()
        gate.open_session("same")
        fresh = gate.begin_turn(now_ms=105)
        self.assertFalse(gate.allows(old, now_ms=106))
        self.assertTrue(gate.allows(fresh, now_ms=106))
        gate.disable()
        self.assertFalse(gate.allows(fresh, now_ms=107))

    def test_new_turn_supersedes_old_generation(self):
        gate = PlaybackGate(enabled=True)
        gate.open_session("one")
        old = gate.begin_turn(now_ms=0)
        current = gate.begin_turn(now_ms=1)
        self.assertFalse(gate.allows(old, now_ms=2))
        self.assertTrue(gate.allows(current, now_ms=2))
        with self.assertRaises(ValueError):
            gate.begin_turn(now_ms=0, ttl_ms=30001)


if __name__ == "__main__":
    unittest.main()
