"""One-shot, epoch-bound output receipts for an opt-in AI gaming VTuber.

A worker may finish producing a sentence *after* a restart, interruption, or
deadline. It must not be played merely because generation completed. This
bounded, in-memory host helper links a scheduler admission to the worker epoch
that produced it and rechecks that epoch at the final output boundary.

This is NOT an audio player, an OS process verifier, a QoS scheduler, or an
authorization to speak/stream. The trusted Windows host must independently
check actual process liveness, audio device, current game context, turn-taking
and preplay evidence; model/chat/viewer input must never call this API.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from threading import RLock

from .stream_host_worker_epochs import HostWorkerEpoch, HostWorkerEpochRegistry
from .stream_qos import InferenceJob, QoSDecision

_MAX_CLOCK_MS = 1e13
_OUTPUT_KINDS = frozenset({"speech", "commentary", "vision"})


def _clock(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("trusted monotonic clock required")
    try:
        now = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError("invalid host clock") from exc
    if not math.isfinite(now) or not 0 <= now <= _MAX_CLOCK_MS:
        raise ValueError("invalid host clock")
    return now


@dataclass(frozen=True)
class HostReplyPermit:
    """Opaque one-shot reference. Not a credential or permission to emit."""

    serial: int
    kind: str
    route_profile: str
    deadline_ms: float


@dataclass(frozen=True)
class HostReplyAdvice:
    eligible: bool
    reason: str
    authorizes_audio: bool = False
    authorizes_broadcast: bool = False


class HostWorkerReplyFence:
    """Prevent delayed old-worker content from entering the playout queue.

    The host must bind a job with HostWorkerEpochRegistry.bind(), obtain an
    actual admitted QoSDecision, and arm *before* dispatch. claim() must be
    called immediately before committing the first output byte/frame; the
    host must flush queued output on restart and check preplay/turn permissions
    separately. Never expose a permit as a model-callable capability.
    """

    def __init__(self, registry: HostWorkerEpochRegistry, *,
                 max_pending: int = 128) -> None:
        if not isinstance(registry, HostWorkerEpochRegistry):
            raise TypeError("trusted worker epoch registry required")
        if type(max_pending) is not int or not 1 <= max_pending <= 1024:
            raise ValueError("bounded output queue required")
        self._registry = registry
        self._cap = max_pending
        self._enabled = False
        self._lock = RLock()
        self._now = 0.0
        self._serial = 0
        self._pending: dict[int, tuple[HostReplyPermit, HostWorkerEpoch]] = {}
        self._used_tickets: set[int] = set()

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("explicit trusted-host opt-in required")
        with self._lock:
            self._enabled = True

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._pending.clear()
            # Do not reuse one-shot admission IDs after a disable/enable cycle.

    def _advance(self, now_ms: float) -> float:
        now = _clock(now_ms)
        if now < self._now:
            raise ValueError("host monotonic clock reversed")
        self._now = now
        return now

    def arm(self, *, epoch: HostWorkerEpoch, job: InferenceJob,
            admission: QoSDecision, now_ms: float) -> HostReplyPermit:
        """Host-only: register one admitted, pinned, fresh inference output."""
        if not isinstance(epoch, HostWorkerEpoch):
            raise TypeError("worker epoch required")
        if not isinstance(job, InferenceJob) or not isinstance(admission, QoSDecision):
            raise TypeError("bound inference job and QoS decision required")
        with self._lock:
            now = self._advance(now_ms)
            if not self._enabled:
                raise PermissionError("output fence is disabled")
            if job.kind not in _OUTPUT_KINDS:
                raise ValueError("not a user-visible inference result")
            if job.route_profile != epoch.route_profile:
                raise ValueError("job is not bound to this worker epoch")
            if not (admission.admitted and type(admission.ticket) is int
                    and admission.ticket > 0 and admission.device == job.device
                    and admission.expires_ms is not None):
                raise ValueError("successful matching QoS admission required")
            expires = _clock(admission.expires_ms)
            if (now < job.created_ms or now >= expires
                    or expires > job.deadline_ms or expires > now + 30_000):
                raise ValueError("expired or forged output deadline")
            if not self._registry.is_current(epoch, now_ms=now):
                raise ValueError("worker epoch expired or replaced")
            for key, (permit, _) in tuple(self._pending.items()):
                if permit.deadline_ms < now:
                    del self._pending[key]
            if admission.ticket in self._used_tickets:
                raise ValueError("replayed QoS admission ticket")
            if len(self._pending) >= self._cap:
                raise ValueError("bounded output queue full")
            if len(self._used_tickets) >= 4096:
                raise ValueError("bounded session ticket limit reached")
            self._used_tickets.add(admission.ticket)
            self._serial += 1
            permit = HostReplyPermit(self._serial, job.kind, epoch.route_profile, expires)
            self._pending[permit.serial] = (permit, epoch)
            return permit

    def claim(self, permit: HostReplyPermit, *, now_ms: float,
              host_output_ready: bool) -> HostReplyAdvice:
        """One-shot final check, NOT a command to publish or play the output.

        Only the trusted host may assert output-ready from its own worker
        transport; this does not confirm speech is audible. If a worker dies,
        the host must also physically release/stall output already buffered.
        """
        if not isinstance(permit, HostReplyPermit):
            raise TypeError("opaque host output permit required")
        if type(host_output_ready) is not bool:
            raise ValueError("explicit trusted host readiness required")
        with self._lock:
            now = self._advance(now_ms)
            if not self._enabled:
                return HostReplyAdvice(False, "owner_opt_in_missing")
            stored = self._pending.get(permit.serial)
            if stored is None or stored[0] is not permit:
                return HostReplyAdvice(False, "unknown_or_replayed_output")
            epoch = stored[1]
            if now > permit.deadline_ms:
                del self._pending[permit.serial]
                return HostReplyAdvice(False, "output_deadline_expired")
            if not self._registry.is_current(epoch, now_ms=now):
                del self._pending[permit.serial]
                return HostReplyAdvice(False, "worker_restarted_or_observation_stale")
            if not host_output_ready:
                return HostReplyAdvice(False, "worker_output_not_ready")
            # One-shot: a second queued callback cannot play the same reply.
            del self._pending[permit.serial]
            return HostReplyAdvice(True, "fresh_worker_output_candidate")

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._pending)


__all__ = ["HostReplyPermit", "HostReplyAdvice", "HostWorkerReplyFence"]
