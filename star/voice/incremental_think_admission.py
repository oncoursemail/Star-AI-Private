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
from .think_resource_profile import ThinkResourceProfile

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_EPOCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
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
    resources: ResourceVector
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
        resources: ResourceVector | None = None,
        resource_profile: ThinkResourceProfile | None = None,
        configuration_fingerprint: str | None = None,
        clock_epoch: str | None = None,
        max_pending: int = 64,
    ) -> None:
        if type(runtime) is not StreamWorkloadRuntime:
            raise TypeError("runtime must be StreamWorkloadRuntime")
        if (resources is None) == (resource_profile is None):
            raise ValueError("provide exactly one of resources or resource_profile")
        if resources is not None and type(resources) is not ResourceVector:
            raise TypeError("resources must be an explicit ResourceVector")
        if resource_profile is not None and type(resource_profile) is not ThinkResourceProfile:
            raise TypeError("resource_profile must be ThinkResourceProfile")
        if resource_profile is None and configuration_fingerprint is not None:
            raise ValueError("configuration_fingerprint requires resource_profile")
        if resource_profile is not None and (
            type(configuration_fingerprint) is not str
            or re.fullmatch(r"[0-9a-f]{64}", configuration_fingerprint) is None
        ):
            raise ValueError("configuration_fingerprint must be a lowercase SHA-256 hex value")
        if resource_profile is not None and resource_profile.clock_epoch is not None:
            if type(clock_epoch) is not str or _EPOCH.fullmatch(clock_epoch) is None:
                raise ValueError("clock_epoch is required for an epoch-bound resource profile")
            if clock_epoch != resource_profile.clock_epoch:
                raise ValueError("clock_epoch must match the resource profile")
        elif clock_epoch is not None:
            raise ValueError("clock_epoch requires an epoch-bound resource profile")
        if type(max_pending) is not int or not 1 <= max_pending <= 256:
            raise ValueError("max_pending must be in 1..256")
        if resources is not None:
            for name in ("cpu_millicores", "ram_mb", "vram_mb"):
                value = getattr(resources, name)
                if type(value) is not int or not 0 <= value <= _MAX_RESOURCE_UNITS:
                    raise ValueError(f"resources.{name} is outside the supported range")
        self._runtime = runtime
        self._resources = resources
        self._resource_profile = resource_profile
        self._configuration_fingerprint = configuration_fingerprint
        self._clock_epoch = clock_epoch
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
            "profile_unusable": 0,
        }

    def _resources_for(self, now_ms: int) -> ResourceVector | None:
        if self._resource_profile is None:
            assert self._resources is not None
            return self._resources
        resources = self._resource_profile.resources_for(
            now_ms=now_ms,
            expected_configuration_fingerprint=self._configuration_fingerprint or "",
            expected_clock_epoch=self._clock_epoch,
        )
        if resources is None:
            self._counts["profile_unusable"] += 1
        return resources

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
                    self._counts["blocked"] += 1
                    return ThinkAdmissionResult("blocked", "pending_capacity_reached")
                resources = self._resources_for(now)
                if resources is None:
                    self._counts["blocked"] += 1
                    return ThinkAdmissionResult("rejected", "resource_profile_stale_or_mismatched")
                request_id = self._request_id(key)
                request = WorkloadRequest(
                    request_id=request_id,
                    lane=WorkloadLane.VOICE_PREP,
                    resources=resources,
                    enqueued_monotonic_ms=now,
                    deadline_monotonic_ms=directive.expires_at_ms,
                )
                submission = self._runtime.submit(request)
                if submission.status not in ("queued", "granted"):
                    self._counts["blocked"] += 1
                    return ThinkAdmissionResult("blocked", submission.reason or submission.status)
                binding = _Binding(
                    utterance_id=key[0],
                    revision=key[1],
                    request_id=request_id,
                    directive=directive,
                    state=ThinkBindingState.QUEUED,
                    resources=resources,
                    lease=submission.lease,
                )
                self._bindings[key] = binding
                if submission.lease is not None:
                    self._by_lease[submission.lease.lease_id] = key
                self._counts["queued"] += 1
                return ThinkAdmissionResult("queued", "awaiting_central_scheduler", request_id)

            if directive.action is ThinkAction.UPDATE:
                key = self._key(directive.utterance_id, directive.revision)
                binding = self._bindings.get(key)
                if binding is None:
                    return ThinkAdmissionResult("not_found", "no_matching_thinker")
                if binding.state in (ThinkBindingState.CANCEL_PENDING, ThinkBindingState.STOP_REQUESTED,
                                     ThinkBindingState.RECOVERY_REQUIRED):
                    return ThinkAdmissionResult("blocked", "thinker_generation_is_stopping", binding.request_id)
                binding.directive = directive
                self._counts["updated"] += 1
                return ThinkAdmissionResult("updated", "ephemeral_prefix_replaced", binding.request_id)

            if directive.action in (ThinkAction.CANCEL, ThinkAction.FINALIZE):
                return self._cancel_exact(
                    directive.utterance_id,
                    directive.revision,
                    reason=directive.reason or directive.action.value,
                )

            return ThinkAdmissionResult("ignored", "unsupported_directive")

    def accept_lease(self, lease: WorkloadLease, *, now_ms: int) -> ThinkLaunch | None:
        """Route a central scheduler lease to this bridge, or release an orphan."""
        now = _now(now_ms)
        if type(lease) is not WorkloadLease or lease.lane is not WorkloadLane.VOICE_PREP:
            return None
        with self._lock:
            key = self._by_lease.get(lease.lease_id)
            if key is None:
                # A lease may be routed after a queued cancellation raced with
                # the scheduler. Release only because no worker was launched.
                self._runtime.release(
                    lease.lease_id, now, host_confirmed_stopped=True
                )
                return None
            binding = self._bindings.get(key)
            if binding is None or binding.state is not ThinkBindingState.QUEUED:
                self._runtime.release(
                    lease.lease_id, now, host_confirmed_stopped=True
                )
                if binding is not None:
                    self._remove(binding)
                return None
            if lease.resources != binding.resources:
                binding.state = ThinkBindingState.RECOVERY_REQUIRED
                self._counts["start_uncertain"] += 1
                return None
            if self._resources_for(now) != binding.resources:
                # Profile/configuration can expire while the scheduler queue is
                # waiting. No process has started, so release the unused lease.
                self._runtime.release(
                    lease.lease_id, now, host_confirmed_stopped=True
                )
                self._remove(binding)
                self._counts["profile_unusable"] += 1
                return None
            binding.lease = lease
            binding.state = ThinkBindingState.STARTING
            self._by_lease[lease.lease_id] = key
            self._counts["started"] += 1
            return ThinkLaunch(binding.directive, lease)

    def startup_result(
        self,
        utterance_id: str,
        revision: int,
        *,
        started: bool,
        host_confirmed_not_started: bool = False,
    ) -> ThinkAdmissionResult:
        """Resolve a host launch offer; uncertain startup keeps the lease fenced."""
        key = self._key(utterance_id, revision)
        if type(started) is not bool or type(host_confirmed_not_started) is not bool:
            raise ValueError("startup result flags must be explicit booleans")
        with self._lock:
            binding = self._bindings.get(key)
            if binding is None or binding.state is not ThinkBindingState.STARTING or binding.lease is None:
                return ThinkAdmissionResult("not_found", "no_starting_generation")
            if started:
                binding.state = ThinkBindingState.RUNNING
                return ThinkAdmissionResult("running", "host_confirmed_started", binding.request_id)
            if host_confirmed_not_started:
                self._runtime.release(
                    binding.lease.lease_id, binding.lease.granted_monotonic_ms,
                    host_confirmed_stopped=True,
                )
                self._remove(binding)
                self._counts["cancelled"] += 1
                return ThinkAdmissionResult("cancelled", "host_confirmed_not_started", binding.request_id)
            binding.state = ThinkBindingState.RECOVERY_REQUIRED
            self._counts["start_uncertain"] += 1
            return ThinkAdmissionResult("recovery_required", "startup_state_uncertain", binding.request_id)

    def stop_request(
        self,
        utterance_id: str,
        revision: int,
    ) -> ThinkStopRequest | None:
        """Return the host's exact process-stop obligation, if one is pending."""
        key = self._key(utterance_id, revision)
        with self._lock:
            binding = self._bindings.get(key)
            if binding is None or binding.state is not ThinkBindingState.STOP_REQUESTED or binding.lease is None:
                return None
            return ThinkStopRequest(
                utterance_id=binding.utterance_id,
                revision=binding.revision,
                reason=binding.cancel_reason or "cancelled",
                lease=binding.lease,
            )

    def stop_result(
        self,
        utterance_id: str,
        revision: int,
        *,
        host_confirmed_stopped: bool,
        now_ms: int,
    ) -> ThinkAdmissionResult:
        """Release active resources only after a truthful host stop acknowledgement."""
        now = _now(now_ms)
        if type(host_confirmed_stopped) is not bool:
            raise ValueError("host_confirmed_stopped must be an explicit boolean")
        key = self._key(utterance_id, revision)
        with self._lock:
            binding = self._bindings.get(key)
            if binding is None or binding.state not in (
                ThinkBindingState.STOP_REQUESTED, ThinkBindingState.RECOVERY_REQUIRED
            ) or binding.lease is None:
                return ThinkAdmissionResult("not_found", "no_stoppable_generation")
            if not host_confirmed_stopped:
                binding.state = ThinkBindingState.RECOVERY_REQUIRED
                self._counts["stop_unconfirmed"] += 1
                return ThinkAdmissionResult("recovery_required", "worker_stop_not_confirmed", binding.request_id)
            self._runtime.release(
                binding.lease.lease_id, now, host_confirmed_stopped=True
            )
            self._remove(binding)
            self._counts["cancelled"] += 1
            return ThinkAdmissionResult("cancelled", "host_confirmed_stopped", binding.request_id)

    def metrics(self) -> dict[str, int]:
        """Aggregate counters only; no transcript or utterance identifiers."""
        with self._lock:
            return dict(self._counts)


__all__ = [
    "ThinkAdmissionResult",
    "ThinkBindingState",
    "ThinkLaunch",
    "ThinkStopRequest",
    "IncrementalThinkAdmissionBridge",
]
