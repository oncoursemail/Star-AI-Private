"""Opt-in trusted-host actuation bridge with independent key-up confirmation.

Connects an OBS-guarded advisory game permit to a *host-owned* input port.
This file contains no keyboard/mouse injection and never launches a game.
Only a private Windows host may provide the callbacks; a language model,
viewer message or game screen must never be able to obtain this capability.

WARNING: Python checks cannot make an asynchronous physical key write atomic
with shutdown. The native port MUST atomically check the cancellation fence
at its actual injection edge, provide a separate out-of-process maximum-key-
hold watchdog, and independently verify all keys/buttons are physically up.
A passing simulated test is not proof those Windows requirements are met.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from threading import Event, Lock
import time
from typing import Callable

from .game_action_gate import ActionPermit
from .obs_guarded_game_episode import ObsGuardedGameEpisode


@dataclass(frozen=True)
class ActuationResult:
    """Sanitized outcome: no game pixels, device names, credentials or chat."""

    status: str
    claimed: bool = False
    keys_up_verified: bool = False


class GameActuationRehearsal:
    """One host-owned actuation path, disabled until explicit owner approval.

    run() consumes the ORIGINAL, one-time ActionPermit issued by the guarded
    episode. It rechecks owner/game focus, invokes the episode's authenticated
    OBS-epoch claim, and rechecks host focus before touching the input port.

    The input port is responsible for its own atomic cancellation fence and
    physical max-hold deadline. request_all_up must be prompt, callable from
    any thread, and independent of blocked OBS or input-port calls.

    The all_keys_up probe must read the *actual OS/device state* for ALL keys
    and buttons this port can hold. Merely returning 'sent release' is NOT a
    release receipt. A false/missing receipt permanently stops this episode.

    This is a bridge, not a ready-to-use Windows input implementation. There
    is deliberately no default send_action or default release-state probe.
    """

    def __init__(
        self, *, episode: ObsGuardedGameEpisode,
        send_action: Callable[[str, int, Event], bool],
        request_all_up: Callable[[], None],
        all_keys_up: Callable[[], bool],
        focus_probe: Callable[[], bool],
        permission_probe: Callable[[], bool],
        clock_ms: Callable[[], float] = lambda: time.monotonic() * 1000,
        max_dispatch_ms: int = 500,
    ) -> None:
        if not isinstance(episode, ObsGuardedGameEpisode):
            raise TypeError("a trusted OBS game episode is required")
        if not all(callable(fn) for fn in (
            send_action, request_all_up, all_keys_up,
            focus_probe, permission_probe, clock_ms,
        )):
            raise TypeError("all native host hooks are required")
        if type(max_dispatch_ms) is not int or not 80 <= max_dispatch_ms <= 1000:
            raise ValueError("maximum dispatch window must be 80..1000 ms")
        self._episode = episode
        self._send_action = send_action
        self._request_all_up = request_all_up
        self._all_keys_up = all_keys_up
        self._focus = focus_probe
        self._permission = permission_probe
        self._clock = clock_ms
        self._max_dispatch_ms = max_dispatch_ms
        self._cancelled = Event()
        self._run_lock = Lock()
        self._stop_lock = Lock()
        self._enabled = False
        self._ever_enabled = False

    @property
    def game_scope(self) -> str | None:
        """Host-pinned game identity from the OBS-guarded episode."""
        return self._episode.game_scope

    @property
    def stopped(self) -> bool:
        return self._cancelled.is_set()

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner approval required for host input")
        with self._stop_lock:
            if self._cancelled.is_set() or self._ever_enabled:
                raise RuntimeError("use a fresh host adapter for each game episode")
            if not self._episode.active:
                raise RuntimeError("a live trusted game episode is required")
            self._ever_enabled = True
            self._enabled = True

    def _host_allowed(self) -> bool:
        try:
            return (
                self._focus() is True
                and self._permission() is True
                and not self._cancelled.is_set()
            )
        except Exception:
            return False

    def _clock_ms(self) -> float:
        try:
            value = self._clock()
            if type(value) not in (int, float):
                raise ValueError
            number = float(value)
            if not math.isfinite(number) or not 0 <= number <= 1e13:
                raise ValueError
            return number
        except Exception:
            raise ValueError("trusted monotonic clock unavailable") from None

    def _request_key_release(self) -> None:
        try:
            self._request_all_up()
        except Exception:
            pass  # Absence of a receipt remains terminal; never claim success.

    def stop(self) -> None:
        """Emergency latch without waiting for OBS or the input-port mutex.

        Synchronously requests a host-wide key-up and revokes the OBS episode.
        The callback is a REQUEST; only the independent probe can attest up.
        """
        self._cancelled.set()
        self._enabled = False
        self._request_key_release()
        try:
            self._episode.stop()
        except Exception:
            pass

    def run(self, permit: ActionPermit) -> ActuationResult:
        """Attempt exactly one host-bound permit and verify physical key-up.

        No caller can bypass the episode's exact-object claim. All failures
        become a terminal owner-stop; errors are deliberately sanitized.
        A native host must still implement its own out-of-process watchdog.
        """
        if not self._enabled or self._cancelled.is_set():
            return ActuationResult("disabled")
        if not self._run_lock.acquire(blocking=False):
            return ActuationResult("busy")
        claimed = False
        try:
            if self._cancelled.is_set() or not self._enabled:
                return ActuationResult("disabled")
            if (not isinstance(permit, ActionPermit) or permit.offered is not True
                    or type(permit.action_id) is not str
                    or type(permit.hold_ms) is not int
                    or not 1 <= permit.hold_ms <= 180):
                self.stop()
                return ActuationResult("invalid_permit")
            if not self._host_allowed():
                self.stop()
                return ActuationResult("host_denied")
            try:
                start_ms = self._clock_ms()
            except ValueError:
                self.stop()
                return ActuationResult("clock_failed")
            try:
                claimed = self._episode.claim(permit) is True
            except Exception:
                claimed = False
            if not claimed or self._cancelled.is_set():
                self.stop()
                return ActuationResult("claim_rejected")
            # Recheck after a potentially slow authenticated OBS snapshot.
            if not self._host_allowed():
                self.stop()
                return ActuationResult("host_denied", claimed=True)
            try:
                dispatched = self._send_action(
                    permit.action_id, permit.hold_ms, self._cancelled
                ) is True
            except Exception:
                dispatched = False
            if self._cancelled.is_set():
                self.stop()
                return ActuationResult("stopped_during_dispatch", claimed=True)
            if not dispatched:
                self.stop()
                return ActuationResult("dispatch_failed", claimed=True)
            # Native port must guarantee release at its own max-hold deadline.
            # No advisory release is acknowledged without this independent probe.
            self._request_key_release()
            try:
                physical_up = self._all_keys_up() is True
                elapsed = self._clock_ms() - start_ms
                deadline_ok = 0 <= elapsed <= self._max_dispatch_ms
            except Exception:
                physical_up = False
                deadline_ok = False
            if self._cancelled.is_set():
                self.stop()
                return ActuationResult("stopped_during_dispatch", claimed=True)
            if not physical_up:
                self.stop()
                return ActuationResult("release_unverified", claimed=True)
            if not deadline_ok:
                self.stop()
                return ActuationResult("dispatch_deadline_exceeded", claimed=True)
            try:
                released = self._episode.release(
                    permit, host_confirmed_released=True
                ) is True
            except Exception:
                released = False
            if not released or self._cancelled.is_set():
                self.stop()
                return ActuationResult("release_rejected", claimed=True)
            return ActuationResult(
                "released_verified", claimed=True, keys_up_verified=True
            )
        finally:
            self._run_lock.release()


__all__ = ["GameActuationRehearsal", "ActuationResult"]
