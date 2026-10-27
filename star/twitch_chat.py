"""Read-only installed Twitch chat: owner token, EventSub and an ephemeral queue.

Only the broadcaster's own channel is supported. Receiving a message is never
moderation approval. No chat-send, account-creation or stream-key APIs exist.
Secrets stay in native OS storage and host memory, outside model context.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict, deque
from dataclasses import dataclass
from datetime import datetime
from getpass import getpass
from hashlib import sha256
import json
import logging
import math
import re
import ssl
import sys
import threading
import time
from urllib.parse import urlsplit

import httpx

from .bulk_profiles import OSProfileSecrets

VALIDATE = "https://id.twitch.tv/oauth2/validate"
SUBSCRIPTIONS = "https://api.twitch.tv/helix/eventsub/subscriptions"
EVENTSUB = "wss://eventsub.wss.twitch.tv/ws"
TYPES = ("channel.chat.message", "channel.chat.message_delete", "channel.chat.clear_user_messages", "channel.chat.clear")
_ID = re.compile(r"[A-Za-z0-9_-]{1,256}\Z")
_USER = re.compile(r"[0-9]{1,32}\Z")
_ERRORS = frozenset({"invalid_token", "authorization_failed", "token_identity_or_scope_mismatch", "secure_vault_unavailable",
    "no_saved_token", "subscription_revoked", "token_expired", "twitch_request_failed", "invalid_twitch_response",
    "twitch_unavailable", "invalid_event", "invalid_welcome", "welcome_timeout", "stopped", "invalid_subscription",
    "invalid_subscription_event", "unexpected_event", "invalid_reconnect", "socket_closed", "keepalive_timeout"})


class TwitchChatError(RuntimeError):
    """Static diagnostic codes only; never preserve HTTP bodies, tokens or chat."""


class AuthorizationError(TwitchChatError):
    pass


def _identity(client_id: str, broadcaster_id: str):
    if (type(client_id) is not str or not re.fullmatch(r"[A-Za-z0-9]{1,128}", client_id)
            or type(broadcaster_id) is not str or not _USER.fullmatch(broadcaster_id)):
        raise ValueError("Configure a Twitch client ID and numeric broadcaster user ID")


def _token(value):
    if type(value) is not str:
        raise AuthorizationError("invalid_token")
    value = value.removeprefix("oauth:")
    if not re.fullmatch(r"[A-Za-z0-9_-]{20,256}", value):
        raise AuthorizationError("invalid_token")
    return value


def _clean(value, limit):
    if type(value) is not str or len(value) > limit:
        raise ValueError("Invalid bounded chat text")
    value = "".join(c for c in value if (ord(c) >= 32 and ord(c) != 127 and c not in "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069") or c in "\n\t")
    return " ".join(value.split())


@dataclass(frozen=True)
class ChatMessage:
    message_id: str
    broadcaster_id: str
    user_id: str
    display_name: str
    text: str
    received_at: float

    def __post_init__(self):
        if (type(self.message_id) is not str or not _ID.fullmatch(self.message_id)
                or type(self.broadcaster_id) is not str or not _USER.fullmatch(self.broadcaster_id)
                or type(self.user_id) is not str or not _USER.fullmatch(self.user_id)
                or not self.text or _clean(self.text, 2000) != self.text
                or _clean(self.display_name, 100) != self.display_name
                or type(self.received_at) not in (int, float) or not math.isfinite(self.received_at)):
            raise ValueError("Invalid bounded chat message")


class ChatQueue:
    """Thread-safe bounded chat. A popped message stays current until TTL/removal.

    Deletion and expiry invalidate already-selected messages too. The host must
    recheck current(id) immediately before any later use, and separately moderate
    both incoming text and proposed speech. No raw chat is persisted.
    """
    def __init__(self, *, capacity=200, ttl=45.0, clock=time.monotonic):
        if type(capacity) is not int or not 1 <= capacity <= 1000 or type(ttl) not in (int, float) or not 1 <= ttl <= 300:
            raise ValueError("Invalid bounded chat queue settings")
        self.capacity, self.ttl, self.clock = capacity, float(ttl), clock
        self._active = OrderedDict()
        self._ready = deque()
        self._seen = OrderedDict()
        self._overload_until = 0.0
        self._lock = threading.RLock()
        self._counts = {"dropped": 0, "duplicates": 0, "expired": 0, "removed": 0, "overflows": 0}

    def _trim(self):
        now = self.clock()
        for key, row in list(self._active.items()):
            if now - row.received_at >= self.ttl:
                self._active.pop(key)
                self._counts["expired"] += 1
        self._ready = deque(key for key in self._ready if key in self._active)
        while self._seen and now - next(iter(self._seen.values())) >= 600:
            self._seen.popitem(last=False)
        if len(self._seen) > 4096:
            # Forgetting a tombstone must not resurrect a just-deleted message.
            # Wait until pre-overflow notifications exceed the reader's freshness TTL.
            self._counts["dropped"] += len(self._active)
            self._counts["overflows"] += 1
            self._active.clear()
            self._ready.clear()
            self._seen.clear()
            self._overload_until = now + self.ttl + 30  # also age out the permitted server-clock skew

    def put(self, message: ChatMessage) -> bool:
        if not isinstance(message, ChatMessage):
            raise TypeError("Expected a ChatMessage")
        with self._lock:
            self._trim()
            if self.clock() < self._overload_until:
                self._counts["dropped"] += 1
                return False
            if message.message_id in self._seen:
                self._counts["duplicates"] += 1
                return False
            self._seen[message.message_id] = self.clock()
            if not 0 <= self.clock() - message.received_at < self.ttl:
                self._counts["expired"] += 1
                self._trim()
                return False
            if len(self._active) >= self.capacity:
                self._active.popitem(last=False)
                self._counts["dropped"] += 1
            self._active[message.message_id] = message
            self._ready.append(message.message_id)
            self._trim()
            return message.message_id in self._active

    def peek(self):
        with self._lock:
            self._trim()
            return self._active[self._ready[0]] if self._ready else None

    def pop(self):
        with self._lock:
            self._trim()
            return self._active[self._ready.popleft()] if self._ready else None

    def current(self, message_id: str) -> bool:
        with self._lock:
            self._trim()
            return message_id in self._active

    def remove(self, message_id: str):
        if type(message_id) is not str or not _ID.fullmatch(message_id):
            return
        with self._lock:
            self._seen[message_id] = self.clock()  # tombstone even when deletion precedes delivery
            self._seen.move_to_end(message_id)
            self._counts["removed"] += int(self._active.pop(message_id, None) is not None)
            self._trim()

    def clear_user(self, user_id: str):
        with self._lock:
            for key, message in list(self._active.items()):
                if message.user_id == user_id:
                    self.remove(key)

    def clear(self):
        with self._lock:
            self._counts["removed"] += len(self._active)
            self._active.clear()
            self._ready.clear()

    def counts(self):
        with self._lock:
            self._trim()
            return {**self._counts, "queued": len(self._ready), "current": len(self._active),
                    "overloaded": self.clock() < self._overload_until}


class TwitchSecrets(OSProfileSecrets):
    service = "STAR Twitch Read-Only Chat"


def reconnect_url(value: str) -> str:
    """Retain Twitch's URL exactly; reject alternate hosts, ports, credentials and fragments."""
    if type(value) is not str or not 1 <= len(value) <= 4096 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise TwitchChatError("invalid_reconnect")
    try:
        parsed = urlsplit(value)
        allowed = (parsed.scheme == "wss" and parsed.hostname == "eventsub.wss.twitch.tv"
                   and parsed.port in (None, 443) and parsed.username is None and parsed.password is None
                   and parsed.path in ("", "/", "/ws") and not parsed.fragment
                   and parsed.netloc.casefold() in ("eventsub.wss.twitch.tv", "eventsub.wss.twitch.tv:443"))
    except ValueError:
        allowed = False
    if not allowed:
        raise TwitchChatError("invalid_reconnect")
    return value


