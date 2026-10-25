"""Sealed set store + manifest, the integrity layer (#562), the additions-only gate, judge scoring, answer keys."""
import json

import pytest

from star import eval_checks, integrity, protected_paths as pp, sealed_eval as se
from star.eval_sandbox import JudgeSandbox, SandboxResult
from star.knowledge_checks import answer_checks


def _make_set(root, tasks):
    folder = root / "s1"
    (folder / "tests").mkdir(parents=True)
    (folder / "suite.json").write_text(json.dumps(tasks), encoding="utf-8")
    (folder / "tests" / "A.luau").write_text("check('x', true)\n", encoding="utf-8")
    return folder


TASKS = [{"id": "A", "family": "luau-bugfix", "difficulty": 2, "seed_sha256": "s1", "prompt": "p"},
         {"id": "B", "family": "knowledge", "difficulty": 1, "prompt": "q"},
         {"id": "C", "family": "canary", "difficulty": 1, "prompt": "r"}]


@pytest.fixture
def sealed(tmp_path, monkeypatch):
    monkeypatch.setenv("STAR_SEALED_DIR", str(tmp_path))
    monkeypatch.setattr(se, "MANIFEST_DIR", tmp_path / "manifests")
    (tmp_path / "manifests").mkdir()
    folder = _make_set(tmp_path, TASKS)
    manifest = se.build_manifest("s1", folder, grader_sha256="g" * 64)
    se.manifest_path("s1").write_text(json.dumps(manifest), encoding="utf-8")
    return folder, manifest


def test_manifest_counts_hashes_and_power(sealed):
    folder, m = sealed
    assert m["counts"]["tasks"] == 3 and m["counts"]["scored"] == 2 and m["counts"]["canaries"] == 1
    assert set(m["files"]) == {"suite.json", "tests/A.luau"} and len(m["set_sha256"]) == 64
    assert {"k1", "k2", "k3"} <= set(m["power"])
    assert se.verify("s1") == []


def test_verify_catches_edits_extra_files_and_ignores_results(sealed):
    folder, _ = sealed
    (folder / "results").mkdir()
    (folder / "results" / "run.json").write_text("{}", encoding="utf-8")
    assert se.verify("s1") == []                                  # run outputs are not frozen
    (folder / "tests" / "A.luau").write_text("check('x', 1 == 1)\n", encoding="utf-8")
    assert any(p.startswith("changed: tests/A.luau") for p in se.verify("s1"))
    (folder / "tests" / "A.luau").write_text("check('x', true)\n", encoding="utf-8")
    (folder / "extra.md").write_text("x", encoding="utf-8")
    assert "not in the manifest: extra.md" in se.verify("s1")
    with pytest.raises(se.SealedError):
        se.load("s1")


def test_frozen_grader_problem_when_the_grading_code_changed(sealed):
    _, m = sealed
    assert se.grader_problems(m) and "re-freeze" in se.grader_problems(m)[0]
    from star.eval_runner import grader_sha256
    assert se.grader_problems({**m, "grader_sha256": grader_sha256()}) == []


def test_family_scores_and_canary_passes(sealed):
    _, m = sealed
    result = {"tasks": {"A": {"status": "pass"}, "B": {"status": "fail"}, "C": {"status": "pass"}}}
    scores = se.family_scores(result, m)
    assert scores["all"] == {"pass": 1, "scored": 2, "error": 0, "rate": 0.5}
    assert scores["canary"]["pass"] == 1 and "canary" not in [k for k in scores["all"]]
    assert se.canary_passes(result, m) == ["C"]


# --- integrity: no easier grading -----------------------------------------------------------------------------

BASE_TASK = {"id": "T1", "prompt": "do x", "run_mode": "automated",
             "auto": {"compile_mode": "exact", "strict": True, "unit_test": {"file": "tests/T1.luau", "checks": 5},
                      "forbid": [{"id": "no_any", "re": "::\\s*any"}]}}
