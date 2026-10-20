"""The night conductor (server/night_school/nightschool/conductor.py): parsing, validators, duplicate check, nightly
cap, the window and the report. The model is a scripted function; the Luau check is night school's fake."""
import datetime as dt
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server" / "night_school"))

from nightschool import conductor, fake                                  # noqa: E402
from nightschool.config import Settings                                  # noqa: E402
from nightschool.engine import Yielded                                   # noqa: E402

REFERENCE = """--!strict
local Greeter = {}
function Greeter.welcome(name: string): string
\treturn "Welcome, " .. name .. "!"
end
return Greeter"""


def block(n: int = 1, **over) -> str:
    fields = {"category": "luau-typing", "difficulty": "1", "goal": f"Practise typed greeting helper {n}",
              "strict": "yes",
              "prompt": f"In my Roblox game: write a ModuleScript that returns a table Greeter{n}. Greeter{n}.welcome(name: string): "
                        f"string returns \"Welcome, \" followed by the name and an exclamation mark. Annotate every parameter and return type.",
              "reference": REFERENCE}
    fields.update(over)
    text = ("=== TASK ===\ncategory: {category}\ndifficulty: {difficulty}\ngoal: {goal}\nstrict: {strict}\nprompt: {prompt}\n"
            "require: welcome ::: Welcome,\\s ::: greets\nrequire: ret ::: \\):\\s*string ::: typed return\n"
            "forbid: loadstr ::: loadstring ::: no loadstring\nreference:\n```lua\n{reference}\n```\n").format(**fields)
    return text


def settings_for(tmp_path, **changes) -> Settings:
    values = dict(home=tmp_path / "learning", conductor_models="star-fast", conductor_max_new=40,
                  conductor_tz_hours=0.0, lock_dir=str(tmp_path / "no-lock"))
    values.update(changes)
    made = Settings(**values)
    made.ensure_dirs()
    return made


def validators(settings, **changes):
    values = dict(luau_check=fake.luau_ok, pool_dir=Path(settings.pool))
    values.update(changes)
    return conductor.Validators(**values)


NIGHT = dt.datetime(2026, 10, 17, 23, 0, tzinfo=dt.timezone.utc)


# --- parsing and schema --------------------------------------------------------------------------------------------

def test_parse_reply_reads_diagnosis_and_blocks():
    diagnosis, raws = conductor.parse_reply("DIAGNOSIS: forgets to annotate returns\n" + block(1) + block(2))
    assert diagnosis == "forgets to annotate returns"
    assert len(raws) == 2
    assert raws[0]["require"][1] == {"id": "ret", "re": "\\):\\s*string", "why": "typed return"}
    assert raws[0]["reference"].startswith("--!strict")
    assert raws[1]["prompt"].startswith("In my Roblox game:")


def test_build_task_makes_a_loader_shaped_task():
    _, raws = conductor.parse_reply(block(1))
    task, why = conductor.build_task(raws[0], "20261017")
    assert why == "" and task["id"].startswith("conductor-20261017-")
    assert task["run_mode"] == "automated" and task["auto"]["strict"] is True
    assert task["auto"]["require"][0]["id"] == "strict_header"          # strict tasks get the header check


@pytest.mark.parametrize("over,reason", [
    ({"prompt": "too short"}, "length"),
    ({"prompt": "In my Roblox game: write a Paintball round manager module with start and stop functions and timers please."}, "blocked"),
    ({"prompt": "In my Roblox game: connect to " + ".".join(["10", "1", "2", "3"]) + " and write a module with a function that returns the status string."}, "blocked"),
    ({"reference": "x"}, "reference length"),
    ({"category": "!!"}, "category"),
])
def test_build_task_refuses_bad_blocks(over, reason):
    _, raws = conductor.parse_reply(block(1, **over))
    task, why = conductor.build_task(raws[0], "20261017")
    assert task is None and reason in why


