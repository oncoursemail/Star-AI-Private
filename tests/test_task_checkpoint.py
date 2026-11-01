"""star.task_checkpoint: step results survive a stop, a new scope starts clean, a broken file is not fatal."""
from __future__ import annotations

import json

from star.task_checkpoint import StepCheckpoint, step_key


def test_steps_survive_a_new_instance(tmp_path):
    path = tmp_path / "ck.json"
    first = StepCheckpoint(path, scope="night-1")
    assert first.get("a") is None
    first.put("a", {"reply": "x", "accepted": 2})
    again = StepCheckpoint(path, scope="night-1")
    assert again.get("a") == {"reply": "x", "accepted": 2}
    assert len(again) == 1


def test_other_scope_starts_clean(tmp_path):
    path = tmp_path / "ck.json"
    StepCheckpoint(path, scope="night-1").put("a", 1)
    other = StepCheckpoint(path, scope="night-2")
    assert other.get("a") is None and len(other) == 0
    other.put("b", 2)
    assert json.loads(path.read_text())["scope"] == "night-2"


def test_clear_and_broken_file(tmp_path):
    path = tmp_path / "ck.json"
    ck = StepCheckpoint(path, scope="s")
    ck.put("a", 1)
    ck.clear()
    assert not path.exists() and StepCheckpoint(path, scope="s").get("a") is None
    path.write_text("{not json")
    broken = StepCheckpoint(path, scope="s")
    assert broken.get("a") is None
    broken.put("a", 3)
    assert StepCheckpoint(path, scope="s").get("a") == 3


def test_step_key_is_stable_and_distinct():
    assert step_key("cluster", "prompt") == step_key("cluster", "prompt")
    assert step_key("cluster", "prompt") != step_key("ideas", "prompt")
    assert len(step_key("x")) == 16