KEY_TASK = {"id": "K1", "prompt": "q", "run_mode": "automated",
            "auto": {"code": False, "answer": {"type": "numeric", "value": 3, "tol": 0, "first": True}}}


def _with(task, **auto):
    return {**task, "auto": {**task["auto"], **auto}}


def test_adding_a_task_is_allowed_and_identical_tasks_pass():
    extra = {**BASE_TASK, "id": "T2"}
    assert integrity.easier_grading([BASE_TASK, KEY_TASK], [BASE_TASK, KEY_TASK, extra]) == []


@pytest.mark.parametrize("new,expect", [
    ([KEY_TASK], "task deleted"),
    ([_with(BASE_TASK, unit_test={"file": "tests/T1.luau", "checks": 4}), KEY_TASK], "fewer unit-test assertions"),
    ([_with(BASE_TASK, strict=False), KEY_TASK], "strict mode turned off"),
    ([_with(BASE_TASK, forbid=[]), KEY_TASK], "forbid check removed"),
    ([{**BASE_TASK, "prompt": "do y"}, KEY_TASK], "prompt edited"),
    ([BASE_TASK, _with(KEY_TASK, answer={"type": "numeric", "value": 3, "tol": 1, "first": True})], "tol raised"),
    ([BASE_TASK, _with(KEY_TASK, answer={"type": "numeric", "value": 3, "tol": 0})], "'first' removed"),
])
def test_every_way_of_grading_easier_is_refused(new, expect):
    problems = integrity.easier_grading([BASE_TASK, KEY_TASK], new)
    assert any(expect in p for p in problems), problems


def test_edited_unit_test_is_refused_but_appended_assertions_are_fine():
    old = {"tests/T1.luau": "check('a', f() == 1)\n"}
    grown = {"tests/T1.luau": "check('a', f() == 1)\ncheck('b', f(2) == 2)\n"}
    weaker = {"tests/T1.luau": "check('a', true)\n"}
    stricter = _with(BASE_TASK, unit_test={"file": "tests/T1.luau", "checks": 6})
    assert integrity.easier_grading([BASE_TASK], [stricter], old_tests=old, new_tests=grown) == []
    assert integrity.easier_grading([BASE_TASK], [BASE_TASK], old_tests=old, new_tests=weaker)


def test_gate_config_and_rescore_checks():
    assert integrity.gate_config_easier({"alpha": 0.05, "samples": 2}, {"alpha": 0.05, "samples": 3}) == []
    assert integrity.gate_config_easier({"alpha": 0.05}, {"alpha": 0.1})
    assert integrity.gate_config_easier({"samples": 2}, {"samples": 1})
    assert integrity.gate_config_easier({"smallest_effect": 0.1}, {})
    assert integrity.rescore_monotonic({"A": "fail", "B": "pass"}, {"A": "pass", "B": "pass"}) == ["A: fail -> pass under the new grader"]
    assert integrity.rescore_monotonic({"A": "pass"}, {"A": "fail"}) == []
    assert integrity.canary_alarm([], ["C1"]) and integrity.canary_alarm(["C1"], ["C1"]) == []


# --- integrity: decide, receipts, drift watch and automatic rollback ------------------------------------------

@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("STAR_RECEIPTS_DIR", str(tmp_path / "receipts"))
    monkeypatch.setenv("STAR_PROMOTIONS_FILE", str(tmp_path / "promotions.json"))
    return tmp_path


def test_promotion_needs_dev_and_holdout_promote_and_writes_overlay_and_receipt(home):
    win = {"decision": "PROMOTE", "candidate_pass": 80, "samples": 100}
    d = integrity.decide("ladder", apply={"verify_ladder": "on"}, dev=win, holdout=win, grader=[], canaries=[], easier=[])
    assert d.promote and json.loads((home / "promotions.json").read_text())["verify_ladder"] == "on"
    receipt = json.loads(open(d.receipt, encoding="utf-8").read())
    assert receipt["kind"] == "promotion" and receipt["rollback"] == {"verify_ladder": None}


