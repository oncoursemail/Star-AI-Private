"""The generation loop with a scripted brain and fake Luau tools: kept path, every kind of rejection, resumability,
dropping a request in flight, and the checkpoint after every candidate (run on the PC)."""
from __future__ import annotations

import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest   # noqa: E402

from startrain import decontam, loop, prompts, topics  # noqa: E402
from startrain.brain import BrainError, Yielded  # noqa: E402
from startrain.config import Settings  # noqa: E402
from startrain.luau import VmResult  # noqa: E402
from startrain.store import Store, read_jsonl  # noqa: E402

SOLUTION = ("--!strict\nlocal Stack = {}\nStack.__index = Stack\n\n"
            "function Stack.new()\n\treturn setmetatable({ items = {} }, Stack)\nend\n\n"
            "function Stack.push(self, v: number)\n\ttable.insert(self.items, v)\nend\n\n"
            "function Stack.pop(self): number?\n\treturn table.remove(self.items)\nend\n\nreturn Stack\n")
TESTS = "local Stack = load_answer()\n" + "\n".join(f'check("case {i}", Stack.new() ~= nil)' for i in range(6)) + "\n-- " + "t" * 100
TASK_REPLY = "### PROMPT\n" + "Write a strictly typed Luau stack module with new, push and pop that handles empty pops. " * 2 + "\n### TESTS\n```luau\n" + TESTS + "\n```\n"
SOLUTION_REPLY = "```luau\n" + SOLUTION + "```\nA table of items with push and pop.\n"


class FakeTools:
    """Pass/fail is decided by the code: the original solution passes, everything else fails."""
    prelude = ""
    versions = {"analyzer": "fake"}

    def __init__(self):
        self.break_analysis = False

    def analyse(self, code, mode):
        if "does not compile" in code:
            return {"compiled": False, "errors": [{"line": 1, "message": "syntax"}]}
        if self.break_analysis:
            return {"compiled": True, "analyzed": True, "errors": [{"line": 2, "message": "type"}]}
        return {"compiled": True, "analyzed": True, "errors": [], "warning_count": 0}

    def run_script(self, script, *, mutant=False):
        answer = script.split("[[\n", 1)[1].split("\n]]", 1)[0] + "\n" if "[[\n" in script else ""
        ok = answer.strip() == SOLUTION.strip()
        lines = [f"@@T\t{'pass' if ok else 'fail'}\tcase {i}" for i in range(6)] + ["@@DONE"]
        return VmResult(0, "\n".join(lines), False, 0.01)


class ScriptedBrain:
    def __init__(self, solution_reply=SOLUTION_REPLY, task_reply=TASK_REPLY, fail_after=None):
        self.solution_reply, self.task_reply = solution_reply, task_reply
        self.requests: list[str] = []
        self.fail_after = fail_after
        self.vector = [1.0, 0.0, 0.0]

    def others_active(self, own_model=None, chat_models_only=False):
        return False

    def seconds_since_other_activity(self):
        return 1e9

    def chat(self, model, messages, *, max_tokens, temperature=0.6, top_p=0.95, should_yield=lambda: "", seed=None):
        system = messages[0]["content"]
        kind = "ideas" if system == prompts.IDEA_SYSTEM else "task" if system == prompts.TASK_SYSTEM else "solution"
        self.requests.append(kind)
        if self.fail_after is not None and len(self.requests) > self.fail_after:
            raise Yielded("interactive")
        text = {"ideas": "\n".join(f"Build a small helper number {i} that handles tricky input well" for i in range(6)),
                "task": self.task_reply, "solution": self.solution_reply}[kind]
        return {"text": text, "finish": "stop", "prompt_tokens": 100, "completion_tokens": 50, "seconds": 0.1}

    def embed(self, model, texts):
        return [list(self.vector) for _ in texts]


class RepairBrain(ScriptedBrain):
    def chat(self, model, messages, *, max_tokens, temperature=0.6, top_p=0.95,
             should_yield=lambda: "", seed=None):
        if messages[0]["content"].startswith(prompts.REPAIR_SYSTEM):
            self.requests.append("repair")
            return {"text": SOLUTION_REPLY, "finish": "stop", "prompt_tokens": 100,
                    "completion_tokens": 50, "seconds": 0.1}
        return super().chat(
            model, messages, max_tokens=max_tokens, temperature=temperature,
            top_p=top_p, should_yield=should_yield, seed=seed,
        )


