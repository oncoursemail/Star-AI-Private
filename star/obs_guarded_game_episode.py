"""Opt-in trusted-host bridge: OBS epoch fences for advisory game actions.

This module deliberately does not drive a game, launch a model, or publish a
stream. A trusted Windows host supplies captured frames, workload telemetry,
a focus probe, a permission probe, worker cancellation and key-release hooks.
The model must never be allowed to construct this bridge or call its methods.

One authenticated OBS witness is bound to exactly one game episode. Every
offer, finish, and final claim re-samples it on the same ordered WebSocket;
a lost witness permanently revokes the episode and requests key release.
A successful claim is advisory, NOT permission to dispatch input without an
independent physical-edge focus check and a key-up watchdog.
"""
from __future__ import annotations

from threading import Event, Lock, RLock
import time
from typing import Callable, Sequence

from .game_action_gate import (
    ActionPermit, GameActionHint, GameFrame, GameScope,
)
from .game_realtime_loop import GameThinkLease, RealtimeGameLoop
from .obs_stream_event_witness import (
    ObsGameStreamEpochSource, ObsGameStreamSnapshot,
)
from .stream_budget import StreamTelemetry
from .stream_load_governor import StreamLoadGovernor


class ObsGuardedGameError(RuntimeError):
    """Sanitized terminal error: no credentials, pixels or game data."""


