"""Offline, opt-in Twitch EventSub chat ingress for Star's VTuber.

Twitch notifications are delivered at least once and may be redelivered after
WebSocket reconnection. This bounded adapter rejects both repeated transport
message IDs and repeated chat message IDs BEFORE they reach StreamDirector.

An authenticated, consented host must parse Twitch TLS/WebSocket traffic,
validate OAuth subscriptions and moderate all text. host_verified/moderated
are host attestations, not cryptographic checks. Viewer text is ALWAYS data;
this module never sends chat, speaks, controls games, stores raw text, or
connects to the internet. It is disabled by default.
"""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import math
import re
from threading import RLock
from typing import Mapping, cast

from .stream_director import StreamSignal

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_ACCOUNT = re.compile(r"[0-9]{1,40}\Z")
_CHAT_KINDS = frozenset({"viewer_question", "viewer_comment"})
_MAX_CLOCK_S = 1e10


def _host_seconds(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("host time must be a finite monotonic second value")
    try:
        number = float(cast(int | float, value))
    except (OverflowError, ValueError) as exc:
        raise ValueError("invalid host time") from exc
    if not math.isfinite(number) or not 0 <= number <= _MAX_CLOCK_S:
        raise ValueError("invalid host time")
    return number


def _bounded_id(value: object, label: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{label} must be a bounded platform event ID")
    return value


def _account_id(value: object, label: str) -> str:
    if type(value) is not str or _ACCOUNT.fullmatch(value) is None:
        raise ValueError(f"{label} must be a canonical Twitch numeric account ID")
    return value


def _part(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _digest(prefix: str, ident: str) -> str:
    return hashlib.sha256((prefix + "\x00" + ident).encode("utf-8")).hexdigest()


class TwitchEventSubIngress:
    """Session-scoped transport-level chat de-duplication, no network I/O.

    Reconnect to Twitch WITHOUT disabling this instance so at-least-once
    deliveries cannot repeat an already processed line. Disable/re-enable
    only for a truly new stream session. A bounded window means very old
    duplicate deliveries can reappear; the host also needs replay protection.
    """

    def __init__(self, *, max_seen_ids: int = 2048,
                 retention_seconds: float = 900.0) -> None:
        if type(max_seen_ids) is not int or not 64 <= max_seen_ids <= 8192:
            raise ValueError("max_seen_ids must be 64..8192")
        retention = _host_seconds(retention_seconds)
        if not 30 <= retention <= 3600:
            raise ValueError("retention_seconds must be 30..3600")
        self._lock = RLock()
        self._max_seen = max_seen_ids
        self._retention = retention
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._enabled = False
        self._broadcaster = ""
        self._last_now: float | None = None
        self._counts = {"accepted": 0, "rejected": 0, "duplicates": 0}

    def enable(self, *, owner_approved: bool = False,
               broadcaster_user_id: str) -> None:
        if owner_approved is not True:
            raise PermissionError("trusted host must opt into Twitch chat ingest")
        broadcaster = _account_id(broadcaster_user_id, "broadcaster_user_id")
        with self._lock:
            if self._enabled:
                raise RuntimeError("disable before switching stream sessions")
            self._seen.clear()
            self._broadcaster = broadcaster
            self._last_now = None
            self._enabled = True

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._broadcaster = ""
            self._last_now = None
            self._seen.clear()

    def _expire(self, now: float) -> None:
        # Insertion order is expiry order because the host clock is monotonic.
        while self._seen and next(iter(self._seen.values())) <= now:
            self._seen.popitem(last=False)

    def offer(self, notification: Mapping[str, object], *,
              now_s: float, host_verified: bool = False,
              moderated: bool = False, kind: str = "viewer_comment") -> StreamSignal | None:
        """Return a moderated StreamSignal; Stage.offer still rechecks moderation.

        Only authenticated EventSub `channel.chat.message` notifications qualify.
        Twitch metadata.message_id and event.message_id are independently
        deduplicated; reconnect does not clear history. No authorization,
        prediction or subscriber operation can be derived from viewer text.
        """
        now = _host_seconds(now_s)
        if type(host_verified) is not bool or type(moderated) is not bool:
            raise ValueError("host_verified/moderated must be strict booleans")
        if type(kind) is not str or kind not in _CHAT_KINDS:
            raise ValueError("kind must be a viewer speech category")
        with self._lock:
            if not self._enabled or not host_verified or not moderated:
                self._counts["rejected"] += 1
                return None
            if self._last_now is not None and now < self._last_now:
                self._counts["rejected"] += 1
                return None
            self._last_now = now
            self._expire(now)
            if not isinstance(notification, Mapping):
                raise ValueError("notification must be a JSON object")
            metadata = _part(notification.get("metadata"), "metadata")
            payload = _part(notification.get("payload"), "payload")
            subscription = _part(payload.get("subscription"), "subscription")
            event = _part(payload.get("event"), "event")
            message = _part(event.get("message"), "message")
            if (metadata.get("message_type") != "notification"
                    or metadata.get("subscription_type") != "channel.chat.message"
                    or subscription.get("type") != "channel.chat.message"):
                self._counts["rejected"] += 1
                return None
            envelope_id = _bounded_id(metadata.get("message_id"), "message_id")
            chat_id = _bounded_id(event.get("message_id"), "chat_message_id")
            broadcaster = _account_id(event.get("broadcaster_user_id"), "broadcaster")
            chatter = _account_id(event.get("chatter_user_id"), "chatter")
            if broadcaster != self._broadcaster:
                self._counts["rejected"] += 1
                return None
            detail = message.get("text")
            if type(detail) is not str or not 1 <= len(detail) <= 500:
                raise ValueError("moderated chat text must be 1..500 characters")
            if any(ord(ch) < 32 and ch not in "\n\t" for ch in detail):
                raise ValueError("control characters cannot be narrated")
            envelope_hash = _digest("delivery", envelope_id)
            chat_hash = _digest("chat", chat_id)
            if envelope_hash in self._seen or chat_hash in self._seen:
                self._counts["duplicates"] += 1
                return None
            signal = StreamSignal(
                signal_id="tw_" + hashlib.sha256(chat_id.encode("utf-8")).hexdigest()[:32],
                kind=kind, timestamp=now, detail=detail,
                speaker_id="twitch:" + chatter, evidence="reported",
            )
            self._seen[envelope_hash] = now + self._retention
            self._seen[chat_hash] = now + self._retention
            while len(self._seen) > self._max_seen:
                self._seen.popitem(last=False)
            self._counts["accepted"] += 1
            return signal

    def metrics(self) -> dict[str, int | bool]:
        """Anonymous counts only, never raw IDs, messages, or viewer names."""
        with self._lock:
            return {**self._counts, "enabled": self._enabled,
                    "recent_id_count": len(self._seen)}


__all__ = ["TwitchEventSubIngress"]
