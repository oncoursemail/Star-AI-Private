"""Reproduce offline streaming speech chunking overhead on synthetic text.

Usage:
  python scripts/bench_voice_chunker_fastpath.py BASELINE_CHUNKER_PY CANDIDATE_CHUNKER_PY

No microphone, OBS, model server, network, or user messages are accessed.
Always compare on the same idle machine. This benchmarks chunking CPU only,
not model inference, TTS, playback, animation, game FPS or user-perceived delay.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import random
from statistics import median
from time import perf_counter


SAMPLES = {
    "gameplay": "Okay, I saw the jump. That was close! We can try again, because the platform is moving. " * 15,
    "explanation": "We should inspect the server first, then check all the props. I will run a safe playtest before changing anything. " * 15,
    "protected_markup": (
        "Here is the plan. <think>private reasoning code. hidden details!</think> "
        "We should move to checkpoint two. ```lua\nprint(1)\n``` Let us build that. " * 12
    ),
}


def load_chunker(label: str, file: Path):
    spec = importlib.util.spec_from_file_location(label, file)
    if spec is None or spec.loader is None:
        raise ValueError(f"could not load {label} chunker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SentenceChunker


def consume(chunker_cls, deltas: list[str]) -> list[str]:
    chunker = chunker_cls()
    output: list[str] = []
    for part in deltas:
        output.extend(chunker.feed(part))
    output.extend(chunker.flush())
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--trials", type=int, default=7)
    parser.add_argument("--iterations", type=int, default=100)
    args = parser.parse_args()
    if not 3 <= args.trials <= 30 or not 10 <= args.iterations <= 1000:
        parser.error("trials must be 3..30 and iterations 10..1000")
    classes = {
        "baseline": load_chunker("chunker_baseline", args.baseline),
        "candidate": load_chunker("chunker_candidate", args.candidate),
    }
    rng = random.Random(20261030)
    results = []
    for label, source in SAMPLES.items():
        for token_size in (1, 4, 12):
            deltas = [source[i:i + token_size] for i in range(0, len(source), token_size)]
            if consume(classes["baseline"], deltas) != consume(classes["candidate"], deltas):
                raise AssertionError(f"chunk boundaries changed for {label}/{token_size}")
            times: dict[str, list[float]] = {"baseline": [], "candidate": []}
            for _ in range(args.trials):
                names = ["baseline", "candidate"]
                rng.shuffle(names)
                for name in names:
                    start = perf_counter()
                    for _ in range(args.iterations):
                        consume(classes[name], deltas)
                    times[name].append(1000 * (perf_counter() - start) / args.iterations)
            before = median(times["baseline"])
            after = median(times["candidate"])
            results.append({
                "scenario": label, "token_size": token_size,
                "baseline_ms": round(before, 4),
                "candidate_ms": round(after, 4),
                "speedup_x": round(before / after, 3),
            })
    print(json.dumps({"synthetic_only": True, "trial_count": args.trials,
                      "iterations_per_trial": args.iterations,
                      "cases": results}, indent=2))


if __name__ == "__main__":
    main()