def test_build_task_refuses_bad_and_runaway_regex():
    _, raws = conductor.parse_reply(block(1).replace("\\):\\s*string", "(unclosed"))
    assert "does not compile" in conductor.build_task(raws[0], "x")[1]
    _, raws = conductor.parse_reply(block(1).replace("\\):\\s*string", "(a+)+b"))
    assert "run away" in conductor.build_task(raws[0], "x")[1]
    _, raws = conductor.parse_reply(block(1).replace("require: ret", "require: broken line without separators\nrequire: ret"))
    assert conductor.build_task(raws[0], "x")[0] is None


# --- validators ----------------------------------------------------------------------------------------------------

def _task(n=1, **over):
    _, raws = conductor.parse_reply(block(n, **over))
    task, why = conductor.build_task(raws[0], "20261017")
    assert task, why
    return task, raws[0]["reference"]


def test_good_task_passes_and_trivial_answer_control_works(tmp_path):
    s = settings_for(tmp_path)
    task, ref = _task()
    assert validators(s).check(task, ref) == ""


def test_reference_that_fails_its_own_checks_is_refused(tmp_path):
    s = settings_for(tmp_path)
    task, _ = _task()
    why = validators(s).check(task, "--!strict\nlocal x = 1\nreturn x")
    assert why.startswith("reference fails its own task")


def test_vacuous_checks_are_refused(tmp_path):
    s = settings_for(tmp_path)
    task, ref = _task()
    task["auto"]["require"] = [{"id": "any", "re": "print", "why": "x"}, {"id": "any2", "re": "hello", "why": "y"}]
    task["auto"]["strict"] = False
    assert validators(s).check(task, "print('hello')") == "checks too weak: a trivial answer passes"


def test_luau_error_in_reference_is_refused(tmp_path):
    s = settings_for(tmp_path)
    task, ref = _task()
    bad = lambda code, strict=False: {**fake.luau_ok(code), "ok": False, "errors": [{"kind": "SyntaxError", "message": "boom", "line": 1}]}   # noqa: E731
    assert "luau_check" in validators(s, luau_check=bad).check(task, ref)


def test_roblox_api_checker_refuses_invented_members(tmp_path):
    from star.roblox_api_dataset import api_dump
    s = settings_for(tmp_path)
    ref = 'local p = Instance.new("NotARealClass")\nreturn p'
    task, _ = _task(reference=REFERENCE)
    task["auto"]["require"] = [{"id": "inst", "re": "Instance\\.new", "why": "x"}, {"id": "ret", "re": "return", "why": "y"}]
    task["auto"]["strict"] = False
    why = validators(s, api_dump=api_dump()).check(task, ref)
    assert why.startswith("roblox api")


def test_duplicates_are_refused_by_id_hash_and_near_copy(tmp_path):
    s = settings_for(tmp_path)
    v = validators(s)
    task, ref = _task(1)
    assert v.check(task, ref) == ""
    v.remember(task)
    assert v.check(task, ref) == "duplicate: same task"
    near, _ = _task(1, prompt=task["prompt"].replace("Annotate", "Please annotate"))
    assert v.check(near, ref) == "duplicate: near copy of a pool task"
    other, _ = _task(2, prompt="In my Roblox game: write a ModuleScript Inventory with add(itemId: string, count: number) that "
                               "stores counts per item in a table and remove(itemId: string): boolean that refuses missing items.")
    assert v.check(other, ref) == ""


def test_copy_of_an_evaluation_prompt_is_refused(tmp_path):
    s = settings_for(tmp_path)
    task, ref = _task()
    from nightschool.pool import prompt_hash
    (Path(s.pool) / "forbidden-prompts.json").write_text(json.dumps({"prompt_sha256": [prompt_hash(task["prompt"])], "ids": []}))
    assert validators(s).check(task, ref).startswith("loader:")


# --- one cycle -----------------------------------------------------------------------------------------------------

