"""Bounded, ephemeral text payloads for multiparty room cues.

RoomCueQueue intentionally stores metadata only. This optional host-side store keeps the
small text payload needed to answer a queued audio transcript, chat message, or game
observation. It never stores PCM, embeddings, voiceprints, credentials, or persistent data.

The store is opt-in, thread-safe, TTL-bounded, byte-bounded, and destructive on take.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
import math
import threading

from .room import CueSource, RoomCue


def _finite(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class RoomPayloadStoreConfig:
    max_items: int = 64
    max_payload_bytes: int = 8_192
    max_total_bytes: int = 262_144
    max_age_seconds: float = 8.0
    max_future_skew_seconds: float = 0.25
    dedupe_capacity: int = 1_024

    def __post_init__(self) -> None:
        if type(self.max_items) is not int or not 1 <= self.max_items <= 4_096:
            raise ValueError("max_items must be an integer from 1 to 4096")
        if type(self.max_payload_bytes) is not int or not 1 <= self.max_payload_bytes <= 1_048_576:
            raise ValueError("max_payload_bytes must be an integer from 1 to 1048576")
        if type(self.max_total_bytes) is not int or not 1 <= self.max_total_bytes <= 16_777_216:
            raise ValueError("max_total_bytes must be an integer from 1 to 16777216")
        if self.max_total_bytes < self.max_payload_bytes:
            raise ValueError("max_total_bytes must be at least max_payload_bytes")
        if type(self.dedupe_capacity) is not int or not 1 <= self.dedupe_capacity <= 16_384:
            raise ValueError("dedupe_capacity must be an integer from 1 to 16384")
        for name in ("max_age_seconds",):
            value = getattr(self, name)
            if not _finite(value) or value <= 0:
                raise ValueError(f"{name} must be a finite positive number")
        if not _finite(self.max_future_skew_seconds) or self.max_future_skew_seconds < 0:
            raise ValueError("max_future_skew_seconds must be a finite non-negative number")


class RoomPayloadKind(str, Enum):
    TRANSCRIPT = "transcript"
    CHAT_MESSAGE = "chat_message"
    GAME_OBSERVATION = "game_observation"


class RoomPayloadStoreResult(str, Enum):
    STORED = "stored"
    DUPLICATE = "duplicate"
    FULL = "full"
    TOO_LARGE = "too_large"
    STALE = "stale"
    NOT_FINAL = "not_final"


@dataclass(frozen=True)
class RoomPayload:
    """A one-time payload returned to the host; content remains untrusted input."""

    cue: RoomCue
    kind: RoomPayloadKind
    text: str
    received_at: float


@dataclass(frozen=True)
class RoomPayloadStoreStats:
    items: int = 0
    bytes_used: int = 0
    peak_bytes: int = 0
    accepted: int = 0
    taken: int = 0
    expired: int = 0
    deleted: int = 0
    duplicates: int = 0
    rejected_full: int = 0
    rejected_too_large: int = 0
    rejected_stale: int = 0
    rejected_non_final: int = 0


@dataclass
class _PayloadEntry:
    cue: RoomCue
    kind: RoomPayloadKind
    data: bytearray
    received_at: float
    expires_at: float


_SOURCE_KIND = {
    CueSource.AUDIO: RoomPayloadKind.TRANSCRIPT,
    CueSource.CHAT: RoomPayloadKind.CHAT_MESSAGE,
    CueSource.GAME: RoomPayloadKind.GAME_OBSERVATION,
}


class RoomPayloadStore:
    """Opt-in in-memory store for short-lived, classified room text.

    The caller supplies already-transcribed or already-extracted text. The store does not
    perform ASR, OCR, diarization, classification, persistence, or tool authorization.
    Timestamps use the same host monotonic clock as RoomCue and RoomCueQueue.
    """

    def __init__(self, config: RoomPayloadStoreConfig | None = None) -> None:
        if config is not None and not isinstance(config, RoomPayloadStoreConfig):
            raise TypeError("config must be a RoomPayloadStoreConfig")
        self.config = config or RoomPayloadStoreConfig()
        self._lock = threading.RLock()
        self._items: dict[str, _PayloadEntry] = {}
        self._seen_order: deque[str] = deque()
        self._seen: set[str] = set()
        self._bytes_used = 0
        self._peak_bytes = 0
        self._counts = {
            "accepted": 0,
            "taken": 0,
            "expired": 0,
            "deleted": 0,
            "duplicates": 0,
            "rejected_full": 0,
            "rejected_too_large": 0,
            "rejected_stale": 0,
            "rejected_non_final": 0,
        }

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    @property
    def stats(self) -> RoomPayloadStoreStats:
        with self._lock:
            return RoomPayloadStoreStats(
                items=len(self._items),
                bytes_used=self._bytes_used,
                peak_bytes=self._peak_bytes,
                **self._counts,
            )

    def put(self, cue: RoomCue, text: str, *, now: float) -> RoomPayloadStoreResult:
        """Store final cue text until take, delete, expiry, or session reset."""
        self._validate_cue(cue, now)
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        if not text.strip():
            raise ValueError("text must not be empty")
        if not cue.final:
            with self._lock:
                self._bump("rejected_non_final")
            return RoomPayloadStoreResult.NOT_FINAL

        try:
            encoded = bytearray(text.encode("utf-8", errors="strict"))
        except UnicodeEncodeError as exc:
            raise ValueError("text must be valid UTF-8") from exc

        size = len(encoded)
        if size > self.config.max_payload_bytes:
            self._wipe(encoded)
            with self._lock:
                self._bump("rejected_too_large")
            return RoomPayloadStoreResult.TOO_LARGE

        if cue.ended_at > now + self.config.max_future_skew_seconds:
            self._wipe(encoded)
            with self._lock:
                self._bump("rejected_stale")
            return RoomPayloadStoreResult.STALE
        if now - cue.ended_at > self.config.max_age_seconds:
            self._wipe(encoded)
            with self._lock:
                self._bump("rejected_stale")
            return RoomPayloadStoreResult.STALE

        expires_at = min(cue.ended_at + self.config.max_age_seconds, now + self.config.max_age_seconds)
        if expires_at <= now:
            self._wipe(encoded)
            with self._lock:
                self._bump("rejected_stale")
            return RoomPayloadStoreResult.STALE

        with self._lock:
            self._expire_locked(now)
            if cue.event_id in self._seen or cue.event_id in self._items:
                self._wipe(encoded)
                self._bump("duplicates")
                return RoomPayloadStoreResult.DUPLICATE
            if len(self._items) >= self.config.max_items or self._bytes_used + size > self.config.max_total_bytes:
                self._wipe(encoded)
                self._bump("rejected_full")
                return RoomPayloadStoreResult.FULL

            self._items[cue.event_id] = _PayloadEntry(
                cue=cue,
                kind=_SOURCE_KIND[cue.source],
                data=encoded,
                received_at=float(now),
                expires_at=expires_at,
            )
            self._bytes_used += size
            self._peak_bytes = max(self._peak_bytes, self._bytes_used)
            self._remember(cue.event_id)
            self._bump("accepted")
            return RoomPayloadStoreResult.STORED

    def take(self, event_id: str, *, now: float) -> RoomPayload | None:
        """Destructively retrieve one unexpired payload and wipe the stored byte buffer."""
        self._validate_event_id(event_id)
        if not _finite(now):
            raise ValueError("now must be a finite monotonic timestamp")
        with self._lock:
            self._expire_locked(float(now))
            entry = self._items.pop(event_id, None)
            if entry is None:
                return None
            self._bytes_used -= len(entry.data)
            text = bytes(entry.data).decode("utf-8")
            self._wipe(entry.data)
            self._bump("taken")
            return RoomPayload(
                cue=entry.cue,
                kind=entry.kind,
                text=text,
                received_at=entry.received_at,
            )

    def delete(self, event_id: str) -> bool:
        """Delete one payload without making its event ID reusable in this session."""
        self._validate_event_id(event_id)
        with self._lock:
            entry = self._items.pop(event_id, None)
            if entry is None:
                return False
            self._bytes_used -= len(entry.data)
            self._wipe(entry.data)
            self._bump("deleted")
            return True

    def expire(self, *, now: float) -> tuple[str, ...]:
        """Expire payloads and return event IDs so the host can reconcile its room queue."""
        if not _finite(now):
            raise ValueError("now must be a finite monotonic timestamp")
        with self._lock:
            return tuple(self._expire_locked(float(now)))

    def reset(self) -> None:
        """Wipe all pending payloads and session deduplication state."""
        with self._lock:
            for entry in self._items.values():
                self._wipe(entry.data)
            self._items.clear()
            self._seen_order.clear()
            self._seen.clear()
            self._bytes_used = 0
            self._peak_bytes = 0
            for key in self._counts:
                self._counts[key] = 0

    def _expire_locked(self, now: float) -> list[str]:
        expired = [event_id for event_id, entry in self._items.items() if now >= entry.expires_at]
        for event_id in expired:
            entry = self._items.pop(event_id)
            self._bytes_used -= len(entry.data)
            self._wipe(entry.data)
        if expired:
            self._bump("expired", len(expired))
        return expired

    def _remember(self, event_id: str) -> None:
        self._seen.add(event_id)
        self._seen_order.append(event_id)
        while len(self._seen_order) > self.config.dedupe_capacity:
            old_id = self._seen_order.popleft()
            self._seen.discard(old_id)

    def _bump(self, name: str, amount: int = 1) -> None:
        self._counts[name] += amount

    @staticmethod
    def _wipe(buffer: bytearray) -> None:
        """Best-effort overwrite of this store's mutable copy; not cryptographic erasure."""
        for index in range(len(buffer)):
            buffer[index] = 0
        buffer.clear()

    @staticmethod
    def _validate_event_id(event_id: str) -> None:
        if not isinstance(event_id, str) or not event_id or len(event_id) > 128:
            raise ValueError("event_id must be a non-empty string of at most 128 characters")

    @classmethod
    def _validate_cue(cls, cue: RoomCue, now: float) -> None:
        if not isinstance(cue, RoomCue):
            raise TypeError("cue must be a RoomCue")
        cls._validate_event_id(cue.event_id)
        if not isinstance(cue.speaker_id, str) or not cue.speaker_id or len(cue.speaker_id) > 128:
            raise ValueError("speaker_id must be a non-empty string of at most 128 characters")
        if not isinstance(cue.source, CueSource):
            raise ValueError("source must use CueSource")
        if type(cue.final) is not bool:
            raise ValueError("final must be a boolean")
        if type(cue.addressed_to_star) is not bool:
            raise ValueError("addressed_to_star must be a boolean")
        for name, value in (
            ("confidence", cue.confidence),
            ("urgency", cue.urgency),
            ("started_at", cue.started_at),
            ("ended_at", cue.ended_at),
            ("now", now),
        ):
            if not _finite(value):
                raise ValueError(f"{name} must be a finite number")
        if not 0.0 <= cue.confidence <= 1.0 or not 0.0 <= cue.urgency <= 1.0:
            raise ValueError("confidence and urgency must be between 0 and 1")
        if cue.ended_at < cue.started_at:
            raise ValueError("ended_at cannot be earlier than started_at")
        if type(cue.overlap_ms) is not int or not 0 <= cue.overlap_ms <= 60_000:
            raise ValueError("overlap_ms must be an integer from 0 to 60000")
