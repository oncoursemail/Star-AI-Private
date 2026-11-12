"""Offline tests for the read-only AgentTrace profiler."""

import pytest

from star.agent_trace import AgentTrace
from star.agent_trace_analysis import profile_trace


TRACE_ID = "a" * 32


def _closed_span(trace, name, component, start, end, parent=None):
    context = trace.start_span(name, component, at_ms=start, parent=parent)
    trace.finish_span(context, at_ms=end)
    return context


def test_root_reports_child_coverage_and_uninstrumented_wall_time():
    trace = AgentTrace(trace_id=TRACE_ID)
    root = trace.start_span("session.run", "runtime", at_ms=0)
    _closed_span(trace, "model.generate", "model", 10, 40, root)
    _closed_span(trace, "tts.synthesize", "tts", 50, 80, root)
    trace.finish_span(root, at_ms=100)

    profile = profile_trace(trace.snapshot())

    assert profile["trace_wall_ms"] == 100
    assert profile["roots"][0]["child_coverage_ms"] == 60
    assert profile["roots"][0]["unattributed_ms"] == 40
    assert profile["roots"][0]["parallel_child_overlap_ms"] == 0
    assert profile["counts"] == {
        "spans": 3,
        "completed_spans": 3,
        "open_spans": 0,
        "failed_spans": 0,
        "roots": 1,
    }


def test_parallel_sibling_overlap_is_not_double_counted_as_coverage():
    trace = AgentTrace(trace_id=TRACE_ID)
    root = trace.start_span("session.run", "runtime", at_ms=0)
    _closed_span(trace, "vision.observe", "game", 10, 60, root)
    _closed_span(trace, "model.plan", "model", 30, 70, root)
    trace.finish_span(root, at_ms=100)

    root_profile = profile_trace(trace.snapshot())["roots"][0]

    assert root_profile["child_coverage_ms"] == 60
    assert root_profile["parallel_child_overlap_ms"] == 30
    assert root_profile["unattributed_ms"] == 40


def test_nested_spans_have_inclusive_and_exclusive_durations():
    trace = AgentTrace(trace_id=TRACE_ID)
    root = trace.start_span("session.run", "runtime", at_ms=0)
    model = trace.start_span("model.generate", "model", at_ms=10, parent=root)
    _closed_span(trace, "memory.retrieve", "memory", 20, 30, model)
    trace.finish_span(model, at_ms=80)
    trace.finish_span(root, at_ms=100)

    profile = profile_trace(trace.snapshot())
    by_name = {item["name"]: item for item in profile["slowest_spans"]}

    assert by_name["model.generate"]["duration_ms"] == 70
    assert by_name["model.generate"]["child_coverage_ms"] == 10
    assert by_name["model.generate"]["exclusive_ms"] == 60
    assert by_name["session.run"]["exclusive_ms"] == 30


def test_open_spans_are_counted_without_fabricated_durations():
    trace = AgentTrace(trace_id=TRACE_ID)
    root = trace.start_span("session.run", "runtime", at_ms=0)
    trace.start_span("voice.listen", "voice", at_ms=5, parent=root)

    profile = profile_trace(trace.snapshot())

    assert profile["trace_wall_ms"] is None
    assert profile["counts"]["open_spans"] == 2
    assert profile["counts"]["completed_spans"] == 0
    assert all(item["duration_ms"] is None for item in profile["roots"])


def test_component_percentiles_use_nearest_rank_and_exclude_open_spans():
    trace = AgentTrace(trace_id=TRACE_ID)
    root = trace.start_span("session.run", "runtime", at_ms=0)
    _closed_span(trace, "model.one", "model", 1, 11, root)
    _closed_span(trace, "model.two", "model", 20, 40, root)
    _closed_span(trace, "model.three", "model", 50, 80, root)
    trace.start_span("model.open", "model", at_ms=90, parent=root)
    profile = profile_trace(trace.snapshot())
    model = next(item for item in profile["components"] if item["component"] == "model")

    assert model["completed_spans"] == 3
    assert model["inclusive_p50_ms"] == 20
    assert model["inclusive_p95_ms"] == 30
    assert model["inclusive_max_ms"] == 30


