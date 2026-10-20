"""Knowledge school (2026-10-18): answer keys for non-code tasks, and the practice pools built from them.

Every pool task must be loadable by the night-school loader, its reference answer must pass, three trivial answers
must fail, and no two prompts may be near-duplicates (the conductor's own rule).
"""
import hashlib
import json
from pathlib import Path
import re

import pytest

from star import eval_checks as checks
from star.knowledge_checks import answer_checks, final_answer, numbers_in, validate_key

ROOT = Path(__file__).resolve().parents[1]
POOLS = sorted((ROOT / "server" / "night_school" / "practice").glob("knowledge-*-20261018.json"))
REFERENCES = ROOT / "server" / "night_school" / "practice" / "knowledge-references-20261018.jsonl"
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


# --- the practice pools -------------------------------------------------------------------------

def words(text: str) -> frozenset:
    return frozenset(w for w in re.findall(r"[a-z0-9_]{3,}", text.lower()))


def load_pools():
    tasks = []
    for path in POOLS:
        rows = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(rows, list) and rows, path
        tasks.extend(rows)
    return tasks


@pytest.mark.skipif(not POOLS, reason="pools not built")
def test_pools_are_loadable_and_large_enough():
    from star.eval_runner import validate_tasks
    from star.evals import load_catalog
    tasks = load_pools()
    assert len(tasks) >= 500, len(tasks)
    for path in POOLS:
        load_catalog(path)
        assert not validate_tasks(json.loads(path.read_text(encoding="utf-8")), path.parent)
    domains = {t["category"] for t in tasks}
    assert len(domains) >= 12, domains
    for task in tasks:
        assert task["run_mode"] == "automated" and task["auto"].get("code") is False
        assert not validate_key(task["auto"]["answer"]), task["id"]
        assert task.get("source_urls"), task["id"]
        assert not re.search(r"golden|holdout|paintball|rec\s*room|password|secret|token|api[_ -]?key", task["prompt"], re.I)


@pytest.mark.skipif(not POOLS, reason="pools not built")
def test_every_reference_passes_and_trivial_answers_fail():
    references = {}
    for line in REFERENCES.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            references[row["id"]] = row["reference"]
    for task in load_pools():
        assert task["id"] in references, task["id"]
        result = score(task, references[task["id"]])
        assert result.passed, (task["id"], result.reasons)
        for trivial in TRIVIAL:
            assert not score(task, trivial).passed, (task["id"], trivial)


@pytest.mark.skipif(not POOLS, reason="pools not built")
def test_no_duplicate_ids_or_near_duplicate_prompts():
    tasks = load_pools()
    ids = [t["id"] for t in tasks]
    assert len(ids) == len(set(ids))
    hashes = {hashlib.sha256(" ".join(t["prompt"].lower().split()).encode()).hexdigest() for t in tasks}
    assert len(hashes) == len(tasks)
    sets = [(t["id"], words(t["prompt"])) for t in tasks]
    near = []
    for i, (a_id, a) in enumerate(sets):
        for b_id, b in sets[i + 1:]:
            if a and b and len(a & b) / len(a | b) >= 0.72:
                near.append((a_id, b_id))
    assert not near, near[:10]
