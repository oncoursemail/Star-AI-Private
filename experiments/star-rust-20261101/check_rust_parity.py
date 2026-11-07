"""Rerun 40 archived parity cases; no timing-speedup or live AI claim."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import random
import subprocess


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path, required=True,
                        help="trusted, locally compiled historical pilot executable")
    args = parser.parse_args()
    exe = args.exe.resolve(strict=True)
    if not exe.is_file():
        parser.error("--exe must identify a file")
    path = Path(__file__).parent / "historical/rust-pilot/benchmark.py"
    spec = importlib.util.spec_from_file_location("archived_rrf_benchmark", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rng = random.Random(10530)
    cases = [[], [[]], [[], [20], [10]], [[7, 7]], [[1, 2], [2, 3], [2, 4]], [[-1, 2], [3]]]
    for _ in range(34):
        cases.append([[rng.randrange(-50, 100) for _ in range(rng.randrange(0, 50))]
                      for _ in range(rng.randrange(1, 10))])
    for rankings in cases:
        output, _, _ = module.native(exe, rankings)
        module.check_equal(module.python_fuse(rankings), output)
    # Probe the CLI error contract separately from successful parity cases.
    for payload in ("1,foo", "\n" * 16, "1," * 20_000 + "1"):
        result = subprocess.run([str(exe)], input=payload, capture_output=True, text=True,
                                timeout=30, check=False)
        if result.returncode != 2 or result.stdout:
            raise RuntimeError("invalid input did not fail with the expected error contract")
    print(json.dumps({"parity_cases_passed": len(cases), "invalid_cli_probes_passed": 3,
                      "timing_benchmark_rerun": False, "production_backend_tested": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