@pytest.mark.parametrize("kwargs,reason", [
    ({"holdout": {"decision": "UNDERPOWERED"}}, "sealed holdout verdict is UNDERPOWERED"),
    ({"canaries": ["canary passed (impossible task): C1"]}, "canary passed"),
    ({"easier": ["T1: task deleted"]}, "task deleted"),
    ({"grader": ["grader changed since the freeze"]}, "grader changed"),
])
def test_any_failed_check_refuses_and_leaves_the_overlay_alone(home, kwargs, reason):
    args = {"apply": {"x": 1}, "dev": {"decision": "PROMOTE"}, "holdout": {"decision": "PROMOTE"}, "grader": [],
            "canaries": [], "easier": [], **kwargs}
    d = integrity.decide("c", **args)
    assert not d.promote and any(reason in r for r in d.reasons)
    assert not (home / "promotions.json").exists()
    assert json.loads(open(d.receipt, encoding="utf-8").read())["kind"] == "refusal"


def test_drift_watch_rolls_back_automatically(home):
    win = {"decision": "PROMOTE", "candidate_pass": 80, "samples": 100}
    integrity.write_overlay({"verify_ladder": "off"})
    d = integrity.decide("ladder", apply={"verify_ladder": "on"}, dev=win, holdout=win, grader=[], canaries=[], easier=[])
    assert integrity.watch(d.receipt, 78, 100)["healthy"]                       # within noise
    out = integrity.watch(d.receipt, 40, 100)                                   # clear drop
    assert not out["healthy"] and integrity.read_overlay() == {"verify_ladder": "off"}
    assert json.loads(open(out["rollback_receipt"], encoding="utf-8").read())["kind"] == "rollback"
    assert integrity.drift_check({"holdout": win}, 80, 100, live_canary_passes=1)


# --- protected closure: the additions-only integrity gate -----------------------------------------------------

def test_additive_gate_allows_new_files_and_appended_tasks_only():
    old = json.dumps([{"id": "A", "prompt": "a"}]).encode()
    assert pp.additive_problem("evals/roblox/new.json", None, b"[]") == ""
    assert pp.additive_problem("evals/roblox/s.json", old, json.dumps([{"id": "A", "prompt": "a"}, {"id": "B"}]).encode()) == ""
    assert "edited" in pp.additive_problem("evals/roblox/s.json", old, json.dumps([{"id": "A", "prompt": "b"}]).encode())
    assert "deleted" in pp.additive_problem("evals/roblox/s.json", old, None)
    assert "unique" in pp.additive_problem("evals/roblox/s.json", old, json.dumps([{"id": "A", "prompt": "a"}, {"id": "A"}]).encode())
    assert pp.additive_problem("evals/roblox/tests/X.luau", b"check(1)", b"check(true)")
    assert pp.additive_problem("evals/sealed/eval-power-v1.manifest.json", None, b"{}")
    assert pp.additive_problem("star/eval_checks.py", b"a", b"b")


def test_cli_integrity_gate_clears_additions_and_label_still_overrides(tmp_path, monkeypatch):
    import subprocess
    repo = tmp_path / "r"
    (repo / "evals").mkdir(parents=True)
    run = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()  # noqa: E731
    run("init", "-q")
    (repo / "evals" / "s.json").write_text(json.dumps([{"id": "A"}]), encoding="utf-8")
    run("add", "-A")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "base")
    base = run("rev-parse", "HEAD")
    (repo / "evals" / "s.json").write_text(json.dumps([{"id": "A"}, {"id": "B"}]), encoding="utf-8")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "add")
    head = run("rev-parse", "HEAD")
    monkeypatch.chdir(repo)
    args = ["--branch", "star/gen-x", "--files", "evals/s.json", "--base-sha", base, "--head-sha", head]
    assert pp.main(args) == 0
    (repo / "evals" / "s.json").write_text(json.dumps([{"id": "A", "x": 1}, {"id": "B"}]), encoding="utf-8")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "edit")
    head2 = run("rev-parse", "HEAD")
    assert pp.main(["--branch", "star/gen-x", "--files", "evals/s.json", "--base-sha", base, "--head-sha", head2]) == 1
    assert pp.main(["--branch", "star/gen-x", "--files", "evals/s.json", "--base-sha", base, "--head-sha", head2,
                    "--labels", pp.OWNER_LABEL]) == 0
    assert pp.main(["--branch", "star/gen-x", "--files", "star/eval_checks.py"]) == 1


