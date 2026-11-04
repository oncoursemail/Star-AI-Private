"""Optional trusted-host watchdog for Star's audible VTuber voice feed.

A VAD callback cannot detect its own disappearance. This local worker calls
StreamInterruptionHost.tick() *even when no new voice frames arrive*. In strict
mode a stale source triggers an epoch-scoped PCM stop/rig flush and latches a
manual recovery fault. The trusted audio adapter is responsible for actually
stopping physical sound; a Python thread cannot provide process-crash safety.
Nothing here captures audio, broadcasts, starts OBS, or exposes model tools.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from threading import Event, RLock, Thread, current_thread
from typing import Callable

from .stream_interrupt_host import InterruptionResult, StreamInterruptionHost
from .stream_stage import StagePlan
from .stream_turntaking import VoiceFrame


@dataclass(frozen=True)
class VoiceSupervisorMetrics:
    running: bool
    checks: int
    observed_frames: int
    revoked: bool
    notification_failed: bool


class StreamVoiceLivenessSupervisor:
    """Drive owner-opted strict VAD liveness independently of microphone events.

    All voice ingestion and playback registration should flow through this
    wrapper, not through model tools. start() requires an existing authorized
    StreamInterruptionHost with require_live_voice=True. The optional on_lost
    callback is for trusted local diagnostics, not physical audio termination.
    """

    def __init__(
        self, host: StreamInterruptionHost, *,
        interval_s: float = 0.05,
        on_lost: Callable[[], None] | None = None,
    ) -> None:
        if not isinstance(host, StreamInterruptionHost):
            raise TypeError("existing trusted voice interruption host required")
        if (type(interval_s) not in (int, float)
                or not math.isfinite(interval_s) or
                not 0.01 <= interval_s <= 0.15):
            raise ValueError("voice watchdog interval must be 10..150ms")
        if interval_s * 3000 > host.voice_gap_limit_ms:
            raise ValueError("watchdog must tick at least three times per VAD gap")
        if on_lost is not None and not callable(on_lost):
            raise TypeError("on_lost must be a trusted local callback")
        self._host = host
        self._interval = float(interval_s)
        self._on_lost = on_lost
        self._lock = RLock()
        self._stop = Event()
        self._worker: Thread | None = None
        self._started = False
        self._closed = False
        self._failed = False
        self._callback_failed = False
        self._checks = 0
        self._observed = 0

    def start(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner approval required for live voice supervision")
        with self._lock:
            if self._started or self._closed:
                raise RuntimeError("voice watchdog is one-shot and cannot restart")
            state = self._host.metrics()
            if not state["enabled"] or not state["voice_liveness_required"] or state["fault"]:
                raise RuntimeError("enable verified live VAD on host first")
            self._started = True
            worker = Thread(
                target=self._run, daemon=True, name="star-live-voice-watchdog",
            )
            self._worker = worker
            try:
                worker.start()
            except Exception:
                self._trip()
                raise RuntimeError("voice watchdog failed to start") from None

    def _trip(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._failed = True
            self._stop.set()
        # If this is a watchdog failure, attempt a physical stop even when
        # the VAD callback and event loop have both stopped. This is still
        # a host attestation, not a guarantee the sound device went silent.
        try:
            self._host.emergency_stop()
        except Exception:
            pass
        try:
            self._host.disable()
        except Exception:
            pass
        if self._on_lost is not None:
            try:
                self._on_lost()
            except Exception:
                with self._lock:
                    self._callback_failed = True

    def _check(self) -> InterruptionResult:
        try:
            result = self._host.tick()
        except Exception:
            # A failed sensor or clock callback must not leave PCM armed until
            # the next watchdog interval. The trusted host performs the stop.
            self._trip()
            raise RuntimeError("live voice supervision failed closed") from None
        with self._lock:
            self._checks += 1
        if result.status in {"fault", "disabled"}:
            self._trip()
        return result

    def _run(self) -> None:
        try:
            while not self._stop.wait(self._interval):
                with self._lock:
                    if self._closed:
                        return
                self._check()
        except Exception:
            self._trip()

    def _require_running(self) -> None:
        with self._lock:
            if not self._started or self._closed:
                raise RuntimeError("live voice supervisor is not running")
            worker = self._worker
            if worker is not None and worker.is_alive():
                return
        self._trip()
        raise RuntimeError("live voice watchdog stopped unexpectedly")

    def observe(self, frame: VoiceFrame) -> InterruptionResult:
        """Proxy VAD input, refusing unprotected ingestion after watchdog loss."""
        self._require_running()
        try:
            result = self._host.observe(frame)
        except Exception:
            # Invalid/replayed VAD is not evidence of quiet. Revoke the old
            # audible epoch rather than continuing with a poisoned feed.
            self._trip()
            raise RuntimeError("live voice observations failed closed") from None
        if result.status in {"fault", "disabled"}:
            self._trip()
        self._require_running()
        with self._lock:
            self._observed += 1
        return result

    def arm(self, plan: StagePlan, *, playback_epoch: str) -> bool:
        """Never begin an utterance when the independent monitor is absent."""
        self._require_running()
        armed = self._host.arm(plan, playback_epoch=playback_epoch)
        self._require_running()
        return armed

    def health(self) -> VoiceSupervisorMetrics:
        """Poll the source synchronously before permitting the next PCM chunk."""
        self._require_running()
        self._check()
        self._require_running()
        return self.metrics()

    def stop(self) -> InterruptionResult:
        """Permanently close the wrapper and physically request audio stop."""
        with self._lock:
            self._closed = True
            self._stop.set()
            worker = self._worker
        result = self._host.disable()
        if worker is not None and worker is not current_thread():
            worker.join(timeout=min(1.0, self._interval * 3))
        return result

    def metrics(self) -> VoiceSupervisorMetrics:
        with self._lock:
            live = (self._started and not self._closed
                    and self._worker is not None and self._worker.is_alive())
            checks = self._checks
            frames = self._observed
            revoked = self._failed
            cb_failed = self._callback_failed
        state = self._host.metrics()
        return VoiceSupervisorMetrics(
            running=live and bool(state["enabled"]) and not bool(state["fault"]),
            checks=checks, observed_frames=frames,
            revoked=revoked or bool(state["fault"]),
            notification_failed=cb_failed,
        )


__all__ = ["StreamVoiceLivenessSupervisor", "VoiceSupervisorMetrics"]
