"""Paired, randomized local model comparison for STAR's mixed streaming workloads.

This is an opt-in experiment, not an automatic router. It sends the same fixed
synthetic workload to two or three model aliases on one already-running
loopback endpoint, randomizes model order within each matched pair, runs one
request at a time, and reports client-observed paired latency deltas.

The report contains no prompts or generated text. It does not grade answer
quality, prove model residency, inspect GPU kernels, or change a live route.
If a server loads/unloads models on demand, that switching cost is included in
the observed result and must not be mistaken for steady-state decode speed.
"""
from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
import json
import random
import math
from pathlib import Path
from time import monotonic
from typing import Any, cast

from .brain_router import validate_alias
from .desktop_core import Settings
from .inference_workload_benchmark import (
    InferenceWorkload,
    StreamingProbe,
    WORKLOADS,
    _one_streaming_request,
)
from .providers import open_client

MAX_MODELS = 3
MAX_PAIRED_REQUESTS = 64
MAX_REPEATS_PER_WORKLOAD = 4
DEFAULT_SEED = 20261109
_TIE_MS = 0.5
_CATEGORIES = frozenset(item.category for item in WORKLOADS)
_WORKLOAD_BY_CATEGORY = {item.category: item for item in WORKLOADS}
_WARMUP = InferenceWorkload("warmup", "Reply with the single word ready.")


@dataclass(frozen=True)
class PairedStreamingProbe:
    pair_id: int
    model: str
    order_index: int
    probe: StreamingProbe

    def __post_init__(self) -> None:
        if type(self.pair_id) is not int or not 0 <= self.pair_id < 64:
            raise ValueError("pair_id must be a bounded nonnegative integer")
        if type(self.model) is not str or not self.model:
            raise ValueError("model alias must be nonempty")
        validate_alias(self.model, field="model")
        if type(self.order_index) is not int or not 0 <= self.order_index < MAX_MODELS:
            raise ValueError("order_index is outside the supported model count")
        if not isinstance(self.probe, StreamingProbe) or self.probe.category not in _CATEGORIES:
            raise ValueError("paired probes require a measured workload probe")


def _models(values: Sequence[str]) -> tuple[str, ...]:
    if (not isinstance(values, Sequence) or isinstance(values, (str, bytes))
            or not 2 <= len(values) <= MAX_MODELS):
        raise ValueError("compare exactly two or three model aliases")
    result = tuple(values)
    for model in result:
        if type(model) is not str or not model:
            raise ValueError("model aliases must be nonempty strings")
        validate_alias(model, field="model")
    if len(set(result)) != len(result):
        raise ValueError("model aliases must be unique")
    return result


