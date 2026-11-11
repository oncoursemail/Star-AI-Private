"""Explicit, privacy-safe bridges from existing STAR subsystems into AgentTrace.

These adapters record bounded aggregate facts only. They do not install hooks,
poll devices, perform network I/O, retain source payloads, or authorize actions.
Call them from trusted host code after the corresponding subsystem has produced
a validated result. Never call them from an audio callback or render thread.
"""
from __future__ import annotations

from collections.abc import Mapping
import time
from typing import Any, Callable

from .agent_trace import AgentTrace, TraceContext
from .llama_metrics import LlamaCppMetricsDelta
from .stream_director import SpeechIntent
from .stream_hardware_telemetry import HardwareSnapshot


_STREAM_COUNTERS = frozenset({
    "accepted", "rejected", "expired", "evicted",
    "completed", "abandoned", "queued",
})
_GAME_COUNTERS = frozenset({"sessions", "episodes", "state_actions"})


def _bounded_counts(
    values: Mapping[str, object],
    expected: frozenset[str],
    label: str,
) -> dict[str, int]:
    if not isinstance(values, Mapping) or set(values) != expected:
        raise ValueError(f"{label} must contain exactly the documented aggregate counters")
    result: dict[str, int] = {}
    for key in expected:
        value = values[key]
        if type(value) is not int or not 0 <= value <= 1_000_000_000:
            raise ValueError(f"{label}.{key} must be a bounded nonnegative integer")
        result[key] = value
    return result


class AgentTraceAdapters:
    """Small explicit bridge for existing inference, stream, host and learning APIs.

    The default clock is the current process monotonic clock. If an adapter is
    called from another process, supply that process's monotonic clock and a
    trace context created from the received W3C traceparent; do not compare raw
    monotonic timestamps across machines.
    """

    def __init__(
        self,
        trace: AgentTrace,
        *,
        clock_ms: Callable[[], float] | None = None,
    ) -> None:
        if not isinstance(trace, AgentTrace):
            raise TypeError("trace must be an AgentTrace")
        if clock_ms is not None and not callable(clock_ms):
            raise TypeError("clock_ms must be callable")
        self._trace = trace
        self._clock_ms = clock_ms if clock_ms is not None else (
            lambda: time.monotonic_ns() / 1_000_000
        )

    def _record(
        self,
        event: str,
        attributes: dict[str, Any],
        span: TraceContext | None,
    ) -> int:
        return self._trace.add_event(
            event,
            at_ms=self._clock_ms(),
            span=span,
            attributes=attributes,
        )

    def record_llama_delta(
        self,
        delta: LlamaCppMetricsDelta,
        *,
        span: TraceContext | None = None,
    ) -> int:
        """Attach one interval sample; server-wide rates are not per-request latency."""
        if type(delta) is not LlamaCppMetricsDelta:
            raise TypeError("delta must be a LlamaCppMetricsDelta")
        attributes: dict[str, Any] = {"elapsed_ms": delta.elapsed_ms}
        optional = {
            "prompt_tokens_per_second": delta.prompt_tokens_per_second,
            "generation_tokens_per_second": delta.generated_tokens_per_second,
            "requests_processing": delta.requests_processing,
            "requests_deferred": delta.requests_deferred,
            "busy_slots_per_decode": delta.busy_slots_per_decode,
            "speculative_acceptance_percent": delta.speculative_draft_acceptance_percent,
            "speculative_tokens_per_step": delta.speculative_accepted_tokens_per_step,
        }
        attributes.update({key: value for key, value in optional.items() if value is not None})
        attributes["counter_reset_count"] = len(delta.counter_resets)
        attributes["anomaly_count"] = len(delta.anomalies)
        return self._record("inference_sampled", attributes, span)

    def record_hardware_snapshot(
        self,
        snapshot: HardwareSnapshot,
        *,
        span: TraceContext | None = None,
    ) -> int:
        """Record aggregate resource state from the trusted hardware sampler."""
        if type(snapshot) is not HardwareSnapshot:
            raise TypeError("snapshot must be a HardwareSnapshot")
        if snapshot.free_vram_mib > snapshot.total_vram_mib:
            raise ValueError("free VRAM cannot exceed total VRAM")
        attributes: dict[str, Any] = {
            "gpu_memory_mib": snapshot.total_vram_mib - snapshot.free_vram_mib,
            "total_vram_mib": snapshot.total_vram_mib,
            "free_vram_mib": snapshot.free_vram_mib,
            "free_ram_mib": snapshot.free_ram_mib,
        }
        if snapshot.cpu_busy_percent is not None:
            attributes["cpu_busy_percent"] = snapshot.cpu_busy_percent
        return self._record("hardware_sampled", attributes, span)

    def record_stream_director_metrics(
        self,
        metrics: Mapping[str, object],
        *,
        span: TraceContext | None = None,
    ) -> int:
        """Record only StreamDirector.metrics() counters, never signal contents or speaker IDs."""
        counts = _bounded_counts(metrics, _STREAM_COUNTERS, "stream metrics")
        attributes = {
            "stream_accepted": counts["accepted"],
            "stream_rejected": counts["rejected"],
            "stream_expired": counts["expired"],
            "stream_evicted": counts["evicted"],
            "stream_completed": counts["completed"],
            "stream_abandoned": counts["abandoned"],
            "stream_queued": counts["queued"],
        }
        return self._record("stream_director_sampled", attributes, span)

    def record_speech_intent(
        self,
        intent: SpeechIntent,
        *,
        span: TraceContext | None = None,
    ) -> int:
        """Record decision shape only; omit signal ID, speaker, and untrusted context."""
        if type(intent) is not SpeechIntent:
            raise TypeError("intent must be a SpeechIntent")
        attributes = {
            "speech_kind": intent.kind,
            "interrupted": intent.interrupt_current,
            "untrusted_context": intent.untrusted_context,
        }
        return self._record("speech_proposed", attributes, span)

    def record_speech_completion(
        self,
        *,
        spoken: bool,
        interrupted: bool = False,
        span: TraceContext | None = None,
    ) -> int:
        """Record whether a proposed utterance reached the host's completion point."""
        if type(spoken) is not bool or type(interrupted) is not bool:
            raise TypeError("spoken and interrupted must be explicit booleans")
        return self._record(
            "speech_completed",
            {
                "outcome": "success" if spoken else "cancelled",
                "interrupted": interrupted,
            },
            span,
        )

    def record_game_learning_summary(
        self,
        summary: Mapping[str, object],
        *,
        span: TraceContext | None = None,
    ) -> int:
        """Attach GameSkillMemory.summary() aggregate counts, not episode payloads."""
        counts = _bounded_counts(summary, _GAME_COUNTERS, "game learning summary")
        return self._record(
            "game_learning_sampled",
            {
                "learning_sessions": counts["sessions"],
                "learning_episodes": counts["episodes"],
                "learning_state_actions": counts["state_actions"],
            },
            span,
        )

    def record_checkpoint_progress(
        self,
        completed_steps: int,
        *,
        span: TraceContext | None = None,
    ) -> int:
        """Record only len(StepCheckpoint); never expose scope, keys or step results."""
        if type(completed_steps) is not int or not 0 <= completed_steps <= 1_000_000_000:
            raise ValueError("completed_steps must be a bounded nonnegative integer")
        return self._record(
            "task_checkpoint_sampled",
            {"checkpoint_steps": completed_steps},
            span,
        )


__all__ = ["AgentTraceAdapters"]
