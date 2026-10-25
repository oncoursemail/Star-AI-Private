"""Offline, evidence-grounded decision layer for a future STAR AI streamer.

No model calls, screen capture, game control, recording, chat reading or broadcasting.
The trusted host MUST verify event provenance and human opt-in before invoking
this class. A model message, game text, or viewer message is NEVER authority.

Emits *intents*, not generated dialogue or audio. Nothing here speaks for STAR.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import re

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}\Z")

# kind -> (trusted adapter, speech intent, expression, animation, priority, speak)
# The host must authenticate each adapter; source strings are not capabilities.
_KINDS = {
    "game_win": ("verified_game", "celebrate_verified_win", "happy", "cheer", 4, True),
    "game_loss": ("verified_game", "reflect_on_verified_loss", "disappointed", "flinch", 3, True),
    "game_checkpoint": ("verified_game", "acknowledge_checkpoint", "pleased", "nod", 2, True),
    "game_stuck": ("verified_game", "reason_about_observed_obstacle", "focused", "think", 2, True),
    "game_hazard": ("verified_game", "", "surprised", "startle", 4, False),
    "chat_question": ("moderated_chat", "consider_moderated_viewer_question", "curious", "look_at_chat", 1, True),
    "chat_cheer": ("moderated_chat", "acknowledge_moderated_chat", "happy", "wave", 1, True),
    "owner_intro": ("owner_ui", "welcome_viewers", "happy", "wave", 2, True),
    "owner_outro": ("owner_ui", "say_goodbye", "calm", "wave", 2, True),
    "owner_stop": ("owner_ui", "", "neutral", "idle", 100, False),
}
MAX_QUEUE = 48
MAX_SEEN = 256
MAX_EVENT_AGE_MS = 12000
MAX_FUTURE_MS = 500
GLOBAL_SPEECH_COOLDOWN_MS = 5000
KIND_COOLDOWN_MS = 9000


@dataclass(frozen=True)
class StreamEvent:
    event_id: str
    kind: str
    source: str
    observed_ms: int
    evidence_id: str
    moderated: bool = False
    # No chat text, arbitrary commands, account IDs, or process/input handles.


@dataclass(frozen=True)
class StageCue:
    event_id: str
    evidence_id: str
    intent: str
    expression: str
    animation: str
    should_speak: bool
    priority: int
    # "stop" indicates local emergency stop request; no stream I/O occurs.
    kind: str = "stage"


class StreamerDirector:
    """Deterministic priority/cooldown arbiter. Disabled and silent by default.

    An explicit UI approval must call set_enabled(True, owner_confirmed=True).
    External adapters and the LLM must not call it directly. Output is a plan
    for separate, permission-checked TTS/animation services, not a command.
    """

    def __init__(self) -> None:
        self.enabled = False
        self._queue: list[StreamEvent] = []
        self._seen_ids: deque[str] = deque()
        self._seen_set: set[str] = set()
        self._last_kind_speech: dict[str, int] = {}
        self._next_speech_ms = 0
        self._stop: StreamEvent | None = None
        self.accepted = 0
        self.rejected = 0
        self.dropped = 0
        self.dispatched = 0

    def set_enabled(self, enabled: bool, *, owner_confirmed: bool = False) -> None:
        if type(enabled) is not bool:
            raise ValueError("enabled must be a bool")
        if enabled and not owner_confirmed:
            raise PermissionError("Streamer mode requires explicit human approval")
        self.enabled = enabled
        if not enabled:
            self._queue.clear()
            self._next_speech_ms = 0
            self._last_kind_speech.clear()

    def _remember(self, event_id: str) -> None:
        if len(self._seen_ids) == MAX_SEEN:
            old = self._seen_ids.popleft()
            self._seen_set.remove(old)
        self._seen_ids.append(event_id)
        self._seen_set.add(event_id)

    def ingest(self, event: StreamEvent, *, now_ms: int) -> bool:
        """Accept only well-formed, timely, adapter-verified event declarations.

        source and moderated are evidence claims made by an ALREADY
        trusted host adapter, not authorization supplied by an untrusted caller.
        """
        if not isinstance(event, StreamEvent) or type(now_ms) is not int or now_ms < 0:
            raise ValueError("Malformed streamer input")
        spec = _KINDS.get(event.kind)
        valid = (spec is not None and event.source == spec[0]
                 and isinstance(event.event_id, str) and bool(_IDENTIFIER.fullmatch(event.event_id))
                 and isinstance(event.evidence_id, str) and bool(_IDENTIFIER.fullmatch(event.evidence_id))
                 and type(event.observed_ms) is int
                 and now_ms - MAX_EVENT_AGE_MS <= event.observed_ms <= now_ms + MAX_FUTURE_MS
                 and event.event_id not in self._seen_set
                 and all(pending.event_id != event.event_id for pending in self._queue)
                 and (event.source != "moderated_chat" or event.moderated is True))
        if not valid:
            self.rejected += 1
            return False
        self._remember(event.event_id)
        if event.kind == "owner_stop":
            self.set_enabled(False)
            self._stop = event
            self.accepted += 1
            return True
        if not self.enabled:
            self.rejected += 1
            return False
        if len(self._queue) >= MAX_QUEUE:
            # Discard the least important queued cue if the new one is higher priority.
            least = min(range(len(self._queue)), key=lambda i: (_KINDS[self._queue[i].kind][4],
                                                                 self._queue[i].observed_ms))
            if _KINDS[event.kind][4] <= _KINDS[self._queue[least].kind][4]:
                self.dropped += 1
                return False
            self._queue.pop(least)
            self.dropped += 1
        self._queue.append(event)
        self.accepted += 1
        return True

    def next_cue(self, *, now_ms: int, voice_busy: bool = False,
                 intense_gameplay: bool = False) -> StageCue | None:
        """Return an optional, non-executable stage intent; silence is normal.

        Speech yields to actual speaking, active gameplay and global/per-kind
        cooldowns. Expired events are never narrated as current achievements.
        """
        if type(now_ms) is not int or now_ms < 0:
            raise ValueError("Invalid clock")
        if self._stop is not None:
            event = self._stop
            self._stop = None
            self.dispatched += 1
            return StageCue(event.event_id, event.evidence_id, "", "neutral", "idle", False, 100, "stop")
        if not self.enabled:
            return None
        before = len(self._queue)
        self._queue = [e for e in self._queue if -MAX_FUTURE_MS <= now_ms - e.observed_ms <= MAX_EVENT_AGE_MS]
        self.dropped += before - len(self._queue)
        choices: list[tuple[int, StreamEvent]] = []
        for index, event in enumerate(self._queue):
            source, intent, expression, animation, priority, speak = _KINDS[event.kind]
            if speak and (voice_busy or intense_gameplay or now_ms < self._next_speech_ms
                          or now_ms - self._last_kind_speech.get(event.kind, -KIND_COOLDOWN_MS)
                          < KIND_COOLDOWN_MS):
                continue
            choices.append((index, event))
        if not choices:
            return None
        index, event = max(choices, key=lambda pair: (_KINDS[pair[1].kind][4], -pair[1].observed_ms))
        self._queue.pop(index)
        source, intent, expression, animation, priority, speak = _KINDS[event.kind]
        if speak:
            self._next_speech_ms = now_ms + GLOBAL_SPEECH_COOLDOWN_MS
            self._last_kind_speech[event.kind] = now_ms
        self.dispatched += 1
        return StageCue(event.event_id, event.evidence_id, intent, expression, animation, speak, priority)

    def stats(self) -> dict[str, int | bool]:
        """Metadata only; no chat text, user IDs or unverifiable win metrics."""
        return {"enabled": self.enabled, "queued": len(self._queue), "accepted": self.accepted,
                "rejected": self.rejected, "dropped": self.dropped, "dispatched": self.dispatched}
