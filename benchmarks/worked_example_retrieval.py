"""Compare the previous worked-example ranker with indexed, cached retrieval.

Synthetic local data only; no model, training, network or user database access.
Run: python -m benchmarks.worked_example_retrieval --rows 500 --repeats 80
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import platform
import sqlite3
from statistics import median
from tempfile import TemporaryDirectory
from time import perf_counter

from star import worked_examples as examples


TOPICS = (
    "DataStoreService inventory autosave retries",
    "TweenService menu transparency easing",
    "CollectionService collectible tag scanning",
    "PathfindingService enemy waypoint navigation",
    "RemoteEvent shop purchase validation",
    "CFrame turret directional alignment",
    "Vector3 projectile ballistic velocity",
    "RunService heartbeats rotating platform",
    "UserInputService sprint keyboard stamina",
    "MarketplaceService receipt processing idempotence",
)


def legacy_rank(prompt: str, rows: list[examples.Example], *, limit: int = 2):
    """Pre-change algorithm from 9fcb2b2, with the same already-warm term cache.

    Kept here as an explicit comparison, not as a production alternate path.
    """
    if type(prompt) is not str or not 1 <= limit <= 2:
        return []
    query = set(examples.terms(prompt))
    if len(query) < 2 or not rows:
        return []
    docs = [examples._document(row) for row in rows]
    lengths = [sum(doc.values()) for doc in docs]
    average = max(1.0, sum(lengths) / len(lengths))
    frequency = Counter(token for doc in docs for token in doc)
    found = []
    for row, doc, length in zip(rows, docs, lengths):
        overlap = query & doc.keys()
        if len(overlap) < 2 or len(overlap) / len(query) < .40:
            continue
        value = sum(
            math.log1p((len(rows) - frequency[word] + .5) / (frequency[word] + .5))
            * doc[word] * 2.2 / (doc[word] + 1.2 * (.25 + .75 * length / average))
            for word in overlap)
        if value >= examples.MIN_SCORE:
            found.append((row, value))
    found.sort(key=lambda item: (-item[1], item[0].id))
    return found[:limit]


def _rows(count: int) -> list[examples.Example]:
    return [examples.Example(
        f"practice-{i:04d}", f"group-{i:04d}", "synthetic",
        "Implement " + TOPICS[i % len(TOPICS)] + f" revision{i}",
        "-- Synthetic retrieval fixture, no program is executed.\n"
        + f"local variant = {i}\n"
        + "local result = Vector3.new(variant, 0, 0)\nreturn result\n",
    ) for i in range(count)]


def run(rows: int = 500, repeats: int = 80) -> dict:
    if not 20 <= rows <= examples.MAX_ROWS or not 10 <= repeats <= 500:
        raise ValueError("rows must be 20..500 and repeats 10..500")
    corpus = _rows(rows)
    queries = ["Could you implement " + topic + "?" for topic in TOPICS] + ["hello there", "quasar telescope"]
    indexed_rank = examples.rank
    examples._DOCUMENTS.clear()
    examples._compile_corpus.cache_clear()
    expected = [legacy_rank(q, corpus) for q in queries]
    start = perf_counter()
    assert indexed_rank(queries[0], corpus) == expected[0]
    first_index_ms = (perf_counter() - start) * 1000
    timings: dict[str, list[float]] = {"legacy_rank": [], "indexed_rank": [], "legacy_select": [], "indexed_select": []}
    for i in range(repeats):
        q = queries[i % len(queries)]
        # Alternate order to reduce systematic warmup or timer-order bias.
        arms = [("legacy_rank", legacy_rank), ("indexed_rank", indexed_rank)]
        for name, ranker in arms[::1 if i % 2 == 0 else -1]:
            start = perf_counter()
            found = ranker(q, corpus)
            timings[name].append((perf_counter() - start) * 1000)
            assert found == expected[i % len(queries)]

    with TemporaryDirectory(prefix="litha-examples-bench-") as folder:
        home = Path(folder)
        with sqlite3.connect(home / "worked_examples.sqlite3") as db:
            db.execute("CREATE TABLE worked_examples (project TEXT, id TEXT, group_id TEXT, "
                       "category TEXT, instruction TEXT, response TEXT, PRIMARY KEY(project,id))")
            db.executemany("INSERT INTO worked_examples VALUES (?,?,?,?,?,?)", [
                ("BENCH", row.id, row.group_id, row.category, row.instruction, row.response) for row in corpus])
        try:
            examples.rank = legacy_rank
            expected_select = [examples.select(home, "BENCH", q) for q in queries]
            examples.rank = indexed_rank
            for q, answer in zip(queries, expected_select):
                assert examples.select(home, "BENCH", q) == answer
            for i in range(repeats):
                q = queries[i % len(queries)]
                arms = [("legacy_select", legacy_rank), ("indexed_select", indexed_rank)]
                for name, ranker in arms[::1 if i % 2 == 0 else -1]:
                    examples.rank = ranker
                    start = perf_counter()
                    answer = examples.select(home, "BENCH", q)
                    timings[name].append((perf_counter() - start) * 1000)
                    assert answer == expected_select[i % len(queries)]
        finally:
            examples.rank = indexed_rank
    medians = {name: median(samples) for name, samples in timings.items()}
    return {
        "rows": rows, "repeats_per_arm": repeats, "queries": len(queries),
        "python": platform.python_version(), "platform": platform.system(),
        "baseline_algorithm_commit": "9fcb2b257446ede0ca82d33e222e470a51bcc838",
        "first_corpus_index_ms_with_warm_terms": round(first_index_ms, 4),
        "median_ms": {name: round(value, 4) for name, value in medians.items()},
        "rank_speedup_x": round(medians["legacy_rank"] / medians["indexed_rank"], 3),
        "full_select_speedup_x": round(medians["legacy_select"] / medians["indexed_select"], 3),
        "exact_scores_rows_and_context_parity": True,
        "note": "Synthetic CPU retrieval only; not training throughput, model quality, or end-to-end inference speed.",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=500)
    parser.add_argument("--repeats", type=int, default=80)
    args = parser.parse_args()
    print(json.dumps(run(args.rows, args.repeats), indent=2))


if __name__ == "__main__":
    main()
