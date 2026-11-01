"""Read-only 8 GiB GPU candidate planner for Litha.

Catalog values are approximate Ollama *download* sizes, not allocated VRAM.
Never labels a model GPU-resident until independent runtime measurements exist.
No models are downloaded, started, changed or selected automatically.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math

MIB = 1024 * 1024


@dataclass(frozen=True)
class Model:
    tag: str
    published_size_gb: float  # decimal GB from the official Ollama tag page
    vision: bool
    tools: bool
    description: str


CATALOG: dict[str, Model] = {
    "qwen3.5:4b-q4_K_M": Model("qwen3.5:4b-q4_K_M", 3.3, True, True,
                               "Compact multimodal generalist; preferred during games/streaming."),
    "qwen3.5:4b-q8_0": Model("qwen3.5:4b-q8_0", 5.2, True, True,
                            "Higher-precision 4B candidate; reduced GPU headroom."),
    "qwen3.5:9b-q4_K_M": Model("qwen3.5:9b-q4_K_M", 6.6, True, True,
                              "Larger generalist candidate; tight 8 GiB fit requires measurement."),
    "lfm2.5:8b-a1b-q4_K_M": Model("lfm2.5:8b-a1b-q4_K_M", 5.2, False, True,
                                 "Text-only MoE candidate for rapid tool workflows."),
}

# Candidate ordering is a workload hypothesis, NOT measured task accuracy.
ORDERS = {
    "quality": ("qwen3.5:9b-q4_K_M", "qwen3.5:4b-q8_0", "lfm2.5:8b-a1b-q4_K_M", "qwen3.5:4b-q4_K_M"),
    "tools": ("lfm2.5:8b-a1b-q4_K_M", "qwen3.5:4b-q4_K_M", "qwen3.5:4b-q8_0", "qwen3.5:9b-q4_K_M"),
    "gaming": ("qwen3.5:4b-q4_K_M", "qwen3.5:4b-q8_0", "lfm2.5:8b-a1b-q4_K_M", "qwen3.5:9b-q4_K_M"),
    "vision": ("qwen3.5:9b-q4_K_M", "qwen3.5:4b-q8_0", "qwen3.5:4b-q4_K_M"),
}


def plan(*, free_vram_mib: int, reserve_mib: int = 1024, workload: str = "gaming") -> dict:
    """Compute a weight-size screening plan, not an actual memory-fit verdict.

    free_vram_mib must be a CURRENT observation from the intended host, e.g.
    nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits
    reserve_mib covers OS, context, runtime buffers and other workloads; it is
    only a *minimum provisional cushion*, not an estimate of those allocations.
    """
    if type(free_vram_mib) is not int or not 0 <= free_vram_mib <= 262144:
        raise ValueError("free_vram_mib must be a measured integer in 0..262144")
    if type(reserve_mib) is not int or not 256 <= reserve_mib <= 65536:
        raise ValueError("reserve_mib must be an integer in 256..65536")
    if workload not in ORDERS:
        raise ValueError("Unknown workload")
    available_for_weights = max(0, free_vram_mib - reserve_mib)
    rows = []
    for tag in ORDERS[workload]:
        model = CATALOG[tag]
        # A *download* size is an approximate lower bound for VRAM. It is not
        # the actual tensor allocation, nor a GGUF file-size guarantee.
        size_mib = math.ceil(model.published_size_gb * 1_000_000_000 / MIB)
        possible = size_mib <= available_for_weights
        rows.append({
            "tag": tag,
            "vision": model.vision,
            "tools": model.tools,
            "advertised_download_gb": model.published_size_gb,
            "approx_weight_size_mib": size_mib,
            "provisional_room_after_weights_mib": available_for_weights - size_mib,
            "status": "candidate_needs_live_fit_test" if possible else "outside_provisional_budget",
            "purpose": model.description,
        })
    selected = next((row["tag"] for row in rows if row["status"] == "candidate_needs_live_fit_test"), None)
    return {
        "workload": workload,
        "free_vram_mib_observed": free_vram_mib,
        "reserved_vram_mib_user_supplied": reserve_mib,
        "recommended_experiment_candidate": selected,
        "gpu_fit_verified": False,
        "candidates": rows,
        "limitations": (
            "Advertised download GB is NOT peak VRAM. Context length, KV/linear state, vision, "
            "backend buffers, GPU display load and concurrency change actual footprint. "
            "A candidate may OOM even when listed. Measure peak dedicated VRAM, latency, "
            "completion correctness and full GPU allocation on the real host before use. "
            "This planner never changes the live model or downloads weights."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline, read-only RTX 4060 candidate screen")
    parser.add_argument("--free-vram-mib", type=int, required=True,
                        help="Observed *free dedicated* VRAM in MiB (nvidia-smi memory.free)")
    parser.add_argument("--reserve-mib", type=int, default=1024,
                        help="Provisional VRAM cushion; does not prove fit")
    parser.add_argument("--workload", choices=tuple(ORDERS), default="gaming")
    args = parser.parse_args(argv)
    try:
        report = plan(free_vram_mib=args.free_vram_mib, reserve_mib=args.reserve_mib,
                      workload=args.workload)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
