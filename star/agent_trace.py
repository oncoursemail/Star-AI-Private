"""Bounded, privacy-safe causal tracing primitives for STAR's agent runtime.

This is an exporter-neutral instrumentation contract, not an OpenTelemetry SDK,
network exporter, scheduler, permission broker, or automatic observer. It records
only allowlisted identifiers and numeric outcomes; prompts, chat, transcripts,
screenshots, audio, exception messages, credentials, and arbitrary text are
intentionally rejected. All timestamps are host-supplied monotonic milliseconds.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import re
import secrets
from threading import RLock
from typing import Any

_TRACE_ID = re.compile(r"[0-9a-f]{32}\Z")
_SPAN_ID = re.compile(r"[0-9a-f]{16}\Z")
_OPERATION = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_OPAQUE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,63}\Z")
_MAX_CLOCK_MS = 1e13
_MAX_NUMBER = 1e9

_COMPONENTS = frozenset({
    "runtime", "retrieval", "model", "tool", "voice", "tts", "audio",
    "avatar", "game", "memory", "evaluation", "obs", "scheduler",
    "desktop", "network",
})
_STATUSES = frozenset({"ok", "error", "cancelled", "deferred", "timeout"})
_ERROR_CATEGORIES = frozenset({
    "timeout", "rate_limited", "client_error", "server_error",
    "connection_error", "protocol_error", "model_error", "tool_error",
    "cancelled", "unknown",
})
_OUTCOMES = frozenset({"success", "failure", "partial", "cancelled", "deferred", "unknown"})
_DEVICES = frozenset({"cpu", "gpu", "auto", "remote"})
_EVENTS = frozenset({
    "request_received", "task_started", "task_checkpointed", "task_resumed",
    "turn_started", "turn_interrupted", "turn_resumed", "model_started",
    "model_finished", "tool_started", "tool_finished", "audio_queued",
    "audio_playback_started", "audio_playback_finished", "avatar_updated",
    "game_observed", "game_action", "budget_admitted", "budget_deferred",
    "task_finished", "stream_started", "stream_stopped", "obs_sampled", "error",
})

# Only low-cardinality enums, opaque IDs, booleans, and bounded numeric facts
# may cross this boundary. Free-form values are deliberately unsupported.
_ATTRIBUTE_RULES: dict[str, str] = {
    "model_id": "id", "route_id": "id", "tool_id": "id", "game_id": "id",
    "game_version": "id", "session_id": "id", "job_id": "id",
    "provider_id": "id", "studio_id": "id", "skill_id": "id",
    "outcome": "outcome", "error_category": "error", "device": "device",
    "input_tokens": "integer", "output_tokens": "integer",
    "retry_count": "integer", "attempt": "integer", "http_status_code": "http",
    "queue_wait_ms": "number", "ttft_ms": "number", "ttst_ms": "number",
    "first_audio_ms": "number", "audio_playback_ms": "number",
    "frame_time_ms": "number", "gpu_memory_mib": "number",
    "cpu_busy_percent": "percent", "obs_render_lag_ms": "number",
    "kv_cache_usage_ratio": "ratio",
    "cache_hit": "boolean", "interrupted": "boolean", "cancelled": "boolean",
    "game_active": "boolean", "stream_live": "boolean",
}


def _clock(value: object, name: str) -> float:
    if type(value) is int:
        try:
            number = float(value)
        except OverflowError as exc:
            raise ValueError(f"{name} must be finite") from exc
    elif type(value) is float:
        number = value
    else:
        raise ValueError(f"{name} must be numeric monotonic milliseconds")
    if not math.isfinite(number) or not 0 <= number <= _MAX_CLOCK_MS:
        raise ValueError(f"{name} must be finite and within the supported clock range")
    return number


def _attributes(value: dict[str, Any] | None) -> dict[str, str | int | float | bool]:
    if value is None:
        return {}
    if type(value) is not dict or len(value) > 16:
        raise ValueError("attributes must be a dictionary with at most 16 entries")
    clean: dict[str, str | int | float | bool] = {}
    for key, item in value.items():
        if type(key) is not str or key not in _ATTRIBUTE_RULES:
            raise ValueError("attribute name is not on the privacy allowlist")
        rule = _ATTRIBUTE_RULES[key]
        if rule == "id":
            if (type(item) is not str or not _OPAQUE_ID.fullmatch(item)
                    or "://" in item):
                raise ValueError(f"{key} must be a short opaque identifier, not a URL or free text")
        elif rule in {"outcome", "error", "device"}:
            allowed = {"outcome": _OUTCOMES, "error": _ERROR_CATEGORIES, "device": _DEVICES}[rule]
            if type(item) is not str or item not in allowed:
                raise ValueError(f"{key} has an unsupported enum value")
        elif rule == "boolean":
            if type(item) is not bool:
                raise ValueError(f"{key} must be a boolean")
        elif rule in {"integer", "http"}:
            if type(item) is not int or not 0 <= item <= 1_000_000_000:
                raise ValueError(f"{key} must be a bounded nonnegative integer")
            if rule == "http" and not 100 <= item <= 599:
                raise ValueError("http_status_code must be between 100 and 599")
        else:
            if type(item) is int:
                try:
                    number = float(item)
                except OverflowError as exc:
                    raise ValueError(f"{key} must be finite") from exc
            elif type(item) is float:
                number = item
            else:
                raise ValueError(f"{key} must be a finite number")
            if not math.isfinite(number) or not 0 <= number <= _MAX_NUMBER:
                raise ValueError(f"{key} must be finite and nonnegative")
            if rule == "percent" and number > 100:
                raise ValueError(f"{key} must be in 0..100")
            if rule == "ratio" and number > 1:
                raise ValueError(f"{key} must be in 0..1")
            item = number
        clean[key] = item
    return clean


@dataclass(frozen=True)
class TraceContext:
    """W3C traceparent identifiers; propagation is correlation, never authority."""

    trace_id: str
    span_id: str
    trace_flags: str = "00"

    def __post_init__(self) -> None:
        if type(self.trace_id) is not str or not _TRACE_ID.fullmatch(self.trace_id):
            raise ValueError("trace_id must be 32 lowercase hexadecimal characters")
        if self.trace_id == "0" * 32:
            raise ValueError("all-zero trace IDs are invalid")
        if type(self.span_id) is not str or not _SPAN_ID.fullmatch(self.span_id):
            raise ValueError("span_id must be 16 lowercase hexadecimal characters")
        if self.span_id == "0" * 16:
            raise ValueError("all-zero span IDs are invalid")
        if type(self.trace_flags) is not str or self.trace_flags not in {"00", "01"}:
            raise ValueError("version 00 trace_flags must be 00 or 01")

    def to_traceparent(self) -> str:
        return f"00-{self.trace_id}-{self.span_id}-{self.trace_flags}"

    @classmethod
    def from_traceparent(cls, header: str) -> "TraceContext":
        if type(header) is not str or len(header) != 55:
            raise ValueError("traceparent must be a 55-character W3C version 00 header")
        parts = header.split("-")
        if len(parts) != 4 or parts[0] != "00":
            raise ValueError("only W3C traceparent version 00 is supported")
        return cls(parts[1], parts[2], parts[3])


@dataclass
class _Span:
    context: TraceContext
    parent_span_id: str | None
    name: str
    component: str
    started_ms: float
    ended_ms: float | None = None
    status: str = "open"
    attributes: dict[str, str | int | float | bool] = field(default_factory=dict)


@dataclass(frozen=True)
class _Event:
    sequence: int
    name: str
    at_ms: float
    span_id: str | None
    attributes: tuple[tuple[str, str | int | float | bool], ...]


class AgentTrace:
    """Thread-safe bounded trace ledger for one request/session/task trace.

    A caller explicitly starts/finishes spans around model, retrieval, tool,
    voice, avatar, game, and OBS operations. No background polling or I/O occurs.
    Capacity exhaustion raises instead of silently discarding evidence.
    """

    def __init__(
        self, *, trace_id: str | None = None, trace_flags: str = "00",
        max_spans: int = 256, max_events: int = 1024,
    ) -> None:
        chosen_id = secrets.token_hex(16) if trace_id is None else trace_id
        # Validate the trace ID and flags without manufacturing a fake span.
        TraceContext(chosen_id, secrets.token_hex(8), trace_flags)
        if type(max_spans) is not int or not 1 <= max_spans <= 4096:
            raise ValueError("max_spans must be an integer in 1..4096")
        if type(max_events) is not int or not 1 <= max_events <= 16384:
            raise ValueError("max_events must be an integer in 1..16384")
        self.trace_id = chosen_id
        self.trace_flags = trace_flags
        self.max_spans = max_spans
        self.max_events = max_events
        self._spans: dict[str, _Span] = {}
        self._events: list[_Event] = []
        self._lock = RLock()

    def start_span(
        self, name: str, component: str, *, at_ms: float,
        parent: TraceContext | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> TraceContext:
        if type(name) is not str or not _OPERATION.fullmatch(name):
            raise ValueError("span name must be a short lowercase operation identifier")
        if type(component) is not str or component not in _COMPONENTS:
            raise ValueError("unknown span component")
        started = _clock(at_ms, "at_ms")
        clean = _attributes(attributes)
        if parent is not None:
            if type(parent) is not TraceContext or parent.trace_id != self.trace_id:
                raise ValueError("parent context belongs to a different trace")
            parent_id = parent.span_id
            flags = parent.trace_flags
        else:
            parent_id = None
            flags = self.trace_flags
        with self._lock:
            if len(self._spans) >= self.max_spans:
                raise OverflowError("trace span capacity exhausted")
            span_id = secrets.token_hex(8)
            while span_id in self._spans:
                span_id = secrets.token_hex(8)
            context = TraceContext(self.trace_id, span_id, flags)
            self._spans[span_id] = _Span(
                context=context, parent_span_id=parent_id, name=name,
                component=component, started_ms=started, attributes=clean,
            )
            return context

    def _resolve_span(self, reference: TraceContext | str) -> _Span:
        if type(reference) is TraceContext:
            if reference.trace_id != self.trace_id:
                raise ValueError("span context belongs to a different trace")
            span_id = reference.span_id
        elif type(reference) is str and _SPAN_ID.fullmatch(reference):
            span_id = reference
        else:
            raise TypeError("expected a TraceContext or span ID")
        span = self._spans.get(span_id)
        if span is None:
            raise KeyError("span is not present in this trace")
        return span

    def finish_span(
        self, reference: TraceContext | str, *, at_ms: float,
        status: str = "ok", attributes: dict[str, Any] | None = None,
    ) -> None:
        ended = _clock(at_ms, "at_ms")
        if type(status) is not str or status not in _STATUSES:
            raise ValueError("unsupported span status")
        clean = _attributes(attributes)
        with self._lock:
            span = self._resolve_span(reference)
            if span.ended_ms is not None:
                raise RuntimeError("span is already finished")
            if ended < span.started_ms:
                raise ValueError("span cannot finish before it starts")
            span.ended_ms = ended
            span.status = status
            span.attributes.update(clean)

    def add_event(
        self, name: str, *, at_ms: float,
        span: TraceContext | str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> int:
        if type(name) is not str or name not in _EVENTS:
            raise ValueError("event name is not on the event allowlist")
        occurred = _clock(at_ms, "at_ms")
        clean = _attributes(attributes)
        with self._lock:
            span_id: str | None = None
            if span is not None:
                record = self._resolve_span(span)
                if occurred < record.started_ms:
                    raise ValueError("event cannot precede its span")
                if record.ended_ms is not None and occurred > record.ended_ms:
                    raise ValueError("event cannot follow its finished span")
                span_id = record.context.span_id
            if len(self._events) >= self.max_events:
                raise OverflowError("trace event capacity exhausted")
            self._events.append(_Event(
                sequence=len(self._events) + 1, name=name, at_ms=occurred,
                span_id=span_id, attributes=tuple(sorted(clean.items())),
            ))
            return len(self._events)

    def snapshot(self) -> dict[str, Any]:
        """Return JSON-safe structured evidence; never includes arbitrary text."""
        with self._lock:
            spans = sorted(self._spans.values(), key=lambda item: (item.started_ms, item.context.span_id))
            events = sorted(self._events, key=lambda item: (item.at_ms, item.sequence))
            return {
                "schema_version": 1,
                "trace_id": self.trace_id,
                "trace_flags": self.trace_flags,
                "spans": [
                    {
                        "span_id": item.context.span_id,
                        "parent_span_id": item.parent_span_id,
                        "name": item.name,
                        "component": item.component,
                        "started_ms": item.started_ms,
                        "ended_ms": item.ended_ms,
                        "status": item.status,
                        "attributes": dict(sorted(item.attributes.items())),
                    }
                    for item in spans
                ],
                "events": [
                    {
                        "sequence": item.sequence,
                        "name": item.name,
                        "at_ms": item.at_ms,
                        "span_id": item.span_id,
                        "attributes": dict(item.attributes),
                    }
                    for item in events
                ],
            }

    def to_json(self) -> str:
        return json.dumps(self.snapshot(), ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)

    @property
    def open_span_count(self) -> int:
        with self._lock:
            return sum(span.ended_ms is None for span in self._spans.values())

    @property
    def span_count(self) -> int:
        with self._lock:
            return len(self._spans)

    @property
    def event_count(self) -> int:
        with self._lock:
            return len(self._events)


__all__ = ["TraceContext", "AgentTrace"]
