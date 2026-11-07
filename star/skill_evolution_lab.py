"""Bounded skill evolution with development feedback and sealed holdout referee.

GEPA-inspired *candidate search* using injected, host-owned model/evaluator
callbacks. This module does not execute, overwrite, auto-deploy or train code.
The model proposer never sees the sealed holdout cases or their scores.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Callable

from . import frontier_lab, selfbuild

MAX_VARIANTS = 8
MAX_SKILL_CHARS = 6_000
_NAME = re.compile(r"^docs/skills/[A-Za-z0-9][A-Za-z0-9_-]{0,70}\.md$")
_FORBIDDEN = re.compile(
    r"(?:ignore\s+(?:all\s+)?(?:previous|system|developer)\s+instructions|"
    r"disable\s+(?:evaluation|testing|safety|approval)|"
    r"(?:read|print|exfiltrate)\s+(?:secrets?|passwords?|tokens?|private\s+keys?)|"
    r"(?:auto[- ]?merge|publish\s+without\s+approval|skip\s+human\s+review))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EvolutionConfig:
    path: str
    variants: int = 4
    minimum_holdout_tasks: int = 8
    repeats: int = 2

    def __post_init__(self):
        if (type(self.path) is not str or not _NAME.fullmatch(self.path)
                or not selfbuild.skill_path(self.path)):
            raise ValueError("Only docs/skills/<name>.md may evolve")
        if type(self.variants) is not int or not 2 <= self.variants <= MAX_VARIANTS:
            raise ValueError("Evolution has a 2..8 variant cap")
        if type(self.minimum_holdout_tasks) is not int or self.minimum_holdout_tasks < 5:
            raise ValueError("At least five independent holdout tasks are needed")
        if type(self.repeats) is not int or not 2 <= self.repeats <= 5:
            raise ValueError("At least two paired repeats are needed")


def validate_skill(text: str) -> str:
    """Validate *candidate data*. Passing is never permission to execute it."""
    if type(text) is not str or not 40 <= len(text) <= MAX_SKILL_CHARS:
        raise ValueError("Skill candidate has invalid content length")
    if "\x00" in text or _FORBIDDEN.search(text):
        raise ValueError("Skill attempts a privileged instruction or contains forbidden content")
    if re.search(r"(?:-----BEGIN [A-Z ]+PRIVATE KEY-----|"
                 r"(?i:sk-[A-Za-z0-9_-]{24,}))", text):
        raise ValueError("Possible secret in a skill")
    return text


def identity(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _development_result(result: object) -> tuple[float, dict]:
    if not isinstance(result, dict) or set(result) != {
        "executed", "passed", "total", "hard_failure", "feedback", "evaluator",
    }:
        raise ValueError("Development check lacks independently recorded evidence")
    if (result["executed"] is not True or type(result["passed"]) is not int
            or type(result["total"]) is not int or not 1 <= result["total"] <= 500
            or not 0 <= result["passed"] <= result["total"]
            or type(result["hard_failure"]) is not bool
            or not isinstance(result["evaluator"], str) or not result["evaluator"].strip()
            or not isinstance(result["feedback"], str)
            or len(result["feedback"]) > 1500):
        raise ValueError("Malformed development evaluation")
    if result["hard_failure"]:
        return -1.0, {"passed": result["passed"], "total": result["total"],
                      "feedback": result["feedback"][:1200], "hard_failure": True}
    return result["passed"] / result["total"], {
        "passed": result["passed"], "total": result["total"],
        "feedback": result["feedback"][:1200], "hard_failure": False,
    }


async def propose_and_compare(
    config: EvolutionConfig, base_skill: str, *,
    mutate: Callable,
    development_evaluate: Callable,
    sealed_holdout_evaluate: Callable,
) -> dict:
    """Run model mutations only on development feedback; then a sealed holdout.

    Callbacks are dependencies chosen in trusted application code. No callback
    is exposed as a model-selectable shell, file writer or test-grader editor.
    Never send sealed holdout results back into mutate/development calls.
    """
    baseline = validate_skill(base_skill)
    if not all(callable(fn) for fn in (mutate, development_evaluate, sealed_holdout_evaluate)):
        raise TypeError("The trusted host must supply model and independent evaluators")
    # The incumbent must be tested on the very same development evaluator first.
    # Otherwise the first valid mutation always "wins" against -1.0, even if it is
    # worse than the skill Star already uses. This adds one cheap development check
    # while avoiding expensive sealed-holdout calls for non-improvements.
    try:
        baseline_evidence = await development_evaluate(baseline)
        baseline_score, baseline_feedback = _development_result(baseline_evidence)
    except (TypeError, ValueError) as exc:
        return {"decision": "do_not_promote", "reason": "baseline_development_invalid",
                "error_type": type(exc).__name__, "candidate_sha256": None,
                "iterations": [], "holdout_disclosed_to_mutator": False,
                "executed_changes": False}
    if baseline_score < 0:
        return {"decision": "do_not_promote", "reason": "baseline_development_hard_failure",
                "candidate_sha256": None, "iterations": [],
                "holdout_disclosed_to_mutator": False, "executed_changes": False}
    if baseline_score == 1:
        # This search optimizes development correctness, not latency or style.
        # With no failing development tasks, evidence of a strict gain is absent.
        return {"decision": "do_not_promote", "reason": "baseline_development_at_ceiling",
                "baseline_development_score": 1.0, "candidate_sha256": None, "iterations": [],
                "holdout_disclosed_to_mutator": False, "executed_changes": False}

    best_text, best_score = baseline, baseline_score
    feedback = baseline_feedback
    accepted = []
    seen = {identity(baseline)}
    for index in range(config.variants):
        # Development feedback is allowed; sealed-holdout feedback is never seen
        # by the proposer. The model does not choose the evaluator or its tasks.
        draft = await mutate(best_text, dict(feedback), index)
        try:
            text = validate_skill(draft)
        except ValueError:
            accepted.append({"index": index, "status": "rejected", "reason": "invalid_skill"})
            continue
        hashed = identity(text)
        if hashed in seen:
            accepted.append({"index": index, "status": "duplicate"})
            continue
        seen.add(hashed)
        try:
            development_record = await development_evaluate(text)
            score, detail = _development_result(development_record)
        except (TypeError, ValueError):
            accepted.append({"index": index, "status": "unverified_development"})
            continue
        # Ratios from a different evaluator/version or task count are not paired
        # evidence. They must never displace the baseline or current winner.
        # A trusted runner must keep its task identities fixed within one run.
        if (development_record["evaluator"] != baseline_evidence["evaluator"]
                or development_record["total"] != baseline_evidence["total"]):
            accepted.append({"index": index, "status": "incomparable_development",
                             "digest": hashed})
            continue
        accepted.append({"index": index, "status": "tested", "score": round(score, 4),
                         "digest": hashed, "improves_incumbent": score > baseline_score})
        feedback = detail
        if score > best_score:
            best_score, best_text = score, text
    if best_text == baseline:
        return {"decision": "do_not_promote", "reason": "no_development_improvement",
                "baseline_development_score": round(baseline_score, 4),
                "candidate_sha256": None, "iterations": accepted,
                "holdout_disclosed_to_mutator": False, "executed_changes": False}

    # Candidate selection is frozen BEFORE the sealed holdout is evaluated.
    # The independent runner must own the actual tests and provenance records.
    try:
        baseline_trials = await sealed_holdout_evaluate("baseline", baseline)
        candidate_trials = await sealed_holdout_evaluate("candidate", best_text)
        if (not isinstance(baseline_trials, list) or not isinstance(candidate_trials, list)
                or any(type(x) is not frontier_lab.Trial for x in
                       baseline_trials + candidate_trials)):
            raise ValueError("Holdout evaluator must return trusted Trial objects")
        if any(t.candidate != "baseline" for t in baseline_trials) or any(
            t.candidate != "candidate" for t in candidate_trials
        ):
            raise ValueError("Holdout labels do not match the evaluated skill")
        report = frontier_lab.candidate_report(
            baseline_trials + candidate_trials, baseline="baseline",
            candidate="candidate", repeats=config.repeats,
            minimum_holdout_tasks=config.minimum_holdout_tasks,
        )
    except (ValueError, TypeError, KeyError, ZeroDivisionError) as exc:
        return {"decision": "do_not_promote", "reason": "holdout_evaluation_invalid",
                "error_type": type(exc).__name__,
                "candidate_sha256": identity(best_text), "iterations": accepted,
                "baseline_development_score": round(baseline_score, 4),
                "holdout_disclosed_to_mutator": False, "executed_changes": False}
    return {
        "decision": report["decision"], "candidate_sha256": identity(best_text),
        "baseline_sha256": identity(baseline), "target": config.path,
        "candidate_text": best_text if report["decision"] == "candidate_for_independent_review" else None,
        "development_score": round(best_score, 4),
        "baseline_development_score": round(baseline_score, 4), "iterations": accepted,
        "holdout_summary": report,
        "holdout_disclosed_to_mutator": False, "executed_changes": False,
        "owner_review_required": True, "promoted": False, "weights_changed": False,
    }