def failure(i, cat="luau-typing", validation=False, ts="2026-10-17T20:00:00Z"):
    return {"ts": ts, "task": f"T{i}", "category": cat, "validation": validation, "prompt": f"practise {i}",
            "answer": "code", "reasons": [f"luau_check[1]: line {i}: type mismatch"]}


def test_cluster_failures_groups_by_category_and_first_reason_and_skips_validation(tmp_path):
    rows = [failure(i) for i in range(5)] + [failure(9, cat="remote-security")] + [failure(7, validation=True)]
    path = tmp_path / "failures.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    got = conductor.read_failures(path, "2026-10-17T00:00:00Z")
    assert len(got) == 6                                     # validation row left out
    clusters = conductor.cluster_failures(got)
    assert clusters[0]["category"] == "luau-typing" and clusters[0]["count"] == 5
    assert clusters[1]["category"] == "remote-security"


def test_cycle_accepts_valid_tasks_dedups_and_writes_report(tmp_path):
    s = settings_for(tmp_path)
    Path(s.data, "failures.jsonl").write_text("\n".join(json.dumps(failure(i)) for i in range(3)), encoding="utf-8")
    prompts = []
    # cluster call -> 2 good + 1 duplicate of the first + 1 bad format; ideas calls -> nothing usable
    def ask(model, system, user):
        prompts.append(user)
        if "student failed" in user:
            return "DIAGNOSIS: needs return types\n" + block(1) + block(2, prompt=block(2).split("prompt: ")[1].split("\n")[0].replace("Greeter2", "Greeter1")) + block(3, prompt="short") + block(4, prompt="In my Roblox game: write a ModuleScript Queue with push(value: number) and pop(): number? using a table, keeping first in first out order and returning nil when empty.")
        return "DIAGNOSIS: none\n"
    result = conductor.run_cycle(s, ask, validators(s), now=NIGHT, models=["star-fast"], log=lambda *_: None)
    assert result["created"] == 4 and result["accepted"] == 2
    assert sum(result["rejected"].values()) == 2
    assert "format: prompt or goal length" in result["rejected"]
    rows = json.loads(conductor.pool_file(s, "20261017").read_text(encoding="utf-8"))
    assert len(rows) == 2 and all(r["id"].startswith("conductor-20261017-") for r in rows)
    assert len(prompts) == 3 and "Recent project notes" in prompts[1]
    report = (s.conductor_dir / "report-20261017.md").read_text(encoding="utf-8")
    assert "accepted into pool/conductor-20261017.json: 2" in report and "needs return types" in report
    assert "10." not in report.replace("2026-10-17", "")
    assert (s.conductor_dir / "summary.txt").read_text(encoding="utf-8").startswith("Night conductor 20261017: created 4, accepted 2")
    # the pool loader accepts the file
    from nightschool.pool import load_pool
    assert len([t for t in load_pool(Path(s.pool)).tasks if t["id"].startswith("conductor-")]) == 2


def test_nightly_cap_is_enforced_across_cycles(tmp_path):
    s = settings_for(tmp_path, conductor_max_new=3)
    counter = {"n": 0}

    def ask(model, system, user):
        out = "DIAGNOSIS: none\n"
        for _ in range(4):
            counter["n"] += 1
            n = counter["n"]
            out += block(n, prompt="In my Roblox game: write a ModuleScript " + " ".join(f"{w}{n}" for w in ("alpha", "beta", "gamma", "delta", "kappa", "sigma", "omega", "theta", "lambda", "zeta", "omicron", "upsilon")) + " that does something useful.")
        return out
    first = conductor.run_cycle(s, ask, validators(s), now=NIGHT, models=["m"], log=lambda *_: None)
    assert first["accepted"] == 3 and first["night_total"] == 3
    second = conductor.run_cycle(s, ask, validators(s), now=NIGHT, models=["m"], log=lambda *_: None)
    assert second["accepted"] == 0 and second["night_total"] == 3 and second["calls"] == 0
    assert len(json.loads(conductor.pool_file(s, "20261017").read_text(encoding="utf-8"))) == 3


