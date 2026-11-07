"""M5 offline replay (star/pool_replay.py): rules, expected values, paired statistics, result-file loading, Q7, grading.
No model, no server: stored data is synthetic."""
import json
from types import SimpleNamespace

import pytest

from star import candidate_pool as cp, pool_replay as pr

CODE_A = "local a = 1\nprint(a)\n"
CODE_B = "local b = 2\nprint(b)\n"


def cand(task, passed, source="s", **view):
    code = view.pop("code", CODE_A)
    return pr.Cand(task, source, passed, {"slop": 0, **view}, code, 1.0, (code,))


def seen(*rows):
    return [pr.Seen(i, view, code) for i, (view, code) in enumerate(rows)]


# --- rules see views only ------------------------------------------------------------------------------------

def test_verified_first_takes_the_first_clean_candidate_else_the_first():
    assert pr.verified_first(seen(({"compile_ok": False}, ""), ({"compile_ok": True}, ""), ({}, ""))) == 1
    assert pr.verified_first(seen(({"slop_hard": True}, ""), ({"compile_ok": False}, ""))) == 0
    assert pr.verified_first(seen(({"compile_ok": None}, ""), ({"compile_ok": True}, ""))) == 0   # unknown is not a failure


def test_verified_rank_prefers_clean_then_low_slop_then_early():
    rows = seen(({"compile_ok": False, "slop": 0}, ""), ({"slop": 5}, ""), ({"slop": 2}, ""), ({"slop": 2}, ""))
    assert pr.verified_rank(rows) == 2


def test_ladder_rules_count_the_three_static_rungs():
    rows = seen(({"compile_ok": True, "api_ok": False, "deprecated_ok": False}, ""),
                ({"compile_ok": True, "api_ok": False}, ""), ({"compile_ok": True, "api_ok": True}, ""))
    assert [pr.static_fails(r) for r in rows] == [2, 1, 0]
    assert pr.ladder_first(rows) == 2 and pr.ladder_rank_pick(rows) == 2
    assert pr.ladder_first(seen(({"api_ok": False}, ""), ({"compile_ok": False}, ""))) == 0     # none clean: the first


def test_consensus_picks_the_candidate_closest_to_the_others_and_ignores_comments():
    rows = seen(({}, "local a = 1\nprint(a)"), ({}, "local zzz = {}\nreturn zzz"), ({}, "-- hi\nlocal a = 1\nprint(a)"))
    assert pr.consensus(rows) in (0, 2)
    assert pr.consensus(seen(({}, CODE_B), ({}, CODE_A), ({}, CODE_A))) == 1
    clean = seen(({"compile_ok": False}, CODE_A), ({"compile_ok": False}, CODE_A), ({}, CODE_B), ({}, CODE_A))
    assert pr.consensus(clean) == 0 and pr.consensus_clean(clean) in (2, 3)


def test_rules_cannot_read_the_grade():
    assert not hasattr(pr.Seen(0, {}, ""), "passed")


# --- expected values ------------------------------------------------------------------------------------------

def test_expected_pass_is_exact_over_all_orderings():
    pool = [cand("t", True), cand("t", False, compile_ok=False)]
    # the passing candidate is clean, the failing one does not compile: both orders end on the passing one
    assert pr.expected(pool, pr.verified_first, 2) == (1.0, pytest.approx(1.5))      # 1 or 2 generations, equally often
    assert pr.expected(pool, pr.first, 2)[0] == 0.5
    assert pr.expected(pool, "oracle", 2)[0] == 1.0
    assert pr.expected(pool, pr.verified_rank, 2) == (1.0, 2.0)


def test_expected_samples_when_there_are_too_many_orderings():
    pool = [cand("t", i % 2 == 0) for i in range(12)]
    got = pr.expected(pool, pr.first, 6, seed=3)[0]
    assert got == pr.expected(pool, pr.first, 6, seed=3)[0] and 0.4 < got < 0.6


# --- paired statistics ---------------------------------------------------------------------------------------

def test_compare_counts_task_wins_and_losses_and_gives_a_sign_test():
    base = {f"t{i}": 0.5 for i in range(12)}
    rule = {f"t{i}": (0.9 if i < 10 else 0.1) for i in range(12)}
    row = pr.compare(rule, base)
    assert (row["tasks"], row["task_wins"], row["task_losses"]) == (12, 10, 2)
    assert row["delta"] == pytest.approx(0.2667, abs=1e-3) and row["ci95"][0] > 0
    assert row["p_better"] == pytest.approx(0.0193, abs=1e-3)
    assert pr.verdict(row, 0.05) == "CLEAR WIN"
    assert pr.verdict({**row, "p_better": 0.2}, 0.05) == "no clear difference"
    assert pr.verdict(pr.compare(base, rule), 0.05) == "CLEAR LOSS"


