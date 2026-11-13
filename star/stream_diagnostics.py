"""Evidence-bounded triage for STAR's private VTuber rehearsal runs.

Combines the existing rehearsal quality gates with one host-correlated AgentTrace
profile. It proposes investigation targets; it does not claim causal attribution,
change runtime policy, tune models, control devices, or authorize actions.
"""
from __future__ import annotations

import math
import re
from typing import Any, cast

from .agent_trace_analysis import profile_trace
from .stream_rehearsal_eval import RehearsalLimits, evaluate_rehearsal

_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_COMPONENTS = frozenset({
    "runtime", "retrieval", "model", "tool", "voice", "tts", "audio",
    "avatar", "game", "memory", "evaluation", "obs", "scheduler",
    "desktop", "network",
})
_MAX_BUDGET_MS = 300_000.0
_MAX_DIAGNOSES = 17

# These are investigation maps, not causal graphs. A failed metric can have
# multiple causes and the listed components are only sensible first probes.
_GATE_ROUTES: dict[str, tuple[str, ...]] = {
    "first_content_p95_ms": ("scheduler", "retrieval", "memory", "model", "network"),
    "first_audible_p95_ms": ("scheduler", "voice", "tts", "audio", "avatar"),
    "game_frame_p99_ms": ("game", "desktop", "obs", "scheduler"),
    "avatar_sync_p95_ms": ("avatar", "audio", "voice"),
    "audio_underrun_rate": ("audio", "voice", "scheduler"),
    "obs_render_skip_rate": ("obs", "game", "desktop"),
    "obs_output_skip_rate": ("obs", "network"),
    "turn_precision": ("voice", "audio", "runtime"),
    "turn_recall": ("voice", "audio", "runtime"),
    "task_recovery_rate": ("runtime", "memory", "tool"),
    "stale_task_resumes": ("runtime", "memory", "tool"),
    "duplicate_speech_replays": ("voice", "audio", "runtime"),
    "held_out_skill_transfer_rate": ("game", "memory", "tool"),
    "spoken_task_accuracy": ("voice", "model", "retrieval", "tool"),
    "whisper_control_rate": ("voice", "tts", "audio"),
    "volume_control_rate": ("voice", "tts", "audio"),
    "groundedness_rate": ("memory", "retrieval", "model", "tool"),
}

_GATE_EXPERIMENTS: dict[str, str] = {
    "first_content_p95_ms": (
        "Run a paired, fixed-prompt inference trial; separately record queue wait, "
        "retrieval, prefill, decode and tool time before changing model settings."
    ),
    "first_audible_p95_ms": (
        "Replay the same short turns and separately timestamp model first-content, "
        "TTS first chunk, audio queue submission and device-confirmed playback."
    ),
    "game_frame_p99_ms": (
        "Repeat the same game scene with voice, vision and background agents enabled "
        "one at a time; capture host-verified frame-present intervals."
    ),
    "avatar_sync_p95_ms": (
        "Use a fixed audio sample and measure playback-clock to avatar-parameter "
        "application error; do not infer synchronization from generated text."
    ),
    "audio_underrun_rate": (
        "Repeat a fixed speech workload while logging device callback health and "
        "underrun counters; keep capture content out of the diagnostic record."
    ),
    "obs_render_skip_rate": (
        "Compare OBS render-lag counters with game frame times and GPU headroom; "
        "keep render skips distinct from output/network drops."
    ),
    "obs_output_skip_rate": (
        "Inspect encoder and network/output counters separately from render timing; "
        "repeat with a local recording and a controlled network condition."
    ),
    "turn_precision": (
        "Score a held-out, human-labelled set of direct-address, backchannel, "
        "side-conversation and interruption cases; inspect false-positive turns."
    ),
    "turn_recall": (
        "Score held-out genuine questions and barge-ins; inspect missed direct "
        "addresses and missed interruptions without relaxing all thresholds."
    ),
    "task_recovery_rate": (
        "Inject a viewer interruption at a known checkpoint, then verify task revision, "
        "fresh external state, completed side effects and exactly-once speech playback."
    ),
    "stale_task_resumes": (
        "Create a task revision change while the task is paused; verify the old "
        "checkpoint is marked superseded and never resumed."
    ),
    "duplicate_speech_replays": (
        "Inject playback acknowledgement loss and planner restart; verify idempotent "
        "utterance identity and host-confirmed stop/completion before retry."
    ),
    "held_out_skill_transfer_rate": (
        "Evaluate the same mechanic on unseen maps or games with fixed controls and "
        "independent outcome labels; separate practice tasks from held-out tasks."
    ),
    "spoken_task_accuracy": (
        "Score spoken requests against a sealed task oracle; separate task success "
        "from turn timing, tool recovery, and the model's own self-rating."
    ),
    "whisper_control_rate": (
        "Use blinded human or calibrated acoustic labels to check requested whisper "
        "delivery; normalize for microphone gain and playback chain."
    ),
    "volume_control_rate": (
        "Compare requested relative loudness changes with independently measured "
        "playback levels; do not use one universal dB target across devices."
    ),
    "groundedness_rate": (
        "Evaluate conversations of at least 21 turns against cited evidence and "
        "temporal consistency; score unsupported claims and stale-memory errors."
    ),
}

