"""Opt-in, host-only bridge from independently audible voice to voice-health evidence.

STAR's speech queue is not proof anyone heard it. This adapter joins a trusted
speech-request timestamp, an OS/device *loopback* witness, and an independent
completed-turn review before sending any sample to LongSessionVoiceHealth.
The adapter NEVER captures audio, controls PCM, OBS, game input, or models.

Caller provenance flags are declarations, not cryptographic authentication.
A trusted native host must own this object and source the timestamps from a
single monotonic clock; do not expose these methods as LLM/chat tools.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from threading import RLock
from typing import cast

from .stream_long_session_voice_health import LongSessionVoiceHealth, ReviewedVoiceTurn

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_MAX_CLOCK = 1e13
_MAX_WAIT_MS = 30_000.0
_MAX_CAPTURE_AGE_MS = 5_000.0
_MAX_TURN_MS = 60_000.0
_MAX_TURNS = 2048


def _id(value: object, label: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{label} must be a bounded opaque ID")
    return value


def _ms(value: object, label: str) -> float:
    if type(value) not in (float, int):
        raise ValueError(f"{label} must be a finite host clock")
    try:
        result = float(cast(float | int, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a finite host clock") from exc
    if not math.isfinite(result) or not 0 <= result <= _MAX_CLOCK:
        raise ValueError(f"{label} outside monotonic host clock bounds")
    return result


@dataclass(frozen=True)
class SpeechRequestWitness:
    """Issued by trusted host BEFORE TTS; never by the response model."""

    turn_id: str
    output_epoch: str
    scene_epoch: str
    requested_at_ms: float

    def __post_init__(self) -> None:
        for field in ("turn_id", "output_epoch", "scene_epoch"):
            _id(getattr(self, field), field)
        _ms(self.requested_at_ms, "requested_at_ms")


@dataclass(frozen=True)
class DeviceAudibleWitness:
    """First sound independently detected at the output device/loopback.

    PCM enqueued or a TTS callback invoked is NOT a valid audible witness.
    The host is responsible for correlating the output epoch to the device.
    """

    turn_id: str
    output_epoch: str
    first_audible_ms: float
    observed_at_ms: float
    device_loopback_confirmed: bool

    def __post_init__(self) -> None:
        _id(self.turn_id, "turn_id")
        _id(self.output_epoch, "output_epoch")
        _ms(self.first_audible_ms, "first_audible_ms")
        _ms(self.observed_at_ms, "observed_at_ms")
        if type(self.device_loopback_confirmed) is not bool:
            raise ValueError("device_loopback_confirmed must be boolean")


@dataclass(frozen=True)
class CompletedVoiceReview:
    """Independent turn-end and quality judgment, no transcripts or identities."""

    turn_id: str
    output_epoch: str
    completed_audible_ms: float
    observed_at_ms: float
    voice_consistency: float
    grounded: bool
    repeated: bool
    interruption_respected: bool
    reviewer_confirmed: bool

    def __post_init__(self) -> None:
        _id(self.turn_id, "turn_id")
        _id(self.output_epoch, "output_epoch")
        _ms(self.completed_audible_ms, "completed_audible_ms")
        _ms(self.observed_at_ms, "observed_at_ms")
        if type(self.voice_consistency) not in (float, int):
            raise ValueError("voice consistency must be a numeric score")
        try:
            score = float(self.voice_consistency)
        except (OverflowError, ValueError) as exc:
            raise ValueError("voice consistency must be finite") from exc
        if not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("voice consistency must be within 0..1")
        if any(
            type(value) is not bool
            for value in (
                self.grounded,
                self.repeated,
                self.interruption_respected,
                self.reviewer_confirmed,
            )
        ):
            raise ValueError("independent review flags must be booleans")


@dataclass(frozen=True)
class AudibleJoinMetrics:
    enabled: bool
    faulted: bool
    pending: bool
    has_device_witness: bool
    reviewed_turns: int
    rejected: int
    authorizes_audio: bool = False
    authorizes_broadcast: bool = False


class AudibleTurnEvidenceAssembler:
    """One-flight, bounded session evidence joining; default OFF.

    Any identity, clock, device-witness, scene, ordering or provenance
    mismatch poisons this assembler until explicit owner-controlled rearm.
    Prior good results cannot be silently inherited by a new output session.
    Physical audible evidence comes ONLY from an independently trusted native
    loopback. Even a successful join is still host-ATTESTED, not verified by
    this pure Python module.
    """

    def __init__(self, health: LongSessionVoiceHealth) -> None:
        if type(health) is not LongSessionVoiceHealth:
            raise TypeError("existing long-session voice guard required")
        self._health = health
        self._lock = RLock()
        self._enabled = False
        self._fault: str | None = None
        self._session: str | None = None
        self._last_now_ms: float | None = None
        self._pending: SpeechRequestWitness | None = None
        self._audible: DeviceAudibleWitness | None = None
        self._seen: set[str] = set()
        self._accepted = 0
        self._rejected = 0

    def enable(self, *, owner_approved: bool = False, session_id: str) -> None:
        if owner_approved is not True:
            raise PermissionError("trusted host must explicitly opt in")
        session = _id(session_id, "session_id")
        with self._lock:
            if self._enabled:
                raise RuntimeError("disable before arming a new voice session")
            state = self._health.metrics()
            # A new native output session must start with a NEW, independently
            # warmed voice baseline. Never inherit a green previous session.
            if (
                not state["enabled"]
                or state["accepted"] != 0
                or state["faulted"]
                or state["baseline"] != 0
                or state["recent"] != 0
            ):
                raise RuntimeError("fresh owner-armed empty voice guard required")
            self._enabled = True
            self._session = session
            self._last_now_ms = None
            self._pending = None
            self._audible = None
            self._seen.clear()
            self._fault = None
            self._accepted = 0
            self._rejected = 0

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._session = None
            self._pending = None
            self._audible = None
            self._seen.clear()
            self._last_now_ms = None
            self._fault = None

    def _now(self, value: object) -> float:
        now = _ms(value, "now_ms")
        if self._last_now_ms is not None and now < self._last_now_ms:
            self._trip("host_clock_reversed")
            raise ValueError("host clock reversed")
        self._last_now_ms = now
        return now

    def _trip(self, reason: str) -> None:
        self._fault = reason
        self._pending = None
        self._audible = None
        self._rejected += 1

    def begin(self, request: SpeechRequestWitness, *, session_id: str, now_ms: float) -> bool:
        """Reserve one independently identified turn; no audio authorization."""
        with self._lock:
            if not self._enabled or self._fault is not None:
                return False
            now = self._now(now_ms)
            if (
                type(request) is not SpeechRequestWitness
                or session_id != self._session
                or self._pending is not None
                or request.turn_id in self._seen
                or len(self._seen) >= _MAX_TURNS
                or request.requested_at_ms > now
                or now - request.requested_at_ms > _MAX_CAPTURE_AGE_MS
            ):
                self._trip("untrusted_or_replayed_speech_request")
                return False
            self._seen.add(request.turn_id)
            self._pending = request
            return True

    def heard(self, witness: DeviceAudibleWitness, *, now_ms: float) -> bool:
        """Accept ONLY independently observed first sound, not queued PCM."""
        with self._lock:
            if not self._enabled or self._fault is not None:
                return False
            now = self._now(now_ms)
            request = self._pending
            if (
                type(witness) is not DeviceAudibleWitness
                or request is None
                or self._audible is not None
                or witness.turn_id != request.turn_id
                or witness.output_epoch != request.output_epoch
                or not witness.device_loopback_confirmed
                or not request.requested_at_ms <= witness.first_audible_ms <= witness.observed_at_ms <= now
                or witness.first_audible_ms - request.requested_at_ms > _MAX_WAIT_MS
                or now - witness.observed_at_ms > _MAX_CAPTURE_AGE_MS
                or witness.observed_at_ms - witness.first_audible_ms > _MAX_CAPTURE_AGE_MS
            ):
                self._trip("device_audibility_unverified_or_unmatched")
                return False
            self._audible = witness
            return True

    def reviewed(
        self, review: CompletedVoiceReview, *, session_id: str,
        current_scene_epoch: str, now_ms: float,
    ) -> bool:
        """Join first physical sound and separately reviewed COMPLETE speech."""
        with self._lock:
            if not self._enabled or self._fault is not None:
                return False
            now = self._now(now_ms)
            request, audible = self._pending, self._audible
            if (
                type(review) is not CompletedVoiceReview
                or request is None
                or audible is None
                or session_id != self._session
                or current_scene_epoch != request.scene_epoch
                or review.turn_id != request.turn_id
                or review.output_epoch != request.output_epoch
                or not review.reviewer_confirmed
                or not audible.first_audible_ms <= review.completed_audible_ms <= review.observed_at_ms <= now
                or review.completed_audible_ms - audible.first_audible_ms > _MAX_TURN_MS
                or now - review.observed_at_ms > _MAX_CAPTURE_AGE_MS
            ):
                self._trip("independent_turn_review_unverified_or_unmatched")
                return False
            turn = ReviewedVoiceTurn(
                turn_id=request.turn_id,
                measured_at_ms=review.observed_at_ms,
                # Independently measured from two physical timestamps; the
                # reviewer cannot invent a lower first-audio latency score.
                first_audio_latency_ms=audible.first_audible_ms - request.requested_at_ms,
                voice_consistency=review.voice_consistency,
                grounded=review.grounded,
                repeated=review.repeated,
                interruption_respected=review.interruption_respected,
            )
            if not self._health.ingest(turn, now_ms=now, host_verified=True):
                self._trip("voice_health_rejected_joined_evidence")
                return False
            self._pending = None
            self._audible = None
            self._accepted += 1
            return True

    def metrics(self) -> AudibleJoinMetrics:
        """Safe aggregate diagnostic without text, PCM, viewer data or IDs."""
        with self._lock:
            return AudibleJoinMetrics(
                self._enabled,
                self._fault is not None,
                self._pending is not None,
                self._audible is not None,
                self._accepted,
                self._rejected,
            )


__all__ = [
    "SpeechRequestWitness",
    "DeviceAudibleWitness",
    "CompletedVoiceReview",
    "AudibleJoinMetrics",
    "AudibleTurnEvidenceAssembler",
]
