"""Opt-in Twitch EventSub WebSocket host for Star's gaming VTuber.

Unlike the pure JSON adapter, this host manages an authenticated, read-only chat
connection, subscription, heartbeat, reconnect handoff, and revocation. It offers
moderated StreamSignals to an existing StreamDirector. It NEVER speaks, starts
OBS, executes a viewer instruction, owns an OAuth login, or controls a game.

Network access is strictly opt-in via run(owner_approved=True). OAuth credentials
must be supplied by the embedding trusted host's secret store. Production
connections require the optional websockets package. No credentials, chat text,
or viewer identifiers are written to disk or telemetry.
"""
from __future__ import annotations

from typing import cast

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
import hmac
import json
import secrets
import time
from typing import Awaitable, Callable, Protocol
from urllib import parse, request

from .stream_director import StreamDirector
from .twitch_eventsub_bridge import (
    TwitchEventSubBridge, _timestamp, _MAX_AGE_SECONDS, _FUTURE_TOLERANCE_SECONDS,
)


class TwitchAuthorizationError(RuntimeError):
    """Token/scopes/subscription are not authorized; do not retry blindly."""


class TwitchProtocolError(RuntimeError):
    """Bad framing or an untrusted server-directed state change."""


class Socket(Protocol):
    async def recv(self) -> str: ...
    async def close(self) -> None: ...


Moderator = Callable[[str], Awaitable[str | None]]
Connector = Callable[[str], Awaitable[Socket]]
TokenProvider = Callable[[], str]
TokenValidator = Callable[[str], Awaitable[dict]]
Subscriber = Callable[[str, str], Awaitable[None]]
_URL = "wss://eventsub.wss.twitch.tv/ws"
_API = "https://api.twitch.tv/helix/eventsub/subscriptions"
_VALIDATE = "https://id.twitch.tv/oauth2/validate"
_MAX_FRAME = 16_384


async def _connect(url: str) -> Socket:
    try:
        from websockets.asyncio.client import connect
    except ImportError as exc:
        raise RuntimeError("Install optional package 'websockets>=14' to use live Twitch") from exc
    try:
        return await connect(url, open_timeout=7, close_timeout=2, max_size=_MAX_FRAME,
                             ping_interval=20, ping_timeout=15)
    except Exception:
        raise ConnectionError("Twitch WebSocket connection failed") from None


def _url(value: str) -> str:
    """Reconnect URL is supplied by Twitch, not chat; nevertheless pin the host."""
    if type(value) is not str or len(value) > 2048:
        raise TwitchProtocolError("invalid reconnect URL")
    try:
        parsed = parse.urlsplit(value)
        trusted = (parsed.scheme == "wss" and parsed.hostname == "eventsub.wss.twitch.tv"
                   and parsed.port in (None, 443) and not parsed.username
                   and not parsed.password and parsed.path == "/ws" and not parsed.fragment)
    except ValueError:
        raise TwitchProtocolError("untrusted reconnect URL") from None
    if not trusted:
        raise TwitchProtocolError("untrusted reconnect URL")
    return value


def _packet(raw: str) -> dict:
    if type(raw) is not str or len(raw) > _MAX_FRAME:
        raise TwitchProtocolError("invalid or oversized WebSocket frame")

    def pairs(items: list[tuple[str, object]]) -> dict:
        out: dict = {}
        for key, val in items:
            if key in out:
                raise TwitchProtocolError("duplicate JSON key")
            out[key] = val
        return out

    try:
        data = json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, TypeError, RecursionError) as exc:
        raise TwitchProtocolError("invalid EventSub JSON") from exc
    if type(data) is not dict or type(data.get("metadata")) is not dict or type(data.get("payload")) is not dict:
        raise TwitchProtocolError("invalid EventSub envelope")
    return data


def _bounded_id(value: object) -> bool:
    return (type(value) is str and 8 <= len(value) <= 128
            and all(char.isascii() and (char.isalnum() or char in "_-") for char in value))


