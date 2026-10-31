"""Evidence summaries must not inflate retries, stale errors or candidate repairs."""
from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server" / "night_school"))

from nightschool import insights, report  # noqa: E402


def test_stored_outcomes_keep_historical_errors_and_stale_causes_separate():
    state = {"tasks": {
        "success": {"status": "passed_first", "tries": 300, "errors": 4,
                    "last_error": "old checker failure", "cause": "unit tests fail (wrong logic)"},
        "repair": {"status": "fixed", "tries": 20, "cause": "unit tests fail (wrong logic)"},
        "failure": {"status": "failed", "tries": 1, "cause": "code does not compile or type-check"},
        "error": {"status": "error", "tries": 8, "errors": 20},
        "first-error": {"status": "", "tries": 0, "last_error": "checker offline"},
        "not-judged": {"status": "", "tries": 0},
        "unknown": {"status": "new-status", "tries": 4},
    }}
    before = deepcopy(state)
    facts = insights.summarize(state)
    assert (facts.passed, facts.repaired, facts.failed) == (1, 1, 1)
    assert (facts.no_final_outcome, facts.checker_incomplete, facts.unrecognized) == (3, 2, 1)
    assert facts.error_history == 3
    assert facts.failure_families == (("compile/type-check", 1),)
    assert "stored outcomes may predate later errors" in "\n".join(insights.build(state))
    assert state == before


def test_duplicate_repairs_do_not_establish_transfer_or_reveal_task_ids():
    state = {"lessons": {
        "one": {"status": "candidate", "fixed": ["PRIVATE-TASK"] * 100},
        "none": {"status": "candidate", "fixed": []},
        "two": {"status": "candidate", "fixed": ["PRIVATE-TASK", "OTHER-TASK"]},
        "active": {"status": "active", "fixed": []},
    }, "validation_ids": ["SEALED-HOLDOUT-ID"], "validation": []}
    facts = insights.summarize(state)
    assert facts.candidates_with_little_evidence == 2
    text = "\n".join(insights.build(state))
    assert "try one new practice variant for a candidate" in text
    assert "PRIVATE-TASK" not in text and "OTHER-TASK" not in text and "SEALED-HOLDOUT-ID" not in text
    assert "promote to active" not in text


def test_only_fixed_family_labels_are_exposed_and_counts_are_per_failed_task():
    state = {"tasks": {
        "a": {"status": "failed", "tries": 500, "cause": "unit tests fail (wrong logic)"},
        "b": {"status": "failed", "tries": 1, "cause": "unit tests fail (wrong logic)"},
        "c": {"status": "failed", "cause": "PRIVATE\n## inject\nBearer secret"},
        "d": {"status": "failed", "cause": "required element missing (PRIVATE-TASK)"},
    }, "validation": [{"passed": 1, "total": 2}]}
    facts = insights.summarize(state)
    assert dict(facts.failure_families)["unit-test assertion"] == 2
    text = "\n".join(insights.build(state))
    assert "isolate one recurring failed-check family" in text
    assert "PRIVATE" not in text and "Bearer" not in text and "inject" not in text
    assert "500" not in text


def test_validation_gap_takes_precedence_without_exposing_validation_data():
    state = {"validation_missing": 3, "validation_ids": ["SECRET-VALIDATION-ID"],
             "validation": [{"passed": 0, "total": 2, "prompt": "SECRET-PROMPT"}],
             "tasks": {"x": {"status": "error"}}}
    facts = insights.summarize(state)
    assert facts.validation_recorded and facts.validation_missing == 3
    text = "\n".join(insights.build(state))
    assert "restore missing validation inputs" in text
    assert "SECRET" not in text


def test_empty_or_unrecognized_evidence_is_not_a_success_claim():
    text = "\n".join(insights.build({}))
    assert "0 passed" in text and "no valid summary recorded" in text
    assert "this state does not establish live Studio transfer" in text
    facts = insights.summarize({"tasks": {"x": None}, "lessons": None,
                               "validation": [{"passed": True, "total": 1}],
                               "validation_missing": True})
    assert facts.unrecognized == 1 and not facts.validation_recorded and facts.validation_missing == 0


def test_report_integration_retains_bounded_output_and_does_not_mutate_state():
    state = {"tasks": {"private-task": {"status": "failed", "tries": 999,
                                      "cause": "unit tests fail (wrong logic)"}},
             "validation": [], "causes": {}, "lessons": {}, "counters": {}}
    before = deepcopy(state)
    text = report.build(state)
    assert "## Evidence limits and next checks" in text
    assert "## Validation slice over time" in text and "## Most common failure causes" in text
    assert len(text) <= report.LIMIT
    assert "private-task" not in text and "999" not in text
    assert state == before


def test_loaded_report_keeps_validation_and_failure_evidence_after_trimming_details():
    lessons = {}
    for index, status in enumerate(["active"] * 6 + ["candidate"] * 4 + ["retired"] * 3, 1):
        lessons[f"L{index}"] = {"id": f"L{index}", "status": status, "text": "lesson " * 36,
                               "fixed": ["practice-a", "practice-b"], "promoted": "2026-10-12"}
    state = {"lessons": lessons,
             "validation": [{"ts": "2026-10-12T00:00:00Z", "passed": 2, "total": 3,
                             "active_lessons": [], "why": "paired comparison"}],
             "causes": {"unit tests fail (wrong logic)": {"count": 4, "example": "observed assertion failed"}}}
    before = deepcopy(state)
    text = report.build(state)
    for expected in ("## Evidence limits and next checks", "- active L1:", "## Validation slice over time",
                     "2/3", "paired comparison", "## Most common failure causes", "observed assertion failed"):
        assert expected in text
    assert "detail shortened" in text and len(text) <= report.LIMIT
    assert state == before


def test_unavailable_retry_after_judged_failure_is_incomplete_not_error_only(tmp_path):
    from nightschool.engine import Result
    from tests.test_night_school import Script, engine_for

    script = Script()
    first_solve = script.solve
    script.solve = lambda task, lessons: (Result(error="checker unavailable on retry")
                                         if lessons else first_solve(task, lessons))
    _, store, engine = engine_for(tmp_path, ["H-1", "V-1"], script)
    assert engine.run_item(engine.training[0]) == "error"
    stored = store.state["tasks"]["H-1"]
    assert stored["cause"] and stored["errors"] == 1 and stored["status"] == "error"
    facts = insights.summarize(store.state)
    assert facts.failed == 0 and facts.no_final_outcome == 1 and facts.checker_incomplete == 1
    text = "\n".join(insights.build(store.state))
    assert "without a stored final outcome" in text and "initial judged failure" in text
    assert "verify check readiness" in text and "obtain a complete outcome" in text
    assert "error-only" not in text and "without a stored judgment" not in text
