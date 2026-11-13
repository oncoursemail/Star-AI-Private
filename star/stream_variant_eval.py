"""Paired, signed A/B evaluation for STAR's mixed realtime workloads.

The evaluator compares two pinned STAR revisions on the same preregistered
cases and host environment. It consumes only opaque IDs, independent outcomes,
bounded numeric measurements, and HMAC receipts. It never runs models, captures
media, controls games/OBS/VTube Studio, or promotes a candidate automatically.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import hmac
import json
import math
import re
from statistics import median
from typing import Sequence

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_DOMAIN = b"star.stream-variant-trial.v1\x00"
_MAX_CASES = 512
_MAX_TRIALS = 1024
_MAX_AGE_S = 30 * 86400
_MAX_MS = 300_000
_MAX_RATE = 1.0
_MAX_COUNTER = 1_000_000_000
_MAX_MIB = 1_000_000_000
_MAX_TPS = 1_000_000.0
_DOMAINS = frozenset({"voice", "gaming", "creator", "knowledge", "mixed"})
_SPLITS = frozenset({"development", "holdout"})
_VARIANTS = frozenset({"baseline", "candidate"})
_STATUSES = frozenset({"completed", "error"})
_DIMENSIONS = frozenset({
    "turn_taking",
    "groundedness",
    "held_out_skill",
    "game_completion",
})
_METRICS = frozenset({
    "first_content_ms",
    "first_audible_ms",
    "game_frame_p99_ms",
    "audio_underrun_rate",
    "obs_output_skip_rate",
    "peak_cpu_millicores",
    "peak_ram_mib",
    "peak_vram_mib",
    "tokens_per_second",
    "memory_tokens",
})
_LOWER_IS_BETTER = frozenset({
    "first_content_ms",
    "first_audible_ms",
    "game_frame_p99_ms",
    "audio_underrun_rate",
    "obs_output_skip_rate",
    "peak_cpu_millicores",
    "peak_ram_mib",
    "peak_vram_mib",
    "memory_tokens",
})


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"{label} must be a bounded opaque identifier")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or not _SHA.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _finite(value: object, label: str, maximum: float) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be a finite nonnegative number")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{label} is outside the supported range") from exc
    if not math.isfinite(number) or not 0 <= number <= maximum:
        raise ValueError(f"{label} is outside the supported range")
    return number


def _bounded_int(value: object, label: str, maximum: int) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"{label} must be a bounded nonnegative integer")
    return value


def _one_sided_p(wins: int, losses: int) -> float:
    """Exact one-sided paired sign/McNemar probability."""
    n = wins + losses
    if n == 0:
        return 1.0
    return sum(math.comb(n, k) for k in range(wins, n + 1)) / (1 << n)


def _rate(successes: int, trials: int) -> float | None:
    return None if trials == 0 else round(successes / trials, 6)


def _nearest_rank(values: Sequence[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(quantile * len(ordered)))
    return round(ordered[rank - 1], 3)


@dataclass(frozen=True)
class StreamCase:
    """One preregistered case; scenario text and answer keys stay host-side."""

    case_id: str
    domain: str
    split: str
    required_dimensions: tuple[str, ...] = ()
    required_metrics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _identifier(self.case_id, "case_id")
        if type(self.domain) is not str or self.domain not in _DOMAINS:
            raise ValueError("domain must be one of voice, gaming, creator, knowledge, mixed")
        if type(self.split) is not str or self.split not in _SPLITS:
            raise ValueError("split must be development or holdout")
        for name, values, allowed in (
            ("required_dimensions", self.required_dimensions, _DIMENSIONS),
            ("required_metrics", self.required_metrics, _METRICS),
        ):
            if type(values) is not tuple or len(values) > len(allowed):
                raise ValueError(f"{name} must be a bounded tuple")
            if any(type(item) is not str or item not in allowed for item in values):
                raise ValueError(f"{name} contains an unsupported value")
            if len(set(values)) != len(values):
                raise ValueError(f"{name} must not contain duplicates")


@dataclass(frozen=True)
class StreamTrial:
    """One independently scored run of one preregistered case."""

    trial_id: str
    experiment_id: str
    case_id: str
    variant: str
    revision: str
    environment_sha256: str
    execution_status: str
    task_success: bool | None
    turn_taking_success: bool | None
    groundedness_success: bool | None
    held_out_skill_success: bool | None
    game_completion_success: bool | None
    first_content_ms: float | None
    first_audible_ms: float | None
    game_frame_p99_ms: float | None
    audio_underrun_rate: float | None
    obs_output_skip_rate: float | None
    peak_cpu_millicores: int | None
    peak_ram_mib: int | None
    peak_vram_mib: int | None
    tokens_per_second: float | None
    memory_tokens: int | None
    evidence_sha256: str
    observed_unix_s: int

    def __post_init__(self) -> None:
        for name in ("trial_id", "experiment_id", "case_id", "revision"):
            _identifier(getattr(self, name), name)
        if type(self.variant) is not str or self.variant not in _VARIANTS:
            raise ValueError("variant must be baseline or candidate")
        if type(self.execution_status) is not str or self.execution_status not in _STATUSES:
            raise ValueError("execution_status must be completed or error")
        _digest(self.environment_sha256, "environment_sha256")
        _digest(self.evidence_sha256, "evidence_sha256")
        if type(self.observed_unix_s) is not int or not 0 < self.observed_unix_s <= 10**11:
            raise ValueError("observed_unix_s must be a valid positive Unix timestamp")

        outcome_names = (
            "task_success",
            "turn_taking_success",
            "groundedness_success",
            "held_out_skill_success",
            "game_completion_success",
        )
        for name in outcome_names:
            value = getattr(self, name)
            if value is not None and type(value) is not bool:
                raise ValueError(f"{name} must be boolean or None")

        numeric_bounds = {
            "first_content_ms": _MAX_MS,
            "first_audible_ms": _MAX_MS,
            "game_frame_p99_ms": _MAX_MS,
            "audio_underrun_rate": _MAX_RATE,
            "obs_output_skip_rate": _MAX_RATE,
            "tokens_per_second": _MAX_TPS,
        }
        for name, maximum in numeric_bounds.items():
            value = getattr(self, name)
            if value is not None:
                _finite(value, name, maximum)

        for name in ("peak_cpu_millicores", "peak_ram_mib", "peak_vram_mib", "memory_tokens"):
            value = getattr(self, name)
            if value is not None:
                _bounded_int(value, name, _MAX_COUNTER if name == "peak_cpu_millicores" else _MAX_MIB)

        if self.execution_status == "completed":
            if type(self.task_success) is not bool:
                raise ValueError("completed trials require an independently scored task_success")
        else:
            if any(getattr(self, name) is not None for name in outcome_names):
                raise ValueError("error trials cannot contain task outcomes")
            if any(getattr(self, name) is not None for name in _METRICS):
                raise ValueError("error trials cannot contain performance measurements")

    def canonical_bytes(self) -> bytes:
        """Canonical, domain-separated receipt payload; no raw content."""
        payload = json.dumps(
            asdict(self),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        return _DOMAIN + payload


@dataclass(frozen=True)
class SignedStreamTrial:
    trial: StreamTrial
    receipt: str

    def __post_init__(self) -> None:
        if type(self.trial) is not StreamTrial:
            raise TypeError("trial must be StreamTrial")
        _digest(self.receipt, "receipt")


def sign_stream_trial(trial: StreamTrial, *, validation_key: bytes) -> SignedStreamTrial:
    """Host-only helper. Never expose the key or this function as an LLM tool."""
    if type(validation_key) is not bytes or len(validation_key) < 32:
        raise ValueError("requires an independent host-owned validation key")
    receipt = hmac.new(validation_key, trial.canonical_bytes(), hashlib.sha256).hexdigest()
    return SignedStreamTrial(trial=trial, receipt=receipt)


def roster_digest(cases: Sequence[StreamCase]) -> str:
    """Seal the case roster before either variant is run."""
    if type(cases) not in (tuple, list) or not 1 <= len(cases) <= _MAX_CASES:
        raise ValueError("provide 1..512 preregistered stream cases")
    if any(type(case) is not StreamCase for case in cases):
        raise TypeError("all cases must be StreamCase")
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("case IDs must be unique")
    rows = sorted(
        (
            case.case_id,
            case.domain,
            case.split,
            tuple(sorted(case.required_dimensions)),
            tuple(sorted(case.required_metrics)),
        )
        for case in cases
    )
    payload = json.dumps(rows, separators=(",", ":"), ensure_ascii=True).encode("ascii")
    return hashlib.sha256(b"star.stream-variant-roster.v1\x00" + payload).hexdigest()


@dataclass(frozen=True)
class StreamVariantLimits:
    """Operator-set non-inferiority and speed goals; no automatic promotion."""

    min_pairs: int = 30
    min_holdout_pairs: int = 20
    min_holdout_domains: int = 3
    min_dimension_pairs: int = 5
    min_metric_pairs: int = 5
    max_task_success_regression: float = 0.02
    max_turn_taking_regression: float | None = None
    max_groundedness_regression: float | None = None
    max_held_out_skill_regression: float | None = None
    max_game_completion_regression: float | None = None
    max_first_content_regression_fraction: float = 0.05
    max_first_audible_regression_fraction: float = 0.05
    max_game_frame_regression_fraction: float = 0.05
    max_audio_underrun_regression: float = 0.001
    max_obs_output_skip_regression: float | None = 0.001
    max_cpu_regression_fraction: float = 0.10
    max_ram_regression_fraction: float = 0.10
    max_memory_tokens_regression_fraction: float = 0.10
    max_vram_regression_mib: int | None = 256
    min_first_content_improvement_fraction: float | None = None
    min_first_audible_improvement_fraction: float | None = None
    min_tokens_per_second_improvement_fraction: float | None = None
    max_validation_age_s: int = 7 * 86400

    def __post_init__(self) -> None:
        for name in (
            "min_pairs", "min_holdout_pairs", "min_holdout_domains",
            "min_dimension_pairs", "min_metric_pairs", "max_validation_age_s",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.min_pairs > _MAX_TRIALS // 2 or self.min_holdout_pairs > _MAX_TRIALS // 2:
            raise ValueError("pair limits exceed the supported trial capacity")
        if self.max_validation_age_s > _MAX_AGE_S:
            raise ValueError("max_validation_age_s exceeds 30 days")
        for name in (
            "max_task_success_regression",
            "max_turn_taking_regression",
            "max_groundedness_regression",
            "max_held_out_skill_regression",
            "max_game_completion_regression",
            "max_first_content_regression_fraction",
            "max_first_audible_regression_fraction",
            "max_game_frame_regression_fraction",
            "max_audio_underrun_regression",
            "max_obs_output_skip_regression",
            "max_cpu_regression_fraction",
            "max_ram_regression_fraction",
            "max_memory_tokens_regression_fraction",
        ):
            value = getattr(self, name)
            if value is None:
                continue
            _finite(value, name, 1.0)
        if self.max_vram_regression_mib is not None:
            _bounded_int(self.max_vram_regression_mib, "max_vram_regression_mib", _MAX_MIB)
        improvement_goals = (
            self.min_first_content_improvement_fraction,
            self.min_first_audible_improvement_fraction,
            self.min_tokens_per_second_improvement_fraction,
        )
        if not any(value is not None for value in improvement_goals):
            raise ValueError("configure at least one explicit speed/throughput improvement goal")
        for name, value in zip(
            (
                "min_first_content_improvement_fraction",
                "min_first_audible_improvement_fraction",
                "min_tokens_per_second_improvement_fraction",
            ),
            improvement_goals,
        ):
            if value is not None:
                _finite(value, name, 10.0)


def _metric_value(trial: StreamTrial, name: str) -> float | None:
    value = getattr(trial, name)
    return None if value is None else float(value)


def _metric_summary(pairs: list[tuple[StreamTrial, StreamTrial]], name: str) -> dict[str, float | int | None]:
    baseline = [_metric_value(left, name) for left, _ in pairs]
    candidate = [_metric_value(right, name) for _, right in pairs]
    paired = [
        (left, right)
        for left, right in zip(baseline, candidate)
        if left is not None and right is not None
    ]
    base_values = [left for left, _ in paired]
    candidate_values = [right for _, right in paired]
    deltas = [right - left for left, right in paired]
    quantile = 0.50 if name == "tokens_per_second" else 0.95
    base_q = _nearest_rank(base_values, quantile)
    candidate_q = _nearest_rank(candidate_values, quantile)
    paired_median_delta = round(median(deltas), 3) if deltas else None
    improvement = None
    if base_q is not None and candidate_q is not None and base_q > 0:
        improvement = (
            (candidate_q - base_q) / base_q
            if name == "tokens_per_second"
            else (base_q - candidate_q) / base_q
        )
    return {
        "pairs": len(paired),
        "baseline_p95_or_p50": base_q,
        "candidate_p95_or_p50": candidate_q,
        "paired_median_delta": paired_median_delta,
        "improvement_fraction": None if improvement is None else round(improvement, 6),
    }


def _dimension_summary(
    pairs: list[tuple[StreamTrial, StreamTrial]],
    field: str,
) -> dict[str, float | int | None]:
    selected = [
        (getattr(left, field), getattr(right, field))
        for left, right in pairs
        if getattr(left, field) is not None and getattr(right, field) is not None
    ]
    baseline_successes = sum(1 for left, _ in selected if left is True)
    candidate_successes = sum(1 for _, right in selected if right is True)
    wins = sum(1 for left, right in selected if right is True and left is False)
    losses = sum(1 for left, right in selected if right is False and left is True)
    return {
        "pairs": len(selected),
        "baseline_rate": _rate(baseline_successes, len(selected)),
        "candidate_rate": _rate(candidate_successes, len(selected)),
        "delta": (
            None if not selected
            else round(candidate_successes / len(selected) - baseline_successes / len(selected), 6)
        ),
        "candidate_only_successes": wins,
        "baseline_only_successes": losses,
        "mcnemar_one_sided_p": round(_one_sided_p(wins, losses), 8),
    }


def evaluate_stream_variants(
    cases: Sequence[StreamCase],
    signed_trials: Sequence[SignedStreamTrial],
    *,
    validation_key: bytes,
    expected_roster_sha256: str,
    baseline_revision: str,
    candidate_revision: str,
    now_unix_s: int,
    limits: StreamVariantLimits,
) -> dict[str, object]:
    """Compare two revisions on identical sealed cases and host conditions.

    Only holdout pairs drive gates. Development pairs are reported separately
    and cannot satisfy holdout minimums. Incomplete/error pairs are excluded.
    A PASS means only that the configured comparison gates passed; it never
    promotes a model, memory, skill, or runtime configuration.
    """
    if type(validation_key) is not bytes or len(validation_key) < 32:
        raise ValueError("requires an independent host-owned validation key")
    if type(limits) is not StreamVariantLimits:
        raise TypeError("limits must be StreamVariantLimits")
    _identifier(baseline_revision, "baseline_revision")
    _identifier(candidate_revision, "candidate_revision")
    if baseline_revision == candidate_revision:
        raise ValueError("baseline and candidate revisions must differ")
    _digest(expected_roster_sha256, "expected_roster_sha256")
    if type(now_unix_s) is not int or not 0 < now_unix_s <= 10**11:
        raise ValueError("now_unix_s must be a valid positive Unix timestamp")
    if type(cases) not in (tuple, list) or not 1 <= len(cases) <= _MAX_CASES:
        raise ValueError("provide 1..512 preregistered stream cases")
    if type(signed_trials) not in (tuple, list) or len(signed_trials) > _MAX_TRIALS:
        raise ValueError("provide at most 1024 signed stream trials")
    if any(type(case) is not StreamCase for case in cases):
        raise TypeError("all cases must be StreamCase")
    if any(type(item) is not SignedStreamTrial for item in signed_trials):
        raise TypeError("all trials must be SignedStreamTrial")
    if not hmac.compare_digest(roster_digest(cases), expected_roster_sha256):
        raise ValueError("case roster differs from its preregistered digest")

    case_index = {case.case_id: case for case in cases}
    if len(case_index) != len(cases):
        raise ValueError("case IDs must be unique")
    seen_trial_ids: set[str] = set()
    slots: dict[tuple[str, str], StreamTrial] = {}
    experiment_id: str | None = None

    for signed in signed_trials:
        trial = signed.trial
        if trial.trial_id in seen_trial_ids:
            raise ValueError("trial IDs must be unique")
        seen_trial_ids.add(trial.trial_id)
        if trial.case_id not in case_index:
            raise ValueError("trial references a case outside the sealed roster")
        if experiment_id is None:
            experiment_id = trial.experiment_id
        elif trial.experiment_id != experiment_id:
            raise ValueError("all trials must belong to one experiment")
        expected_revision = baseline_revision if trial.variant == "baseline" else candidate_revision
        if trial.revision != expected_revision:
            raise ValueError("trial revision does not match its variant")
        age = now_unix_s - trial.observed_unix_s
        if age < -30 or age > limits.max_validation_age_s:
            raise ValueError("trial is future-dated or outside the validation age limit")
        expected_receipt = hmac.new(
            validation_key, trial.canonical_bytes(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected_receipt, signed.receipt):
            raise ValueError("invalid independent host receipt")
        key = (trial.case_id, trial.variant)
        if key in slots:
            raise ValueError("each case must have at most one trial per variant")
        slots[key] = trial

    pairs: list[tuple[StreamCase, StreamTrial, StreamTrial]] = []
    incomplete_pairs = 0
    dimension_fields = {
        "turn_taking": "turn_taking_success",
        "groundedness": "groundedness_success",
        "held_out_skill": "held_out_skill_success",
        "game_completion": "game_completion_success",
    }
    for case in cases:
        left = slots.get((case.case_id, "baseline"))
        right = slots.get((case.case_id, "candidate"))
        if left is None or right is None:
            incomplete_pairs += 1
            continue
        if left.environment_sha256 != right.environment_sha256:
            raise ValueError("paired variants must share the same host/game/harness environment")
        if left.execution_status != "completed" or right.execution_status != "completed":
            incomplete_pairs += 1
            continue
        for dimension in case.required_dimensions:
            field = dimension_fields[dimension]
            if getattr(left, field) is None or getattr(right, field) is None:
                raise ValueError(f"paired trials are missing required outcome: {dimension}")
        for metric in case.required_metrics:
            if getattr(left, metric) is None or getattr(right, metric) is None:
                raise ValueError(f"paired trials are missing required metric: {metric}")
        for metric in _METRICS:
            if (getattr(left, metric) is None) != (getattr(right, metric) is None):
                raise ValueError(f"paired trials have asymmetric metric availability: {metric}")
        for dimension, field in dimension_fields.items():
            if (getattr(left, field) is None) != (getattr(right, field) is None):
                raise ValueError(f"paired trials have asymmetric outcome availability: {dimension}")
        pairs.append((case, left, right))

    holdout_pairs = [(left, right) for case, left, right in pairs if case.split == "holdout"]
    development_pairs = [(left, right) for case, left, right in pairs if case.split == "development"]
    holdout_domains = sorted({case.domain for case, _, _ in pairs if case.split == "holdout"})

    dimensions = {
        "task_success": _dimension_summary(holdout_pairs, "task_success"),
        "turn_taking": _dimension_summary(holdout_pairs, "turn_taking_success"),
        "groundedness": _dimension_summary(holdout_pairs, "groundedness_success"),
        "held_out_skill": _dimension_summary(holdout_pairs, "held_out_skill_success"),
        "game_completion": _dimension_summary(holdout_pairs, "game_completion_success"),
    }
    metrics = {
        name: _metric_summary(holdout_pairs, name)
        for name in sorted(_METRICS)
    }

    gates: list[dict[str, object]] = []

    def gate(name: str, observed: float | None, limit: float | None, *, direction: str,
             observations: int, required: int) -> None:
        if limit is None:
            return
        if observed is None or observations < required:
            status = "INCONCLUSIVE"
        elif direction == "min":
            status = "PASS" if observed >= limit else "FAIL"
        else:
            status = "PASS" if observed <= limit else "FAIL"
        gates.append({
            "name": name,
            "status": status,
            "observed": observed,
            "comparator": ">=" if direction == "min" else "<=",
            "limit": limit,
            "observations": observations,
            "required_observations": required,
        })

    enough = (
        len(pairs) >= limits.min_pairs
        and len(holdout_pairs) >= limits.min_holdout_pairs
        and len(holdout_domains) >= limits.min_holdout_domains
    )
    if not enough:
        gates.append({
            "name": "holdout_coverage",
            "status": "INCONCLUSIVE",
            "observed": {
                "complete_pairs": len(pairs),
                "holdout_pairs": len(holdout_pairs),
                "holdout_domains": len(holdout_domains),
            },
            "comparator": "minimums",
            "limit": {
                "complete_pairs": limits.min_pairs,
                "holdout_pairs": limits.min_holdout_pairs,
                "holdout_domains": limits.min_holdout_domains,
            },
            "observations": len(holdout_pairs),
            "required_observations": limits.min_holdout_pairs,
        })
    else:
        gate("task_success_noninferiority", dimensions["task_success"]["delta"],
             -limits.max_task_success_regression, direction="min",
             observations=int(dimensions["task_success"]["pairs"] or 0),
             required=limits.min_holdout_pairs)
        for dimension, threshold in (
            ("turn_taking", limits.max_turn_taking_regression),
            ("groundedness", limits.max_groundedness_regression),
            ("held_out_skill", limits.max_held_out_skill_regression),
            ("game_completion", limits.max_game_completion_regression),
        ):
            gate(
                f"{dimension}_noninferiority",
                dimensions[dimension]["delta"],
                None if threshold is None else -threshold,
                direction="min",
                observations=int(dimensions[dimension]["pairs"] or 0),
                required=limits.min_dimension_pairs,
            )
        for metric, threshold in (
            ("first_content_ms", limits.max_first_content_regression_fraction),
            ("first_audible_ms", limits.max_first_audible_regression_fraction),
            ("game_frame_p99_ms", limits.max_game_frame_regression_fraction),
        ):
            summary = metrics[metric]
            improvement = summary["improvement_fraction"]
            regression = None if improvement is None else -float(improvement)
            gate(
                f"{metric}_nonregression",
                regression,
                threshold,
                direction="max",
                observations=int(summary["pairs"] or 0),
                required=limits.min_metric_pairs,
            )
        audio = metrics["audio_underrun_rate"]
        audio_delta = audio["paired_median_delta"]
        gate(
            "audio_underrun_nonregression",
            None if audio_delta is None else float(audio_delta),
            limits.max_audio_underrun_regression,
            direction="max",
            observations=int(audio["pairs"] or 0),
            required=limits.min_metric_pairs,
        )
        obs = metrics["obs_output_skip_rate"]
        obs_delta = obs["paired_median_delta"]
        gate(
            "obs_output_skip_nonregression",
            None if obs_delta is None else float(obs_delta),
            limits.max_obs_output_skip_regression,
            direction="max",
            observations=int(obs["pairs"] or 0),
            required=limits.min_metric_pairs,
        )
        vram = metrics["peak_vram_mib"]
        vram_delta = vram["paired_median_delta"]
        gate(
            "vram_nonregression",
            None if vram_delta is None else float(vram_delta),
            None if limits.max_vram_regression_mib is None else float(limits.max_vram_regression_mib),
            direction="max",
            observations=int(vram["pairs"] or 0),
            required=limits.min_metric_pairs,
        )
        for metric, threshold in (
            ("peak_cpu_millicores", limits.max_cpu_regression_fraction),
            ("peak_ram_mib", limits.max_ram_regression_fraction),
            ("memory_tokens", limits.max_memory_tokens_regression_fraction),
        ):
            summary = metrics[metric]
            improvement = summary["improvement_fraction"]
            regression = None if improvement is None else -float(improvement)
            gate(
                f"{metric}_nonregression",
                regression,
                threshold,
                direction="max",
                observations=int(summary["pairs"] or 0),
                required=limits.min_metric_pairs,
            )
        for metric, threshold in (
            ("first_content_ms", limits.min_first_content_improvement_fraction),
            ("first_audible_ms", limits.min_first_audible_improvement_fraction),
            ("tokens_per_second", limits.min_tokens_per_second_improvement_fraction),
        ):
            summary = metrics[metric]
            gate(
                f"{metric}_improvement",
                None if summary["improvement_fraction"] is None else float(summary["improvement_fraction"]),
                threshold,
                direction="min",
                observations=int(summary["pairs"] or 0),
                required=limits.min_metric_pairs,
            )

    if not gates:
        raise ValueError("no configured stream variant gates were evaluated")
    statuses = {str(item["status"]) for item in gates}
    overall = "FAIL" if "FAIL" in statuses else (
        "INCONCLUSIVE" if "INCONCLUSIVE" in statuses else "PASS"
    )
    return {
        "schema_version": 1,
        "experiment_id": experiment_id,
        "baseline_revision": baseline_revision,
        "candidate_revision": candidate_revision,
        "overall": overall,
        "promotion": "never_automatic",
        "counts": {
            "preregistered_cases": len(cases),
            "signed_trials": len(signed_trials),
            "complete_pairs": len(pairs),
            "holdout_pairs": len(holdout_pairs),
            "development_pairs": len(development_pairs),
            "incomplete_or_error_pairs": incomplete_pairs,
            "holdout_domains": holdout_domains,
        },
        "dimensions": dimensions,
        "metrics": metrics,
        "gates": gates,
        "notes": [
            "Only preregistered holdout pairs drive gates; development pairs never satisfy holdout minimums.",
            "Every paired trial must share the same host/game/harness environment digest.",
            "HMAC authenticates to the host key holder; it does not prove the scorer or observer is truthful.",
            "The host must randomize or counterbalance baseline/candidate order and isolate warm/cold-cache conditions.",
            "A PASS applies only to configured limits and supplied observations; it is not a model promotion.",
            "No transcript, audio, video, screenshot, viewer identity, prompt, scenario text, or answer key is accepted.",
            "Metric p95 values are nearest-rank over paired holdout cases; token throughput uses p50.",
            "Missing or asymmetric paired evidence is rejected or inconclusive, never treated as zero.",
        ],
    }


__all__ = [
    "SignedStreamTrial",
    "StreamCase",
    "StreamTrial",
    "StreamVariantLimits",
    "evaluate_stream_variants",
    "roster_digest",
    "sign_stream_trial",
]