def test_new_night_starts_a_new_file_and_count(tmp_path):
    s = settings_for(tmp_path, conductor_max_new=1)
    ask = lambda model, system, user: "DIAGNOSIS: none\n" + block(len(user) % 7)   # noqa: E731
    conductor.run_cycle(s, ask, validators(s), now=NIGHT, models=["m"], log=lambda *_: None)
    later = NIGHT + dt.timedelta(days=1)
    result = conductor.run_cycle(s, lambda m, a, b: "DIAGNOSIS: none\n" + block(5, goal="Practise another thing entirely here"),
                                 validators(s), now=later, models=["m"], log=lambda *_: None)
    assert result["night_total"] <= 1
    assert conductor.pool_file(s, "20261017").is_file()


def test_yield_propagates_and_other_errors_do_not_stop_the_cycle(tmp_path):
    s = settings_for(tmp_path)

    def stranger(model, system, user):
        raise Yielded("another client")
    with pytest.raises(Yielded):
        conductor.run_cycle(s, stranger, validators(s), now=NIGHT, models=["m"], log=lambda *_: None)

    def broken(model, system, user):
        raise ConnectionError("down")
    result = conductor.run_cycle(s, broken, validators(s), now=NIGHT, models=["m"], log=lambda *_: None)
    assert result["accepted"] == 0 and any("no reply" in n for n in result["notes"])


def test_infrastructure_failure_stops_cycle_without_rejecting(tmp_path):
    from star.eval_checks import InfraError
    s = settings_for(tmp_path)

    def down(code, strict=False):
        raise OSError("knowledge down")
    result = conductor.run_cycle(s, lambda m, a, b: "DIAGNOSIS: none\n" + block(1), validators(s, luau_check=down), now=NIGHT,
                                 models=["m"], log=lambda *_: None)
    assert result["accepted"] == 0 and result["rejected"] == {} and any("cycle stopped" in n for n in result["notes"])
    assert InfraError


# --- window, switches, models ---------------------------------------------------------------------------------------

def test_window_night_key_and_switches(tmp_path):
    s = settings_for(tmp_path, conductor_tz_hours=-5.0)
    utc = lambda h, d=17: dt.datetime(2026, 10, d, h, 0, tzinfo=dt.timezone.utc)   # noqa: E731
    assert conductor.in_window(s, utc(0, 18))          # 19:00 local on the 17th
    assert conductor.in_window(s, utc(11))             # 06:00 local
    assert not conductor.in_window(s, utc(16))         # 11:00 local
    assert conductor.night_key(s, utc(11)) == "20261016"       # 06:00 local belongs to the night that began the day before
    assert conductor.night_key(s, utc(0, 18)) == "20261017"
    assert conductor.due(s, {}, utc(16)) == "outside the night window"
    assert conductor.due(s, {}, utc(2), 1e10) == ""
    assert "ran less" in conductor.due(s, {"finished_at": 1e10 - 60}, utc(2), 1e10)
    s.conductor_off_file.write_text("off")
    assert "CONDUCTOR_OFF" in conductor.due(s, {}, utc(2), 1e10)
    s.conductor_off_file.unlink()
    s.conductor = "off"
    assert "switched off" in conductor.due(s, {}, utc(2), 1e10)


def test_pick_models_skips_single_slot_and_unloaded(tmp_path):
    from nightschool.idle import BrainWatch
    table = {"/v1/models": {"data": [{"id": "star-deep", "status": {"value": "loaded"}}, {"id": "star-fast", "status": {"value": "loaded"}},
                                     {"id": "star-quick", "status": {"value": "unloaded"}}]},
             "/slots?model=star-deep": [{"id": 0, "is_processing": False}],
             "/slots?model=star-fast": [{"id": 0, "is_processing": False}, {"id": 1, "is_processing": False}]}
    watch = BrainWatch("http://x", fetch=lambda path: table[path])
    s = settings_for(tmp_path, conductor_models="star-deep,star-fast,star-quick")
    assert conductor.pick_models(s, watch) == ["star-fast"]


