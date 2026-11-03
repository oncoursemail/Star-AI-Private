"""Trusted-host liveness fence for signed game-engine telemetry.

The signed source and authenticated receiver verify *messages*, but neither can
notice a silent transport unless a trusted host checks the time. This opt-in
wrapper refuses late frames, revokes the verified observer and erases the
private journal after silence, and prevents a delayed frame from reviving it.

IMPORTANT: arm()/accept()/check() belong in the isolated receiver host, never
in a model tool or viewer API. The receiver host MUST schedule check() using
its own watchdog even when no packets arrive. This class is not an OS process
watchdog, independent game-engine attestation, IPC transport, or proof of safe
Windows input. If the whole host crashes, only an external supervisor can
stop physical actions or audio.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from threading import RLock
import time
from typing import Callable

from .game_state_transition_witness import AttestedGameMoment
from .game_telemetry_source_bridge import AuthenticatedGameTelemetryBridge


class GameTelemetryLivenessLost(RuntimeError):
    """Receiver's observation continuity is gone; create a fresh session."""


@dataclass(frozen=True)
class LivenessMetrics:
    active: bool
    accepted_frames: int
    checks: int
    revoked: bool


class GameTelemetryLivenessGuard:
    """Fail-closed receiver-side silence/clock/ingest deadline fence.

    max_silence_s covers the interval from arming to the first valid packet,
    and between successive valid packets. max_ingest_ms bounds a successful
    bridge.accept() call. The protected bridge MUST NOT be accessed directly
    by any other telemetry ingestion path after arming.

    A successful accept() never starts speech or streaming. This guard must be
    driven by an independent host-owned periodic check, ideally much more
    frequently than max_silence_s.
    """

    def __init__(
        self,
        bridge: AuthenticatedGameTelemetryBridge,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_silence_s: float = 1.0,
        max_ingest_ms: float = 150.0,
    ) -> None:
        if not isinstance(bridge, AuthenticatedGameTelemetryBridge):
            raise TypeError("authenticated telemetry bridge required")
        if not callable(clock):
            raise TypeError("trusted monotonic clock required")
        if (type(max_silence_s) not in (int, float)
                or not math.isfinite(max_silence_s)
                or not 0.05 <= max_silence_s <= 10.0):
            raise ValueError("max_silence_s must be 0.05..10")
        if (type(max_ingest_ms) not in (int, float)
                or not math.isfinite(max_ingest_ms)
                or not 1.0 <= max_ingest_ms <= 1000.0):
            raise ValueError("max_ingest_ms must be 1..1000")
        self._bridge = bridge
        self._clock = clock
        self._silence_s = float(max_silence_s)
        self._ingest_s = float(max_ingest_ms) / 1000.0
        self._lock = RLock()
        self._armed = False
        self._ever_armed = False
        self._revoked = False
        self._last_frame_at: float | None = None
        self._last_check_at: float | None = None
        self._frames = 0
        self._checks = 0

    def _revoke(self) -> None:
        """Erase protected memories on any ambiguous transport state."""
        self._armed = False
        self._revoked = True
        self._last_frame_at = None
        try:
            self._bridge.disable()
        except Exception:
            # A broken bridge must not make the liveness fence appear active.
            pass

    def _fail(self) -> None:
        self._revoke()
        raise GameTelemetryLivenessLost(
            "game telemetry freshness lost: session revoked"
        ) from None

    def _now(self) -> float:
        try:
            candidate = self._clock()
            if type(candidate) not in (int, float):
                raise ValueError
            now = float(candidate)
            if not math.isfinite(now) or not 0 <= now <= 1e13:
                raise ValueError
            if self._last_check_at is not None and now < self._last_check_at:
                raise ValueError
        except Exception:
            self._fail()
        self._last_check_at = now
        return now

    @property
    def game_scope(self) -> str:
        """Pinned source game identity, not an authorization to control it."""
        return self._bridge.game_scope

    @property
    def silence_limit_s(self) -> float:
        """Configured receiver deadline, for trusted host tick scheduling."""
        return self._silence_s

    def arm(self, *, owner_approved: bool = False) -> None:
        """Arm once after enabling the independent witness and source bridge."""
        if owner_approved is not True:
            raise PermissionError("owner approval required for telemetry liveness")
        with self._lock:
            if self._ever_armed or self._revoked or not self._bridge.active:
                raise GameTelemetryLivenessLost("liveness session cannot be armed")
            now = self._now()
            self._last_frame_at = now
            self._armed = True
            self._ever_armed = True

    def _check(self) -> float:
        if not self._armed or self._revoked:
            raise GameTelemetryLivenessLost("liveness session is not active")
        now = self._now()
        previous = self._last_frame_at
        if (not self._bridge.active or previous is None
                or now - previous > self._silence_s):
            self._fail()
        return now

    def check(self) -> LivenessMetrics:
        """Host watchdog tick; MUST be called periodically even during silence."""
        with self._lock:
            self._check()
            self._checks += 1
            return self.metrics()

    def accept(self, packet: bytes) -> AttestedGameMoment | None:
        """Accept at most one fresh authenticated frame through the bridge."""
        with self._lock:
            started = self._check()
            try:
                event = self._bridge.accept(packet)
            except Exception:
                self._fail()
            finished = self._now()
            # If a synchronous bridge call blocks, it must not grant itself a
            # new silence window based on its pre-call start timestamp.
            if (finished - started > self._ingest_s
                    or self._last_frame_at is None
                    or finished - self._last_frame_at > self._silence_s
                    or not self._bridge.active):
                self._fail()
            self._last_frame_at = finished
            self._frames += 1
            return event

    def disable(self) -> None:
        with self._lock:
            self._revoke()

    def metrics(self) -> LivenessMetrics:
        with self._lock:
            return LivenessMetrics(
                self._armed and not self._revoked and self._bridge.active,
                self._frames, self._checks, self._revoked,
            )


__all__ = [
    "GameTelemetryLivenessGuard", "GameTelemetryLivenessLost",
    "LivenessMetrics",
]