async def _http_json(url: str, headers: dict[str, str], data: bytes | None = None) -> tuple[int, dict]:
    """Blocking urllib lives in a worker; never return request headers in errors."""
    def call() -> tuple[int, dict]:
        req = request.Request(url, headers=headers, data=data, method="POST" if data is not None else "GET")
        try:
            with request.urlopen(req, timeout=5) as resp:
                body = resp.read(32_769)
                if len(body) > 32_768:
                    raise TwitchProtocolError("Twitch response too large")
                result = json.loads(body)
                if type(result) is not dict:
                    raise TwitchProtocolError("invalid Twitch response")
                return resp.status, result
        except Exception:
            # Never include response bodies, URLs with query parameters, tokens or headers.
            raise TwitchAuthorizationError("Twitch authorization or API request failed") from None
    return await asyncio.to_thread(call)


@dataclass(frozen=True)
class TwitchChatConfig:
    client_id: str
    broadcaster_user_id: str
    chat_user_id: str

    def __post_init__(self) -> None:
        if (not isinstance(self.client_id, str) or not 8 <= len(self.client_id) <= 128
                or not self.client_id.isascii() or not self.client_id.isalnum()):
            raise ValueError("client_id must be a bounded Twitch client ID")
        for name in ("broadcaster_user_id", "chat_user_id"):
            value = getattr(self, name)
            if type(value) is not str or not 1 <= len(value) <= 32 or not value.isascii() or not value.isdigit():
                raise ValueError(f"{name} must be a numeric user ID")


