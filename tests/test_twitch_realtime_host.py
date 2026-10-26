"""Offline fake-socket tests: no Twitch account, stream, OBS, or model required."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import time
from unittest.mock import patch

import pytest

from star.stream_director import StreamDirector
from star.twitch_realtime_host import (
    TwitchAuthorizationError, TwitchChatConfig, TwitchProtocolError,
    TwitchRealtimeHost, _packet, _url,
)


class FakeSocket:
    def __init__(self, *events):
        self.events = asyncio.Queue()
        for item in events:
            self.events.put_nowait(item)
        self.closed = False

    async def recv(self):
        result = await self.events.get()
        if isinstance(result, BaseException):
            raise result
        return result

    async def close(self):
        self.closed = True


def envelope(kind, *, session="welcomeSessionABCD", text="Hello Star?", mid="chat-message-aaaa",
             reconnect=None):
    meta = {"message_type": kind, "message_id": "notice-message-aaaa",
            "message_timestamp": datetime.now(timezone.utc).isoformat()}
    payload = {}
    if kind == "session_welcome":
        payload = {"session": {"id": session, "status": "connected",
                               "keepalive_timeout_seconds": 10}}
    if kind == "session_reconnect":
        payload = {"session": {"reconnect_url": reconnect}}
    if kind == "notification":
        meta["subscription_type"] = "channel.chat.message"
        meta["subscription_version"] = "1"
        payload = {
            "subscription": {
                "type": "channel.chat.message", "version": "1",
                "status": "enabled",
                "condition": {"broadcaster_user_id": "12345", "user_id": "99999"},
                "transport": {"method": "websocket", "session_id": session},
            },
            "event": {
                "broadcaster_user_id": "12345",
                "chatter_user_id": "87654",
                "message_id": mid,
                "message": {"text": text},
            },
        }
    return json.dumps({"metadata": meta, "payload": payload})


def make_host(sockets, stop, *, moderate=None, validator=None, on_subscription=None):
    director = StreamDirector()
    director.enable(owner_approved=True)
    requested_urls = []
    socket_iter = iter(sockets)
    async def connect(url):
        requested_urls.append(url)
        return next(socket_iter)
    async def validate(_token):
        if validator is not None:
            return validator
        return {"client_id": "client12345", "user_id": "99999",
                "scopes": ["user:read:chat"], "expires_in": 1800}
    async def subscribe(session, _token):
        if on_subscription is not None:
            on_subscription.append(session)
    async def default_moderate(text):
        stop.set()
        return text
    config = TwitchChatConfig("client12345", "12345", "99999")
    host = TwitchRealtimeHost(
        config=config, director=director, token_provider=lambda: "test-token-123456789",
        moderator=moderate or default_moderate, connect=connect,
        validate_token=validate, subscribe_chat=subscribe,
    )
    return host, director, requested_urls


def test_first_subscription_moderated_chat_reaches_director():
    async def run():
        stop = asyncio.Event()
        socket = FakeSocket(envelope("session_welcome"),
                            envelope("notification", text="Can you do that jump?"))
        subscribed = []
        host, director, urls = make_host([socket], stop, on_subscription=subscribed)
        await asyncio.wait_for(host.run(owner_approved=True, stop=stop), timeout=2)
        intent = director.propose(now=time.monotonic() + 1000)  # stale events expire
        assert intent is None
        assert host.metrics()["subscriptions"] == 1
        assert host.metrics()["delivered"] == 1
        assert host.metrics()["sessions"] == 1
        assert subscribed == ["welcomeSessionABCD"]
        assert urls == ["wss://eventsub.wss.twitch.tv/ws"]
        assert socket.closed
    asyncio.run(run())


def test_director_receives_untrusted_viewer_signal_not_owner_command():
    async def run():
        stop = asyncio.Event()
        socket = FakeSocket(envelope("session_welcome"),
                            envelope("notification", text="Please launch admin tools?", mid="msg-2468-aaaa"))
        host, director, _ = make_host([socket], stop)
        await host.run(owner_approved=True, stop=stop)
        # Inspect bounded queue without exposing credentials or raw platform IDs.
        assert len(director._events) == 1
        event = director._events[0]
        assert event.kind == "viewer_question" and event.evidence == "reported"
        assert event.speaker_id.startswith("v_")
        assert event.speaker_id != "87654"
        assert "admin tools" in event.detail
    asyncio.run(run())


def test_reconnect_handoff_preserves_subscription_and_closes_old_socket():
    async def run():
        stop = asyncio.Event()
        url = "wss://eventsub.wss.twitch.tv/ws?reconnect=opaque"
        original = FakeSocket(envelope("session_welcome", session="oldSession1234"),
                              envelope("session_reconnect", reconnect=url))
        replacement = FakeSocket(envelope("session_welcome", session="newSession1234"),
                                 envelope("notification", session="newSession1234",
                                          mid="chat-new-12345"))
        subscribed = []
        host, director, urls = make_host([original, replacement], stop, on_subscription=subscribed)
        await asyncio.wait_for(host.run(owner_approved=True, stop=stop), timeout=2)
        assert urls == ["wss://eventsub.wss.twitch.tv/ws", url]
        assert subscribed == ["oldSession1234"]  # Twitch transfers subscriptions
        assert host.metrics()["handoffs"] == 1
        assert host.metrics()["delivered"] == 1
        assert original.closed and replacement.closed
    asyncio.run(run())


def test_transport_loss_causes_new_subscription_not_lost_event_replay():
    async def run():
        stop = asyncio.Event()
        first = FakeSocket(envelope("session_welcome", session="lostSession1234"),
                           ConnectionError("socket closed"))
        second = FakeSocket(envelope("session_welcome", session="freshSession1234"),
                            envelope("notification", session="freshSession1234",
                                     mid="fresh-chat-1234"))
        subscribed = []
        host, _, urls = make_host([first, second], stop, on_subscription=subscribed)
        await asyncio.wait_for(host.run(owner_approved=True, stop=stop), timeout=3)
        assert host.metrics()["sessions"] == 2
        assert host.metrics()["restarts"] == 1
        assert subscribed == ["lostSession1234", "freshSession1234"]
        assert len(urls) == 2 and first.closed and second.closed
    asyncio.run(run())


def test_revocation_stops_immediately():
    async def run():
        stop = asyncio.Event()
        socket = FakeSocket(envelope("session_welcome"), envelope("revocation"))
        host, _, _ = make_host([socket], stop)
        with pytest.raises(TwitchAuthorizationError, match="revoked"):
            await host.run(owner_approved=True, stop=stop)
        assert socket.closed and host.metrics()["revocations"] == 1
    asyncio.run(run())


def test_moderation_is_mandatory_and_fail_closed():
    async def run():
        stop = asyncio.Event()
        async def deny(_original):
            stop.set()
            return None
        socket = FakeSocket(envelope("session_welcome"), envelope("notification"))
        host, director, _ = make_host([socket], stop, moderate=deny)
        await host.run(owner_approved=True, stop=stop)
        assert director.metrics()["queued"] == 0
        assert host.metrics()["rejected"] == 1
    asyncio.run(run())


def test_bad_token_scope_fails_before_socket_open():
    async def run():
        stop = asyncio.Event()
        socket = FakeSocket()
        host, _, urls = make_host([socket], stop, validator={
            "client_id": "client12345", "user_id": "99999", "scopes": [], "expires_in": 999,
        })
        with pytest.raises(TwitchAuthorizationError):
            await host.run(owner_approved=True, stop=stop)
        assert not urls
    asyncio.run(run())


def test_no_owner_permission_never_opens_socket():
    async def run():
        stop = asyncio.Event()
        host, _, urls = make_host([], stop)
        with pytest.raises(PermissionError):
            await host.run(owner_approved=False, stop=stop)
        assert not urls
    asyncio.run(run())


def test_reconnect_url_is_pinned_not_ssrf():
    for url in ("https://eventsub.wss.twitch.tv/ws",
                "wss://evil.example/ws", "wss://eventsub.wss.twitch.tv.evil/ws",
                "wss://user@eventsub.wss.twitch.tv/ws",
                "wss://eventsub.wss.twitch.tv:444/ws",
                "wss://eventsub.wss.twitch.tv:invalid/ws",
                "wss://eventsub.wss.twitch.tv/private"):
        with pytest.raises(TwitchProtocolError):
            _url(url)
    assert _url("wss://eventsub.wss.twitch.tv/ws?reconnect=abc").startswith("wss://")


def test_protocol_rejects_duplicate_keys_and_oversized_frame():
    with pytest.raises(TwitchProtocolError):
        _packet('{"metadata": {}, "metadata": {}, "payload": {}}')
    with pytest.raises(TwitchProtocolError):
        _packet("x" * 20_000)


def test_missing_moderation_async_callback_does_not_leak_to_director():
    async def run():
        stop = asyncio.Event()
        def broken_sync_moderator(_text):
            stop.set()
            return "Bad! This must not pass"  # not awaitable
        socket = FakeSocket(envelope("session_welcome"), envelope("notification"))
        host, director, _ = make_host([socket], stop, moderate=broken_sync_moderator)
        await host.run(owner_approved=True, stop=stop)
        assert director.metrics()["queued"] == 0
        assert host.metrics()["rejected"] == 1
    asyncio.run(run())


def test_timeout_or_permission_failure_is_not_reported_as_success():
    async def run():
        stop = asyncio.Event()
        socket = FakeSocket(envelope("session_welcome"), envelope("notification"))
        async def slow(_text):
            await asyncio.sleep(2)
            return "Too late"
        async def stop_after():
            await asyncio.sleep(0.8)
            stop.set()
        host, director, _ = make_host([socket], stop, moderate=slow)
        host.moderator_timeout_s = 0.1
        t = asyncio.create_task(stop_after())
        await asyncio.wait_for(host.run(owner_approved=True, stop=stop), timeout=2)
        await t
        assert host.metrics()["rejected"] == 1
        assert director.metrics()["queued"] == 0
    asyncio.run(run())


def test_token_provider_and_reconnect_error_do_not_echo_secrets():
    async def run():
        stop = asyncio.Event()
        socket = FakeSocket(envelope("session_welcome"),
                            envelope("session_reconnect",
                                     reconnect="wss://attacker.example/ws?secret=not-for-logging"))
        host, _, _ = make_host([socket], stop)
        with pytest.raises(RuntimeError, match="repeatedly") as err:
            await asyncio.wait_for(host.run(owner_approved=True, stop=stop,
                                            max_failures=1), timeout=2)
        assert "secret=" not in str(err.value)
        assert socket.closed
    asyncio.run(run())


def test_subscription_uses_websocket_and_explicit_chat_user_not_app_token():
    async def run():
        stop = asyncio.Event()
        host, _, _ = make_host([], stop)
        host.subscribe_chat = None
        async def fake_http(url, headers, data=None):
            assert url == "https://api.twitch.tv/helix/eventsub/subscriptions"
            assert headers["Authorization"] == "Bearer test-token-123456789"
            assert headers["Client-Id"] == "client12345"
            payload = json.loads(data)
            assert payload == {
                "type": "channel.chat.message", "version": "1",
                "condition": {"broadcaster_user_id": "12345", "user_id": "99999"},
                "transport": {"method": "websocket", "session_id": "welcomeSessionABCD"},
            }
            return 202, {"data": [{
                "status": "enabled", "type": "channel.chat.message",
                "version": "1",
                "transport": {"method": "websocket", "session_id": "welcomeSessionABCD"},
            }]}
        with patch("star.twitch_realtime_host._http_json", fake_http):
            await host._subscribe("welcomeSessionABCD", "test-token-123456789")
    asyncio.run(run())


def test_duplicate_chat_across_handoff_stays_one_signal():
    async def run():
        stop = asyncio.Event()
        count = 0

        async def moderated(text):
            nonlocal count
            count += 1
            return text

        url = "wss://eventsub.wss.twitch.tv/ws?reconnect=test"
        first = FakeSocket(
            envelope("session_welcome", session="oldSession1234"),
            envelope("notification", session="oldSession1234"),
        )
        second = FakeSocket(
            envelope("session_welcome", session="newSession1234"),
            envelope("notification", session="newSession1234"),
        )
        host, director, _ = make_host([first, second], stop, moderate=moderated)

        async def trigger_handoff_and_stop():
            # Verify *confirmed* old delivery before starting the handoff.
            while host.metrics()["delivered"] < 1:
                await asyncio.sleep(0.001)
            first.events.put_nowait(envelope("session_reconnect", reconnect=url))
            while host.metrics()["duplicate_drops"] < 1:
                await asyncio.sleep(0.001)
            stop.set()

        watcher = asyncio.create_task(trigger_handoff_and_stop())
        await asyncio.wait_for(host.run(owner_approved=True, stop=stop), timeout=2)
        await watcher
        assert count == 1
        assert host.metrics()["handoffs"] == 1
        assert host.metrics()["duplicate_drops"] == 1
        assert host.metrics()["delivered"] == 1
        assert director.metrics()["queued"] == 1
    asyncio.run(run())


def test_websocket_library_style_close_uses_retry_boundary():
    async def run():
        stop = asyncio.Event()
        first = FakeSocket(envelope("session_welcome"), RuntimeError("ConnectionClosedError"))
        next_socket = FakeSocket(envelope("session_welcome", session="freshSession1234"),
                                 envelope("notification", session="freshSession1234"))
        host, _, _ = make_host([first, next_socket], stop)
        await asyncio.wait_for(host.run(owner_approved=True, stop=stop), timeout=3)
        assert host.metrics()["restarts"] == 1
        assert host.metrics()["delivered"] == 1
    asyncio.run(run())


def test_disabled_director_never_reads_chat():
    async def run():
        stop = asyncio.Event()
        host, director, urls = make_host([], stop)
        director.disable()
        with pytest.raises(PermissionError, match="StreamDirector"):
            await host.run(owner_approved=True, stop=stop)
        assert not urls
    asyncio.run(run())


def test_invalid_session_is_not_forwarded_to_mod_untrusted_scope():
    async def run():
        stop = asyncio.Event()
        calls = []
        async def mod(text):
            calls.append(text)
            stop.set()
            return text
        socket = FakeSocket(envelope("session_welcome"),
                            envelope("notification", session="wrongSession1234"))
        host, director, _ = make_host([socket], stop, moderate=mod)
        async def end_after_rejection():
            await asyncio.sleep(0.05)
            stop.set()
        stopper = asyncio.create_task(end_after_rejection())
        await asyncio.wait_for(host.run(owner_approved=True, stop=stop), timeout=2)
        await stopper
        assert not calls
        assert director.metrics()["queued"] == 0
        assert host.metrics()["rejected"] == 1
    asyncio.run(run())



def test_parallel_moderation_keeps_chat_usable_while_first_question_waits():
    async def run():
        stop = asyncio.Event()
        second_started = asyncio.Event()
        async def moderate(text):
            if text == "slow question?":
                # This would timeout if the WebSocket reader awaited the first
                # moderator before receiving the next notification.
                await asyncio.wait_for(second_started.wait(), timeout=0.35)
                return text
            second_started.set()
            stop.set()
            return text
        slow = envelope("notification", text="slow question?", mid="chat-slow-12345")
        packet = json.loads(envelope("notification", text="second question?", mid="chat-fast-12345"))
        packet["payload"]["event"]["chatter_user_id"] = "1234567"
        fast = json.dumps(packet)
        socket = FakeSocket(envelope("session_welcome"), slow,
                            envelope("session_keepalive"), fast)
        host, director, _ = make_host([socket], stop, moderate=moderate)
        host.moderator_timeout_s = 0.5
        await asyncio.wait_for(host.run(owner_approved=True, stop=stop), timeout=2)
        assert second_started.is_set()
        assert host.metrics()["delivered"] == 2
        assert host.metrics()["moderation_faults"] == 0
        assert host.metrics()["moderations_inflight"] == 0
        assert director.metrics()["queued"] == 2
    asyncio.run(run())


def test_chat_backpressure_is_bounded_and_never_queues_all_messages():
    async def run():
        stop = asyncio.Event()
        entered = 0
        async def moderate(_text):
            nonlocal entered
            entered += 1
            await asyncio.sleep(60)
            return "late"
        notifications = [
            envelope("notification", mid=f"message-{i:08d}", text=f"question {i}?")
            for i in range(20)
        ]
        socket = FakeSocket(envelope("session_welcome"), *notifications)
        host, director, _ = make_host([socket], stop, moderate=moderate)
        host.max_pending_moderations = 2
        host.moderator_timeout_s = 0.12
        async def stop_soon():
            await asyncio.sleep(0.04)
            stop.set()
        stopper = asyncio.create_task(stop_soon())
        await asyncio.wait_for(host.run(owner_approved=True, stop=stop), timeout=2)
        await stopper
        assert entered <= 2
        assert host.metrics()["backpressure_drops"] >= 18
        assert host.metrics()["moderations_inflight"] == 0
        assert director.metrics()["queued"] == 0
    asyncio.run(run())


def test_revocation_cancels_waiting_moderation_without_delivering_chat():
    async def run():
        stop = asyncio.Event()
        cancelled = asyncio.Event()
        async def moderate(_text):
            try:
                await asyncio.sleep(60)
                return "never"
            except asyncio.CancelledError:
                cancelled.set()
                raise
        socket = FakeSocket(envelope("session_welcome"),
                            envelope("notification", mid="chat-pending-revoked"),
                            envelope("revocation"))
        host, director, _ = make_host([socket], stop, moderate=moderate)
        with pytest.raises(TwitchAuthorizationError, match="revoked"):
            await asyncio.wait_for(host.run(owner_approved=True, stop=stop), timeout=2)
        assert host.metrics()["delivered"] == 0
        assert host.metrics()["moderations_inflight"] == 0
        assert host.metrics()["moderations_cancelled"] >= 1
        assert director.metrics()["queued"] == 0
    asyncio.run(run())


def test_reconnect_cancels_old_pending_chat_but_delivers_new_session_chat():
    async def run():
        stop = asyncio.Event()
        async def moderate(text):
            if text == "old question?":
                await asyncio.sleep(60)
            else:
                stop.set()
            return text
        old = FakeSocket(
            envelope("session_welcome", session="oldSession1234"),
            envelope("notification", session="oldSession1234",
                     text="old question?", mid="chat-old-waiting"),
            envelope("session_reconnect",
                     reconnect="wss://eventsub.wss.twitch.tv/ws?reconnect=abc"))
        new = FakeSocket(
            envelope("session_welcome", session="newSession1234"),
            envelope("notification", session="newSession1234",
                     text="new question?", mid="chat-new-success"))
        host, director, _ = make_host([old, new], stop, moderate=moderate)
        await asyncio.wait_for(host.run(owner_approved=True, stop=stop), timeout=2)
        assert host.metrics()["delivered"] == 1
        assert host.metrics()["handoffs"] == 1
        assert host.metrics()["moderations_inflight"] == 0
        assert director._events[0].detail == "new question?"
        assert old.closed and new.closed
    asyncio.run(run())


def test_unexpected_chat_task_fault_does_not_kill_eventsub_session():
    async def run():
        stop = asyncio.Event()
        first = envelope("notification", mid="chat-malformed-fault", text="first?")
        second = envelope("notification", mid="chat-follows-fault", text="second?")
        socket = FakeSocket(envelope("session_welcome"), first, second)
        host, director, _ = make_host([socket], stop)
        original = host._message
        async def injected_failure(raw, bridge, session):
            if "chat-malformed-fault" in raw:
                raise RuntimeError("untrusted private content should never be logged")
            return await original(raw, bridge, session)
        host._message = injected_failure
        await asyncio.wait_for(host.run(owner_approved=True, stop=stop), timeout=2)
        assert host.metrics()["moderation_faults"] == 1
        assert host.metrics()["delivered"] == 1
        assert host.metrics()["moderations_inflight"] == 0
        assert director.metrics()["queued"] == 1
    asyncio.run(run())


def test_pending_cap_validation_rejects_zero_and_bool():
    async def dummy(_):
        return ""
    for value in (0, 33, True, 4.5):
        with pytest.raises(ValueError, match="max_pending"):
            TwitchRealtimeHost(
                config=TwitchChatConfig("client12345", "12345", "99999"),
                director=StreamDirector(), token_provider=lambda: "1234567890",
                moderator=dummy, max_pending_moderations=value)


def test_duplicate_chat_flood_is_deduplicated_before_expensive_moderation():
    async def run():
        stop = asyncio.Event()
        calls = 0

        async def moderate(text):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.02)
            stop.set()
            return text

        event = envelope("notification", mid="identical-message-12345")
        socket = FakeSocket(envelope("session_welcome"), *([event] * 24))
        host, director, _ = make_host([socket], stop, moderate=moderate)
        host.max_pending_moderations = 2
        await asyncio.wait_for(host.run(owner_approved=True, stop=stop), timeout=2)
        metrics = host.metrics()
        assert calls == 1
        assert metrics["duplicate_drops"] == 23
        assert metrics["backpressure_drops"] == 0
        assert metrics["delivered"] == 1
        assert metrics["moderations_inflight"] == 0
        assert director.metrics()["queued"] == 1
    asyncio.run(run())


def test_stale_eventsub_notification_is_rejected_before_moderation():
    async def run():
        stop = asyncio.Event()
        calls = []

        async def moderate(text):
            calls.append(text)
            stop.set()
            return text

        stale = json.loads(envelope("notification", mid="old-event-msg-12345"))
        stale["metadata"]["message_timestamp"] = datetime.fromtimestamp(
            time.time() - 300, timezone.utc
        ).isoformat()
        socket = FakeSocket(
            envelope("session_welcome"), json.dumps(stale),
            envelope("notification", mid="fresh-event-msg-12345"),
        )
        host, director, _ = make_host([socket], stop, moderate=moderate)
        await asyncio.wait_for(host.run(owner_approved=True, stop=stop), timeout=2)
        assert calls == ["Hello Star?"]
        assert host.metrics()["premoderation_rejected"] == 1
        assert host.metrics()["delivered"] == 1
        assert director.metrics()["queued"] == 1
    asyncio.run(run())


def test_duplicate_flood_does_not_occupy_capacity_for_new_viewer():
    async def run():
        stop = asyncio.Event()
        moderator_started = []

        async def moderate(text):
            moderator_started.append(text)
            await asyncio.sleep(0.03)
            if len(moderator_started) == 2:
                stop.set()
            return text

        duplicate = envelope("notification", mid="chat-same-episode-123")
        different = json.loads(envelope(
            "notification", mid="chat-new-viewer-1234", text="Second viewer?"
        ))
        different["payload"]["event"]["chatter_user_id"] = "567890"
        socket = FakeSocket(
            envelope("session_welcome"), *([duplicate] * 12),
            json.dumps(different),
        )
        host, director, _ = make_host([socket], stop, moderate=moderate)
        host.max_pending_moderations = 2
        await asyncio.wait_for(host.run(owner_approved=True, stop=stop), timeout=2)
        assert sorted(moderator_started) == ["Hello Star?", "Second viewer?"]
        assert host.metrics()["duplicate_drops"] == 11
        assert host.metrics()["delivered"] == 2
        assert host.metrics()["backpressure_drops"] == 0
        assert director.metrics()["queued"] == 2
    asyncio.run(run())


def test_rejected_moderation_releases_id_for_legitimate_twitch_retry():
    async def run():
        stop = asyncio.Event()
        calls = 0
        same = envelope("notification", mid="retry-chat-after-reject")
        socket = FakeSocket(envelope("session_welcome"), same)

        async def moderate(text):
            nonlocal calls
            calls += 1
            if calls == 1:
                async def retry():
                    await asyncio.sleep(0.05)
                    socket.events.put_nowait(same)
                asyncio.create_task(retry())
                return None
            stop.set()
            return text

        host, director, _ = make_host([socket], stop, moderate=moderate)
        await asyncio.wait_for(host.run(owner_approved=True, stop=stop), timeout=2)
        assert calls == 2
        assert host.metrics()["delivered"] == 1
        assert host.metrics()["duplicate_drops"] == 0
        assert director.metrics()["queued"] == 1
    asyncio.run(run())
