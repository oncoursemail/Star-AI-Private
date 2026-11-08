"""Independent owner-host polling for the reviewed VTuber PCM wall-clock watchdog.

The language model, TTS generator and audio callback cannot be trusted to call
watchdog() while they are stuck. This opt-in local worker drives the existing
StreamPreplayPCMBridge with one host monotonic clock even when TTS emits no PCM.

This is NOT a Windows audio-device adapter or physical silence attestation.
The bridge's trusted SoundSpeaker host must still stop/flush native output and
verify independent quiet before rearming. No microphone, OBS, game input,
network or speech generation is started here. Process crashes cannot be
protected by an in-process thread: production requires an external watchdog.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from threading import Event, RLock, Thread, current_thread
import time
from typing import Callable

from .stream_director import SpeechIntent
from .stream_preplay_gate import PreplayDecision
from .stream_preplay_pcm_bridge import PCMBridgeAdvice, StreamPreplayPCMBridge


@dataclass(frozen=True)
class PCMWatchdogMetrics:
    running: bool
    polls: int
    admitted: int
    submitted: int
    revoked: bool
    notification_failed: bool
    permits_broadcast: bool = False
    verifies_physical_silence: bool = False


class StreamPCMWatchdogSupervisor:
    """Monitor a single existing bridge without trusting TTS progress.

    start() must be called only by an authorized local host after the gate,
    sink and bridge are explicitly enabled. For covered epochs, call admit()
    and submit() through this wrapper. Native final playback receipts should
    still go to bridge.complete_turn()/attest_quiet() from the trusted host.
    A failed/late clock, lost poller, or timeout requests physical STOP and
    keeps any reviewed turn quarantined; it NEVER asserts output is silent.
    """

    def __init__(
        self,
        bridge: StreamPreplayPCMBridge,
        *,
        interval_s: float = 0.05,
        clock: Callable[[], float] = time.monotonic,
        on_trip: Callable[[], None] | None = None,
    ) -> None:
        if type(bridge) is not StreamPreplayPCMBridge:
            raise TypeError("trusted stream PCM bridge required")
        if type(interval_s) not in (int, float) or not math.isfinite(interval_s) or not 0.01 <= interval_s <= 0.25:
            raise ValueError("watchdog interval must be 10..250ms")
        if not callable(clock) or (on_trip is not None and not callable(on_trip)):
            raise TypeError("trusted clock and optional local callback required")
        self._bridge = bridge
        self._interval = float(interval_s)
        self._clock = clock
        self._on_trip = on_trip
        self._lock = RLock()
        self._stop = Event()
        self._worker: Thread | None = None
        self._started = False
        self._closed = False
        self._failed = False
        self._notification_failed = False
        self._last_now: float | None = None
        self._polls = 0
        self._admitted = 0
        self._submitted = 0

    def start(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("local owner approval required")
        with self._lock:
            if self._started or self._closed:
                raise RuntimeError("PCM watchdog is one-shot")
            state = self._bridge.metrics()
            if (
                state["enabled"] is not True
                or state["native_epoch_active"]
                or state["stop_outstanding"]
                or state["faulted"]
            ):
                raise RuntimeError("enable an idle, healthy PCM bridge first")
            self._started = True
            worker = Thread(target=self._run, daemon=True, name="star-pcm-epoch-watchdog")
            self._worker = worker
            try:
                worker.start()
            except Exception:
                self._trip()
                raise RuntimeError("PCM watchdog could not start") from None

    def _trip(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._failed = True
            self._stop.set()
        # Never clear the quarantine or assert that PortAudio/hardware stopped.
        try:
            self._bridge.disable()
        except Exception:
            pass
        if self._on_trip is not None:
            try:
                self._on_trip()
            except Exception:
                with self._lock:
                    self._notification_failed = True

    def _require_running(self) -> None:
        if not self._started or self._closed:
            raise RuntimeError("PCM watchdog is not running")
        if self._worker is None or not self._worker.is_alive():
            self._trip()
            raise RuntimeError("independent PCM watchdog worker was lost")

    def _poll(self) -> tuple[float, PCMBridgeAdvice]:
        with self._lock:
            self._require_running()
            try:
                value = self._clock()
                if type(value) not in (int, float):
                    raise ValueError("host clock must return numeric seconds")
                now = float(value)
                if (
                    not math.isfinite(now)
                    or not 0 <= now <= 1e10
                    or (self._last_now is not None and now < self._last_now)
                ):
                    raise ValueError("host monotonic clock unavailable")
                self._last_now = now
                result = self._bridge.watchdog(now_s=now)
                self._polls += 1
                state = self._bridge.metrics()
                if result.state in ("stop_requested", "fault") or not state["enabled"] or state["faulted"]:
                    raise RuntimeError("reviewed PCM turn requires stop/recovery")
            except Exception:
                self._trip()
                raise RuntimeError("PCM watchdog failed closed") from None
            return now, result

    def _run(self) -> None:
        try:
            while not self._stop.wait(self._interval):
                self._poll()
        except Exception:
            self._trip()

    def health(self) -> PCMWatchdogMetrics:
        """Synchronous check before granting further PCM producer access."""
        self._poll()
        return self.metrics()

    def admit(
        self,
        review: PreplayDecision,
        *,
        epoch: str,
        independently_quiet: bool = False,
    ) -> PCMBridgeAdvice:
        """Use same host clock for admission and independent polling."""
        with self._lock:
            now, _ = self._poll()
            try:
                advice = self._bridge.admit(
                    review,
                    epoch=epoch,
                    now_s=now,
                    independently_quiet=independently_quiet,
                )
            except Exception:
                self._trip()
                raise RuntimeError("PCM admission failed closed") from None
            if advice.state == "ready":
                self._admitted += 1
            return advice

    def submit(self, intent: SpeechIntent, *, epoch: str, pcm16: bytes) -> bool:
        """Deadline-check even if the background worker is late to run."""
        with self._lock:
            self._poll()
            try:
                queued = self._bridge.submit(intent, epoch=epoch, pcm16=pcm16)
            except Exception:
                self._trip()
                raise RuntimeError("PCM submission failed closed") from None
            if queued:
                self._submitted += 1
            state = self._bridge.metrics()
            if state["faulted"] or state["stop_outstanding"]:
                self._trip()
                raise RuntimeError("PCM submission revoked due to native stop")
            return queued

    def stop(self) -> PCMBridgeAdvice:
        """Shut down and request native stop; quiet still needs host receipt."""
        with self._lock:
            self._closed = True
            self._stop.set()
            worker = self._worker
        outcome = self._bridge.disable()
        if worker is not None and worker is not current_thread():
            worker.join(timeout=min(1.0, self._interval * 3))
        return outcome

    def metrics(self) -> PCMWatchdogMetrics:
        with self._lock:
            running = self._started and not self._closed and self._worker is not None and self._worker.is_alive()
            state = self._bridge.metrics()
            return PCMWatchdogMetrics(
                running=bool(running and state["enabled"] and not state["faulted"]),
                polls=self._polls,
                admitted=self._admitted,
                submitted=self._submitted,
                revoked=self._failed,
                notification_failed=self._notification_failed,
            )


__all__ = ["PCMWatchdogMetrics", "StreamPCMWatchdogSupervisor"]
