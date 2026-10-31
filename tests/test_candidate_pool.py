"""M5 candidate pool (star/candidate_pool.py): the recorders, the flags, reading, and the hooks in the ladder and in
best-of-N. Services are faked."""
import asyncio

import pytest

from star import candidate_pool as pool, verify_ladder as vl
from star.best_of_n import Candidate, CheckResult, Outcome

BROKEN = "local x = \nprint(x)\n"
GOOD = "local x = 1\nprint(x)\n"


def checker(code, strict=False):
    for number, line in enumerate(code.splitlines(), 1):
        if line.rstrip().endswith("="):
            return {"ran": True, "ok": False, "errors": [{"line": number, "column": 1, "kind": "SyntaxError",
                                                        "message": "Expected identifier"}]}
    return {"ran": True, "ok": True, "errors": []}


def fence(code):
    return f"```luau\n{code}```"


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    for name in ("STAR_VERIFY_SSH", "STAR_EVAL_SANDBOX_SSH", "STAR_EVAL_SSH", pool.ENV_DIR, pool.ENV_TAG):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("STAR_MISTAKE_LOG", str(tmp_path / "mistakes.jsonl"))


@pytest.fixture
def on(monkeypatch, tmp_path):
    monkeypatch.setenv(pool.ENV_DIR, str(tmp_path / "pools"))
    monkeypatch.setenv(pool.ENV_TAG, "arm A/1")
    return tmp_path / "pools" / "pool-arm-A-1.jsonl"


def test_off_writes_nothing_and_the_recorders_are_no_ops(tmp_path):
    assert not pool.active() and pool.pool_path() is None and not pool.write({"kind": "x"})
    assert pool.record_answer("p", "a", []) == ""
    pool.record_ladder_candidate("p", "", 1, 0, "first", None, "c", [], (0, 0), True)
    pool.record_block_final("p", "", 1, 0, True, 0, "")

    async def fix(code, failure, members):
        return fence(GOOD)
    asyncio.run(vl.review(fence(BROKEN), vl.Tools(checker=checker, fix=fix)))
    assert not list(tmp_path.glob("**/pool-*.jsonl"))


def test_the_ladder_writes_the_raw_answer_every_version_and_the_final_choice(on):
    async def fix(code, failure, members):
        return fence(GOOD)
    answer, record = asyncio.run(vl.review("Prose.\n\n" + fence(BROKEN), vl.Tools(checker=checker, fix=fix, prompt="print x")))
    lines = pool.read_lines(on)
    assert [r["kind"] for r in lines] == ["answer", "candidate", "candidate", "block_final"]
    raw, first, fixed, final = lines
    assert raw["answer"] == "Prose.\n\n" + fence(BROKEN) and raw["prompt_sha256"] == pool.prompt_key("print x")
    assert pool.rebuild_answer(raw["answer"], raw["blocks"], 1, GOOD) == "Prose.\n\n" + fence(GOOD)
    assert (first["origin"], first["idx"], first["parent"], first["ok"]) == ("first", 0, None, False)
    assert first["rungs"][0]["rung"] == "compile" and first["rungs"][0]["status"] == "fail"
    assert (fixed["origin"], fixed["idx"], fixed["parent"], fixed["ok"], fixed["accepted"]) == ("fix", 1, 0, True, True)
    assert fixed["code"].strip() == GOOD.strip() and fixed["fix_seconds"] is not None and fixed["rank"] > first["rank"]
    assert final["chosen"] == 1 and final["ok"] and final["rounds"] == 1
    assert all(r["schema"] == pool.SCHEMA and r["tag"] == "arm-A-1" for r in lines)
    assert record["verified"]


def test_a_rejected_fix_is_recorded_but_not_accepted(on):
    async def fix(code, failure, members):
        return fence(BROKEN.replace("print(x)", "print(x, 2)"))
    asyncio.run(vl.review(fence(BROKEN), vl.Tools(checker=checker, fix=fix, prompt="p")))
    candidates = [r for r in pool.read_lines(on) if r["kind"] == "candidate"]
    assert [(c["origin"], c["accepted"]) for c in candidates] == [("first", True), ("fix", False)]
    assert [r for r in pool.read_lines(on) if r["kind"] == "block_final"][0]["chosen"] == 0


