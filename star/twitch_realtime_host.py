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
from .twitch_eventsub_bridge import TwitchEventSubBridge


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
    _counters: dict[str, int] = field(default_factory=lambda: {
        "subscriptions": 0, "sessions": 0, "handoffs": 0, "restarts": 0,
        "delivered": 0, "rejected": 0, "revocations": 0}, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.config, TwitchChatConfig) or not isinstance(self.director, StreamDirector):
            raise TypeError("config and director must be trusted instances")
        if not all(callable(item) for item in (self.token_provider, self.moderator, self.connect)):
            raise TypeError("missing token/moderation/connect callbacks")
        if not 0.1 <= self.moderator_timeout_s <= 3.0:
            raise ValueError("moderator_timeout_s must be 0.1..3 seconds")
        self._running = False
        self._salt = secrets.token_bytes(32)
        self._seen: OrderedDict[str, float] = OrderedDict()

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

    def _remember_id(self, raw: str, now: float) -> bool:
        """Host-level dedupe persists across Twitch reconnect handoffs."""
        packet = _packet(raw)
        event = packet["payload"].get("event")
        msg_id = event.get("message_id") if type(event) is dict else None
        if not _bounded_id(msg_id):
            return False
        digest = hmac.new(self._salt, msg_id.encode("ascii"), hashlib.sha256).hexdigest()[:32]
        while self._seen and (now - next(iter(self._seen.values())) > 90 or len(self._seen) >= 1024):
            self._seen.popitem(last=False)
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
                            handoff_url = _url(sess.get("reconnect_url"))
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
                            bridge = TwitchEventSubBridge(
                                broadcaster_user_id=self.config.broadcaster_user_id,
                                session_id=new_session, session_salt=self._salt)
                            bridge.enable(owner_approved=True)
                            heartbeat = new_heartbeat
                            session = new_session
                            self._counters["handoffs"] += 1
                            await old.close()
                        elif kind == "revocation":
                            self._counters["revocations"] += 1
                            raise TwitchAuthorizationError("EventSub permission revoked")
                        elif kind == "notification":
                            await self._message(raw, bridge, session)
                        elif kind in ("session_keepalive", "session_welcome"):
                            pass
                        else:
                            self._counters["rejected"] += 1
                except TwitchAuthorizationError:
                    raise
                except (TimeoutError, OSError, ConnectionError, TwitchProtocolError,
                        asyncio.TimeoutError):
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
        return dict(self._counters)


__all__ = ["TwitchRealtimeHost", "TwitchChatConfig", "TwitchAuthorizationError",
           "TwitchProtocolError"]
