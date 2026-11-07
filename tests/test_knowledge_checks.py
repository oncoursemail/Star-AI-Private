"""Knowledge school (2026-10-18): answer keys for non-code tasks (`auto.answer`), scored by star.eval_checks."""
import json
from pathlib import Path
import sys

import pytest

from star import eval_checks as checks
from star.eval_runner import validate_tasks
from star.knowledge_checks import answer_checks, final_answer, numbers_in, validate_key

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server" / "night_school"))

TRIVIAL = ("I don't know.", "Answer: 0", "Answer: none of the above", "")


def score(task, answer):
    return checks.score_answer(task, answer, luau_check=lambda *a, **k: pytest.fail("no Luau for a knowledge task"))


def key_task(key):
    return {"id": "K", "prompt": "q", "auto": {"code": False, "answer": key}}


def test_final_answer_follows_the_marker_or_is_the_last_paragraph():
    assert final_answer("Thinking...\n\nAnswer: 42 N") == "42 N"
    assert final_answer("**Final answer:** Paris.") == "Paris."
    assert final_answer("First idea.\n\nLast paragraph here.") == "Last paragraph here."
    assert numbers_in("3/4 of 1,200 is 900 (7.5e2 + 150)") == [0.75, 1200.0, 900.0, 750.0, 150.0]


@pytest.mark.parametrize("key, good, bad", [
    ({"type": "exact", "accept": ["Paris"]}, "The capital is in France.\n\nAnswer: Paris", "Answer: Lyon"),
    ({"type": "numeric", "value": 6, "tol": 0.01, "unit": "N"}, "F = ma = 2*3.\n\nAnswer: 6 N", "Answer: 6 kg"),
    ({"type": "numeric", "value": 880, "rel": 0.01}, "One octave above A4 is 880 Hz.\nAnswer: 880 Hz", "Answer: 440 Hz"),
    ({"type": "choice", "options": {"A": "red", "B": "cyan", "C": "yellow"}, "correct": "B"}, "Answer: B) cyan", "Answer: A"),
    ({"type": "choice", "options": {"A": "red", "B": "cyan"}, "correct": "B"}, "Answer: cyan", "Answer: A or B"),
    ({"type": "order", "items": ["sketch", "model", "rig", "animate"]}, "Answer: sketch, model, rig, animate",
     "Answer: model, sketch, rig, animate"),
    ({"type": "match", "pairs": [["hue", "colour family"], ["value", "light or dark"]]},
     "Hue is the colour family.\nValue says how light or dark it is.", "Hue: how light or dark. Value: colour family."),
    ({"type": "short", "required": [["anticipation"], ["follow[- ]?through"]], "forbidden": ["lorem"]},
     "Use anticipation before the jump and follow-through after landing.", "Use squash and stretch."),
    ({"type": "rubric", "required": [["checkpoint"], ["difficulty"], ["playtest"]], "min_required": 2, "min_words": 8},
     "Add a checkpoint before the hard jump and lower the difficulty curve; then playtest it.", "Playtest it."),
])
def test_each_answer_kind_passes_its_reference_and_fails_a_wrong_answer(key, good, bad):
    assert not validate_key(key)
    assert score(key_task(key), good).passed
    assert not score(key_task(key), bad).passed
    for trivial in TRIVIAL:
        assert not score(key_task(key), trivial).passed, (key, trivial)


def test_thinking_and_code_blocks_are_not_the_answer():
    key = {"type": "exact", "accept": ["blue"]}
    assert score(key_task(key), "<think>blue?</think>\n\nAnswer: red").passed is False
    assert score(key_task(key), "```lua\nprint('blue')\n```\nAnswer: blue").passed


def test_bad_keys_are_reported_not_scored():
    assert validate_key({"type": "numeric"}) and validate_key({"type": "order", "items": ["("]})
    assert validate_key({"type": "choice", "options": {"A": "x"}, "correct": "B"})
    assert answer_checks({"type": "essay"}, "Answer: x")[0].ok is False


def test_numbers_and_order_are_read_from_the_final_answer_only():
    numeric = {"type": "numeric", "value": 6, "tol": 0.01}
    assert not score(key_task(numeric), "F = 2 * 3 = 6 N, I think.\n\nAnswer: I am not sure").passed
    order = {"type": "order", "items": ["sketch", "model", "rig"]}
    assert not score(key_task(order), "We sketch, model and finally rig it.\n\nAnswer: sketch, model").passed
    assert score(key_task(order), "Answer: sketch, then model, then rig").passed


def test_the_task_loader_refuses_a_bad_answer_key(tmp_path):
    good = {"id": "K-1", "prompt": "q", "run_mode": "automated", "category": "knowledge", "goal": "g",
            "required_evidence": ["answer.md"], "pass_conditions": ["the answer key passes"],
            "auto": {"code": False, "answer": {"type": "exact", "accept": ["Paris"]}}}
    bad_regex = {**good, "id": "K-2", "auto": {"code": False, "answer": {"type": "order", "items": ["(", "x"]}}}
    not_an_object = {**good, "id": "K-3", "auto": {"code": False, "answer": "Paris"}}
    problems = validate_tasks([good, bad_regex, not_an_object], tmp_path)
    assert [p.split(":")[0] for p in problems] == ["K-2", "K-3"], problems
    from nightschool.pool import load_pool                  # night school drops it instead of failing on it later
    (tmp_path / "tasks.json").write_text(json.dumps([good, bad_regex]), encoding="utf-8")
    pool = load_pool(tmp_path)
    assert [t["id"] for t in pool.tasks] == ["K-1"] and sum(pool.dropped.values()) == 1, pool.summary()