@pytest.fixture()
def env(tmp_path):
    s = Settings(home=tmp_path / "h", lock_dir=str(tmp_path / "nolock"), idle_s=0, poll_s=0.01)
    s.ensure_dirs()
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "golden-tasks-x.json").write_text(json.dumps([{"id": "E-1", "prompt": "Make a raycasting vehicle controller with suspension springs and steering."}]), encoding="utf-8")
    index = decontam.build_index(suite, embed=lambda texts: [[0.0, 1.0, 0.0] for _ in texts])
    return s, decontam.Decontaminator(index, s), tmp_path


def make(env, brain, tools=None):
    s, d, _ = env
    store = Store(s.data)
    gen = loop.Generator(s, brain, tools or FakeTools(), d, store, lambda: False, lambda m: None)
    gen._pick_topic = lambda rng: topics.by_id()["typed-containers"]          # a pure topic, for determinism
    return gen, store


def test_a_good_candidate_is_kept_with_its_evidence(env):
    gen, store = make(env, ScriptedBrain())
    row = gen.make_candidate()
    assert "gate" not in row, row
    kept = read_jsonl(store.kept_path)
    assert len(kept) == 1 and kept[0]["id"] == "sv-000001" and kept[0]["gates"]["G3"]["assertions"] == 6
    assert kept[0]["gates"]["G4"]["kill_rate"] == 1.0 and kept[0]["gates"]["G8"]["max_cosine"] == 0.0
    assert kept[0]["sources"] == ["owner-open-weight-models-synthetic"] and len(kept[0]["gate_log_sha256"]) == 64
    assert store.load_vectors() == [("sv-000001", [1.0, 0.0, 0.0])]
    assert store.state["kept"] == 1 and store.state["tokens"]["completion"] == 150


def test_optional_verifier_repair_turns_fixable_failure_into_kept(env):
    s, _, _ = env
    s.solver_repair_rounds = 2
    broken = "```luau\n" + SOLUTION.replace("pop", "popp") + "```"
    brain = RepairBrain(solution_reply=broken)
    gen, store = make(env, brain)
    row = gen.make_candidate()

    assert "gate" not in row, row
    assert row["generation_mode"] == "verifier-repair"
    assert row["repairs"][0]["trigger"] == "G3:assertion_failed"
    assert row["repairs"][0]["result"] == "candidate"
    assert len(row["repairs"][0]["feedback_sha256"]) == 64
    assert row["tokens_repairs"] == 50
    assert brain.requests[-1] == "repair"
    assert store.state["kept"] == 1


def test_second_identical_candidate_is_a_duplicate(env):
    brain = ScriptedBrain()
    gen, store = make(env, brain)
    assert "gate" not in gen.make_candidate()
    row = gen.make_candidate()
    assert (row["gate"], row["code"]) == ("G7", "near_duplicate")
    assert store.state["rejected"] == {"G7": {"near_duplicate": 1}}


