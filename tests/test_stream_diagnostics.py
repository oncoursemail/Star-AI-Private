"""Offline tests for evidence-bounded stream rehearsal diagnostics."""

import pytest

from star.agent_trace import AgentTrace
from star.stream_diagnostics import diagnose_stream_rehearsal
from star.stream_rehearsal_eval import RehearsalLimits


def rehearsal(**changes):
    value = {
        "schema_version": 2,
        "run_id": "rehearsal-001",
        "first_content_latency_ms": [180.0] * 20,
        "first_audible_latency_ms": [420.0] * 20,
        "game_frame_time_ms": [16.7] * 20,
        "avatar_sync_error_ms": [24.0] * 20,
        "audio_underrun_chunks": 0,
        "audio_playback_chunks": 1000,
        "obs_render_skipped_frames": 0,
        "obs_render_total_frames": 10000,
        "obs_output_skipped_frames": 0,
        "obs_output_total_frames": 10000,
        "turn_true_positives": 19,
        "turn_false_positives": 1,
        "turn_false_negatives": 1,
        "task_recovery_attempts": 20,
        "task_recovery_successes": 19,
        "stale_task_resumes": 0,
        "duplicate_speech_replays": 0,
        "held_out_skill_trials": 20,
        "held_out_skill_successes": 18,
        "spoken_task_trials": 20,
        "spoken_task_successes": 19,
        "whisper_control_trials": 20,
        "whisper_control_successes": 20,
        "volume_control_trials": 20,
        "volume_control_successes": 19,
        "groundedness_trials": 20,
        "groundedness_successes": 19,
    }
    value.update(changes)
    return value


def limits(**changes):
    value = {
        "min_observations": 20,
        "max_first_content_p95_ms": 300.0,
        "max_first_audible_p95_ms": 600.0,
        "max_game_frame_p99_ms": 20.0,
        "max_avatar_sync_p95_ms": 50.0,
        "max_audio_underrun_rate": 0.001,
        "max_obs_render_skip_rate": 0.001,
        "max_obs_output_skip_rate": 0.001,
        "min_turn_precision": 0.9,
        "min_turn_recall": 0.9,
        "min_task_recovery_rate": 0.9,
        "min_held_out_skill_transfer_rate": 0.8,
        "min_spoken_task_accuracy": 0.9,
        "min_whisper_control_rate": 0.9,
        "min_volume_control_rate": 0.9,
        "min_groundedness_rate": 0.9,
        "max_stale_task_resumes": 0,
        "max_duplicate_speech_replays": 0,
    }
    value.update(changes)
    return RehearsalLimits(**value)


def trace_with_spans(*, open_model=False):
    trace = AgentTrace(trace_id="a" * 32)
    root = trace.start_span("session.run", "runtime", at_ms=0)
    model = trace.start_span("model.generate", "model", at_ms=10, parent=root)
    if not open_model:
        trace.finish_span(model, at_ms=70)
    voice = trace.start_span("tts.synthesize", "tts", at_ms=75, parent=root)
    trace.finish_span(voice, at_ms=95)
    if not open_model:
        trace.finish_span(root, at_ms=100)
    return trace.snapshot()


def test_failed_audible_gate_routes_to_voice_components_without_claiming_causality():
    report = diagnose_stream_rehearsal(
        rehearsal(first_audible_latency_ms=[900.0] * 20),
        limits(),
        trace_snapshot=trace_with_spans(),
        trace_run_id="rehearsal-001",
    )

    assert report["status"] == "ACTIONABLE_FAILURES"
    issue = next(item for item in report["diagnoses"] if item["gate"] == "first_audible_p95_ms")
    assert issue["evidence_status"] == "OBSERVED_NOT_CAUSAL"
    assert {item["component"] for item in issue["candidate_component_observations"]} == {"tts"}
    assert "causal" in report["notes"][0].lower()


def test_failed_game_and_obs_gates_remain_separate():
    report = diagnose_stream_rehearsal(
        rehearsal(
            game_frame_time_ms=[30.0] * 20,
            obs_render_skipped_frames=100,
            obs_render_total_frames=10000,
            obs_output_skipped_frames=200,
            obs_output_total_frames=10000,
        ),
        limits(),
    )

    gates = {item["gate"] for item in report["diagnoses"]}
    assert "game_frame_p99_ms" in gates
    assert "obs_render_skip_rate" in gates
    assert "obs_output_skip_rate" in gates
    assert all(item["evidence_status"] == "TRACE_NOT_SUPPLIED" for item in report["diagnoses"])


def test_missing_trace_never_invents_component_attribution():
    report = diagnose_stream_rehearsal(
        rehearsal(first_content_latency_ms=[800.0] * 20),
        limits(),
    )

    issue = report["diagnoses"][0]
    assert issue["evidence_status"] == "TRACE_NOT_SUPPLIED"
    assert issue["candidate_component_observations"] == []


def test_trace_run_id_must_match_rehearsal_run_id():
    with pytest.raises(ValueError, match="must match"):
        diagnose_stream_rehearsal(
            rehearsal(),
            limits(),
            trace_snapshot=trace_with_spans(),
            trace_run_id="different-run",
        )


def test_trace_requires_explicit_host_correlation_label():
    with pytest.raises(ValueError, match="required"):
        diagnose_stream_rehearsal(
            rehearsal(),
            limits(),
            trace_snapshot=trace_with_spans(),
        )