_GATE_PRIORITY = {
    "first_audible_p95_ms": 0,
    "audio_underrun_rate": 0,
    "game_frame_p99_ms": 0,
    "obs_render_skip_rate": 1,
    "obs_output_skip_rate": 1,
    "first_content_p95_ms": 1,
    "avatar_sync_p95_ms": 1,
    "turn_precision": 1,
    "turn_recall": 1,
    "task_recovery_rate": 1,
    "stale_task_resumes": 1,
    "duplicate_speech_replays": 1,
    "held_out_skill_transfer_rate": 2,
    "spoken_task_accuracy": 1,
    "whisper_control_rate": 1,
    "volume_control_rate": 1,
    "groundedness_rate": 1,
}


def _budget_map(value: object) -> dict[str, float]:
    if value is None:
        return {}
    if type(value) is not dict or len(value) > len(_COMPONENTS):
        raise ValueError("component_budgets_ms must be a bounded component-to-budget dictionary")
    result: dict[str, float] = {}
    for component, budget in value.items():
        if type(component) is not str or component not in _COMPONENTS:
            raise ValueError("component budget uses an unknown component")
        if type(budget) not in (int, float):
            raise ValueError("component budgets must be finite positive milliseconds")
        try:
            number = float(cast(int | float, budget))
        except (OverflowError, ValueError) as exc:
            raise ValueError("component budgets must be finite positive milliseconds") from exc
        if not math.isfinite(number) or not 0 < number <= _MAX_BUDGET_MS:
            raise ValueError("component budgets must be finite positive milliseconds")
        result[component] = number
    return result


def _trace_summary(profile: dict[str, Any], budgets: dict[str, float]) -> dict[str, Any]:
    components: list[dict[str, Any]] = []
    by_component: dict[str, dict[str, Any]] = {}
    for item in profile["components"]:
        component = item["component"]
        exclusive = item["exclusive_p95_ms"]
        budget = budgets.get(component)
        status = None
        if budget is not None and exclusive is not None:
            status = "OVER_BUDGET" if exclusive > budget else "WITHIN_BUDGET"
        record = {
            "component": component,
            "completed_spans": item["completed_spans"],
            "inclusive_p95_ms": item["inclusive_p95_ms"],
            "exclusive_p95_ms": exclusive,
            "exclusive_max_ms": item["exclusive_max_ms"],
            "budget_ms": budget,
            "budget_status": status,
        }
        components.append(record)
        by_component[component] = record

    roots = []
    for root in profile["roots"]:
        duration = root["duration_ms"]
        unattributed = root["unattributed_ms"]
        roots.append({
            "duration_ms": duration,
            "child_coverage_ms": root["child_coverage_ms"],
            "unattributed_ms": unattributed,
            "unattributed_fraction": (
                round(unattributed / duration, 6)
                if duration is not None and duration > 0 and unattributed is not None
                else None
            ),
            "parallel_child_overlap_ms": root["parallel_child_overlap_ms"],
            "status": root["status"],
        })

    counts = profile["counts"]
    health = "NO_COMPLETED_SPANS" if counts["completed_spans"] == 0 else (
        "OPEN_SPANS_PRESENT" if counts["open_spans"] else "COMPLETE"
    )
    return {
        "health": health,
        "counts": dict(counts),
        "roots": roots,
        "components": components,
        "_by_component": by_component,
    }


