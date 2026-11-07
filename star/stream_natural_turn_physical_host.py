"""Owner-local actuation of a NaturalTurnBridge stop decision.

This narrow host adapter closes the gap between a *requested* dialogue stop
and an independently *observed* PCM drain plus neutral avatar. It performs no
TTS, microphone capture, OBS operations, or broadcasts. No device callbacks are
provided by default: a trusted native host must implement and own all five.

IMPORTANT: Callback booleans are host assertions, not hardware guarantees.
Callbacks must be epoch-scoped, must not be exposed to viewers/models, and the
native audio device requires an independent timeout/stop watchdog. This class
must not run its blocking callbacks on the real-time audio callback thread.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from threading import RLock
from typing import Callable

from .stream_director import SpeechIntent
from .stream_natural_turn_bridge import NaturalTurnBridge

_EPOCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z", re.ASCII)


@dataclass(frozen=True)
class PhysicalTurnResult:
    action: str  # hold | prepare | stopped | fault
    reason: str
    intent: SpeechIntent | None = None
    stop_token: int | None = None
    pcm_drained: bool = False
    avatar_neutral: bool = False
    authorizes_playback: bool = False
    authorizes_broadcast: bool = False


class NaturalTurnPhysicalHost:
    """One private device/rig stop path for an already approved speech turn.

    A caller must bind its *own* native playback epoch before reporting active
    audio. All callbacks must target ONLY that epoch. A failed stop is sticky,
    never silently retried (the old epoch might have been superseded).
    Recovery only rechecks independently observed device and avatar state.
    """

    def __init__(
        self,
        bridge: NaturalTurnBridge,
        *,
        request_pcm_stop: Callable[[str], bool],
        request_animation_flush: Callable[[str], bool],
        request_avatar_neutral: Callable[[str], bool],
        pcm_drained_probe: Callable[[str], bool],
        avatar_neutral_probe: Callable[[str], bool],
    ) -> None:
        if type(bridge) is not NaturalTurnBridge:
            raise TypeError("exact NaturalTurnBridge required")
        hooks = (
            request_pcm_stop,
            request_animation_flush,
            request_avatar_neutral,
            pcm_drained_probe,
            avatar_neutral_probe,
        )
        if not all(callable(hook) for hook in hooks):
            raise TypeError("five local host callbacks required")
        self._bridge = bridge
        self._stop_pcm = request_pcm_stop
        self._flush = request_animation_flush
        self._neutral = request_avatar_neutral
        self._pcm_drained = pcm_drained_probe
        self._avatar_neutral = avatar_neutral_probe
        self._lock = RLock()
        self._enabled = False
        self._epoch: str | None = None
        self._failed_token: int | None = None
        self._attempted: set[int] = set()
        self._verified_stops = 0

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner must approve local physical output")
        with self._lock:
            if self._enabled or self._epoch is not None or self._failed_token is not None:
                raise RuntimeError("finish or recover the previous physical turn")
            self._bridge.enable(owner_approved=True)
            self._enabled = True

    def bind_playout(self, epoch: str, *, host_observed_active: bool) -> None:
        """Bind native device epoch; this is NOT permission to start speaking."""
        if type(epoch) is not str or _EPOCH.fullmatch(epoch) is None:
            raise ValueError("bounded native playback epoch required")
        if host_observed_active is not True:
            raise ValueError("only an already active physical epoch can be bound")
        with self._lock:
            if (
                not self._enabled
                or self._epoch is not None
                or self._failed_token is not None
                or self._bridge.metrics()["stop_outstanding"]
            ):
                raise RuntimeError("cannot replace/forge an active physical epoch")
            self._epoch = epoch

    @staticmethod
    def _observed(probe: Callable[[str], bool], epoch: str) -> bool:
        try:
            return probe(epoch) is True
        except Exception:
            return False

    @staticmethod
    def _request(request: Callable[[str], bool], epoch: str) -> bool:
        try:
            return request(epoch) is True
        except Exception:
            return False

    def _execute_stop(self, token: int) -> PhysicalTurnResult:
        """Caller holds lock; never acknowledge merely a stop request."""
        epoch = self._epoch
        if type(token) is not int or token in self._attempted or self._failed_token is not None:
            return PhysicalTurnResult("fault", "stop_already_attempted_or_faulted", stop_token=token)
        self._attempted.add(token)
        if epoch is None:
            self._failed_token = token
            return PhysicalTurnResult("fault", "unbound_physical_playout", stop_token=token)
        # Flush even if stop request failed, but do not inject a neutral pose
        # while the output may still be speaking.
        stop_requested = self._request(self._stop_pcm, epoch)
        flushed = self._request(self._flush, epoch)
        drained = stop_requested and self._observed(self._pcm_drained, epoch)
        neutral = False
        if drained and flushed and self._request(self._neutral, epoch):
            neutral = self._observed(self._avatar_neutral, epoch)
            # Final recheck: a resumed/queued PCM stream invalidates the ACK.
            drained = self._observed(self._pcm_drained, epoch)
        if drained and neutral and self._bridge.acknowledge_stopped(token, pcm_drained=True, avatar_neutral=True):
            self._epoch = None
            self._verified_stops += 1
            return PhysicalTurnResult(
                "stopped", "physical_stop_verified", stop_token=token, pcm_drained=True, avatar_neutral=True
            )
        self._failed_token = token
        return PhysicalTurnResult(
            "fault", "manual_hardware_recovery_required", stop_token=token, pcm_drained=drained, avatar_neutral=neutral
        )

    def drive(
        self,
        *,
        now_ms: float,
        host_playout_active: bool,
        gameplay_critical: bool,
        output_healthy: bool,
    ) -> PhysicalTurnResult:
        """One trusted-host tick, NEVER invoked from model/viewer tools."""
        if any(
            type(v) is not bool
            for v in (
                host_playout_active,
                gameplay_critical,
                output_healthy,
            )
        ):
            raise ValueError("host observations must be booleans")
        with self._lock:
            if self._failed_token is not None:
                return PhysicalTurnResult("fault", "manual_hardware_recovery_required", stop_token=self._failed_token)
            if not self._enabled:
                return PhysicalTurnResult("hold", "owner_opt_in_missing")
            # The host must agree with the bound physical epoch. A missing
            # playback observation is NOT proof that old device audio stopped.
            # On disagreement stop the pinned epoch rather than prepare speech.
            if host_playout_active and self._epoch is None or not host_playout_active and self._epoch is not None:
                token = self._bridge.disable(host_playout_active=True)
                self._enabled = False
                assert token is not None
                return self._execute_stop(token)
            advice = self._bridge.advise(
                now_ms=now_ms,
                host_playout_active=host_playout_active,
                gameplay_critical=gameplay_critical,
                output_healthy=output_healthy,
            )
            if advice.action == "stop_playback":
                assert advice.stop_token is not None
                return self._execute_stop(advice.stop_token)
            return PhysicalTurnResult(advice.action, advice.reason, intent=advice.intent)

    def disable(self, *, host_playout_active: bool) -> PhysicalTurnResult:
        """Revoke dialogue; attempt physical stop even if the clock is broken."""
        if type(host_playout_active) is not bool:
            raise ValueError("host_playout_active must be bool")
        with self._lock:
            self._enabled = False
            token = self._bridge.disable(
                host_playout_active=host_playout_active or self._epoch is not None,
            )
            if self._failed_token is not None:
                return PhysicalTurnResult("fault", "manual_hardware_recovery_required", stop_token=self._failed_token)
            if token is not None:
                return self._execute_stop(token)
            return PhysicalTurnResult("hold", "session_disabled")

    def retire_finished(self, epoch: str) -> bool:
        """Retire natural completion only after separate quiet/neutral probes."""
        with self._lock:
            if (
                type(epoch) is not str
                or epoch != self._epoch
                or self._failed_token is not None
                or self._bridge.metrics()["stop_outstanding"]
            ):
                return False
            if not self._observed(self._pcm_drained, epoch) or not self._observed(self._avatar_neutral, epoch):
                return False
            self._epoch = None
            return True

    def recover_after_manual_stop(self, *, owner_approved: bool = False) -> bool:
        """Owner recovery: re-probe old epoch; never rerun stop on a new one."""
        if owner_approved is not True:
            raise PermissionError("owner must approve manual hardware recovery")
        with self._lock:
            token, epoch = self._failed_token, self._epoch
            if token is None or epoch is None:
                return False
            drained = self._observed(self._pcm_drained, epoch)
            neutral = self._observed(self._avatar_neutral, epoch)
            if not drained or not neutral:
                return False
            # Disable first: otherwise the bridge might reissue a fresh stop
            # because its most recent observation still said PCM was active.
            self._bridge.disable(host_playout_active=False)
            if not self._bridge.acknowledge_stopped(
                token,
                pcm_drained=True,
                avatar_neutral=True,
            ):
                return False
            self._failed_token = None
            self._epoch = None
            self._verified_stops += 1
            # No auto-reenable: owner must explicitly start a NEW session.
            self._enabled = False
            return True

    def metrics(self) -> dict[str, int | bool]:
        """Sanitized counts only; no epoch, PCM, transcript or viewer data."""
        with self._lock:
            return {
                "enabled": self._enabled,
                "epoch_bound": self._epoch is not None,
                "faulted": self._failed_token is not None,
                "attempted_stop_tokens": len(self._attempted),
                "verified_stops": self._verified_stops,
            }


__all__ = ["NaturalTurnPhysicalHost", "PhysicalTurnResult"]
