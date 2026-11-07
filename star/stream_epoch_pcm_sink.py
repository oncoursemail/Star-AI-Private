"""Opt-in local PCM16 speaker boundary for a verified Star speech epoch.

Connects StreamOutputConsumerQueue.consume_one(submit=...) to the *existing*
star.voice.devices.SoundSpeaker on an owner-controlled host. SoundSpeaker
must already be opened and started by the owner. This adapter does not load
models, connect microphones, control OBS, contact viewers, or start devices.

Every PCM write is checked against an active, never-reused native epoch.
Epoch invalidation is serialized with enqueue, and the device buffer is
cleared on stop. Important: SoundSpeaker's play() merely appends to an
application queue. Its callback count is NOT proof the listener heard sound,
and stop() alone cannot flush frames already handed to PortAudio. The real
audio host must independently attest native output silence before reuse.
Do not invoke from the PortAudio callback or expose to model/viewer tools.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from threading import RLock
from typing import Protocol

_EPOCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z", re.ASCII)
_MAX_EPOCHS = 4096


class PCM16Speaker(Protocol):
    """Structural interface implemented by star.voice.devices.SoundSpeaker."""

    sample_rate: int

    def play(self, pcm: bytes, sample_rate: int) -> None: ...
    def stop(self) -> None: ...
    def pending_seconds(self) -> float: ...


@dataclass(frozen=True)
class EpochPCMStatus:
    status: str  # ready | held | stopped | quiet | disabled | fault
    reason: str
    authorizes_broadcast: bool = False
    authorizes_game_input: bool = False
    device_audibility_verified: bool = False


class LocalEpochPCMSink:
    """Owner-host-only last-mile native PCM16 queue, disabled by default.

    This is a device *submission* boundary, not a playout clock. A trusted
    native backend must separately enforce per-epoch cancellation/flush and
    independently confirm the output path is quiet before bind() is reused.
    An accepted chunk means queued PCM only; it is NOT audible proof.

    All submission, stop and epoch changes are serialized. If backend.play()
    raises, the epoch is latched faulty; it cannot silently resume.
    """

    def __init__(
        self,
        backend: PCM16Speaker,
        *,
        max_buffered_ms: int = 600,
        max_chunk_bytes: int = 65536,
    ) -> None:
        if not all(callable(getattr(backend, name, None)) for name in ("play", "stop", "pending_seconds")):
            raise TypeError("trusted opened PCM speaker adapter required")
        rate = getattr(backend, "sample_rate", None)
        if type(rate) is not int or not 8000 <= rate <= 96000:
            raise ValueError("PCM16 speaker must use an explicit 8..96 kHz sample rate")
        if type(max_buffered_ms) is not int or not 40 <= max_buffered_ms <= 2000:
            raise ValueError("buffer time must be 40..2000 ms")
        if type(max_chunk_bytes) is not int or not 2 <= max_chunk_bytes <= 262144:
            raise ValueError("bounded PCM chunk size required")
        self._backend = backend
        self._rate = rate
        self._budget_ms = max_buffered_ms
        self._max_chunk = max_chunk_bytes
        self._lock = RLock()
        self._enabled = False
        self._active: str | None = None
        self._pending_quiet: str | None = None
        self._used: set[str] = set()
        self._faulted = False
        self._queued = 0
        self._rejected = 0
        self._stops = 0
        self._bytes = 0

    def _pending_ms(self) -> float | None:
        try:
            value = self._backend.pending_seconds()
            if type(value) not in (int, float):
                return None
            number = float(value) * 1000.0
            if not math.isfinite(number) or not 0 <= number <= 120000:
                return None
            return number
        except Exception:
            return None

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("explicit local owner opt-in required")
        with self._lock:
            if self._enabled or self._active is not None or self._faulted:
                raise RuntimeError("complete existing native-output lifecycle first")
            self._enabled = True

    def bind(self, epoch: str, *, independently_quiet: bool = False) -> EpochPCMStatus:
        """Only a trusted host may attest clean output before binding.

        The boolean is a host assertion and is deliberately NOT produced by
        pending_seconds(), which omits native PortAudio/driver buffers.
        """
        if type(epoch) is not str or _EPOCH.fullmatch(epoch) is None:
            raise ValueError("bounded trusted native epoch required")
        if type(independently_quiet) is not bool:
            raise ValueError("trusted native quiet witness must be boolean")
        with self._lock:
            if not self._enabled or self._faulted or self._active is not None or self._pending_quiet is not None:
                return EpochPCMStatus("held", "native_output_unavailable")
            if not independently_quiet or epoch in self._used or len(self._used) >= _MAX_EPOCHS:
                return EpochPCMStatus("held", "fresh_epoch_and_independent_quiet_required")
            pending = self._pending_ms()
            if pending is None or pending > 0:
                return EpochPCMStatus("held", "speaker_queue_not_empty_or_unreadable")
            self._active = epoch
            self._used.add(epoch)
            return EpochPCMStatus("ready", "owner_local_pcm_epoch_bound")

    def submit(self, epoch: str, kind: str, payload: bytes | str) -> bool:
        """Use as the PCM route for StreamOutputConsumerQueue.consume_one().

        PCM must already be mono signed little-endian 16-bit at backend rate.
        No resampling or blocking synthesis is performed on this hot path.
        """
        if type(payload) is not bytes or not 0 < len(payload) <= self._max_chunk or len(payload) % 2:
            return False
        if type(kind) is not str or kind != "tts_pcm" or type(epoch) is not str:
            return False
        with self._lock:
            if not self._enabled or self._faulted or self._active != epoch:
                self._rejected += 1
                return False
            pending = self._pending_ms()
            new_ms = len(payload) * 500.0 / self._rate
            if pending is None or pending + new_ms > self._budget_ms:
                self._rejected += 1
                return False
            try:
                self._backend.play(payload, self._rate)
            except Exception:
                # Invalidate BEFORE attempting to clear app PCM. Never report
                # sound stopped merely because the backend accepted stop().
                self._faulted = True
                self._pending_quiet = epoch
                self._active = None
                try:
                    self._backend.stop()
                except Exception:
                    pass
                self._rejected += 1
                return False
            self._queued += 1
            self._bytes += len(payload)
            return True

    def request_stop(self, epoch: str) -> bool:
        """Invalidate first; clear app queue. Native output still needs proof."""
        with self._lock:
            if type(epoch) is not str:
                return False
            # The output fence and the physical-stop coordinator may both
            # request the same stop. Acknowledging the *request* twice is
            # safe; only observe_quiet can attest native device drain.
            if epoch == self._pending_quiet:
                return not self._faulted
            if epoch != self._active:
                return False
            self._active = None
            self._pending_quiet = epoch
            self._stops += 1
            try:
                self._backend.stop()
            except Exception:
                self._faulted = True
                return False
            return True

    def observe_quiet(
        self,
        epoch: str,
        *,
        native_output_flushed: bool = False,
    ) -> EpochPCMStatus:
        """External host attestation only; cannot be derived from app buffer."""
        if type(native_output_flushed) is not bool:
            raise ValueError("native flush observation must be boolean")
        with self._lock:
            if epoch != self._pending_quiet or type(epoch) is not str:
                return EpochPCMStatus("held", "no_matching_stopped_epoch")
            if not native_output_flushed or self._pending_ms() != 0:
                return EpochPCMStatus("held", "native_silence_not_verified")
            if self._faulted:
                return EpochPCMStatus("fault", "manual_device_recovery_required")
            self._pending_quiet = None
            return EpochPCMStatus("quiet", "native_host_attested_quiet_not_audibility")

    def disable(self) -> EpochPCMStatus:
        """Never replay an interrupted epoch; no silent recovery after error."""
        with self._lock:
            self._enabled = False
            if self._active is not None:
                epoch = self._active
                self._active = None
                self._pending_quiet = epoch
                self._stops += 1
                try:
                    self._backend.stop()
                except Exception:
                    self._faulted = True
            return EpochPCMStatus(
                "fault" if self._faulted else "disabled",
                "native_quiet_requires_independent_host_witness"
                if self._pending_quiet
                else "disabled_without_active_pcm",
            )

    def metrics(self) -> dict[str, int | bool]:
        """No epochs, transcripts, device identifiers, voices or raw PCM."""
        with self._lock:
            return {
                "enabled": self._enabled,
                "active": self._active is not None,
                "pending_quiet": self._pending_quiet is not None,
                "faulted": self._faulted,
                "unique_epochs": len(self._used),
                "queued": self._queued,
                "queued_bytes_total": self._bytes,
                "rejected": self._rejected,
                "stops": self._stops,
            }


__all__ = ["LocalEpochPCMSink", "EpochPCMStatus", "PCM16Speaker"]