def _finite_positive(value: object, label: str, *, allow_zero: bool = False) -> float:
    if type(value) not in (int, float):
        raise ValueError(f"{label} must be a finite number")
    try:
        number = float(cast(int | float, value))
    except (ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be finite") from exc
    if not math.isfinite(number) or number < (0 if allow_zero else 0.01):
        raise ValueError(f"{label} must be finite and nonnegative/positive")
    return number


def _percentile(values: Sequence[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if fraction == 0.5:
        middle = len(ordered) // 2
        if len(ordered) % 2:
            value = ordered[middle]
        else:
            value = (ordered[middle - 1] + ordered[middle]) / 2
    else:
        value = ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]
    return round(float(value), 2)


def _first_content(probe: StreamingProbe) -> float:
    value = probe.first_content_ms
    if value is None:
        raise ValueError("paired comparison requires first-content timestamps")
    return float(value)


def _comparison(pairs: Sequence[tuple[StreamingProbe, StreamingProbe]],
                *, incomplete_pairs: int) -> dict[str, Any]:
    first_deltas = [
        _first_content(candidate) - _first_content(baseline)
        for baseline, candidate in pairs
    ]
    end_deltas = [candidate.elapsed_ms - baseline.elapsed_ms
                  for baseline, candidate in pairs]
    faster = sum(delta < -_TIE_MS for delta in first_deltas)
    slower = sum(delta > _TIE_MS for delta in first_deltas)
    tied = len(first_deltas) - faster - slower
    return {
        "paired_samples": len(pairs),
        "incomplete_pairs": incomplete_pairs,
        "baseline_first_content_p50_ms": _percentile(
            [_first_content(base) for base, _ in pairs], 0.50),
        "candidate_first_content_p50_ms": _percentile(
            [_first_content(candidate) for _, candidate in pairs], 0.50),
        "first_content_delta_p50_ms": _percentile(first_deltas, 0.50),
        "first_content_delta_p95_ms": _percentile(first_deltas, 0.95),
        "candidate_faster_pairs": faster,
        "candidate_tied_pairs": tied,
        "candidate_slower_pairs": slower,
        "baseline_end_to_end_p50_ms": _percentile(
            [base.elapsed_ms for base, _ in pairs], 0.50),
        "candidate_end_to_end_p50_ms": _percentile(
            [candidate.elapsed_ms for _, candidate in pairs], 0.50),
        "end_to_end_delta_p50_ms": _percentile(end_deltas, 0.50),
        "tie_threshold_ms": _TIE_MS,
    }


def summarize_paired_streaming_probes(
    probes: Sequence[PairedStreamingProbe],
    *,
    models: Sequence[str],
    pair_schedule: Sequence[dict[str, Any]],
    seed: int,
    wall_ms: float,
    warmup_ms: float,
    warmup_by_model_ms: dict[str, float],
) -> dict[str, Any]:
    """Validate a complete matched schedule and summarize paired observations.

    Negative candidate-minus-baseline deltas mean the candidate was faster.
    Failed requests remain visible as incomplete pairs and are never silently
    dropped from the denominator.
    """
    aliases = _models(models)
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError("seed must be a 32-bit nonnegative integer")
    wall = _finite_positive(wall_ms, "wall_ms")
    warmup = _finite_positive(warmup_ms, "warmup_ms", allow_zero=True)
    if not isinstance(pair_schedule, Sequence) or isinstance(pair_schedule, (str, bytes)):
        raise ValueError("pair_schedule must be a sequence")
    if not 1 <= len(pair_schedule) <= 64:
        raise ValueError("pair_schedule must contain 1..64 pairs")
    if not isinstance(probes, Sequence) or len(probes) > 64 * MAX_MODELS:
        raise ValueError("probes must be a bounded sequence")
    if not isinstance(warmup_by_model_ms, dict) or set(warmup_by_model_ms) != set(aliases):
        raise ValueError("warm-up timings must cover every compared model")
    for value in warmup_by_model_ms.values():
        _finite_positive(value, "warmup_by_model_ms", allow_zero=True)

    schedule: dict[int, tuple[str, tuple[str, ...]]] = {}
    for expected_id, item in enumerate(pair_schedule):
        if not isinstance(item, dict) or set(item) != {"pair_id", "category", "model_order"}:
            raise ValueError("pair schedule contains unknown or missing fields")
        if type(item["pair_id"]) is not int or item["pair_id"] != expected_id:
            raise ValueError("pair IDs must be contiguous and ordered")
        category = item["category"]
        order = item["model_order"]
        if type(category) is not str or category not in _CATEGORIES:
            raise ValueError("pair schedule has an unknown workload category")
        if not isinstance(order, Sequence) or isinstance(order, (str, bytes)):
            raise ValueError("each pair order must contain every model exactly once")
        order_tuple = tuple(order)
        if (any(type(name) is not str for name in order_tuple)
                or len(order_tuple) != len(aliases)
                or len(set(order_tuple)) != len(order_tuple)
                or set(order_tuple) != set(aliases)):
            raise ValueError("each pair order must contain every model exactly once")
        schedule[expected_id] = (category, order_tuple)

    indexed: dict[int, dict[str, StreamingProbe]] = {key: {} for key in schedule}
    for row in probes:
        if not isinstance(row, PairedStreamingProbe) or row.model not in aliases:
            raise ValueError("unexpected paired probe")
        if row.pair_id not in indexed or row.model in indexed[row.pair_id]:
            raise ValueError("duplicate or out-of-range paired probe")
        category, order = schedule[row.pair_id]
        if row.probe.category != category or row.order_index >= len(order):
            raise ValueError("probe does not match its preregistered workload")
        if order[row.order_index] != row.model:
            raise ValueError("probe order differs from the recorded randomized schedule")
        indexed[row.pair_id][row.model] = row.probe
    if any(set(group) != set(aliases) for group in indexed.values()):
        raise ValueError("every pair must contain exactly one probe for each model; a model probe is missing")

    candidates: dict[str, Any] = {}
    baseline = aliases[0]
    for candidate in aliases[1:]:
        complete: list[tuple[StreamingProbe, StreamingProbe]] = []
        by_category: dict[str, list[tuple[StreamingProbe, StreamingProbe]]] = {
            category: [] for category in sorted(_CATEGORIES)
        }
        incomplete_by_category = {category: 0 for category in sorted(_CATEGORIES)}
        for pair_id, group in indexed.items():
            category = schedule[pair_id][0]
            base_probe, candidate_probe = group[baseline], group[candidate]
            valid = (
                base_probe.ok and candidate_probe.ok
                and base_probe.first_content_ms is not None
                and candidate_probe.first_content_ms is not None
            )
            if valid:
                pair = (base_probe, candidate_probe)
                complete.append(pair)
                by_category[category].append(pair)
            else:
                incomplete_by_category[category] += 1
        candidates[candidate] = {
            "overall": _comparison(
                complete, incomplete_pairs=len(indexed) - len(complete)),
            "by_category": {
                category: _comparison(
                    by_category[category],
                    incomplete_pairs=incomplete_by_category[category],
                )
                for category in sorted(_CATEGORIES)
                if by_category[category] or incomplete_by_category[category]
            },
        }

    successful = sum(1 for row in probes if row.probe.ok)
    return {
        "schema_version": 1,
        "verdict": "paired_observations" if any(
            value["overall"]["paired_samples"] for value in candidates.values()
        ) else "no_complete_pairs",
        "baseline_model": baseline,
        "models": list(aliases),
        "seed": seed,
        "pair_count": len(pair_schedule),
        "total_requests": len(probes),
        "successful_requests": successful,
        "failed_requests": len(probes) - successful,
        "wall_ms": round(wall, 2),
        "warmup_ms": round(warmup, 2),
        "warmup_by_model_ms": {
            model: round(float(warmup_by_model_ms[model]), 2) for model in aliases
        },
        "pair_schedule": [
            {
                "pair_id": item["pair_id"],
                "category": item["category"],
                "model_order": list(item["model_order"]),
            }
            for item in pair_schedule
        ],
        "by_candidate": candidates,
        "note": (
            "Paired client-observed synthetic workload experiment. Negative candidate-minus-baseline "
            "latency deltas mean faster candidate observations. Model order is randomized within each "
            "matched prompt pair and requests are sequential. Failed pairs remain in incomplete counts. "
            "This does not grade answer quality, prove model residency, isolate engine decode kernels, "
            "or authorize automatic routing. Server-side model loading/switching is included if it occurs; "
            "confirm equivalent residency and runtime configuration before interpreting steady-state speed. "
            "Compare on the same host, endpoint, runtime build, context and hardware, then repeat under the "
            "actual game/OBS/TTS workload."
        ),
    }


async def benchmark_paired_local_streaming(
    endpoint: str,
    models: Sequence[str],
    *,
    repeats_per_workload: int = 1,
    seed: int = DEFAULT_SEED,
    client: Any = None,
) -> dict[str, Any]:
    """Run bounded, sequential, randomized model comparisons against loopback."""
    aliases = _models(models)
    if (type(repeats_per_workload) is not int
            or not 1 <= repeats_per_workload <= MAX_REPEATS_PER_WORKLOAD):
        raise ValueError(f"repeats_per_workload must be 1..{MAX_REPEATS_PER_WORKLOAD}")
    pair_count = len(WORKLOADS) * repeats_per_workload
    if pair_count * len(aliases) > MAX_PAIRED_REQUESTS:
        raise ValueError(f"paired run exceeds {MAX_PAIRED_REQUESTS} measured requests")
    if type(seed) is not int or not 0 <= seed <= 2**32 - 1:
        raise ValueError("seed must be a 32-bit nonnegative integer")

    settings = Settings(endpoint=endpoint, model=aliases[0])
    settings.validate()  # Same loopback-only policy as STAR's existing benchmark.
    own_client = client is None
    if own_client:
        client = open_client(settings, request_timeout=90.0)

    try:
        warmup_by_model: dict[str, float] = {}
        for model in aliases:
            warmup_probe = await _one_streaming_request(
                client, model, _WARMUP, max_tokens=8
            )
            if not warmup_probe.ok:
                raise RuntimeError(f"Warm-up failed for model alias {model}; no paired run was started")
            warmup_by_model[model] = warmup_probe.elapsed_ms

        rng = random.Random(seed)
        schedule: list[dict[str, Any]] = []
        for repeat in range(repeats_per_workload):
            for workload in WORKLOADS:
                order = list(aliases)
                rng.shuffle(order)
                schedule.append({
                    "pair_id": len(schedule),
                    "category": workload.category,
                    "model_order": order,
                })

        probes: list[PairedStreamingProbe] = []
        began = monotonic()
        for item in schedule:
            workload = _WORKLOAD_BY_CATEGORY[item["category"]]
            for order_index, model in enumerate(item["model_order"]):
                probe = await _one_streaming_request(
                    client, model, workload, max_tokens=192
                )
                probes.append(PairedStreamingProbe(
                    pair_id=item["pair_id"],
                    model=model,
                    order_index=order_index,
                    probe=probe,
                ))
        wall_ms = max(0.01, (monotonic() - began) * 1000)
        warmup_ms = sum(warmup_by_model.values())
        return summarize_paired_streaming_probes(
            probes,
            models=aliases,
            pair_schedule=schedule,
            seed=seed,
            wall_ms=wall_ms,
            warmup_ms=warmup_ms,
            warmup_by_model_ms=warmup_by_model,
        )
    finally:
        if own_client:
            await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare two or three local STAR model aliases using paired streaming workloads."
    )
    parser.add_argument("--endpoint", default="http://127.0.0.1:8080/v1",
                        help="Loopback model URL ending in /v1")
    parser.add_argument("--model", required=True, help="Baseline local model alias")
    parser.add_argument("--compare-model", action="append", default=[],
                        help="Candidate model alias; repeat once for a third model")
    parser.add_argument("--repeats-per-workload", type=int, default=1,
                        help="Repeat each fixed workload (1..4, subject to request cap)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help="Deterministic randomized-order seed")
    parser.add_argument("--output", type=Path, help="Optional local JSON report path")
    args = parser.parse_args()
    if not args.compare_model:
        parser.error("provide at least one --compare-model")
    report = asyncio.run(benchmark_paired_local_streaming(
        args.endpoint,
        [args.model, *args.compare_model],
        repeats_per_workload=args.repeats_per_workload,
        seed=args.seed,
    ))
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
