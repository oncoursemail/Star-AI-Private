"""Offline Twitch protocol checks. No real token, OS vault, socket or API is used."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from star import twitch_chat as twitch  # noqa: E402

TOKEN = "offline-test-token-not-a-real-secret"
CLIENT, CHANNEL = "fixtureclient", "1234"


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def wall(self):
        return 1_800_000_000 + self.now

    def advance(self, seconds):
        self.now += seconds


class Stop:
    def __init__(self, clock, *, stop_on_wait=False):
        self.clock, self.stopped, self.stop_on_wait = clock, False, stop_on_wait
        self.waits = []

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def wait(self, seconds):
        self.waits.append(seconds)
        self.clock.advance(seconds)
        if self.stop_on_wait:
            self.set()


class Vault:
    def __init__(self):
        self.value, self.writes = TOKEN, []

    def get(self, _key):
        return self.value

    def put(self, key, value):
        self.writes.append((key, value))
        self.value = value


class HTTP:
    def __init__(self):
        self.calls = []
        self.validation = {"client_id": CLIENT, "user_id": CHANNEL, "scopes": ["user:read:chat"], "expires_in": 10000}
        self.status = 200
        self.fail = False

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if self.fail:
            raise RuntimeError(TOKEN + " synthetic upstream body")
        if url == twitch.VALIDATE:
            body, status = self.validation, self.status
        else:
            kind = kwargs["json"]["type"]
            body, status = {"data": [{"id": "sub-" + kind.replace(".", "-"), "type": kind, "status": "enabled"}]}, 202
        return SimpleNamespace(status_code=status, content=json.dumps(body).encode(), json=lambda: body)


class Socket:
    def __init__(self, rows, clock, stop):
        self.rows, self.clock, self.stop, self.closed = list(rows), clock, stop, False

    def recv(self):
        row = self.rows.pop(0) if self.rows else "STOP"
        if callable(row):
            row = row()
        if isinstance(row, Exception):
            raise row
        if row == "STOP":
            self.stop.set()
            return None
        if row is None:
            self.clock.advance(2)
        return json.dumps(row) if isinstance(row, dict) else row

    def close(self):
        self.closed = True


class TwitchChecks(unittest.TestCase):
    def setUp(self):
        self.clock, self.http, self.vault = Clock(), HTTP(), Vault()
        self.stop = Stop(self.clock)
        self.delivered = []
        self.reader = twitch.TwitchChat(CLIENT, CHANNEL, vault=self.vault, http=self.http,
            clock=self.clock, wall_clock=self.clock.wall, on_chat=self.delivered.append)
        self.sequence = 0

    def frame(self, kind, payload=None, *, subtype=None, stamp=None):
        self.sequence += 1
        meta = {"message_id": "envelope-" + str(self.sequence), "message_type": kind,
                "message_timestamp": datetime.fromtimestamp(self.clock.wall() if stamp is None else stamp, timezone.utc).isoformat()}
        if subtype:
            meta.update(subscription_type=subtype, subscription_version="1")
        return {"metadata": meta, "payload": payload or {}}

    def welcome(self, identifier="session-1"):
        return self.frame("session_welcome", {"session": {"id": identifier, "keepalive_timeout_seconds": 10}})

    def event(self, kind="channel.chat.message", *, message_id="message-1", user="999", stamp=None, channel=CHANNEL):
        sub = {"id": "sub-" + kind.replace(".", "-"), "type": kind, "version": "1", "status": "enabled",
               "condition": {"broadcaster_user_id": CHANNEL, "user_id": CHANNEL}}
        event = {"broadcaster_user_id": channel, "message_id": message_id, "chatter_user_id": user,
                 "chatter_user_name": "FixtureViewer", "message": {"text": "offline untrusted chat"}, "target_user_id": user}
        return self.frame("notification", {"subscription": sub, "event": event}, subtype=kind, stamp=stamp)

    def connect(self, rows):
        socket = Socket(rows, self.clock, self.stop)
        self.reader._socket_factory = lambda _url: socket
        return socket

    def ready(self):
        self.reader.check_auth()
        self.reader._subscribe("session-1", self.stop)

    def test_queue_pop_expiry_deletion_tombstones_and_bounds(self):
        queue = twitch.ChatQueue(capacity=2, ttl=5, clock=self.clock)
        make = lambda key, user="999": twitch.ChatMessage(key, CHANNEL, user, "Viewer", "text", self.clock())
        self.assertTrue(queue.put(make("a")))
        self.assertEqual(queue.pop().message_id, "a")
        self.assertTrue(queue.current("a"))
        queue.remove("a")
        self.assertFalse(queue.current("a"))
        self.assertFalse(queue.put(make("a")))
        queue.remove("before-delivery")
        self.assertFalse(queue.put(make("before-delivery")))
        for key in ("b", "c", "d"):
            queue.put(make(key))
        self.assertFalse(queue.current("b"))
        self.assertEqual(queue.counts()["current"], 2)
        queue.clear_user("999")
        self.assertFalse(queue.current("c"))
        queue.put(make("e", "888"))
        self.clock.advance(6)
        self.assertFalse(queue.current("e"))
        self.assertIsNone(queue.peek())
        for index in range(4100):
            queue.remove("deleted-" + str(index))
        self.assertLessEqual(len(queue._seen), 4096)

    def test_validate_scope_identity_expiry_and_save_before_native_storage(self):
        self.assertTrue(self.reader.save_token("oauth:" + TOKEN)["saved"])
        self.assertEqual(self.vault.writes[0][1], TOKEN)
        self.assertNotIn(TOKEN, self.vault.writes[0][0])
        for change in ({"client_id": "other"}, {"user_id": "888"}, {"scopes": ["user:read:chat", "user:write:chat"]},
                       {"scopes": []}, {"expires_in": 0}, {"expires_in": True}):
            old = self.http.validation.copy()
            self.http.validation.update(change)
            with self.assertRaises(twitch.AuthorizationError):
                self.reader.save_token(TOKEN)
            self.http.validation = old
        self.assertEqual(len(self.vault.writes), 1)
        self.assertFalse(self.reader.status()["authenticated"])

    def test_seen_overflow_invalidates_pending_and_cannot_resurrect_deletion(self):
        queue = twitch.ChatQueue(clock=self.clock)
        queue.remove("deleted")
        for index in range(4096):
            queue.put(twitch.ChatMessage("new-" + str(index), CHANNEL, "999", "Viewer", "text", self.clock()))
        self.assertFalse(queue.put(twitch.ChatMessage("deleted", CHANNEL, "999", "Viewer", "text", self.clock())))
        self.assertEqual(queue.counts()["current"], 0)
        self.assertTrue(queue.counts()["overloaded"])
        self.clock.advance(76)
        self.assertTrue(queue.put(twitch.ChatMessage("fresh", CHANNEL, "999", "Viewer", "text", self.clock())))
        self.assertFalse(queue.counts()["overloaded"])

    def test_overflow_cooldown_also_covers_future_skew_and_exact_ttl_boundary(self):
        self.ready()
        self.reader.queue.remove("deleted")
        future_stamp = self.clock.wall() + 30
        for index in range(4096):
            self.reader.queue.put(twitch.ChatMessage("burst-" + str(index), CHANNEL, "999", "Viewer", "text", self.clock()))
        self.clock.advance(74)
        self.reader._handle(json.dumps(self.event(message_id="deleted", stamp=future_stamp)))
        self.assertFalse(self.reader.queue.current("deleted"))
        self.clock.advance(1)
        self.reader._handle(json.dumps(self.event(message_id="deleted", stamp=future_stamp)))
        self.assertFalse(self.reader.queue.current("deleted"))
        self.reader._handle(json.dumps(self.event(message_id="fresh-after-overflow")))
        self.assertTrue(self.reader.queue.current("fresh-after-overflow"))

    def test_endpoints_redirects_and_errors_do_not_expose_token_or_bodies(self):
        self.reader.check_auth()
        _, url, kwargs = self.http.calls[-1]
        self.assertEqual(url, twitch.VALIDATE)
        self.assertIs(kwargs["follow_redirects"], False)
        self.assertEqual(kwargs["headers"]["Authorization"], "OAuth " + TOKEN)
        with self.assertRaises(PermissionError):
            self.reader._request("https://example.invalid/", token=TOKEN)
        self.http.status = 302
        with self.assertRaises(twitch.TwitchChatError):
            self.reader.check_auth()
        self.http.fail = True
        with self.assertRaises(twitch.TwitchChatError) as caught:
            self.reader.check_auth()
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertNotIn(TOKEN, json.dumps(self.reader.status()))

    def test_native_vault_has_no_plaintext_backend_fallback(self):
        backend = type("PlaintextBackend", (), {"__module__": "keyrings.alt.file"})()
        fake = SimpleNamespace(get_keyring=lambda: backend)
        with patch.dict(sys.modules, {"keyring": fake}):
            with self.assertRaises(RuntimeError):
                twitch.TwitchSecrets._backend()

    def test_four_own_channel_subscriptions_and_no_write_scope_or_send_api(self):
        self.ready()
        posts = [row for row in self.http.calls if row[0] == "POST"]
        self.assertEqual(len(posts), 4)
        self.assertEqual({row[2]["json"]["type"] for row in posts}, set(twitch.TYPES))
        for _, url, kwargs in posts:
            self.assertEqual(url, twitch.SUBSCRIPTIONS)
            self.assertEqual(kwargs["json"]["condition"], {"broadcaster_user_id": CHANNEL, "user_id": CHANNEL})
            self.assertEqual(kwargs["json"]["transport"], {"method": "websocket", "session_id": "session-1"})
        self.assertFalse(hasattr(self.reader, "send_message"))

    def test_message_dedupe_delete_before_delivery_and_clear_invalidates_popped(self):
        self.ready()
        send = lambda frame: self.reader._handle(json.dumps(frame))
        send(self.event())
        selected = self.reader.queue.pop()
        self.assertTrue(self.reader.queue.current(selected.message_id))
        send(self.event("channel.chat.message_delete"))
        self.assertFalse(self.reader.queue.current(selected.message_id))
        send(self.event())
        self.assertEqual(len(self.delivered), 1)
        send(self.event("channel.chat.message_delete", message_id="late"))
        send(self.event(message_id="late"))
        self.assertEqual(len(self.delivered), 1)
        self.clock.advance(1)
        send(self.event(message_id="new"))
        self.reader.queue.pop()
        send(self.event("channel.chat.clear_user_messages"))
        self.assertFalse(self.reader.queue.current("new"))
        send(self.event(message_id="old-after-clear", stamp=self.clock.wall() - 0.5))
        self.assertFalse(self.reader.queue.current("old-after-clear"))
        self.clock.advance(1)
        send(self.event(message_id="other", user="888"))
        send(self.event("channel.chat.clear"))
        self.assertFalse(self.reader.queue.current("other"))

    def test_wrong_channel_stale_text_unknown_subscription_and_callback_failure(self):
        self.ready()
        for value in (self.event(channel="777"), self.event(stamp=self.clock.wall() - 60)):
            self.reader._handle(json.dumps(value))
        unknown = self.event()
        unknown["payload"]["subscription"]["id"] = "not-subscribed"
        self.reader._handle(json.dumps(unknown))
        self.assertEqual(self.delivered, [])
        self.reader.on_chat = lambda _row: (_ for _ in ()).throw(RuntimeError(TOKEN))
        self.reader._handle(json.dumps(self.event(message_id="callback")))
        self.assertEqual(self.reader.status()["callback_errors"], 1)
        self.assertNotIn(TOKEN, json.dumps(self.reader.status()))

    def test_revocation_clears_selected_messages_and_ends_session(self):
        def revoked():
            frame = self.event()
            frame["metadata"]["message_type"] = "revocation"
            frame["payload"].pop("event")
            return frame
        socket = self.connect([lambda: self.welcome(), lambda: self.event(), revoked])
        state = self.reader.run(self.stop)
        self.assertEqual(state["error"], "subscription_revoked")
        self.assertFalse(self.reader.queue.current("message-1"))
        self.assertTrue(socket.closed)
        self.assertFalse(state["authenticated"])

    def test_hourly_validation_and_keepalive_timeout(self):
        def elapsed():
            self.clock.advance(3501)
            return self.frame("session_keepalive")
        self.connect([lambda: self.welcome(), elapsed, "STOP"])
        self.reader.run(self.stop)
        self.assertEqual(sum(url == twitch.VALIDATE for _, url, _ in self.http.calls), 2)
        self.setUp()
        self.stop.stop_on_wait = True
        self.connect([lambda: self.welcome(), *([None] * 7)])
        state = self.reader.run(self.stop)
        self.assertEqual(state["error"], "keepalive_timeout")
        self.assertEqual(self.stop.waits, [1])

    def test_migration_keeps_old_until_welcome_and_does_not_resubscribe(self):
        url = twitch.EVENTSUB + "?session=opaque-fixture"
        sockets = []
        def new_welcome():
            self.assertFalse(sockets[0].closed)
            return self.welcome("session-2")
        def after_welcome():
            self.assertTrue(sockets[0].closed)
            self.assertFalse(self.reader.queue.current("message-1"))
            self.clock.advance(0.1)
            return self.event(message_id="message-2")
        old = Socket([lambda: self.welcome(), lambda: self.event(),
            lambda: self.frame("session_reconnect", {"session": {"reconnect_url": url}})], self.clock, self.stop)
        new = Socket([new_welcome, after_welcome, "STOP"], self.clock, self.stop)
        sockets.extend([old, new])
        urls = []
        def factory(value):
            urls.append(value)
            return sockets[len(urls) - 1]
        self.reader._socket_factory = factory
        self.reader.run(self.stop)
        self.assertEqual(urls, [twitch.EVENTSUB, url])
        self.assertEqual(sum(method == "POST" for method, _, _ in self.http.calls), 4)
        self.assertEqual([row.message_id for row in self.delivered], ["message-1", "message-2"])

    def test_abrupt_disconnect_clears_and_resubscribes_without_exposing_errors(self):
        sockets, urls = [], []
        def fresh():
            self.assertFalse(self.reader.queue.current("message-1"))
            self.clock.advance(0.1)
            return self.event(message_id="message-2")
        sockets.append(Socket([lambda: self.welcome(), lambda: self.event(), RuntimeError(TOKEN)], self.clock, self.stop))
        sockets.append(Socket([lambda: self.welcome("new-session"), fresh, "STOP"], self.clock, self.stop))
        def factory(value):
            urls.append(value)
            return sockets[len(urls) - 1]
        self.reader._socket_factory = factory
        self.reader.run(self.stop)
        self.assertEqual(urls, [twitch.EVENTSUB, twitch.EVENTSUB])
        self.assertEqual(sum(method == "POST" for method, _, _ in self.http.calls), 8)
        self.assertNotIn(TOKEN, json.dumps(self.reader.status()))

    def test_reconnect_allowlist_and_native_socket_arguments_without_network(self):
        for value in ("ws://eventsub.wss.twitch.tv/ws", "wss://example.invalid/ws", "wss://eventsub.wss.twitch.tv:444/ws",
                      "wss://eventsub.wss.twitch.tv@other/ws", "wss://eventsub.wss.twitch.tv/ws#fragment",
                      "wss://eventsub.wss.twitch.tv/other", "wss://eventsub.wss.twitch.tv/ws\n"):
            with self.assertRaises(twitch.TwitchChatError):
                twitch.reconnect_url(value)
        url = "wss://eventsub.wss.twitch.tv/ws?token=opaque-fixture"
        self.assertEqual(twitch.reconnect_url(url), url)
        module, arguments = ModuleType("websocket"), []
        module.enableTrace = lambda enabled: self.assertFalse(enabled)
        module.ABNF = SimpleNamespace(OPCODE_TEXT=1, OPCODE_PING=9, OPCODE_PONG=10)
        module.WebSocketTimeoutException = TimeoutError
        native = SimpleNamespace(recv_data=lambda **kwargs: (9, b"ping"), close=lambda: None)
        module.create_connection = lambda *args, **kwargs: arguments.append((args, kwargs)) or native
        with patch.dict(sys.modules, {"websocket": module}):
            socket = twitch._Socket(url)
            self.assertIsNone(socket.recv())
            socket.close()
        self.assertEqual(arguments[0][1]["redirect_limit"], 0)
        self.assertTrue(arguments[0][1]["sslopt"]["check_hostname"])
        self.assertFalse(hasattr(socket, "send"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
