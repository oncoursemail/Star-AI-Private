"""Read-only timing analysis for bounded STAR AgentTrace snapshots.

This profiler deliberately distinguishes inclusive span duration from the
portion of a span not covered by its direct children. It reports wall-clock
coverage and sibling overlap; it does not invent a causal critical path from
parent/child nesting alone. No attributes or source payloads are copied.
"""
from __future__ import annotations

from collections import defaultdict
import math
import re
from typing import Any

_TRACE_ID = re.compile(r"[0-9a-f]{32}\Z")
_SPAN_ID = re.compile(r"[0-9a-f]{16}\Z")
_NAME = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_COMPONENTS = frozenset({
    "runtime", "retrieval", "model", "tool", "voice", "tts", "audio",
    "avatar", "game", "memory", "evaluation", "obs", "scheduler",
    "desktop", "network",
})
_STATUSES = frozenset({"open", "ok", "error", "cancelled", "deferred", "timeout"})
_EVENTS = frozenset({
    "request_received", "task_started", "task_checkpointed", "task_resumed",
    "turn_started", "turn_interrupted", "turn_resumed", "model_started",
    "model_finished", "tool_started", "tool_finished", "audio_queued",
    "audio_playback_started", "audio_playback_finished", "avatar_updated",
    "game_observed", "game_action", "budget_admitted", "budget_deferred",
    "task_finished", "stream_started", "stream_stopped", "obs_sampled",
    "inference_sampled", "hardware_sampled", "stream_director_sampled",
    "speech_proposed", "speech_completed", "game_learning_sampled",
    "task_checkpoint_sampled", "error",
})
_MAX_CLOCK_MS = 1e13
_MAX_SPANS = 4096
_MAX_EVENTS = 16384


def _number(value: object, label: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be a finite nonnegative number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{label} must be a finite nonnegative number") from exc
    if not math.isfinite(result) or not 0 <= result <= _MAX_CLOCK_MS:
        raise ValueError(f"{label} is outside the supported clock range")
    return result


def _union_length(intervals: list[tuple[float, float]]) -> float:
    """Return the wall-clock union of closed intervals."""
    if not intervals:
        return 0.0
    ordered = sorted(intervals)
    start, end = ordered[0]
    total = 0.0
    for next_start, next_end in ordered[1:]:
        if next_start > end:
            total += end - start
            start, end = next_start, next_end
        elif next_end > end:
            end = next_end
    return total + end - start


def _percentile(values: list[float], percentile: float) -> float | None:
    """Nearest-rank percentile, stable for small sample counts."""
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 3)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 3)


