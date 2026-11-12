"""Content-free delivery ledger for STAR's user-facing result obligations.

A completed task is not necessarily a communicated result. This bounded,
thread-safe ledger tracks which speech segments have been acknowledged by the
local playback host. It stores opaque identifiers and digests only; it never
stores text, audio, transcripts, viewer identities, or credentials.

A local playback acknowledgement is not proof that a remote viewer heard the
stream. The trusted host remains responsible for authenticating playback
callbacks, stopping audio, and enforcing permissions.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import re
from threading import RLock

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_CLOCK_MS = 10**12
_MAX_RECORDS = 100_000
_MAX_SEGMENTS = 256
_MAX_LEASE_MS = 10 * 60 * 1000
_MAX_PLAYBACK_MS = 60 * 60 * 1000


class DeliveryState(str, Enum):
    READY = "ready"
    CLAIMED = "claimed"
    PLAYING = "playing"
    PARTIAL = "partial"
    FAILED = "failed"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class DeliveryConflict(RuntimeError):
    """A compare-and-swap version or legal-state precondition failed."""


class DeliveryLeaseExpired(RuntimeError):
    """A playback worker lease is stale, expired, or no longer current."""


class DeliveryDeadlineExpired(RuntimeError):
    """The delivery obligation's absolute deadline has passed."""


@dataclass(frozen=True)
class DeliveryLease:
    """Host-internal segment lease; this is not a playback authorization token."""

    delivery_id: str
    version: int
    generation: int
    segment_index: int
    attempt_id: str
    clock_epoch: str
    expires_ms: int


@dataclass(frozen=True)
class DeliveryRecord:
    """Immutable content-free snapshot of one user-facing delivery obligation."""

    delivery_id: str
    task_id: str
    task_version: int
    result_sha256: str
    segment_sha256s: tuple[str, ...]
    completed_segments: int
    state: DeliveryState
    version: int
    generation: int
    created_ms: int
    updated_ms: int
    deadline_ms: int | None = None
    attempt_id: str | None = None
    lease_expires_ms: int | None = None
    active_segment: int | None = None
    playback_id: str | None = None
    last_played_ms: int = 0
    failure_code: str | None = None

    @property
    def segment_count(self) -> int:
        return len(self.segment_sha256s)

    @property
    def remaining_segments(self) -> int:
        return self.segment_count - self.completed_segments


@dataclass(frozen=True)
class DeliveryReapReport:
    expired_deadlines: int