def diagnose_stream_rehearsal(
    rehearsal_snapshot: dict[str, Any],
    limits: RehearsalLimits,
    *,
    trace_snapshot: dict[str, Any] | None = None,
    trace_run_id: str | None = None,
    component_budgets_ms: dict[str, float] | None = None,
    max_diagnoses: int = 8,
) -> dict[str, Any]:
    """Create a bounded, read-only investigation plan for one rehearsal.

    If a trace is supplied, trace_run_id must exactly match the rehearsal
    run ID. This is a host-supplied correlation assertion, not cryptographic
    proof that the trace and rehearsal measurements came from the same session.
    The report therefore describes trace data as supporting observations, never
    as causal attribution.
    """
    if type(limits) is not RehearsalLimits:
        raise TypeError("limits must be RehearsalLimits")
    if type(max_diagnoses) is not int or not 1 <= max_diagnoses <= _MAX_DIAGNOSES:
        raise ValueError(f"max_diagnoses must be an integer in 1..{_MAX_DIAGNOSES}")
    budgets = _budget_map(component_budgets_ms)
    rehearsal = evaluate_rehearsal(rehearsal_snapshot, limits)
    run_id = rehearsal["run_id"]

    trace_report: dict[str, Any] | None = None
    component_index: dict[str, dict[str, Any]] = {}
    correlation = "not_supplied"
    if trace_snapshot is None and trace_run_id is not None:
        raise ValueError("trace_run_id cannot be supplied without a trace snapshot")
    if trace_snapshot is not None:
        if type(trace_run_id) is not str or not _RUN_ID.fullmatch(trace_run_id):
            raise ValueError("trace_run_id is required when a trace snapshot is supplied")
        if trace_run_id != run_id:
            raise ValueError("trace_run_id must match the rehearsal run_id")
        profile = profile_trace(trace_snapshot)
        trace_report = _trace_summary(profile, budgets)
        component_index = trace_report.pop("_by_component")
        correlation = "host_asserted_same_run"

    failures = [gate for gate in rehearsal["gates"] if gate["status"] == "FAIL"]
    inconclusive = [gate for gate in rehearsal["gates"] if gate["status"] == "INCONCLUSIVE"]
    diagnoses: list[dict[str, Any]] = []
    for gate in failures:
        name = gate["name"]
        mapped = _GATE_ROUTES[name]
        evidence = [
            component_index[component]
            for component in mapped
            if component in component_index
        ]
        evidence.sort(
            key=lambda item: (
                item["budget_status"] != "OVER_BUDGET",
                -(item["exclusive_p95_ms"] if item["exclusive_p95_ms"] is not None else -1.0),
                item["component"],
            )
        )
        if trace_report is None:
            evidence_status = "TRACE_NOT_SUPPLIED"
        elif not evidence:
            evidence_status = "MAPPED_COMPONENTS_NOT_INSTRUMENTED"
        else:
            evidence_status = "OBSERVED_NOT_CAUSAL"
        diagnoses.append({
            "gate": name,
            "priority": _GATE_PRIORITY[name],
            "observed": gate["observed"],
            "limit": gate["limit"],
            "comparator": gate["comparator"],
            "observations": gate["observations"],
            "evidence_status": evidence_status,
            "candidate_component_observations": evidence[:3],
            "next_experiment": _GATE_EXPERIMENTS[name],
        })

    diagnoses.sort(key=lambda item: (item["priority"], item["gate"]))
    evidence_gaps = [
        {
            "gate": gate["name"],
            "observations": gate["observations"],
            "required_observations": gate["required_observations"],
            "action": "collect_more_valid_observations",
        }
        for gate in inconclusive
    ]

    if failures:
        status = "ACTIONABLE_FAILURES"
    elif inconclusive:
        status = "INCONCLUSIVE"
    else:
        status = "CONFIGURED_GATES_PASS"

    notes = [
        "Investigation routes are hypotheses, not causal attribution.",
        "Component exclusive p95 values are per-component span distributions, not additive wall time.",
        "A trace/rehearsal run-ID match is host-asserted correlation, not cryptographic provenance.",
        "Missing or open trace spans are not assigned fabricated durations.",
        "Passing configured gates does not establish general intelligence, game mastery, or human-equivalent behavior.",
        "This report never changes models, scheduler settings, memory, audio, avatar, OBS, or game controls.",
    ]
    if trace_report is not None and trace_report["health"] != "COMPLETE":
        notes.append("Trace is incomplete; treat component observations as partial.")

    return {
        "schema_version": 1,
        "run_id": run_id,
        "status": status,
        "rehearsal_overall": rehearsal["overall"],
        "gate_results": rehearsal["gates"],
        "trace_correlation": correlation,
        "trace": trace_report,
        "diagnoses": diagnoses[:max_diagnoses],
        "evidence_gaps": evidence_gaps,
        "notes": notes,
    }


__all__ = ["diagnose_stream_rehearsal"]
