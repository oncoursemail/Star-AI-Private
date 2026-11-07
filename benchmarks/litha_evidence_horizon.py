"""Reproducible, synthetic retrieval-only benchmark for Litha Evidence Horizon.

It does not measure model intelligence, real search quality, inference latency,
GPU performance, real web research, or production throughput.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import statistics
from tempfile import TemporaryDirectory
from time import perf_counter

from litha.evidence_horizon import HorizonStore


def run(*, sources: int, repeats: int) -> dict:
    if not 50 <= sources <= 3_000 or not 3 <= repeats <= 100:
        raise ValueError("sources must be 50..3000 and repeats must be 3..100")
    with TemporaryDirectory(prefix="litha-evidence-bench-") as folder:
        with HorizonStore(Path(folder) / "evidence.sqlite3") as store:
            for i in range(sources):
                kind = ("roblox", "blender", "rust", "memory", "research")[i % 5]
                body = (
                    f"source {i} developer information {kind} "
                    + f"important_{i:05d} verified example documentation "
                    + "model runtime context tool agent debugging " * 12
                )
                store.put(
                    "benchmark", f"source_{i:05d}", "r1", body,
                    locator=f"synthetic://{i}", kind="repo",
                )
            queries = [
                ["roblox debugging", "rust model"],
                ["memory retrieval context"],
                ["blender model important_00223"],
            ]
            samples = []
            fingerprints = []
            for _ in range(repeats):
                started = perf_counter()
                results = [store.search("benchmark", q, limit=12) for q in queries]
                samples.append(round((perf_counter() - started) * 1000, 5))
                fingerprints.append(sha256(
                    json.dumps(
                        [[(h["source_id"], h["sha256"]) for h in r["hits"]]
                         for r in results],
                        sort_keys=True,
                    ).encode("utf-8")
                ).hexdigest())
            return {
                "description": "synthetic, offline, retrieval-only; three multiquery searches per sample",
                "sources": sources,
                "repeats": repeats,
                "queries": queries,
                "backend": "fts5" if store.has_fts else "bounded_fallback",
                "median_ms_per_3_query_batch": round(statistics.median(samples), 5),
                "min_ms": min(samples),
                "max_ms": max(samples),
                "samples_ms": samples,
                "deterministic_hit_order": len(set(fingerprints)) == 1,
                "result_identity_sha256": fingerprints[0],
                "limitations": (
                    "Cold indexing cost excluded; synthetic content, isolated host, no model, "
                    "tokenization, reranking, GPU, live data, or production latency."
                ),
            }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=int, default=300)
    parser.add_argument("--repeats", type=int, default=15)
    args = parser.parse_args()
    print(json.dumps(run(sources=args.sources, repeats=args.repeats), indent=2))


if __name__ == "__main__":
    main()
