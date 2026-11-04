"""Final read-only OS-to-reply composition for Star's local gaming VTuber.

The older reply fence proves a QoS receipt belongs to a recent *registered*
worker, not that the OS process still exists at the final playout boundary.
The OS supervisor separately verifies process liveness. This opt-in bridge
combines both checks in order, consuming a pending reply on OS failure.

It never emits audio, controls a game, captures media or starts OBS. Even a
successful result is only a candidate for the host's separate PCM, interruption,
game-context, moderation and broadcast authorization gates. OS liveness can
change immediately after observation; downstream physical-output gates remain
mandatory. No viewer, model, prompt or remote client should invoke it.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock

from .stream_host_process_supervisor import HostOSWorkerSupervisor
from .stream_host_reply_fence import HostReplyPermit, HostWorkerReplyFence
from .stream_host_worker_epochs import HostWorkerEpoch


@dataclass(frozen=True)
class LiveOutputAdvice:
    eligible: bool
    reason: str
    authorizes_audio: bool = False
    authorizes_broadcast: bool = False


class HostLiveOutputGate:
    """One final owner-opt-in process + worker-epoch output eligibility check."""

    def __init__(
        self, supervisor: HostOSWorkerSupervisor, fence: HostWorkerReplyFence,
    ) -> None:
        if not isinstance(supervisor, HostOSWorkerSupervisor):
            raise TypeError("trusted OS worker supervisor required")
        if not isinstance(fence, HostWorkerReplyFence):
            raise TypeError("host reply fence required")
        # Both host components must be bound to EXACTLY the same registry.
        if supervisor._registry is not fence._registry:
            raise ValueError("worker supervisor and reply fence registry differ")
        self._supervisor = supervisor
        self._fence = fence
        self._lock = RLock()
        self._enabled = False

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("local owner opt-in required")
        with self._lock:
            self._enabled = True

    def disable(self) -> None:
        """Stop gate decisions; revoke every pending fence receipt."""
        with self._lock:
            self._enabled = False
            # Output leases are not valid across gate disable/re-enable.
            self._fence.clear_pending()

    def claim(
        self, epoch: HostWorkerEpoch, permit: HostReplyPermit, *,
        host_output_ready: bool,
    ) -> LiveOutputAdvice:
        if not isinstance(epoch, HostWorkerEpoch) or not isinstance(
            permit, HostReplyPermit
        ):
            raise TypeError("host epoch and opaque output receipt required")
        if type(host_output_ready) is not bool:
            raise ValueError("trusted output readiness boolean required")
        with self._lock:
            if not self._enabled:
                self._fence.cancel(permit)
                return LiveOutputAdvice(False, "host_live_output_gate_disabled")
            if epoch.route_profile != permit.route_profile:
                self._fence.cancel(permit)
                return LiveOutputAdvice(False, "worker_output_route_mismatch")
            # On every playout attempt, ask the trusted OS observer AGAIN.
            # A registry lease or a prior successful enrollment is insufficient.
            try:
                process = self._supervisor.refresh(epoch)
            except (OSError, ValueError, RuntimeError):
                self._fence.cancel(permit)
                return LiveOutputAdvice(False, "host_process_probe_failed")
            if not process.current:
                self._fence.cancel(permit)
                return LiveOutputAdvice(False, "host_process_not_current")
            try:
                # Sample the SAME host clock only AFTER process verification.
                # Caller-supplied timestamps could backdate a slow OS probe.
                now_ms = self._supervisor.current_host_ms()
                advice = self._fence.claim(
                    permit, now_ms=now_ms, host_output_ready=host_output_ready)
            except (ValueError, RuntimeError):
                self._fence.cancel(permit)
                return LiveOutputAdvice(False, "host_reply_claim_invalid")
            return LiveOutputAdvice(advice.eligible, advice.reason)


__all__ = ["HostLiveOutputGate", "LiveOutputAdvice"]
