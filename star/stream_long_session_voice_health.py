"""Privacy-minimal, opt-in long-session voice stability advisory for Star.

It detects *regressions* across an independently reviewed long conversation.
The trusted native host provides monotonic times and external quality verdicts;
a model cannot grade its own voice. Never ingest PCM, transcripts, viewer IDs,
game captures, or generated speech in this module.

This module NEVER changes TTS, broadcasts, invokes a model, or controls games.
It can only advise NaturalTurnBridge to defer nonessential commentary.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math
import re
from statistics import median
from threading import RLock
from typing import cast

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_MAX_MS = 1e13
_BASELINE = 8
_RECENT = 8
_MIN_MATURE_MS = 300_000.0
_MAX_AGE_MS = 30_000.0
_MAX_INGEST_AGE_MS = 5_000.0
_MAX_SAMPLE_GAP_MS = 120_000.0


def _number(value: object, name: str, *, maximum: float) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{name} requires a finite numeric value")
    try:
        result = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{name} requires a finite numeric value") from exc
    if not math.isfinite(result) or not 0 <= result <= maximum:
        raise ValueError(f"{name} outside allowed range")
    return result


@dataclass(frozen=True)
class ReviewedVoiceTurn:
    """One externally scored, host-attested *completed* audible speech turn.

    Ratios come from an independent evaluator or observable playback evidence,
    never the speech model's self-judgment. All IDs are opaque and private.
    """

    turn_id: str
    measured_at_ms: float
    first_audio_latency_ms: float
    voice_consistency: float
    grounded: bool
    repeated: bool
    interruption_respected: bool

    def __post_init__(self) -> None:
        if type(self.turn_id) is not str or _ID.fullmatch(self.turn_id) is None:
            raise ValueError("turn_id must be a bounded opaque identifier")
        _number(self.measured_at_ms, "measured_at_ms", maximum=_MAX_MS)
        _number(self.first_audio_latency_ms, "first_audio_latency_ms", maximum=60_000)
        _number(self.voice_consistency, "voice_consistency", maximum=1)
        if any(
            type(value) is not bool
            for value in (
                self.grounded,
                self.repeated,
                self.interruption_respected,
            )
        ):
            raise ValueError("quality outcomes require explicit booleans")


@dataclass(frozen=True)
class VoiceHealthAdvice:
    status: str  # disabled | warming | stable | degraded | stale | faulted
    reason: str
    allow_optional_commentary: bool
    observed_baseline: int
    observed_recent: int
    host_verified_evidence_only: bool = True
    authorizes_audio: bool = False
    authorizes_broadcast: bool = False


class LongSessionVoiceHealth:
    """Rolling long-session degradation guard; host-owned and OFF by default.

    A short healthy sample does not establish long-session stability. First
    eight verified completed turns form a frozen baseline. Eight subsequent
    turns and >=5 minutes of elapsed session time establish the comparison.
    Session clock rollback, duplicate IDs, invalid provenance and coverage
    gaps lock the guard faulted until the owner re-arms a new session.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._enabled = False
        self._fault: str | None = None
        self._baseline: list[ReviewedVoiceTurn] = []
        self._recent: deque[ReviewedVoiceTurn] = deque(maxlen=_RECENT)
        self._seen: set[str] = set()
        self._last_sample_ms: float | None = None
        self._last_now_ms: float | None = None
        self._accepted = 0
        self._rejected = 0

    def enable(self, *, owner_approved: bool = False) -> None:
        if owner_approved is not True:
            raise PermissionError("host owner approval required")
        with self._lock:
            if self._enabled:
                raise RuntimeError("disable before starting a new session")
            self._baseline.clear()
            self._recent.clear()
            self._seen.clear()
            self._fault = None
            self._last_sample_ms = None
            self._last_now_ms = None
            self._enabled = True

    def disable(self) -> None:
        with self._lock:
            self._enabled = False
            self._baseline.clear()
            self._recent.clear()
            self._seen.clear()
            self._last_sample_ms = None
            self._last_now_ms = None
            self._fault = None

    def ingest(
        self,
        turn: ReviewedVoiceTurn,
        *,
        now_ms: float,
        host_verified: bool = False,
    ) -> bool:
        now = _number(now_ms, "now_ms", maximum=_MAX_MS)
        if not isinstance(turn, ReviewedVoiceTurn):
            raise TypeError("expected ReviewedVoiceTurn")
        if type(host_verified) is not bool:
            raise ValueError("host_verified requires explicit bool")
        with self._lock:
            if not self._enabled:
                return False
            if self._fault is not None:
                return False
            if (
                not host_verified
                or turn.turn_id in self._seen
                or turn.measured_at_ms > now
                or now - turn.measured_at_ms > _MAX_INGEST_AGE_MS
                or (self._last_now_ms is not None and now < self._last_now_ms)
                or (
                    self._last_sample_ms is not None
                    and (
                        turn.measured_at_ms <= self._last_sample_ms
                        or turn.measured_at_ms - self._last_sample_ms > _MAX_SAMPLE_GAP_MS
                    )
                )
            ):
                self._fault = "untrusted_or_noncontiguous_evidence"
                self._rejected += 1
                return False
            self._last_now_ms = now
            self._last_sample_ms = turn.measured_at_ms
            if len(self._baseline) < _BASELINE:
                self._baseline.append(turn)
            else:
                self._recent.append(turn)
            # Bound replay memory; if the session exceeds the bound, require a
            # new externally re-established baseline, never silently forget IDs.
            if len(self._seen) >= 2048:
                self._fault = "session_receipt_capacity"
                self._rejected += 1
                return False
            self._seen.add(turn.turn_id)
            self._accepted += 1
            return True

    def advise(self, *, now_ms: float) -> VoiceHealthAdvice:
        now = _number(now_ms, "now_ms", maximum=_MAX_MS)
        with self._lock:
            baseline = len(self._baseline)
            recent = len(self._recent)

            def advice(status: str, reason: str, permitted: bool) -> VoiceHealthAdvice:
                return VoiceHealthAdvice(status, reason, permitted, baseline, recent)

            if not self._enabled:
                return advice("disabled", "owner_opt_in_missing", True)
            if self._fault is not None:
                return advice("faulted", self._fault, False)
            if self._last_now_ms is not None and now < self._last_now_ms:
                self._fault = "host_clock_reversed"
                return advice("faulted", self._fault, False)
            self._last_now_ms = now
            if self._last_sample_ms is None or now - self._last_sample_ms > _MAX_AGE_MS:
                return advice("stale", "fresh_voice_review_missing", False)
            if (
                baseline < _BASELINE
                or recent < _RECENT
                or self._recent[-1].measured_at_ms - self._baseline[0].measured_at_ms < _MIN_MATURE_MS
            ):
                return advice("warming", "long_session_evidence_insufficient", False)
            first = self._baseline
            last = list(self._recent)
            baseline_latency = float(median(t.first_audio_latency_ms for t in first))
            recent_latency = float(median(t.first_audio_latency_ms for t in last))
            baseline_voice = float(median(t.voice_consistency for t in first))
            recent_voice = float(median(t.voice_consistency for t in last))
            if any(not t.grounded for t in last):
                return advice("degraded", "unverified_factual_claim", False)
            if any(not t.interruption_respected for t in last):
                return advice("degraded", "interruption_not_respected", False)
            if sum(t.repeated for t in last) >= 2:
                return advice("degraded", "repeated_spoken_turns", False)
            if recent_voice < 0.65 or (baseline_voice - recent_voice >= 0.20 and recent_voice < 0.80):
                return advice("degraded", "voice_consistency_regression", False)
            if recent_latency - baseline_latency >= 250.0 and recent_latency > max(800.0, baseline_latency * 1.5):
                return advice("degraded", "first_audio_latency_regression", False)
            return advice("stable", "sampled_voice_metrics_within_budget", True)

    def metrics(self) -> dict[str, int | bool]:
        """Counts only: no voice/audio/chat/identifiers returned."""
        with self._lock:
            return {
                "enabled": self._enabled,
                "faulted": self._fault is not None,
                "accepted": self._accepted,
                "rejected": self._rejected,
                "baseline": len(self._baseline),
                "recent": len(self._recent),
            }


__all__ = ["ReviewedVoiceTurn", "VoiceHealthAdvice", "LongSessionVoiceHealth"]