def test_recent_docs_skips_old_and_paintball_notes(tmp_path):
    import os
    import time
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "new.md").write_text("# New\nround timers and teams", encoding="utf-8")
    (folder / "pb-conduct.md").write_text("# secret", encoding="utf-8")
    (folder / "mentions.md").write_text("Rec Room Paintball remake notes", encoding="utf-8")
    old = folder / "old.md"
    old.write_text("# Old", encoding="utf-8")
    os.utime(old, (time.time() - 5 * 86400,) * 2)
    assert [name for name, _ in conductor.recent_docs(folder)] == ["new.md"]


def test_parser_is_lenient_about_backticks_ids_none_forbid_and_missing_goal():
    reply = ("=== TASK ===\ncategory: remote-security\ndifficulty: 2\nstrict: no\nprompt: In my Roblox game: write a ModuleScript Guard with "
             "check(itemId: string, price: number): boolean that returns true only for a non-empty string and a positive price.\n"
             "require: `return true` ::: `return\s+true` ::: returns true on success\n"
             "require: `string check` ::: `type\(itemId\)` ::: checks the id type\n"
             "forbid: none\nreference:\n```lua\nlocal Guard = {}\nfunction Guard.check(itemId: string, price: number): boolean\n"
             "\tif type(itemId) ~= \"string\" or itemId == \"\" then return false end\n\treturn price > 0\nend\nreturn Guard\n```\n")
    _, raws = conductor.parse_reply(reply)
    assert raws[0]["forbid"] == [] and "error" not in raws[0]
    assert [c["id"] for c in raws[0]["require"]] == ["return_true", "string_check"] and raws[0]["require"][0]["re"] == r"return\s+true"
    task, why = conductor.build_task(raws[0], "20261017")
    assert task and why == "" and task["goal"].startswith("write a ModuleScript Guard")


def test_rejected_samples_are_kept_for_tuning(tmp_path):
    s = settings_for(tmp_path)
    conductor.run_cycle(s, lambda m, a, b: "DIAGNOSIS: none\n" + block(1, prompt="short"), validators(s), now=NIGHT, models=["m"],
                        log=lambda *_: None)
    lines = (s.conductor_dir / "rejected-20261017.jsonl").read_text(encoding="utf-8").splitlines()
    assert lines and json.loads(lines[0])["reason"] == "format: prompt or goal length"


# --- variants of solved tasks and the repair round (star-finetune-20261018) ------------------------------------------

def solved(i, cat="luau-typing"):
    return {"ts": "2026-10-17T21:00:00Z", "task": f"S{i}", "category": cat, "kind": "first", "verified": True,
            "prompt": f"In my Roblox game: write module Solved{i} with a typed function.",
            "answer": f"Here:\n```lua\nlocal M{i} = {{}}\nreturn M{i}\n```\n"}


def test_recent_solved_rotates_and_skips_river_and_blocked(tmp_path):
    rows = [solved(i) for i in range(5)] + [solved(8, cat="river-paintball-native-cases"), dict(solved(9), prompt="Paintball gun")]
    path = tmp_path / "examples.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    assert [r["task"] for r in conductor.recent_solved(path, 0, 2)] == ["S0", "S1"]
    assert [r["task"] for r in conductor.recent_solved(path, 4, 2)] == ["S4", "S0"]
    assert conductor.recent_solved(tmp_path / "missing.jsonl", 0, 2) == []
    path.write_text("\n".join(json.dumps(r) for r in [solved(1, cat="ledger-x"), solved(2), solved(3, cat="ledger-y"), solved(4)]), encoding="utf-8")
    assert [r["task"] for r in conductor.recent_solved(path, 0, 2)] == ["S2", "S4"]     # others before ledger tasks
    assert len(conductor.recent_solved(path, 0, 3)) == 3                                  # too few others: all


