"""Offline, per-language calibration for semantic end-of-turn policies.

This module consumes metadata-only score timelines exported by a trusted host
adapter. It never reads audio, transcripts, speaker identities, or chat content.
Thresholds are selected on a calibration split and must pass an independent
conversation-level holdout split before a manual-review recommendation is emitted.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from statistics import NormalDist
from typing import Iterable, Mapping, Sequence

_SCHEMA_VERSION = 1
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+-]{0,79}\Z")
_LANGUAGE = re.compile(r"(?:[a-z]{2,3}|[a-z]{2,3}-[A-Z]{2}|und)\Z")
_GROUP_ID = re.compile(r"[a-f0-9]{20,64}\Z")
_ALLOWED_TRIAL_KEYS = frozenset({
    "example_id", "conversation_group", "model_id", "language", "split",
    "is_turn_end", "reference_ms", "resume_ms", "observations",
})
_ALLOWED_OBSERVATION_KEYS = frozenset({"at_ms", "end_probability"})
MAX_INPUT_BYTES = 50 * 1024 * 1024
MAX_TRIALS = 200_000
MAX_LINE_BYTES = 8192
MAX_OBSERVATIONS_PER_TRIAL = 2048


def _number(
    value: object, label: str, *, minimum: float = 0.0, maximum: float = 1e12,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite number")
    result = float(value)
    if not math.isfinite(result) or result < minimum or result > maximum:
        raise ValueError(f"{label} is outside its supported range")
    return result


def _label(value: object, name: str) -> str:
    if type(value) is not str or _LABEL.fullmatch(value) is None:
        raise ValueError(f"{name} must be a short opaque identifier")
    return value


@dataclass(frozen=True)
class ScoreObservation:
    """One end-of-turn score sampled at a host-monotonic timestamp."""

    at_ms: float
    end_probability: float

    def __post_init__(self) -> None:
        _number(self.at_ms, "observation.at_ms")
        _number(self.end_probability, "observation.end_probability", maximum=1.0)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "ScoreObservation":
        if not isinstance(value, Mapping):
            raise TypeError("score observation must be an object")
        if set(value) != _ALLOWED_OBSERVATION_KEYS:
            raise ValueError("score observation has missing or unsupported fields")
        return cls(**dict(value))  # type: ignore[arg-type]


@dataclass(frozen=True)
class EOTTrial:
    """One independently labeled final-turn or mid-turn pause opportunity.

    For a true turn end, reference_ms is the independently annotated end
    of speech. For a mid-turn pause, it is the pause start and resume_ms is
    when the speaker resumes. The policy commits at the first observation whose
    end probability reaches the candidate threshold. A mid-turn cutoff is false
    only when that first crossing occurs before the speaker resumes.

    conversation_group is one stable, opaque 20..64-character digest for
    every example from the same conversation. It is used only to prevent the
    same conversation from leaking across calibration and holdout splits.
    All timestamps must already share one host-monotonic clock.
    """

    example_id: str
    conversation_group: str
    model_id: str
    language: str
    split: str
    is_turn_end: bool
    reference_ms: float
    resume_ms: float | None
    observations: tuple[ScoreObservation, ...]

    def __post_init__(self) -> None:
        _label(self.example_id, "example_id")
        if type(self.conversation_group) is not str or _GROUP_ID.fullmatch(self.conversation_group) is None:
            raise ValueError("conversation_group must be a 20..64 character lowercase hex digest")
        _label(self.model_id, "model_id")
        if type(self.language) is not str or _LANGUAGE.fullmatch(self.language) is None:
            raise ValueError("language must be a short BCP-47 tag or und")
        if type(self.split) is not str or self.split not in {"calibration", "holdout"}:
            raise ValueError("split must be calibration or holdout")
        if type(self.is_turn_end) is not bool:
            raise ValueError("is_turn_end must be boolean")
        reference = _number(self.reference_ms, "reference_ms")
        if self.is_turn_end:
            if self.resume_ms is not None:
                raise ValueError("true turn-end trials must not have resume_ms")
        else:
            if self.resume_ms is None:
                raise ValueError("mid-turn pause trials require resume_ms")
            resume = _number(self.resume_ms, "resume_ms")
            if resume <= reference:
                raise ValueError("resume_ms must be after the mid-turn pause start")
        if type(self.observations) is not tuple:
            raise ValueError("observations must be an immutable tuple")
        if len(self.observations) > MAX_OBSERVATIONS_PER_TRIAL:
            raise ValueError("trial exceeds the observation count limit")
        previous_at = -1.0
        for observation in self.observations:
            if not isinstance(observation, ScoreObservation):
                raise TypeError("observations must contain validated ScoreObservation values")
            if observation.at_ms < reference:
                raise ValueError("score observations cannot precede the reference timestamp")
            if observation.at_ms <= previous_at:
                raise ValueError("score observation timestamps must be strictly increasing")
            previous_at = observation.at_ms

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "EOTTrial":
        if not isinstance(value, Mapping):
            raise TypeError("trial record must be an object")
        if set(value) != _ALLOWED_TRIAL_KEYS:
            raise ValueError("trial record has missing or unsupported fields")
        raw_observations = value["observations"]
        if type(raw_observations) not in {list, tuple}:
            raise ValueError("observations must be a list")
        observations = tuple(ScoreObservation.from_mapping(item) for item in raw_observations)
        fields = dict(value)
        fields["observations"] = observations
        return cls(**fields)  # type: ignore[arg-type]


@dataclass(frozen=True)
class CalibrationConfig:
    """Conservative operating-point selection constraints."""

    thresholds: tuple[float, ...] = (0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90)
    false_cutoff_budget: float = 0.05
    missed_turn_budget: float = 0.10
    max_response_delay_ms: float = 2500.0
    confidence_level: float = 0.95
    minimum_positive_conversations: int = 100
    minimum_negative_conversations: int = 100

    def __post_init__(self) -> None:
        if type(self.thresholds) is not tuple or not self.thresholds or len(self.thresholds) > 101:
            raise ValueError("thresholds must be a tuple containing 1..101 values")
        normalized = tuple(_number(item, "threshold", maximum=1.0) for item in self.thresholds)
        if tuple(sorted(set(normalized))) != normalized:
            raise ValueError("thresholds must be strictly increasing and unique")
        for name in ("false_cutoff_budget", "missed_turn_budget"):
            _number(getattr(self, name), name, maximum=1.0)
        confidence = _number(self.confidence_level, "confidence_level", maximum=1.0)
        if not 0.5 < confidence < 1.0:
            raise ValueError("confidence_level must be between 0.5 and 1")
        _number(self.max_response_delay_ms, "max_response_delay_ms", maximum=60000.0)
        for name in ("minimum_positive_conversations", "minimum_negative_conversations"):
            value = getattr(self, name)
            if type(value) is not int or not 1 <= value <= 1_000_000:
                raise ValueError(f"{name} must be a positive bounded integer")


def _wilson_upper(errors: int, total: int, confidence_level: float) -> float:
    """One-sided Wilson upper confidence bound for a binomial error rate."""
    if total <= 0:
        return 1.0
    if not 0 <= errors <= total:
        raise ValueError("errors must be between zero and total")
    z = NormalDist().inv_cdf(confidence_level)
    rate = errors / total
    z2 = z * z
    denominator = 1.0 + z2 / total
    center = rate + z2 / (2.0 * total)
    margin = z * math.sqrt(rate * (1.0 - rate) / total + z2 / (4.0 * total * total))
    return min(1.0, (center + margin) / denominator)


def _percentile(values: Sequence[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    # Nearest-rank percentile: deterministic and conservative for small samples.
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 3)


def _first_crossing(trial: EOTTrial, threshold: float) -> ScoreObservation | None:
    return next(
        (item for item in trial.observations if item.end_probability >= threshold),
        None,
    )


def evaluate_threshold(
    trials: Sequence[EOTTrial], threshold: float, config: CalibrationConfig,
) -> dict[str, object]:
    """Evaluate first threshold crossings and cluster confidence by conversation."""
    threshold = _number(threshold, "threshold", maximum=1.0)
    positives = [trial for trial in trials if trial.is_turn_end]
    negatives = [trial for trial in trials if not trial.is_turn_end]
    false_cutoffs = 0
    missed_turns = 0
    latencies: list[float] = []
    positive_groups: set[str] = set()
    negative_groups: set[str] = set()
    missed_groups: set[str] = set()
    false_cutoff_groups: set[str] = set()

    for trial in positives:
        positive_groups.add(trial.conversation_group)
        crossing = _first_crossing(trial, threshold)
        if crossing is None:
            missed_turns += 1
            missed_groups.add(trial.conversation_group)
            continue
        latency = crossing.at_ms - trial.reference_ms
        if latency > config.max_response_delay_ms:
            missed_turns += 1
            missed_groups.add(trial.conversation_group)
        else:
            latencies.append(latency)

    for trial in negatives:
        negative_groups.add(trial.conversation_group)
        crossing = _first_crossing(trial, threshold)
        if crossing is not None and trial.resume_ms is not None and crossing.at_ms < trial.resume_ms:
            false_cutoffs += 1
            false_cutoff_groups.add(trial.conversation_group)

    positive_count = len(positives)
    negative_count = len(negatives)
    missed_rate = missed_turns / positive_count if positive_count else 1.0
    false_rate = false_cutoffs / negative_count if negative_count else 1.0
    positive_conversation_count = len(positive_groups)
    negative_conversation_count = len(negative_groups)
    return {
        "threshold": threshold,
        "positive_examples": positive_count,
        "negative_examples": negative_count,
        "positive_conversations": positive_conversation_count,
        "negative_conversations": negative_conversation_count,
        "false_cutoffs": false_cutoffs,
        "false_cutoff_rate": round(false_rate, 6),
        "false_cutoff_conversation_failures": len(false_cutoff_groups),
        "false_cutoff_conversation_rate": round(
            len(false_cutoff_groups) / negative_conversation_count, 6
        ) if negative_conversation_count else 1.0,
        "false_cutoff_upper_confidence": round(
            _wilson_upper(len(false_cutoff_groups), negative_conversation_count,
                          config.confidence_level), 6
        ),
        "missed_turns": missed_turns,
        "missed_turn_rate": round(missed_rate, 6),
        "missed_turn_conversation_failures": len(missed_groups),
        "missed_turn_conversation_rate": round(
            len(missed_groups) / positive_conversation_count, 6
        ) if positive_conversation_count else 1.0,
        "missed_turn_upper_confidence": round(
            _wilson_upper(len(missed_groups), positive_conversation_count,
                          config.confidence_level), 6
        ),
        "recognized_turns": len(latencies),
        "median_response_delay_ms": _percentile(latencies, 0.50),
        "p95_response_delay_ms": _percentile(latencies, 0.95),
    }


def calibrate_end_of_turn(
    trials: Iterable[EOTTrial | Mapping[str, object]],
    config: CalibrationConfig | None = None,
) -> dict[str, object]:
    """Select per-model/per-language thresholds on calibration data only.

    A threshold is recommended for manual review only when both calibration
    and untouched holdout cohorts satisfy sample-count, false-cutoff and
    missed-turn constraints using one-sided Wilson upper bounds.
    """
    cfg = config or CalibrationConfig()
    parsed: list[EOTTrial] = []
    seen: set[tuple[str, str, str, str]] = set()
    group_splits: dict[str, str] = {}
    for raw in trials:
        trial = raw if isinstance(raw, EOTTrial) else EOTTrial.from_mapping(raw)
        previous_split = group_splits.setdefault(trial.conversation_group, trial.split)
        if previous_split != trial.split:
            raise ValueError("conversation group appears in both calibration and holdout splits")
        key = (trial.model_id, trial.language, trial.split, trial.example_id)
        if key in seen:
            raise ValueError("duplicate example in the same model/language/split cohort")
        seen.add(key)
        parsed.append(trial)
        if len(parsed) > MAX_TRIALS:
            raise ValueError("input exceeds the 200,000 trial limit")
    if not parsed:
        raise ValueError("at least one labeled trial is required")

    groups = sorted({(item.model_id, item.language) for item in parsed})
    reports: list[dict[str, object]] = []
    for model_id, language in groups:
        calibration = [
            item for item in parsed
            if item.model_id == model_id and item.language == language
            and item.split == "calibration"
        ]
        holdout = [
            item for item in parsed
            if item.model_id == model_id and item.language == language
            and item.split == "holdout"
        ]
        calibration_pos = len({item.conversation_group for item in calibration if item.is_turn_end})
        calibration_neg = len({item.conversation_group for item in calibration if not item.is_turn_end})
        holdout_pos = len({item.conversation_group for item in holdout if item.is_turn_end})
        holdout_neg = len({item.conversation_group for item in holdout if not item.is_turn_end})
        base = {
            "model_id": model_id,
            "language": language,
            "calibration_examples": len(calibration),
            "holdout_examples": len(holdout),
        }
        if (calibration_pos < cfg.minimum_positive_conversations
                or calibration_neg < cfg.minimum_negative_conversations):
            reports.append({
                **base,
                "status": "inconclusive_calibration_sample_size",
                "selected_threshold": None,
                "required_calibration_positive_conversations": cfg.minimum_positive_conversations,
                "required_calibration_negative_conversations": cfg.minimum_negative_conversations,
            })
            continue

        sweep = [evaluate_threshold(calibration, threshold, cfg) for threshold in cfg.thresholds]
        feasible = [
            item for item in sweep
            if item["false_cutoff_upper_confidence"] <= cfg.false_cutoff_budget
            and item["missed_turn_upper_confidence"] <= cfg.missed_turn_budget
            and item["p95_response_delay_ms"] is not None
        ]
        if not feasible:
            reports.append({
                **base,
                "status": "no_calibration_operating_point",
                "selected_threshold": None,
                "threshold_sweep": sweep,
            })
            continue
        selected = min(
            feasible,
            key=lambda item: (
                item["p95_response_delay_ms"],
                item["median_response_delay_ms"],
                -item["threshold"],
            ),
        )
        candidate_threshold = float(selected["threshold"])
        if (holdout_pos < cfg.minimum_positive_conversations
                or holdout_neg < cfg.minimum_negative_conversations):
            reports.append({
                **base,
                "status": "inconclusive_holdout_sample_size",
                "selected_threshold": None,
                "candidate_threshold": candidate_threshold,
                "calibration_operating_point": selected,
                "required_holdout_positive_conversations": cfg.minimum_positive_conversations,
                "required_holdout_negative_conversations": cfg.minimum_negative_conversations,
            })
            continue
        holdout_result = evaluate_threshold(holdout, candidate_threshold, cfg)
        holdout_pass = (
            holdout_result["false_cutoff_upper_confidence"] <= cfg.false_cutoff_budget
            and holdout_result["missed_turn_upper_confidence"] <= cfg.missed_turn_budget
            and holdout_result["p95_response_delay_ms"] is not None
        )
        reports.append({
            **base,
            "status": "manual_review_recommended" if holdout_pass else "holdout_failed",
            "selected_threshold": candidate_threshold if holdout_pass else None,
            "candidate_threshold": candidate_threshold,
            "calibration_operating_point": selected,
            "holdout_result": holdout_result,
        })

    return {
        "schema_version": _SCHEMA_VERSION,
        "method": "first_crossing_threshold_sweep_with_conversation_holdout",
        "policy": {
            "false_cutoff_budget": cfg.false_cutoff_budget,
            "missed_turn_budget": cfg.missed_turn_budget,
            "max_response_delay_ms": cfg.max_response_delay_ms,
            "confidence_level": cfg.confidence_level,
            "minimum_positive_conversations_per_split": cfg.minimum_positive_conversations,
            "minimum_negative_conversations_per_split": cfg.minimum_negative_conversations,
            "thresholds": list(cfg.thresholds),
        },
        "groups": reports,
        "raw_examples_included": False,
        "media_or_transcripts_included": False,
        "automatic_runtime_changes": False,
    }


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSONL record contains a duplicate key")
        result[key] = value
    return result


def _load_jsonl(path: Path) -> list[EOTTrial]:
    if not path.is_file():
        raise ValueError("input path must be an existing regular file")
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("input file exceeds the 50 MiB safety limit")
    records: list[EOTTrial] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if len(line.encode("utf-8")) > MAX_LINE_BYTES:
                raise ValueError(f"line {line_number} exceeds the record size limit")
            if not line.strip():
                continue
            try:
                raw = json.loads(line, object_pairs_hook=_unique_json_object)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_number} is not valid JSON") from exc
            records.append(EOTTrial.from_mapping(raw))
            if len(records) > MAX_TRIALS:
                raise ValueError("input exceeds the 200,000 trial limit")
    if not records:
        raise ValueError("input contains no trial records")
    return records


def main(argv: Sequence[str] | None = None) -> int:
    """Run the metadata-only JSONL calibration CLI."""
    parser = argparse.ArgumentParser(
        description="Calibrate end-of-turn thresholds using conversation-separated JSONL splits."
    )
    parser.add_argument("input", type=Path, help="metadata-only EOT score-timeline JSONL")
    parser.add_argument("--output", type=Path, help="write the aggregate report to this path")
    parser.add_argument("--force", action="store_true", help="replace an existing output file")
    parser.add_argument("--thresholds", default="0.30,0.40,0.50,0.60,0.70,0.80,0.90")
    parser.add_argument("--false-cutoff-budget", type=float, default=0.05)
    parser.add_argument("--missed-turn-budget", type=float, default=0.10)
    parser.add_argument("--max-response-delay-ms", type=float, default=2500.0)
    parser.add_argument("--confidence-level", type=float, default=0.95)
    parser.add_argument("--min-positive-conversations", type=int, default=100)
    parser.add_argument("--min-negative-conversations", type=int, default=100)
    args = parser.parse_args(argv)
    try:
        thresholds = tuple(float(item.strip()) for item in args.thresholds.split(","))
        config = CalibrationConfig(
            thresholds=thresholds,
            false_cutoff_budget=args.false_cutoff_budget,
            missed_turn_budget=args.missed_turn_budget,
            max_response_delay_ms=args.max_response_delay_ms,
            confidence_level=args.confidence_level,
            minimum_positive_conversations=args.min_positive_conversations,
            minimum_negative_conversations=args.min_negative_conversations,
        )
        trials = _load_jsonl(args.input)
        report = calibrate_end_of_turn(trials, config)
        payload = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output is None:
            sys.stdout.write(payload)
            return 0
        if args.output.resolve() == args.input.resolve():
            raise ValueError("output path must not replace the input file")
        if args.output.exists() and not args.force:
            raise ValueError("output file already exists; pass --force to replace it")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=args.output.parent,
            prefix=f".{args.output.name}.", suffix=".tmp", delete=False,
        ) as temporary:
            temporary.write(payload)
            temporary_path = Path(temporary.name)
        try:
            if args.force:
                os.replace(temporary_path, args.output)
            else:
                # Hard-link creation is atomic and fails if another process won the race.
                os.link(temporary_path, args.output)
                temporary_path.unlink()
        finally:
            if temporary_path.exists():
                temporary_path.unlink()
        return 0
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"eot calibration: {exc}", file=sys.stderr)
        return 2


__all__ = [
    "ScoreObservation", "EOTTrial", "CalibrationConfig", "evaluate_threshold",
    "calibrate_end_of_turn", "main",
]

if __name__ == "__main__":
    raise SystemExit(main())