class ObsGuardedGameEpisode:
    """Single-use host-only integration between OBS evidence and game lease.

    The host MUST ensure that its release_keys callback independently requests
    all keys/buttons up, including keys pressed by earlier actions. The host
    MUST enforce a separate physical key-hold watchdog and never use the
    callback's return as evidence of completed release.

    This object does not attest frame authenticity, monitor OS focus, or
    physically inject input. The trusted host owns those separate sources.
    """

    def __init__(
        self, *,
        witness: ObsGameStreamEpochSource,
        loop: RealtimeGameLoop,
        focus_probe: Callable[[], bool],
        permission_probe: Callable[[], bool],
        release_keys: Callable[[], None],
        cancel_inference: Callable[[], None],
        clock_ms: Callable[[], float] = lambda: time.monotonic() * 1000,
    ) -> None:
        if not isinstance(witness, ObsGameStreamEpochSource):
            raise TypeError("expected an OBS game-event witness")
        if not isinstance(loop, RealtimeGameLoop):
            raise TypeError("expected a realtime game loop")
        if not all(callable(fn) for fn in (
            focus_probe, permission_probe, release_keys, cancel_inference, clock_ms,
        )):
            raise TypeError("trusted host callbacks are required")
        self._witness = witness
        self._loop = loop
        self._focus = focus_probe
        self._permission = permission_probe
        self._release_keys = release_keys
        self._cancel_inference = cancel_inference
        self._clock_ms = clock_ms
        self._lock = RLock()
        # Emergency stop must not wait for a blocked OBS WebSocket read.
        self._stop_requested = Event()
        self._cleanup_lock = Lock()
        self._cleanup_requested = False
        self._game_scope: GameScope | None = None
        self._ever_started = False
        self._active = False
        self._revoked = False

    @property
    def game_scope(self) -> str | None:
        """Immutable, owner-approved OBS game scope once started."""
        scope = self._game_scope
        return scope.game_id if scope is not None else None

    @property
    def active(self) -> bool:
        if self._stop_requested.is_set():
            return False  # Do not wait for a blocked OBS snapshot.
        with self._lock:
            return self._active and not self._revoked and not self._stop_requested.is_set()

    @property
    def revoked(self) -> bool:
        if self._stop_requested.is_set():
            return True
        with self._lock:
            return self._revoked

    def _request_host_cleanup(self) -> None:
        """Request cancel/key-up once, independently of the OBS sample lock.

        The callbacks themselves MUST be prompt and safe to invoke on the
        host shutdown thread. They are requests, not proof of physical key-up.
        """
        with self._cleanup_lock:
            if self._cleanup_requested:
                return
            self._cleanup_requested = True
        for callback in (self._cancel_inference, self._release_keys):
            try:
                callback()
            except Exception:
                pass

    def _revoke(self) -> None:
        """Request a best-effort halt; NEVER claim worker or key-up completed."""
        self._stop_requested.set()
        if self._revoked:
            return
        self._revoked = True
        self._active = False
        # Request host cancellation before another potentially blocked socket.
        self._request_host_cleanup()
        for callback in (self._loop.stop, self._witness.disconnect):
            try:
                callback()
            except Exception:
                pass  # Failed cleanup is not approval to restart this episode.

    def _assert_active(self) -> None:
        if not self._active or self._revoked or self._stop_requested.is_set():
            raise ObsGuardedGameError("trusted game episode is not active")

    def _snapshot(self) -> ObsGameStreamSnapshot:
        try:
            result = self._witness.snapshot()
            if self._stop_requested.is_set():
                raise ObsGuardedGameError("trusted game episode stopped")
            return result
        except ObsGuardedGameError:
            self._revoke()
            raise
        except Exception:
            self._revoke()
            raise ObsGuardedGameError(
                "trusted OBS game episode revoked: event continuity lost"
            ) from None

    def _execute(self, fn: Callable[[], object]) -> object:
        """Fail closed on invalid host data and callbacks, without leaking it."""
        try:
            result = fn()
            if self._stop_requested.is_set() and not self._revoked:
                self._revoke()
                raise ObsGuardedGameError("trusted game episode stopped")
            return result
        except ObsGuardedGameError:
            self._revoke()
            raise
        except Exception:
            self._revoke()
            raise ObsGuardedGameError(
                "trusted OBS game episode revoked: host verification failed"
            ) from None

    def start(
        self, scope: GameScope, action_ids: Sequence[str], *,
        password: str, owner_approved: bool = False,
    ) -> None:
        if owner_approved is not True:
            raise PermissionError("owner approval required")
        with self._lock:
            if self._ever_started:
                raise ObsGuardedGameError("game episode is single-use")
            self._ever_started = True
            self._game_scope = scope
            def connect_and_start() -> None:
                self._witness.connect(password=password, owner_approved=True)
                self._loop.start(scope, action_ids, owner_approved=True)
                # A verified initial OBS state is required before admitting work.
                self._witness.snapshot()
                self._active = True
            self._execute(connect_and_start)

    def record_reactive_latency(
        self, *, sample_id: int, duration_ms: float,
        host_measured: bool = False, completed: bool = True,
    ) -> bool:
        with self._lock:
            self._assert_active()
            def record() -> bool:
                snapshot = self._snapshot()
                return self._loop.record_reactive_latency(
                    sample_id=sample_id, duration_ms=duration_ms,
                    sample_host_ms=self._clock_ms(),
                    host_measured=host_measured, completed=completed,
                    stream_live=snapshot.stream_live,
                )
            return bool(self._execute(record))

    def offer(
        self, frame: GameFrame, *,
        telemetry: StreamTelemetry | None,
        host_verified: bool = False,
        stream_governor: StreamLoadGovernor | None = None,
        cpu_pressure: bool = False, gpu_pressure: bool = False,
        previous_worker_stopped: bool = False,
    ) -> GameThinkLease:
        with self._lock:
            self._assert_active()
            def offered() -> GameThinkLease:
                snapshot = self._snapshot()
                return self._loop.offer(
                    frame, now_ms=self._clock_ms(),
                    host_verified=host_verified, telemetry=telemetry,
                    stream_live=snapshot.stream_live,
                    stream_epoch=snapshot.epoch,
                    stream_governor=stream_governor,
                    cpu_pressure=cpu_pressure, gpu_pressure=gpu_pressure,
                    previous_worker_stopped=previous_worker_stopped,
                )
            return self._execute(offered)  # type: ignore[return-value]

    def finish(
        self, lease: GameThinkLease, frame: GameFrame,
        hint: GameActionHint, *,
        telemetry: StreamTelemetry | None,
        host_verified: bool = False,
        stream_governor: StreamLoadGovernor | None = None,
        cpu_pressure: bool = False, gpu_pressure: bool = False,
    ) -> ActionPermit:
        with self._lock:
            self._assert_active()
            def finished() -> ActionPermit:
                snapshot = self._snapshot()
                return self._loop.finish(
                    lease, frame, hint, now_ms=self._clock_ms(),
                    host_verified=host_verified, telemetry=telemetry,
                    stream_live=snapshot.stream_live,
                    stream_epoch=snapshot.epoch,
                    stream_governor=stream_governor,
                    cpu_pressure=cpu_pressure, gpu_pressure=gpu_pressure,
                )
            return self._execute(finished)  # type: ignore[return-value]

    def claim(self, permit: ActionPermit) -> bool:
        """Snapshot and independently check permission, immediately at host edge.

        Even True means only a consumed advisory claim. A physical input host
        MUST independently recheck focus/stream and enforce key-up, not treat
        this return as a permanent grant.
        """
        with self._lock:
            self._assert_active()
            def claimed() -> bool:
                snapshot = self._snapshot()
                if self._focus() is not True or self._permission() is not True:
                    self._revoke()
                    return False
                if not self._loop.claim(
                    permit, now_ms=self._clock_ms(),
                    host_focus_and_permission=True,
                    stream_epoch=snapshot.epoch,
                ):
                    # A stale permit or changed OBS epoch is terminal for
                    # this guarded episode; never retry it after a transition.
                    self._revoke()
                    return False
                return True
            return bool(self._execute(claimed))

    def release(
        self, permit: ActionPermit, *, host_confirmed_released: bool = False,
    ) -> bool:
        with self._lock:
            self._assert_active()
            def released() -> bool:
                result = self._loop.release(
                    permit, now_ms=self._clock_ms(),
                    host_confirmed_released=host_confirmed_released,
                )
                if not result:
                    self._revoke()
                return result
            return bool(self._execute(released))

    def stop(self) -> None:
        """Prompt emergency cancel/key-up even while a snapshot is blocked.

        The in-flight operation notices this latch before returning a permit.
        Physical input hosts still need their independent key-up watchdog;
        a callback request is not proof of actual release.
        """
        self._stop_requested.set()
        self._request_host_cleanup()
        # Do not block on a 3-second OBS socket timeout holding this lock.
        # The in-flight _execute() completes revocation once it unwinds.
        if self._lock.acquire(blocking=False):
            try:
                self._revoke()
            finally:
                self._lock.release()


__all__ = ["ObsGuardedGameEpisode", "ObsGuardedGameError"]
