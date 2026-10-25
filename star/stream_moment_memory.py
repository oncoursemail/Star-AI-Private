"""Evidence-only, low-cost storytelling cues for STAR's future VTuber.

A trusted game adapter supplies small structured events. These cues provide
recall, pacing and callbacks from *actual in-game moments* without inventing a
human past. They do not generate speech, control OBS, or read chat/audio/video.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_KINDS = frozenset({"discovery", "victory", "failure", "recovery", "surprise"})
_PHRASES = {
    "discovery": "React to the verified discovery. Be curious; do not invent game facts.",
    "victory": "Celebrate the verified win without exaggerating the achievement.",
    "failure": "Acknowledge this observed setback briefly and naturally.",
    "recovery": "React to the observed comeback, without inventing earlier events.",
    "surprise": "Respond to the observed surprise naturally, without claiming human memories.",
}


def _identifier(value: object) -> None:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError("Expected a short safe identifier")


@dataclass(frozen=True)
class GameMoment:
    session: str
    event_id: str
    seq: int
    kind: str
    topic: str
    occurred_ms: int
    evidence_sha256: str

    def __post_init__(self):
        for value in (self.session, self.event_id, self.topic):
            _identifier(value)
        if type(self.seq) is not int or not 1 <= self.seq <= 1_000_000_000:
            raise ValueError("Event sequence must increase monotonically")
        if self.kind not in _KINDS:
            raise ValueError("Unknown gameplay moment type")
        if type(self.occurred_ms) is not int or not 0 <= self.occurred_ms <= 10**12:
            raise ValueError("Timestamp must be bounded monotonic milliseconds")
        if type(self.evidence_sha256) is not str or _SHA.fullmatch(self.evidence_sha256) is None:
            raise ValueError("Moment must reference SHA-256 evidence")


@dataclass(frozen=True)
class VoiceCue:
    kind: str
    event_ids: tuple[str, ...]
    brief: str
    # This is *not* permission to play TTS; the authoritative playback gate
    # must still validate the current turn and interruptions.


class StreamMomentMemory:
    """Bounded in-session narrative arc selector. Pure in-memory advisory data."""

    def __init__(self, *, max_moments: int = 256, max_sessions: int = 16,
                 min_gap_ms: int = 8_000, max_age_ms: int = 120_000):
        if (type(max_moments) is not int or not 1 <= max_moments <= 2048
                or type(max_sessions) is not int or not 1 <= max_sessions <= 128
                or type(min_gap_ms) is not int or not 0 <= min_gap_ms <= 60_000
                or type(max_age_ms) is not int or not 1_000 <= max_age_ms <= 600_000):
            raise ValueError("Stream memory limits outside supported range")
        self._max_moments = max_moments
        self._max_sessions = max_sessions
        self._min_gap = min_gap_ms
        self._max_age = max_age_ms
        self._events: dict[str, list[GameMoment]] = {}
        self._used: set[tuple[str, str]] = set()
        self._seen_ids: set[tuple[str, str]] = set()
        self._seq: dict[str, int] = {}
        self._occurred: dict[str, int] = {}
        self._last_cue: dict[str, int] = {}
        self._total = 0

    def observe(self, moment: GameMoment, *, trusted_game_adapter: bool = False) -> None:
        if trusted_game_adapter is not True:
            raise PermissionError("Only host-authorized game telemetry may add moments")
        if type(moment) is not GameMoment:
            raise TypeError("Expected validated GameMoment")
        prior = self._seq.get(moment.session, 0)
        if (moment.seq <= prior or moment.occurred_ms < self._occurred.get(moment.session, 0)
                or (moment.session, moment.event_id) in self._seen_ids):
            raise ValueError("Repeated, stale, or out-of-order moment")
        if moment.session not in self._seq and len(self._seq) >= self._max_sessions:
            raise OverflowError("Session capacity reached")
        if self._total >= self._max_moments:
            raise OverflowError("Moment capacity reached")
        self._events.setdefault(moment.session, []).append(moment)
        self._seen_ids.add((moment.session, moment.event_id))
        self._seq[moment.session] = moment.seq
        self._occurred[moment.session] = moment.occurred_ms
        self._total += 1

    def next_cue(self, session: str, now_ms: int, *, audience_can_hear: bool = False) -> VoiceCue | None:
        _identifier(session)
        if type(now_ms) is not int or not 0 <= now_ms <= 10**12:
            raise ValueError("now_ms must be bounded monotonic milliseconds")
        if audience_can_hear is not True:
            return None
        last = self._last_cue.get(session)
        if last is not None and now_ms - last < self._min_gap:
            return None
        recent = [e for e in self._events.get(session, [])
                  if 0 <= now_ms - e.occurred_ms <= self._max_age
                  and (session, e.event_id) not in self._used]
        if not recent:
            return None
        newest = recent[-1]
        # A genuine comeback uses the earlier observed failure in the SAME
        # session/topic. It need not be in 'recent' because it may have been
        # commented on already; it still must be inside the five-minute arc.
        if newest.kind == "recovery":
            history = self._events.get(session, [])
            failures = [e for e in history if e.kind == "failure" and e.topic == newest.topic
                        and e.seq < newest.seq and 0 <= newest.occurred_ms - e.occurred_ms <= 300_000]
            if failures:
                failure = failures[-1]
                self._used.add((session, newest.event_id))
                self._used.add((session, failure.event_id))
                self._last_cue[session] = now_ms
                return VoiceCue("callback", (failure.event_id, newest.event_id),
                                "Reference the verified earlier setback and verified recovery. "
                                "Use casual, brief in-game continuity; do not invent a personal past.")
        self._used.add((session, newest.event_id))
        self._last_cue[session] = now_ms
        return VoiceCue(newest.kind, (newest.event_id,), _PHRASES[newest.kind])

    def summary(self) -> dict[str, int]:
        return {"sessions": len(self._seq), "moments": self._total, "cues": len(self._used)}
