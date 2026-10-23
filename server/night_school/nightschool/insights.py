"""Read-only evidence limits from Night School's stored state.

These are descriptions of recorded outcomes, not capability scores or causal
diagnoses. In particular, retry counts are not independent trials and a stored
outcome can predate a later checker error. No tasks, settings or lessons change.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class Insights:
    passed: int
    repaired: int
    failed: int
    no_final_outcome: int
    checker_incomplete: int
    unrecognized: int
    error_history: int
    candidates_with_little_evidence: int
    failure_families: tuple[tuple[str, int], ...]
    validation_recorded: bool
    validation_missing: int


def _count(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _family(cause) -> str:
    """Only fixed labels leave the helper; raw check text can contain private data."""
    if not isinstance(cause, str):
        return "unclassified check"
    exact = {
        "no answer": "missing answer",
        "no Luau code block in the answer": "missing code block",
        "code does not compile or type-check": "compile/type-check",
        "unit tests: the code did not load": "test loading",
        "unit tests: timed out": "test timeout",
        "unit tests fail (wrong logic)": "unit-test assertion",
        "types too loose (a wrong call is accepted)": "type coverage",
        "documentation source not cited": "missing citation",
    }
    if cause in exact:
        return exact[cause]
    if cause.startswith("required element missing"):
        return "missing required element"
    if cause.startswith("forbidden pattern used"):
        return "forbidden pattern"
    return "unclassified check"


def summarize(state: dict) -> Insights:
    """Aggregate stored practice evidence without exposing IDs or reading evaluation files."""
    outcomes: Counter = Counter()
    families: Counter = Counter()
    tasks = state.get("tasks", {})
    for task in tasks.values() if isinstance(tasks, dict) else ():
        if not isinstance(task, dict):
            outcomes["unrecognized"] += 1
            continue
        status = task.get("status")
        has_error = bool(_count(task.get("errors"))) or bool(
            isinstance(task.get("last_error"), str) and task["last_error"].strip())
        if has_error or status == "error":
            outcomes["error_history"] += 1
        if status in ("passed_first", "fixed", "failed"):
            outcomes[status] += 1
            if status == "failed":
                families[_family(task.get("cause"))] += 1
        elif status in (None, "", "error"):
            outcomes["no_final_outcome"] += 1
            if has_error or status == "error":
                outcomes["checker_incomplete"] += 1
        else:
            outcomes["unrecognized"] += 1

    candidates = 0
    lessons = state.get("lessons", {})
    for lesson in lessons.values() if isinstance(lessons, dict) else ():
        if not isinstance(lesson, dict) or lesson.get("status") != "candidate":
            continue
        fixed = lesson.get("fixed", [])
        unique = {item for item in fixed if isinstance(item, str) and item.strip()} if isinstance(fixed, list) else set()
        candidates += len(unique) < 2

    validation = state.get("validation", [])
    measured = any(
        isinstance(row, dict) and _count(row.get("total")) > 0
        and isinstance(row.get("passed"), int) and not isinstance(row.get("passed"), bool)
        and 0 <= row["passed"] <= row["total"]
        for row in validation
    ) if isinstance(validation, list) else False
    return Insights(
        passed=outcomes["passed_first"], repaired=outcomes["fixed"], failed=outcomes["failed"],
        no_final_outcome=outcomes["no_final_outcome"], checker_incomplete=outcomes["checker_incomplete"],
        unrecognized=outcomes["unrecognized"], error_history=outcomes["error_history"],
        candidates_with_little_evidence=candidates,
        failure_families=tuple(sorted(families.items(), key=lambda item: (-item[1], item[0]))),
        validation_recorded=measured, validation_missing=_count(state.get("validation_missing")),
    )


def build(state: dict) -> list[str]:
    """Compact report section; suggestions collect evidence and never enable a change."""
    facts = summarize(state)
    lines = [
        "## Evidence limits and next checks",
        f"Stored task status: {facts.passed} passed, {facts.repaired} lesson-repaired, {facts.failed} failed; "
        f"{facts.no_final_outcome} without a stored final outcome ({facts.checker_incomplete} checker-error/incomplete); "
        f"{facts.unrecognized} unrecognized.",
        f"Checker-error history: {facts.error_history} tasks; stored outcomes may predate later errors.",
        f"Candidates fixing fewer than 2 distinct tasks: {facts.candidates_with_little_evidence}. "
        "Distinct IDs alone do not prove transfer.",
    ]
    if facts.checker_incomplete:
        lines.append("An incomplete outcome may follow an initial judged failure; the final retry is not established.")
    if facts.failure_families:
        lines.append("Failed-task check families (heuristic): " + "; ".join(
            f"{name} {count}" for name, count in facts.failure_families[:3]) + ".")
    lines.append("Validation: " + ("summary recorded" if facts.validation_recorded else "no valid summary recorded")
                 + f"; missing reserved tasks: {facts.validation_missing}.")
    if facts.validation_missing:
        action = "restore missing validation inputs before requesting the existing paired gate."
    elif facts.unrecognized:
        action = "inspect unrecognized stored states before interpreting capability."
    elif facts.checker_incomplete:
        action = "verify check readiness for one incomplete task and obtain a complete outcome."
    elif facts.candidates_with_little_evidence:
        action = "try one new practice variant for a candidate before requesting the existing paired gate."
    elif any(count > 1 and name != "unclassified check" for name, count in facts.failure_families):
        action = "isolate one recurring failed-check family with a new practice variant."
    elif not facts.validation_recorded:
        action = "collect a validation summary through the existing gate before claiming improvement."
    else:
        action = "check transfer on one new practice variant; keep the existing promotion gate."
    lines += ["Next evidence: " + action,
              "Scope: retries are not independent trials; this state does not establish live Studio transfer."]
    return lines