# --- judge scoring and answer keys -----------------------------------------------------------------------------

class FakeJudge:
    def __init__(self, stdout="", error=""):
        self.stdout, self.error, self.sources = stdout, error, []

    def run(self, language, source):
        self.sources.append(source)
        return SandboxResult(rc=0, stdout=self.stdout, error=self.error)


JTASK = {"id": "P", "prompt": "p", "auto": {"language": "python", "judge": {"tests": "check('a', lambda: f() == 1)", "expect": 1}}}


def test_judge_scoring_passes_only_complete_honest_runs():
    ok = eval_checks.score_answer(JTASK, "```python\ndef f():\n    return 1\n```", luau_check=None,
                                  judge=FakeJudge("@@PASS a\n@@DONE 1/1\n"))
    assert ok.passed
    bad = eval_checks.score_answer(JTASK, "```python\ndef f():\n    return 2\n```", luau_check=None,
                                   judge=FakeJudge("@@FAIL a\n@@DONE 0/1\n"))
    assert not bad.passed and "failed: a" in bad.reasons[0]
    forged = eval_checks.score_answer(JTASK, "```python\nx=1\n```", luau_check=None,
                                      judge=FakeJudge("@@PASS a\n@@PASS a\n@@DONE 1/1\n"))
    assert not forged.passed
    assert not eval_checks.score_answer(JTASK, "no code here", luau_check=None, judge=FakeJudge()).passed
    assert not eval_checks.score_answer(JTASK, "", luau_check=None, judge=FakeJudge()).passed
    with pytest.raises(eval_checks.InfraError):
        eval_checks.score_answer(JTASK, "```python\nx=1\n```", luau_check=None, judge=FakeJudge(error="down"))


def test_judge_sandbox_parses_the_host_reply():
    calls = []

    def runner(argv, input, capture_output, timeout):
        calls.append(input.decode())
        jobs = json.loads(__import__("base64").b64decode(input.decode().split("'")[1]).decode())
        body = {j["id"]: {"stdout": "@@PASS a\n@@DONE 1/1\n", "steps": [{"rc": 0, "timed_out": False}], "seconds": 0.1}
                for j in jobs}
        return type("Done", (), {"stdout": ("@@JSON " + json.dumps(body) + "\n").encode(), "returncode": 0})()
    box = JudgeSandbox("u@h", runner=runner)
    res = box.run_many("python", ["print(1)", "print(2)"])
    assert [r.stdout for r in res] == ["@@PASS a\n@@DONE 1/1\n"] * 2 and not any(r.error for r in res)
    assert "star-judge" in calls[0]
    with pytest.raises(ValueError):
        JudgeSandbox("not a target")


def test_answer_key_first_and_whole_refuse_guess_lists():
    num = {"type": "numeric", "value": 44, "tol": 0, "first": True}
    assert answer_checks(num, "Ru is element 44.\n\nAnswer: 44")[0].ok
    assert not answer_checks(num, "Answer: 43 44 45")[0].ok
    exact = {"type": "exact", "accept": ["Canberra"], "whole": True}
    assert answer_checks(exact, "Answer: **Canberra**.\n\nHope that helps")[0].ok
    assert not answer_checks(exact, "Answer: Canberra or Sydney")[0].ok
    assert not answer_checks(exact, "Answer:")[0].ok