@dataclass
class TwitchRealtimeHost:
    """The host must separately enable StreamDirector and audio/broadcast access.

    Inject network callbacks for offline tests. The normal code path opens a
    real WSS connection and uses Twitch's official REST endpoints. Moderator is
    REQUIRED and must be an independent trusted async host callback.
    The callback never receives permissions to operate tools or devices.
    """
    config: TwitchChatConfig
    director: StreamDirector
    token_provider: TokenProvider = field(repr=False)
    moderator: Moderator = field(repr=False)
    connect: Connector = field(default=_connect, repr=False)
    validate_token: TokenValidator | None = field(default=None, repr=False)
    subscribe_chat: Subscriber | None = field(default=None, repr=False)
    moderator_timeout_s: float = 0.75
    max_pending_moderations: int = 8
    _counters: dict[str, int] = field(default_factory=lambda: {
        "subscriptions": 0, "sessions": 0, "handoffs": 0, "restarts": 0,
        "delivered": 0, "rejected": 0, "revocations": 0,
        "backpressure_drops": 0, "moderations_cancelled": 0,
        "moderation_faults": 0, "premoderation_rejected": 0,
        "duplicate_drops": 0}, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.config, TwitchChatConfig) or not isinstance(self.director, StreamDirector):
            raise TypeError("config and director must be trusted instances")
        if not all(callable(item) for item in (self.token_provider, self.moderator, self.connect)):
            raise TypeError("missing token/moderation/connect callbacks")
        if not 0.1 <= self.moderator_timeout_s <= 3.0:
            raise ValueError("moderator_timeout_s must be 0.1..3 seconds")
        if type(self.max_pending_moderations) is not int or not 1 <= self.max_pending_moderations <= 32:
            raise ValueError("max_pending_moderations must be 1..32")
        self._running = False
        self._salt = secrets.token_bytes(32)
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._pending: set[asyncio.Task[None]] = set()
        self._pending_keys: set[str] = set()

    async def _token(self) -> str:
        token = self.token_provider()
        if type(token) is not str or not 10 <= len(token) <= 8192 or any(c.isspace() for c in token):
            raise TwitchAuthorizationError("missing or invalid Twitch user access token")
        check = self.validate_token or self._validate
        payload = await check(token)
        if (type(payload) is not dict or payload.get("client_id") != self.config.client_id
                or payload.get("user_id") != self.config.chat_user_id
                or type(payload.get("scopes")) is not list
                or "user:read:chat" not in payload["scopes"]
                or type(payload.get("expires_in")) is not int
                or payload["expires_in"] < 120):
            raise TwitchAuthorizationError("Twitch token identity, scope or expiry is invalid")
        return token

    async def _validate(self, token: str) -> dict:
        status, body = await _http_json(_VALIDATE, {"Authorization": f"OAuth {token}"})
        if status != 200:
            raise TwitchAuthorizationError("Twitch token validation failed")
        return body

    async def _subscribe(self, session: str, token: str) -> None:
        if self.subscribe_chat is not None:
            await self.subscribe_chat(session, token)
            return
        body = {
            "type": "channel.chat.message", "version": "1",
            "condition": {
                "broadcaster_user_id": self.config.broadcaster_user_id,
                "user_id": self.config.chat_user_id,
            },
            "transport": {"method": "websocket", "session_id": session},
        }
        status, result = await _http_json(
            _API,
            {"Authorization": f"Bearer {token}", "Client-Id": self.config.client_id,
             "Content-Type": "application/json"},
            json.dumps(body, separators=(",", ":")).encode("utf-8"))
        data = result.get("data")
        if (status not in (200, 202) or type(data) is not list or len(data) != 1
                or type(data[0]) is not dict or data[0].get("status") != "enabled"
                or data[0].get("type") != "channel.chat.message"
                or data[0].get("version") != "1"
                or type(data[0].get("transport")) is not dict
                or data[0]["transport"].get("session_id") != session):
            raise TwitchAuthorizationError("Twitch did not confirm an enabled chat subscription")

    async def _welcome(self, socket: Socket) -> tuple[str, float]:
        try:
            raw = await asyncio.wait_for(socket.recv(), timeout=10)
        except asyncio.TimeoutError:
            raise TimeoutError("Twitch welcome timed out") from None
        except Exception:
            raise ConnectionError("Twitch welcome connection closed") from None
        packet = _packet(raw)
        payload = packet["payload"]
        meta = packet["metadata"]
        session = payload.get("session")
        if (meta.get("message_type") != "session_welcome" or type(session) is not dict
                or session.get("status") != "connected"
                or not _bounded_id(session.get("id"))
                or type(session.get("keepalive_timeout_seconds")) is not int
                or not 5 <= session["keepalive_timeout_seconds"] <= 120):
            raise TwitchProtocolError("invalid Twitch session welcome")
        return session["id"], float(session["keepalive_timeout_seconds"])

    def _prune_seen(self, now: float) -> None:
        while self._seen and (
            now - next(iter(self._seen.values())) > 90 or len(self._seen) >= 1024
        ):
            self._seen.popitem(last=False)

    def _admission_key(self, packet: dict, session_id: str, now_unix: float) -> str | None:
        """Cheap strict gate *before* allocating scarce moderation capacity.

        Twitch delivers at least once. A duplicate notification must not run
        the (potentially expensive) independent moderation callback again.
        This verifies identifiers, session, channel and age; _message and
        TwitchEventSubBridge still perform full post-moderation validation.
        No chat text, source account IDs or raw identifiers are retained.
        """
        meta = packet["metadata"]
        payload = packet["payload"]
        sub = payload.get("subscription")
        event = payload.get("event")
        condition = sub.get("condition") if type(sub) is dict else None
        transport = sub.get("transport") if type(sub) is dict else None
        msg = event.get("message") if type(event) is dict else None
        if (
            meta.get("message_type") != "notification"
            or meta.get("subscription_type") != "channel.chat.message"
            or meta.get("subscription_version") != "1"
            or type(sub) is not dict or sub.get("type") != "channel.chat.message"
            or sub.get("version") != "1" or sub.get("status") != "enabled"
            or type(condition) is not dict
            or condition.get("broadcaster_user_id") != self.config.broadcaster_user_id
            or condition.get("user_id") != self.config.chat_user_id
            or type(transport) is not dict or transport.get("method") != "websocket"
            or transport.get("session_id") != session_id
            or type(event) is not dict
            or event.get("broadcaster_user_id") != self.config.broadcaster_user_id
            or type(msg) is not dict or type(msg.get("text")) is not str
            or not 1 <= len(msg["text"].strip()) <= 1000
            or not _bounded_id(meta.get("message_id"))
        ):
            return None
        chat_id = event.get("message_id")
        viewer = event.get("chatter_user_id")
        if (
            type(chat_id) is not str or not _bounded_id(chat_id)
            or "_" in chat_id  # Match the downstream bridge's ID grammar.
            or type(viewer) is not str or not 1 <= len(viewer) <= 32
            or not viewer.isascii() or not viewer.isdigit()
        ):
            return None
        # The grammar validator is a runtime bool, not a typing TypeGuard.
        chat_id = cast(str, chat_id)
        sent = _timestamp(meta.get("message_timestamp"))
        if sent is None or not -_FUTURE_TOLERANCE_SECONDS <= now_unix - sent <= _MAX_AGE_SECONDS:
            return None
        return hmac.new(self._salt, chat_id.encode("ascii"), hashlib.sha256).hexdigest()[:32]

    def _remember_id(self, raw: str, now: float) -> bool:
        """Host-level dedupe persists across Twitch reconnect handoffs."""
        packet = _packet(raw)
        event = packet["payload"].get("event")
        msg_id = event.get("message_id") if type(event) is dict else None
        if not _bounded_id(msg_id):
            return False
        digest = hmac.new(self._salt, cast(str, msg_id).encode("ascii"), hashlib.sha256).hexdigest()[:32]
        self._prune_seen(now)
        if digest in self._seen:
            return False
        self._seen[digest] = now
        return True

    async def _message(self, raw: str, bridge: TwitchEventSubBridge, session_id: str) -> None:
        """Validate channel/scope first, moderate, then offer untrusted DATA."""
        packet = _packet(raw)
        meta = packet["metadata"]
        payload = packet["payload"]
        sub = payload.get("subscription")
        event = payload.get("event")
        condition = sub.get("condition") if type(sub) is dict else None
        transport = sub.get("transport") if type(sub) is dict else None
        if (meta.get("message_type") != "notification"
                or meta.get("subscription_type") != "channel.chat.message"
                or meta.get("subscription_version") != "1"
                or type(sub) is not dict or sub.get("type") != "channel.chat.message"
                or sub.get("version") != "1" or sub.get("status") != "enabled"
                or type(condition) is not dict
                or condition.get("broadcaster_user_id") != self.config.broadcaster_user_id
                or condition.get("user_id") != self.config.chat_user_id
                or type(transport) is not dict or transport.get("method") != "websocket"
                or transport.get("session_id") != session_id
                or type(event) is not dict
                or event.get("broadcaster_user_id") != self.config.broadcaster_user_id):
            self._counters["rejected"] += 1
            return
        msg = event.get("message")
        original = msg.get("text") if type(msg) is dict else None
        if type(original) is not str or not 1 <= len(original.strip()) <= 1000:
            self._counters["rejected"] += 1
            return
        # Do not allow the LLM to substitute for independently trusted moderation.
        try:
            moderated = await asyncio.wait_for(self.moderator(original), self.moderator_timeout_s)
        except (Exception, asyncio.TimeoutError):
            self._counters["rejected"] += 1
            return
        if type(moderated) is not str or not 1 <= len(moderated.strip()) <= 500:
            self._counters["rejected"] += 1
            return
        now_mono, now_unix = time.monotonic(), time.time()
        if not self._remember_id(raw, now_mono):
            self._counters["rejected"] += 1
            return
        signal = bridge.ingest(raw, now_unix_s=now_unix, now_monotonic_s=now_mono,
                               moderated_text=moderated, moderation_approved=True)
        if signal is not None and self.director.offer(signal, now=now_mono):
            self._counters["delivered"] += 1
        else:
            self._counters["rejected"] += 1

    async def _moderate_task(
        self, raw: str, bridge: TwitchEventSubBridge, session_id: str,
    ) -> None:
        """Isolate errors so one malformed chat never kills EventSub's heartbeat."""
        try:
            await self._message(raw, bridge, session_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Never log chat text, OAuth material, user IDs or exception bodies.
            self._counters["moderation_faults"] += 1
            self._counters["rejected"] += 1

    def _submit_message(
        self, raw: str, bridge: TwitchEventSubBridge, session_id: str,
        packet: dict,
    ) -> None:
        """Bounded nonblocking ingress; dedupe before expensive moderation.

        A message ID is only reserved while its moderator task is live. A
        rejected/failed moderation releases it for a legitimate EventSub retry.
        Successfully delivered IDs remain protected by the 90-second cache.
        """
        key = self._admission_key(packet, session_id, time.time())
        if key is None:
            self._counters["premoderation_rejected"] += 1
            self._counters["rejected"] += 1
            return
        self._prune_seen(time.monotonic())
        if key in self._seen or key in self._pending_keys:
            self._counters["duplicate_drops"] += 1
            self._counters["rejected"] += 1
            return
        if len(self._pending) >= self.max_pending_moderations:
            self._counters["backpressure_drops"] += 1
            self._counters["rejected"] += 1
            return
        self._pending_keys.add(key)
        task = asyncio.create_task(self._moderate_task(raw, bridge, session_id))
        self._pending.add(task)

        def release(done: asyncio.Task[None]) -> None:
            self._pending.discard(done)
            self._pending_keys.discard(key)
        task.add_done_callback(release)

    async def _settle_moderations(self, *, graceful: bool) -> None:
        """Drain on owner stop; cancel on reconnect, revocation, or failure.

        A Twitch session change invalidates pending moderation: even an
        eventual approval must not re-enter the old session. A graceful owner
        stop gives already accepted frames one bounded chance to finish.
        """
        tasks = set(self._pending)
        if not tasks:
            return
        leftovers = tasks
        if graceful:
            _, leftovers = await asyncio.wait(
                tasks, timeout=self.moderator_timeout_s + 0.1
            )
        for task in leftovers:
            if not task.done():
                task.cancel()
                self._counters["moderations_cancelled"] += 1
        if leftovers:
            await asyncio.gather(*leftovers, return_exceptions=True)
        # Explicit cleanup even if add_done_callback hasn't fired yet.
        self._pending.difference_update(tasks)
        self._pending_keys.clear()

    async def _receive(self, ws: Socket, stop: asyncio.Event, timeout: float) -> str | None:
        receiver = asyncio.create_task(ws.recv())
        stopper = asyncio.create_task(stop.wait())
        try:
            done, _ = await asyncio.wait({receiver, stopper}, timeout=timeout,
                                         return_when=asyncio.FIRST_COMPLETED)
            if stopper in done:
                return None
            if receiver not in done:
                raise TimeoutError("EventSub keepalive overdue")
            try:
                return receiver.result()
            except Exception:
                # WebSocket libraries use connection-closed exception classes
                # unrelated to OSError. Normalize without exposing internals.
                raise ConnectionError("Twitch WebSocket closed") from None
        finally:
            for task in (receiver, stopper):
                if not task.done():
                    task.cancel()
            await asyncio.gather(receiver, stopper, return_exceptions=True)

    async def run(self, *, owner_approved: bool = False, stop: asyncio.Event,
                  max_failures: int = 5) -> None:
        """Run until stop or repeated transport failures. Never start implicitly.

        Fresh disconnects must resubscribe. Twitch reconnect handoffs preserve
        subscriptions; old sockets close only after the new welcome. Secrets
        remain in memory, and all transcripts are discarded after moderation.
        """
        if owner_approved is not True:
            raise PermissionError("owner approval required for live Twitch reads")
        if not isinstance(stop, asyncio.Event) or type(max_failures) is not int or not 1 <= max_failures <= 20:
            raise ValueError("stop must be asyncio.Event and max_failures 1..20")
        if self._running:
            raise RuntimeError("Twitch host already running")
        if not self.director.enabled:
            raise PermissionError("StreamDirector must be separately owner-enabled")
        self._running = True
        self._salt = secrets.token_bytes(32)
        self._seen.clear()
        failures = 0
        try:
            token = await self._token()
            while not stop.is_set():
                ws: Socket | None = None
                bridge: TwitchEventSubBridge | None = None
                revoked = False
                try:
                    ws = await self.connect(_URL)
                    session, heartbeat = await self._welcome(ws)
                    await self._subscribe(session, token)
                    self._counters["subscriptions"] += 1
                    self._counters["sessions"] += 1
                    bridge = TwitchEventSubBridge(
                        broadcaster_user_id=self.config.broadcaster_user_id,
                        session_id=session, session_salt=self._salt)
                    bridge.enable(owner_approved=True)
                    failures = 0
                    while not stop.is_set():
                        raw = await self._receive(ws, stop, heartbeat + 3)
                        if raw is None:
                            break
                        packet = _packet(raw)
                        kind = packet["metadata"].get("message_type")
                        if kind == "session_reconnect":
                            sess = packet["payload"].get("session")
                            if type(sess) is not dict:
                                raise TwitchProtocolError("missing reconnect session")
                            handoff_value = sess.get("reconnect_url")
                            if type(handoff_value) is not str:
                                raise TwitchProtocolError("invalid reconnect URL")
                            handoff_url = _url(handoff_value)
                            new_ws = await self.connect(handoff_url)
                            try:
                                new_session, new_heartbeat = await self._welcome(new_ws)
                            except BaseException:
                                await new_ws.close()
                                raise
                            # Do not create another subscription on handoff.
                            old = ws
                            ws = new_ws
                            bridge.disable()
                            await self._settle_moderations(graceful=False)
                            bridge = TwitchEventSubBridge(
                                broadcaster_user_id=self.config.broadcaster_user_id,
                                session_id=new_session, session_salt=self._salt)
                            bridge.enable(owner_approved=True)
                            heartbeat = new_heartbeat
                            session = new_session
                            self._counters["handoffs"] += 1
                            await old.close()
                        elif kind == "revocation":
                            revoked = True
                            self._counters["revocations"] += 1
                            raise TwitchAuthorizationError("EventSub permission revoked")
                        elif kind == "notification":
                            self._submit_message(raw, bridge, session, packet)
                        elif kind in ("session_keepalive", "session_welcome"):
                            pass
                        else:
                            self._counters["rejected"] += 1
                except TwitchAuthorizationError:
                    raise
                except (TimeoutError, OSError, ConnectionError, TwitchProtocolError,
                        asyncio.TimeoutError):
                    # Drop old-session chat before any reconnect backoff.
                    if bridge is not None:
                        bridge.disable()
                    await self._settle_moderations(graceful=False)
                    failures += 1
                    self._counters["restarts"] += 1
                    if failures >= max_failures:
                        raise RuntimeError("Twitch connection failed repeatedly") from None
                    # Failures never cause a rapid connection storm.
                    if not stop.is_set():
                        try:
                            await asyncio.wait_for(stop.wait(), timeout=min(16.0, 2.0 ** (failures - 1)))
                        except asyncio.TimeoutError:
                            pass
                finally:
                    await self._settle_moderations(
                        graceful=(stop.is_set() and not revoked)
                    )
                    if bridge is not None:
                        bridge.disable()
                    if ws is not None:
                        try:
                            await ws.close()
                        except Exception:
                            # Failure to close an already-disconnected socket must
                            # not replace a more useful revocation/stop outcome.
                            pass
        finally:
            self._seen.clear()
            self._running = False

    def metrics(self) -> dict[str, int]:
        """No raw viewer IDs, chat text, tokens or endpoints are exposed."""
        return {**self._counters, "moderations_inflight": len(self._pending)}


__all__ = ["TwitchRealtimeHost", "TwitchChatConfig", "TwitchAuthorizationError",
           "TwitchProtocolError"]
