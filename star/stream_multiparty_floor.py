"""Session-scoped multi-party floor control for STAR's live voice path.

A trusted local adapter supplies content-free diarization/addressee receipts.
Speaker slots are anonymous, ephemeral labels, not identities. This module
keeps only coarse turn metadata; it stores no audio, transcript, voiceprint,
speaker name, chat text, or cross-session profile.

The gate decides whether a spoken viewer turn is addressed to STAR. It does
not authenticate the owner, interrupt playback, authorize TTS, or grant tools.
Owner barge-in remains exclusively governed by the existing TurnTakingGate.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from threading import RLock

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\\Z")
_ADDRESSEES = frozenset({"star", "other", "group", "unknown"})
_SPEECH_ACTS = frozenset({
    "question", "request", "correction", "backchannel",
    "side_conversation", "statement", "uncertain",
})
_ACTIONS = frozenset({"respond", "listen", "backchannel", "silence", "hold"})
_REASONS = frozenset({
    "addressed_question", "addressed_request", "addressed_correction",
    "listener_backchannel", "turn_in_progress", "group_address",
    "other_addressee", "side_conversation", "uncertain_addressee",
    "low_speaker_confidence", "low_act_confidence", "overlapping_speakers",
    "interrupted_turn", "stale_receipt", "future_receipt", "clock_regression",
    "missing_receipt", "replayed_receipt", "owner_opt_in_missing",
    "session_mismatch", "sequence_replay", "capacity_exhausted",
})


def _finite(value: object, name: str, *, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= maximum:
        raise ValueError(f"{name} is outside its supported range")
    return number


@dataclass(frozen=True)
class FloorObservation:
    """One host-derived turn receipt; no transcript or biometric data."""

    turn_id: str
    session_epoch: int
    sequence: int
    captured_ms: float
    speaker_slot: int
    addressed_to: str
    speech_act: str
    speaker_confidence: float
    addressee_confidence: float
    act_confidence: float
    active_speakers: int = 1
    turn_complete: bool = True
    interrupted: bool = False

    def __post_init__(self) -> None:
        if type(self.turn_id) is not str or _ID.fullmatch(self.turn_id) is None:
            raise ValueError("turn_id must be a bounded opaque identifier")
        for name in ("session_epoch", "sequence"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 1_000_000_000:
                raise ValueError(f"{name} must be a positive bounded integer")
        _finite(self.captured_ms, "captured_ms", maximum=1e13)
        if type(self.speaker_slot) is not int or not 1 <= self.speaker_slot <= 16:
            raise ValueError("speaker_slot must be an ephemeral slot from 1..16")
        if type(self.addressed_to) is not str or self.addressed_to not in _ADDRESSEES:
            raise ValueError("unsupported addressee")
        if type(self.speech_act) is not str or self.speech_act not in _SPEECH_ACTS:
            raise ValueError("unsupported speech act")
        for name in ("speaker_confidence", "addressee_confidence", "act_confidence"):
            _finite(getattr(self, name), name, maximum=1.0)
        if type(self.active_speakers) is not int or not 1 <= self.active_speakers <= 8:
            raise ValueError("active_speakers must be in 1..8")
        if type(self.turn_complete) is not bool or type(self.interrupted) is not bool:
            raise ValueError("turn state flags must be booleans")


@dataclass(frozen=True)
class FloorPolicy:
    """Conservative provisional thresholds; calibrate with held-out MP-Bench-like data."""

    max_age_ms: float = 1500.0
    future_tolerance_ms: float = 25.0
    max_signal_skew_ms: float = 250.0
    min_speaker_confidence: float = 0.80
    min_addressee_confidence: float = 0.82
    min_act_confidence: float = 0.75
    max_active_speakers: int = 1
    max_pending: int = 64
    max_seen: int = 512

    def __post_init__(self) -> None:
        for name, lo, hi in (
            ("max_age_ms", 100.0, 10_000.0),
            ("future_tolerance_ms", 0.0, 500.0),
            ("max_signal_skew_ms", 0.0, 2_000.0),
            ("min_speaker_confidence", 0.0, 1.0),
            ("min_addressee_confidence", 0.0, 1.0),
            ("min_act_confidence", 0.0, 1.0),
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be numeric")
            if not math.isfinite(float(value)) or not lo <= value <= hi:
                raise ValueError(f"{name} is outside its supported range")
        if type(self.max_active_speakers) is not int or not 1 <= self.max_active_speakers <= 8:
            raise ValueError("max_active_speakers must be in 1..8")
        if type(self.max_pending) is not int or not 1 <= self.max_pending <= 256:
            raise ValueError("max_pending must be in 1..256")
        if type(self.max_seen) is not int or not 1 <= self.max_seen <= 4096:
            raise ValueError("max_seen must be in 1..4096")
        if self.max_seen < self.max_pending:
            raise ValueError("max_seen must cover the pending window")


@dataclass(frozen=True)
class FloorDecision:
    """One-use host-side recommendation; it is not permission to play audio."""

    action: str
    reason: str
    turn_id: str
    session_epoch: int
    sequence: int
    age_ms: float

    def __post_init__(self) -> None:
        if self.action not in _ACTIONS or self.reason not in _REASONS:
            raise ValueError("invalid floor decision")
        if type(self.turn_id) is not str or _ID.fullmatch(self.turn_id) is None:
            raise ValueError("invalid decision turn_id")
        if type(self.session_epoch) is not int or self.session_epoch < 1:
            raise ValueError("invalid decision session")
        if type(self.sequence) is not int or self.sequence < 1:
            raise ValueError("invalid decision sequence")
        if isinstance(self.age_ms, bool) or not isinstance(self.age_ms, (int, float)):
            raise ValueError("invalid decision age")
        if not math.isfinite(float(self.age_ms)):
            raise ValueError("invalid decision age")

    @property
    def should_speak(self) -> bool:
        return self.action == "respond"


class StreamMultipartyFloorGate:
    """Bounded one-shot addressee/floor gate for spoken viewer events.

    The native host must supply session-local diarization slots and an
    independently produced addressee estimate. Diarization labels distinguish
    voices only; they are not names, owner authentication, or persistent IDs.
    A clock fault, overlap, ambiguity, stale receipt, or missing evidence
    suppresses optional viewer speech. This gate never suppresses the separate
    authenticated-owner interruption path or non-spoken chat/game events.
    """

    def __init__(self, policy: FloorPolicy | None = None) -> None:
        self.policy = policy if policy is not None else FloorPolicy()
        if type(self.policy) is not FloorPolicy:
            raise TypeError("policy must be FloorPolicy")
        self._lock = RLock()
        self._enabled = False
        self._session_epoch = 0
        self._last_sequence = 0
        self._last_capture_ms: float | None = None
        self._last_now_ms: float | None = None
        self._clock_fault = False
        self._pending: dict[str, FloorObservation] = {}
        self._seen: set[str] = set()
        self._counts = {
            "accepted": 0, "rejected": 0, "respond": 0, "listen": 0,
            "backchannel": 0, "silence": 0, "hold": 0,
            "clock_faults": 0, "capacity_rejections": 0,
        }

    @property
    def session_epoch(self) -> int:
        with self._lock:
            return self._session_epoch

    def enable(self, *, owner_approved: bool = False) -> int:
        if owner_approved is not True:
            raise PermissionError("multiparty floor control requires owner approval")
        with self._lock:
            if self._enabled:
                raise RuntimeError("disable before starting another floor session")
            if self._session_epoch >= 1_000_000_000:
                raise RuntimeError("floor session epoch exhausted")
            self._session_epoch += 1
            self._last_sequence = 0
            self._last_capture_ms = None
            self._last_now_ms = None
            self._clock_fault = False
            self._pending.clear()
            self._seen.clear()
            self._enabled = True
            return self._session_epoch

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._pending.clear()
            self._seen.clear()
            self._last_sequence = 0
            self._last_capture_ms = None
            self._last_now_ms = None
            self._clock_fault = False
            if self._session_epoch < 1_000_000_000:
                self._session_epoch += 1

    def observe(self, observation: FloorObservation) -> bool:
        if type(observation) is not FloorObservation:
            raise TypeError("expected FloorObservation")
        with self._lock:
            if not self._enabled or self._clock_fault:
                self._counts["rejected"] += 1
                return False
            if observation.session_epoch != self._session_epoch:
                self._counts["rejected"] += 1
                return False
            if observation.sequence <= self._last_sequence:
                self._counts["rejected"] += 1
                return False
            if (self._last_capture_ms is not None
                    and observation.captured_ms <= self._last_capture_ms):
                self._counts["rejected"] += 1
                return False
            if observation.turn_id in self._seen:
                self._counts["rejected"] += 1
                return False
            if (len(self._pending) >= self.policy.max_pending
                    or len(self._seen) >= self.policy.max_seen):
                self._counts["capacity_rejections"] += 1
                return False
            self._last_sequence = observation.sequence
            self._last_capture_ms = float(observation.captured_ms)
            self._pending[observation.turn_id] = observation
            self._seen.add(observation.turn_id)
            self._counts["accepted"] += 1
            return True

    def decide(self, turn_id: str, *, now_ms: float) -> FloorDecision:
        if type(turn_id) is not str or _ID.fullmatch(turn_id) is None:
            raise ValueError("turn_id must be a bounded opaque identifier")
        now = _finite(now_ms, "now_ms", maximum=1e13)
        with self._lock:
            if not self._enabled:
                return self._decision("hold", "owner_opt_in_missing", turn_id, None, now)
            if self._clock_fault:
                return self._decision("hold", "clock_regression", turn_id, None, now)
            if self._last_now_ms is not None and now < self._last_now_ms:
                self._clock_fault = True
                self._counts["clock_faults"] += 1
                return self._decision("hold", "clock_regression", turn_id, None, now)
            self._last_now_ms = now
            observation = self._pending.pop(turn_id, None)
            if observation is None:
                self._counts["rejected"] += 1
                return self._decision("hold", "missing_receipt", turn_id, None, now)
            age = now - float(observation.captured_ms)
            if age < -self.policy.future_tolerance_ms:
                return self._decision("hold", "future_receipt", turn_id, observation, age)
            if age > self.policy.max_age_ms:
                return self._decision("hold", "stale_receipt", turn_id, observation, age)
            if observation.interrupted:
                return self._decision("hold", "interrupted_turn", turn_id, observation, age)
            if observation.active_speakers > self.policy.max_active_speakers:
                return self._decision("hold", "overlapping_speakers", turn_id, observation, age)
            if observation.speaker_confidence < self.policy.min_speaker_confidence:
                return self._decision("hold", "low_speaker_confidence", turn_id, observation, age)
            if not observation.turn_complete:
                return self._decision("listen", "turn_in_progress", turn_id, observation, age)
            if (observation.addressed_to == "unknown"
                    or observation.addressee_confidence < self.policy.min_addressee_confidence):
                return self._decision("hold", "uncertain_addressee", turn_id, observation, age)
            if observation.speech_act == "side_conversation":
                return self._decision("silence", "side_conversation", turn_id, observation, age)
            if observation.addressed_to == "other":
                return self._decision("silence", "other_addressee", turn_id, observation, age)
            if observation.addressed_to == "group":
                return self._decision("listen", "group_address", turn_id, observation, age)
            if observation.act_confidence < self.policy.min_act_confidence:
                return self._decision("hold", "low_act_confidence", turn_id, observation, age)
            if observation.speech_act == "backchannel":
                return self._decision("backchannel", "listener_backchannel", turn_id, observation, age)
            reason_by_act = {
                "question": "addressed_question",
                "request": "addressed_request",
                "correction": "addressed_correction",
            }
            if observation.speech_act in reason_by_act:
                return self._decision("respond", reason_by_act[observation.speech_act],
                                      turn_id, observation, age)
            return self._decision("listen", "turn_in_progress", turn_id, observation, age)

    def _decision(
        self, action: str, reason: str, turn_id: str,
        observation: FloorObservation | None, age_ms: float,
    ) -> FloorDecision:
        if observation is None:
            epoch, sequence = self._session_epoch, 0
        else:
            epoch, sequence = observation.session_epoch, observation.sequence
        self._counts[action] += 1
        return FloorDecision(action, reason, turn_id, epoch, sequence, float(age_ms))

    def status(self) -> dict[str, int | bool]:
        """Aggregate-only diagnostics; never return speaker slots or turn IDs."""
        with self._lock:
            return {
                **self._counts,
                "enabled": self._enabled,
                "session_epoch": self._session_epoch,
                "pending": len(self._pending),
                "clock_fault": self._clock_fault,
            }


__all__ = ["FloorObservation", "FloorPolicy", "FloorDecision", "StreamMultipartyFloorGate"]
