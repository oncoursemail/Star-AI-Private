"""Trusted host-side ingress and dispatch for an opted-in multiparty voice session.

Provider SDKs (Twitch, YouTube, Discord, ASR/diarization, and game observers) stay outside
this module. They must authenticate/consent, moderate, classify, and construct a RoomCue
before submitting. This boundary applies source allowlists, bounded rate limits, and chat
moderation before forwarding untrusted text to CallSession.
"""
from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
import math
import threading
import time
from typing import Callable

from .call import CallSession, RoomDispatchResult, RoomDispatchStatus
from .room import CueIntent, CueSource, RoomAction, RoomCue, RoomDecision


def _finite(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class RoomHostConfig:
    """Per-call source consent and conservative ingress limits."""

    allowed_sources: frozenset[CueSource]
    rate_window_seconds: float = 10.0
    max_events_per_source: int = 60
    max_events_per_speaker: int = 8
    max_speakers: int = 256
    max_text_bytes: int = 8_192
    dedupe_capacity: int = 1_024
    require_chat_moderation: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.allowed_sources, frozenset) or not self.allowed_sources:
            raise ValueError("allowed_sources must be a non-empty frozenset")
        if any(not isinstance(source, CueSource) for source in self.allowed_sources):
            raise ValueError("allowed_sources must contain CueSource values")
        if not _finite(self.rate_window_seconds) or self.rate_window_seconds <= 0:
            raise ValueError("rate_window_seconds must be finite and positive")
        for name, low, high in (
            ("max_events_per_source", 1, 10_000),
            ("max_events_per_speaker", 1, 1_000),
            ("max_speakers", 1, 4_096),
            ("max_text_bytes", 1, 1_048_576),
            ("dedupe_capacity", 1, 16_384),
        ):
            value = getattr(self, name)
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name} must be an integer from {low} to {high}")
        if type(self.require_chat_moderation) is not bool:
            raise ValueError("require_chat_moderation must be a boolean")


@dataclass(frozen=True)
class RoomHostStats:
    submitted: int = 0
    accepted: int = 0
    rejected_closed: int = 0
    rejected_source: int = 0
    rejected_duplicate: int = 0
    rejected_invalid: int = 0
    rejected_non_final: int = 0
    rejected_empty: int = 0
    rejected_oversize: int = 0
    rejected_rate: int = 0
    rejected_moderation: int = 0
    moderation_errors: int = 0
    dispatch_started: int = 0
    dispatch_busy: int = 0
    dispatch_empty: int = 0
    dispatch_stopped: int = 0
    dispatch_missing_payload: int = 0
    dispatch_cue_mismatch: int = 0


