"""Trusted, bounded VTuber barge-in coordinator for existing Star components.

Owner/guest VAD input comes only from an authorized local host, never Twitch,
LLM content, voice cloning or a probability pretending to establish identity.
The host supplies an epoch-scoped *physical playback stop* and animation-queue
flush. This module neither captures a microphone nor owns an output device.

The coordinator invalidates a specific audible StagePlan BEFORE requesting
hardware stop, then resets VTube Studio parameters only after the host attests
the playback epoch actually stopped and stale animation packets were flushed.
Any missing acknowledgement latches a fault: no new playback is armed.

The callbacks and VTS transport MUST be private host capabilities; never make
them accessible as model tools or viewer commands.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from threading import RLock
import time
from typing import Callable, Protocol

from .stream_stage import StagePlan, StarStage
from .stream_turntaking import TurnTakingGate, VoiceFrame

_EPOCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")


class AvatarPort(Protocol):
    @property
    def connected(self) -> bool: ...

    def send_neutral(
        self, plan: StagePlan, *, playback_epoch: str, playback_stopped: bool = False
    ) -> bool: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class InterruptionResult:
    status: str  # disabled | hold | speak | owner_yield | interrupted | fault | stale
    reason: str
    audio_stopped: bool = False
    avatar_reset: bool = False
    stop_latency_ms: float | None = None


def _clock_ms(read: Callable[[], float]) -> float:
    try:
        val = read()
        if type(val) not in (int, float):
            raise ValueError
        value = float(val)
        if not math.isfinite(value) or not 0 <= value <= 1e13:
            raise ValueError
        return value
    except Exception as exc:
        raise ValueError("trusted host clock unavailable") from exc


class StreamInterruptionHost:
    """Bind one audible plan to one local playback epoch and interrupt safely.

    'stop_epoch' MUST stop the physical sound device and return exactly True
    ONLY after the addressed epoch is stopped. 'flush_animation' MUST remove
    pending rig frames for that same epoch. Both are provided by the trusted
    host, not the language model. Their return values are attestations, not
    hardware-proven guarantees.

    This deliberately never resumes or restarts playback automatically.
    """

    def __init__(
        self, *,
        stage: StarStage,
        turns: TurnTakingGate,
        stop_epoch: Callable[[str], bool],
        flush_animation: Callable[[str], bool],
        avatar: AvatarPort | None = None,
        clock_ms: Callable[[], float] = lambda: time.monotonic() * 1000,
        maximum_stop_ms: float = 120,
        owner_approved: bool = False,
    ) -> None:
        if owner_approved is not True:
            raise PermissionError("owner must approve local voice-interruption control")
        if not isinstance(stage, StarStage) or not isinstance(turns, TurnTakingGate):
            raise TypeError("expected existing StarStage and TurnTakingGate")
        if not all(callable(item) for item in (stop_epoch, flush_animation, clock_ms)):
            raise TypeError("trusted host callbacks must be callable")
        if avatar is not None and not all(
            callable(getattr(avatar, name, None))
            for name in ("send_neutral", "close")
        ):
            raise TypeError("avatar must supply send_neutral and close")
        if type(maximum_stop_ms) not in (int, float) or not math.isfinite(
            float(maximum_stop_ms)
        ) or not 20 <= maximum_stop_ms <= 500:
            raise ValueError("maximum_stop_ms must be 20..500")
        self._stage = stage
        self._turns = turns
        self._stop_epoch = stop_epoch
        self._flush = flush_animation
        self._avatar = avatar
        self._clock = clock_ms
        self._maximum_stop = float(maximum_stop_ms)
        self._lock = RLock()
        self._enabled = False
        self._busy = False
        self._fault = False
        self._active: tuple[StagePlan, str] | None = None
        self._counts = {
            "armed": 0, "held": 0, "interruptions": 0,
            "stop_failures": 0, "reset_failures": 0, "latency_faults": 0,
            "stale": 0, "faults": 0,
        }

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner must explicitly enable the VAD source")
        with self._lock:
            if self._fault or self._active is not None or self._busy:
                raise RuntimeError("recover hardware or finish the current epoch first")
            if self._stage.metrics()["enabled"] is not True:
                raise RuntimeError("stage must already be owner-enabled")
            self._turns.enable(owner_approved=True)
            self._enabled = True

    def arm(self, plan: StagePlan, *, playback_epoch: str) -> bool:
        """Register an already audible plan; not permission to start TTS."""
        if type(playback_epoch) is not str or not _EPOCH.fullmatch(playback_epoch):
            raise ValueError("invalid bounded playback epoch")
        with self._lock:
            if (not self._enabled or self._fault or self._busy
                    or self._active is not None or not isinstance(plan, StagePlan)
                    or not self._stage.current(plan)):
                return False
            # Never bind speech over an active owner/guest voice, uncleared
            # echo, or stale/missing VAD. The stage may be audible already,
            # but the trusted host must have established a clear vocal floor.
            if self._turns.advise(
                now_ms=_clock_ms(self._clock), star_speaking=False
            ).action != "speak":
                return False
            if self._avatar is not None and self._avatar.connected is not True:
                return False
            self._active = (plan, playback_epoch)
            self._counts["armed"] += 1
            return True

    def _avatar_close(self) -> None:
        if self._avatar is not None:
            try:
                self._avatar.close()  # release parameter overrides on failure
            except Exception:
                pass

    def _interrupt(self, *, reason: str, now_ms: float) -> InterruptionResult:
        """The caller owns _lock; no blocking external callback can rearm us."""
        assert self._active is not None
        plan, epoch = self._active
        self._active = None
        self._busy = True
        try:
            # The compare-and-revoke is atomic with respect to concurrent
            # stage.finish/new turns; do NOT cancel a different StagePlan.
            if self._stage.interrupt_if_current(plan, now=now_ms / 1000) is None:
                self._counts["stale"] += 1
                return InterruptionResult("stale", "playback_plan_already_changed")
            start_ms = _clock_ms(self._clock)
            try:
                stopped = self._stop_epoch(epoch) is True
            except Exception:
                stopped = False
            try:
                elapsed = _clock_ms(self._clock) - start_ms
            except ValueError:
                elapsed = -1.0
            latency_fault = elapsed < 0 or elapsed > self._maximum_stop
            if latency_fault:
                self._counts["latency_faults"] += 1
            # Queue flushing is useful even when audio stop failed, but it
            # cannot authorize neutral injection without an audio-stop ACK.
            try:
                flushed = self._flush(epoch) is True
            except Exception:
                flushed = False
            if not stopped:
                self._counts["stop_failures"] += 1
            reset = stopped and flushed
            if reset and self._avatar is not None:
                try:
                    reset = self._avatar.send_neutral(
                        plan, playback_epoch=epoch, playback_stopped=True
                    ) is True
                except Exception:
                    reset = False
            if not reset:
                self._counts["reset_failures"] += 1
            if not stopped or not reset or latency_fault:
                self._fault = True
                self._counts["faults"] += 1
                self._avatar_close()
                return InterruptionResult(
                    "fault", "hardware_stop_or_avatar_reset_unconfirmed",
                    audio_stopped=stopped, avatar_reset=reset,
                    stop_latency_ms=elapsed if elapsed >= 0 else None,
                )
            self._counts["interruptions"] += 1
            return InterruptionResult(
                "interrupted", reason, audio_stopped=True, avatar_reset=True,
                stop_latency_ms=elapsed,
            )
        finally:
            self._busy = False

    def observe(self, frame: VoiceFrame) -> InterruptionResult:
        """Host drives short VAD frames; guests cannot authorize interruption."""
        if not isinstance(frame, VoiceFrame):
            raise TypeError("expected host-provided VoiceFrame")
        with self._lock:
            if not self._enabled:
                return InterruptionResult("disabled", "owner_opt_in_missing")
            if self._fault or self._busy:
                return InterruptionResult("fault", "manual_audio_recovery_required")
            # Validate time before touching turn counters; replay/future audio
            # from an unrelated stream must not cancel a current turn.
            now = _clock_ms(self._clock)
            if frame.at_ms > now + 1e-6:
                raise ValueError("VAD frame is ahead of the host clock")
            self._turns.observe(frame)
            active = self._active is not None
            plan = self._active[0] if active else None
            speaking = bool(plan is not None and self._stage.current(plan))
            advice = self._turns.advise(now_ms=now, star_speaking=speaking)
            if active and not speaking:
                self._active = None
                self._counts["stale"] += 1
                return InterruptionResult("stale", "audible_plan_already_finished")
            if speaking and advice.should_interrupt:
                return self._interrupt(reason="authenticated_owner_barge_in", now_ms=now)
            self._counts["held"] += int(advice.hold)
            return InterruptionResult(
                "owner_yield" if advice.action == "yield_owner"
                else "hold" if advice.hold else "speak",
                advice.reason,
            )

    def emergency_stop(self) -> InterruptionResult:
        """Trusted host's manual stop; chat/model have no access to this method."""
        with self._lock:
            if not self._enabled or self._active is None:
                return InterruptionResult("disabled", "no_local_playback_epoch")
            if self._fault or self._busy:
                return InterruptionResult("fault", "manual_audio_recovery_required")
            return self._interrupt(
                reason="operator_requested_stop", now_ms=_clock_ms(self._clock)
            )

    def disable(self) -> InterruptionResult:
        """Revoke VAD control; attempt an epoch-scoped stop before returning."""
        with self._lock:
            result = (self.emergency_stop() if self._active is not None
                      else InterruptionResult("disabled", "no_local_playback_epoch"))
            self._enabled = False
            self._turns.disable()
            return result

    def recover(
        self, *, owner_approved: bool = False,
        physical_audio_stopped: bool = False,
        avatar_neutral_or_disconnected: bool = False,
    ) -> None:
        """Manual host-only recovery after external physical device checks."""
        if (owner_approved is not True or physical_audio_stopped is not True
                or avatar_neutral_or_disconnected is not True):
            raise PermissionError("physical audio and avatar recovery require owner attestation")
        with self._lock:
            if self._active is not None or self._busy:
                raise RuntimeError("cannot recover an active epoch")
            self._fault = False
            self._enabled = False
            self._turns.disable()

    def metrics(self) -> dict[str, int | bool]:
        """No raw audio, viewer data, speaker IDs, epoch IDs or transcripts."""
        with self._lock:
            return {**self._counts, "enabled": self._enabled,
                    "fault": self._fault, "active": self._active is not None}


__all__ = ["InterruptionResult", "StreamInterruptionHost", "AvatarPort"]