def test_two_blocks_are_numbered_and_the_raw_answer_is_written_once(on):
    asyncio.run(vl.review(fence(GOOD) + "\n" + fence(GOOD.replace("1", "2")), vl.Tools(checker=checker, prompt="p")))
    lines = pool.read_lines(on)
    assert [r["kind"] for r in lines].count("answer") == 1
    assert sorted(r["block"] for r in lines if r["kind"] == "candidate") == [1, 2]


def test_best_of_n_candidates_are_written_with_their_checks(on):
    main = Candidate(1, "star-fast", 0.0, answer="main", code="m", seconds=3.21,
                     checks=[CheckResult("compile", "pass")], unit=(2, 3))
    extra = Candidate(2, "star-fast", 0.7, answer="extra", code="e", error="")
    pool.record_best_of_n("the prompt", Outcome("main", main, [main, extra]))
    rows = pool.read_lines(on)
    assert [(r["idx"], r["chosen"], r["temperature"]) for r in rows] == [(1, True, 0.0), (2, False, 0.7)]
    assert rows[0]["checks"] == [{"name": "compile", "status": "pass", "detail": "", "hard": True}]
    assert rows[0]["unit"] == [2, 3] and rows[0]["seconds"] == 3.2 and rows[0]["source"] == "best_of_n"


def test_private_addresses_are_scrubbed_and_a_failed_write_is_false(on, monkeypatch):
    address = ".".join(["10", "1", "2", "3"])             # built here so the source holds no private address
    assert pool.write({"kind": "answer", "answer": f"connect to {address} now"})
    assert address not in on.read_text(encoding="utf-8") and "<private-address>" in on.read_text(encoding="utf-8")
    monkeypatch.setenv(pool.ENV_DIR, str(on))            # a file where the folder should be
    assert not pool.write({"kind": "answer"})


def test_read_lines_skips_damage_and_refuses_a_newer_schema(tmp_path):
    path = tmp_path / "p.jsonl"
    path.write_text('{"kind": "answer", "schema": 1}\nnot json\n[1]\n{"no": "kind"}\n\n', encoding="utf-8")
    assert len(pool.read_lines(path)) == 1
    path.write_text('{"kind": "answer", "schema": 99}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="newer"):
        pool.read_lines(path)


def test_take_flags_sets_the_environment_and_returns_the_rest(monkeypatch):
    monkeypatch.setenv(pool.ENV_DIR, "")          # registers the restore: take_flags writes os.environ directly
    monkeypatch.setenv(pool.ENV_TAG, "")
    assert pool.take_flags(["run", "--pool", "D", "--suite", "s.json", "--pool-tag=night1"]) == ["run", "--suite", "s.json"]
    assert pool.pool_dir().name == "D" and pool.tag() == "night1"
    with pytest.raises(SystemExit):
        pool.take_flags(["run", "--pool"])


def test_evals_run_accepts_the_pool_flag_and_pool_goes_to_the_replay_tool(monkeypatch):
    from star import evals
    seen = {}
    monkeypatch.setenv(pool.ENV_DIR, "")
    monkeypatch.setenv(pool.ENV_TAG, "")
    monkeypatch.setattr("star.eval_runner.main", lambda args: seen.setdefault("run", args) and 0)
    monkeypatch.setattr("star.pool_replay.main", lambda args: seen.setdefault("pool", args) and 0)
    assert evals.main(["run", "--pool", "X", "--suite", "s.json"]) == 0
    assert seen["run"] == ["run", "--suite", "s.json"] and pool.pool_dir().name == "X"
    assert evals.main(["pool", "inspect", "--results", "r.json"]) == 0
    assert seen["pool"] == ["inspect", "--results", "r.json"]


def test_rebuild_answer_leaves_an_unknown_block_alone():
    assert pool.rebuild_answer("abc", [[0, 1]], 5, "x") == "abc"
    assert pool.rebuild_answer("a-b", [[1, 2]], 1, "XY") == "aXY\nb"