def test_event_summary_never_copies_event_attributes():
    trace = AgentTrace(trace_id=TRACE_ID)
    root = trace.start_span("session.run", "runtime", at_ms=0)
    trace.add_event("model_started", at_ms=1, span=root)
    trace.add_event("model_finished", at_ms=2, span=root)
    trace.finish_span(root, at_ms=3)
    snapshot = trace.snapshot()
    snapshot["events"][0]["attributes"] = {"transcript": "private words"}

    profile = profile_trace(snapshot)

    assert profile["event_counts"] == {"model_finished": 1, "model_started": 1}
    assert "private words" not in repr(profile)
    assert "transcript" not in repr(profile)


@pytest.mark.parametrize("mutation, message", [
    ("missing_parent", "missing parent"),
    ("child_outlives_parent", "outlives"),
    ("cycle", "cycle"),
])
def test_invalid_parent_graphs_are_rejected(mutation, message):
    trace = AgentTrace(trace_id=TRACE_ID)
    root = trace.start_span("session.run", "runtime", at_ms=0)
    child = trace.start_span("model.generate", "model", at_ms=0, parent=root)
    trace.finish_span(child, at_ms=10)
    trace.finish_span(root, at_ms=10)
    snapshot = trace.snapshot()

    root_record = next(
        item for item in snapshot["spans"] if item["parent_span_id"] is None
    )
    child_record = next(
        item for item in snapshot["spans"] if item["parent_span_id"] is not None
    )
    if mutation == "missing_parent":
        child_record["parent_span_id"] = "f" * 16
    elif mutation == "child_outlives_parent":
        child_record["ended_ms"] = 11
    else:
        root_record["parent_span_id"] = child.span_id

    with pytest.raises(ValueError, match=message):
        profile_trace(snapshot)


def test_unknown_events_duplicate_sequences_and_bad_clocks_are_rejected():
    trace = AgentTrace(trace_id=TRACE_ID)
    root = trace.start_span("session.run", "runtime", at_ms=0)
    trace.add_event("task_started", at_ms=1, span=root)
    trace.finish_span(root, at_ms=2)
    snapshot = trace.snapshot()

    unknown = dict(snapshot)
    unknown["events"] = [dict(snapshot["events"][0], name="viewer_said_private_text")]
    with pytest.raises(ValueError, match="event name"):
        profile_trace(unknown)

    duplicate = dict(snapshot)
    duplicate["events"] = [snapshot["events"][0], dict(snapshot["events"][0])]
    with pytest.raises(ValueError, match="unique"):
        profile_trace(duplicate)

    bad_clock = dict(snapshot)
    bad_clock["spans"] = [dict(snapshot["spans"][0], started_ms=float("nan"))]
    with pytest.raises(ValueError, match="clock range"):
        profile_trace(bad_clock)


def test_slowest_limit_is_bounded_and_empty_trace_is_valid():
    trace = AgentTrace(trace_id=TRACE_ID)
    with pytest.raises(ValueError, match="slowest_limit"):
        profile_trace(trace.snapshot(), slowest_limit=0)

    profile = profile_trace(trace.snapshot())
    assert profile["trace_wall_ms"] is None
    assert profile["counts"]["spans"] == 0
    assert profile["roots"] == []
    assert profile["slowest_spans"] == []


def test_invalid_trace_flags_and_all_zero_identifiers_are_rejected():
    trace = AgentTrace(trace_id=TRACE_ID)
    root = trace.start_span("session.run", "runtime", at_ms=0)
    trace.finish_span(root, at_ms=1)
    snapshot = trace.snapshot()

    bad_flags = dict(snapshot, trace_flags="ff")
    with pytest.raises(ValueError, match="trace flags"):
        profile_trace(bad_flags)

    zero_trace = dict(snapshot, trace_id="0" * 32)
    with pytest.raises(ValueError, match="trace ID"):
        profile_trace(zero_trace)

    zero_span = dict(snapshot)
    zero_span["spans"] = [dict(snapshot["spans"][0], span_id="0" * 16)]
    with pytest.raises(ValueError, match="all-zero"):
        profile_trace(zero_span)
