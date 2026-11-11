"""Offline quality/latency evaluator for STAR's installed Agent Skill retrieval.

Input JSONL contains only a task query and the gold skill names for that query.
The runner never downloads a corpus, calls a model, or executes skill contents.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import statistics
import sys
import time
from typing import Callable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from star.agent_skills import SkillLibrary  # noqa: E402

_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class RetrievalCase:
    query: str
    relevant_skills: tuple[str, ...]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_cases(path: Path, *, max_records: int = 10_000) -> list[RetrievalCase]:
    cases: list[RetrievalCase] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            if len(line) > 16_384:
                raise ValueError(f"line {line_number} exceeds 16384 characters")
            try:
                raw = json.loads(line, object_pairs_hook=_unique_object)
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"invalid JSONL record on line {line_number}: {exc}") from exc
            if not isinstance(raw, dict) or set(raw) != {"query", "relevant_skills"}:
                raise ValueError(
                    f"line {line_number} must contain exactly query and relevant_skills"
                )
            query = raw["query"]
            relevant = raw["relevant_skills"]
            if not isinstance(query, str) or not 2 <= len(query.strip()) <= 200:
                raise ValueError(f"line {line_number} query must contain 2..200 characters")
            if (not isinstance(relevant, list) or not relevant
                    or any(not isinstance(name, str) or not _NAME.fullmatch(name)
                           for name in relevant)):
                raise ValueError(
                    f"line {line_number} relevant_skills must be a non-empty list of skill names"
                )
            names = tuple(dict.fromkeys(relevant))
            cases.append(RetrievalCase(query=query, relevant_skills=names))
            if len(cases) > max_records:
                raise ValueError(f"dataset exceeds {max_records} records")
    if not cases:
        raise ValueError("dataset contains no evaluation records")
    return cases


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def evaluate_cases(
    cases: Sequence[RetrievalCase],
    search: Callable[[str], list[dict]],
    *,
    k: int = 5,
) -> dict[str, int | float]:
    """Report retrieval quality and cold/warm query latency without raw queries."""
    if not cases:
        raise ValueError("at least one retrieval case is required")
    if type(k) is not int or not 1 <= k <= 20:
        raise ValueError("k must be an integer from 1 to 20")

    first_pass_ms: list[float] = []
    warm_pass_ms: list[float] = []
    recall_total = 0.0
    reciprocal_rank_total = 0.0
    ndcg_total = 0.0
    relevant_label_count = 0

    for case in cases:
        start = time.perf_counter_ns()
        results = search(case.query)
        first_pass_ms.append((time.perf_counter_ns() - start) / 1_000_000)
        if not isinstance(results, list):
            raise TypeError("skill search must return a list")
        names = [
            item["name"] for item in results[:k]
            if isinstance(item, dict) and isinstance(item.get("name"), str)
        ]
        relevant = set(case.relevant_skills)
        relevant_label_count += len(relevant)
        hits = sum(1 for name in names if name in relevant)
        recall_total += hits / len(relevant)

        first_relevant_rank = next(
            (rank for rank, name in enumerate(names, start=1) if name in relevant),
            None,
        )
        if first_relevant_rank is not None:
            reciprocal_rank_total += 1.0 / first_relevant_rank

        dcg = sum(
            1.0 / math.log2(rank + 1)
            for rank, name in enumerate(names, start=1)
            if name in relevant
        )
        ideal_hits = min(len(relevant), k)
        ideal_dcg = sum(
            1.0 / math.log2(rank + 1)
            for rank in range(1, ideal_hits + 1)
        )
        ndcg_total += dcg / ideal_dcg if ideal_dcg else 0.0

    # Repeat the same fixed queries after metadata and BM25 index warm-up.
    for case in cases:
        start = time.perf_counter_ns()
        search(case.query)
        warm_pass_ms.append((time.perf_counter_ns() - start) / 1_000_000)

    count = len(cases)
    return {
        "query_count": count,
        "k": k,
        "relevant_label_count": relevant_label_count,
        "recall_at_k": round(recall_total / count, 6),
        "mrr_at_k": round(reciprocal_rank_total / count, 6),
        "ndcg_at_k": round(ndcg_total / count, 6),
        "first_query_ms": round(first_pass_ms[0], 3),
        "first_pass_p50_ms": round(statistics.median(first_pass_ms), 3),
        "first_pass_p95_ms": round(_percentile(first_pass_ms, 0.95), 3),
        "warm_pass_p50_ms": round(statistics.median(warm_pass_ms), 3),
        "warm_pass_p95_ms": round(_percentile(warm_pass_ms, 0.95), 3),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", required=True, type=Path, help="local gold-label JSONL")
    parser.add_argument("--home", required=True, type=Path, help="STAR profile home")
    parser.add_argument("--workspace", type=Path, help="optional selected project workspace")
    parser.add_argument("--bundled", type=Path, help="optional bundled skills directory")
    parser.add_argument("--k", type=int, default=5, help="retrieval cutoff (1..20)")
    args = parser.parse_args()
    if not 1 <= args.k <= 20:
        parser.error("--k must be between 1 and 20")

    try:
        cases = load_cases(args.queries)
        library = SkillLibrary(
            workspace=args.workspace,
            home=args.home,
            bundled=args.bundled,
        )
        report = evaluate_cases(
            cases,
            lambda query: library.search(query, limit=args.k),
            k=args.k,
        )
        report["catalog_skill_count"] = len(library.catalog())
    except (OSError, ValueError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
