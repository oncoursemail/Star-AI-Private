"""Owner-gated, offline Roblox practice: observe -> propose -> input -> verify.

This is a small integration layer over EXISTING components, not a game-playing
model or independent evaluator. An embedded trusted host must provide
host-measured telemetry/clock, private Studio focus and an independent key-up
watchdog. Suggestions from an LLM are never accepted as game observations,
owner permissions, gameplay results, signing keys, or arbitrary key presses.

Only private Studio PLAYTEST input can flow through StudioPlaytestHost. The
post-action verdict must come from a separate evaluator signing a practice
GameTrial. Missing/unchanged/old visual evidence can never be recorded as a
successful action. One unscored delivery blocks all additional actions.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import math
from threading import RLock
import time
from typing import Awaitable, Callable

from .game_action_gate import GameActionHint, GameFrame, GameScope
from .game_learning_ladder import GameLearningLadder, LadderAdvice
from .gameplay_skill_bank import GameTrial
from .studio_outcome_bridge import OutcomeRecord, StudioOutcomeBridge
from .studio_playtest_host import (
    DeliveredAction, DispatchReport, StudioInputPort, StudioPlaytestHost,
)
from .studio_visual_evidence import StudioVisualObserver, VisualEvidence
from .studio_vision_qos import StudioVisionQoS
from .stream_budget import StreamTelemetry

Clock = Callable[[], float]
TelemetryProbe = Callable[[], StreamTelemetry | None]


@dataclass(frozen=True)
class PracticeProposal:
    """UNTRUSTED narrow suggestion; probability is a diagnostic only."""
    action_id: str
    hold_ms: int
    success_probability_bps: int | None = None  # for pre-action forecast, never an authorization


@dataclass(frozen=True)
class PracticeStep:
    status: str
    reason: str
    situation_id: str | None = None
    action_sent: bool = False
    awaiting_signed_feedback: bool = False


@dataclass
class _Pending:
    report: DispatchReport
    delivery: DeliveredAction
    after: GameFrame | None = None


def _ms(clock: Clock) -> float:
    try:
        value = clock()
    except Exception:
        raise ValueError("trusted monotonic clock unavailable") from None
    if (type(value) not in (int, float)
            or not math.isfinite(float(value))
            or not 0 <= float(value) <= 1e13):
        raise ValueError("trusted monotonic clock invalid")
    return float(value)


class StudioPracticeRunner:
    """Compose evidence, curriculum, protected input and signed results.

    The host must independently arm the StudioVisualObserver and start the
    StudioPlaytestHost with explicit owner consent. The curriculum must also
    be enabled; enabling this runner does not grant any of those permissions.

    Deliberately only ONE outstanding action: if post-action feedback is
    missing, no new input can overwrite the delivery awaiting independent
    evaluation. The host must supply its own keyboard watchdog independently
    of the Python process, including in the event of process termination.
    """

    def __init__(
        self, *,
        scope: GameScope,
        observer: StudioVisualObserver,
        vision: StudioVisionQoS,
        actions: StudioPlaytestHost,
        outcomes: StudioOutcomeBridge,
        ladder: GameLearningLadder,
        port: StudioInputPort,
        telemetry: TelemetryProbe,
        clock_ms: Clock = lambda: time.monotonic() * 1000,
        proposal_timeout_s: float = 0.15,
        feedback_window_ms: int = 12000,
    ) -> None:
        if (not isinstance(scope, GameScope)
                or not isinstance(observer, StudioVisualObserver)
                or not isinstance(vision, StudioVisionQoS)
                or vision._observer is not observer
                or observer._scope != scope
                or not isinstance(actions, StudioPlaytestHost)
                or not isinstance(outcomes, StudioOutcomeBridge)
                or not isinstance(ladder, GameLearningLadder)
                or ladder.game_id != scope.game_id
                or ladder.game_version != scope.version_id
                or not callable(telemetry) or not callable(clock_ms)
                or not all(callable(getattr(port, name, None))
                           for name in ("snapshot", "key_down", "key_up"))):
            raise ValueError("incompatible trusted practice components")
        if (type(proposal_timeout_s) not in (int, float)
                or not math.isfinite(float(proposal_timeout_s))
                or not .02 <= float(proposal_timeout_s) <= .25):
            raise ValueError("proposal timeout must be 0.02..0.25 seconds")
        if type(feedback_window_ms) is not int or not 1000 <= feedback_window_ms <= 12000:
            raise ValueError("feedback window must be 1000..12000 ms")
        self._scope = scope
        self._observer, self._vision = observer, vision
        self._actions, self._outcomes, self._ladder = actions, outcomes, ladder
        self._port, self._telemetry, self._clock = port, telemetry, clock_ms
        self._proposal_timeout = float(proposal_timeout_s)
        self._window = feedback_window_ms
        self._turn_lock = asyncio.Lock()
        self._state_lock = RLock()
        self._enabled = False
        self._generation = 0
        self._pending: _Pending | None = None
        self._attempted = False  # one independently scored attempt per episode/run_id
        self._counts = dict(actions_sent=0, actions_blocked=0, timeouts=0,
                            feedback_collected=0, accepted=0, rejected=0,
                            discarded=0)

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("owner must explicitly enable private Studio practice")
        with self._state_lock:
            if self._enabled or self._pending is not None or self._attempted:
                raise RuntimeError("a new episode scope/runner is needed for another attempt")
            self._enabled = True
            self._generation += 1

    def _sample_telemetry(self) -> StreamTelemetry | None:
        # Called only from the trusted embedding host; no model/chat can
        # provide or mutate telemetry through the proposal API.
        try:
            item = self._telemetry()
        except Exception:
            return None
        if item is None or not isinstance(item, StreamTelemetry):
            return None
        return item

    @staticmethod
    def _practice_capacity(tele: StreamTelemetry | None) -> bool:
        # Conservatively refuse input when broadcasting, no active game,
        # or GPU/audio/game performance is unhealthy.
        return bool(tele is not None and not tele.live and tele.game_active
                    and tele.game_fps >= 50 and tele.free_vram_mib >= 1536
                    and tele.speech_backlog_ms <= 250)

    def _blocked(self, reason: str, situation: str | None = None) -> PracticeStep:
        self._counts["actions_blocked"] += 1
        return PracticeStep("deferred", reason, situation)

    async def take_step(
        self, proposer: Callable[[VisualEvidence, LadderAdvice], Awaitable[PracticeProposal]],
        *, now_unix_s: int,
        dispatch_guard: Callable[[], bool] | None = None,
    ) -> PracticeStep:
        """At most one approved input pulse; no auto evaluation or repeat loop.

        The UNTRUSTED proposer receives only bounded summaries, scoped frame
        metadata, and one curriculum suggestion. It cannot set the frame,
        session, game result, signature, focus/permission, telemetry or raw keys.
        """
        if not callable(proposer):
            raise TypeError("proposer must be async callable")
        if dispatch_guard is not None and not callable(dispatch_guard):
            raise TypeError("dispatch_guard must be trusted host callable")
        async with self._turn_lock:
            with self._state_lock:
                if not self._enabled:
                    return self._blocked("owner_practice_runner_disabled")
                if self._pending is not None:
                    return self._blocked("independent_feedback_pending")
                if self._attempted:
                    return self._blocked("episode_attempt_already_consumed")
                generation = self._generation
            tele = self._sample_telemetry()
            if not self._practice_capacity(tele):
                return self._blocked("offline_game_or_realtime_headroom_missing")
            advice = self._ladder.recommend(now_unix_s=now_unix_s, telemetry=tele)
            if advice.status != "practice_candidate" or not advice.action_id:
                return self._blocked("curriculum_" + advice.status)
            sampled = await self._vision.sample(tele)
            if (sampled.evidence is None or not sampled.evidence.changed
                    or not sampled.evidence.actionable_when_captured):
                return self._blocked("fresh_visual_evidence_missing", advice.situation_id)
            evidence = sampled.evidence
            if evidence.frame.scope != self._scope:
                return self._blocked("wrong_game_scope", advice.situation_id)
            try:
                proposal = await asyncio.wait_for(
                    proposer(evidence, advice), timeout=self._proposal_timeout)
            except asyncio.TimeoutError:
                self._counts["timeouts"] += 1
                return self._blocked("proposal_deadline_exceeded", advice.situation_id)
            except Exception:
                return self._blocked("proposal_unavailable", advice.situation_id)
            if (not isinstance(proposal, PracticeProposal)
                    or type(proposal.action_id) is not str
                    or proposal.action_id != advice.action_id
                    or type(proposal.hold_ms) is not int
                    or not 1 <= proposal.hold_ms <= 180
                    or (proposal.success_probability_bps is not None
                        and (type(proposal.success_probability_bps) is not int
                             or not 1 <= proposal.success_probability_bps <= 9999))):
                return self._blocked("untrusted_or_off_curriculum_action", advice.situation_id)
            tele = self._sample_telemetry()  # remeasure AFTER model inference
            if not self._practice_capacity(tele):
                return self._blocked("realtime_pressure_before_input", advice.situation_id)
            with self._state_lock:
                if not self._enabled or generation != self._generation:
                    return self._blocked("practice_revoked_before_input", advice.situation_id)
                if self._pending is not None or self._attempted:
                    return self._blocked("episode_attempt_already_consumed")
                # Second independent private-focus check closes a focus
                # change while the model was deliberating. Dispatch still
                # performs its own host-attested StudioSnapshot preflights.
                try:
                    if not self._observer.metrics()["armed"]:
                        return self._blocked("visual_authorization_revoked")
                    self._observer._private()
                except Exception:
                    return self._blocked("private_focus_revoked_before_input")
                # A trusted scheduler may revoke an episode while slow model
                # inference is in progress. Recheck immediately before input.
                # This callback has no authority to grant a Studio permit.
                if dispatch_guard is not None:
                    try:
                        if dispatch_guard() is not True:
                            return self._blocked("portfolio_reservation_revoked",
                                                 advice.situation_id)
                    except Exception:
                        return self._blocked("portfolio_reservation_unavailable",
                                             advice.situation_id)
                now = _ms(self._clock)
                hint = GameActionHint(
                    proposal.action_id, evidence.frame.sequence,
                    evidence.frame.evidence_sha256, now, proposal.hold_ms)
                permit = self._actions.request(
                    evidence.frame, hint, now_ms=now,
                    host_verified=True, telemetry=tele)
                if not permit.offered:
                    return self._blocked("game_action_gate_" + permit.reason,
                                         advice.situation_id)
                # Synchronous private-Studio pulse; not allowed while live.
                # Lock serializes an owner STOP from another host thread.
                # Also enforce revocation *inside* the physical input host:
                # its second Studio focus snapshot may block after our check.
                report = self._actions.dispatch(
                    permit, port=self._port, dispatch_guard=dispatch_guard)
                if not report.sent or not report.input_released:
                    return self._blocked("studio_input_" + report.reason,
                                         advice.situation_id)
                delivery = self._actions.inspect_delivery(report)
                if delivery is None or delivery.scope != self._scope:
                    return self._blocked("trusted_delivery_missing",
                                         advice.situation_id)
                self._pending = _Pending(report, delivery)
                self._attempted = True
                self._counts["actions_sent"] += 1
                return PracticeStep("action_sent", "await_independent_game_result",
                                    advice.situation_id, True, True)

    async def observe_after(self) -> PracticeStep:
        """Collect *real* changed post-input visual evidence for external scoring.

        No verdict, success, or signature is generated here. Private and
        timing checks remain enforced by the underlying observer and QoS.
        """
        async with self._turn_lock:
            with self._state_lock:
                pending = self._pending
                generation = self._generation
                if not self._enabled or pending is None:
                    return self._blocked("no_active_delivered_action")
                if pending.after is not None:
                    return PracticeStep("feedback_ready", "independent_scoring_required",
                                        awaiting_signed_feedback=True)
                elapsed = _ms(self._clock) - pending.delivery.released_ms
                if elapsed < 0 or elapsed > self._window:
                    self._discard_unlocked()
                    return self._blocked("post_action_feedback_expired")
            tele = self._sample_telemetry()
            if not self._practice_capacity(tele):
                return self._blocked("offline_game_or_realtime_headroom_missing")
            sample = await self._vision.sample(tele)
            with self._state_lock:
                if not self._enabled or generation != self._generation or self._pending is not pending:
                    return self._blocked("practice_revoked_during_observation")
                elapsed = _ms(self._clock) - pending.delivery.released_ms
                if elapsed < 0 or elapsed > self._window:
                    self._discard_unlocked()
                    return self._blocked("post_action_feedback_expired")
                if (sample.evidence is None or not sample.evidence.changed
                        or sample.evidence.frame.scope != self._scope
                        or sample.evidence.frame.sequence <= pending.delivery.frame_sequence
                        or sample.evidence.frame.captured_ms < pending.delivery.released_ms
                        or sample.evidence.frame.perception_confidence < .75):
                    return self._blocked("usable_post_action_scene_missing")
                pending.after = sample.evidence.frame
                self._counts["feedback_collected"] += 1
                return PracticeStep("feedback_ready", "independent_scoring_required",
                                    awaiting_signed_feedback=True)

    def evidence_for_evaluator(self) -> tuple[DeliveredAction, GameFrame] | None:
        """Read-only input/observation facts for a separately trusted evaluator.

        Returned values cannot sign an outcome; the evaluator, not this class
        or the model, owns the isolated scoring/verdict key.
        """
        with self._state_lock:
            p = self._pending
            if not self._enabled or p is None or p.after is None:
                return None
            return p.delivery, p.after

    def record_signed_outcome(
        self, trial: GameTrial, receipt: str, *, now_unix_s: int,
    ) -> OutcomeRecord:
        """Consume one independently signed PRACTICE verdict, never self-score."""
        with self._state_lock:
            p = self._pending
            if not self._enabled or p is None or p.after is None:
                raise PermissionError("a real post-action observation is required")
            # One-shot even when a verdict is invalid, so a forged failure
            # cannot be replaced by a different forged success for this action.
            now = _ms(self._clock)
            self._pending = None
            try:
                result = self._outcomes.record(
                    host=self._actions, dispatch=p.report, after=p.after,
                    trial=trial, host_verified_after=True,
                    signed_practice_receipt=receipt,
                    now_ms=now, now_unix_s=now_unix_s)
            except (TypeError, ValueError, PermissionError, OverflowError):
                self._counts["rejected"] += 1
                raise
            self._counts["accepted"] += 1
            return result

    def _discard_unlocked(self) -> bool:
        p = self._pending
        self._pending = None
        if p is None:
            return False
        # Never mark an unverified action successful. A consumed delivery
        # prevents it from being recorded later or overwritten silently.
        self._actions.claim_delivery(p.report)
        self._counts["discarded"] += 1
        return True

    def discard_unverified(self) -> bool:
        with self._state_lock:
            return self._discard_unlocked()

    def stop(self) -> bool:
        """Host-initiated STOP. Independent watchdog remains mandatory."""
        with self._state_lock:
            self._enabled = False
            self._generation += 1
            self._observer.disarm()
            self._ladder.disable()
            self._discard_unlocked()
            return self._actions.revoke(port=self._port)

    def metrics(self) -> dict[str, int | bool]:
        """No model text, game frame, screenshot, chat, player, or secret."""
        with self._state_lock:
            return {**self._counts, "enabled": self._enabled,
                    "feedback_pending": self._pending is not None,
                    "episode_attempted": self._attempted}


__all__ = ["StudioPracticeRunner", "PracticeProposal", "PracticeStep"]