class DeliveryLedger:
    """Thread-safe, bounded ledger for communicating completed task results.

    Each delivery contains an ordered set of content digests representing short
    speech segments. Only a complete, non-interrupted playback acknowledgement
    advances the completed-segment cursor. An interrupted segment is retried
    from its beginning; previously acknowledged segments are never replayed.

    Leases are scoped to a host clock epoch. An expired lease is *not* silently
    requeued: the host must first confirm that its playback worker has stopped,
    otherwise retrying could produce overlapping or duplicate speech. The
    ledger is in-memory; durable crash recovery belongs in a separately
    validated persistence adapter.
    """

    def __init__(
        self,
        *,
        clock_epoch: str,
        max_records: int = 4096,
        max_lease_ms: int = 30_000,
    ) -> None:
        self._identifier(clock_epoch, "clock_epoch")
        if type(max_records) is not int or not 1 <= max_records <= _MAX_RECORDS:
            raise ValueError("max_records must be in 1..100000")
        if type(max_lease_ms) is not int or not 100 <= max_lease_ms <= _MAX_LEASE_MS:
            raise ValueError("max_lease_ms must be in 100..600000")
        self.clock_epoch = clock_epoch
        self.max_records = max_records
        self.max_lease_ms = max_lease_ms
        self._records: dict[str, DeliveryRecord] = {}
        self._last_now_ms: int | None = None
        self._lock = RLock()

    @staticmethod
    def _identifier(value: object, label: str) -> str:
        if type(value) is not str or _ID.fullmatch(value) is None:
            raise ValueError(f"{label} must be a bounded opaque identifier")
        return value

    @staticmethod
    def _digest(value: object, label: str) -> str:
        if type(value) is not str or _SHA256.fullmatch(value) is None:
            raise ValueError(f"{label} must be a lowercase SHA-256 digest")
        return value

    def _now(self, value: object) -> int:
        if type(value) is not int or not 0 <= value <= _MAX_CLOCK_MS:
            raise ValueError("now_ms must be a bounded monotonic millisecond value")
        if self._last_now_ms is not None and value < self._last_now_ms:
            raise ValueError("ledger monotonic clock moved backwards")
        self._last_now_ms = value
        return value

    def _get(self, delivery_id: str) -> DeliveryRecord:
        self._identifier(delivery_id, "delivery_id")
        try:
            return self._records[delivery_id]
        except KeyError as exc:
            raise KeyError("unknown delivery_id") from exc

    @staticmethod
    def _cas(record: DeliveryRecord, expected_version: object) -> None:
        if type(expected_version) is not int or expected_version != record.version:
            raise DeliveryConflict("delivery version changed; refresh the snapshot")

    def _expire_deadline(self, record: DeliveryRecord, now: int) -> DeliveryRecord:
        if (
            record.deadline_ms is not None
            and now >= record.deadline_ms
            and record.state not in (
                DeliveryState.DELIVERED,
                DeliveryState.CANCELLED,
                DeliveryState.EXPIRED,
            )
        ):
            updated = replace(
                record,
                state=DeliveryState.EXPIRED,
                version=record.version + 1,
                updated_ms=now,
                attempt_id=None,
                lease_expires_ms=None,
                active_segment=None,
                playback_id=None,
                failure_code="deadline_expired",
            )
            self._records[record.delivery_id] = updated
            return updated
        return record

    def create(
        self,
        delivery_id: str,
        task_id: str,
        task_version: int,
        result_sha256: str,
        segment_sha256s: tuple[str, ...],
        *,
        now_ms: int,
        deadline_ms: int | None = None,
    ) -> DeliveryRecord:
        """Create an obligation after a caller has verified a task result.

        Repeating the exact same create is idempotent, which makes an
        at-least-once enqueue safe. Reusing an ID for a different contract is
        rejected. The caller must not pass raw speech or media here.
        """
        self._identifier(delivery_id, "delivery_id")
        self._identifier(task_id, "task_id")
        if type(task_version) is not int or task_version < 1:
            raise ValueError("task_version must be a positive integer")
        self._digest(result_sha256, "result_sha256")
        if type(segment_sha256s) is not tuple or not 1 <= len(segment_sha256s) <= _MAX_SEGMENTS:
            raise ValueError("segment_sha256s must be a tuple of 1..256 digests")
        for index, digest in enumerate(segment_sha256s):
            self._digest(digest, f"segment_sha256s[{index}]")
        with self._lock:
            now = self._now(now_ms)
            if deadline_ms is not None:
                if type(deadline_ms) is not int or not now < deadline_ms <= _MAX_CLOCK_MS:
                    raise ValueError("deadline_ms must be after now_ms")
            existing = self._records.get(delivery_id)
            if existing is not None:
                same_contract = (
                    existing.task_id == task_id
                    and existing.task_version == task_version
                    and existing.result_sha256 == result_sha256
                    and existing.segment_sha256s == segment_sha256s
                    and existing.deadline_ms == deadline_ms
                )
                if same_contract:
                    return existing
                raise DeliveryConflict("delivery IDs cannot be reused for another contract")
            if len(self._records) >= self.max_records:
                raise OverflowError("delivery ledger capacity reached; rotate after review")
            record = DeliveryRecord(
                delivery_id=delivery_id,
                task_id=task_id,
                task_version=task_version,
                result_sha256=result_sha256,
                segment_sha256s=segment_sha256s,
                completed_segments=0,
                state=DeliveryState.READY,
                version=1,
                generation=0,
                created_ms=now,
                updated_ms=now,
                deadline_ms=deadline_ms,
            )
            self._records[delivery_id] = record
            return record

    def claim(
        self,
        delivery_id: str,
        expected_version: int,
        attempt_id: str,
        *,
        now_ms: int,
        lease_ms: int | None = None,
    ) -> DeliveryLease:
        """Claim the next unacknowledged segment for one playback worker."""
        self._identifier(attempt_id, "attempt_id")
        with self._lock:
            now = self._now(now_ms)
            record = self._get(delivery_id)
            self._cas(record, expected_version)
            record = self._expire_deadline(record, now)
            if record.state is DeliveryState.EXPIRED:
                raise DeliveryDeadlineExpired("delivery deadline has expired")
            if record.state not in (
                DeliveryState.READY, DeliveryState.PARTIAL, DeliveryState.FAILED
            ):
                raise DeliveryConflict("delivery is not ready for another segment attempt")
            if record.completed_segments >= record.segment_count:
                raise DeliveryConflict("delivery has no remaining segments")
            duration = self.max_lease_ms if lease_ms is None else lease_ms
            if type(duration) is not int or not 100 <= duration <= self.max_lease_ms:
                raise ValueError("lease_ms must be in 100..max_lease_ms")
            expires = now + duration
            if record.deadline_ms is not None:
                expires = min(expires, record.deadline_ms)
            if expires <= now:
                raise DeliveryDeadlineExpired("delivery deadline leaves no lease time")
            claimed = replace(
                record,
                state=DeliveryState.CLAIMED,
                version=record.version + 1,
                generation=record.generation + 1,
                updated_ms=now,
                attempt_id=attempt_id,
                lease_expires_ms=expires,
                active_segment=record.completed_segments,
                playback_id=None,
                last_played_ms=0,
                failure_code=None,
            )
            self._records[delivery_id] = claimed
            return DeliveryLease(
                delivery_id, claimed.version, claimed.generation,
                claimed.completed_segments, attempt_id, self.clock_epoch, expires,
            )

    def _current_lease(
        self,
        lease: DeliveryLease,
        now: int,
        *,
        allowed_states: tuple[DeliveryState, ...],
    ) -> DeliveryRecord:
        if not isinstance(lease, DeliveryLease):
            raise TypeError("expected DeliveryLease")
        if lease.clock_epoch != self.clock_epoch:
            raise DeliveryLeaseExpired("lease belongs to another host clock epoch")
        record = self._get(lease.delivery_id)
        if (
            record.state not in allowed_states
            or record.version != lease.version
            or record.generation != lease.generation
            or record.active_segment != lease.segment_index
            or record.attempt_id != lease.attempt_id
            or record.lease_expires_ms != lease.expires_ms
        ):
            raise DeliveryLeaseExpired("playback lease is no longer current")
        record = self._expire_deadline(record, now)
        if record.state is DeliveryState.EXPIRED:
            raise DeliveryDeadlineExpired("delivery deadline expired before playback update")
        if record.lease_expires_ms is None or now >= record.lease_expires_ms:
            raise DeliveryLeaseExpired("playback lease expired")
        return record

    def start_playback(
        self,
        lease: DeliveryLease,
        playback_id: str,
        *,
        now_ms: int,
    ) -> DeliveryLease:
        """Record the host's playback-start event and return the new lease version."""
        self._identifier(playback_id, "playback_id")
        with self._lock:
            now = self._now(now_ms)
            record = self._current_lease(lease, now, allowed_states=(DeliveryState.CLAIMED,))
            playing = replace(
                record,
                state=DeliveryState.PLAYING,
                version=record.version + 1,
                updated_ms=now,
                playback_id=playback_id,
            )
            self._records[record.delivery_id] = playing
            return DeliveryLease(
                playing.delivery_id, playing.version, playing.generation,
                lease.segment_index, lease.attempt_id, self.clock_epoch,
                lease.expires_ms,
            )

    def acknowledge_playback(
        self,
        lease: DeliveryLease,
        playback_id: str,
        *,
        played_ms: int,
        duration_ms: int,
        interrupted: bool,
        now_ms: int,
        completion_tolerance_ms: int = 0,
    ) -> DeliveryRecord:
        """Apply one trusted local playback-finished receipt.

        A segment advances only when playback was not interrupted and the host
        reports that its playback position reached the duration (within the
        explicit tolerance). Partial or interrupted segments remain pending and
        are retried from their beginning. This confirms local output completion,
        not that a remote audience member heard the stream.
        """
        self._identifier(playback_id, "playback_id")
        for name, value in (("played_ms", played_ms), ("duration_ms", duration_ms)):
            if type(value) is not int or not 0 <= value <= _MAX_PLAYBACK_MS:
                raise ValueError(f"{name} must be a bounded nonnegative integer")
        if duration_ms < 1:
            raise ValueError("duration_ms must be positive")
        if type(interrupted) is not bool:
            raise ValueError("interrupted must be a boolean")
        if type(completion_tolerance_ms) is not int or not 0 <= completion_tolerance_ms <= 5_000:
            raise ValueError("completion_tolerance_ms must be in 0..5000")
        if completion_tolerance_ms > duration_ms // 2:
            raise ValueError("completion tolerance cannot exceed half the segment duration")
        if played_ms > duration_ms + completion_tolerance_ms:
            raise ValueError("played_ms exceeds duration and tolerance")
        with self._lock:
            now = self._now(now_ms)
            record = self._current_lease(lease, now, allowed_states=(DeliveryState.PLAYING,))
            if record.playback_id != playback_id:
                raise DeliveryLeaseExpired("playback receipt does not match active playback")
            complete = not interrupted and played_ms >= duration_ms - completion_tolerance_ms
            completed_segments = record.completed_segments + (1 if complete else 0)
            state = (
                DeliveryState.DELIVERED
                if completed_segments == record.segment_count
                else DeliveryState.READY if complete else DeliveryState.PARTIAL
            )
            updated = replace(
                record,
                state=state,
                version=record.version + 1,
                updated_ms=now,
                completed_segments=completed_segments,
                attempt_id=None,
                lease_expires_ms=None,
                active_segment=None,
                playback_id=None,
                last_played_ms=played_ms,
                failure_code=None,
            )
            self._records[record.delivery_id] = updated
            return updated

    def fail(
        self,
        lease: DeliveryLease,
        failure_code: str,
        *,
        now_ms: int,
        host_confirmed_stopped: bool = False,
    ) -> DeliveryRecord:
        """Mark an attempt failed; playing audio requires host stop confirmation."""
        self._identifier(failure_code, "failure_code")
        with self._lock:
            now = self._now(now_ms)
            record = self._current_lease(
                lease, now, allowed_states=(DeliveryState.CLAIMED, DeliveryState.PLAYING)
            )
            if record.state is DeliveryState.PLAYING and host_confirmed_stopped is not True:
                raise PermissionError("host must confirm playback stopped before retry")
            failed = replace(
                record,
                state=DeliveryState.FAILED,
                version=record.version + 1,
                updated_ms=now,
                attempt_id=None,
                lease_expires_ms=None,
                active_segment=None,
                playback_id=None,
                failure_code=failure_code,
            )
            self._records[record.delivery_id] = failed
            return failed

    def recover_expired_lease(
        self,
        lease: DeliveryLease,
        *,
        now_ms: int,
        host_confirmed_stopped: bool,
    ) -> DeliveryRecord:
        """Release an expired lease only after the host proves playback stopped."""
        if host_confirmed_stopped is not True:
            raise PermissionError("host stop confirmation is required before lease recovery")
        with self._lock:
            now = self._now(now_ms)
            if not isinstance(lease, DeliveryLease):
                raise TypeError("expected DeliveryLease")
            if lease.clock_epoch != self.clock_epoch:
                raise DeliveryLeaseExpired("lease belongs to another host clock epoch")
            record = self._get(lease.delivery_id)
            if (
                record.state not in (DeliveryState.CLAIMED, DeliveryState.PLAYING)
                or record.version != lease.version
                or record.generation != lease.generation
                or record.active_segment != lease.segment_index
                or record.attempt_id != lease.attempt_id
                or record.lease_expires_ms != lease.expires_ms
            ):
                raise DeliveryLeaseExpired("playback lease is no longer current")
            if now < lease.expires_ms:
                raise DeliveryConflict("playback lease has not expired")
            record = self._expire_deadline(record, now)
            if record.state is DeliveryState.EXPIRED:
                raise DeliveryDeadlineExpired("delivery deadline expired before lease recovery")
            recovered = replace(
                record,
                state=(
                    DeliveryState.PARTIAL
                    if record.state is DeliveryState.PLAYING
                    else DeliveryState.READY
                ),
                version=record.version + 1,
                updated_ms=now,
                attempt_id=None,
                lease_expires_ms=None,
                active_segment=None,
                playback_id=None,
                failure_code="lease_recovered",
            )
            self._records[record.delivery_id] = recovered
            return recovered

    def cancel(
        self,
        delivery_id: str,
        expected_version: int,
        *,
        now_ms: int,
        host_confirmed_stopped: bool = False,
    ) -> DeliveryRecord:
        """Explicitly cancel an obligation; active playback must first be stopped."""
        with self._lock:
            now = self._now(now_ms)
            record = self._get(delivery_id)
            self._cas(record, expected_version)
            record = self._expire_deadline(record, now)
            if record.state is DeliveryState.EXPIRED:
                raise DeliveryDeadlineExpired("delivery deadline has expired")
            if record.state is DeliveryState.DELIVERED:
                raise DeliveryConflict("delivered obligations cannot be cancelled")
            if record.state is DeliveryState.CANCELLED:
                raise DeliveryConflict("delivery is already cancelled")
            if record.state is DeliveryState.PLAYING and host_confirmed_stopped is not True:
                raise PermissionError("host must confirm playback stopped before cancellation")
            cancelled = replace(
                record,
                state=DeliveryState.CANCELLED,
                version=record.version + 1,
                updated_ms=now,
                attempt_id=None,
                lease_expires_ms=None,
                active_segment=None,
                playback_id=None,
                failure_code="cancelled",
            )
            self._records[delivery_id] = cancelled
            return cancelled

    def reap(self, *, now_ms: int) -> DeliveryReapReport:
        """Expire overdue obligations; never requeue a possibly active audio worker."""
        with self._lock:
            now = self._now(now_ms)
            expired = 0
            for delivery_id, record in tuple(self._records.items()):
                before = record.version
                updated = self._expire_deadline(record, now)
                if updated.version != before:
                    expired += 1
            return DeliveryReapReport(expired_deadlines=expired)

    def get(self, delivery_id: str) -> DeliveryRecord:
        """Return an immutable snapshot for one delivery obligation."""
        with self._lock:
            return self._get(delivery_id)

    def outstanding(self, *, limit: int = 1000) -> tuple[DeliveryRecord, ...]:
        """Return oldest unfulfilled obligations without exposing payload content."""
        if type(limit) is not int or not 1 <= limit <= 10_000:
            raise ValueError("limit must be in 1..10000")
        with self._lock:
            rows = (
                record for record in self._records.values()
                if record.state not in (
                    DeliveryState.DELIVERED,
                    DeliveryState.CANCELLED,
                    DeliveryState.EXPIRED,
                )
            )
            return tuple(sorted(rows, key=lambda row: (row.created_ms, row.delivery_id))[:limit])