class _Socket:
    """No application send method; the library handles required WebSocket pong frames."""
    def __init__(self, url):
        reconnect_url(url)
        import websocket
        websocket.enableTrace(False)
        logger = logging.getLogger("websocket")
        logger.setLevel(logging.CRITICAL + 1)
        logger.propagate = False
        self._library = websocket
        self._ws = websocket.create_connection(url, timeout=2, redirect_limit=0,
            enable_multithread=True, sslopt={"cert_reqs": ssl.CERT_REQUIRED, "check_hostname": True})

    def recv(self):
        try:
            opcode, data = self._ws.recv_data(control_frame=True)
            if opcode == self._library.ABNF.OPCODE_TEXT:
                return data.decode("utf-8") if isinstance(data, bytes) else data
            if opcode in (self._library.ABNF.OPCODE_PING, self._library.ABNF.OPCODE_PONG):
                return None                    # ping/pong does not reset EventSub's keepalive clock
            raise TwitchChatError("socket_closed")
        except self._library.WebSocketTimeoutException:
            return None

    def close(self):
        self._ws.close()


class TwitchChat:
    def __init__(self, client_id: str, broadcaster_id: str, *, vault=None, http=None,
                 socket_factory=None, on_chat=None, clock=time.monotonic, wall_clock=time.time):
        _identity(client_id, broadcaster_id)
        self.client_id, self.broadcaster_id = client_id, broadcaster_id
        self.vault = vault if vault is not None else TwitchSecrets()
        self._vault_key = sha256((client_id + ":" + broadcaster_id).encode()).hexdigest()
        self._http, self._own_http = http, http is None
        self._socket_factory = socket_factory or _Socket
        self._socket = None
        self._token = ""
        self._next_validation = self._expires = 0.0
        self._clock, self._wall_clock = clock, wall_clock
        self._subscriptions = {}
        self._seen_events = OrderedDict()
        self._user_clears = OrderedDict()
        self._clear_at = float("-inf")
        self._run_lock = threading.Lock()
        self.queue = ChatQueue(clock=clock)
        self.on_chat = on_chat
        self._state = {"connected": False, "authenticated": False, "state": "idle", "received": 0,
                       "ignored": 0, "reconnects": 0, "callback_errors": 0, "error": ""}

    def _request(self, target, *, token: str, payload=None):
        if target not in (VALIDATE, SUBSCRIPTIONS):
            raise PermissionError("Only Twitch validation and EventSub subscription endpoints are available")
        if self._http is None:
            self._http = httpx.Client(timeout=8, trust_env=False, follow_redirects=False)
        headers = {"Authorization": ("OAuth " if target == VALIDATE else "Bearer ") + token}
        if target == SUBSCRIPTIONS:
            headers["Client-Id"] = self.client_id
        try:
            response = self._http.request("GET" if target == VALIDATE else "POST", target,
                headers=headers, json=payload, timeout=8, follow_redirects=False)
            if response.status_code == 401:
                raise AuthorizationError("authorization_failed")
            if response.status_code != (200 if target == VALIDATE else 202) or len(response.content) > 131072:
                raise TwitchChatError("twitch_request_failed")
            data = response.json()
            if type(data) is not dict:
                raise TwitchChatError("invalid_twitch_response")
            return data
        except (AuthorizationError, TwitchChatError):
            raise
        except Exception:
            raise TwitchChatError("twitch_unavailable") from None

    def _validate(self, token):
        try:
            return self._validated(token)
        except TwitchChatError:
            self._token = ""
            self._state["authenticated"] = False
            self.queue.clear()
            raise

    def _validated(self, token):
        token = _token(token)
        data = self._request(VALIDATE, token=token)
        expires = data.get("expires_in")
        if (data.get("client_id") != self.client_id or data.get("user_id") != self.broadcaster_id
                or data.get("scopes") != ["user:read:chat"] or type(expires) is not int or expires <= 0):
            raise AuthorizationError("token_identity_or_scope_mismatch")
        self._token = token
        self._expires = self._clock() + expires
        self._next_validation = self._clock() + max(1, min(3500, expires - 1))
        self._state["authenticated"] = True
        return {"authenticated": True, "read_only": True}

    def check_auth(self):
        try:
            token = self.vault.get(self._vault_key)
        except Exception:
            self._token = ""
            self._state["authenticated"] = False
            self.queue.clear()
            raise AuthorizationError("secure_vault_unavailable") from None
        if not token:
            self._token = ""
            self._state["authenticated"] = False
            self.queue.clear()
            raise AuthorizationError("no_saved_token")
        return self._validate(token)

    def save_token(self, token: str):
        self._validate(token)
        try:
            self.vault.put(self._vault_key, self._token)
        except Exception:
            self._token = ""
            self._state["authenticated"] = False
            self.queue.clear()
            raise AuthorizationError("secure_vault_unavailable") from None
        return {"saved": True, "read_only": True}

    def status(self):
        return {**self._state, "queue": self.queue.counts(), "read_only": True}

    def _frame(self, raw):
        if type(raw) is not str or len(raw) > 131072:
            raise TwitchChatError("invalid_event")
        try:
            frame = json.loads(raw)
            metadata = frame["metadata"]
            payload = frame["payload"]
            event_id, kind = metadata["message_id"], metadata["message_type"]
            stamp = datetime.fromisoformat(metadata["message_timestamp"].replace("Z", "+00:00"))
            if stamp.tzinfo is None or not -30 <= self._wall_clock() - stamp.timestamp() <= 120:
                raise ValueError
            if (type(metadata) is not dict or type(payload) is not dict or type(event_id) is not str
                    or not _ID.fullmatch(event_id) or type(kind) is not str):
                raise ValueError
            return metadata, payload, stamp.timestamp()
        except Exception:
            raise TwitchChatError("invalid_event") from None

    def _welcome(self, socket, stop):
        deadline = self._clock() + 10
        while not stop.is_set() and self._clock() < deadline:
            raw = socket.recv()
            if raw is None:
                continue
            metadata, payload, _ = self._frame(raw)
            session = payload.get("session") or {}
            keepalive, identifier = session.get("keepalive_timeout_seconds"), session.get("id")
            if (metadata["message_type"] != "session_welcome" or type(identifier) is not str or not _ID.fullmatch(identifier)
                    or type(keepalive) is not int or not 10 <= keepalive <= 600):
                raise TwitchChatError("invalid_welcome")
            return identifier, keepalive
        raise TwitchChatError("welcome_timeout")

    def _subscribe(self, session_id, stop):
        self._subscriptions = {}
        for kind in TYPES:
            if stop.is_set():
                raise TwitchChatError("stopped")
            payload = {"type": kind, "version": "1", "condition": {"broadcaster_user_id": self.broadcaster_id,
                       "user_id": self.broadcaster_id}, "transport": {"method": "websocket", "session_id": session_id}}
            result = self._request(SUBSCRIPTIONS, token=self._token, payload=payload)
            rows = result.get("data")
            if (type(rows) is not list or len(rows) != 1 or rows[0].get("type") != kind
                    or rows[0].get("status") != "enabled" or type(rows[0].get("id")) is not str
                    or not _ID.fullmatch(rows[0]["id"])):
                raise TwitchChatError("invalid_subscription")
            self._subscriptions[rows[0]["id"]] = kind

    def _notification(self, metadata, payload, stamp):
        subscription, event = payload.get("subscription"), payload.get("event")
        if type(subscription) is not dict:
            raise TwitchChatError("invalid_subscription_event")
        kind = self._subscriptions.get(subscription.get("id"))
        if (kind is None or subscription.get("type") != kind or subscription.get("version") != "1"
                or metadata.get("subscription_type") != kind or metadata.get("subscription_version") != "1"
                or subscription.get("condition") != {"broadcaster_user_id": self.broadcaster_id, "user_id": self.broadcaster_id}):
            self._state["ignored"] += 1
            return
        if metadata["message_type"] == "revocation":
            raise AuthorizationError("subscription_revoked")
        if type(event) is not dict or event.get("broadcaster_user_id") != self.broadcaster_id:
            self._state["ignored"] += 1
            return
        if kind == "channel.chat.message_delete":
            self.queue.remove(event.get("message_id", ""))
        elif kind == "channel.chat.clear_user_messages":
            user = event.get("target_user_id")
            if type(user) is str and _USER.fullmatch(user):
                self.queue.clear_user(user)
                self._user_clears[user] = max(stamp, self._user_clears.get(user, float("-inf")))
                if len(self._user_clears) > 1024:
                    self._clear_at = max(self._clear_at, stamp)
                    self._user_clears.clear()
                    self.queue.clear()
        elif kind == "channel.chat.clear":
            self._clear_at = max(self._clear_at, stamp)
            self.queue.clear()
        else:
            user, message_id = event.get("chatter_user_id", ""), event.get("message_id", "")
            if type(user) is not str or type(message_id) is not str:
                self._state["ignored"] += 1
                return
            if (self._wall_clock() - stamp >= self.queue.ttl or stamp <= self._clear_at
                    or stamp <= self._user_clears.get(user, float("-inf"))):
                self._state["ignored"] += 1
                return
            try:
                row = ChatMessage(message_id, self.broadcaster_id, user,
                                  _clean(event.get("chatter_user_name", ""), 100),
                                  _clean((event.get("message") or {}).get("text"), 2000), self._clock())
            except (ValueError, TypeError, AttributeError):
                self._state["ignored"] += 1
                return
            if self.queue.put(row):
                self._state["received"] += 1
                if self.on_chat is not None:
                    try:
                        self.on_chat(row)
                    except Exception:
                        self._state["callback_errors"] += 1

    def _handle(self, raw):
        metadata, payload, stamp = self._frame(raw)
        now = self._clock()
        while self._seen_events and now - next(iter(self._seen_events.values())) >= 600:
            self._seen_events.popitem(last=False)
        event_id = metadata["message_id"]
        if event_id in self._seen_events:
            return None
        self._seen_events[event_id] = now
        while len(self._seen_events) > 4096:
            self._seen_events.popitem(last=False)
        kind = metadata["message_type"]
        if kind in ("notification", "revocation"):
            self._notification(metadata, payload, stamp)
        elif kind == "session_reconnect":
            return reconnect_url((payload.get("session") or {}).get("reconnect_url", ""))
        elif kind != "session_keepalive":
            raise TwitchChatError("unexpected_event")
        return None

    @staticmethod
    def _close(socket):
        if socket is not None:
            try:
                socket.close()
            except Exception:
                pass

    def run(self, stop_event):
        """Listen until stop/revocation, reconnect with backoff; callbacks must return promptly.

        A server-directed migration retains subscriptions and keeps the old socket
        open until the replacement welcome. Pending chat is invalidated on every
        transition rather than assuming that no moderation events were missed.
        """
        if not self._run_lock.acquire(blocking=False):
            raise TwitchChatError("already_running")
        backoff = 1
        try:
            while not stop_event.is_set():
                try:
                    self._state.update(state="connecting", error="", connected=False)
                    self.check_auth()
                    self._socket = self._socket_factory(EVENTSUB)
                    session_id, keepalive = self._welcome(self._socket, stop_event)
                    self._subscribe(session_id, stop_event)
                    last = self._clock()
                    self._state.update(state="listening", connected=True)
                    backoff = 1
                    while not stop_event.is_set():
                        if self._clock() >= self._next_validation:
                            self._validate(self._token)
                        if self._clock() >= self._expires:
                            raise AuthorizationError("token_expired")
                        if self._clock() - last > keepalive:
                            raise TwitchChatError("keepalive_timeout")
                        raw = self._socket.recv()
                        if raw is None:
                            continue
                        migration = self._handle(raw)
                        last = self._clock()
                        if migration:
                            self.queue.clear()
                            self._state.update(state="reconnecting", connected=False)
                            replacement = None
                            try:
                                replacement = self._socket_factory(migration)
                                _, keepalive = self._welcome(replacement, stop_event)
                            except Exception:
                                self._close(replacement)
                                raise
                            self._close(self._socket)
                            self._socket = replacement
                            self._clear_at = max(self._clear_at, self._wall_clock())
                            self._state["reconnects"] += 1
                            self._state.update(state="listening", connected=True)
                            last = self._clock()
                except AuthorizationError as exc:
                    code = str(exc) if str(exc) in _ERRORS else "authorization_failed"
                    self._state.update(authenticated=False, state="authorization_failed", error=code)
                    break
                except Exception as exc:
                    code = str(exc) if isinstance(exc, TwitchChatError) and str(exc) in _ERRORS else "connection_unavailable"
                    self._state.update(state="reconnecting", error=code, authenticated=False)
                finally:
                    self._state["connected"] = False
                    self.queue.clear()
                    self._clear_at = max(self._clear_at, self._wall_clock())
                    self._close(self._socket)
                    self._socket = None
                if stop_event.is_set():
                    break
                self._state["reconnects"] += 1
                stop_event.wait(backoff)
                backoff = min(60, backoff * 2)
        finally:
            self._state["connected"] = False
            self._state["authenticated"] = False
            self._token = ""
            if stop_event.is_set() or self._state["state"] in ("connecting", "listening", "reconnecting"):
                self._state["state"] = "stopped"
            if self._own_http and self._http is not None:
                try:
                    self._http.close()
                except Exception:
                    pass
                self._http = None
            self._run_lock.release()
        return self.status()


def cli():
    parser = argparse.ArgumentParser(description="Read-only own-channel Twitch chat; never sends messages")
    parser.add_argument("command", choices=("status", "save-token", "listen"))
    parser.add_argument("--client-id", required=True)
    parser.add_argument("--broadcaster-id", required=True)
    args = parser.parse_args()
    reader = None
    try:
        reader = TwitchChat(args.client_id, args.broadcaster_id)
        if args.command == "save-token":
            if not sys.stdin.isatty():
                raise AuthorizationError("interactive_terminal_required")
            result = reader.save_token(getpass("Broadcaster token with only user:read:chat: "))
        elif args.command == "status":
            reader.check_auth()
            result = reader.status()
        else:
            stop = threading.Event()
            try:
                result = reader.run(stop)
            except KeyboardInterrupt:
                stop.set()
                result = reader.status()
        print(json.dumps(result, indent=2))
    except (ValueError, TwitchChatError):
        print(json.dumps({"ok": False, "error": "Twitch chat is unavailable; review the local read-only authorization"}))
        raise SystemExit(1) from None
    finally:
        if reader is not None and reader._own_http and reader._http is not None:
            try:
                reader._http.close()
            except Exception:
                pass


if __name__ == "__main__":
    cli()
