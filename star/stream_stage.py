"""An opt-in stage manager linking Star's stream decisions to *heard* audio and avatar cues.

This pure-Python module has no OBS, VTube Studio, microphone, chat, input-control
or network access. A trusted host drives it with clocks, moderated observations,
and playback acknowledgements. The host must gate emitted animation frames by
the plan's unique sequence ID and reset its rig when a turn is interrupted.

Deliberate separation:
  signal -> proposed intent -> prepared utterance -> queued audio
         -> host-confirmed audible -> eligible expression/motion -> finish

Merely queuing TTS, generating model text, or receiving a viewer claim must not
animate a victory or commit a spoken reaction.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from threading import RLock
import time
from typing import Callable, Sequence

from .stream_budget import StreamTelemetry
from .stream_episode import EpisodePacket
from .stream_director import SpeechIntent, StreamDirector, StreamSignal
from .stream_knowledge import KnowledgePacket
from .stream_motion import (
    AudioLevel, ExpressionCue, MotionFrame, neutral_frame, plan_motion,
)
from .stream_persona import event_message
from .stream_turntaking import TurnAdvice

MODES = frozenset({"normal", "cat", "puppy"})

# Small, evidence-gated cues; no hallucinated laughter or fake user emotion.
_CUES: dict[str, tuple[str, float] | None] = {
    "owner_interrupt": None,
    "game_danger": ("surprise", 0.50),
    "game_success": ("joy", 0.75),
    "game_observation": ("focus", 0.35),
    "viewer_question": ("nod", 0.35),
    "viewer_comment": ("nod", 0.25),
    "ambient": None,
}

# Only fixed descriptions enter the language-model context from this module.
# A "cute" voice should be earned by events, never a noisy catchphrase machine.
_DELIVERY = {
    "owner_interrupt": "Stop the previous response; listen to the interruption.",
    "game_danger": "Brief and alert. Do not manufacture panic or certainty.",
    "game_success": "A small, specific delighted reaction only if verified.",
    "game_observation": "Curious and observant; do not assert an unverified mechanic.",
    "viewer_question": "Friendly, direct answer; a little warmth is enough.",
    "viewer_comment": "Optional short acknowledgement, without copying abusive chat.",
    "ambient": "Quiet is allowed; never force an idle catchphrase.",
}


def _time(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("time must be a nonnegative finite number")
    try:
        value = float(value)
    except (ValueError, OverflowError) as exc:
        raise ValueError("invalid time") from exc
    if not math.isfinite(value) or value < 0:
        raise ValueError("time must be a nonnegative finite number")
    return value


@dataclass(frozen=True)
class StagePlan:
    """Immutable, one-shot host cue; no actual voice or animation is generated."""

    sequence: int
    signal_id: str
    kind: str
    evidence: str
    mode: str
    reduced_motion: bool
    deadline_at: float
    context_record: str
    expression: str | None
    expression_strength: float

    def user_message(self) -> dict[str, str]:
        """Untrusted event record at USER priority, never a new system prompt."""
        return {"role": "user", "content": self.context_record}


class StarStage:
    """A single-stream, bounded in-memory scene coordinator.

    "Owner approved" means the authorized host explicitly opted into using
    the offline planner, not that a broadcast or viewer-data permission exists.
    The underlying StreamDirector remains responsible for event arbitration.
    """

    def __init__(self, *,
                 director: StreamDirector | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._director = director if director is not None else StreamDirector()
        if not isinstance(self._director, StreamDirector):
            raise TypeError("director must be a StreamDirector")
        self._clock = clock
        self._lock = RLock()
        self._enabled = False
        self._mode = "normal"
        self._reduced_motion = False
        self._sequence = 0
        self._plan: StagePlan | None = None
        self._intent: SpeechIntent | None = None
        self._phase = "idle"
        self._counts = {
            "prepared": 0, "queued": 0, "audible": 0,
            "abandoned": 0, "interrupted": 0, "motion_requests": 0,
        }

    def enable(self, *, owner_approved: bool = False,
               mode: str = "normal", reduced_motion: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("stage needs explicit authorized host approval")
        self._validate_look(mode, reduced_motion)
        with self._lock:
            if self._plan is not None:
                raise RuntimeError("finish or interrupt the current turn first")
            self._director.enable(owner_approved=True)
            self._mode, self._reduced_motion = mode, reduced_motion
            self._enabled = True

    @staticmethod
    def _validate_look(mode: str, reduced_motion: bool) -> None:
        if type(mode) is not str or mode not in MODES:
            raise ValueError("mode must be normal, cat, or puppy")
        if type(reduced_motion) is not bool:
            raise ValueError("reduced_motion must be boolean")

    def configure(self, *, mode: str, reduced_motion: bool = False) -> None:
        """Mode changes are allowed only between turns (not mid-utterance)."""
        self._validate_look(mode, reduced_motion)
        with self._lock:
            if self._plan is not None:
                raise RuntimeError("cannot swap rigs during a turn")
            self._mode, self._reduced_motion = mode, reduced_motion

    def disable(self) -> MotionFrame:
        """Invalidate the stage; the host must silence playback/reset its rig."""
        with self._lock:
            self._drop(interrupted=True)
            self._director.disable()
            self._enabled = False
            return neutral_frame()

    def offer(self, event: StreamSignal, *,
              now: float | None = None, moderated: bool = False) -> bool:
        """Queue a signal; require upstream moderation for every viewer message.

        This boolean is a host attestation, not independent proof of moderation.
        No chat events may grant access to operating-system or streaming tools.
        """
        current = _time(self._clock() if now is None else now)
        if not isinstance(event, StreamSignal):
            raise TypeError("expected a StreamSignal")
        with self._lock:
            if not self._enabled:
                return False
            if event.kind.startswith("viewer") and moderated is not True:
                return False
            return self._director.offer(event, now=current)

    def prepare(self, *, now: float | None = None,
                voice_speaking: bool = False,
                viewer_speaking: bool = False,
                gameplay_critical: bool = False,
                knowledge: KnowledgePacket | None = None,
                telemetry: StreamTelemetry | None = None,
                episode: EpisodePacket | None = None,
                turn: TurnAdvice | None = None) -> StagePlan | None:
        """Propose a short reaction; measured overload favors silence and gameplay."""
        current = _time(self._clock() if now is None else now)
        if knowledge is not None and not isinstance(knowledge, KnowledgePacket):
            raise TypeError("knowledge must be a host-approved KnowledgePacket")
        if telemetry is not None and not isinstance(telemetry, StreamTelemetry):
            raise TypeError("telemetry must be host-provided StreamTelemetry")
        if episode is not None and not isinstance(episode, EpisodePacket):
            raise TypeError("episode must be a host-approved EpisodePacket")
        if turn is not None and not isinstance(turn, TurnAdvice):
            raise TypeError("turn must be a host-provided TurnAdvice")
        # The host, not chat or a prompt, supplies validated GPU/FPS/voice data.
        # Preserve urgent danger/owner preemption; defer commentary when gameplay,
        # VRAM or speech queues are under strain. No unbounded TTS queue buildup.
        measured_pressure = bool(telemetry and (
            (telemetry.game_active and telemetry.game_fps < 50.0)
            or telemetry.speech_backlog_ms > 250.0
            or (telemetry.live and telemetry.free_vram_mib < 1536.0)
        ))
        with self._lock:
            if not self._enabled or self._plan is not None:
                return None
            intent = self._director.propose(
                now=current, voice_speaking=voice_speaking,
                viewer_speaking=viewer_speaking or bool(turn and turn.hold),
                gameplay_critical=gameplay_critical or measured_pressure,
            )
            if intent is None:
                return None
            self._sequence += 1
            expression = _CUES[intent.kind]
            # An unconfirmed game inference can never trigger a victory dance
            # or a fear cue; only host-classified "observed" gets game emoting.
            if intent.kind.startswith("game_") and intent.evidence != "observed":
                expression = None
            guidance = _DELIVERY[intent.kind]
            prompt = event_message(intent)["content"] + "\nDelivery: " + guidance
            # Public facts accompany only an actual viewer question, never an
            # unsolicited idle remark or high-priority gameplay interruption.
            if knowledge is not None and intent.kind == "viewer_question":
                prompt += "\n" + knowledge.context_record
            # Session-scoped, signed-practice aggregates: never attach them to
            # urgent warnings, idle banter or unrelated viewer comments.
            if episode is not None and intent.kind in {
                "game_observation", "game_success", "viewer_question"
            }:
                prompt += "\n" + episode.context_record
            plan = StagePlan(
                sequence=self._sequence, signal_id=intent.signal_id,
                kind=intent.kind, evidence=intent.evidence,
                mode=self._mode, reduced_motion=self._reduced_motion,
                deadline_at=intent.deadline_at, context_record=prompt,
                expression=None if expression is None else expression[0],
                expression_strength=0.0 if expression is None else expression[1],
            )
            self._plan, self._intent, self._phase = plan, intent, "prepared"
            self._counts["prepared"] += 1
            return plan

    def _matches(self, plan: StagePlan, phase: str | None = None) -> bool:
        return (self._enabled and isinstance(plan, StagePlan)
                and self._plan is plan
                and (phase is None or phase == self._phase))

    def queue_audio(self, plan: StagePlan, *,
                    now: float | None = None) -> bool:
        """Host indicates audio was queued, *not* that anyone heard it."""
        current = _time(self._clock() if now is None else now)
        with self._lock:
            if not self._matches(plan, "prepared"):
                return False
            if current > plan.deadline_at:
                self._drop(interrupted=False, now=current)
                return False
            self._phase = "queued"
            self._counts["queued"] += 1
            return True

    def acknowledge_audible(self, plan: StagePlan, *,
                            now: float | None = None) -> bool:
        """Host certifies audio was played to the output device.

        This is an operator/adapter assertion. It is not audio verification.
        Do not acknowledge merely because TTS or a speaker queue returned.
        """
        current = _time(self._clock() if now is None else now)
        with self._lock:
            if not self._matches(plan, "queued"):
                return False
            if current > plan.deadline_at or self._intent is None:
                self._drop(interrupted=False, now=current)
                return False
            # Playback has *started*, but the entire utterance has NOT yet
            # been heard. Do not commit the director's spoken outcome until
            # finish(played_to_end=True) acknowledges completion.
            self._phase = "audible"
            self._counts["audible"] += 1
            return True

    def prepared(self, plan: StagePlan) -> bool:
        """Host-only preplay check: same live plan object in prepared phase."""
        with self._lock:
            return self._matches(plan, "prepared")

    def current(self, plan: StagePlan) -> bool:
        """Call immediately before sending rig frames to reject stale tokens."""
        with self._lock:
            return self._matches(plan, "audible")

    def motion(self, plan: StagePlan, *, duration_s: float,
               audio_levels: Sequence[AudioLevel], fps: int = 30,
               seed: int = 7) -> tuple[MotionFrame, ...]:
        """Sample original character movement against HOST-PLAYED audio levels.

        A non-audible/cancelled plan returns no frames, not a fake mouth cue.
        The renderer must confirm current(plan) on every dispatched batch.
        """
        with self._lock:
            if not self._matches(plan, "audible"):
                return ()
            cues = ()
            if plan.expression is not None:
                cues = (ExpressionCue(
                    at_s=0.0, kind=plan.expression,
                    strength=plan.expression_strength,
                ),)
            frames = plan_motion(
                duration_s=duration_s, audio_levels=list(audio_levels),
                cues=cues, mode=plan.mode, fps=fps,
                reduced_motion=plan.reduced_motion, seed=seed,
            )
            self._counts["motion_requests"] += 1
            return frames

    def _drop(self, *, interrupted: bool, now: float | None = None) -> None:
        if self._plan is None:
            return
        if self._intent is not None:
            # A partially heard but interrupted sentence is NOT a completed
            # performance. Consume without claiming a full spoken success.
            self._director.complete(
                self._intent, now=_time(self._clock() if now is None else now),
                spoken=False,
            )
            self._counts["abandoned"] += 1
        if interrupted:
            self._counts["interrupted"] += 1
        self._intent, self._plan, self._phase = None, None, "idle"

    def finish(self, plan: StagePlan, *,
               now: float | None = None,
               played_to_end: bool = False) -> bool:
        """Release the stage. Only verified full playback commits a success.

        The host sets played_to_end=True after its playback device reports that
        the *whole* utterance finished. Mere model completion, TTS generation,
        or audio enqueueing must not set this flag. Calls without it abandon
        the plan, including speech stopped partway through.
        """
        current = _time(self._clock() if now is None else now)
        if type(played_to_end) is not bool:
            raise TypeError("played_to_end must be an explicit boolean")
        with self._lock:
            if not self._matches(plan):
                return False
            if played_to_end:
                if self._phase != "audible" or self._intent is None:
                    return False
                if not self._director.complete(
                    self._intent, now=current, spoken=True,
                ):
                    self._drop(interrupted=False, now=current)
                    return False
                self._intent = None
            self._drop(interrupted=False, now=current)
            return True

    def interrupt(self, *, now: float | None = None) -> MotionFrame:
        """Host must stop audible output and discard the old motion queue."""
        current = _time(self._clock() if now is None else now)
        with self._lock:
            self._drop(interrupted=True, now=current)
            return neutral_frame()

    def interrupt_if_current(
        self, plan: StagePlan, *, now: float | None = None
    ) -> MotionFrame | None:
        """Atomically revoke only this audible plan, never a replacement turn.

        Realtime hosts must bind a specific playback epoch to a plan; racing
        finish()/prepare() should never let an old audio stop revoke a newer
        turn. This invalidates rig-frame authority, but the trusted host still
        must actually stop sound and reset animation hardware.
        """
        current = _time(self._clock() if now is None else now)
        with self._lock:
            if not self._matches(plan, "audible"):
                return None
            self._drop(interrupted=True, now=current)
            return neutral_frame()

    def metrics(self) -> dict[str, object]:
        """Only anonymous counts, not raw chat, names, audio, or private data."""
        with self._lock:
            return {**self._counts, "enabled": self._enabled,
                    "phase": self._phase, "mode": self._mode,
                    "director": self._director.metrics()}


__all__ = ["StagePlan", "StarStage"]
