"""Owner-enabled live visual-intelligence admission using REAL host measurements.

This bridges RealtimeTelemetryHost -> ObservationGovernor for Star's gaming
VTuber and game-learning pipelines. Unlike giving an LLM a synthetic FPS
number, the bridge uses only validated, fresh device samples.

IMPORTANT: This does not capture frames, interpret screenshots, run inference,
play games, store images, or grant OS, browser, OBS or microphone privileges.
The authorized local caller owns actual capture and worker stop/termination.
Never expose host methods as model/chat tools.

Every issued lease survives disable/timeout until the trusted host confirms
that its GPU/CPU worker has physically stopped. Expired results are discarded.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from threading import RLock
import time
from typing import Callable

from .stream_hardware_telemetry import RealtimeTelemetryHost
from .frame_fingerprint import Region
from .stream_observe import FrameCue, ObservationDecision, ObservationGovernor


def _now_ms(clock: Callable[[], float]) -> float:
    try:
        result = clock()
        if type(result) not in (float, int):
            raise ValueError("invalid clock")
        now = float(result)
        if not math.isfinite(now) or not 0 <= now <= 1e13:
            raise ValueError("invalid clock")
        return now
    except Exception as exc:
        raise ValueError("trusted monotonic host clock unavailable") from exc


@dataclass(frozen=True)
class VisionLease:
    """Opaque local reservation; NOT a security authorization or image."""
    generation: int
    ticket: int
    expires_ms: float


@dataclass(frozen=True)
class VisionAdmission:
    admitted: bool
    reason: str
    target_fps: float
    lease: VisionLease | None = None


class StreamVisionHost:
    """Single-flight vision job planner that conserves live gaming resources.

    The caller owns the screen-capture permission and supplies real FrameCue
    observations from its device. It must call acknowledge_worker_stopped
    after joining/killing the physical worker, not merely requesting cancel.

    A host may disable admissions immediately, but cannot re-enable while
    even one old worker remains, including an expired worker. No actual tool
    execution is performed by this module.
    """

    def __init__(
        self, *, telemetry: RealtimeTelemetryHost,
        governor: ObservationGovernor,
        clock_ms: Callable[[], float] = lambda: time.monotonic() * 1000,
    ) -> None:
        if not isinstance(telemetry, RealtimeTelemetryHost):
            raise TypeError("expected existing RealtimeTelemetryHost")
        if not isinstance(governor, ObservationGovernor):
            raise TypeError("expected existing ObservationGovernor")
        if not callable(clock_ms):
            raise TypeError("trusted monotonic clock required")
        self._telemetry = telemetry
        self._governor = governor
        self._clock = clock_ms
        self._lock = RLock()
        self._generation = 0
        self._enabled = False
        self._leases: dict[int, VisionLease] = {}
        self._counters = {
            "admitted": 0, "deferred": 0, "stopped": 0,
            "completed": 0, "discarded": 0, "missing_sensor": 0,
            "stale_lease": 0,
        }

    def enable(self, *, owner_approved: bool = False,
               capture_approved: bool = False) -> None:
        """Two host-only approvals. This cannot grant actual OS capture rights."""
        if owner_approved is not True or capture_approved is not True:
            raise PermissionError("owner and capture authorization required")
        with self._lock:
            if self._enabled or self._leases:
                raise RuntimeError("stop previous vision session and worker first")
            _now_ms(self._clock)
            self._governor.enable(owner_approved=True)
            self._enabled = True
            self._generation += 1

    def disable(self) -> None:
        """Stop admissions; preserve reservations until actual worker stop."""
        with self._lock:
            self._enabled = False
            self._generation += 1
            self._governor.disable()

    def consider(self, frame: FrameCue) -> VisionAdmission:
        """Admit an owner-captured frame only with fresh real CPU/GPU/FPS/audio.

        The sample is read in memory; callers must refresh hardware off the
        real-time thread. A cue ('win', etc.) is not verified game success.
        """
        if not isinstance(frame, FrameCue):
            raise TypeError("host-captured FrameCue required")
        with self._lock:
            if not self._enabled:
                self._counters["deferred"] += 1
                return VisionAdmission(False, "owner_opt_in_missing", 0.0)
            now = _now_ms(self._clock)
            sample = self._telemetry.snapshot()
            if sample is None or sample.qos is None:
                self._counters["missing_sensor"] += 1
                self._counters["deferred"] += 1
                return VisionAdmission(False, "trusted_hardware_game_audio_missing", 0.0)
            decision: ObservationDecision = self._governor.consider(
                frame, sample.telemetry, now_ms=now, capture_authorized=True
            )
            if not decision.admitted:
                self._counters["deferred"] += 1
                return VisionAdmission(False, decision.reason, decision.target_fps)
            assert decision.ticket is not None
            lease = VisionLease(
                generation=self._generation,
                ticket=decision.ticket,
                expires_ms=now + self._governor.ticket_timeout_ms,
            )
            self._leases[lease.ticket] = lease
            self._counters["admitted"] += 1
            return VisionAdmission(True, decision.reason, decision.target_fps, lease)

    def consider_pixels(
        self, pixels: bytes | bytearray | memoryview, *, captured_ms: float,
        width: int, height: int, pixel_format: str = "BGRA",
        row_stride: int | None = None, cue: str = "none",
        game_region: Region | None = None, hud_region: Region | None = None,
    ) -> VisionAdmission:
        """Use CPU fingerprints on an existing approved host-captured frame.

        No capture or copy is performed. For raw frame pixels from Windows/OBS,
        this provides the missing local CPU sensor between capture and the
        ordinary measured hardware + novelty admission path. It does NOT
        allow viewer/model-provided crops to override host capture scopes.
        """
        with self._lock:
            if not self._enabled:
                # Never inspect disabled-session image buffers.
                self._counters["deferred"] += 1
                return VisionAdmission(False, "owner_opt_in_missing", 0.0)
            frame = FrameCue.from_pixels(
                captured_ms, pixels, width=width, height=height,
                pixel_format=pixel_format, row_stride=row_stride, cue=cue,
                game_region=game_region, hud_region=hud_region,
            )
            return self.consider(frame)

    def acknowledge_worker_stopped(
        self, lease: VisionLease, *, worker_stopped: bool,
        succeeded: bool = False,
    ) -> bool:
        """Release a worker only after the host confirms it stopped.

        Returns True only for a timely, successful result in this live session.
        Expired or disabled-session work is released but NEVER accepted.
        Do not use model-reported 'finished' or a cancellation request as proof.
        """
        if not isinstance(lease, VisionLease):
            raise TypeError("expected issued VisionLease")
        if type(worker_stopped) is not bool or type(succeeded) is not bool:
            raise TypeError("explicit host worker-stopped and success flags required")
        with self._lock:
            if self._leases.get(lease.ticket) is not lease:
                self._counters["stale_lease"] += 1
                return False
            if not worker_stopped:
                return False
            now = _now_ms(self._clock)
            timely = self._enabled and lease.generation == self._generation
            accepted = self._governor.complete(
                ticket=lease.ticket, now_ms=now,
                succeeded=succeeded and timely,
            )
            # complete() can fail on timeout/disable. Only trusted physical
            # stop acknowledgment releases the quarantine in that case.
            if not accepted:
                released = self._governor.acknowledge_worker_stopped(
                    ticket=lease.ticket, now_ms=now, worker_stopped=True
                )
                if not released:
                    raise RuntimeError("vision lease/worker state inconsistent; keep quarantined")
            del self._leases[lease.ticket]
            self._counters["stopped"] += 1
            if accepted and succeeded and timely:
                self._counters["completed"] += 1
                return True
            self._counters["discarded"] += 1
            return False

    def status(self) -> dict[str, int | bool]:
        """Only anonymous counters; never frames, fingerprints, chat, identities."""
        with self._lock:
            return {
                **self._counters, "enabled": self._enabled,
                "inflight": bool(self._leases),
                "quarantined": self._governor.stats()["quarantined"],
            }


__all__ = ["StreamVisionHost", "VisionLease", "VisionAdmission"]