def test_every_gate_can_reject(env):
    cases = []
    gen, store = make(env, ScriptedBrain(task_reply="no sections here"))
    cases.append(gen.make_candidate())
    gen, store = make(env, ScriptedBrain(solution_reply="no code at all"))
    cases.append(gen.make_candidate())
    gen, store = make(env, ScriptedBrain(solution_reply="```luau\n" + SOLUTION.replace("--!strict\n", "") + "```"))
    cases.append(gen.make_candidate())                                                    # G0 header
    gen, store = make(env, ScriptedBrain(solution_reply="```luau\n" + SOLUTION.replace("table.insert", "wait(1) table.insert") + "```"))
    cases.append(gen.make_candidate())                                                    # G6
    gen, store = make(env, ScriptedBrain(solution_reply="```luau\n" + SOLUTION + "-- does not compile\n```"))
    cases.append(gen.make_candidate())                                                    # G1
    tools = FakeTools()
    tools.break_analysis = True
    gen, store = make(env, ScriptedBrain(), tools)
    cases.append(gen.make_candidate())                                                    # G2
    gen, store = make(env, ScriptedBrain(solution_reply="```luau\n" + SOLUTION.replace("pop", "popp") + "```"))
    cases.append(gen.make_candidate())                                                    # G3
    brain = ScriptedBrain()
    brain.vector = [0.0, 1.0, 0.0]
    gen, store = make(env, brain)
    cases.append(gen.make_candidate())                                                    # G8 by embedding
    brain2 = ScriptedBrain(task_reply=TASK_REPLY.replace("Write a strictly typed Luau stack module", "Make a raycasting vehicle controller with suspension springs and steering. Write a strictly typed Luau stack module"))
    gen, store = make(env, brain2)
    cases.append(gen.make_candidate())
    seen = {(c["gate"], c["code"]) for c in cases}
    assert ("T", "task_unparsable") in seen and ("S", "solution_unparsable") in seen
    assert ("G0", "missing_strict_header") in seen and ("G6", "deprecated_api") in seen
    assert ("G1", "does_not_compile") in seen and ("G2", "type_errors") in seen
    assert ("G3", "assertion_failed") in seen and ("G8", "suite_overlap_embedding") in seen
    assert ("G8", "suite_overlap") in seen


def test_truncated_replies_are_rejected(env):
    class Truncated(ScriptedBrain):
        def chat(self, *a, **k):
            r = super().chat(*a, **k)
            if self.requests[-1] == "task":
                r["finish"] = "length"
            return r
    gen, _ = make(env, Truncated())
    assert gen.make_candidate()["code"] == "task_truncated"


def test_resumes_from_the_files_and_keeps_counting(env):
    s, d, _ = env
    gen, store = make(env, ScriptedBrain())
    gen.run(max_candidates=2)
    first = Store(s.data)
    assert first.state["candidates"] == 2 and first.state["kept"] == 1
    gen2, store2 = make(env, ScriptedBrain())                       # a new process: memory is rebuilt from kept.jsonl
    assert len(gen2.memory.items) == 1
    row = gen2.make_candidate()
    assert row["id"] == "sv-000003" and row["gate"] == "G7"
    # a crash before state.json was saved: the files are ahead, and the ids must not be reused
    assert Store(s.data).state["candidates"] == 3
    assert [r["id"] for r in read_jsonl(store2.kept_path) + read_jsonl(store2.rejected_path)] == ["sv-000001", "sv-000002", "sv-000003"]


def test_a_yield_drops_the_candidate_and_loses_nothing(env):
    s, _, _ = env
    brain = ScriptedBrain(fail_after=1)                              # the ideas call works, then somebody else arrives
    gen, store = make(env, brain)
    gen.run(max_candidates=1, max_seconds=0.05)
    assert store.state["candidates"] == 0 and read_jsonl(store.kept_path) == []
    assert any(k.startswith("dropped_requests_") for k in store.state["paused"])
    assert json.loads(Path(s.data / "state.json").read_text())["candidates"] == 0


def test_brain_errors_back_off_and_are_counted(env, monkeypatch):
    class Failing(ScriptedBrain):
        def chat(self, *a, **k):
            raise BrainError("down")
    s, _, _ = env
    gen, store = make(env, Failing())
    sleeps = []
    monkeypatch.setattr(loop.time, "sleep", lambda x: sleeps.append(x))
    gen.stop = lambda: len(sleeps) >= 3
    gen.run()
    assert store.state["infra_errors"] >= 1


def test_the_report_counts_everything(env):
    from startrain import report
    gen, store = make(env, ScriptedBrain())
    gen.run(max_candidates=3, report=lambda: report.write(store, env[0].data))
    text = (env[0].data / "report.md").read_text()
    info = json.loads((env[0].data / "report.json").read_text())
    assert info["candidates"] == 3 and info["kept"] == 1 and info["rejected"] == 2
    assert "near_duplicate" in text and "Kept per active hour" in text


def test_idle_gate_ordering_is_cheapest_first():
    order = re.findall(r'"(G\d)"', Path(loop.__file__).read_text())
    assert order.index("G0") < order.index("G6") < order.index("G8") < order.index("G7") < order.index("G1") < order.index("G3") < order.index("G4")
