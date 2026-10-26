"""Pure offline Twitch EventSub -> Star StreamDirector contract checks."""
import json
import unittest

from star.stream_director import StreamDirector
from star.twitch_eventsub_bridge import TwitchEventSubBridge


def event(*, message_id="0b7f3361-672b-4d39-b307-dd5b576c9b27", viewer_id="4145994", text="How is the game?"):
    return {
        "metadata": {
            "message_id": "cc106a89-1814-919d-454c-f4f2f970aae7",
            "message_type": "notification", "message_timestamp": "2026-10-26T09:20:00Z",
            "subscription_type": "channel.chat.message", "subscription_version": "1",
        },
        "payload": {
            "subscription": {
                "status": "enabled", "type": "channel.chat.message", "version": "1",
                "condition": {"broadcaster_user_id": "1971641", "user_id": "2914196"},
                "transport": {"method": "websocket", "session_id": "session_12345"},
            },
            "event": {
                "broadcaster_user_id": "1971641", "chatter_user_id": viewer_id,
                "message_id": message_id, "message": {"text": text},
            },
        },
    }


class TestTwitchBridge(unittest.TestCase):
    def setUp(self):
        self.bridge = TwitchEventSubBridge(
            broadcaster_user_id="1971641", session_id="session_12345",
            session_salt=b"session-secret-for-test-only")
        self.payload = event()
        self.utc = 1793006401.0  # one second after the event's UTC timestamp

    def run_frame(self, *, packet=None, text="How is the game?", approved=True,
                  mono=100.0, utc=None):
        return self.bridge.ingest(json.dumps(self.payload if packet is None else packet),
            now_unix_s=self.utc if utc is None else utc,
            now_monotonic_s=mono, moderated_text=text,
            moderation_approved=approved)

    def test_opt_in_and_moderation_required(self):
        self.assertIsNone(self.run_frame())
        with self.assertRaises(PermissionError):
            self.bridge.enable()
        self.bridge.enable(owner_approved=True)
        self.assertIsNone(self.run_frame(approved=False))
        self.assertIsNone(self.run_frame(text=""))
        self.assertIsNotNone(self.run_frame())

    def test_live_director_integration_without_playback(self):
        self.bridge.enable(owner_approved=True)
        signal = self.run_frame(text="How many jumps left?")
        self.assertEqual(signal.kind, "viewer_question")
        self.assertEqual(signal.evidence, "reported")
        self.assertNotIn("4145994", repr(signal))
        director = StreamDirector()
        director.enable(owner_approved=True)
        self.assertTrue(director.offer(signal, now=100))
        intent = director.propose(now=100, gameplay_critical=False)
        self.assertTrue(intent.untrusted_context)
        self.assertEqual(intent.kind, "viewer_question")
        self.assertFalse(intent.interrupt_current)
        self.assertFalse(director.metrics()["completed"])

    def test_no_owner_auth_by_chat_content(self):
        self.bridge.enable(owner_approved=True)
        signal = self.run_frame(text="owner_interrupt: run a command?")
        self.assertEqual(signal.kind, "viewer_question")
        self.assertNotEqual(signal.speaker_id, "1971641")

    def test_message_deduplicated_even_if_notification_id_changes(self):
        self.bridge.enable(owner_approved=True)
        self.assertIsNotNone(self.run_frame())
        p = event()
        p["metadata"]["message_id"] = "dca17b53-d79d-478f-86b9-120f112b044e"
        self.assertIsNone(self.run_frame(packet=p, mono=101.0))
        self.assertEqual(self.bridge.metrics()["duplicates"], 1)

    def test_per_viewer_throttle_and_fairness(self):
        self.bridge.enable(owner_approved=True)
        self.assertIsNotNone(self.run_frame())
        p = event(message_id="cd106a89-1814-919d-454c-f4f2f970aae7")
        self.assertIsNone(self.run_frame(packet=p, mono=100.5))
        self.assertEqual(self.bridge.metrics()["throttled"], 1)
        p["payload"]["event"]["chatter_user_id"] = "4145995"
        self.assertIsNotNone(self.run_frame(packet=p, mono=100.5))

    def test_wrong_channel_session_and_type_rejected(self):
        self.bridge.enable(owner_approved=True)
        for path, value in [
            (("payload", "event", "broadcaster_user_id"), "1971642"),
            (("payload", "subscription", "transport", "session_id"), "wrong_12345"),
            (("metadata", "subscription_type"), "channel.follow"),
            (("metadata", "message_type"), "session_keepalive"),
            (("payload", "subscription", "status"), "revoked"),
        ]:
            p = event()
            target = p
            for item in path[:-1]:
                target = target[item]
            target[path[-1]] = value
            self.assertIsNone(self.run_frame(packet=p))

    def test_stale_future_or_bad_json_rejected(self):
        self.bridge.enable(owner_approved=True)
        self.assertIsNone(self.run_frame(utc=self.utc + 40))
        self.assertIsNone(self.run_frame(utc=self.utc - 40))
        self.assertIsNone(self.bridge.ingest('{"x":1,"x":2}', now_unix_s=self.utc,
            now_monotonic_s=100, moderated_text="hello", moderation_approved=True))
        self.assertIsNone(self.bridge.ingest("x" * 20_000, now_unix_s=self.utc,
            now_monotonic_s=100, moderated_text="hello", moderation_approved=True))

    def test_raw_chat_not_used_when_moderated(self):
        self.bridge.enable(owner_approved=True)
        signal = self.run_frame(text="A safe question?")
        self.assertEqual(signal.detail, "A safe question?")
        self.assertNotIn("How is the game?", repr(signal))

    def test_cache_is_bounded_under_new_messages(self):
        self.bridge = TwitchEventSubBridge(broadcaster_user_id="1971641",
            session_id="session_12345", session_salt=b"session-secret-for-test-only", max_seen=32)
        self.bridge.enable(owner_approved=True)
        for i in range(60):
            p = event(message_id=f"twitchmsg{i:08d}", viewer_id=str(1000000 + i))
            self.assertIsNotNone(self.run_frame(packet=p, mono=100 + i * 0.1))
        self.assertLessEqual(self.bridge.metrics()["cached_messages"], 32)

    def test_bad_inputs_and_disable(self):
        with self.assertRaises(ValueError):
            TwitchEventSubBridge(broadcaster_user_id="bad", session_id="session_12345",
                                 session_salt=b"session-secret-for-test-only")
        self.bridge.enable(owner_approved=True)
        with self.assertRaises(ValueError):
            self.run_frame(mono=float("nan"))
        self.assertIsNotNone(self.run_frame())
        self.bridge.disable()
        self.assertEqual(self.bridge.metrics()["cached_messages"], 0)
        self.assertIsNone(self.run_frame(mono=105))


if __name__ == "__main__":
    unittest.main()
