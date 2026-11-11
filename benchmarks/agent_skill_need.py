"""Offline evaluator for STAR's need-aware Agent Skill incorporation.

This complements lexical retrieval metrics: finding a relevant skill is not
proof that the task needed it, that STAR chose to load it, or that loading it
improved the outcome. The evaluator makes those decisions separately visible.

The input is a locally curated JSONL artifact. No model, network, skill body,
secret, or live tool is accessed. Output contains aggregate metrics only.
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
from typing import Sequence

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$")
_SKILL = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_OUTCOMES = {"pass", "fail", "not_run"}
_NEED = {"required", "optional", "not_needed"}
_MAX_RECORDS = 10_000
_MAX_LINE_CHARS = 16_384
_MAX_QUERY_CHARS = 4_000
_MAX_SKILLS = 20
_MAX_LATENCY_MS = 60_000.0
_MAX_TOKENS = 1_000_000


@dataclass(frozen=True)
class NeedCase:
    task_id: str
    query: str
    need: str
    relevant_skills: tuple[str, ...]
    need_probability: float
    decision: str
    loaded_skills: tuple[str, ...]
    no_skill_outcome: str
    assisted_outcome: str
    load_latency_ms: float
    loaded_tokens: int

    def __post_init__(self) -> None:
        if type(self.task_id) is not str or not _ID.fullmatch(self.task_id):
            raise ValueError("invalid task_id")
        if (type(self.query) is not str or not 2 <= len(self.query.strip()) <= _MAX_QUERY_CHARS
                or "\x00" in self.query):
            raise ValueError("invalid bounded query")
        self.query.encode("utf-8")
        if type(self.need) is not str or self.need not in _NEED:
            raise ValueError("invalid need label")
        if type(self.relevant_skills) is not tuple or type(self.loaded_skills) is not tuple:
            raise ValueError("skill collections must be immutable tuples")
        _names(list(self.relevant_skills), allow_empty=self.need != "required",
               field="relevant_skills")
        _names(list(self.loaded_skills), allow_empty=True, field="loaded_skills")
        if self.need == "not_needed" and self.relevant_skills:
            raise ValueError("not_needed tasks must have no gold relevant skills")
        _finite_number(self.need_probability, field="need_probability", low=0.0, high=1.0)
        if type(self.decision) is not str or self.decision not in {"load", "skip"}:
            raise ValueError("decision must be load or skip")
        _outcome(self.no_skill_outcome, "no_skill_outcome")
        _outcome(self.assisted_outcome, "assisted_outcome")
        _finite_number(self.load_latency_ms, field="load_latency_ms", low=0.0,
                       high=_MAX_LATENCY_MS)
        if type(self.loaded_tokens) is not int or not 0 <= self.loaded_tokens <= _MAX_TOKENS:
            raise ValueError("invalid loaded_tokens")
        if self.decision == "skip" and (self.loaded_skills or self.load_latency_ms or self.loaded_tokens):
            raise ValueError("skip decisions cannot load skills or incur load cost")
        if self.loaded_skills and self.decision != "load":
            raise ValueError("loaded skills require a load decision")
        if not self.loaded_skills and (self.loaded_tokens or self.assisted_outcome != "not_run"):
            raise ValueError("skill-assisted outcomes/tokens require a loaded skill")
        if self.assisted_outcome != "not_run" and self.no_skill_outcome == "not_run":
            raise ValueError("paired skill utility requires a no-skill baseline outcome")


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _names(value: object, *, allow_empty: bool, field: str) -> tuple[str, ...]:
    if (not isinstance(value, list) or len(value) > _MAX_SKILLS
            or (not allow_empty and not value)
            or any(not isinstance(item, str) or not _SKILL.fullmatch(item)
                   for item in value)):
        raise ValueError(f"{field} must contain up to {_MAX_SKILLS} valid skill names")
    if len(set(value)) != len(value):
        raise ValueError(f"{field} must not contain duplicates")
    return tuple(value)


def _finite_number(value: object, *, field: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"{field} must be finite and within [{low}, {high}]")
    return number


def _outcome(value: object, field: str) -> str:
    if type(value) is not str or value not in _OUTCOMES:
        raise ValueError(f"{field} must be pass, fail, or not_run")
    return value


def load_cases(path: Path, *, max_records: int = _MAX_RECORDS) -> list[NeedCase]:
    if type(max_records) is not int or not 1 <= max_records <= _MAX_RECORDS:
        raise ValueError("max_records must be an integer from 1 to 10000")
    cases: list[NeedCase] = []
    seen_ids: set[str] = set()
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            if len(line) > _MAX_LINE_CHARS:
                raise ValueError(f"line {line_number} exceeds {_MAX_LINE_CHARS} characters")
            try:
                raw = json.loads(line, object_pairs_hook=_unique_object,
                                 parse_constant=_reject_constant)
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"invalid JSONL record on line {line_number}: {exc}") from exc
            expected = {
                "task_id", "query", "need", "relevant_skills", "need_probability",
                "decision", "loaded_skills", "no_skill_outcome", "assisted_outcome",
                "load_latency_ms", "loaded_tokens",
            }
            if not isinstance(raw, dict) or set(raw) != expected:
                raise ValueError(f"line {line_number} must contain exactly the declared fields")

            task_id, query, need = raw["task_id"], raw["query"], raw["need"]
            if type(task_id) is not str or not _ID.fullmatch(task_id):
                raise ValueError(f"line {line_number} has an invalid task_id")
            if task_id in seen_ids:
                raise ValueError(f"line {line_number} repeats task_id {task_id}")
            if (type(query) is not str or not 2 <= len(query.strip()) <= _MAX_QUERY_CHARS
                    or "\x00" in query):
                raise ValueError(f"line {line_number} query must contain 2..4000 characters")
            query.encode("utf-8")
            if type(need) is not str or need not in _NEED:
                raise ValueError(f"line {line_number} has an invalid need label")

            relevant = _names(raw["relevant_skills"], allow_empty=need != "required",
                              field="relevant_skills")
            if need == "not_needed" and relevant:
                raise ValueError("not_needed tasks must have no gold relevant skills")
            probability = _finite_number(raw["need_probability"], field="need_probability",
                                         low=0.0, high=1.0)
            decision = raw["decision"]
            if type(decision) is not str or decision not in {"load", "skip"}:
                raise ValueError("decision must be load or skip")
            loaded = _names(raw["loaded_skills"], allow_empty=True, field="loaded_skills")
            no_skill = _outcome(raw["no_skill_outcome"], "no_skill_outcome")
            assisted = _outcome(raw["assisted_outcome"], "assisted_outcome")
            latency = _finite_number(raw["load_latency_ms"], field="load_latency_ms",
                                     low=0.0, high=_MAX_LATENCY_MS)
            tokens = raw["loaded_tokens"]
            if type(tokens) is not int or not 0 <= tokens <= _MAX_TOKENS:
                raise ValueError(f"loaded_tokens must be an integer from 0 to {_MAX_TOKENS}")

            if decision == "skip" and (loaded or latency != 0 or tokens != 0):
                raise ValueError("skip decisions cannot load skills or incur load cost")
            if loaded and decision != "load":
                raise ValueError("loaded skills require a load decision")
            if not loaded and (tokens != 0 or assisted != "not_run"):
                raise ValueError("skill-assisted outcomes/tokens require at least one loaded skill")
            if assisted != "not_run" and no_skill == "not_run":
                raise ValueError("paired skill utility requires a no-skill baseline outcome")

            seen_ids.add(task_id)
            cases.append(NeedCase(
                task_id, query, need, relevant, probability, decision, loaded,
                no_skill, assisted, latency, tokens,
            ))
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


def evaluate_cases(cases: Sequence[NeedCase]) -> dict[str, int | float]:
    """Evaluate need decisions, skill selection, utility and loading overhead.

    Optional tasks are reported separately and excluded from binary need
    calibration because a useful-but-not-essential skill is not a false label.
    """
    if not cases or any(type(case) is not NeedCase for case in cases):
        raise ValueError("provide at least one validated NeedCase")
    if len({case.task_id for case in cases}) != len(cases):
        raise ValueError("task IDs must be unique")

    primary = [case for case in cases if case.need != "optional"]
    required = [case for case in cases if case.need == "required"]
    not_needed = [case for case in cases if case.need == "not_needed"]
    tp = sum(case.need == "required" and case.decision == "load" for case in primary)
    fn = sum(case.need == "required" and case.decision == "skip" for case in primary)
    fp = sum(case.need == "not_needed" and case.decision == "load" for case in primary)
    tn = sum(case.need == "not_needed" and case.decision == "skip" for case in primary)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    brier = (sum((case.need_probability - 1.0) ** 2 if case.need == "required"
                 else case.need_probability ** 2 for case in primary) / len(primary)
             if primary else 0.0)
    bins: list[list[tuple[float, float]]] = [[] for _ in range(10)]
    for case in primary:
        index = min(int(case.need_probability * 10), 9)
        label = 1.0 if case.need == "required" else 0.0
        bins[index].append((case.need_probability, label))
    ece = 0.0
    for bucket in bins:
        if bucket:
            confidence = sum(item[0] for item in bucket) / len(bucket)
            accuracy = sum(item[1] for item in bucket) / len(bucket)
            if primary:
                ece += len(bucket) / len(primary) * abs(confidence - accuracy)

    required_gold = sum(len(case.relevant_skills) for case in required)
    required_hits = sum(len(set(case.relevant_skills) & set(case.loaded_skills))
                        for case in required)
    all_loaded = sum(len(case.loaded_skills) for case in cases)
    all_hits = sum(len(set(case.relevant_skills) & set(case.loaded_skills))
                   for case in cases)
    false_loads = sum(case.decision == "load" or bool(case.loaded_skills)
                      for case in not_needed)
    optional_loads = sum(case.decision == "load" or bool(case.loaded_skills)
                         for case in cases if case.need == "optional")

    # Include false loads in the paired utility cohort: unnecessary skill
    # context can consume tokens or degrade a task, so it must not be hidden.
    paired = [case for case in cases
              if case.loaded_skills
              and case.no_skill_outcome in {"pass", "fail"}
              and case.assisted_outcome in {"pass", "fail"}]
    baseline_passes = sum(case.no_skill_outcome == "pass" for case in paired)
    assisted_passes = sum(case.assisted_outcome == "pass" for case in paired)
    wins = sum(case.assisted_outcome == "pass" and case.no_skill_outcome == "fail"
               for case in paired)
    losses = sum(case.assisted_outcome == "fail" and case.no_skill_outcome == "pass"
                 for case in paired)
    load_attempts = [case.load_latency_ms for case in cases if case.decision == "load"]

    return {
        "task_count": len(cases),
        "required_count": len(required),
        "not_needed_count": len(not_needed),
        "optional_count": sum(case.need == "optional" for case in cases),
        "need_decision_true_positive": tp,
        "need_decision_false_positive": fp,
        "need_decision_false_negative": fn,
        "need_decision_true_negative": tn,
        "need_decision_precision": round(precision, 6),
        "need_decision_recall": round(recall, 6),
        "need_decision_f1": round(f1, 6),
        "need_probability_brier": round(brier, 6),
        "need_probability_ece_10_bins": round(ece, 6),
        "required_task_load_rate": round(
            sum(case.decision == "load" for case in required) / len(required), 6
        ) if required else 0.0,
        "required_gold_skill_recall": round(required_hits / required_gold, 6)
        if required_gold else 0.0,
        "loaded_skill_precision": round(all_hits / all_loaded, 6) if all_loaded else 0.0,
        "not_needed_false_load_rate": round(false_loads / len(not_needed), 6)
        if not_needed else 0.0,
        "optional_load_rate": round(optional_loads / sum(case.need == "optional" for case in cases), 6)
        if any(case.need == "optional" for case in cases) else 0.0,
        "skill_assisted_pair_count": len(paired),
        "no_skill_pass_rate_on_pairs": round(baseline_passes / len(paired), 6) if paired else 0.0,
        "skill_assisted_pass_rate_on_pairs": round(assisted_passes / len(paired), 6) if paired else 0.0,
        "paired_success_gain": round((assisted_passes - baseline_passes) / len(paired), 6)
        if paired else 0.0,
        "paired_candidate_wins": wins,
        "paired_candidate_losses": losses,
        "load_attempt_count": len(load_attempts),
        "load_latency_p50_ms": round(statistics.median(load_attempts), 3) if load_attempts else 0.0,
        "load_latency_p95_ms": round(_percentile(load_attempts, 0.95), 3),
        "loaded_tokens_total": sum(case.loaded_tokens for case in cases),
        "loaded_tokens_mean_per_task": round(sum(case.loaded_tokens for case in cases) / len(cases), 3),
    }


def main(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path,
                        help="locally curated, aggregate-safe need-decision JSONL")
    parser.add_argument("--out", type=Path, help="optional new JSON report path (must not exist)")
    args = parser.parse_args(arguments)
    try:
        report = evaluate_cases(load_cases(args.cases))
        text = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.out is None:
            print(text, end="")
        else:
            with args.out.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