def test_replay_tells_a_rule_that_helps_from_one_that_does_not():
    by_task = {}
    for t in range(14):          # first candidate of each task fails to compile and fails; the others are clean and pass
        by_task[f"t{t}"] = [cand(f"t{t}", False, compile_ok=False), cand(f"t{t}", True, compile_ok=True),
                            cand(f"t{t}", True, compile_ok=True)]
    for t in range(14, 20):      # nothing to select: every candidate passes
        by_task[f"t{t}"] = [cand(f"t{t}", True, compile_ok=True) for _ in range(3)]
    report = pr.replay(by_task, [2, 3])
    n3 = report["budgets"]["3"]["rules"]
    assert report["tasks_with_candidates"] == 20 and report["mixed_tasks"] == 14
    assert n3["verified_first"]["rule"] == 1.0 and n3["verified_first"]["base"] == pytest.approx(0.7667, abs=1e-3)
    assert n3["verified_first"]["verdict"] == "CLEAR WIN" and n3["oracle"]["verdict"] == "ceiling (not a rule)"
    assert n3["verified_first"]["generations"] < 3 and n3["verified_rank"]["generations"] == 3.0
    assert n3["consensus"]["rule"] <= n3["oracle"]["rule"]
    assert report["alpha_per_rule"] == round(0.05 / (len(pr.RULES) * 2), 4)
    assert "iid" in report["caveat"] and "N=3" in pr.text_report(report)


def test_tasks_with_fewer_candidates_than_the_budget_are_left_out_of_that_budget():
    by_task = {"a": [cand("a", True), cand("a", False)], "b": [cand("b", True)] * 3}
    report = pr.replay(by_task, [3])
    assert report["budgets"]["3"]["tasks"] == 1


def test_signal_report_gives_pass_rates_with_intervals():
    pools = {"t": [cand("t", False, compile_ok=False), cand("t", True, compile_ok=True), cand("t", False, slop_hard=True)]}
    rows = pr.signal_report(pools)
    assert rows["compile_fail"]["pass"] == 0 and rows["compile_ok"]["rate"] == 1.0 and rows["slop_hard"]["n"] == 1
    assert rows["all"]["ci95"][0] < rows["all"]["rate"] < rows["all"]["ci95"][1]


# --- stored result files ---------------------------------------------------------------------------------------

def record(passed, answer=CODE_A, prompt="p1", events=None, checks=None, slop=0):
    return {"status": "pass" if passed else "fail", "passed": passed, "prompt_sha256": prompt, "seconds": 5.0,
            "answer": "```luau\n" + answer + "```", "answer_chars": len(answer), "events": events or [],
            "checks": checks or [{"id": "luau_block", "ok": True}, {"id": "luau_check[1]", "ok": True},
                                 {"id": "unit_tests", "ok": passed, "detail": "3/4 passed"}],
            "slop": {"score": slop, "hard": slop > 5, "rules": []}}


def result_file(tmp_path, name, tasks, settings=None, suite="suite.json"):
    path = tmp_path / name
    path.write_text(json.dumps({"schema": 1, "suite": {"file": suite}, "run": {"settings": settings or {}},
                                "tasks": tasks}), encoding="utf-8")
    return path


def test_load_results_reads_views_and_skips_unscored_records(tmp_path):
    path = result_file(tmp_path, "a.json", {
        "T1": record(True), "T2": record(False, checks=[{"id": "luau_check[1]", "ok": False}], slop=9),
        "T3": {"status": "error"}, "T4": {"status": "skipped"}})
    rows = {c.task: c for c in pr.load_results([path])}
    assert sorted(rows) == ["suite.json:T1", "suite.json:T2"]
    t1, t2 = rows["suite.json:T1"], rows["suite.json:T2"]
    assert t1.passed and t1.view["compile_ok"] is True and t1.view["unit_share"] == 0.75 and t1.code == CODE_A
    assert t2.view["compile_ok"] is False and t2.view["slop_hard"] and t2.source.endswith("/a")


def test_a_different_prompt_for_the_same_task_is_dropped(tmp_path):
    files = [result_file(tmp_path, f"r{i}.json", {"T1": record(True, prompt="old" if i == 0 else "new")})
             for i in range(3)]
    assert sorted(c.view["prompt"] for c in pr.load_results(files)) == ["new", "new"]