def profile_trace(
    snapshot: dict[str, Any],
    *,
    slowest_limit: int = 10,
) -> dict[str, Any]:
    """Summarize one AgentTrace.snapshot() without exporting its attributes.

    Completed spans receive inclusive duration, direct-child coverage,
    child-overlap and exclusive wall time. Open spans are counted but are not
    assigned a fabricated duration. Component inclusive durations are not
    additive because parent/child and concurrent spans can overlap.
    """
    if (type(snapshot) is not dict or type(snapshot.get("schema_version")) is not int
            or snapshot.get("schema_version") != 1):
        raise ValueError("snapshot must be an AgentTrace schema-version-1 dictionary")
    if type(slowest_limit) is not int or not 1 <= slowest_limit <= 50:
        raise ValueError("slowest_limit must be an integer in 1..50")

    trace_id = snapshot.get("trace_id")
    if (type(trace_id) is not str or not _TRACE_ID.fullmatch(trace_id)
            or trace_id == "0" * 32):
        raise ValueError("snapshot has an invalid trace ID")
    trace_flags = snapshot.get("trace_flags")
    if type(trace_flags) is not str or trace_flags not in {"00", "01"}:
        raise ValueError("snapshot has invalid trace flags")

    raw_spans = snapshot.get("spans")
    raw_events = snapshot.get("events")
    if type(raw_spans) is not list or len(raw_spans) > _MAX_SPANS:
        raise ValueError("snapshot spans must be a bounded list")
    if type(raw_events) is not list or len(raw_events) > _MAX_EVENTS:
        raise ValueError("snapshot events must be a bounded list")

    spans: dict[str, dict[str, Any]] = {}
    children: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in raw_spans:
        if type(raw) is not dict:
            raise ValueError("each span must be a dictionary")
        span_id = raw.get("span_id")
        parent_id = raw.get("parent_span_id")
        name = raw.get("name")
        component = raw.get("component")
        status = raw.get("status")
        if type(span_id) is not str or not _SPAN_ID.fullmatch(span_id):
            raise ValueError("span has an invalid span ID")
        if span_id == "0" * 16:
            raise ValueError("span has an invalid all-zero span ID")
        if span_id in spans:
            raise ValueError("snapshot contains duplicate span IDs")
        if parent_id is not None and (
            type(parent_id) is not str or not _SPAN_ID.fullmatch(parent_id)
        ):
            raise ValueError("span has an invalid parent span ID")
        if type(name) is not str or not _NAME.fullmatch(name):
            raise ValueError("span has an invalid operation name")
        if type(component) is not str or component not in _COMPONENTS:
            raise ValueError("span has an unknown component")
        if type(status) is not str or status not in _STATUSES:
            raise ValueError("span has an unknown status")
        if type(raw.get("attributes")) is not dict:
            raise ValueError("span attributes must be a dictionary")

        started = _number(raw.get("started_ms"), "span start")
        ended_raw = raw.get("ended_ms")
        ended = None if ended_raw is None else _number(ended_raw, "span end")
        if ended is not None and ended < started:
            raise ValueError("span ends before it starts")
        if (ended is None) != (status == "open"):
            raise ValueError("open span status and end timestamp disagree")

        spans[span_id] = {
            "span_id": span_id,
            "parent_span_id": parent_id,
            "name": name,
            "component": component,
            "status": status,
            "started_ms": started,
            "ended_ms": ended,
        }

    for span in spans.values():
        parent_id = span["parent_span_id"]
        if parent_id is None:
            continue
        parent = spans.get(parent_id)
        if parent is None:
            raise ValueError("span references a missing parent")
        if span["started_ms"] < parent["started_ms"]:
            raise ValueError("child span starts before its parent")
        if parent["ended_ms"] is not None:
            if span["ended_ms"] is None or span["ended_ms"] > parent["ended_ms"]:
                raise ValueError("child span outlives its finished parent")
        children[parent_id].append(span)

    # Parent pointers must form a forest, not a cycle.
    for span_id in spans:
        visited: set[str] = set()
        current: str | None = span_id
        while current is not None:
            if current in visited:
                raise ValueError("span parent relationships contain a cycle")
            visited.add(current)
            current_span = spans.get(current)
            current = None if current_span is None else current_span["parent_span_id"]

    event_counts: dict[str, int] = {}
    event_sequences: set[int] = set()
    for raw in raw_events:
        if type(raw) is not dict:
            raise ValueError("each event must be a dictionary")
        name = raw.get("name")
        sequence = raw.get("sequence")
        if type(name) is not str or name not in _EVENTS:
            raise ValueError("event name is not recognized")
        if type(sequence) is not int or not 1 <= sequence <= _MAX_EVENTS:
            raise ValueError("event sequence is invalid")
        if sequence in event_sequences:
            raise ValueError("event sequences must be unique")
        event_sequences.add(sequence)
        at_ms = _number(raw.get("at_ms"), "event timestamp")
        span_id = raw.get("span_id")
        if span_id is not None:
            if type(span_id) is not str or span_id not in spans:
                raise ValueError("event references a missing span")
            span = spans[span_id]
            if at_ms < span["started_ms"]:
                raise ValueError("event precedes its span")
            if span["ended_ms"] is not None and at_ms > span["ended_ms"]:
                raise ValueError("event follows its finished span")
        event_counts[name] = event_counts.get(name, 0) + 1

    span_profiles: list[dict[str, Any]] = []
    duration_by_component: dict[str, list[float]] = defaultdict(list)
    exclusive_by_component: dict[str, list[float]] = defaultdict(list)
    root_profiles: list[dict[str, Any]] = []

    for span in spans.values():
        ended = span["ended_ms"]
        duration = None if ended is None else ended - span["started_ms"]
        child_intervals: list[tuple[float, float]] = []
        child_duration_sum = 0.0
        for child in children.get(span["span_id"], []):
            child_end = child["ended_ms"]
            if child_end is not None:
                child_intervals.append((child["started_ms"], child_end))
                child_duration_sum += child_end - child["started_ms"]
        child_coverage = None
        child_overlap = None
        exclusive = None
        if duration is not None:
            child_coverage = _union_length(child_intervals)
            child_overlap = max(0.0, child_duration_sum - child_coverage)
            exclusive = max(0.0, duration - child_coverage)
            duration_by_component[span["component"]].append(duration)
            exclusive_by_component[span["component"]].append(exclusive)

        profile = {
            "span_id": span["span_id"],
            "parent_span_id": span["parent_span_id"],
            "name": span["name"],
            "component": span["component"],
            "status": span["status"],
            "duration_ms": _round(duration),
            "child_coverage_ms": _round(child_coverage),
            "child_overlap_ms": _round(child_overlap),
            "exclusive_ms": _round(exclusive),
        }
        span_profiles.append(profile)

        if span["parent_span_id"] is None:
            root_profiles.append({
                "span_id": span["span_id"],
                "name": span["name"],
                "component": span["component"],
                "duration_ms": _round(duration),
                "child_coverage_ms": _round(child_coverage),
                "unattributed_ms": _round(exclusive),
                "parallel_child_overlap_ms": _round(child_overlap),
                "status": span["status"],
            })

    roots = [span for span in spans.values() if span["parent_span_id"] is None]
    if roots and all(span["ended_ms"] is not None for span in roots):
        trace_start = min(span["started_ms"] for span in roots)
        trace_end = max(span["ended_ms"] for span in roots)
        trace_wall_ms: float | None = trace_end - trace_start
    else:
        trace_wall_ms = None

    component_profiles = []
    for component in sorted(duration_by_component):
        durations = duration_by_component[component]
        exclusive_values = exclusive_by_component[component]
        component_profiles.append({
            "component": component,
            "completed_spans": len(durations),
            "inclusive_p50_ms": _percentile(durations, 0.50),
            "inclusive_p95_ms": _percentile(durations, 0.95),
            "inclusive_max_ms": _round(max(durations)),
            "exclusive_p50_ms": _percentile(exclusive_values, 0.50),
            "exclusive_p95_ms": _percentile(exclusive_values, 0.95),
            "exclusive_max_ms": _round(max(exclusive_values)),
        })

    completed_profiles = [item for item in span_profiles if item["duration_ms"] is not None]
    slowest = sorted(
        completed_profiles,
        key=lambda item: (
            -float(item["duration_ms"]),
            str(item["component"]),
            str(item["name"]),
            str(item["span_id"]),
        ),
    )[:slowest_limit]

    status_counts: dict[str, int] = {}
    for span in spans.values():
        status_counts[span["status"]] = status_counts.get(span["status"], 0) + 1

    return {
        "schema_version": 1,
        "trace_id": trace_id,
        "trace_wall_ms": _round(trace_wall_ms),
        "counts": {
            "spans": len(spans),
            "completed_spans": sum(span["ended_ms"] is not None for span in spans.values()),
            "open_spans": sum(span["ended_ms"] is None for span in spans.values()),
            "failed_spans": sum(span["status"] in {"error", "timeout"} for span in spans.values()),
            "roots": len(roots),
        },
        "status_counts": dict(sorted(status_counts.items())),
        "roots": sorted(root_profiles, key=lambda item: item["span_id"]),
        "components": component_profiles,
        "slowest_spans": slowest,
        "event_counts": dict(sorted(event_counts.items())),
    }


__all__ = ["profile_trace"]
