"""Deterministic, privacy-minimizing turn policy for a future multiparty stream adapter.

This module consumes already-classified *metadata* from diarization/ASR/chat/game adapters.
It does not identify people, transcribe audio, infer emotion, call models, store transcripts,
control devices, or grant tool permissions. A single host event loop should own each director.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
import math


def _finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


class CueSource(str, Enum):
    AUDIO = "audio"
    CHAT = "chat"
    GAME = "game"


class CueIntent(str, Enum):
    DIRECT_QUESTION = "direct_question"
    DIRECT_REQUEST = "direct_request"
    DIRECT_MENTION = "direct_mention"
    CORRECTION = "correction"
    BACKCHANNEL = "backchannel"
    SIDE_CONVERSATION = "side_conversation"
    NARRATION = "narration"
    GAME_EVENT = "game_event"
    UNKNOWN = "unknown"


class RoomAction(str, Enum):
    RESPOND = "respond"
    QUEUE = "queue"
    CONTINUE = "continue"
    IGNORE = "ignore"
    WAIT = "wait"
    INTERRUPT = "interrupt"


@dataclass(frozen=True)
class RoomCue:
    """A final or partial cue; intentionally contains no transcript or audio payload."""

    event_id: str
    speaker_id: str
    source: CueSource
    intent: CueIntent
    addressed_to_star: bool
    confidence: float
    started_at: float
    ended_at: float
    overlap_ms: int = 0
    urgency: float = 0.0
    final: bool = True


@dataclass(frozen=True)
class RoomDecision:
    action: RoomAction
    event_id: str
    reason: str
    priority: int = 0
    cancel_response_id: str | None = None


@dataclass(frozen=True)
class RoomPolicyConfig:
    min_confidence: float = 0.72
    interrupt_confidence: float = 0.90
    interrupt_overlap_ms: int = 288
    max_event_age_seconds: float = 60.0
    max_future_skew_seconds: float = 0.25
    min_game_urgency: float = 0.82
    dedupe_capacity: int = 512

    def __post_init__(self) -> None:
        for name in ("min_confidence", "interrupt_confidence", "min_game_urgency"):
            value = getattr(self, name)
            if not _finite_number(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be a finite number from 0 to 1")
        for name in ("max_event_age_seconds", "max_future_skew_seconds"):
            value = getattr(self, name)
            if not _finite_number(value) or value < 0.0:
                raise ValueError(f"{name} must be a finite non-negative number")
        if type(self.interrupt_overlap_ms) is not int or not 0 <= self.interrupt_overlap_ms <= 60_000:
            raise ValueError("interrupt_overlap_ms must be an integer from 0 to 60000")
        if type(self.dedupe_capacity) is not int or not 1 <= self.dedupe_capacity <= 8192:
            raise ValueError("dedupe_capacity must be an integer from 1 to 8192")


_DIRECT_INTENTS = {
    CueIntent.DIRECT_QUESTION,
    CueIntent.DIRECT_REQUEST,
    CueIntent.DIRECT_MENTION,
    CueIntent.CORRECTION,
}
_NON_INTERRUPT_INTENTS = {
    CueIntent.BACKCHANNEL,
    CueIntent.SIDE_CONVERSATION,
    CueIntent.NARRATION,
}
_PRIORITY = {
    CueIntent.CORRECTION: 100,
    CueIntent.DIRECT_REQUEST: 85,
    CueIntent.DIRECT_QUESTION: 75,
    CueIntent.DIRECT_MENTION: 55,
}


class RoomTurnDirector:
    """Select respond/queue/continue/ignore/interrupt without retaining user content.

    now and cue timestamps must use the same monotonic clock. Chat/game adapters must
    translate wall-clock timestamps to host-monotonic arrival times before creating cues.
    The returned INTERRUPT decision names the exact active response generation to cancel.
    """

    def __init__(self, config: RoomPolicyConfig | None = None) -> None:
        if config is not None and not isinstance(config, RoomPolicyConfig):
            raise TypeError("config must be a RoomPolicyConfig")
        self.config = config or RoomPolicyConfig()
        self._assistant_speaking = False
        self._response_id: str | None = None
        self._seen_order: deque[str] = deque()
        self._seen: set[str] = set()

    @property
    def assistant_speaking(self) -> bool:
        return self._assistant_speaking

    def set_assistant_playback(self, speaking: bool, response_id: str | None = None) -> None:
        """Update playback state from the actual speaker, not from generated text."""
        if type(speaking) is not bool:
            raise ValueError("speaking must be a boolean")
        if speaking:
            if not isinstance(response_id, str) or not response_id or len(response_id) > 128:
                raise ValueError("an active playback requires a non-empty response_id of at most 128 characters")
            self._assistant_speaking = True
            self._response_id = response_id
        else:
            self._assistant_speaking = False
            self._response_id = None

    def reset_session(self) -> None:
        """Clear ephemeral room state when a stream/session ends."""
        self._assistant_speaking = False
        self._response_id = None
        self._seen_order.clear()
        self._seen.clear()

    def decide(self, cue: RoomCue, *, now: float) -> RoomDecision:
        self._validate(cue, now)
        if not cue.final:
            return RoomDecision(RoomAction.WAIT, cue.event_id, "await_final_cue")
        if cue.ended_at > now + self.config.max_future_skew_seconds:
            return RoomDecision(RoomAction.IGNORE, cue.event_id, "future_timestamp")
        if now - cue.ended_at > self.config.max_event_age_seconds:
            return RoomDecision(RoomAction.IGNORE, cue.event_id, "stale_event")
        if cue.event_id in self._seen:
            return RoomDecision(RoomAction.IGNORE, cue.event_id, "duplicate_event")
        self._remember(cue.event_id)

        if cue.confidence < self.config.min_confidence:
            return RoomDecision(RoomAction.WAIT, cue.event_id, "low_classification_confidence")

        if cue.intent in _NON_INTERRUPT_INTENTS:
            action = RoomAction.CONTINUE if self._assistant_speaking else RoomAction.IGNORE
            return RoomDecision(action, cue.event_id, "non_directed_social_cue")

        if cue.intent is CueIntent.UNKNOWN:
            action = RoomAction.CONTINUE if self._assistant_speaking else RoomAction.WAIT
            return RoomDecision(action, cue.event_id, "intent_unresolved")

        if cue.intent is CueIntent.GAME_EVENT:
            if cue.source is not CueSource.GAME or cue.urgency < self.config.min_game_urgency:
                action = RoomAction.CONTINUE if self._assistant_speaking else RoomAction.IGNORE
                return RoomDecision(action, cue.event_id, "game_event_below_reaction_threshold")
            priority = round(cue.urgency * 100)
            if self._assistant_speaking:
                return RoomDecision(RoomAction.QUEUE, cue.event_id, "important_game_event_queued", priority)
            return RoomDecision(RoomAction.RESPOND, cue.event_id, "important_game_event", priority)

        if cue.intent not in _DIRECT_INTENTS or not cue.addressed_to_star:
            action = RoomAction.CONTINUE if self._assistant_speaking else RoomAction.IGNORE
            return RoomDecision(action, cue.event_id, "not_addressed_to_star")

        priority = _PRIORITY[cue.intent]
        if not self._assistant_speaking:
            return RoomDecision(RoomAction.RESPOND, cue.event_id, "directed_to_star", priority)

        should_interrupt = (
            cue.source is CueSource.AUDIO
            and cue.confidence >= self.config.interrupt_confidence
            and cue.overlap_ms >= self.config.interrupt_overlap_ms
        )
        if should_interrupt:
            return RoomDecision(
                RoomAction.INTERRUPT,
                cue.event_id,
                "high_confidence_direct_audio_barge_in",
                priority,
                cancel_response_id=self._response_id,
            )
        return RoomDecision(RoomAction.QUEUE, cue.event_id, "directed_to_star_while_speaking", priority)

    def _remember(self, event_id: str) -> None:
        self._seen.add(event_id)
        self._seen_order.append(event_id)
        while len(self._seen_order) > self.config.dedupe_capacity:
            expired = self._seen_order.popleft()
            self._seen.discard(expired)

    @staticmethod
    def _validate(cue: RoomCue, now: float) -> None:
        if not isinstance(cue, RoomCue):
            raise TypeError("cue must be a RoomCue")
        for name, value in (("event_id", cue.event_id), ("speaker_id", cue.speaker_id)):
            if not isinstance(value, str) or not value or len(value) > 128:
                raise ValueError(f"{name} must be a non-empty string of at most 128 characters")
        if not isinstance(cue.source, CueSource) or not isinstance(cue.intent, CueIntent):
            raise ValueError("source and intent must use their enum values")
        if type(cue.addressed_to_star) is not bool or type(cue.final) is not bool:
            raise ValueError("addressed_to_star and final must be booleans")
        for name, value in (("confidence", cue.confidence), ("urgency", cue.urgency)):
            if not _finite_number(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be a finite number from 0 to 1")
        for name, value in (("started_at", cue.started_at), ("ended_at", cue.ended_at), ("now", now)):
            if not _finite_number(value):
                raise ValueError(f"{name} must be a finite monotonic timestamp")
        if cue.ended_at < cue.started_at:
            raise ValueError("ended_at cannot be earlier than started_at")
        if type(cue.overlap_ms) is not int or not 0 <= cue.overlap_ms <= 60_000:
            raise ValueError("overlap_ms must be an integer from 0 to 60000")