def test_processed_answers_are_not_raw_samples(tmp_path):
    ladder = [{"event": "verify_finished", "verified": True, "rounds": 1, "fixed": True}]
    files = [result_file(tmp_path, "raw.json", {"T1": record(True)}),
             result_file(tmp_path, "ladder.json", {"T1": record(False, events=ladder)}),
             result_file(tmp_path, "retry.json", {"T1": record(True)}, settings={"luau_retry_ladder": True}),
             result_file(tmp_path, "on.json", {"T1": record(True)}, settings={"verify_ladder": "on"})]
    cands = pr.load_results(files)
    assert len(cands) == 4 and [c.view["processed"] for c in cands] == [False, True, True, True]
    assert [c.source for cs in pr.pools(cands).values() for c in cs] == ["tmp/raw".replace("tmp", files[0].parent.name)]
    assert len(pr.pools(cands, raw_only=False)["suite.json:T1"]) == 4
    ladder_cand = cands[1]
    assert ladder_cand.view["ladder_rounds"] == 1 and ladder_cand.view["ladder_fixed"] and ladder_cand.view["ladder_ok"]


def test_offline_rungs_use_the_local_api_dump_on_the_stored_code(tmp_path, monkeypatch):
    suites = tmp_path / "evals" / "x"
    suites.mkdir(parents=True)
    prompt = "make a part"
    (suites / "suite.json").write_text(json.dumps([{"id": "T1", "prompt": prompt}]), encoding="utf-8")
    bad = 'local p = Instance.new("Part")\np.Colour = Color3.new(1, 0, 0)\n'
    good = 'local p = Instance.new("Part")\np.Color = Color3.new(1, 0, 0)\n'
    key = cp.prompt_key(prompt)
    files = [result_file(tmp_path, "bad.json", {"T1": record(False, bad, prompt=key)}),
             result_file(tmp_path, "good.json", {"T1": record(True, good, prompt=key)}),
             result_file(tmp_path, "other.json", {"T1": record(True, good, prompt="changed")})]
    cands = pr.load_results(files)
    assert pr.offline_rungs(cands, tmp_path / "evals") == 2
    by_source = {c.source.split("/")[-1]: c.view.get("api_ok") for c in cands}
    assert by_source["bad"] is False and by_source["good"] is True and by_source.get("other") is None


# --- Q7 -------------------------------------------------------------------------------------------------------

def test_fix_vs_resample_pairs_each_fix_task_with_fresh_samples_from_other_runs():
    def ladder_cand(task, passed):
        return pr.Cand(task, "on", passed, {"processed": True, "ladder_rounds": 1, "ladder_fixed": False}, "", 1.0)
    cands = [ladder_cand("t1", False), ladder_cand("t2", False)]
    for task in ("t1", "t2"):
        cands += [pr.Cand(task, f"raw{i}", i != 0, {"processed": False}, CODE_A, 1.0, (CODE_A,)) for i in range(3)]
    out = pr.fix_vs_resample(cands)
    assert out["fix_calls_tasks"] == 2 and out["fix_pass"] == 0
    assert out["vs_resample1"]["base"] == pytest.approx(2 / 3, abs=1e-3) and out["vs_resample1"]["task_losses"] == 2
    assert {r["task"] for r in out["rows"]} == {"t1", "t2"}
    assert pr.fix_vs_resample([ladder_cand("t1", True)])["fix_calls_tasks"] == 0      # no other run to compare with


# --- live pools: grading and chains --------------------------------------------------------------------------------

def write_pool(path, prompt):
    key = cp.prompt_key(prompt)
    raw = "Intro\n```luau\nlocal x = \n```\n"
    start = raw.index("local")
    end = raw.index("```", start)
    rows = [{"kind": "answer", "answer_id": "A1", "prompt_sha256": key, "answer": raw, "blocks": [[start, end]]},
            {"kind": "candidate", "source": "ladder", "answer_id": "A1", "prompt_sha256": key, "block": 1, "idx": 0,
             "origin": "first", "parent": None, "code": "local x = \n", "ok": False, "accepted": True, "rank": [0, -1],
             "rungs": [{"rung": "compile", "status": "fail"}], "fix_seconds": None},
            {"kind": "candidate", "source": "ladder", "answer_id": "A1", "prompt_sha256": key, "block": 1, "idx": 1,
             "origin": "fix", "parent": 0, "code": "local x = 1\n", "ok": True, "accepted": True, "rank": [5, 0],
             "rungs": [{"rung": "compile", "status": "pass"}], "fix_seconds": 30.0},
            {"kind": "candidate", "source": "best_of_n", "answer_id": "B2", "prompt_sha256": key, "idx": 2,
             "answer": "other answer", "code": "", "checks": [], "chosen": False}]
    path.write_text("".join(json.dumps({"schema": 1, **r}) + "\n" for r in rows), encoding="utf-8")


