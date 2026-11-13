"""Resource-admission bridge for STAR's speculative voice thinker.

The semantic-prefix coordinator decides *when* a partial utterance is stable.
This bridge decides whether a background thinker may consume host resources.
It uses the existing StreamWorkloadRuntime and never starts a process, calls a
model, speaks, executes tools, or writes canonical conversation history.

A trusted host owns telemetry, scheduling, worker startup/cancellation, and the
truth of every stop acknowledgement. Never call this bridge from an audio or
render callback.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import re
from threading import RLock

from ..stream_workload_admission import ResourceVector, WorkloadLane, WorkloadLease, WorkloadRequest
from ..stream_workload_runtime import StreamWorkloadRuntime
from .incremental_thinking import ThinkAction, ThinkDirective

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_MAX_CLOCK_MS = 10**12
_MAX_RESOURCE_UNITS = 1_000_000_000


class ThinkBindingState(str, Enum):
    QUEUED = "queued"
    CANCEL_PENDING = "cancel_pending"
    STARTING = "starting"
    RUNNING = "running"
    STOP_REQUESTED = "stop_requested"
    RECOVERY_REQUIRED = "recovery_required"


@dataclass(frozen=True)
class ThinkAdmissionResult:
    """Content-free result of applying one coordinator directive."""

    status: str
    reason: str
    request_id: str | None = None


@dataclass(frozen=True)
class ThinkLaunch:
    """Host-only launch offer issued after the scheduler grants a lease."""

    directive: ThinkDirective
    lease: WorkloadLease


@dataclass(frozen=True)
class ThinkStopRequest:
    """Host-only stop request; it is not proof that a worker has stopped."""

    utterance_id: str
    revision: int
    reason: str
    lease: WorkloadLease


@dataclass
class _Binding:
    utterance_id: str
    revision: int
    request_id: str
    directive: ThinkDirective
    state: ThinkBindingState
    lease: WorkloadLease | None = None
    cancel_reason: str = ""


def _now(value: object) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_CLOCK_MS:
        raise ValueError("now_ms must be a bounded monotonic millisecond value")
    return value


def _revision(value: object) -> int:
    if type(value) is not int or not 0 <= value <= 1_000_000:
        raise ValueError("revision must be a bounded nonnegative integer")
    return value


class IncrementalThinkAdmissionBridge:
    """Admit bounded, read-only speculative reasoning without stealing reserves.

    Thinker work uses WorkloadLane.VOICE_PREP: it is lower priority than audio, game
    control, voice, avatar, and chat work; it cannot consume the hard realtime reserve;
    and it is eligible during a healthy stream/game only from unreserved
    capacity. Stale or degraded host telemetry blocks this non-protected lane.

    The central host scheduler still calls StreamWorkloadRuntime.schedule().
    It routes each returned lease to the owning subsystem, which calls
    accept_lease() here. This avoids this adapter accidentally consuming leases
    belonging to other subsystems.
    """

    def __init__(
        self,
        runtime: StreamWorkloadRuntime,
        *,
        resources: ResourceVector,
        max_pending: int = 64,
    ) -> None:
        if type(runtime) is not StreamWorkloadRuntime:
            raise TypeError("runtime must be StreamWorkloadRuntime")
        if type(resources) is not ResourceVector:
            raise TypeError("resources must be an explicit ResourceVector")
        if type(max_pending) is not int or not 1 <= max_pending <= 256:
            raise ValueError("max_pending must be in 1..256")
        for name in ("cpu_millicores", "ram_mb", "vram_mb"):
            value = getattr(resources, name)
            if type(value) is not int or not 0 <= value <= _MAX_RESOURCE_UNITS:
                raise ValueError(f"resources.{name} is outside the supported range")
        self._runtime = runtime
        self._resources = resources
        self._max_pending = max_pending
        self._bindings: dict[tuple[str, int], _Binding] = {}
        self._by_lease: dict[str, tuple[str, int]] = {}
        self._lock = RLock()
        self._counts = {
            "queued": 0,
            "started": 0,
            "updated": 0,
            "cancelled": 0,
            "cancel_pending": 0,
            "blocked": 0,
            "expired_or_rejected": 0,
            "start_uncertain": 0,
            "stop_unconfirmed": 0,
            "completed": 0,
        }

    @staticmethod
    def _key(utterance_id: str, revision: int) -> tuple[str, int]:
        if type(utterance_id) is not str or _ID.fullmatch(utterance_id) is None:
            raise ValueError("utterance_id must be a bounded opaque identifier")
        return utterance_id, _revision(revision)

    @staticmethod
    def _request_id(key: tuple[str, int]) -> str:
        # Never place transcript text, user content, or raw utterance IDs in the
        # shared scheduler's request identifier.
        material = f"{key[0]}:{key[1]}".encode("ascii")
        return "think-" + hashlib.sha256(material).hexdigest()[:32]

    def _remove(self, binding: _Binding) -> None:
        self._bindings.pop((binding.utterance_id, binding.revision), None)
        if binding.lease is not None:
            self._by_lease.pop(binding.lease.lease_id, None)

    def _cancel_exact(
        self,
        utterance_id: str,
        revision: int,
        *,
        reason: str,
    ) -> ThinkAdmissionResult:
        key = self._key(utterance_id, revision)
        binding = self._bindings.get(key)
        if binding is None:
            return ThinkAdmissionResult("not_found", "no_matching_thinker")

        if binding.state in (ThinkBindingState.QUEUED, ThinkBindingState.CANCEL_PENDING):
            if self._runtime.cancel_queued(binding.request_id):
                self._remove(binding)
                self._counts["cancelled"] += 1
                return ThinkAdmissionResult("cancelled", "queued_request_removed", binding.request_id)
            # The central scheduler may have moved the request to an active
            # lease just before this cancellation. Keep the binding until that
            # lease is routed here; accept_lease() will release it without
            # starting a worker.
            binding.state = ThinkBindingState.CANCEL_PENDING
            binding.cancel_reason = reason
            self._counts["cancel_pending"] += 1
            return ThinkAdmissionResult(
                "cancel_pending", "awaiting_scheduler_lease_reconciliation", binding.request_id
            )

        if binding.lease is None:
            self._counts["blocked"] += 1
            return ThinkAdmissionResult("blocked", "worker_state_uncertain", binding.request_id)

        binding.state = ThinkBindingState.STOP_REQUESTED
        binding.cancel_reason = reason
        self._counts["blocked"] += 1
        return ThinkAdmissionResult("stop_required", "host_must_confirm_worker_stop", binding.request_id)

    def apply(self, directive: ThinkDirective, *, now_ms: int) -> ThinkAdmissionResult:
        """Apply START/UPDATE/CANCEL/FINALIZE from IncrementalThinkCoordinator.

        START requests are queued, not launched. UPDATE replaces only the
        ephemeral prefix visible to the already-admitted worker. CANCEL and
        FINALIZE revoke queued work or return a stop-required state; the host
        must obtain a real process-stop acknowledgement before releasing an
        active lease.
        """
        now = _now(now_ms)
        if type(directive) is not ThinkDirective:
            raise TypeError("directive must be ThinkDirective")
        if type(directive.action) is not ThinkAction or type(directive.cancel_previous) is not bool:
            raise ValueError("directive action and cancellation flag must be explicit")
        if directive.may_speak is not False or directive.may_execute_tools is not False:
            raise PermissionError("incremental thinker directives cannot speak or execute tools")

        with self._lock:
            if directive.action is ThinkAction.WAIT:
                return ThinkAdmissionResult("wait", "coordinator_not_ready")
            if directive.action is ThinkAction.REJECT:
                self._counts["expired_or_rejected"] += 1
                return ThinkAdmissionResult("rejected", directive.reason or "coordinator_rejected")

            if directive.action is ThinkAction.START:
                if directive.revision < 0:
                    raise ValueError("START requires a nonnegative revision")
                if directive.cancel_previous:
                    if (not directive.cancel_utterance_id
                            or directive.cancel_revision < 0):
                        raise ValueError("START cancellation target is incomplete")
                    prior = self._cancel_exact(
                        directive.cancel_utterance_id,
                        directive.cancel_revision,
                        reason="asr_revision_replaced",
                    )
                    if prior.status not in ("cancelled", "not_found"):
                        self._counts["blocked"] += 1
                        return ThinkAdmissionResult(
                            "blocked_previous",
                            "previous_thinker_must_stop_before_new_revision",
                        )

                key = self._key(directive.utterance_id, directive.revision)
                existing = self._bindings.get(key)
                if existing is not None:
                    if existing.state in (
                        ThinkBindingState.CANCEL_PENDING,
                        ThinkBindingState.STOP_REQUESTED,
                        ThinkBindingState.RECOVERY_REQUIRED,
                    ):
                        self._counts["blocked"] += 1
                        return ThinkAdmissionResult("blocked", "existing_generation_is_stopping", existing.request_id)
                    existing.directive = directive
                    self._counts["updated"] += 1
                    return ThinkAdmissionResult("already_pending", "idempotent_start", existing.request_id)
                if len(self._bindings) >= self._max_pending:
                    self._counts["expired_or_rejected"] += 1
                    return ThinkAdmissionResult("rejected", "pending_capacity_reached")

                request_id = self._request_id(key)
                request = WorkloadRequest(
                    request_id=request_id,
                    lane=WorkloadLane.VOICE_PREP,
                    resources=self._resources,
                    enqueued_monotonic_ms=now,
                    deadline_monotonic_ms=None,
                )
                submission = self._runtime.submit(request)
                if submission.status != "queued":
                    self._counts["expired_or_rejected"] += 1
                    return ThinkAdmissionResult(
                        "rejected", submission.reason or submission.status, request_id
                    )
                self._bindings[key] = _Binding(
                    utterance_id=key[0],
                    revision=key[1],
                    request_id=request_id,
                    directive=directive,
                    state=ThinkBindingState.QUEUED,
                )
                self._counts["queued"] += 1
                return ThinkAdmissionResult("queued", "awaiting_fresh_host_admission", request_id)

            if directive.action is ThinkAction.UPDATE:
                key = self._key(directive.utterance_id, directive.revision)
                binding = self._bindings.get(key)
                if binding is None or binding.state in (
                    ThinkBindingState.CANCEL_PENDING,
                    ThinkBindingState.STOP_REQUESTED,
                    ThinkBindingState.RECOVERY_REQUIRED,
                ):
                    self._counts["blocked"] += 1
                    return ThinkAdmissionResult("blocked", "no_current_admitted_thinker")
                binding.directive = directive
                self._counts["updated"] += 1
                return ThinkAdmissionResult("updated", "latest_stable_prefix_replaced", binding.request_id)

            if directive.action is ThinkAction.CANCEL:
                if not directive.cancel_previous:
                    return ThinkAdmissionResult("cancelled", "no_active_thinker")
                return self._cancel_exact(
                    directive.cancel_utterance_id,
                    directive.cancel_revision,
                    reason=directive.reason or "coordinator_cancelled",
                )

            if directive.action is ThinkAction.FINALIZE:
                return self._cancel_exact(
                    directive.utterance_id,
                    directive.revision,
                    reason="final_transcript_committed",
                )

            raise ValueError("unsupported think directive action")

    def accept_lease(self, lease: WorkloadLease, *, now_ms: int) -> ThinkLaunch | None:
        """Route one scheduler-granted lease; never starts a worker itself."""
        now = _now(now_ms)
        if type(lease) is not WorkloadLease:
            raise TypeError("lease must be WorkloadLease")
        if lease.lane is not WorkloadLane.VOICE_PREP:
            return None
        if lease.granted_monotonic_ms > now:
            raise ValueError("scheduler lease cannot be future-dated")
        with self._lock:
            key = next(
                (key for key, binding in self._bindings.items()
                 if binding.request_id == lease.request_id),
                None,
            )
            if key is None:
                return None
            binding = self._bindings[key]
            if binding.state is ThinkBindingState.CANCEL_PENDING:
                # No worker was launched, so the host can safely release this
                # just-granted reservation after routing it here.
                self._runtime.release(
                    lease.lease_id, now, host_confirmed_stopped=True
                )
                self._remove(binding)
                self._counts["cancelled"] += 1
                return None
            if binding.state is not ThinkBindingState.QUEUED:
                raise RuntimeError("duplicate or out-of-order scheduler lease")
            if now >= lease.expires_monotonic_ms:
                self._runtime.release(lease.lease_id, now, host_confirmed_stopped=True)
                self._remove(binding)
                self._counts["expired_or_rejected"] += 1
                return None
            if lease.request_id != binding.request_id:
                raise ValueError("lease does not match the queued thinker request")
            if lease.resources != self._resources:
                raise ValueError("scheduler lease resource vector changed")
            binding.lease = lease
            binding.state = ThinkBindingState.STARTING
            self._by_lease[lease.lease_id] = key
            return ThinkLaunch(binding.directive, lease)

    def current_directive(self, lease_id: str) -> ThinkDirective:
        """Return the latest ephemeral prefix for a host-owned worker poll."""
        if type(lease_id) is not str or re.fullmatch(r"[0-9a-f]{32}", lease_id) is None:
            raise ValueError("lease_id must be a host-issued opaque lease ID")
        with self._lock:
            key = self._by_lease.get(lease_id)
            binding = self._bindings.get(key) if key is not None else None
            if binding is None or binding.state not in (
                ThinkBindingState.STARTING,
                ThinkBindingState.RUNNING,
            ):
                raise KeyError("no live thinker for lease")
            return binding.directive

    def confirm_started(
        self,
        lease_id: str,
        *,
        now_ms: int,
        started: bool,
        host_confirmed_stopped: bool = False,
    ) -> bool:
        """Record a host startup receipt; uncertain startup keeps capacity fenced."""
        now = _now(now_ms)
        if type(started) is not bool or type(host_confirmed_stopped) is not bool:
            raise ValueError("startup receipt fields must be explicit booleans")
        if started and host_confirmed_stopped:
            raise ValueError("a started worker cannot simultaneously be confirmed stopped")
        with self._lock:
            key = self._by_lease.get(lease_id)
            binding = self._bindings.get(key) if key is not None else None
            if binding is None or binding.lease is None:
                raise KeyError("unknown thinker lease")
            if binding.state not in (
                ThinkBindingState.STARTING,
                ThinkBindingState.STOP_REQUESTED,
                ThinkBindingState.RECOVERY_REQUIRED,
            ):
                raise RuntimeError("startup receipt is not expected in this state")
            if started:
                if binding.state is ThinkBindingState.STARTING:
                    binding.state = ThinkBindingState.RUNNING
                # If cancellation raced with startup, retain STOP_REQUESTED or
                # RECOVERY_REQUIRED so the host cannot mistake the worker for
                # an ordinary running generation.
                self._counts["started"] += 1
                return True
            if host_confirmed_stopped:
                self._runtime.release(
                    lease_id, now, host_confirmed_stopped=True
                )
                self._remove(binding)
                self._counts["expired_or_rejected"] += 1
                return False
            binding.state = ThinkBindingState.RECOVERY_REQUIRED
            self._counts["start_uncertain"] += 1
            return False

    def stop_request(
        self,
        utterance_id: str,
        revision: int,
        *,
        now_ms: int,
        reason: str = "owner_or_asr_cancel",
    ) -> ThinkStopRequest | None:
        """Return a host stop request for one exact worker generation."""
        _now(now_ms)
        if type(reason) is not str or not 1 <= len(reason) <= 64:
            raise ValueError("reason must be a short nonempty label")
        with self._lock:
            key = self._key(utterance_id, revision)
            result = self._cancel_exact(
                utterance_id, revision, reason=reason
            )
            if result.status != "stop_required":
                return None
            binding = self._bindings[key]
            assert binding.lease is not None
            return ThinkStopRequest(
                utterance_id=utterance_id,
                revision=revision,
                reason=reason,
                lease=binding.lease,
            )

    def confirm_stopped(
        self,
        lease_id: str,
        *,
        now_ms: int,
        host_confirmed_stopped: bool,
    ) -> bool:
        """Release capacity only after the host proves the worker is stopped."""
        now = _now(now_ms)
        if type(host_confirmed_stopped) is not bool:
            raise ValueError("host_confirmed_stopped must be an explicit boolean")
        if host_confirmed_stopped is not True:
            with self._lock:
                key = self._by_lease.get(lease_id)
                binding = self._bindings.get(key) if key is not None else None
                if binding is not None:
                    binding.state = ThinkBindingState.RECOVERY_REQUIRED
                    self._counts["stop_unconfirmed"] += 1
            return False
        with self._lock:
            key = self._by_lease.get(lease_id)
            binding = self._bindings.get(key) if key is not None else None
            if binding is None or binding.lease is None:
                return False
            if binding.state not in (
                ThinkBindingState.STOP_REQUESTED,
                ThinkBindingState.RECOVERY_REQUIRED,
                ThinkBindingState.RUNNING,
                ThinkBindingState.STARTING,
            ):
                raise RuntimeError("worker stop is not expected in this state")
            self._runtime.release(
                lease_id, now, host_confirmed_stopped=True
            )
            self._remove(binding)
            self._counts["cancelled"] += 1
            return True

    def metrics(self) -> dict[str, int]:
        """Aggregate counters only; no utterance IDs, transcript text, or lease IDs."""
        with self._lock:
            return dict(self._counts)


__all__ = [
    "IncrementalThinkAdmissionBridge",
    "ThinkAdmissionResult",
    "ThinkBindingState",
    "ThinkLaunch",
    "ThinkStopRequest",
]