def test_cycle_asks_for_variants_of_solved_tasks(tmp_path):
    s = settings_for(tmp_path)
    Path(s.data, "examples.jsonl").write_text("\n".join(json.dumps(solved(i)) for i in range(5)), encoding="utf-8")
    prompts = []

    def ask(model, system, user):
        prompts.append(user)
        return "DIAGNOSIS: none\n" + (block(7) if "SOLVED" in user and "Solved0" in user else "")
    result = conductor.run_cycle(s, ask, validators(s), now=NIGHT, models=["m"], log=lambda *_: None)
    variant_calls = [p for p in prompts if p.startswith("The student SOLVED")]
    assert len(variant_calls) == 2 and "Solved0" in variant_calls[0] and "Solved2" in variant_calls[1]
    assert "local M0 = {}" in variant_calls[0]                       # the passing code is shown, not the prose
    assert result["accepted"] == 1 and result["by_kind"] == {"variants": 1}
    assert conductor.load_state(s)["variant_cursor"] == 4
    report = (s.conductor_dir / "report-20261017.md").read_text(encoding="utf-8")
    assert 'accepted by source: {"variants": 1}' in report


def test_repair_round_fixes_a_failing_reference_once(tmp_path):
    s = settings_for(tmp_path)
    broken = REFERENCE.replace("Welcome, ", "Hello ")              # misses the required "Welcome," pattern
    calls = {"repair": 0}

    def ask(model, system, user):
        if user.startswith("This practice task's reference"):
            calls["repair"] += 1
            assert "FAILED: reference fails its own task" in user and "Hello " in user
            return "```lua\n" + REFERENCE + "\n```"
        if "student failed" in user or "Recent project notes" in user:
            return "DIAGNOSIS: none\n" + (block(1, reference=broken) if "student failed" not in user and calls["repair"] == 0 else "")
        return ""
    result = conductor.run_cycle(s, ask, validators(s), now=NIGHT, models=["m"], log=lambda *_: None)
    assert calls["repair"] == 1 and result["accepted"] == 1 and result["repaired"] == 1
    refs = (s.conductor_dir / "references-20261017.jsonl").read_text(encoding="utf-8")
    assert "Welcome, " in refs and "Hello " not in refs


def test_repair_that_still_fails_is_rejected_and_capped(tmp_path):
    s = settings_for(tmp_path)
    broken = REFERENCE.replace("Welcome, ", "Hello ")
    repairs = []

    def ask(model, system, user):
        if user.startswith("This practice task's reference"):
            repairs.append(user)
            return "```lua\n" + broken + "\n```"
        out = "DIAGNOSIS: none\n"
        for n in range(4):
            words = " ".join(f"{w}{len(user)}{n}" for w in ("alpha", "beta", "gamma", "delta", "kappa", "sigma", "omega", "theta"))
            out += block(n, reference=broken, prompt="In my Roblox game: write a ModuleScript " + words + " that greets people.")
        return out
    result = conductor.run_cycle(s, ask, validators(s), now=NIGHT, models=["m"], log=lambda *_: None)
    assert result["accepted"] == 0 and len(repairs) == conductor.MAX_REPAIRS_PER_CYCLE
    assert any(k.startswith("reference fails its own task") for k in result["rejected"])


def test_pc_turbo_conductor_uses_its_own_slot_0_and_a_tagged_pool_file(tmp_path):
    from nightschool.idle import BrainWatch
    table = {"/v1/models": {"data": [{"id": "star-fast"}]}, "/slots?model=star-fast": [{"id": 0, "is_processing": False}]}
    watch = BrainWatch("http://x", fetch=lambda path: table[path])
    assert conductor.pick_models(settings_for(tmp_path, conductor_models="star-fast"), watch) == []
    s = settings_for(tmp_path, conductor_models="star-fast", slot=0, conductor_tag="pc-")
    assert conductor.pick_models(s, watch) == ["star-fast"]                   # STAR_NS_SLOT=0: night school's own server
    assert conductor.pool_file(s, "20261017").name == "conductor-pc-20261017.json"
