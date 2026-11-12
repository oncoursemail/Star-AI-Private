"""Versioned, bounded coordination ledger for STAR's concurrent subsystems.

The ledger coordinates task intent and result freshness. It does not execute or
terminate processes, authorize tools, persist prompts, control playback, or
prove that a worker actually stopped. The trusted host owns those operations.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from enum import Enum
import re
from threading import RLock

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_MAX_CLOCK_MS = 10**12
_MAX_RECORDS = 100_000
_MAX_LEASE_MS = 10 * 60 * 1000


class TaskState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class TaskConflict(RuntimeError):
    """A compare-and-swap version or legal-state precondition failed."""


class TaskLeaseExpired(RuntimeError):
    """A worker lease is stale, expired, or no longer current."""


class TaskDeadlineExpired(RuntimeError):
    """The task deadline passed before the requested transition."""


@dataclass(frozen=True)
class TaskLease:
    """Host-internal attempt handle; not an authorization credential."""

    task_id: str
    version: int
    attempt_id: str
    clock_epoch: str
    expires_ms: int


@dataclass(frozen=True)
class TaskRecord:
    """Content-free task metadata; only digests and bounded identifiers persist."""

    task_id: str
    domain: str
    state: TaskState
    version: int
    spec_sha256: str
    created_ms: int
    updated_ms: int
    deadline_ms: int | None = None
    attempt_id: str | None = None
    lease_expires_ms: int | None = None
    result_sha256: str | None = None
    failure_code: str | None = None


@dataclass(frozen=True)
class ReapReport:
    requeued_leases: int
    expired_deadlines: int


class TaskLedger:
    """Thread-safe compare-and-swap task lifecycle ledger.

    Each mutation advances a task version. A claimed worker receives the
    version and attempt ID that must still be current when it commits. Cancel,
    refine, lease expiry, or deadline expiry invalidates the old lease, so a
    late worker cannot overwrite a newer decision.

    The ledger is deliberately in-memory and bounded. Do not serialize raw
    monotonic timestamps across process restarts; create a fresh ledger with a
    new clock epoch and restore only separately validated durable checkpoints.
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
        self._records: dict[str, TaskRecord] = {}
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

    def _get(self, task_id: str) -> TaskRecord:
        self._identifier(task_id, "task_id")
        try:
            return self._records[task_id]
        except KeyError as exc:
            raise KeyError("unknown task_id") from exc

    @staticmethod
    def _cas(record: TaskRecord, expected_version: object) -> None:
        if type(expected_version) is not int or expected_version != record.version:
            raise TaskConflict("task version changed; refresh the snapshot")

    def _expire_deadline(self, record: TaskRecord, now: int) -> TaskRecord:
        if (record.deadline_ms is not None and now >= record.deadline_ms
                and record.state in (
                    TaskState.QUEUED, TaskState.RUNNING,
                    TaskState.FAILED, TaskState.CANCELLED,
                )):
            updated = replace(
                record,
                state=TaskState.EXPIRED,
                version=record.version + 1,
                updated_ms=now,
                attempt_id=None,
                lease_expires_ms=None,
                failure_code="deadline_expired",
            )
            self._records[record.task_id] = updated
            return updated
        return record

    def create(
        self,
        task_id: str,
        domain: str,
        spec_sha256: str,
        *,
        now_ms: int,
        deadline_ms: int | None = None,
    ) -> TaskRecord:
        self._identifier(task_id, "task_id")
        self._identifier(domain, "domain")
        self._digest(spec_sha256, "spec_sha256")
        with self._lock:
            now = self._now(now_ms)
            if deadline_ms is not None:
                if type(deadline_ms) is not int or not now < deadline_ms <= _MAX_CLOCK_MS:
                    raise ValueError("deadline_ms must be after now_ms")
            if task_id in self._records:
                raise TaskConflict("task IDs cannot be reused within a ledger epoch")
            if len(self._records) >= self.max_records:
                raise OverflowError("task ledger capacity reached; rotate after review")
            record = TaskRecord(
                task_id=task_id,
                domain=domain,
                state=TaskState.QUEUED,
                version=1,
                spec_sha256=spec_sha256,
                created_ms=now,
                updated_ms=now,
                deadline_ms=deadline_ms,
            )
            self._records[task_id] = record
            return record

    def claim(
        self,
        task_id: str,
        expected_version: int,
        attempt_id: str,
        *,
        now_ms: int,
        lease_ms: int | None = None,
    ) -> TaskLease:
        self._identifier(attempt_id, "attempt_id")
        with self._lock:
            now = self._now(now_ms)
            record = self._get(task_id)
            self._cas(record, expected_version)
            record = self._expire_deadline(record, now)
            if record.state is TaskState.EXPIRED:
                raise TaskDeadlineExpired("task deadline has expired")
            if record.state is not TaskState.QUEUED:
                raise TaskConflict("only queued tasks can be claimed")
            duration = self.max_lease_ms if lease_ms is None else lease_ms
            if type(duration) is not int or not 100 <= duration <= self.max_lease_ms:
                raise ValueError("lease_ms must be in 100..max_lease_ms")
            expires = now + duration
            if record.deadline_ms is not None:
                expires = min(expires, record.deadline_ms)
            claimed = replace(
                record,
                state=TaskState.RUNNING,
                version=record.version + 1,
                updated_ms=now,
                attempt_id=attempt_id,
                lease_expires_ms=expires,
                result_sha256=None,
                failure_code=None,
            )
            self._records[task_id] = claimed
            return TaskLease(task_id, claimed.version, attempt_id, self.clock_epoch, expires)

    def _current_lease(self, lease: TaskLease, now: int) -> TaskRecord:
        if not isinstance(lease, TaskLease):
            raise TypeError("expected TaskLease")
        if lease.clock_epoch != self.clock_epoch:
            raise TaskLeaseExpired("lease belongs to another host clock epoch")
        record = self._get(lease.task_id)
        if (record.state is not TaskState.RUNNING
                or record.version != lease.version
                or record.attempt_id != lease.attempt_id
                or record.lease_expires_ms != lease.expires_ms):
            raise TaskLeaseExpired("worker lease is no longer current")
        record = self._expire_deadline(record, now)
        if record.state is TaskState.EXPIRED:
            raise TaskDeadlineExpired("task deadline expired before worker commit")
        if record.lease_expires_ms is None or now >= record.lease_expires_ms:
            raise TaskLeaseExpired("worker lease expired")
        return record

    def renew(self, lease: TaskLease, *, now_ms: int, lease_ms: int | None = None) -> TaskLease:
        with self._lock:
            now = self._now(now_ms)
            record = self._current_lease(lease, now)
            duration = self.max_lease_ms if lease_ms is None else lease_ms
            if type(duration) is not int or not 100 <= duration <= self.max_lease_ms:
                raise ValueError("lease_ms must be in 100..max_lease_ms")
            expires = now + duration
            if record.deadline_ms is not None:
                expires = min(expires, record.deadline_ms)
            if expires <= now:
                raise TaskDeadlineExpired("task deadline leaves no lease time")
            updated = replace(record, updated_ms=now, lease_expires_ms=expires)
            self._records[record.task_id] = updated
            return TaskLease(updated.task_id, updated.version, lease.attempt_id,
                             self.clock_epoch, expires)

    def complete(self, lease: TaskLease, result_sha256: str, *, now_ms: int) -> TaskRecord:
        self._digest(result_sha256, "result_sha256")
        with self._lock:
            now = self._now(now_ms)
            record = self._current_lease(lease, now)
            completed = replace(
                record,
                state=TaskState.COMPLETED,
                version=record.version + 1,
                updated_ms=now,
                attempt_id=None,
                lease_expires_ms=None,
                result_sha256=result_sha256,
                failure_code=None,
            )
            self._records[record.task_id] = completed
            return completed

    def fail(self, lease: TaskLease, failure_code: str, *, now_ms: int) -> TaskRecord:
        self._identifier(failure_code, "failure_code")
        with self._lock:
            now = self._now(now_ms)
            record = self._current_lease(lease, now)
            failed = replace(
                record,
                state=TaskState.FAILED,
                version=record.version + 1,
                updated_ms=now,
                attempt_id=None,
                lease_expires_ms=None,
                result_sha256=None,
                failure_code=failure_code,
            )
            self._records[record.task_id] = failed
            return failed

    def cancel(self, task_id: str, expected_version: int, *, now_ms: int) -> TaskRecord:
        with self._lock:
            now = self._now(now_ms)
            record = self._get(task_id)
            self._cas(record, expected_version)
            record = self._expire_deadline(record, now)
            if record.state is TaskState.EXPIRED:
                raise TaskDeadlineExpired("task deadline has expired")
            if record.state not in (TaskState.QUEUED, TaskState.RUNNING):
                raise TaskConflict("only queued or running tasks can be cancelled")
            cancelled = replace(
                record,
                state=TaskState.CANCELLED,
                version=record.version + 1,
                updated_ms=now,
                attempt_id=None,
                lease_expires_ms=None,
                failure_code=None,
            )
            self._records[task_id] = cancelled
            return cancelled

    def refine(
        self,
        task_id: str,
        expected_version: int,
        new_spec_sha256: str,
        *,
        now_ms: int,
    ) -> TaskRecord:
        self._digest(new_spec_sha256, "new_spec_sha256")
        with self._lock:
            now = self._now(now_ms)
            record = self._get(task_id)
            self._cas(record, expected_version)
            if record.state not in (
                TaskState.QUEUED, TaskState.RUNNING, TaskState.FAILED, TaskState.CANCELLED
            ):
                raise TaskConflict("completed or expired tasks cannot be refined in place")
            if record.deadline_ms is not None and now >= record.deadline_ms:
                expired = self._expire_deadline(record, now)
                if expired.state is TaskState.EXPIRED:
                    raise TaskDeadlineExpired("task deadline has expired")
            refined = replace(
                record,
                state=TaskState.QUEUED,
                version=record.version + 1,
                spec_sha256=new_spec_sha256,
                updated_ms=now,
                attempt_id=None,
                lease_expires_ms=None,
                result_sha256=None,
                failure_code=None,
            )
            self._records[task_id] = refined
            return refined

    def reap(self, *, now_ms: int) -> ReapReport:
        """Expire deadlines and requeue abandoned worker leases, invalidating old handles."""
        with self._lock:
            now = self._now(now_ms)
            requeued = 0
            expired = 0
            for task_id, record in tuple(self._records.items()):
                if record.state not in (
                    TaskState.QUEUED, TaskState.RUNNING,
                    TaskState.FAILED, TaskState.CANCELLED,
                ):
                    continue
                if record.deadline_ms is not None and now >= record.deadline_ms:
                    self._records[task_id] = replace(
                        record,
                        state=TaskState.EXPIRED,
                        version=record.version + 1,
                        updated_ms=now,
                        attempt_id=None,
                        lease_expires_ms=None,
                        failure_code="deadline_expired",
                    )
                    expired += 1
                elif (record.state is TaskState.RUNNING
                      and record.lease_expires_ms is not None
                      and now >= record.lease_expires_ms):
                    self._records[task_id] = replace(
                        record,
                        state=TaskState.QUEUED,
                        version=record.version + 1,
                        updated_ms=now,
                        attempt_id=None,
                        lease_expires_ms=None,
                        failure_code="lease_expired",
                    )
                    requeued += 1
            return ReapReport(requeued, expired)

    def get(self, task_id: str) -> TaskRecord:
        with self._lock:
            return self._get(task_id)

    def snapshot(self) -> tuple[TaskRecord, ...]:
        with self._lock:
            return tuple(self._records.values())

    def counts(self) -> dict[str, int]:
        with self._lock:
            counts = Counter(record.state.value for record in self._records.values())
            return {state.value: counts.get(state.value, 0) for state in TaskState}


__all__ = [
    "TaskState", "TaskLease", "TaskRecord", "ReapReport",
    "TaskConflict", "TaskLeaseExpired", "TaskDeadlineExpired", "TaskLedger",
]
