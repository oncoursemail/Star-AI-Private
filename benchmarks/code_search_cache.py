"""Bounded synthetic workload for STAR's source-search cache.

Runs no models or remote services and touches no user source files.
python -m benchmarks.code_search_cache --files 300 --repeats 8
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

from star.code_navigation import clear_source_cache, search_workspace, source_cache_stats
from star.workspace import Workspace


def run(files: int = 300, repeats: int = 8) -> dict:
    if not 20 <= files <= 1200 or not 4 <= repeats <= 40:
        raise ValueError("files must be 20..1200 and repeats 4..40")
    samples = {"uncached": [], "warm": []}
    with TemporaryDirectory(prefix="star-code-speed-") as root_name:
        root = Path(root_name)
        for index in range(files):
            (root / f"module_{index:04d}.py").write_text(
                "class InventoryLedger:\n"
                + "".join(f"    def save_slot_{n}(self, user_id):\n        return {n + index}\n" for n in range(14)),
                encoding="utf-8",
            )
        workspace = Workspace(root)
        queries = [("save_slot", "symbols"), ("return", "text")]
        previous = os.environ.get("STAR_CODE_SEARCH_CACHE")
        try:
            os.environ["STAR_CODE_SEARCH_CACHE"] = "off"
            expected = [search_workspace(workspace, q, mode) for q, mode in queries]
            for i in range(repeats):
                q, mode = queries[i % len(queries)]
                start = perf_counter()
                answer = search_workspace(workspace, q, mode)
                samples["uncached"].append((perf_counter() - start) * 1000)
                assert answer == expected[i % len(queries)]
            clear_source_cache()
            os.environ["STAR_CODE_SEARCH_CACHE"] = "on"
            search_workspace(workspace, "save_slot", "symbols")  # warm every file
            for i in range(repeats):
                q, mode = queries[i % len(queries)]
                start = perf_counter()
                answer = search_workspace(workspace, q, mode)
                samples["warm"].append((perf_counter() - start) * 1000)
                assert answer == expected[i % len(queries)]
            stats = source_cache_stats()
        finally:
            clear_source_cache()
            if previous is None:
                os.environ.pop("STAR_CODE_SEARCH_CACHE", None)
            else:
                os.environ["STAR_CODE_SEARCH_CACHE"] = previous
    control, warm = median(samples["uncached"]), median(samples["warm"])
    return {
        "files": files, "repeats": repeats,
        "uncached_median_ms": round(control, 3),
        "warm_median_ms": round(warm, 3),
        "warm_search_speedup_x": round(control / warm, 3) if warm else None,
        "cache_entries": stats["entries"], "cache_bytes": stats["bytes"],
        "note": "Synthetic source search timing only; not full agent inference latency",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=int, default=300)
    parser.add_argument("--repeats", type=int, default=8)
    args = parser.parse_args()
    print(json.dumps(run(args.files, args.repeats), indent=2))


if __name__ == "__main__":
    main()