def test_passing_configured_gates_does_not_claim_broad_capability():
    report = diagnose_stream_rehearsal(rehearsal(), limits())

    assert report["status"] == "CONFIGURED_GATES_PASS"
    assert report["diagnoses"] == []
    assert any("does not establish general intelligence" in note for note in report["notes"])


def test_inconclusive_gate_becomes_evidence_gap_not_failure():
    report = diagnose_stream_rehearsal(
        rehearsal(first_audible_latency_ms=[100.0]),
        limits(),
    )

    assert report["status"] == "INCONCLUSIVE"
    assert report["diagnoses"] == []
    assert report["evidence_gaps"] == [{
        "gate": "first_audible_p95_ms",
        "observations": 1,
        "required_observations": 20,
        "action": "collect_more_valid_observations",
    }]


def test_open_trace_spans_are_reported_without_fabricated_durations():
    report = diagnose_stream_rehearsal(
        rehearsal(first_content_latency_ms=[800.0] * 20),
        limits(),
        trace_snapshot=trace_with_spans(open_model=True),
        trace_run_id="rehearsal-001",
    )

    assert report["trace"]["health"] == "OPEN_SPANS_PRESENT"
    assert report["trace"]["counts"]["open_spans"] == 2
    assert any("incomplete" in note.lower() for note in report["notes"])


def test_component_budget_is_operator_supplied_and_reported():
    report = diagnose_stream_rehearsal(
        rehearsal(first_audible_latency_ms=[900.0] * 20),
        limits(),
        trace_snapshot=trace_with_spans(),
        trace_run_id="rehearsal-001",
        component_budgets_ms={"tts": 10.0},
    )

    component = next(
        item for item in report["trace"]["components"] if item["component"] == "tts"
    )
    assert component["budget_ms"] == 10.0
    assert component["budget_status"] == "OVER_BUDGET"


def test_invalid_component_budgets_are_rejected():
    with pytest.raises(ValueError, match="unknown component"):
        diagnose_stream_rehearsal(rehearsal(), limits(), component_budgets_ms={"gpu": 20.0})
    with pytest.raises(ValueError, match="finite positive"):
        diagnose_stream_rehearsal(rehearsal(), limits(), component_budgets_ms={"model": float("nan")})
    with pytest.raises(ValueError, match="finite positive"):
        diagnose_stream_rehearsal(rehearsal(), limits(), component_budgets_ms={"model": True})


def test_trace_attributes_and_ids_are_not_copied_into_report():
    snapshot = trace_with_spans()
    snapshot["events"].append({
        "sequence": 1,
        "name": "task_started",
        "at_ms": 1,
        "span_id": snapshot["spans"][0]["span_id"],
        "attributes": {"transcript": "private words must not escape"},
    })
    report = diagnose_stream_rehearsal(
        rehearsal(first_content_latency_ms=[800.0] * 20),
        limits(),
        trace_snapshot=snapshot,
        trace_run_id="rehearsal-001",
    )

    rendered = repr(report)
    assert "private words" not in rendered
    assert "transcript" not in rendered
    assert "a" * 32 not in rendered
    assert snapshot["spans"][0]["span_id"] not in rendered


def test_diagnoses_are_bounded_and_deterministically_ordered():
    report = diagnose_stream_rehearsal(
        rehearsal(
            first_content_latency_ms=[800.0] * 20,
            first_audible_latency_ms=[900.0] * 20,
            game_frame_time_ms=[30.0] * 20,
            avatar_sync_error_ms=[100.0] * 20,
            audio_underrun_chunks=5,
            obs_render_skipped_frames=100,
            obs_output_skipped_frames=100,
            turn_false_positives=20,
            turn_false_negatives=20,
            task_recovery_successes=0,
            stale_task_resumes=1,
            duplicate_speech_replays=1,
            held_out_skill_successes=0,
        ),
        limits(),
        max_diagnoses=3,
    )

    assert len(report["diagnoses"]) == 3
    assert [item["gate"] for item in report["diagnoses"]] == sorted(
        [item["gate"] for item in report["diagnoses"]],
        key=lambda name: (0 if name in {
            "first_audible_p95_ms", "audio_underrun_rate", "game_frame_p99_ms"
        } else 1, name),
    )


def test_diagnosis_limit_is_bounded():
    with pytest.raises(ValueError, match="max_diagnoses"):
        diagnose_stream_rehearsal(rehearsal(), limits(), max_diagnoses=0)



def test_new_voice_quality_and_groundedness_gates_route_to_distinct_components():
    report = diagnose_stream_rehearsal(
        rehearsal(
            spoken_task_successes=10,
            whisper_control_successes=10,
            volume_control_successes=10,
            groundedness_successes=10,
        ),
        limits(),
    )

    by_gate = {item["gate"]: item for item in report["diagnoses"]}
    assert set(by_gate) == {
        "spoken_task_accuracy",
        "whisper_control_rate",
        "volume_control_rate",
        "groundedness_rate",
    }
    assert by_gate["spoken_task_accuracy"]["candidate_component_observations"] == []
    assert by_gate["groundedness_rate"]["evidence_status"] == "TRACE_NOT_SUPPLIED"
    assert report["status"] == "ACTIONABLE_FAILURES"
