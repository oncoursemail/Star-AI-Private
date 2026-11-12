"""Offline acceptance scoring for a private STAR VTuber rehearsal.

The evaluator consumes only bounded aggregate measurements and produces
PASS/FAIL/INCONCLUSIVE gates. It never captures media, reads chat, controls
OBS/VTube Studio, changes scheduling, or authorizes gameplay/broadcast actions.
Thresholds are supplied by the operator because frame-rate and latency targets
depend on the game, encoder, audio device, and hardware.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, cast

_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_MAX_SAMPLES = 100_000
_MAX_COUNT = 1_000_000_000
_MAX_NUMBER = 1e12

_SERIES_FIELDS = (
    "first_content_latency_ms",
    "first_audible_latency_ms",
    "game_frame_time_ms",
    "avatar_sync_error_ms",
)
_COUNT_FIELDS = (
    "audio_underruns",
    "audio_playback_chunks",
    "obs_render_skipped_frames",
    "obs_render_total_frames",
    "obs_output_skipped_frames",
    "obs_output_total_frames",
    "turn_true_positives",
    "turn_false_positives",
    "turn_false_negatives",
    "task_recovery_attempts",
    "task_recovery_successes",
    "stale_task_resumes",
    "duplicate_speech_replays",
    "held_out_skill_trials",
    "held_out_skill_successes",
)
_REQUIRED_KEYS = frozenset({"schema_version", "run_id", *_SERIES_FIELDS, *_COUNT_FIELDS})
_RATE_LIMITS = frozenset({
    "max_audio_underrun_rate",
    "max_obs_render_skip_rate",
    "max_obs_output_skip_rate",
    "min_turn_precision",
    "min_turn_recall",
    "min_task_recovery_rate",
    "min_held_out_skill_transfer_rate",
})


def _number(value: object, label: str) -> float:
    """Convert exact JSON numeric primitives without accepting bool or strings."""
    if type(value) is int:
        result = float(cast(int, value))
    elif type(value) is float:
        result = cast(float, value)
    else:
        raise ValueError(f"{label} must be a finite nonnegative number")
    if not math.isfinite(result) or not 0 <= result <= _MAX_NUMBER:
        raise ValueError(f"{label} is outside the supported range")
    return result


def _count(value: object, label: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{label} must be a bounded nonnegative integer")
    result = cast(int, value)
    if not 0 <= result <= _MAX_COUNT:
        raise ValueError(f"{label} must be a bounded nonnegative integer")
    return result


def _series(value: object, label: str) -> list[float]:
    if type(value) is not list or len(value) > _MAX_SAMPLES:
        raise ValueError(f"{label} must be a bounded list")
    return [_number(sample, f"{label}[{index}]") for index, sample in enumerate(value)]


def _percentile(values: list[float], percentile: float) -> float | None:
    """Nearest-rank percentile; no interpolation or fabricated samples."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return round(ordered[rank - 1], 3)


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 6)


@dataclass(frozen=True)
class RehearsalLimits:
    """Operator-selected limits; None disables that individual gate.

    At least one gate must be configured. Rate limits are fractions in 0..1.
    The defaults intentionally do not encode a universal latency/FPS target.
    """

    min_observations: int = 20
    max_first_content_p95_ms: float | None = None
    max_first_audible_p95_ms: float | None = None
    max_game_frame_p99_ms: float | None = None
    max_avatar_sync_p95_ms: float | None = None
    max_audio_underrun_rate: float | None = None
    max_obs_render_skip_rate: float | None = None
    max_obs_output_skip_rate: float | None = None
    min_turn_precision: float | None = None
    min_turn_recall: float | None = None
    min_task_recovery_rate: float | None = None
    min_held_out_skill_transfer_rate: float | None = None
    max_stale_task_resumes: int | None = None
    max_duplicate_speech_replays: int | None = None

    def __post_init__(self) -> None:
        if type(self.min_observations) is not int or not 1 <= self.min_observations <= _MAX_SAMPLES:
            raise ValueError("min_observations must be an integer in 1..100000")
        configured = False
        for name in (
            "max_first_content_p95_ms",
            "max_first_audible_p95_ms",
            "max_game_frame_p99_ms",
            "max_avatar_sync_p95_ms",
            "max_audio_underrun_rate",
            "max_obs_render_skip_rate",
            "max_obs_output_skip_rate",
            "min_turn_precision",
            "min_turn_recall",
            "min_task_recovery_rate",
            "min_held_out_skill_transfer_rate",
        ):
            value = getattr(self, name)
            if value is None:
                continue
            configured = True
            number = _number(value, name)
            if name in _RATE_LIMITS and number > 1:
                raise ValueError(f"{name} must be in 0..1")
        for name in ("max_stale_task_resumes", "max_duplicate_speech_replays"):
            value = getattr(self, name)
            if value is not None:
                configured = True
                _count(value, name)
        if not configured:
            raise ValueError("at least one rehearsal gate must be configured")


