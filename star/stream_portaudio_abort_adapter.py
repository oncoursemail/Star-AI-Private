"""Owner-only PortAudio abort bridge for Star's epoch-fenced local PCM speaker.

This is an opt-in *transport* for LocalEpochPCMSink, not a new audio device.
It requires a dedicated, already started SoundSpeaker with no other writers.
A stop invalidates future writes BEFORE attempting a strict native abort.
PortAudio abort means pending host buffers need not drain; it does NOT prove
that speakers, Windows mixers, capture devices or viewers heard silence.

Do not call from the realtime PortAudio callback, the LLM, or viewer tools.
Never treat native stream flags as a substitute for an independent quiet
observation or for an authenticated audio/rig epoch handoff.
"""

from __future__ import annotations

from threading import RLock
import math
from typing import Protocol


class NativeAbortSpeaker(Protocol):
    sample_rate: int

    def play(self, pcm: bytes, sample_rate: int) -> None: ...
    def pending_seconds(self) -> float: ...
    def abort_pending_output(self) -> bool: ...
    def restart_after_abort(self) -> bool: ...
    def native_output_state(self) -> str: ...


class NativeAbortPCMSpeaker:
    """Strict, serial, private PCM submission and abort boundary.

    Use as the PCM16Speaker backend of LocalEpochPCMSink. The owner host
    must be the speaker's *only* writer. LocalEpochPCMSink remains in charge
    of validating the speech epoch, PCM format and buffer budget; this
    component enforces native stop and explicit, witnessed rearming.
    """

    def __init__(self, speaker: NativeAbortSpeaker, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner opt-in required for native audio abort control")
        if not all(
            callable(getattr(speaker, method, None))
            for method in (
                "play",
                "pending_seconds",
                "abort_pending_output",
                "restart_after_abort",
                "native_output_state",
            )
        ):
            raise TypeError("requires an abort-capable, dedicated SoundSpeaker")
        rate = getattr(speaker, "sample_rate", None)
        if type(rate) is not int or not 8000 <= rate <= 96000:
            raise ValueError("invalid PCM16 sample rate")
        if speaker.native_output_state() != "running" or speaker.pending_seconds() != 0:
            raise RuntimeError("owner must supply started speaker with an empty queue")
        self.sample_rate = rate
        self._speaker = speaker
        self._lock = RLock()
        self._running = True
        self._requires_quiet = False
        self._fault = False
        self._aborts = 0
        self._restarts = 0

    def pending_seconds(self) -> float:
        with self._lock:
            value = self._speaker.pending_seconds()
            if type(value) not in (int, float) or not math.isfinite(float(value)):
                raise RuntimeError("unreliable native queue measurement")
            if float(value) < 0 or float(value) > 120:
                raise RuntimeError("invalid native queue measurement")
            return float(value)

    def play(self, pcm: bytes, sample_rate: int) -> None:
        with self._lock:
            if self._fault or not self._running or self._requires_quiet:
                raise RuntimeError("native speaker stopped or faulty")
            if sample_rate != self.sample_rate:
                raise ValueError("unexpected PCM sample rate")
            # This delegation is serialized with stop(); an interrupted epoch
            # cannot enqueue fresh audio after the abort boundary has won.
            try:
                self._speaker.play(pcm, sample_rate)
            except Exception:
                # play() can fail *after* partially queuing PCM. Before
                # propagating failure to LocalEpochPCMSink, request a strict
                # native abort instead of leaving those frames running.
                self._running = False
                self._requires_quiet = True
                try:
                    if (
                        self._speaker.abort_pending_output() is True
                        and self._speaker.native_output_state() == "stopped"
                    ):
                        self._aborts += 1
                except Exception:
                    pass
                self._fault = True  # manual owner recovery, even if abort worked
                raise

    def stop(self) -> None:
        """Invalidate writes then abort native pending output, never drain it."""
        with self._lock:
            if self._fault:
                raise RuntimeError("native speaker requires manual recovery")
            if not self._running:
                return  # duplicated cancellation, NOT a quiet attestation
            self._running = False
            self._requires_quiet = True
            try:
                result = self._speaker.abort_pending_output()
                if result is not True or self._speaker.native_output_state() != "stopped":
                    raise RuntimeError("native audio abort not confirmed")
            except Exception:
                self._fault = True
                raise
            self._aborts += 1

    def resume_after_flush(self, *, independently_quiet: bool = False) -> bool:
        """Explicit local host witness required; never auto-rearm an epoch.

        Call only after LocalEpochPCMSink.observe_quiet() succeeds. The host
        must independently establish that its audio and rig outputs are quiet.
        """
        if type(independently_quiet) is not bool:
            raise ValueError("quiet attestation must be a strict boolean")
        with self._lock:
            if not independently_quiet or self._fault or self._running or not self._requires_quiet:
                return False
            try:
                if self.pending_seconds() != 0 or self._speaker.native_output_state() != "stopped":
                    return False
                started = self._speaker.restart_after_abort()
                if started is not True or self._speaker.native_output_state() != "running":
                    raise RuntimeError("native audio restart not confirmed")
            except Exception:
                # A restart may fail after the native stream actually began.
                # Best-effort abort any resulting output before fault latching.
                try:
                    if (
                        self._speaker.abort_pending_output() is True
                        and self._speaker.native_output_state() == "stopped"
                    ):
                        self._aborts += 1
                except Exception:
                    pass
                self._fault = True
                return False
            self._running = True
            self._requires_quiet = False
            self._restarts += 1
            return True

    def metrics(self) -> dict[str, bool | int]:
        """Identity- and audio-free operational counters only."""
        with self._lock:
            return {
                "running": self._running,
                "requires_independent_quiet": self._requires_quiet,
                "faulted": self._fault,
                "native_aborts": self._aborts,
                "native_restarts": self._restarts,
            }


__all__ = ["NativeAbortPCMSpeaker", "NativeAbortSpeaker"]
