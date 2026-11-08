"""Owner-only interlock: fresh signed game telemetry is a prerequisite for input.

Compose the already authenticated, continuously supervised game-state receiver
with Star's OBS-guarded, one-use actuation adapter. This component does not
authorize play, synthesize gameplay, call a model, inject keys, start OBS, or
broadcast. It must live in a TRUSTED host, never in a language-model tool.

There are three independent gates:
  * engine frames: pinned, authenticated and supervised continuously;
  * actions: exact single-use OBS/host-focus verified permits;
  * physical input: host-provided cancellation and independent key-up checks.

Unlike a general purpose watchdog, this interlock links a telemetry outage
directly to actuation.stop(), without waiting for a new game frame or model
answer. It does not survive a process crash and cannot replace an independent
OS watchdog / physical release verification.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from threading import Event, Lock

from .game_action_gate import ActionPermit
from .game_action_outcome_feedback import (
    ActionFeedback, GameActionOutcomeFeedback,
)
from .game_actuation_rehearsal import ActuationResult, GameActuationRehearsal
from .game_state_transition_witness import AttestedGameMoment
from .game_telemetry_liveness_guard import (
    GameTelemetryLivenessGuard, GameTelemetryLivenessLost,
)
from .game_telemetry_tick_supervisor import GameTelemetryTickSupervisor

_SCOPE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")


@dataclass(frozen=True)
class InterlockStatus:
    active: bool
    frames: int
    moments: int
    revoked: bool
    authorizes_gameplay: bool = False
    authorizes_broadcast: bool = False


class TelemetryActuationInterlock:
    """One-way emergency stop for a single owner-approved game episode.

    The caller must first independently enable a trusted signed source, bridge,
    journal, observer, liveness guard, and an OBS-guarded game episode. The
    observer must be scoped to the same owner-controlled game as the episode.
    A signed frame authenticates the reporting source, NOT that the source
    truthfully reports the game or that a physical key is up.

    run() refuses to attempt a key until a real source packet has arrived.
    The host must still enforce the cancellation Event AT the native injection
    edge; a host thread cannot atomically halt another process's Win32 call.
    """

    def __init__(
        self, *,
        guard: GameTelemetryLivenessGuard,
        actuation: GameActuationRehearsal,
        expected_game_scope: str,
        tick_interval_s: float = 0.02,
        outcome_feedback: GameActionOutcomeFeedback | None = None,
    ) -> None:
        if not isinstance(guard, GameTelemetryLivenessGuard):
            raise TypeError("trusted signed-telemetry guard required")
        if not isinstance(actuation, GameActuationRehearsal):
            raise TypeError("trusted game actuation adapter required")
        if type(expected_game_scope) is not str or _SCOPE.fullmatch(expected_game_scope) is None:
            raise ValueError("expected_game_scope must be a bounded canonical ID")
        if (guard.game_scope != expected_game_scope
                or actuation.game_scope != expected_game_scope):
            raise ValueError("telemetry and OBS episode must target the same approved game")
        if outcome_feedback is not None and (
            not isinstance(outcome_feedback, GameActionOutcomeFeedback)
            or outcome_feedback.game_scope != expected_game_scope
        ):
            raise ValueError("outcome feedback must match approved game scope")
        self._outcomes = outcome_feedback
        self._scope = expected_game_scope
        self._actuation = actuation
        self._stopped = Event()
        self._lock = Lock()
        self._started = False
        self._ever_started = False
        self._moments = 0
        self._supervisor = GameTelemetryTickSupervisor(
            guard, interval_s=tick_interval_s, on_lost=self._telemetry_lost,
        )

    def _telemetry_lost(self) -> None:
        """Tick-thread callback: latch cancellation before requesting key-up."""
        self._stopped.set()
        if self._outcomes is not None:
            self._outcomes.revoke()
        self._actuation.stop()

    def start(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner must independently approve the rehearsal")
        with self._lock:
            if self._ever_started or self._stopped.is_set():
                raise RuntimeError("interlock is single-use")
            self._ever_started = True
        try:
            # Start input authorization only after OBS game episode is active.
            self._actuation.enable(owner_approved=True)
            self._supervisor.start(owner_approved=True)
            if self._stopped.is_set():
                raise GameTelemetryLivenessLost("telemetry failed during startup")
            with self._lock:
                self._started = True
        except Exception:
            self.stop()
            raise

    def _ready(self) -> bool:
        return self._started and not self._stopped.is_set()

    def accept(self, packet: bytes) -> AttestedGameMoment | None:
        """Only the private host may ingest authenticated engine observations."""
        if not self._ready():
            raise GameTelemetryLivenessLost("telemetry-actuation interlock inactive")
        try:
            moment = self._supervisor.accept(packet)
            # A matching source/session MAC alone cannot bind the OBS episode
            # to the game. The host pins this scope and checks attested moments.
            if moment is not None and moment.moment.game_scope != self._scope:
                raise GameTelemetryLivenessLost("signed game scope mismatch")
            if self._stopped.is_set():
                raise GameTelemetryLivenessLost("telemetry-actuation interlock stopped")
            if moment is not None and self._outcomes is not None:
                self._outcomes.observe(moment)
            if moment is not None:
                with self._lock:
                    self._moments += 1
            return moment
        except Exception:
            self.stop()
            raise GameTelemetryLivenessLost("telemetry-actuation session revoked") from None

    def run(self, permit: ActionPermit) -> ActuationResult:
        """Attempt one permit only with current telemetry and host checks.

        No successful return is possible after a concurrent source outage.
        The underlying adapter always owns final OS key-up verification.
        """
        if not self._ready():
            return ActuationResult("telemetry_unavailable")
        try:
            before = self._supervisor.health()
            if not before.active or before.accepted_frames == 0:
                return ActuationResult("telemetry_not_established")
            if self._stopped.is_set():
                raise GameTelemetryLivenessLost("telemetry stopped before action")
        except Exception:
            self.stop()
            return ActuationResult("telemetry_unavailable")

        if self._outcomes is not None:
            try:
                if not self._outcomes.ready():
                    return ActuationResult("previous_outcome_pending")
            except Exception:
                self.stop()
                return ActuationResult("outcome_feedback_unavailable")

        try:
            result = self._actuation.run(permit)
        except Exception:
            self.stop()
            return ActuationResult("input_adapter_failed")

        if result.status != "released_verified":
            self.stop()
            return result
        try:
            # A healthy preflight does NOT imply the source stayed alive while
            # native input was running. Check the same receiver after key-up.
            if self._stopped.is_set() or not self._supervisor.health().active:
                raise GameTelemetryLivenessLost("telemetry failed during input")
        except Exception:
            self.stop()
            return ActuationResult("telemetry_lost_during_action", claimed=result.claimed)
        if self._outcomes is not None:
            try:
                # Begin only AFTER a genuine release receipt and the final
                # telemetry postflight. Never infer that input changed game.
                self._outcomes.begin(permit, result, host_confirmed=True)
            except Exception:
                self.stop()
                return ActuationResult("outcome_feedback_unavailable", claimed=result.claimed)
        return result

    def outcome_feedback(self) -> ActionFeedback | None:
        """Host-only post-action evidence, never a skill or victory receipt."""
        if self._outcomes is None:
            return None
        if self._stopped.is_set():
            return ActionFeedback("revoked")
        try:
            return self._outcomes.snapshot()
        except Exception:
            self.stop()
            return ActionFeedback("revoked")

    def stop(self) -> None:
        """Permanent fail-closed shutdown; no automatic source reconnection."""
        self._stopped.set()
        if self._outcomes is not None:
            self._outcomes.revoke()
        try:
            self._actuation.stop()
        finally:
            self._supervisor.stop()

    def status(self) -> InterlockStatus:
        report = self._supervisor.metrics()
        with self._lock:
            moments = self._moments
            started = self._started
        return InterlockStatus(
            active=started and not self._stopped.is_set() and report.active,
            frames=report.accepted_frames,
            moments=moments,
            revoked=self._stopped.is_set() or report.revoked,
        )


__all__ = ["TelemetryActuationInterlock", "InterlockStatus"]
