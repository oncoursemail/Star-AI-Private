"""Offline tests for bounded, privacy-safe agent tracing."""
import json

import pytest

from star.agent_trace import AgentTrace, TraceContext


TRACE_ID = "a" * 32


def test_w3c_traceparent_round_trip():
    context = TraceContext(TRACE_ID, "b" * 16, "01")
    assert TraceContext.from_traceparent(context.to_traceparent()) == context


@pytest.mark.parametrize("header", [
    "",
    "00-" + ("0" * 32) + "-" + ("b" * 16) + "-00",
    "00-" + ("a" * 32) + "-" + ("0" * 16) + "-00",
    "01-" + ("a" * 32) + "-" + ("b" * 16) + "-00",
    "00-" + ("a" * 32) + "-" + ("b" * 16) + "-0x",
    "00-" + ("A" * 32) + "-" + ("b" * 16) + "-01",
    "00-" + ("a" * 32) + "-" + ("b" * 16) + "-02",
    "00-" + ("a" * 32) + "-" + ("b" * 16) + "-ff",
])
def test_invalid_traceparent_is_rejected(header):
    with pytest.raises(ValueError):
        TraceContext.from_traceparent(header)


def test_trace_spans_correlate_model_work_and_safe_events():
    trace = AgentTrace(trace_id=TRACE_ID, trace_flags="01")
    root = trace.start_span("session.run", "runtime", at_ms=100)
    model = trace.start_span(
        "model.generate", "model", at_ms=110, parent=root,
        attributes={"model_id": "local-8b", "input_tokens": 120},
    )
    trace.add_event("model_started", at_ms=111, span=model, attributes={"route_id": "fast"})
    trace.finish_span(
        model, at_ms=250, status="ok",
        attributes={"output_tokens": 32, "ttft_ms": 80.5},
    )
    trace.finish_span(root, at_ms=260, status="ok", attributes={"outcome": "success"})

    snapshot = trace.snapshot()
    assert snapshot["trace_id"] == TRACE_ID
    assert len(snapshot["spans"]) == 2
    assert snapshot["spans"][1]["parent_span_id"] == root.span_id
    assert snapshot["spans"][1]["attributes"]["output_tokens"] == 32
    assert snapshot["events"][0]["name"] == "model_started"
    assert trace.open_span_count == 0
    assert json.loads(trace.to_json()) == snapshot


def test_traceparent_propagates_to_child_and_rejects_cross_trace_parent():
    trace = AgentTrace(trace_id=TRACE_ID)
    root = trace.start_span("runtime.handle", "runtime", at_ms=1)
    remote_context = TraceContext.from_traceparent(root.to_traceparent())
    child = trace.start_span("tool.execute", "tool", at_ms=2, parent=remote_context)
    assert child.trace_id == root.trace_id
    assert trace.snapshot()["spans"][1]["parent_span_id"] == root.span_id

    other = AgentTrace(trace_id="c" * 32)
    with pytest.raises(ValueError, match="different trace"):
        other.start_span("tool.execute", "tool", at_ms=2, parent=root)


def test_events_must_be_inside_their_span_and_finished_spans_are_closed():
    trace = AgentTrace(trace_id=TRACE_ID)
    span = trace.start_span("voice.reply", "voice", at_ms=10)
    with pytest.raises(ValueError, match="precede"):
        trace.add_event("audio_queued", at_ms=9, span=span)
    trace.finish_span(span, at_ms=20)
    with pytest.raises(ValueError, match="follow"):
        trace.add_event("audio_playback_started", at_ms=21, span=span)
    with pytest.raises(RuntimeError, match="already finished"):
        trace.finish_span(span, at_ms=22)


@pytest.mark.parametrize("attributes", [
    {"prompt": "private text"},
    {"viewer_name": "Alice"},
    {"api_key": "secret"},
    {"audio": "raw pcm"},
    {"screenshot": "image bytes"},
    {"model_id": "https://provider.example/model"},
    {"input_tokens": True},
    {"cpu_busy_percent": 101},
    {"kv_cache_usage_ratio": 1.1},
    {"http_status_code": 99},
])
def test_unapproved_or_invalid_attributes_are_rejected(attributes):
    trace = AgentTrace(trace_id=TRACE_ID)
    with pytest.raises(ValueError):
        trace.start_span("model.generate", "model", at_ms=1, attributes=attributes)


def test_capacity_is_bounded_and_never_silently_drops():
    trace = AgentTrace(trace_id=TRACE_ID, max_spans=1, max_events=1)
    span = trace.start_span("runtime.handle", "runtime", at_ms=1)
    with pytest.raises(OverflowError, match="span capacity"):
        trace.start_span("model.generate", "model", at_ms=2)
    trace.add_event("task_started", at_ms=1, span=span)
    with pytest.raises(OverflowError, match="event capacity"):
        trace.add_event("task_checkpointed", at_ms=2, span=span)
    assert trace.span_count == 1
    assert trace.event_count == 1


def test_invalid_operation_component_clock_and_flags_are_rejected():
    with pytest.raises(ValueError):
        TraceContext(TRACE_ID, "b" * 16, "zz")
    trace = AgentTrace(trace_id=TRACE_ID)
    with pytest.raises(ValueError):
        trace.start_span("Model Generate", "model", at_ms=1)
    with pytest.raises(ValueError):
        trace.start_span("model.generate", "unknown", at_ms=1)
    with pytest.raises(ValueError):
        trace.start_span("model.generate", "model", at_ms=float("nan"))