def evaluate_rehearsal(
    snapshot: dict[str, Any],
    limits: RehearsalLimits,
) -> dict[str, Any]:
    """Evaluate one aggregate rehearsal snapshot without retaining raw samples.

    Missing or insufficient evidence is INCONCLUSIVE, never a passing zero.
    An observed failure makes the overall result FAIL; otherwise any
    inconclusive configured gate makes the overall result INCONCLUSIVE.
    """
    if type(limits) is not RehearsalLimits:
        raise TypeError("limits must be RehearsalLimits")
    if type(snapshot) is not dict or set(snapshot) != _REQUIRED_KEYS:
        raise ValueError("snapshot must contain exactly the documented aggregate fields")
    if type(snapshot.get("schema_version")) is not int or snapshot["schema_version"] != 1:
        raise ValueError("unsupported rehearsal snapshot schema")
    run_id = snapshot.get("run_id")
    if type(run_id) is not str or not _RUN_ID.fullmatch(run_id):
        raise ValueError("run_id must be a bounded opaque identifier")

    samples = {name: _series(snapshot[name], name) for name in _SERIES_FIELDS}
    counts = {name: _count(snapshot[name], name) for name in _COUNT_FIELDS}

    if counts["audio_underruns"] > counts["audio_playback_chunks"]:
        raise ValueError("audio underruns cannot exceed playback chunks")
    if counts["obs_render_skipped_frames"] > counts["obs_render_total_frames"]:
        raise ValueError("OBS render skips cannot exceed render frames")
    if counts["obs_output_skipped_frames"] > counts["obs_output_total_frames"]:
        raise ValueError("OBS output skips cannot exceed output frames")
    if counts["task_recovery_successes"] > counts["task_recovery_attempts"]:
        raise ValueError("task recovery successes cannot exceed attempts")
    if counts["held_out_skill_successes"] > counts["held_out_skill_trials"]:
        raise ValueError("held-out skill successes cannot exceed trials")

    tp = counts["turn_true_positives"]
    fp = counts["turn_false_positives"]
    fn = counts["turn_false_negatives"]
    turn_precision_n = tp + fp
    turn_recall_n = tp + fn
    recovery_n = counts["task_recovery_attempts"]
    transfer_n = counts["held_out_skill_trials"]
    audio_n = counts["audio_playback_chunks"]
    render_n = counts["obs_render_total_frames"]
    output_n = counts["obs_output_total_frames"]

    metrics: dict[str, Any] = {
        "first_content_p95_ms": _percentile(samples["first_content_latency_ms"], 0.95),
        "first_audible_p95_ms": _percentile(samples["first_audible_latency_ms"], 0.95),
        "game_frame_p99_ms": _percentile(samples["game_frame_time_ms"], 0.99),
        "avatar_sync_p95_ms": _percentile(samples["avatar_sync_error_ms"], 0.95),
        "audio_underrun_rate": _rate(counts["audio_underruns"], audio_n),
        "obs_render_skip_rate": _rate(counts["obs_render_skipped_frames"], render_n),
        "obs_output_skip_rate": _rate(counts["obs_output_skipped_frames"], output_n),
        "turn_precision": _rate(tp, turn_precision_n),
        "turn_recall": _rate(tp, turn_recall_n),
        "task_recovery_rate": _rate(counts["task_recovery_successes"], recovery_n),
        "held_out_skill_transfer_rate": _rate(counts["held_out_skill_successes"], transfer_n),
        "counts": counts,
        "sample_counts": {name: len(values) for name, values in samples.items()},
    }

    gates: list[dict[str, Any]] = []

    def add_gate(
        name: str,
        observed: float | int | None,
        limit: float | int | None,
        *,
        direction: str,
        observations: int,
        minimum: int,
    ) -> None:
        if limit is None:
            return
        if observed is None or observations < minimum:
            status = "INCONCLUSIVE"
        elif direction == "max":
            status = "PASS" if observed <= limit else "FAIL"
        else:
            status = "PASS" if observed >= limit else "FAIL"
        gates.append({
            "name": name,
            "status": status,
            "observed": observed,
            "comparator": "<=" if direction == "max" else ">=",
            "limit": limit,
            "observations": observations,
            "required_observations": minimum,
        })

    min_n = limits.min_observations
    add_gate("first_content_p95_ms", metrics["first_content_p95_ms"],
             limits.max_first_content_p95_ms, direction="max",
             observations=len(samples["first_content_latency_ms"]), minimum=min_n)
    add_gate("first_audible_p95_ms", metrics["first_audible_p95_ms"],
             limits.max_first_audible_p95_ms, direction="max",
             observations=len(samples["first_audible_latency_ms"]), minimum=min_n)
    add_gate("game_frame_p99_ms", metrics["game_frame_p99_ms"],
             limits.max_game_frame_p99_ms, direction="max",
             observations=len(samples["game_frame_time_ms"]), minimum=min_n)
    add_gate("avatar_sync_p95_ms", metrics["avatar_sync_p95_ms"],
             limits.max_avatar_sync_p95_ms, direction="max",
             observations=len(samples["avatar_sync_error_ms"]), minimum=min_n)
    add_gate("audio_underrun_rate", metrics["audio_underrun_rate"],
             limits.max_audio_underrun_rate, direction="max",
             observations=audio_n, minimum=min_n)
    add_gate("obs_render_skip_rate", metrics["obs_render_skip_rate"],
             limits.max_obs_render_skip_rate, direction="max",
             observations=render_n, minimum=min_n)
    add_gate("obs_output_skip_rate", metrics["obs_output_skip_rate"],
             limits.max_obs_output_skip_rate, direction="max",
             observations=output_n, minimum=min_n)
    add_gate("turn_precision", metrics["turn_precision"],
             limits.min_turn_precision, direction="min",
             observations=turn_precision_n, minimum=min_n)
    add_gate("turn_recall", metrics["turn_recall"],
             limits.min_turn_recall, direction="min",
             observations=turn_recall_n, minimum=min_n)
    add_gate("task_recovery_rate", metrics["task_recovery_rate"],
             limits.min_task_recovery_rate, direction="min",
             observations=recovery_n, minimum=min_n)
    add_gate("held_out_skill_transfer_rate", metrics["held_out_skill_transfer_rate"],
             limits.min_held_out_skill_transfer_rate, direction="min",
             observations=transfer_n, minimum=min_n)
    add_gate("stale_task_resumes", counts["stale_task_resumes"],
             limits.max_stale_task_resumes, direction="max",
             observations=recovery_n, minimum=1)
    add_gate("duplicate_speech_replays", counts["duplicate_speech_replays"],
             limits.max_duplicate_speech_replays, direction="max",
             observations=audio_n, minimum=1)

    if not gates:
        raise ValueError("no configured rehearsal gates were evaluated")
    statuses = {gate["status"] for gate in gates}
    overall = "FAIL" if "FAIL" in statuses else (
        "INCONCLUSIVE" if "INCONCLUSIVE" in statuses else "PASS"
    )
    return {
        "schema_version": 1,
        "run_id": run_id,
        "overall": overall,
        "metrics": metrics,
        "gates": gates,
        "notes": [
            "Percentiles use nearest-rank over the supplied samples.",
            "API first-content latency is not first-audible latency.",
            "OBS render skips and output skips are separate loss channels.",
            "Turn precision/recall require human-labeled or otherwise trusted outcomes.",
            "Held-out skill transfer is not training-set practice success.",
            "A PASS applies only to configured limits and supplied observations.",
            "No raw chat, transcript, audio, video, screenshot, viewer identity, or prompt is retained.",
        ],
    }


__all__ = ["RehearsalLimits", "evaluate_rehearsal"]
