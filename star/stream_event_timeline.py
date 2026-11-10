"""Session-local cross-modal event alignment for STAR's real-time VTuber.

The trusted Windows host supplies already-classified, content-free event
receipts on one shared monotonic clock. This module correlates when audio,
vision, game, chat, avatar and host events occurred; it does not interpret media,
identify people, authenticate sensors, run inference, or control devices.

A close timestamp is temporal proximity, not proof of causation. Timestamp
uncertainty is carried into every pair so consumers cannot over-read ordering.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hashlib
import json
import math
import re
import secrets
from threading import RLock

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,47}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_HEX_SESSION = re.compile(r"[a-f0-9]{32}\Z")
_HEX_EPOCH = re.compile(r"[a-f0-9]{16}\Z")
_MAX_CLOCK_MS = 10**13

_KINDS: dict[str, frozenset[str]] = {
    "audio": frozenset({
        "speech_start", "speech_end", "owner_interrupt",
        "background_speech", "backchannel",
    }),
    "vision": frozenset({
        "scene_change", "ui_change", "visual_hazard",
        "visual_objective", "screen_observation",
    }),
    "game": frozenset({
        "objective_change", "damage", "death", "victory",
        "respawn", "state_change", "input_ack",
    }),
    "chat": frozenset({
        "viewer_question", "viewer_reaction", "moderation_event", "chat_burst",
    }),
    "avatar": frozenset({
        "speech_started", "speech_stopped", "expression_started",
        "expression_completed",
    }),
    "host": frozenset({"load_pressure", "session_marker"}),
}


def _clock(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite monotonic millisecond value")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be finite") from exc
    if not math.isfinite(result) or not 0 <= result <= _MAX_CLOCK_MS:
        raise ValueError(f"{label} must be within the supported monotonic clock range")
    return result


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{label} must be a bounded ASCII identifier")
    return value


@dataclass(frozen=True)
class TimelineSession:
    """Opaque session labels; these are replay guards, not auth credentials."""

    session_id: str
    clock_epoch: str


@dataclass(frozen=True)
class TimelineEvent:
    """Content-free event metadata from one trusted host adapter.

    captured_ms must already be translated by the host into the shared
    monotonic clock named by clock_epoch. evidence_sha256 points to evidence
    retained elsewhere; it neither contains nor authenticates that evidence.
    """

    session_id: str
    clock_epoch: str
    source_id: str
    modality: str
    sequence: int
    captured_ms: float
    kind: str
    evidence_sha256: str
    confidence: float | None = None
    uncertainty_ms: float = 0.0

    def __post_init__(self) -> None:
        if type(self.session_id) is not str or _HEX_SESSION.fullmatch(self.session_id) is None:
            raise ValueError("invalid session identifier")
        if type(self.clock_epoch) is not str or _HEX_EPOCH.fullmatch(self.clock_epoch) is None:
            raise ValueError("invalid clock epoch")
        _identifier(self.source_id, "source_id")
        if type(self.modality) is not str or self.modality not in _KINDS:
            raise ValueError("unsupported modality")
        if type(self.kind) is not str or self.kind not in _KINDS[self.modality]:
            raise ValueError("event kind is not allowed for this modality")
        if type(self.sequence) is not int or not 1 <= self.sequence <= 1_000_000_000:
            raise ValueError("sequence must be a positive bounded integer")
        _clock(self.captured_ms, "captured_ms")
        if type(self.evidence_sha256) is not str or _SHA.fullmatch(self.evidence_sha256) is None:
            raise ValueError("evidence_sha256 must be a lowercase SHA-256 digest")
        if self.confidence is not None:
            if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
                raise ValueError("confidence must be numeric or absent")
            if not math.isfinite(float(self.confidence)) or not 0 <= float(self.confidence) <= 1:
                raise ValueError("confidence must be between zero and one")
        uncertainty = _clock(self.uncertainty_ms, "uncertainty_ms")
        if uncertainty > 5000:
            raise ValueError("uncertainty_ms must not exceed 5000")


@dataclass(frozen=True)
class IngestResult:
    accepted: bool
    reason: str
    event_key: str | None = None


@dataclass(frozen=True)
class EventSummary:
    event_key: str
    source_id: str
    modality: str
    kind: str
    sequence: int
    captured_ms: float
    age_ms: float
    confidence: float | None
    uncertainty_ms: float


@dataclass(frozen=True)
class AlignmentPair:
    earlier: EventSummary
    later: EventSummary
    skew_ms: float
    relative_order_confident: bool


@dataclass(frozen=True)
class TimelineSnapshot:
    session_id: str
    clock_epoch: str
    now_ms: float
    events: tuple[EventSummary, ...]
    aligned_pairs: tuple[AlignmentPair, ...]
    fresh_modalities: tuple[str, ...]
    stale_pruned: int
    accepted_total: int
    rejected_total: int
    faulted: bool
    note: str = (
        "Host-derived event metadata only. Temporal proximity is not causation; "
        "the host must authenticate sensors and supply a shared monotonic clock."
    )

    def context_json(self) -> str:
        """Bounded model-facing metadata; never contains media, chat text or IDs of people."""
        payload = {
            "type": "star_stream_timeline_metadata",
            "events": [
                {
                    "event": e.event_key,
                    "modality": e.modality,
                    "kind": e.kind,
                    "age_ms": round(e.age_ms, 1),
                    "confidence": None if e.confidence is None else round(e.confidence, 3),
                    "uncertainty_ms": round(e.uncertainty_ms, 1),
                }
                for e in self.events
            ],
            "aligned_pairs": [
                {
                    "earlier": p.earlier.event_key,
                    "later": p.later.event_key,
                    "skew_ms": round(p.skew_ms, 1),
                    "relative_order_confident": p.relative_order_confident,
                }
                for p in self.aligned_pairs
            ],
            "fresh_modalities": list(self.fresh_modalities),
            "note": self.note,
        }
        encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode("utf-8")) > 16_384:
            raise ValueError("timeline context exceeded its hard size bound")
        return encoded


class StreamEventTimeline:
    """Bounded in-memory cross-modal event timeline.

    The timeline has no capture, microphone, network, inference, persistence,
    TTS, avatar, OBS or game-control implementation. A trusted host is
    responsible for event classification, source authentication and clock
    translation. A new session is required after any host-clock regression.
    """

    def __init__(
        self,
        *,
        max_events: int = 128,
        max_sources: int = 16,
        max_age_ms: float = 2500.0,
        future_tolerance_ms: float = 25.0,
        alignment_window_ms: float = 250.0,
        max_alignment_pairs: int = 32,
    ) -> None:
        if type(max_events) is not int or not 8 <= max_events <= 512:
            raise ValueError("max_events must be between 8 and 512")
        if type(max_sources) is not int or not 1 <= max_sources <= 32:
            raise ValueError("max_sources must be between 1 and 32")
        if type(max_alignment_pairs) is not int or not 1 <= max_alignment_pairs <= 128:
            raise ValueError("max_alignment_pairs must be between 1 and 128")
        self.max_age_ms = _clock(max_age_ms, "max_age_ms")
        self.future_tolerance_ms = _clock(future_tolerance_ms, "future_tolerance_ms")
        self.alignment_window_ms = _clock(alignment_window_ms, "alignment_window_ms")
        if not 100 <= self.max_age_ms <= 10_000:
            raise ValueError("max_age_ms must be between 100 and 10000")
        if self.future_tolerance_ms > 250:
            raise ValueError("future_tolerance_ms must not exceed 250")
        if not 25 <= self.alignment_window_ms <= 1000:
            raise ValueError("alignment_window_ms must be between 25 and 1000")
        self.max_events = max_events
        self.max_sources = max_sources
        self.max_alignment_pairs = max_alignment_pairs
        self._lock = RLock()
        self._enabled = False
        self._faulted = False
        self._session: TimelineSession | None = None
        self._last_now_ms: float | None = None
        self._events: deque[TimelineEvent] = deque(maxlen=max_events)
        self._watermarks: dict[tuple[str, str], tuple[int, float]] = {}
        self._accepted = 0
        self._rejected = 0
        self._stale_pruned = 0

    def enable(self, *, owner_approved: bool = False, now_ms: float) -> TimelineSession:
        now = _clock(now_ms, "now_ms")
        if owner_approved is not True:
            raise PermissionError("explicit owner approval required to start a stream timeline")
        with self._lock:
            if self._enabled:
                raise RuntimeError("disable before starting a new timeline session")
            session = TimelineSession(secrets.token_hex(16), secrets.token_hex(8))
            self._session = session
            self._enabled = True
            self._faulted = False
            self._last_now_ms = now
            self._events.clear()
            self._watermarks.clear()
            self._accepted = self._rejected = self._stale_pruned = 0
            return session

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._faulted = False
            self._session = None
            self._last_now_ms = None
            self._events.clear()
            self._watermarks.clear()
            self._accepted = self._rejected = self._stale_pruned = 0

    def _advance(self, now_ms: float) -> float:
        now = _clock(now_ms, "now_ms")
        if self._last_now_ms is not None and now < self._last_now_ms:
            self._faulted = True
            self._events.clear()
            self._watermarks.clear()
            self._rejected += 1
            raise ValueError("host monotonic clock moved backwards; start a new session")
        self._last_now_ms = now
        return now

    def _key(self, event: TimelineEvent) -> str:
        assert self._session is not None
        material = (
            f"{self._session.session_id}|{event.modality}|"
            f"{event.source_id}|{event.sequence}"
        ).encode("ascii")
        return hashlib.sha256(material).hexdigest()[:20]

    def ingest(self, event: TimelineEvent, *, now_ms: float) -> IngestResult:
        if not isinstance(event, TimelineEvent):
            raise TypeError("expected TimelineEvent")
        with self._lock:
            try:
                now = self._advance(now_ms)
            except ValueError:
                return IngestResult(False, "host_clock_reversed")
            if not self._enabled or self._session is None:
                self._rejected += 1
                return IngestResult(False, "timeline_disabled")
            if self._faulted:
                self._rejected += 1
                return IngestResult(False, "timeline_faulted")
            if event.session_id != self._session.session_id:
                self._rejected += 1
                return IngestResult(False, "stale_session")
            if event.clock_epoch != self._session.clock_epoch:
                self._rejected += 1
                return IngestResult(False, "clock_epoch_mismatch")
            age = now - float(event.captured_ms)
            if age < -self.future_tolerance_ms:
                self._rejected += 1
                return IngestResult(False, "future_dated")
            if age > self.max_age_ms:
                self._rejected += 1
                return IngestResult(False, "stale_event")
            source_key = (event.modality, event.source_id)
            if source_key not in self._watermarks and len(self._watermarks) >= self.max_sources:
                self._rejected += 1
                return IngestResult(False, "source_limit_reached")
            previous = self._watermarks.get(source_key)
            if previous is not None:
                last_sequence, last_capture = previous
                if event.sequence <= last_sequence:
                    self._rejected += 1
                    return IngestResult(False, "replayed_or_out_of_order_sequence")
                if float(event.captured_ms) < last_capture:
                    self._rejected += 1
                    return IngestResult(False, "source_clock_reversed")
            self._watermarks[source_key] = (event.sequence, float(event.captured_ms))
            self._events.append(event)
            self._accepted += 1
            return IngestResult(True, "accepted", self._key(event))

    def snapshot(self, *, now_ms: float) -> TimelineSnapshot:
        with self._lock:
            try:
                now = self._advance(now_ms)
            except ValueError:
                # The previous trusted monotonic value is the only safe clock
                # after a reversal. Return an empty faulted snapshot, never stale
                # context, and require disable()+enable() for a fresh epoch.
                now = self._last_now_ms if self._last_now_ms is not None else 0.0
            if not self._enabled or self._session is None or self._faulted:
                session = self._session or TimelineSession("0" * 32, "0" * 16)
                return TimelineSnapshot(
                    session.session_id, session.clock_epoch, now, (), (), (),
                    self._stale_pruned, self._accepted, self._rejected, self._faulted,
                )
            kept: deque[TimelineEvent] = deque(maxlen=self.max_events)
            for event in self._events:
                if now - float(event.captured_ms) <= self.max_age_ms:
                    kept.append(event)
                else:
                    self._stale_pruned += 1
            self._events = kept
            summaries = tuple(
                EventSummary(
                    self._key(event),
                    event.source_id,
                    event.modality,
                    event.kind,
                    event.sequence,
                    float(event.captured_ms),
                    max(0.0, now - float(event.captured_ms)),
                    None if event.confidence is None else float(event.confidence),
                    float(event.uncertainty_ms),
                )
                for event in sorted(
                    self._events,
                    key=lambda item: (item.captured_ms, item.modality, item.source_id, item.sequence),
                )
            )
            pairs: list[AlignmentPair] = []
            for index, left in enumerate(summaries):
                for right in summaries[index + 1:]:
                    if left.modality == right.modality:
                        continue
                    skew = abs(left.captured_ms - right.captured_ms)
                    if skew <= self.alignment_window_ms:
                        earlier, later = (left, right) if left.captured_ms <= right.captured_ms else (right, left)
                        uncertain = earlier.uncertainty_ms + later.uncertainty_ms
                        pairs.append(AlignmentPair(earlier, later, skew, skew > uncertain))
            pairs.sort(key=lambda pair: (pair.skew_ms, -max(pair.earlier.age_ms, pair.later.age_ms)))
            fresh = tuple(sorted({event.modality for event in summaries}))
            return TimelineSnapshot(
                self._session.session_id,
                self._session.clock_epoch,
                now,
                summaries,
                tuple(pairs[:self.max_alignment_pairs]),
                fresh,
                self._stale_pruned,
                self._accepted,
                self._rejected,
                self._faulted,
            )

    def stats(self) -> dict[str, int | bool]:
        """Aggregate counters only; no media, payloads, chat text or people."""
        with self._lock:
            return {
                "enabled": self._enabled,
                "faulted": self._faulted,
                "buffered_events": len(self._events),
                "sources": len(self._watermarks),
                "accepted": self._accepted,
                "rejected": self._rejected,
                "stale_pruned": self._stale_pruned,
            }
