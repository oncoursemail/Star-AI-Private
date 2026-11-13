"""Bounded, content-free queue for classified multiparty room cues.

The host keeps message/audio payloads in its own short-lived store keyed by event_id.
This queue stores only RoomCue metadata, prioritizes urgent items, ages older items,
and expires cues before their conversational context becomes stale.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
import math
import threading

from .room import CueIntent, CueSource, RoomAction, RoomCue, RoomDecision


def _finite(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class RoomQueueConfig:
    max_items: int = 64
    max_event_age_seconds: float = 8.0
    max_queue_wait_seconds: float = 8.0
    max_future_skew_seconds: float = 0.25
    aging_interval_seconds: float = 2.0
    dedupe_capacity: int = 1024

    def __post_init__(self) -> None:
        if type(self.max_items) is not int or not 1 <= self.max_items <= 4096:
            raise ValueError("max_items must be an integer from 1 to 4096")
        if type(self.dedupe_capacity) is not int or not 1 <= self.dedupe_capacity <= 16384:
            raise ValueError("dedupe_capacity must be an integer from 1 to 16384")
        for name in (
            "max_event_age_seconds",
            "max_queue_wait_seconds",
            "aging_interval_seconds",
        ):
            value = getattr(self, name)
            if not _finite(value) or value <= 0:
                raise ValueError(f"{name} must be a finite positive number")
        if not _finite(self.max_future_skew_seconds) or self.max_future_skew_seconds < 0:
            raise ValueError("max_future_skew_seconds must be a finite non-negative number")


class RoomQueueResult(str, Enum):
    ADDED = "added"
    DUPLICATE = "duplicate"
    NOT_QUEUEABLE = "not_queueable"
    FULL = "full"
    STALE = "stale"


@dataclass(frozen=True)
class RoomQueueStats:
    accepted: int = 0
    dequeued: int = 0
    expired: int = 0
    duplicates: int = 0
    rejected_full: int = 0
    rejected_stale: int = 0
    not_queueable: int = 0
    expired_notifications_dropped: int = 0


@dataclass(frozen=True)
class _QueuedCue:
    cue: RoomCue
    priority: int
    sequence: int
    accepted_at: float
    expires_at: float


class RoomCueQueue:
    """Thread-safe, bounded priority queue containing metadata only.

    All timestamps use the host monotonic clock. Priority is stable for equal
    scores; waiting items gain one priority point per aging interval (capped at
    100) so a steady stream of urgent cues cannot starve ordinary questions.
    Expiry is bounded by both the cue's event age and its queue residence time.
    """

    def __init__(self, config: RoomQueueConfig | None = None) -> None:
        if config is not None and not isinstance(config, RoomQueueConfig):
            raise TypeError("config must be a RoomQueueConfig")
        self.config = config or RoomQueueConfig()
        self._lock = threading.Lock()
        self._items: list[_QueuedCue] = []
        self._seen_order: deque[str] = deque()
        self._seen: set[str] = set()
        self._expired_pending: deque[RoomCue] = deque()
        self._sequence = 0
        self._stats = RoomQueueStats()

    @property
    def stats(self) -> RoomQueueStats:
        with self._lock:
            return self._stats

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def enqueue(self, cue: RoomCue, decision: RoomDecision, *, now: float) -> RoomQueueResult:
        """Queue one cue only when the director explicitly returned QUEUE."""
        self._validate(cue, decision, now, self.config.max_future_skew_seconds)
        if decision.action is not RoomAction.QUEUE or not cue.final:
            with self._lock:
                self._bump(not_queueable=1)
            return RoomQueueResult.NOT_QUEUEABLE
        if decision.event_id != cue.event_id:
            raise ValueError("decision event_id must match cue event_id")
        if type(decision.priority) is not int or not 0 <= decision.priority <= 100:
            raise ValueError("decision priority must be an integer from 0 to 100")

        if now - cue.ended_at > self.config.max_event_age_seconds:
            with self._lock:
                self._bump(rejected_stale=1)
            return RoomQueueResult.STALE

        expires_at = min(
            cue.ended_at + self.config.max_event_age_seconds,
            now + self.config.max_queue_wait_seconds,
        )
        if expires_at <= now:
            with self._lock:
                self._bump(rejected_stale=1)
            return RoomQueueResult.STALE

        with self._lock:
            self._expire_locked(now)
            if cue.event_id in self._seen:
                self._bump(duplicates=1)
                return RoomQueueResult.DUPLICATE
            if len(self._items) >= self.config.max_items:
                self._bump(rejected_full=1)
                return RoomQueueResult.FULL

            item = _QueuedCue(
                cue=cue,
                priority=decision.priority,
                sequence=self._sequence,
                accepted_at=now,
                expires_at=expires_at,
            )
            self._sequence += 1
            self._items.append(item)
            self._remember_locked(cue.event_id)
            self._bump(accepted=1)
            return RoomQueueResult.ADDED

    def pop_next(self, *, now: float) -> RoomCue | None:
        """Remove and return the highest effective-priority non-expired cue."""
        if not _finite(now):
            raise ValueError("now must be a finite monotonic timestamp")
        with self._lock:
            self._expire_locked(float(now))
            if not self._items:
                return None

            interval = self.config.aging_interval_seconds

            def rank(item: _QueuedCue) -> tuple[int, int]:
                age_boost = int(max(0.0, now - item.accepted_at) / interval)
                effective_priority = min(100, item.priority + age_boost)
                return effective_priority, -item.sequence

            index = max(range(len(self._items)), key=lambda i: rank(self._items[i]))
            item = self._items.pop(index)
            self._bump(dequeued=1)
            return item.cue

    def expire(self, *, now: float) -> tuple[RoomCue, ...]:
        """Remove expired cues and return them so the host can clean its payload store."""
        if not _finite(now):
            raise ValueError("now must be a finite monotonic timestamp")
        with self._lock:
            self._expire_locked(float(now))
            expired = tuple(self._expired_pending)
            self._expired_pending.clear()
            return expired

    def discard(self, event_id: str) -> bool:
        """Remove a queued event without making its ID reusable in this session."""
        if not isinstance(event_id, str) or not event_id or len(event_id) > 128:
            raise ValueError("event_id must be a non-empty string of at most 128 characters")
        with self._lock:
            before = len(self._items)
            self._items = [item for item in self._items if item.cue.event_id != event_id]
            return len(self._items) != before

    def reset(self) -> None:
        """Clear queue, dedupe history, sequence and counters at session end."""
        with self._lock:
            self._items.clear()
            self._seen_order.clear()
            self._seen.clear()
            self._expired_pending.clear()
            self._sequence = 0
            self._stats = RoomQueueStats()

    def _expire_locked(self, now: float) -> list[_QueuedCue]:
        expired = [item for item in self._items if now >= item.expires_at]
        if expired:
            expired_ids = {item.cue.event_id for item in expired}
            self._items = [item for item in self._items if item.cue.event_id not in expired_ids]
            self._bump(expired=len(expired))
            for item in expired:
                if len(self._expired_pending) >= self.config.dedupe_capacity:
                    self._expired_pending.popleft()
                    self._bump(expired_notifications_dropped=1)
                self._expired_pending.append(item.cue)
        return expired

    def _remember_locked(self, event_id: str) -> None:
        self._seen.add(event_id)
        self._seen_order.append(event_id)
        while len(self._seen_order) > self.config.dedupe_capacity:
            old_id = self._seen_order.popleft()
            self._seen.discard(old_id)

    def _bump(self, **changes: int) -> None:
        values = {
            "accepted": self._stats.accepted,
            "dequeued": self._stats.dequeued,
            "expired": self._stats.expired,
            "duplicates": self._stats.duplicates,
            "rejected_full": self._stats.rejected_full,
            "rejected_stale": self._stats.rejected_stale,
            "not_queueable": self._stats.not_queueable,
            "expired_notifications_dropped": self._stats.expired_notifications_dropped,
        }
        for name, amount in changes.items():
            values[name] += amount
        self._stats = RoomQueueStats(**values)

    @staticmethod
    def _validate(
        cue: RoomCue, decision: RoomDecision, now: float, max_future_skew_seconds: float
    ) -> None:
        if not isinstance(cue, RoomCue):
            raise TypeError("cue must be a RoomCue")
        if not isinstance(decision, RoomDecision):
            raise TypeError("decision must be a RoomDecision")
        if not _finite(now):
            raise ValueError("now must be a finite monotonic timestamp")
        for name, value in (("event_id", cue.event_id), ("speaker_id", cue.speaker_id)):
            if not isinstance(value, str) or not value or len(value) > 128:
                raise ValueError(f"{name} must be a non-empty string of at most 128 characters")
        if not isinstance(cue.source, CueSource) or not isinstance(cue.intent, CueIntent):
            raise ValueError("source and intent must use their enum values")
        if type(cue.addressed_to_star) is not bool or type(cue.final) is not bool:
            raise ValueError("addressed_to_star and final must be booleans")
        for name, value in (
            ("confidence", cue.confidence),
            ("urgency", cue.urgency),
            ("started_at", cue.started_at),
            ("ended_at", cue.ended_at),
        ):
            if not _finite(value):
                raise ValueError(f"{name} must be finite")
        if not 0.0 <= cue.confidence <= 1.0 or not 0.0 <= cue.urgency <= 1.0:
            raise ValueError("confidence and urgency must be from 0 to 1")
        if cue.ended_at < cue.started_at:
            raise ValueError("ended_at cannot be earlier than started_at")
        if cue.ended_at > now + max_future_skew_seconds:
            raise ValueError("cue ended_at is too far in the future")
        if type(cue.overlap_ms) is not int or not 0 <= cue.overlap_ms <= 60_000:
            raise ValueError("overlap_ms must be an integer from 0 to 60000")
        if not isinstance(decision.action, RoomAction):
            raise ValueError("decision action must be a RoomAction")
        if not isinstance(decision.event_id, str) or not decision.event_id or len(decision.event_id) > 128:
            raise ValueError("decision event_id must be a non-empty string of at most 128 characters")
