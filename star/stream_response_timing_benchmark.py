"""Offline evaluation of whether STAR responds at the right time—or stays silent.

Inputs are structured event windows and host-observed output receipts. No raw
chat, transcripts, audio, video, viewer identity, or prompt text is accepted.
This analyzer scores timing and policy outcomes; it does not authorize speech,
avatar output, OBS control, game input, or broadcasting.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import json
import math
from pathlib import Path
import re
from statistics import median
from typing import Callable, Iterable, Sequence, cast

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}\Z")
_KINDS = frozenset({
    "owner_interrupt", "game_danger", "game_success", "game_observation",
    "viewer_question", "viewer_comment", "ambient",
})
_ACTIONS = frozenset({"speak", "backchannel", "silence"})
_EMITTED = _ACTIONS | {"none"}
_MAX_CLOCK_MS = 1e12
_MAX_WINDOW_MS = 60_000
_MAX_RECORDS = 5_000


def _identifier(value: object, field: str) -> str:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError(f"{field} must be a bounded opaque identifier")
    return value


def _clock_ms(value: object, field: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{field} must be a finite host-clock millisecond value")
    try:
        result = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be finite") from exc
    if not math.isfinite(result) or not 0 <= result <= _MAX_CLOCK_MS:
        raise ValueError(f"{field} must be finite and nonnegative")
    return result


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    if fraction == 0.5:
        return round(median(values), 2)
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return round(ordered[index], 2)


@dataclass(frozen=True)
class StreamResponseKindReport:
    events: int
    timely_grounded_responses: int
    correct_silence: int
    missed_responses: int
    false_positive_responses: int
    early_outputs: int
    late_outputs: int
    decision_mismatches: int
    emitted_mode_mismatches: int
    duplicate_outputs: int
    ungrounded_outputs: int
    unverified_outputs: int
    early_decisions: int
    response_precision: float | None
    response_recall: float | None
    silence_precision: float | None
    silence_recall: float | None
    decision_latency_p50_ms: float | None
    decision_latency_p95_ms: float | None
    first_audio_latency_p50_ms: float | None
    first_audio_latency_p95_ms: float | None
    first_avatar_latency_p50_ms: float | None
    first_avatar_latency_p95_ms: float | None


@dataclass
class _KindAccumulator:
    events: int = 0
    timely: int = 0
    correct_silence: int = 0
    missed: int = 0
    false_positive: int = 0
    early: int = 0
    late: int = 0
    decision_mismatch: int = 0
    mode_mismatch: int = 0
    duplicates: int = 0
    ungrounded: int = 0
    unverified: int = 0
    early_decisions: int = 0
    emitted_events: int = 0
    expected_responses: int = 0
    expected_silences: int = 0
    silence_decisions: int = 0
    decision_latencies: list[float] = field(default_factory=list)
    audio_latencies: list[float] = field(default_factory=list)
    avatar_latencies: list[float] = field(default_factory=list)

    def finish(self) -> StreamResponseKindReport:
        response_precision = self.timely / self.emitted_events if self.emitted_events else None
        response_recall = self.timely / self.expected_responses if self.expected_responses else None
        silence_precision = self.correct_silence / self.silence_decisions if self.silence_decisions else None
        silence_recall = self.correct_silence / self.expected_silences if self.expected_silences else None
        return StreamResponseKindReport(
            events=self.events,
            timely_grounded_responses=self.timely,
            correct_silence=self.correct_silence,
            missed_responses=self.missed,
            false_positive_responses=self.false_positive,
            early_outputs=self.early,
            late_outputs=self.late,
            decision_mismatches=self.decision_mismatch,
            emitted_mode_mismatches=self.mode_mismatch,
            duplicate_outputs=self.duplicates,
            ungrounded_outputs=self.ungrounded,
            unverified_outputs=self.unverified,
            early_decisions=self.early_decisions,
            response_precision=round(response_precision, 4) if response_precision is not None else None,
            response_recall=round(response_recall, 4) if response_recall is not None else None,
            silence_precision=round(silence_precision, 4) if silence_precision is not None else None,
            silence_recall=round(silence_recall, 4) if silence_recall is not None else None,
            decision_latency_p50_ms=_percentile(self.decision_latencies, 0.50),
            decision_latency_p95_ms=_percentile(self.decision_latencies, 0.95),
            first_audio_latency_p50_ms=_percentile(self.audio_latencies, 0.50),
            first_audio_latency_p95_ms=_percentile(self.audio_latencies, 0.95),
            first_avatar_latency_p50_ms=_percentile(self.avatar_latencies, 0.50),
            first_avatar_latency_p95_ms=_percentile(self.avatar_latencies, 0.95),
        )


@dataclass(frozen=True)
class StreamResponseWindow:
    """Independently labeled window for one salient event; contains no content."""

    session_id: str
    event_id: str
    event_kind: str
    observed_at_ms: float
    opens_at_ms: float
    deadline_at_ms: float
    expected_action: str
    independently_scored: bool

    def __post_init__(self) -> None:
        _identifier(self.session_id, "session_id")
        _identifier(self.event_id, "event_id")
        if type(self.event_kind) is not str or self.event_kind not in _KINDS:
            raise ValueError("unsupported event kind")
        if type(self.expected_action) is not str or self.expected_action not in _ACTIONS:
            raise ValueError("expected_action must be speak, backchannel, or silence")
        if type(self.independently_scored) is not bool:
            raise ValueError("independently_scored must be an explicit boolean")
        observed = _clock_ms(self.observed_at_ms, "observed_at_ms")
        opens = _clock_ms(self.opens_at_ms, "opens_at_ms")
        deadline = _clock_ms(self.deadline_at_ms, "deadline_at_ms")
        if not observed <= opens <= deadline:
            raise ValueError("response window clock order is invalid")
        if deadline - observed > _MAX_WINDOW_MS:
            raise ValueError("response window cannot exceed 60 seconds")

    @classmethod
    def from_dict(cls, item: object) -> StreamResponseWindow:
        expected = {
            "session_id", "event_id", "event_kind", "observed_at_ms",
            "opens_at_ms", "deadline_at_ms", "expected_action",
            "independently_scored",
        }
        if type(item) is not dict or set(item) != expected:
            raise ValueError("response-window record has missing or unsupported fields")
        values = cast(dict[str, object], item)
        return cls(
            session_id=cast(str, values["session_id"]),
            event_id=cast(str, values["event_id"]),
            event_kind=cast(str, values["event_kind"]),
            observed_at_ms=cast(float, values["observed_at_ms"]),
            opens_at_ms=cast(float, values["opens_at_ms"]),
            deadline_at_ms=cast(float, values["deadline_at_ms"]),
            expected_action=cast(str, values["expected_action"]),
            independently_scored=cast(bool, values["independently_scored"]),
        )


@dataclass(frozen=True)
class StreamResponseObservation:
    """Host-observed decision and first audio/avatar timestamps for one event."""

    session_id: str
    event_id: str
    decision: str
    decision_at_ms: float
    emitted_mode: str
    output_count: int = 0
    first_audio_at_ms: float | None = None
    first_avatar_at_ms: float | None = None
    grounded: bool | None = None

    def __post_init__(self) -> None:
        _identifier(self.session_id, "session_id")
        _identifier(self.event_id, "event_id")
        if type(self.decision) is not str or self.decision not in _ACTIONS:
            raise ValueError("decision must be speak, backchannel, or silence")
        if type(self.emitted_mode) is not str or self.emitted_mode not in _EMITTED:
            raise ValueError("emitted_mode must be speak, backchannel, or none")
        _clock_ms(self.decision_at_ms, "decision_at_ms")
        if type(self.output_count) is not int or not 0 <= self.output_count <= 100:
            raise ValueError("output_count must be an integer from 0 to 100")
        if self.first_audio_at_ms is not None:
            _clock_ms(self.first_audio_at_ms, "first_audio_at_ms")
        if self.first_avatar_at_ms is not None:
            _clock_ms(self.first_avatar_at_ms, "first_avatar_at_ms")
        if self.emitted_mode == "none":
            if (self.output_count != 0 or self.first_audio_at_ms is not None
                    or self.first_avatar_at_ms is not None or self.grounded is not None):
                raise ValueError("none output cannot carry output timestamps or grounding")
        elif self.emitted_mode == "speak":
            if self.output_count < 1 or self.first_audio_at_ms is None:
                raise ValueError("spoken output requires a count and first-audio timestamp")
            if self.grounded is not None and type(self.grounded) is not bool:
                raise ValueError("grounded must be bool or absent")
        else:
            if (self.output_count < 1 or self.first_avatar_at_ms is None
                    or self.first_audio_at_ms is not None):
                raise ValueError("backchannel output requires avatar timing and no audio")
            if self.grounded is not None and type(self.grounded) is not bool:
                raise ValueError("grounded must be bool or absent")

    @classmethod
    def from_dict(cls, item: object) -> StreamResponseObservation:
        expected = {
            "session_id", "event_id", "decision", "decision_at_ms",
            "emitted_mode", "output_count", "first_audio_at_ms",
            "first_avatar_at_ms", "grounded",
        }
        if type(item) is not dict or set(item) != expected:
            raise ValueError("response-observation record has missing or unsupported fields")
        values = cast(dict[str, object], item)
        return cls(
            session_id=cast(str, values["session_id"]),
            event_id=cast(str, values["event_id"]),
            decision=cast(str, values["decision"]),
            decision_at_ms=cast(float, values["decision_at_ms"]),
            emitted_mode=cast(str, values["emitted_mode"]),
            output_count=cast(int, values["output_count"]),
            first_audio_at_ms=cast(float | None, values["first_audio_at_ms"]),
            first_avatar_at_ms=cast(float | None, values["first_avatar_at_ms"]),
            grounded=cast(bool | None, values["grounded"]),
        )

    @property
    def first_relevant_output_ms(self) -> float | None:
        if self.emitted_mode == "speak":
            return self.first_audio_at_ms
        if self.emitted_mode == "backchannel":
            return self.first_avatar_at_ms
        return None


@dataclass(frozen=True)
class StreamResponseTimingReport:
    verdict: str
    events: int
    by_event_kind: dict[str, StreamResponseKindReport]
    scored_events: int
    unscored_events: int
    missing_observations: int
    timely_grounded_responses: int
    correct_silence: int
    missed_responses: int
    false_positive_responses: int
    early_outputs: int
    late_outputs: int
    decision_mismatches: int
    emitted_mode_mismatches: int
    duplicate_outputs: int
    ungrounded_outputs: int
    unverified_outputs: int
    response_precision: float | None
    response_recall: float | None
    silence_precision: float | None
    silence_recall: float | None
    early_decisions: int
    decision_latency_p50_ms: float | None
    decision_latency_p95_ms: float | None
    first_audio_latency_p50_ms: float | None
    first_audio_latency_p95_ms: float | None
    first_avatar_latency_p50_ms: float | None
    first_avatar_latency_p95_ms: float | None
    authorized_to_act: bool = False
    note: str = (
        "Offline timing evaluation only. Host timestamps and labels are not "
        "authenticated here; no speech, avatar output, game input, OBS control, "
        "broadcast, or automatic promotion is authorized."
    )


def assess_stream_response_timing(
    windows: Iterable[StreamResponseWindow],
    observations: Iterable[StreamResponseObservation],
    *,
    minimum_events: int = 20,
) -> StreamResponseTimingReport:
    """Score speak/backchannel/silence decisions against independently labeled windows.

    A response is successful only when the correct modality is host-observed
    inside its event window and independently judged grounded. A
    generated sentence, queued TTS item, or model self-report is not output proof.
    """
    if type(minimum_events) is not int or not 1 <= minimum_events <= _MAX_RECORDS:
        raise ValueError("minimum_events must be 1..5000")

    window_map: dict[tuple[str, str], StreamResponseWindow] = {}
    for index, window in enumerate(windows, start=1):
        if index > _MAX_RECORDS:
            raise ValueError("at most 5000 response windows")
        if not isinstance(window, StreamResponseWindow):
            raise TypeError("expected StreamResponseWindow records")
        key = (window.session_id, window.event_id)
        if key in window_map:
            raise ValueError("duplicate response window identity")
        window_map[key] = window

    observation_map: dict[tuple[str, str], StreamResponseObservation] = {}
    for index, observation in enumerate(observations, start=1):
        if index > _MAX_RECORDS:
            raise ValueError("at most 5000 response observations")
        if not isinstance(observation, StreamResponseObservation):
            raise TypeError("expected StreamResponseObservation records")
        key = (observation.session_id, observation.event_id)
        if key in observation_map:
            raise ValueError("duplicate response observation identity")
        if key not in window_map:
            raise ValueError("observation has no matching response window")
        observation_map[key] = observation

    scored = [window for window in window_map.values() if window.independently_scored]
    unscored = len(window_map) - len(scored)
    missing = sum(
        (window.session_id, window.event_id) not in observation_map
        for window in scored
    )
    timely = correct_silence = missed = false_positive = 0
    early = late = decision_mismatch = mode_mismatch = 0
    duplicates = ungrounded = unverified = 0
    decision_latencies: list[float] = []
    early_decisions = 0
    audio_latencies: list[float] = []
    avatar_latencies: list[float] = []
    emitted_events = expected_responses = expected_silences = 0
    silence_decisions = 0
    kind_accumulators: dict[str, _KindAccumulator] = {}

    for window in scored:
        kind_stats = kind_accumulators.setdefault(window.event_kind, _KindAccumulator())
        kind_stats.events += 1
        key = (window.session_id, window.event_id)
        observation = observation_map.get(key)
        if window.expected_action == "silence":
            expected_silences += 1
            kind_stats.expected_silences += 1
        else:
            expected_responses += 1
            kind_stats.expected_responses += 1
        if observation is None:
            if window.expected_action != "silence":
                missed += 1
                kind_stats.missed += 1
            continue

        decision_latency = observation.decision_at_ms - window.observed_at_ms
        decision_latencies.append(decision_latency)
        kind_stats.decision_latencies.append(decision_latency)
        if decision_latency < 0:
            early_decisions += 1
            kind_stats.early_decisions += 1
        if observation.decision != window.expected_action:
            decision_mismatch += 1
            kind_stats.decision_mismatch += 1

        output_at = observation.first_relevant_output_ms
        has_output = observation.emitted_mode != "none"
        if has_output:
            emitted_events += 1
            kind_stats.emitted_events += 1
            duplicates += max(0, observation.output_count - 1)
            kind_stats.duplicates += max(0, observation.output_count - 1)
            if observation.grounded is False:
                ungrounded += 1
                kind_stats.ungrounded += 1
            elif observation.grounded is None:
                unverified += 1
                kind_stats.unverified += 1
            if observation.emitted_mode != window.expected_action:
                mode_mismatch += 1
                kind_stats.mode_mismatch += 1
            if output_at is not None:
                latency = output_at - window.observed_at_ms
                if observation.emitted_mode == "speak":
                    audio_latencies.append(latency)
                    kind_stats.audio_latencies.append(latency)
                else:
                    avatar_latencies.append(latency)
                    kind_stats.avatar_latencies.append(latency)
                if output_at < window.opens_at_ms:
                    early += 1
                    kind_stats.early += 1
                elif output_at > window.deadline_at_ms:
                    late += 1
                    kind_stats.late += 1
        elif observation.decision == "silence":
            silence_decisions += 1
            kind_stats.silence_decisions += 1

        if window.expected_action == "silence":
            if observation.decision == "silence" and not has_output:
                correct_silence += 1
                kind_stats.correct_silence += 1
            elif has_output:
                false_positive += 1
                kind_stats.false_positive += 1
            continue

        if (observation.decision == window.expected_action
                and observation.emitted_mode == window.expected_action
                and output_at is not None
                and window.opens_at_ms <= output_at <= window.deadline_at_ms
                and observation.grounded is True):
            timely += 1
            kind_stats.timely += 1
        else:
            missed += 1
            kind_stats.missed += 1

    response_precision = timely / emitted_events if emitted_events else None
    response_recall = timely / expected_responses if expected_responses else None
    silence_precision = correct_silence / silence_decisions if silence_decisions else None
    silence_recall = correct_silence / expected_silences if expected_silences else None
    verdict = (
        "inconclusive"
        if len(scored) < minimum_events or unscored or missing
        else "measured"
    )
    return StreamResponseTimingReport(
        verdict=verdict,
        events=len(window_map),
        by_event_kind={
            kind: accumulator.finish()
            for kind, accumulator in sorted(kind_accumulators.items())
        },
        scored_events=len(scored),
        unscored_events=unscored,
        missing_observations=missing,
        timely_grounded_responses=timely,
        correct_silence=correct_silence,
        missed_responses=missed,
        false_positive_responses=false_positive,
        early_outputs=early,
        late_outputs=late,
        decision_mismatches=decision_mismatch,
        emitted_mode_mismatches=mode_mismatch,
        duplicate_outputs=duplicates,
        ungrounded_outputs=ungrounded,
        unverified_outputs=unverified,
        early_decisions=early_decisions,
        response_precision=round(response_precision, 4) if response_precision is not None else None,
        response_recall=round(response_recall, 4) if response_recall is not None else None,
        silence_precision=round(silence_precision, 4) if silence_precision is not None else None,
        silence_recall=round(silence_recall, 4) if silence_recall is not None else None,
        decision_latency_p50_ms=_percentile(decision_latencies, 0.50),
        decision_latency_p95_ms=_percentile(decision_latencies, 0.95),
        first_audio_latency_p50_ms=_percentile(audio_latencies, 0.50),
        first_audio_latency_p95_ms=_percentile(audio_latencies, 0.95),
        first_avatar_latency_p50_ms=_percentile(avatar_latencies, 0.50),
        first_avatar_latency_p95_ms=_percentile(avatar_latencies, 0.95),
    )


def _read_jsonl(path: str | Path, factory: Callable[[object], object]) -> list[object]:
    source = Path(path)
    rows: list[object] = []
    with source.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            if len(line) > 8192:
                raise ValueError(f"{source.name}:{line_number}: record too large")
            if len(rows) >= _MAX_RECORDS:
                raise ValueError("at most 5000 records per input file")
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{source.name}:{line_number}: invalid JSON") from exc
            rows.append(factory(item))
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate STAR stream response timing from sanitized JSONL receipts."
    )
    parser.add_argument("windows", help="JSONL of independently labeled event windows")
    parser.add_argument("observations", help="JSONL of host-observed response receipts")
    parser.add_argument("--minimum-events", type=int, default=20)
    args = parser.parse_args(argv)
    windows = _read_jsonl(args.windows, StreamResponseWindow.from_dict)
    observations = _read_jsonl(args.observations, StreamResponseObservation.from_dict)
    report = assess_stream_response_timing(
        cast(Iterable[StreamResponseWindow], windows),
        cast(Iterable[StreamResponseObservation], observations),
        minimum_events=args.minimum_events,
    )
    print(json.dumps(asdict(report), sort_keys=True))
    return 0


__all__ = [
    "StreamResponseWindow", "StreamResponseObservation",
    "StreamResponseKindReport", "StreamResponseTimingReport",
    "assess_stream_response_timing",
]

if __name__ == "__main__":
    raise SystemExit(main())