class RoomStreamHost:
    """A short-lived, in-process capability for a single opted-in CallSession.

    This class does not connect to providers or infer intent. Its caller must be a trusted
    local adapter and must submit already-classified cues with opaque, session-scoped IDs.
    The chat moderator is a fast local policy callback; exceptions fail closed.
    """

    def __init__(
        self,
        session: CallSession,
        config: RoomHostConfig,
        *,
        moderate_chat: Callable[[RoomCue, str], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(session, CallSession):
            raise TypeError("session must be a CallSession")
        if not isinstance(config, RoomHostConfig):
            raise TypeError("config must be a RoomHostConfig")
        if moderate_chat is not None and not callable(moderate_chat):
            raise TypeError("moderate_chat must be callable or None")
        if config.require_chat_moderation and CueSource.CHAT in config.allowed_sources and moderate_chat is None:
            raise ValueError("chat source requires a moderation callback")
        self.session = session
        self.config = config
        self._moderate_chat = moderate_chat
        self._clock = clock
        self._lock = threading.RLock()
        self._closed = False
        self._source_times: dict[CueSource, deque[float]] = {
            source: deque() for source in config.allowed_sources
        }
        self._speaker_times: OrderedDict[tuple[CueSource, str], deque[float]] = OrderedDict()
        self._seen_order: deque[str] = deque()
        self._seen: set[str] = set()
        self._counts = {
            "submitted": 0,
            "accepted": 0,
            "rejected_closed": 0,
            "rejected_source": 0,
            "rejected_duplicate": 0,
            "rejected_invalid": 0,
            "rejected_non_final": 0,
            "rejected_empty": 0,
            "rejected_oversize": 0,
            "rejected_rate": 0,
            "rejected_moderation": 0,
            "moderation_errors": 0,
            "dispatch_started": 0,
            "dispatch_busy": 0,
            "dispatch_empty": 0,
            "dispatch_stopped": 0,
            "dispatch_missing_payload": 0,
            "dispatch_cue_mismatch": 0,
        }

    @property
    def stats(self) -> RoomHostStats:
        with self._lock:
            return RoomHostStats(
                submitted=self._counts["submitted"],
                accepted=self._counts["accepted"],
                rejected_closed=self._counts["rejected_closed"],
                rejected_source=self._counts["rejected_source"],
                rejected_duplicate=self._counts["rejected_duplicate"],
                rejected_invalid=self._counts["rejected_invalid"],
                rejected_non_final=self._counts["rejected_non_final"],
                rejected_empty=self._counts["rejected_empty"],
                rejected_oversize=self._counts["rejected_oversize"],
                rejected_rate=self._counts["rejected_rate"],
                rejected_moderation=self._counts["rejected_moderation"],
                moderation_errors=self._counts["moderation_errors"],
                dispatch_started=self._counts["dispatch_started"],
                dispatch_busy=self._counts["dispatch_busy"],
                dispatch_empty=self._counts["dispatch_empty"],
                dispatch_stopped=self._counts["dispatch_stopped"],
                dispatch_missing_payload=self._counts["dispatch_missing_payload"],
                dispatch_cue_mismatch=self._counts["dispatch_cue_mismatch"],
            )

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def submit(self, cue: RoomCue, text: str) -> RoomDecision:
        """Submit one final classified event; text is never logged or persisted here."""
        if not isinstance(cue, RoomCue):
            raise TypeError("cue must be a RoomCue")
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        with self._lock:
            self._bump("submitted")
            if self._closed:
                self._bump("rejected_closed")
                return self._decision(RoomAction.WAIT, cue, "room_host_closed")
            if (
                not isinstance(cue.event_id, str)
                or not cue.event_id
                or len(cue.event_id) > 128
                or not isinstance(cue.speaker_id, str)
                or not cue.speaker_id
                or len(cue.speaker_id) > 128
                or not isinstance(cue.source, CueSource)
                or not isinstance(cue.intent, CueIntent)
                or type(cue.addressed_to_star) is not bool
                or type(cue.final) is not bool
                or type(cue.overlap_ms) is not int
                or not 0 <= cue.overlap_ms <= 60_000
                or not _finite(cue.started_at)
                or not _finite(cue.ended_at)
                or cue.started_at > cue.ended_at
                or not _finite(cue.confidence)
                or not 0.0 <= cue.confidence <= 1.0
                or not _finite(cue.urgency)
                or not 0.0 <= cue.urgency <= 1.0
            ):
                self._bump("rejected_invalid")
                return self._decision(RoomAction.WAIT, cue, "invalid_room_cue")
            if cue.source not in self.config.allowed_sources:
                self._bump("rejected_source")
                return self._decision(RoomAction.WAIT, cue, "source_not_enabled")
            if not cue.final:
                self._bump("rejected_non_final")
                return self._decision(RoomAction.WAIT, cue, "final_event_required")
            if cue.event_id in self._seen:
                self._bump("rejected_duplicate")
                return self._decision(RoomAction.IGNORE, cue, "duplicate_room_event")
            if not text.strip():
                self._bump("rejected_empty")
                return self._decision(RoomAction.WAIT, cue, "empty_room_message")
            try:
                size = len(text.encode("utf-8", errors="strict"))
            except UnicodeEncodeError:
                self._bump("rejected_empty")
                return self._decision(RoomAction.WAIT, cue, "invalid_utf8")
            if size > self.config.max_text_bytes:
                self._bump("rejected_oversize")
                return self._decision(RoomAction.WAIT, cue, "room_message_too_large")

            now = self._clock()
            if not _finite(now):
                self._bump("rejected_rate")
                return self._decision(RoomAction.WAIT, cue, "host_clock_unavailable")
            if not self._admit_rate_locked(cue, float(now)):
                self._bump("rejected_rate")
                return self._decision(RoomAction.WAIT, cue, "room_rate_limited")
            self._remember_event_locked(cue.event_id)

            # Apply cheap bounded admission before invoking the moderation callback.
            if cue.source is CueSource.CHAT and self.config.require_chat_moderation:
                try:
                    allowed = bool(self._moderate_chat and self._moderate_chat(cue, text))
                except Exception:
                    self._bump("moderation_errors")
                    self._bump("rejected_moderation")
                    return self._decision(RoomAction.WAIT, cue, "chat_moderation_error")
                if not allowed:
                    self._bump("rejected_moderation")
                    return self._decision(RoomAction.IGNORE, cue, "chat_moderation_rejected")

            decision = self.session.handle_room_message(cue, text)
            if decision.action not in (RoomAction.WAIT, RoomAction.IGNORE):
                self._bump("accepted")
            return decision

    def dispatch_pending(self) -> RoomDispatchResult:
        """Dispatch at most one queued message; CallSession enforces the idle/input gate."""
        with self._lock:
            if self._closed:
                return RoomDispatchResult(RoomDispatchStatus.STOPPED, reason="room_host_closed")
            result = self.session.dispatch_next_room_message()
            field = {
                RoomDispatchStatus.DISPATCHED: "dispatch_started",
                RoomDispatchStatus.BUSY: "dispatch_busy",
                RoomDispatchStatus.EMPTY: "dispatch_empty",
                RoomDispatchStatus.STOPPED: "dispatch_stopped",
                RoomDispatchStatus.MISSING_PAYLOAD: "dispatch_missing_payload",
                RoomDispatchStatus.CUE_MISMATCH: "dispatch_cue_mismatch",
            }.get(result.status)
            if field is not None:
                self._bump(field)
            return result

    def close(self) -> None:
        """Revoke this ingress capability and release its bounded rate-limit state."""
        with self._lock:
            self._closed = True
            self._source_times.clear()
            self._speaker_times.clear()
            self._seen_order.clear()
            self._seen.clear()

    def _remember_event_locked(self, event_id: str) -> None:
        self._seen.add(event_id)
        self._seen_order.append(event_id)
        while len(self._seen_order) > self.config.dedupe_capacity:
            expired = self._seen_order.popleft()
            self._seen.discard(expired)

    def _admit_rate_locked(self, cue: RoomCue, now: float) -> bool:
        cutoff = now - self.config.rate_window_seconds
        source_events = self._source_times[cue.source]
        self._prune(source_events, cutoff)
        key = (cue.source, cue.speaker_id)
        speaker_events = self._speaker_times.get(key)
        if speaker_events is None:
            if len(self._speaker_times) >= self.config.max_speakers:
                self._speaker_times.popitem(last=False)
            speaker_events = deque()
            self._speaker_times[key] = speaker_events
        else:
            self._speaker_times.move_to_end(key)
        self._prune(speaker_events, cutoff)
        if (len(source_events) >= self.config.max_events_per_source
                or len(speaker_events) >= self.config.max_events_per_speaker):
            return False
        source_events.append(now)
        speaker_events.append(now)
        return True

    @staticmethod
    def _prune(events: deque[float], cutoff: float) -> None:
        while events and events[0] <= cutoff:
            events.popleft()

    def _bump(self, field: str) -> None:
        self._counts[field] += 1

    @staticmethod
    def _decision(action: RoomAction, cue: RoomCue, reason: str) -> RoomDecision:
        event_id = cue.event_id if isinstance(cue.event_id, str) and cue.event_id else "invalid-room-event"
        return RoomDecision(action, event_id, reason)


__all__ = ["RoomHostConfig", "RoomHostStats", "RoomStreamHost"]
