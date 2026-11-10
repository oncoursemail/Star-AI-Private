"""Deadline-aware, bounded dispatch for STAR's live and background inference work.

This is a host-side *control-plane queue*. It orders already-authorized
InferenceJob metadata and asks StreamBrainGovernor for a one-shot lease. It
never executes a model, starts/stops a process, controls a game, captures media,
plays audio, changes OS priority, or grants a tool permission.

The host remains responsible for launching only its fixed approved worker,
rechecking the exact event/frame before launch, and acknowledging physical
worker termination through StreamBrainGovernor.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import math
import re
from threading import RLock
import time
from typing import Callable

from .stream_brain_governor import BrainAdmission, BrainLease
from .stream_qos import InferenceJob

_CLOCK_MAX = 1e13
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
_PRIORITIES = {
    "speech": 100,
    "vision": 90,
    "commentary": 70,
    "research": 30,
    "training": 20,
    "render": 10,
}
_BACKGROUND = frozenset({"research", "training", "render"})
_COALESCIBLE = frozenset({"vision", "commentary", "research", "training", "render"})
_PERMANENT_ADMISSION_FAILURES = frozenset({
    "job_clock_or_deadline_invalid",
    "job_stale",
    "duplicate_one_shot_job_id",
    "bounded_session_limit_reached",
})


def _clock_ms(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("now_ms must be a finite monotonic timestamp")
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= _CLOCK_MAX:
        raise ValueError("now_ms must be a finite monotonic timestamp")
    return number


@dataclass(frozen=True)
class DispatchPolicy:
    """Small fixed policy; these are scheduling weights, not model priorities."""

    max_queue: int = 64
    max_seen_ids: int = 4096
    max_per_kind: int = 32
    max_queue_age_ms: int = 120_000
    aging_interval_ms: int = 5_000
    max_background_aging_boost: int = 30
    max_admission_attempts: int = 4

    def __post_init__(self) -> None:
        for name, low, high in (
            ("max_queue", 1, 4096),
            ("max_seen_ids", 64, 100_000),
            ("max_per_kind", 1, 4096),
            ("max_queue_age_ms", 100, 120_000),
            ("aging_interval_ms", 100, 60_000),
            ("max_background_aging_boost", 0, 30),
            ("max_admission_attempts", 1, 16),
        ):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"invalid {name}")
        if self.max_seen_ids < self.max_queue:
            raise ValueError("max_seen_ids must be at least max_queue")


@dataclass(frozen=True)
class SubmitResult:
    accepted: bool
    reason: str
    queue_depth: int
    replaced_queued_work: bool = False


@dataclass(frozen=True)
class DispatchResult:
    status: str  # admitted | deferred | idle | busy
    reason: str
    job: InferenceJob | None = None
    admission: BrainAdmission | None = None
    attempted: int = 0
    expired: int = 0


@dataclass(frozen=True)
class _Queued:
    job: InferenceJob
    queued_ms: float
    sequence: int
    coalesce_key: tuple[str, str] | None
    attempts: int = 0
    retry_after_ms: float = 0.0


class StreamWorkDispatcher:
    """Priority/deadline queue in front of an existing governor's `admit`.

    Construct with `admit=stream_brain_governor.admit`. The callback must be
    fast, synchronous, and return the real BrainAdmission from that governor.
    It must not perform network/model/OS work.
    """

    def __init__(
        self,
        *,
        admit: Callable[[InferenceJob], BrainAdmission],
        policy: DispatchPolicy | None = None,
        clock_ms: Callable[[], float] = lambda: time.monotonic() * 1000,
    ) -> None:
        if not callable(admit) or not callable(clock_ms):
            raise TypeError("admit and clock_ms must be callable")
        if policy is not None and type(policy) is not DispatchPolicy:
            raise TypeError("policy must be DispatchPolicy")
        self.policy = policy if policy is not None else DispatchPolicy()
        self._admit = admit
        self._clock = clock_ms
        self._lock = RLock()
        self._queue: dict[str, _Queued] = {}
        self._coalesce_index: dict[tuple[str, str], str] = {}
        self._seen_ids: set[str] = set()
        self._sequence = 0
        self._last_now_ms: float | None = None
        self._dispatching_id: str | None = None
        self._counts = Counter()

    def _advance(self, value: object) -> float:
        now = _clock_ms(value)
        if self._last_now_ms is not None and now < self._last_now_ms:
            raise ValueError("dispatcher monotonic clock regressed")
        self._last_now_ms = now
        return now

    def _remove(self, job_id: str) -> _Queued | None:
        item = self._queue.pop(job_id, None)
        if item is not None and item.coalesce_key is not None:
            if self._coalesce_index.get(item.coalesce_key) == job_id:
                self._coalesce_index.pop(item.coalesce_key, None)
        return item

    def _expire(self, now: float) -> int:
        expired = [
            job_id for job_id, item in self._queue.items()
            if job_id != self._dispatching_id
            and (now >= item.job.deadline_ms
                 or now - item.queued_ms > self.policy.max_queue_age_ms)
        ]
        for job_id in expired:
            self._remove(job_id)
        self._counts["expired"] += len(expired)
        return len(expired)

    def submit(
        self,
        job: InferenceJob,
        *,
        now_ms: float | None = None,
        coalesce_key: str | None = None,
    ) -> SubmitResult:
        """Queue metadata only. Speech is deliberately never coalesced."""
        if not isinstance(job, InferenceJob):
            raise TypeError("job must be InferenceJob")
        if coalesce_key is not None:
            if job.kind not in _COALESCIBLE:
                raise ValueError("this workload kind cannot be coalesced")
            if type(coalesce_key) is not str or not _KEY.fullmatch(coalesce_key):
                raise ValueError("coalesce_key must be a short opaque identifier")
        with self._lock:
            now = self._advance(self._clock() if now_ms is None else now_ms)
            self._expire(now)
            if job.job_id in self._seen_ids:
                self._counts["duplicate"] += 1
                return SubmitResult(False, "duplicate_job_id", len(self._queue))
            if len(self._seen_ids) >= self.policy.max_seen_ids:
                self._counts["rejected"] += 1
                return SubmitResult(False, "session_id_limit", len(self._queue))
            if (job.created_ms > now + 20
                    or now - job.created_ms > self.policy.max_queue_age_ms
                    or job.deadline_ms <= now):
                self._counts["stale"] += 1
                self._seen_ids.add(job.job_id)
                return SubmitResult(False, "stale_or_invalid_deadline", len(self._queue))
            key = (job.kind, coalesce_key) if coalesce_key is not None else None
            replaced = False
            if key is not None:
                old_id = self._coalesce_index.get(key)
                old = self._queue.get(old_id) if old_id is not None else None
                if old is not None:
                    if job.created_ms <= old.job.created_ms:
                        self._seen_ids.add(job.job_id)
                        self._counts["stale_coalesced"] += 1
                        return SubmitResult(False, "older_than_queued_replacement", len(self._queue))
                    # Never pretend to cancel an item currently crossing the
                    # admission boundary. Keep the newer item queued behind it.
                    if old_id != self._dispatching_id:
                        self._remove(old_id)
                        replaced = True
                        self._counts["coalesced"] += 1
            if len(self._queue) >= self.policy.max_queue:
                self._counts["rejected"] += 1
                return SubmitResult(False, "queue_full", len(self._queue))
            same_kind = sum(item.job.kind == job.kind for item in self._queue.values())
            if same_kind >= self.policy.max_per_kind:
                self._counts["rejected"] += 1
                return SubmitResult(False, "kind_queue_limit", len(self._queue))
            self._sequence += 1
            self._queue[job.job_id] = _Queued(job, now, self._sequence, key)
            if key is not None:
                self._coalesce_index[key] = job.job_id
            self._seen_ids.add(job.job_id)
            self._counts["submitted"] += 1
            return SubmitResult(True, "queued", len(self._queue), replaced)

    def cancel_queued(self, job_id: str) -> bool:
        """Remove pending work only; cannot cancel or release a running lease."""
        if type(job_id) is not str:
            raise TypeError("job_id must be a string")
        with self._lock:
            if job_id == self._dispatching_id:
                return False
            removed = self._remove(job_id)
            if removed is None:
                return False
            self._counts["cancelled"] += 1
            return True

    def _sort_key(self, item: _Queued, now: float) -> tuple[float, float, int]:
        kind = item.job.kind
        priority = _PRIORITIES[kind]
        if kind in _BACKGROUND:
            age = max(0.0, now - item.queued_ms)
            boost = min(
                self.policy.max_background_aging_boost,
                int(age // self.policy.aging_interval_ms),
            )
            priority += boost
        # Class priority protects interactive work. Within a class, earliest
        # deadline wins, then FIFO sequence provides deterministic tie-breaking.
        return (-priority, item.job.deadline_ms, item.sequence)

    def _defer(self, item: _Queued, now: float) -> None:
        """Back off transient failures so a blocked head cannot starve the queue."""
        attempts = item.attempts + 1
        delay_ms = min(1000.0, 50.0 * (2 ** min(item.attempts, 4)))
        retry_base = max(now, self._last_now_ms if self._last_now_ms is not None else now)
        self._queue[item.job.job_id] = _Queued(
            item.job, item.queued_ms, item.sequence, item.coalesce_key,
            attempts, retry_base + delay_ms,
        )

    def dispatch(self, *, now_ms: float | None = None) -> DispatchResult:
        """Try a bounded number of candidates and return at most one real lease."""
        with self._lock:
            now = self._advance(self._clock() if now_ms is None else now_ms)
            expired = self._expire(now)
            if self._dispatching_id is not None:
                self._counts["busy"] += 1
                return DispatchResult("busy", "admission_in_progress", expired=expired)

        attempted_ids: set[str] = set()
        last_reason = "no_admissible_candidate"
        attempts = 0
        while attempts < self.policy.max_admission_attempts:
            with self._lock:
                candidates = [
                    item for item in self._queue.values()
                    if item.job.job_id not in attempted_ids and item.retry_after_ms <= now
                ]
                if not candidates:
                    if self._queue:
                        last_reason = "retry_backoff"
                    break
                item = min(candidates, key=lambda row: self._sort_key(row, now))
                job_id = item.job.job_id
                self._dispatching_id = job_id
                attempted_ids.add(job_id)
            try:
                admission = self._admit(item.job)
                if not isinstance(admission, BrainAdmission):
                    raise TypeError("admission callback returned an invalid result")
                if admission.admitted and not isinstance(admission.lease, BrainLease):
                    raise TypeError("admitted work must carry the governor's real BrainLease")
            except Exception:
                with self._lock:
                    self._dispatching_id = None
                    if (item.coalesce_key is not None
                            and self._coalesce_index.get(item.coalesce_key) != job_id):
                        self._remove(job_id)
                        self._counts["coalesced_superseded"] += 1
                    else:
                        self._defer(item, now)
                    self._counts["adapter_errors"] += 1
                return DispatchResult(
                    "deferred", "admission_adapter_error",
                    attempted=attempts + 1, expired=expired,
                )
            attempts += 1
            with self._lock:
                self._dispatching_id = None
                if admission.admitted:
                    self._remove(job_id)
                    self._counts["admitted"] += 1
                    return DispatchResult(
                        "admitted", admission.reason, item.job, admission,
                        attempted=attempts, expired=expired,
                    )
                last_reason = admission.reason
                if admission.reason in _PERMANENT_ADMISSION_FAILURES:
                    self._remove(job_id)
                    self._counts["permanent_reject"] += 1
                elif (item.coalesce_key is not None
                      and self._coalesce_index.get(item.coalesce_key) != job_id):
                    # A newer item arrived while this one crossed the
                    # admission boundary. If the old item was not admitted,
                    # discard it and preserve latest-wins semantics.
                    self._remove(job_id)
                    self._counts["coalesced_superseded"] += 1
                else:
                    self._defer(item, now)
                    self._counts["deferred"] += 1

        with self._lock:
            if not self._queue:
                status = "idle"
                reason = "queue_empty"
            else:
                status = "deferred"
                reason = last_reason
            return DispatchResult(
                status, reason, attempted=attempts, expired=expired,
            )

    def status(self, *, now_ms: float | None = None) -> dict[str, object]:
        """Aggregate-only health; never returns job IDs, coalesce keys or payloads."""
        with self._lock:
            now = self._advance(self._clock() if now_ms is None else now_ms)
            self._expire(now)
            by_kind = Counter(item.job.kind for item in self._queue.values())
            backing_off = sum(item.retry_after_ms > now for item in self._queue.values())
            oldest = max((now - item.queued_ms for item in self._queue.values()), default=0.0)
            return {
                **dict(self._counts),
                "queued": len(self._queue),
                "queued_by_kind": dict(sorted(by_kind.items())),
                "backoff_queued": backing_off,
                "oldest_age_ms": round(oldest, 2),
                "seen_ids": len(self._seen_ids),
                "dispatch_in_progress": self._dispatching_id is not None,
                "priority_policy": dict(_PRIORITIES),
                "background_aging_max": self.policy.max_background_aging_boost,
            }


__all__ = [
    "DispatchPolicy", "SubmitResult", "DispatchResult", "StreamWorkDispatcher",
]
