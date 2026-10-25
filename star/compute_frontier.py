"""Offline hardware tuning frontier for STAR's llama.cpp inference.

Compare real llama-bench JSON/JSONL results on identical model/build/host. No
models are launched and no running configuration is ever changed. +/-2 SD is
a variability heuristic, NOT a confidence interval or quality evidence.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_BYTES = 4_000_000
MAX_ROWS = 1024
IDENTITY = ("build_commit", "cpu_info", "gpu_info", "backends", "model_filename",
            "model_type", "model_size", "model_n_params", "type_k", "type_v")
WORKLOAD = ("n_prompt", "n_gen", "n_depth")
TUNABLES = ("n_threads", "n_batch", "n_ubatch", "n_gpu_layers", "n_cpu_moe",
            "split_mode", "main_gpu", "flash_attn", "use_mmap", "devices",
            "tensor_split", "no_kv_offload")


@dataclass(frozen=True)
class Reading:
    identity: tuple[Any, ...]
    workload: tuple[int, int, int]
    knobs: tuple[Any, ...]
    mean_tps: float
    std_tps: float
    peak_ram_mib: float | None = None
    peak_vram_mib: float | None = None


def _number(value: Any, field: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a measured number")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (positive and result == 0):
        raise ValueError(f"{field} must be finite and nonnegative")
    return result


def _reading(data: Any) -> Reading:
    if not isinstance(data, dict) or any(key not in data for key in IDENTITY):
        raise ValueError("Benchmark row lacks the model/engine/host identity")
    identity = tuple(data[k] for k in IDENTITY)
    if any(x is None or type(x) not in (str, int, float) for x in identity):
        raise ValueError("Invalid model/engine/host identity")
    tokens = []
    for key in WORKLOAD:
        value = data.get(key, 0)
        if type(value) is not int or value < 0:
            raise ValueError(f"Invalid {key}")
        tokens.append(value)
    if tokens[0] == 0 and tokens[1] == 0:
        raise ValueError("Benchmark has no input or generated tokens")
    if "avg_ts" not in data or "stddev_ts" not in data:
        raise ValueError("Repeated llama-bench measurements require avg_ts and stddev_ts")
    knobs = tuple(data.get(k) for k in TUNABLES)
    if all(x is None for x in knobs):
        raise ValueError("Benchmark row lacks tuning parameters")
    peaks = []
    for key in ("peak_ram_mib", "peak_vram_mib"):
        val = data.get(key)
        peaks.append(None if val is None else _number(val, key))
    return Reading(identity, tuple(tokens), knobs,
                   _number(data["avg_ts"], "avg_ts", positive=True),
                   _number(data["stddev_ts"], "stddev_ts"), *peaks)


def load_bench(path: str | Path) -> list[Reading]:
    """Bounded local file loading only. Never read credentials or contact servers."""
    file = Path(path)
    if file.is_symlink() or not file.is_file() or file.stat().st_size > MAX_BYTES:
        raise ValueError("Provide an ordinary benchmark JSON/JSONL file up to 4 MB")
    raw = file.read_text(encoding="utf-8")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        try:
            parsed = [json.loads(x) for x in raw.splitlines() if x.strip()]
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid benchmark JSON/JSONL") from exc
    rows = parsed if isinstance(parsed, list) else [parsed]
    if not 1 <= len(rows) <= MAX_ROWS:
        raise ValueError("Expected 1..1024 benchmark rows")
    return [_reading(row) for row in rows]


def _by_workload(rows: list[Reading]) -> dict[tuple[int, int, int], Reading]:
    result = {}
    for item in rows:
        if item.workload in result:
            raise ValueError("Duplicate workload; split independent benchmark sweeps")
        result[item.workload] = item
    return result


def _flags(knobs: tuple[Any, ...]) -> dict[str, Any]:
    return {field: value for field, value in zip(TUNABLES, knobs) if value is not None}


def _geomean(ratios: list[float]) -> float:
    return math.exp(sum(math.log(x) for x in ratios) / len(ratios))


def compare(baseline: list[Reading], candidates: list[Reading], *,
            min_gain: float = .05, max_ram_mib: float | None = None,
            max_vram_mib: float | None = None) -> dict:
    """Rank measurements conservatively; a passing candidate still requires live QA."""
    if not baseline or not candidates:
        raise ValueError("Baseline and candidate measurements are required")
    if type(min_gain) is not float and type(min_gain) is not int:
        raise ValueError("min_gain must be a number")
    if not .01 <= min_gain <= .50:
        raise ValueError("min_gain must be .01..50")
    for key, cap in (("max_ram_mib", max_ram_mib), ("max_vram_mib", max_vram_mib)):
        if cap is not None:
            _number(cap, key, positive=True)
    current = baseline[0]
    if any(x.identity != current.identity or x.knobs != current.knobs for x in baseline):
        raise ValueError("Baseline must have one model/build/host and one flag profile")
    old = _by_workload(baseline)
    groups: dict[tuple[Any, ...], list[Reading]] = {}
    for item in candidates:
        if item.identity != current.identity:
            raise ValueError("Refusing incomparable model/build/host/KV settings")
        groups.setdefault(item.knobs, []).append(item)
    verdicts = []
    for knobs, items in groups.items():
        if knobs == current.knobs:
            continue
        new = _by_workload(items)
        missing = set(old) - set(new)
        if missing:
            verdicts.append({"flags": _flags(knobs), "verdict": "incomplete_workloads",
                             "missing_workloads": len(missing)})
            continue
        ratio, lower = [], []
        for key, start in old.items():
            end = new[key]
            ratio.append(end.mean_tps / start.mean_tps)
            lower.append(max(.001, end.mean_tps - 2 * end.std_tps) /
                         (start.mean_tps + 2 * start.std_tps))
        mean_ratio = _geomean(ratio)
        low_ratio = _geomean(lower)
        if min(ratio) < .98:
            verdict = "throughput_regression"
        elif mean_ratio < 1 + min_gain:
            verdict = "no_meaningful_benchmark_gain"
        elif low_ratio >= 1 + min_gain and min(lower) >= .98:
            verdict = "worth_latency_and_quality_gates"
        else:
            verdict = "retest_variability"
        peaks = {}
        for field, cap in (("peak_ram_mib", max_ram_mib), ("peak_vram_mib", max_vram_mib)):
            if cap is None:
                continue
            values = [getattr(x, field) for x in new.values()]
            peaks[field] = max(values) if all(x is not None for x in values) else None
            if peaks[field] is None and verdict == "worth_latency_and_quality_gates":
                verdict = "needs_peak_memory_measurement"
            elif peaks[field] is not None and peaks[field] > cap:
                verdict = "exceeds_memory_budget"
        verdicts.append({"flags": _flags(knobs), "verdict": verdict,
                         "benchmark_speed_ratio": round(mean_ratio, 4),
                         "conservative_variability_ratio": round(low_ratio, 4),
                         "worst_workload_ratio": round(min(ratio), 4),
                         "workloads_compared": len(old), **peaks})
    verdicts.sort(key=lambda x: x.get("conservative_variability_ratio", 0), reverse=True)
    return {
        "baseline_flags": _flags(current.knobs), "candidate_count": len(verdicts),
        "candidates": verdicts,
        "limitations": (
            "llama-bench omits queuing, first-token latency, sampling, tool time and tokenization; "
            "+/-2 SD is not a confidence interval; model paths are not checksums. "
            "No quality, memory safety or production speed gain is proven. "
            "Require held-out QA and explicit owner review before changing live inference."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="STAR offline llama-bench hardware profile comparison")
    parser.add_argument("baseline", help="Current settings, llama-bench -o json")
    parser.add_argument("candidates", help="Tuning sweep, llama-bench -o json")
    parser.add_argument("--min-gain", type=float, default=.05)
    parser.add_argument("--max-ram-mib", type=float)
    parser.add_argument("--max-vram-mib", type=float)
    args = parser.parse_args(argv)
    try:
        report = compare(load_bench(args.baseline), load_bench(args.candidates),
                         min_gain=args.min_gain, max_ram_mib=args.max_ram_mib,
                         max_vram_mib=args.max_vram_mib)
    except (OSError, UnicodeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
