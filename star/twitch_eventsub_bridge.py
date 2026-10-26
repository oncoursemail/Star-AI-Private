"""Offline Twitch EventSub chat adapter for Star's StreamDirector.

The authorized host owns Twitch OAuth, the trusted WebSocket, independent
moderation, and stream delivery. This module neither opens sockets nor speaks.
A chat message NEVER authenticates the owner, authorizes tools, or selects
Star's actions. Only owner-approved, moderated text becomes an untrusted
StreamSignal. Raw chat and Twitch account IDs are never saved in this adapter.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import re
from threading import RLock

from .stream_director import StreamSignal

_USER_ID = re.compile(r"[0-9]{1,32}\Z")
_SESSION = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
_MESSAGE_ID = re.compile(r"[A-Za-z0-9-]{8,128}\Z")
_MAX_FRAME = 16_384
_MAX_AGE_SECONDS = 15.0
_FUTURE_TOLERANCE_SECONDS = 2.0


def _clock(value: object, name: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} must be finite and numeric")
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 1e12:
        raise ValueError(f"{name} outside valid range")
    return result


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _timestamp(value: object) -> float | None:
    if type(value) is not str or not 20 <= len(value) <= 48:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc).timestamp()
    except (ValueError, OverflowError, OSError):
        return None


class TwitchEventSubBridge:
    """Bounded EventSub notification parser for a single owner-approved session.

    The session_id must come from an authenticated host-managed EventSub
    WebSocket. A forged JSON frame is not authenticated by checking its fields.
    The caller MUST moderate the ORIGINAL event before supplying trusted
    moderated_text and moderation_approved=True. This bridge is only a
    second-stage protocol/pacing guard; it is not a content safety classifier.
    """

    def __init__(self, *, broadcaster_user_id: str, session_id: str,
                 session_salt: bytes, max_seen: int = 512,
                 viewer_interval_s: float = 1.5) -> None:
        if type(broadcaster_user_id) is not str or not _USER_ID.fullmatch(broadcaster_user_id):
            raise ValueError("expected numeric broadcaster_user_id")
        if type(session_id) is not str or not _SESSION.fullmatch(session_id):
            raise ValueError("expected bounded WebSocket session_id")
        if type(session_salt) is not bytes or not 16 <= len(session_salt) <= 128:
            raise ValueError("session_salt must be 16..128 random host-held bytes")
        if type(max_seen) is not int or not 32 <= max_seen <= 4096:
            raise ValueError("max_seen must be 32..4096")
        interval = _clock(viewer_interval_s, "viewer_interval_s")
        if not 0.25 <= interval <= 20:
            raise ValueError("viewer_interval_s must be 0.25..20")
        self._broadcaster = broadcaster_user_id
        self._session = session_id
        self._salt = session_salt
        self._max_seen = max_seen
        self._viewer_interval = interval
        self._enabled = False
        self._clock_s: float | None = None
        self._seen: dict[str, float] = {}
        self._viewer_last: dict[str, float] = {}
        self._counts = {"accepted": 0, "rejected": 0, "duplicates": 0, "throttled": 0}
        self._lock = RLock()

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("explicit owner approval required")
        with self._lock:
            self._enabled = True

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._seen.clear()
            self._viewer_last.clear()
            self._clock_s = None

    def _opaque(self, prefix: str, value: str) -> str:
        return prefix + hmac.new(self._salt, value.encode("utf-8"), hashlib.sha256).hexdigest()[:40]

    def ingest(self, raw_frame: str, *, now_unix_s: float,
               now_monotonic_s: float, moderated_text: str | None = None,
               moderation_approved: bool = False) -> StreamSignal | None:
        """Convert one trusted, moderated WebSocket frame into speech context.

        No I/O, model inference or speech occurs. Rejects wrong sessions,
        stale events, duplicates, unsafe unmoderated data, and chat floods.
        Rejections intentionally don't reveal raw text or viewer identities.
        """
        now_unix = _clock(now_unix_s, "now_unix_s")
        now_mono = _clock(now_monotonic_s, "now_monotonic_s")
        with self._lock:
            if self._clock_s is not None and now_mono < self._clock_s:
                raise ValueError("monotonic clock cannot reverse")
            self._clock_s = now_mono
            if (not self._enabled or moderation_approved is not True
                    or type(moderated_text) is not str
                    or not 1 <= len(moderated_text.strip()) <= 500
                    or any(ord(c) < 32 for c in moderated_text)
                    or type(raw_frame) is not str or len(raw_frame) > _MAX_FRAME):
                self._counts["rejected"] += 1
                return None
            try:
                packet = json.loads(raw_frame, object_pairs_hook=_no_duplicates,
                                    parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                metadata = packet["metadata"]
                payload = packet["payload"]
                sub = payload["subscription"]
                event = payload["event"]
                transport = sub["transport"]
                condition = sub["condition"]
                message = event["message"]
                if not all(isinstance(item, dict) for item in
                           (packet, metadata, payload, sub, event, transport, condition, message)):
                    raise ValueError("invalid event object")
                if (metadata.get("message_type") != "notification"
                    or metadata.get("subscription_type") != "channel.chat.message"
                    or metadata.get("subscription_version") != "1"
                    or sub.get("type") != "channel.chat.message"
                    or sub.get("version") != "1" or sub.get("status") != "enabled"
                    or transport.get("method") != "websocket"
                    or transport.get("session_id") != self._session
                    or condition.get("broadcaster_user_id") != self._broadcaster
                    or event.get("broadcaster_user_id") != self._broadcaster):
                    raise ValueError("different session or channel")
                packet_id, message_id, viewer_id = (metadata.get("message_id"),
                                                     event.get("message_id"),
                                                     event.get("chatter_user_id"))
                if (type(packet_id) is not str or not _MESSAGE_ID.fullmatch(packet_id)
                    or type(message_id) is not str or not _MESSAGE_ID.fullmatch(message_id)
                    or type(viewer_id) is not str or not _USER_ID.fullmatch(viewer_id)
                    or type(message.get("text")) is not str
                    or not 1 <= len(message["text"].strip()) <= 1000):
                    raise ValueError("invalid message identifiers or text")
                sent = _timestamp(metadata.get("message_timestamp"))
                if sent is None or not -_FUTURE_TOLERANCE_SECONDS <= now_unix - sent <= _MAX_AGE_SECONDS:
                    raise ValueError("stale or future message")
            except (ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError):
                self._counts["rejected"] += 1
                return None
            self._seen = {key: t for key, t in self._seen.items()
                          if now_mono - t <= 90}
            self._viewer_last = {key: t for key, t in self._viewer_last.items()
                                 if now_mono - t <= self._viewer_interval}
            key = self._opaque("m_", message_id)
            viewer = self._opaque("v_", viewer_id)
            if key in self._seen:
                self._counts["duplicates"] += 1
                return None
            if now_mono - self._viewer_last.get(viewer, float("-inf")) < self._viewer_interval:
                self._counts["throttled"] += 1
                return None
            if len(self._seen) >= self._max_seen:
                oldest = min(self._seen, key=self._seen.__getitem__)
                del self._seen[oldest]
            self._seen[key] = now_mono
            if viewer not in self._viewer_last and len(self._viewer_last) >= self._max_seen:
                oldest_viewer = min(self._viewer_last, key=self._viewer_last.__getitem__)
                del self._viewer_last[oldest_viewer]
            self._viewer_last[viewer] = now_mono
            self._counts["accepted"] += 1
            # Twitch's timestamp uses UTC; StreamDirector's expiry uses mono.
            event_mono = max(0, now_mono - max(0, now_unix - sent))
            text = moderated_text.strip()
            return StreamSignal(
                signal_id=self._opaque("tw_", message_id),
                kind="viewer_question" if text.endswith("?") else "viewer_comment",
                timestamp=event_mono, detail=text,
                speaker_id=viewer, evidence="reported",
            )

    def metrics(self) -> dict[str, int | bool]:
        """Aggregate counts only: no message contents or platform IDs."""
        with self._lock:
            return {**self._counts, "enabled": self._enabled,
                    "cached_messages": len(self._seen),
                    "cached_viewers": len(self._viewer_last)}


__all__ = ["TwitchEventSubBridge"]