def test_grade_pool_scores_rebuilt_answers_and_resumes(tmp_path):
    prompt = "write x"
    pool_file, out = tmp_path / "pool.jsonl", tmp_path / "grades.jsonl"
    write_pool(pool_file, prompt)
    asked = []

    def scorer(task, answer):
        asked.append(answer)
        return SimpleNamespace(passed="local x = 1" in answer, reasons=["r"])
    tasks = [{"id": "T1", "prompt": prompt}, {"id": "T2", "prompt": "unrelated"}]
    assert pr.grade_pool(pool_file, tasks, scorer, out) == 3
    assert asked[0] == "Intro\n```luau\nlocal x = \n```\n" and asked[1] == "Intro\n```luau\nlocal x = 1\n```\n"
    assert asked[2] == "other answer"
    grades = [r for r in cp.read_lines(out)]
    assert [(g["source"], g["idx"], g["passed"], g["task"]) for g in grades] == [
        ("ladder", 0, False, "T1"), ("ladder", 1, True, "T1"), ("best_of_n", 2, False, "T1")]
    assert pr.grade_pool(pool_file, tasks, scorer, out) == 0 and len(asked) == 3


def test_an_infrastructure_error_leaves_a_candidate_ungraded(tmp_path):
    pool_file, out = tmp_path / "pool.jsonl", tmp_path / "grades.jsonl"
    write_pool(pool_file, "write x")
    logs = []

    def scorer(task, answer):
        raise OSError("server down")
    assert pr.grade_pool(pool_file, [{"id": "T1", "prompt": "write x"}], scorer, out, log=logs.append) == 0
    assert not out.exists() and len(logs) == 3


def test_chain_policies_compare_first_best_last_and_oracle(tmp_path):
    pool_file, out = tmp_path / "pool.jsonl", tmp_path / "grades.jsonl"
    write_pool(pool_file, "write x")
    pr.grade_pool(pool_file, [{"id": "T1", "prompt": "write x"}],
                  lambda task, answer: SimpleNamespace(passed="local x = 1" in answer, reasons=[]), out)
    chains = pr.load_chains(pool_file, out)
    assert len(chains) == 1 and [c.idx for c in chains[0]] == [0, 1]
    got = pr.chain_policies(chains)
    assert got["chains"] == 1 and got["with_fix_rounds"] == 1
    assert got["best_vs_first"]["delta"] == 1.0 and got["last_vs_first"]["delta"] == 1.0
    assert got["oracle_vs_first"]["task_wins"] == 1


def test_cli_inspect_replay_and_fixes_run_on_result_files(tmp_path, capsys):
    files = [str(result_file(tmp_path, f"r{i}.json", {f"T{t}": record((t + i) % 2 == 0) for t in range(4)}))
             for i in range(3)]
    out = tmp_path / "rep.json"
    assert pr.main(["inspect", "--results", *files, "--no-offline-rungs"]) == 0
    assert json.loads(capsys.readouterr().out)["tasks_with_raw_samples"] == 4
    assert pr.main(["replay", "--results", *files, "--budgets", "2", "--no-offline-rungs", "--out", str(out)]) == 0
    assert "budget N=2" in capsys.readouterr().out and "budgets" in json.loads(out.read_text(encoding="utf-8"))
    assert pr.main(["fixes", "--results", *files, "--no-offline-rungs"]) == 0
    assert json.loads(capsys.readouterr().out)["fix_calls_tasks"] == 0


def test_leave_one_out_reruns_the_rule_without_each_source():
    cands = []
    for src in ("a", "b", "c"):
        for t in range(6):
            cands.append(cand(f"t{t}", t % 2 == 0 or src == "c", source=src, compile_ok=t % 2 == 0 or src == "c"))
    rows = pr.leave_one_out(cands, "verified_first", 2)
    assert list(rows) == ["all", "a", "b", "c"] and rows["all"]["tasks"] == 6
    assert rows["c"]["delta"] == 0.0 and rows["a"]["delta"] > 0       # without the clean source nothing is selectable
