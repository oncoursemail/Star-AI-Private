"""Offline exact dense retrieval benchmark; one isolated process per backend.

Install the optional release-built native wheel first, then:
    python -m benchmarks.litha_dense --rows 10000 --dimension 384 --repeats 20

The baseline is the pre-change dense() method, including math.sumprod when
available. Timings exclude model inference and embedding generation. Startup,
packed payload and process peak RSS are reported separately from warm queries.
"""
from __future__ import annotations

import argparse
import array
import json
import math
import platform
import random
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))
from mesh.docs import build, index  # noqa: E402
sys.path.remove(str(ROOT / "server"))


def previous_dense(idx, vec, k=8):
    """Exact previous implementation, retained here only as the benchmark control."""
    if not idx.vectors or not vec:
        return []
    n = math.sqrt(math.fsum(x * x for x in vec)) or 1.0
    q = array.array("f", (x / n for x in vec))
    scored = [(pid, index._dot(q, v)) for pid, v in idx.vectors]
    scored.sort(key=lambda t: -t[1])
    return scored[:k]


def peak_rss_bytes():
    try:
        import resource
    except ImportError:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)


def worker(path, backend, dimension, repeats, k):
    started = time.perf_counter()
    idx = index.DocsIndex(path, dense_backend="rust" if backend == "rust" else "python")
    startup_ms = (time.perf_counter() - started) * 1000
    if backend == "rust" and idx.dense_backend != "rust":
        raise RuntimeError(f"Rust extension not active: {idx.dense_backend_reason}; install a release wheel first")
    try:
        rng = random.Random(419)
        queries = [[rng.uniform(-1, 1) for _ in range(dimension)] for _ in range(repeats)]
        query_fn = (lambda q: previous_dense(idx, q, k)) if backend == "baseline" else lambda q: idx.dense(q, k)
        for query in queries[:3]:
            query_fn(query)
        timings, answers = [], []
        for query in queries:
            started = time.perf_counter()
            answers.append(query_fn(query))
            timings.append((time.perf_counter() - started) * 1000)
        ordered = sorted(timings)
        return {
            "backend": backend, "index_build_ms": round(startup_ms, 3), "rows": idx.vector_count,
            "dimension": dimension, "repeats": repeats, "k": k,
            "median_ms": round(statistics.median(timings), 4),
            "p95_ms": round(ordered[max(0, math.ceil(len(ordered) * .95) - 1)], 4),
            "samples_ms": [round(x, 4) for x in timings],
            "vector_payload_bytes": idx.vector_bytes, "process_peak_rss_bytes": peak_rss_bytes(),
            "answers": answers,
        }
    finally:
        idx.db.close()


def create_database(path, rows, dimension):
    rng = random.Random(2201)
    with sqlite3.connect(path) as db:
        db.executescript(build.SCHEMA)
        db.execute("INSERT INTO meta VALUES ('meta', '{}')")
        for pid in range(1, rows + 1):
            values = [rng.uniform(-1, 1) for _ in range(dimension)]
            norm = math.sqrt(math.fsum(x * x for x in values))
            payload = array.array("f", (x / norm for x in values)).tobytes()
            db.execute("INSERT INTO passages(id, emb) VALUES (?, ?)", (pid, payload))


def run(rows, dimension, repeats, k):
    if not 1 <= rows <= 100_000 or not 1 <= dimension <= 4096 or not 4 <= repeats <= 100 or not 1 <= k <= 1000:
        raise ValueError("bounds: rows 1..100000; dimension 1..4096; repeats 4..100; k 1..1000")
    if rows * (dimension * 4 + 8) > 512 * 1024 * 1024:
        raise ValueError("synthetic corpus exceeds the 512 MiB packed-payload budget")
    results = []
    with tempfile.TemporaryDirectory(prefix="litha-dense-bench-") as temp:
        path = Path(temp) / "docs.db"
        create_database(path, rows, dimension)
        for backend in ("baseline", "python", "rust"):
            output = subprocess.check_output(
                [sys.executable, "-m", "benchmarks.litha_dense", "--worker", backend, "--db", str(path),
                 "--dimension", str(dimension), "--repeats", str(repeats), "--k", str(k)],
                cwd=ROOT, text=True, timeout=300,
            )
            results.append(json.loads(output))
    baseline = results[0]["answers"]
    max_error = 0.0
    for result in results:
        for expected, actual in zip(baseline, result.pop("answers")):
            if [pid for pid, _ in expected] != [pid for pid, _ in actual]:
                raise AssertionError(f"retrieval order changed for {result['backend']}")
            max_error = max(max_error, max((abs(a[1] - b[1]) for a, b in zip(expected, actual)), default=0.0))
    if max_error > 1e-12:
        raise AssertionError(f"score error exceeds parity tolerance: {max_error}")
    return {
        "python": platform.python_version(), "platform": platform.system(), "machine": platform.machine(),
        "baseline_dot": "math.sumprod" if hasattr(math, "sumprod") else "sum(map(operator.mul,...))",
        "rank_parity_all_queries": True, "max_absolute_score_error": max_error,
        "native_median_speedup_vs_previous": round(results[0]["median_ms"] / results[2]["median_ms"], 3),
        "results": results,
        "scope": "Seeded synthetic exact retrieval only; no LLM, GPU, embedding, network or end-to-end AI benchmark.",
        "memory_note": "Packed payload excludes overhead. Peak RSS is an isolated-process observation, not a hard cap;"
                       " null means this platform does not expose resource.getrusage.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=10_000)
    parser.add_argument("--dimension", type=int, default=384)
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--k", type=int, default=8)
    parser.add_argument("--worker", choices=("baseline", "python", "rust"))
    parser.add_argument("--db")
    args = parser.parse_args()
    result = worker(args.db, args.worker, args.dimension, args.repeats, args.k) if args.worker else \
        run(args.rows, args.dimension, args.repeats, args.k)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
