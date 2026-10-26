"""Privacy-minimal, local-monotonic realtime speech-latency evidence for Star.

A bounded measurement window reports *measured* host-side latency, never text,
user IDs or audio. It does not provide timestamps, synchronize different
machines, dynamically select models, or certify streaming performance.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import math


_STAGES = ("perception_done_ms", "first_token_ms", "tts_chunk_ms", "first_audible_ms")
_RESULTS = frozenset({"completed", "cancelled", "failed"})
MAX_TURN_MS = 120_000.0
MAX_CLOCK_MS = 1e13


def _valid(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite local monotonic millisecond value")
    try:
        value = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite local monotonic millisecond value") from exc
    if not math.isfinite(value) or not 0 <= value <= MAX_CLOCK_MS:
        raise ValueError(f"{label} must be a finite local monotonic millisecond value")
    return value


@dataclass(frozen=True)
class LiveTurn:
    """One utterance's host-provided milestones, same monotonic clock domain.

    Missing stages support direct speech-to-speech engines and partial failures.
    A completed turn requires the first audible output stamp, not just a TTS
    chunk produced but possibly never heard.
    """
    started_ms: float
    first_audible_ms: float | None = None
    perception_done_ms: float | None = None
    first_token_ms: float | None = None
    tts_chunk_ms: float | None = None
    status: str = "completed"

    def __post_init__(self) -> None:
        start = _valid(self.started_ms, "started_ms")
        if not isinstance(self.status, str) or self.status not in _RESULTS:
            raise ValueError("status must be completed, cancelled or failed")
        previous = start
        for label in _STAGES:
            value = getattr(self, label)
            if value is None:
                continue
            at = _valid(value, label)
            if at < previous or at - start > MAX_TURN_MS:
                raise ValueError("milestones must be ordered on one clock within two minutes")
            previous = at
        if self.status == "completed" and self.first_audible_ms is None:
            raise ValueError("completed turns must record when output was audible")


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(p * len(ordered)) - 1)], 2)


class LatencyWindow:
    """Small in-memory development/host observer. No IDs or content are stored."""

    def __init__(self, *, capacity: int = 256, speech_budget_ms: float = 900,
                 minimum_samples: int = 20,
                 minimum_completion_ratio: float = 0.95) -> None:
        if type(capacity) is not int or not 10 <= capacity <= 2048:
            raise ValueError("capacity must be 10..2048")
        if type(minimum_samples) is not int or not 1 <= minimum_samples <= capacity:
            raise ValueError("minimum_samples must be 1..capacity")
        self.speech_budget_ms = _valid(speech_budget_ms, "speech budget")
        if self.speech_budget_ms <= 0:
            raise ValueError("speech budget must be positive")
        if (type(minimum_completion_ratio) not in (float, int)
                or not math.isfinite(float(minimum_completion_ratio))
                or not 0.50 <= minimum_completion_ratio <= 1.0):
            raise ValueError("minimum_completion_ratio must be 0.5..1.0")
        self.minimum_samples = minimum_samples
        self.minimum_completion_ratio = float(minimum_completion_ratio)
        self._turns: deque[LiveTurn] = deque(maxlen=capacity)

    def add(self, turn: LiveTurn) -> None:
        if not isinstance(turn, LiveTurn):
            raise TypeError("expected LiveTurn")
        self._turns.append(turn)

    def clear(self) -> None:
        self._turns.clear()

    def summary(self) -> dict:
        """Return stage p95s, end-to-end p50/p95 and an advisory, not an authorization."""
        turns = tuple(self._turns)
        good = [t for t in turns if t.status == "completed"]
        # completed implies first_audible_ms (checked in LiveTurn); the filter only narrows the type
        latencies = [t.first_audible_ms - t.started_ms for t in good if t.first_audible_ms is not None]
        # A completion-only latency percentile is biased toward surviving turns.
        # Keep it descriptive but do not call an unreliable session "on target".
        completion_ratio = len(good) / len(turns) if turns else 0.0
        within_budget = sum(latency <= self.speech_budget_ms for latency in latencies)
        budget_success_ratio = within_budget / len(turns) if turns else 0.0
        result = {
            "turns": len(turns),
            "completed": len(good),
            "cancelled": sum(t.status == "cancelled" for t in turns),
            "failed": sum(t.status == "failed" for t in turns),
            "first_audible_p50_ms": _percentile(latencies, 0.5),
            "first_audible_p95_ms": _percentile(latencies, 0.95),
            "first_audible_over_budget": sum(t > self.speech_budget_ms for t in latencies),
            "speech_budget_ms": self.speech_budget_ms,
            "completion_ratio": round(completion_ratio, 4),
            "minimum_completion_ratio": self.minimum_completion_ratio,
            "first_audible_budget_success_ratio": round(budget_success_ratio, 4),
        }
        stage_pairs = {
            "perception": ("started_ms", "perception_done_ms"),
            "language": ("perception_done_ms", "first_token_ms"),
            "voice_generation": ("first_token_ms", "tts_chunk_ms"),
            "playback_buffer": ("tts_chunk_ms", "first_audible_ms"),
        }
        stage_p95 = {}
        stage_counts = {}
        for stage, (start, end) in stage_pairs.items():
            samples = [getattr(t, end) - getattr(t, start) for t in good
                       if getattr(t, start) is not None and getattr(t, end) is not None]
            stage_counts[stage] = len(samples)
            stage_p95[stage] = _percentile(samples, 0.95)
        result["stage_p95_ms"] = stage_p95
        result["stage_samples"] = stage_counts
        if len(good) < self.minimum_samples:
            result["assessment"] = "insufficient_completed_samples"
        elif completion_ratio < self.minimum_completion_ratio:
            # Cancelled turns may be intentional owner barge-ins; this is not
            # a failure diagnosis. It only blocks an unsupported speed claim.
            result["assessment"] = "incomplete_audible_coverage"
        elif result["first_audible_p95_ms"] > self.speech_budget_ms:
            result["assessment"] = "first_audible_latency_above_target"
        else:
            result["assessment"] = "first_audible_latency_within_target"
        # A stage may be absent for a full-duplex engine; never call it the bottleneck.
        stage_candidates = [(name, p95) for name, p95 in stage_p95.items()
                            if p95 is not None and stage_counts[name] >= self.minimum_samples]
        result["largest_measured_stage_p95"] = (
            max(stage_candidates, key=lambda item: item[1])[0] if stage_candidates else None
        )
        result["basis"] = ("Host-provided local monotonic samples. Latency percentiles are "
                           "conditional on completed audible turns; reliability ratios "
                           "include failed and cancelled attempts. Intentional barge-ins "
                           "can lower coverage without indicating a bug. Not independent "
                           "measurement, cross-device clock sync or proof of humanlike speech.")
        return result
