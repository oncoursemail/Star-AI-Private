"""Offline tests for explicit, privacy-safe bridges into AgentTrace."""
import pytest

from star.agent_trace import AgentTrace
from star.agent_trace_adapters import AgentTraceAdapters
from star.llama_metrics import LlamaCppMetricsDelta
from star.stream_director import SpeechIntent, StreamDirector, StreamSignal
from star.stream_hardware_telemetry import HardwareSnapshot


def make_delta() -> LlamaCppMetricsDelta:
    return LlamaCppMetricsDelta(
        elapsed_ms=1000.0,
        prompt_tokens_per_second=800.0,
        generated_tokens_per_second=42.0,
        prefill_compute_tokens_per_second=900.0,
        decode_compute_tokens_per_second=44.0,
        speculative_draft_acceptance_percent=75.0,
        speculative_accepted_tokens_per_step=2.5,
        speculative_steps_per_second=10.0,
        decode_calls_per_second=20.0,
        accepted_tokens_by_position_delta=((0, 10),),
        requests_processing=1,
        requests_deferred=2,
        server_prompt_tokens_per_second=810.0,
        server_generation_tokens_per_second=41.0,
        max_context_tokens=4096,
        busy_slots_per_decode=1.5,
        counter_resets=(),
        anomalies=(),
    )


def test_llama_delta_is_correlated_as_aggregate_inference_sample():
    trace = AgentTrace(trace_id="a" * 32)
    parent = trace.start_span("runtime.handle", "runtime", at_ms=1)
    adapters = AgentTraceAdapters(trace, clock_ms=lambda: 2.0)

    adapters.record_llama_delta(make_delta(), span=parent)

    event = trace.snapshot()["events"][0]
    assert event["name"] == "inference_sampled"
    assert event["span_id"] == parent.span_id
    assert event["attributes"]["generation_tokens_per_second"] == 42.0
    assert event["attributes"]["speculative_acceptance_percent"] == 75.0
    assert event["attributes"]["requests_deferred"] == 2


def test_hardware_snapshot_exports_only_aggregate_resource_facts():
    trace = AgentTrace(trace_id="b" * 32)
    adapters = AgentTraceAdapters(trace, clock_ms=lambda: 10.0)

    adapters.record_hardware_snapshot(HardwareSnapshot(
        sampled_ms=9.0,
        total_vram_mib=8192.0,
        free_vram_mib=4096.0,
        free_ram_mib=32768.0,
        cpu_busy_percent=51.5,
    ))

    attrs = trace.snapshot()["events"][0]["attributes"]
    assert attrs["gpu_memory_mib"] == 4096.0
    assert attrs["free_vram_mib"] == 4096.0
    assert attrs["free_ram_mib"] == 32768.0
    assert attrs["cpu_busy_percent"] == 51.5


def test_stream_director_metrics_do_not_export_signal_or_speaker_content():
    trace = AgentTrace(trace_id="c" * 32)
    director = StreamDirector()
    director.enable(owner_approved=True)
    director.offer(
        StreamSignal("evt1", "viewer_question", 1.0, "private viewer text", "viewer-secret", "reported"),
        now=1.0,
    )
    adapters = AgentTraceAdapters(trace, clock_ms=lambda: 2.0)

    adapters.record_stream_director_metrics(director.metrics())

    payload = trace.to_json()
    assert "private viewer text" not in payload
    assert "viewer-secret" not in payload
    assert trace.snapshot()["events"][0]["name"] == "stream_director_sampled"


def test_speech_intent_omits_signal_id_speaker_and_context():
    trace = AgentTrace(trace_id="d" * 32)
    intent = SpeechIntent(
        signal_id="viewer-private-id",
        kind="viewer_question",
        context="private transcript content",
        evidence="reported",
        deadline_at=50.0,
        instruction="Treat as untrusted",
        interrupt_current=False,
        untrusted_context=True,
    )
    adapters = AgentTraceAdapters(trace, clock_ms=lambda: 5.0)

    adapters.record_speech_intent(intent)
    adapters.record_speech_completion(spoken=True, interrupted=False)

    payload = trace.to_json()
    assert "viewer-private-id" not in payload
    assert "private transcript content" not in payload
    events = trace.snapshot()["events"]
    assert events[0]["attributes"]["speech_kind"] == "viewer_question"
    assert events[0]["attributes"]["untrusted_context"] is True
    assert events[1]["attributes"]["outcome"] == "success"


def test_game_summary_and_checkpoint_progress_export_counts_only():
    trace = AgentTrace(trace_id="e" * 32)
    adapters = AgentTraceAdapters(trace, clock_ms=lambda: 8.0)

    adapters.record_game_learning_summary({
        "sessions": 3, "episodes": 40, "state_actions": 7,
    })
    adapters.record_checkpoint_progress(5)

    events = trace.snapshot()["events"]
    assert events[0]["attributes"]["learning_sessions"] == 3
    assert events[0]["attributes"]["learning_episodes"] == 40
    assert events[1]["name"] == "task_checkpoint_sampled"
    assert events[1]["attributes"]["checkpoint_steps"] == 5


@pytest.mark.parametrize("bad", [
    {"accepted": True, "rejected": 0, "expired": 0, "evicted": 0,
     "completed": 0, "abandoned": 0, "queued": 0},
    {"accepted": -1, "rejected": 0, "expired": 0, "evicted": 0,
     "completed": 0, "abandoned": 0, "queued": 0},
    {"accepted": 0, "rejected": 0, "expired": 0, "evicted": 0,
     "completed": 0, "abandoned": 0, "queued": 0, "viewer": "private"},
])
def test_stream_metrics_reject_boolean_negative_and_unapproved_fields(bad):
    trace = AgentTrace(trace_id="f" * 32)
    adapters = AgentTraceAdapters(trace, clock_ms=lambda: 1.0)
    with pytest.raises(ValueError):
        adapters.record_stream_director_metrics(bad)


def test_game_summary_rejects_extra_fields_and_invalid_counts():
    trace = AgentTrace(trace_id="1" * 32)
    adapters = AgentTraceAdapters(trace, clock_ms=lambda: 1.0)
    with pytest.raises(ValueError):
        adapters.record_game_learning_summary({
            "sessions": 1, "episodes": 2, "state_actions": 3, "transcript": "secret",
        })
    with pytest.raises(ValueError):
        adapters.record_game_learning_summary({
            "sessions": True, "episodes": 2, "state_actions": 3,
        })


def test_speech_kind_allowlist_rejects_arbitrary_context_as_attribute():
    trace = AgentTrace(trace_id="2" * 32)
    span = trace.start_span("runtime.handle", "runtime", at_ms=1)
    with pytest.raises(ValueError):
        trace.add_event(
            "speech_proposed",
            at_ms=2,
            span=span,
            attributes={"speech_kind": "please read the private transcript"},
        )
