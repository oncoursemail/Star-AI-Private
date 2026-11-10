"""Semantic end-of-turn gating layered on STAR's trusted VAD/owner gate.

A host adapter can translate a local semantic turn detector (for example,
LiveKit's Turn Detector) into SemanticTurnPrediction. This module has no
LiveKit dependency and never receives audio or transcripts.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import math
import re
from threading import RLock

from .stream_turntaking import TurnAdvice, TurnTakingGate

_TURN_ID = re.compile(r"[a-f0-9]{20}\Z")
_LANGUAGE = re.compile(r"(?:[a-z]{2,3}|[a-z]{2,3}-[A-Z]{2})\Z")
_MODELS = frozenset({
    "livekit-turn-detector-v1",
    "livekit-turn-detector-v1-mini",
    "custom",
})
MAX_PREDICTION_AGE_MS = 500.0
MAX_ENDPOINTING_MS = 2500.0


def _finite(value: object, label: str, *, maximum: float = 1e13) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= maximum:
        raise ValueError(f"{label} is outside its supported range")
    return number


@dataclass(frozen=True)
class SemanticTurnPrediction:
    """Content-free host receipt for one semantic end-of-turn model decision."""

    turn_id: str
    sequence: int
    audio_end_ms: float
    observed_at_ms: float
    is_complete: bool
    model: str
    language: str = "und"
    confidence: float | None = None
    latency_ms: float | None = None

    def __post_init__(self) -> None:
        if type(self.turn_id) is not str or _TURN_ID.fullmatch(self.turn_id) is None:
            raise ValueError("turn_id must be a 20-character lowercase hex identifier")
        if type(self.sequence) is not int or not 1 <= self.sequence <= 1_000_000_000:
            raise ValueError("sequence must be a positive bounded integer")
        if type(self.is_complete) is not bool:
            raise ValueError("is_complete must be boolean")
        if type(self.model) is not str or self.model not in _MODELS:
            raise ValueError("model must be a supported semantic turn detector")
        if type(self.language) is not str or _LANGUAGE.fullmatch(self.language) is None:
            raise ValueError("language must be a short BCP-47 language tag or und")
        audio_end = _finite(self.audio_end_ms, "audio_end_ms")
        observed = _finite(self.observed_at_ms, "observed_at_ms")
        if observed < audio_end - 25.0:
            raise ValueError("semantic prediction cannot precede its audio endpoint")
        if observed - audio_end > 5000.0:
            raise ValueError("semantic prediction endpoint delay is outside the supported range")
        if self.confidence is not None:
            _finite(self.confidence, "confidence", maximum=1.0)
        if self.latency_ms is not None:
            _finite(self.latency_ms, "latency_ms", maximum=5000.0)


class SemanticTurnGate:
    """Require semantic turn completion after the existing trusted VAD gate says speak.

    Owner barge-in and VAD/guest holds always take precedence. A semantic
    prediction can only delay or permit a response; it cannot authorize an
    owner identity, override VAD, or interrupt another speaker.
    """

    def __init__(
        self,
        vad_gate: TurnTakingGate,
        *,
        max_prediction_age_ms: float = MAX_PREDICTION_AGE_MS,
        max_endpointing_ms: float = MAX_ENDPOINTING_MS,
        minimum_confidence: float = 0.5,
        max_turn_history: int = 32,
    ) -> None:
        if not isinstance(vad_gate, TurnTakingGate):
            raise TypeError("vad_gate must be a trusted TurnTakingGate")
        self._max_prediction_age_ms = _finite(
            max_prediction_age_ms, "max_prediction_age_ms", maximum=2500.0
        )
        self._max_endpointing_ms = _finite(
            max_endpointing_ms, "max_endpointing_ms", maximum=5000.0
        )
        self._minimum_confidence = _finite(
            minimum_confidence, "minimum_confidence", maximum=1.0
        )
        if self._max_prediction_age_ms < 50.0 or self._max_endpointing_ms < 250.0:
            raise ValueError("semantic timing budgets are too small")
        if type(max_turn_history) is not int or not 1 <= max_turn_history <= 256:
            raise ValueError("max_turn_history must be 1..256")
        self._vad_gate = vad_gate
        self._max_turn_history = max_turn_history
        self._last_sequences: OrderedDict[str, int] = OrderedDict()
        self._lock = RLock()
        self._counts = {
            "predictions_seen": 0,
            "predictions_rejected": 0,
            "semantic_holds": 0,
            "semantic_completions": 0,
            "owner_yields": 0,
            "vad_holds": 0,
            "stale_predictions": 0,
            "turn_mismatches": 0,
            "replays": 0,
            "continue_predictions": 0,
            "low_confidence": 0,
            "timeout_fallbacks": 0,
        }

    def _hold(self, reason: str, counter: str | None = None) -> TurnAdvice:
        with self._lock:
            self._counts["semantic_holds"] += 1
            if counter is not None:
                self._counts[counter] += 1
        return TurnAdvice("hold", False, reason)

    def _fallback_or_hold(
        self, *, now_ms: float, audio_end_ms: float | None,
        reason: str, counter: str | None = None,
    ) -> TurnAdvice:
        if (audio_end_ms is not None and now_ms >= audio_end_ms
                and now_ms - audio_end_ms >= self._max_endpointing_ms):
            with self._lock:
                self._counts["timeout_fallbacks"] += 1
                self._counts["semantic_completions"] += 1
            return TurnAdvice("speak", False, "semantic_timeout_fallback")
        return self._hold(reason, counter)

    def advise(
        self,
        *,
        now_ms: float,
        star_speaking: bool,
        expected_turn_id: str,
        prediction: SemanticTurnPrediction | None,
        expected_audio_end_ms: float | None = None,
    ) -> TurnAdvice:
        """Combine VAD/owner arbitration with one fresh semantic prediction."""
        base = self._vad_gate.advise(now_ms=now_ms, star_speaking=star_speaking)
        if base.action == "yield_owner":
            with self._lock:
                self._counts["owner_yields"] += 1
            return base
        if base.action != "speak":
            with self._lock:
                self._counts["vad_holds"] += 1
            return base
        now = _finite(now_ms, "now_ms")
        if type(expected_turn_id) is not str or _TURN_ID.fullmatch(expected_turn_id) is None:
            raise ValueError("expected_turn_id must be a 20-character lowercase hex identifier")
        if expected_audio_end_ms is not None:
            audio_end = _finite(expected_audio_end_ms, "expected_audio_end_ms")
        elif (isinstance(prediction, SemanticTurnPrediction)
              and prediction.turn_id == expected_turn_id):
            audio_end = prediction.audio_end_ms
        else:
            audio_end = None
        if prediction is not None and not isinstance(prediction, SemanticTurnPrediction):
            raise TypeError("prediction must be a validated SemanticTurnPrediction")
        if prediction is None:
            with self._lock:
                self._counts["predictions_rejected"] += 1
            return self._fallback_or_hold(
                now_ms=now, audio_end_ms=audio_end,
                reason="semantic_prediction_missing",
            )
        with self._lock:
            self._counts["predictions_seen"] += 1
        if prediction.turn_id != expected_turn_id:
            with self._lock:
                self._counts["predictions_rejected"] += 1
            return self._fallback_or_hold(
                now_ms=now, audio_end_ms=audio_end,
                reason="semantic_turn_mismatch", counter="turn_mismatches",
            )
        if (prediction.observed_at_ms > now + 25.0
                or now - prediction.observed_at_ms > self._max_prediction_age_ms
                or now - prediction.audio_end_ms > self._max_endpointing_ms
                or prediction.observed_at_ms - prediction.audio_end_ms > self._max_endpointing_ms):
            with self._lock:
                self._counts["predictions_rejected"] += 1
            return self._fallback_or_hold(
                now_ms=now, audio_end_ms=audio_end,
                reason="semantic_prediction_stale", counter="stale_predictions",
            )
        with self._lock:
            previous = self._last_sequences.get(prediction.turn_id, 0)
            if prediction.sequence <= previous:
                self._counts["predictions_rejected"] += 1
                self._counts["replays"] += 1
                if (audio_end is not None and now >= audio_end
                        and now - audio_end >= self._max_endpointing_ms):
                    self._counts["timeout_fallbacks"] += 1
                    self._counts["semantic_completions"] += 1
                    return TurnAdvice("speak", False, "semantic_timeout_fallback")
                self._counts["semantic_holds"] += 1
                return TurnAdvice("hold", False, "semantic_prediction_replay")
            self._last_sequences[prediction.turn_id] = prediction.sequence
            self._last_sequences.move_to_end(prediction.turn_id)
            while len(self._last_sequences) > self._max_turn_history:
                self._last_sequences.popitem(last=False)
        if not prediction.is_complete:
            return self._fallback_or_hold(
                now_ms=now, audio_end_ms=audio_end,
                reason="semantic_turn_continue", counter="continue_predictions",
            )
        if (prediction.confidence is not None
                and prediction.confidence < self._minimum_confidence):
            return self._fallback_or_hold(
                now_ms=now, audio_end_ms=audio_end,
                reason="semantic_confidence_low", counter="low_confidence",
            )
        with self._lock:
            self._counts["semantic_completions"] += 1
        return TurnAdvice("speak", False, "semantic_turn_complete")

    def metrics(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)


__all__ = ["SemanticTurnPrediction", "SemanticTurnGate"]
