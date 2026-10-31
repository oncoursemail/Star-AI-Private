"""Night school (server/night_school): polite scheduling, the practice pool, the learning cycle, the report and the
real answer path. No test sends anything to a real model: the brain is a scripted fake on a loopback port."""
import json
from pathlib import Path
import sys
import time

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server" / "night_school"))

from nightschool import fake, report                                    # noqa: E402
from nightschool.config import Settings                                 # noqa: E402
from nightschool.engine import Engine, Result, Store, Yielded, classify, clean_lesson, scrub   # noqa: E402
from nightschool.idle import BrainWatch, IdleGate, activity             # noqa: E402
from nightschool.pool import GUARD_FILE, Pool, build_guard, is_validation, load_pool, prompt_hash   # noqa: E402


def settings_for(tmp_path, **changes) -> Settings:
    values = dict(home=tmp_path / "learning", idle_s=600, poll_s=10, watch_s=0.2, validation_percent=100,
                  validation_max=2, batch=5, recheck_every=3, lock_dir=str(tmp_path / "no-lock"))
    values.update(changes)
    made = Settings(**values)
    made.ensure_dirs()
    return made


# --- polite scheduling ------------------------------------------------------------------------------------------

class Slots:
    """A slot table the test edits; counts how often it was read."""

    def __init__(self):
        self.table = {("star-fast", 0): [False, 5], ("star-fast", 1): [False, 9], ("star-embed", 0): [False, 1]}
        self.fail = False

    def fetch(self, path):
        if self.fail:
            raise OSError("down")
        if path == "/v1/models":
            return {"data": [{"id": m, "status": {"value": "loaded"}, "aliases": ["star-code"] if m == "star-fast" else []}
                             for m in sorted({m for m, _ in self.table})]
                    + [{"id": "star-deep", "status": {"value": "unloaded"}}]}
        model = path.split("=", 1)[1]
        return [{"id": s, "is_processing": v[0], "id_task": v[1]} for (m, s), v in sorted(self.table.items()) if m == model]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def gate_for(tmp_path, slots, clock, said, **changes):
    settings = settings_for(tmp_path, **changes)
    return settings, IdleGate(settings, BrainWatch("http://brain", fetch=slots.fetch), log=said.append, clock=clock,
                              sleep=clock.sleep)


def test_activity_sees_a_busy_slot_and_a_changed_task_number_but_not_the_own_slot():
    before = {("star-fast", 0): (False, 5), ("star-fast", 1): (False, 9), ("star-embed", 0): (False, 1)}
    assert activity(before, dict(before)) == []
    assert activity(before, {**before, ("star-fast", 0): (True, 5)}) == ["star-fast/0"]
    assert activity(before, {**before, ("star-fast", 1): (False, 10)}) == ["star-fast/1"]      # served between two looks
    own = {**before, ("star-fast", 1): (True, 10), ("star-embed", 0): (True, 2)}
    assert activity(before, own, own_slot=1, skip_helpers=True) == []
    assert activity(before, {**own, ("star-fast", 0): (True, 6)}, own_slot=1, skip_helpers=True) == ["star-fast/0"]


def test_the_gate_waits_while_the_brain_is_busy_and_needs_ten_quiet_minutes(tmp_path):
    slots, clock, said = Slots(), Clock(), []
    slots.table[("star-fast", 1)][0] = True                     # an evaluation run is using the brain
    settings, gate = gate_for(tmp_path, slots, clock, said)
    assert gate.look() == "brain busy, waiting"
    clock.sleep(700)
    assert gate.look() == "brain busy, waiting"                 # still busy: time alone does not help
    slots.table[("star-fast", 1)] = [False, 10]
    assert gate.look() == "brain busy, waiting"                 # it just finished a request (task number moved)
    assert "quiet" in gate.look()
    clock.sleep(599)
    assert "quiet" in gate.look()
    slots.table[("star-embed", 0)][1] += 1                      # a documentation search alone (helper model)
    assert "quiet" in gate.look()                               # is not somebody using the brain
    slots.table[("star-fast", 0)][1] += 1                       # a chat turn is
    assert gate.look() == "brain busy, waiting"
    assert "quiet" in gate.look()
    clock.sleep(601)
    assert gate.look() == ""


class ProxiedSlots(Slots):
    """The same brain seen through STAR's priority proxy (star/priority_proxy.py answers /priority/v1/status)."""

    def __init__(self):
        super().__init__()
        self.proxy_up = True

    def fetch(self, path):
        if path == "/priority/v1/status":
            if not self.proxy_up:
                raise OSError("no proxy")
            return {"p0_active": False, "classes": {"P0": {}, "P3": {}}, "models": {}}
        return super().fetch(path)


def test_priority_gate_works_beside_other_clients_when_the_proxy_schedules(tmp_path):
    from nightschool.idle import PriorityGate
    slots, clock, said = ProxiedSlots(), Clock(), []
    settings = settings_for(tmp_path, gate="priority")
    gate = PriorityGate(settings, BrainWatch("http://brain", fetch=slots.fetch), log=said.append, clock=clock,
                        sleep=clock.sleep)
    slots.table[("star-fast", 0)][0] = True                     # the owner is chatting on another slot
    assert gate.look() == ""                                    # no ten-minute wait: the proxy pauses us for chat
    assert gate.intruder(1) == ""                               # and a chat does not cancel our request
    Path(settings.hold_file).write_text("hold")
    assert gate.look() == "HOLD file present, paused" and gate.intruder(1) == "HOLD file"
    Path(settings.hold_file).unlink()
    slots.proxy_up = False                                      # brain URL not behind the proxy: the old idle gate
    clock.sleep(60)
    assert gate.look() == "brain busy, waiting"
    assert gate.intruder(1).startswith("another client")


def test_priority_gate_is_chosen_by_setting(tmp_path):
    from nightschool.__main__ import make_gate
    from nightschool.idle import PlannedGate, PriorityGate
    watch = BrainWatch("http://brain", fetch=ProxiedSlots().fetch)
    assert isinstance(make_gate(settings_for(tmp_path, gate="priority"), watch, planner=None), PriorityGate)
    assert type(make_gate(settings_for(tmp_path), watch, planner=None)) is PlannedGate


def test_wait_logs_brain_busy_once_and_returns_after_the_quiet_period(tmp_path):
    slots, clock, said = Slots(), Clock(), []
    slots.table[("star-fast", 1)][0] = True
    settings, gate = gate_for(tmp_path, slots, clock, said)
    looks = {"n": 0}
    real_look = gate.look

    def look():
        looks["n"] += 1
        if looks["n"] == 4:
            slots.table[("star-fast", 1)] = [False, 9]
        return real_look()
    gate.look = look
    assert gate.wait() is True
    assert said[0] == "brain busy, waiting" and said.count("brain busy, waiting") == 1
    assert said[-1] == "brain idle, working"
    assert clock.now - 1000.0 >= 600


def test_hold_file_lock_and_unreachable_brain_all_pause(tmp_path):
    slots, clock, said = Slots(), Clock(), []
    settings, gate = gate_for(tmp_path, slots, clock, said, idle_s=0)
    assert gate.look() == ""
    settings.hold_file.write_text("", encoding="utf-8")
    assert gate.look() == "HOLD file present, paused"
    assert gate.intruder(1) == "HOLD file"
    settings.hold_file.unlink()
    lock = Path(settings.lock_dir)
    lock.mkdir()
    assert gate.look() == "quiet lock held, waiting"
    lock.rmdir()
    slots.fail = True
    assert gate.look() == "brain not reachable, waiting"
    assert gate.wait(stop=lambda: True) is False


def test_intruder_ignores_the_own_slot_and_backs_off_for_any_other(tmp_path):
    slots, clock, said = Slots(), Clock(), []
    settings, gate = gate_for(tmp_path, slots, clock, said, idle_s=0)
    assert gate.look() == ""
    slots.table[("star-fast", 1)] = [True, 10]                  # night school's own request
    slots.table[("star-embed", 0)] = [True, 2]                  # its own documentation search
    assert gate.intruder(1) == ""
    slots.table[("star-fast", 0)] = [True, 6]                   # the app, on slot 0
    assert gate.intruder(1) == "another client on star-fast/0"
    slots.table[("star-fast", 0)] = [False, 6]
    slots.table[("star-fast", 1)] = [False, 10]
    slots.table[("star-embed", 0)] = [False, 2]
    gate.own_work_done()
    gate.settings.idle_s = 600
    assert "quiet" in gate.look()                               # after an intruder the full quiet period starts again


def test_slot_choice_is_never_zero_when_the_model_has_two_slots():
    slots = Slots()
    watch = BrainWatch("http://brain", fetch=slots.fetch)
    chosen = watch.slot_for(1)
    assert chosen["star-fast"] == 1 and chosen["star-code"] == 1
    assert chosen["star-embed"] == 0                            # a single slot: callers must refuse it
    assert "star-deep" not in chosen                            # not loaded


# --- the practice pool ------------------------------------------------------------------------------------------

def write_pool(folder: Path, name: str, tasks) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(json.dumps(tasks), encoding="utf-8")


def test_pool_keeps_what_the_real_loader_accepts_and_counts_what_it_drops(tmp_path):
    folder = tmp_path / "pool"
    good = [fake.practice_task("P-01", "limitA"), fake.practice_task("P-02", "limitB")]
    no_prompt = {**fake.practice_task("P-03", "limitC"), "prompt": ""}
    no_goal = {k: v for k, v in fake.practice_task("P-04", "limitD").items() if k != "goal"}
    studio = {**fake.practice_task("P-05", "limitE"), "run_mode": "studio", "studio_check": {"x": 1}}
    bad_regex = fake.practice_task("P-06", "limitF", needs="(")
    missing_test = fake.practice_task("P-07", "limitG")
    missing_test["auto"]["unit_test"] = {"file": "tests/nope.luau", "checks": 3}
    with_test = fake.practice_task("P-08", "limitH")
    with_test["auto"]["unit_test"] = {"file": "tests/P-08.luau", "checks": 1}
    (folder / "tests").mkdir(parents=True)
    (folder / "tests" / "P-08.luau").write_bytes(b"check('one', true)\r\n")
    (folder / "prelude.luau").write_text("-- prelude\n", encoding="utf-8")
    write_pool(folder, "a.json", good + [no_prompt, no_goal, studio, bad_regex, missing_test, with_test, good[0], "junk"])
    write_pool(folder, "b.json", {"not": "a list"})
    (folder / "c.json").write_text("{broken", encoding="utf-8")
    write_pool(folder, "golden-tasks-v2.json", [fake.practice_task("G-01", "limitZ")])
    write_pool(folder, "holdout-v1.json", [fake.practice_task("HO-01", "limitY")])
    pool = load_pool(folder)
    assert [t["id"] for t in pool.tasks] == ["P-01", "P-02", "P-08"]
    assert pool.tasks[2]["_test_body"] == "check('one', true)\n" and pool.prelude == "-- prelude\n"
    assert pool.dropped == {
        "loader refused: prompt missing": 1, "loader refused: Missing evaluation specification: goal": 1,
        "loader refused: bad require pattern uses_expected_call": 1, "loader refused: unit test file missing": 1,
        "not automated": 1, "duplicate id": 1, "no id": 1, "file is not a task list": 1, "file is not JSON": 1,
        "evaluation file refused": 2}
    assert pool.summary().startswith("3 practice tasks loaded from 3 files; 11 dropped")


def test_copies_of_evaluation_tasks_are_dropped_by_hash_and_the_blind_exam_is_never_read(tmp_path):
    suite = tmp_path / "golden-tasks-v2.json"
    measured = fake.practice_task("ENG-01", "limitA")
    suite.write_text(json.dumps([measured]), encoding="utf-8")
    guard = build_guard([suite])
    assert guard == {"prompt_sha256": [prompt_hash(measured["prompt"])], "ids": ["ENG-01"]}
    assert "limitA" not in json.dumps(guard)                    # hashes only
    with pytest.raises(ValueError):
        build_guard([tmp_path / "holdout-v1.json"])
    folder = tmp_path / "pool"
    copy = {**measured, "id": "P-99", "prompt": measured["prompt"].upper() + "  "}
    write_pool(folder, "a.json", [copy, fake.practice_task("P-01", "limitB"), fake.practice_task("HO-X", "limitC"),
                                  fake.practice_task("ENG-01", "limitD")])
    (folder / GUARD_FILE).write_text(json.dumps(guard), encoding="utf-8")
    pool = load_pool(folder)
    assert [t["id"] for t in pool.tasks] == ["P-01"]
    assert pool.dropped == {"copy of an evaluation task": 3}


def test_validation_split_is_fixed_by_the_task_id():
    ids = [f"T-{i}" for i in range(400)]
    chosen = [i for i in ids if is_validation(i, 20)]
    assert chosen == [i for i in ids if is_validation(i, 20)]
    assert 50 <= len(chosen) <= 110


# --- the learning cycle (pure: scripted solve and diagnose) -----------------------------------------------------

class Script:
    """Tasks whose id starts with H need the lesson; E tasks pass at once; X tasks never pass; V are validation."""

    def __init__(self):
        self.calls = []
        self.harmful = set()            # lesson texts that break validation tasks
        self.lesson = fake.LESSON
        self.interrupt_on = None
        self.error_on = set()

    def solve(self, task, lessons):
        self.calls.append((task["id"], tuple(l["id"] for l in lessons)))
        if self.interrupt_on == task["id"]:
            raise Yielded("another client on star-fast/0")
        if task["id"] in self.error_on:
            return Result(error="Luau check unavailable")
        texts = {l["text"] for l in lessons}
        kind = task["id"][0]
        if kind == "V":
            passed = not (texts & self.harmful) and (not task["id"].startswith("V-needs") or self.lesson in texts)
        else:
            passed = kind == "E" or (kind == "H" and self.lesson in texts)
        reasons = [] if passed else ["require:uses_expected_call: the expected call is used"]
        return Result(passed, reasons, [{"id": "luau_block", "ok": True}], "```lua\nreturn 1\n```", 2.0,
                      [l["id"] for l in lessons])

    def diagnose(self, task, result):
        return {"cause": "chained ifs instead of the clamp call", "lesson": self.lesson}


def engine_for(tmp_path, ids, script, **changes):
    changes.setdefault("validation_max", len([i for i in ids if i.startswith("V")]))
    settings = settings_for(tmp_path, **changes)
    tasks = [fake.practice_task(i, "limit" + i.replace("-", "")) for i in ids]
    store = Store(settings.data)
    # Validation tasks are named here by hand: ids starting with V.
    store.state["validation_ids"] = [i for i in ids if i.startswith("V")]
    engine = Engine(settings, Pool(tasks, {}, 1, ""), store, solve=script.solve, diagnose=script.diagnose,
                    log=lambda _text: None)
    return settings, store, engine


def test_a_pass_is_stored_as_a_worked_example_and_a_failure_creates_a_candidate_only_if_the_lesson_fixes_it(tmp_path):
    script = Script()
    settings, store, engine = engine_for(tmp_path, ["E-1", "H-1", "X-1", "V-1", "V-2"], script)
    assert [t["id"] for t in engine.training] == ["E-1", "H-1", "X-1"]
    assert engine.run_item(engine.training[0]) == "passed_first"
    assert engine.run_item(engine.training[1]) == "fixed"
    assert engine.run_item(engine.training[2]) == "failed"
    c = store.state["counters"]
    assert (c["tasks_tried"], c["passed_first"], c["fixed_by_lesson"], c["still_failing"]) == (3, 1, 1, 1)
    lessons = store.state["lessons"]
    assert list(lessons) == ["L1"] and lessons["L1"]["status"] == "candidate" and lessons["L1"]["fixed"] == ["H-1"]
    assert lessons["L1"]["evidence"][0]["fixed"] == "H-1"
    # X-1 failed with the waiting candidate, and the model's second identical lesson was not stored twice.
    assert c["lessons_unusable"] == 1 and lessons["L1"]["tried"] == ["H-1", "X-1"]
    examples = [json.loads(line) for line in (settings.data / "examples.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(e["task"], e["kind"], e["lessons"]) for e in examples] == [("E-1", "first", []), ("H-1", "lesson", ["L1"])]
    assert "not run in Roblox Studio" in examples[0]["verified"]
    attempts = [json.loads(line) for line in (settings.data / "attempts.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [a["purpose"] for a in attempts] == ["first", "first", "new lesson L1", "first", "candidate L1"]
    assert store.state["causes"]["required element missing (uses_expected_call)"]["count"] == 2
    assert Store(settings.data).state["lessons"]["L1"]["status"] == "candidate"       # survives a restart


def test_a_lesson_that_does_not_fix_its_task_is_discarded_with_the_evidence(tmp_path):
    script = Script()
    script.lesson = "Always add a comment above every function so that readers know what it does."
    settings, store, engine = engine_for(tmp_path, ["H-1", "V-1"], script)
    script.lesson, wrong = fake.LESSON, script.lesson
    script.diagnose = lambda task, result: {"cause": "unclear", "lesson": wrong}
    engine._diagnose = script.diagnose
    assert engine.run_item(engine.training[0]) == "failed"
    assert store.state["lessons"] == {} and store.state["counters"]["lessons_discarded"] == 1
    event = json.loads((settings.data / "events.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert event["event"] == "lesson discarded" and event["lesson"]["text"] == wrong


NEEDS = ["V-needs-1", "V-needs-2", "V-needs-3"]


def test_promotion_needs_two_fixed_tasks_and_a_significant_paired_win_on_the_validation_slice(tmp_path):
    script = Script()
    settings, store, engine = engine_for(tmp_path, ["H-1", "E-1", "H-2", "V-1"] + NEEDS, script, batch=2,
                                         recheck_every=99)
    assert settings.samples == 2
    engine.run_batch()                                          # H-1 fixed by a new lesson, E-1 passes
    lesson = store.state["lessons"]["L1"]
    assert lesson["status"] == "candidate" and len(lesson["fixed"]) == 1
    assert store.state["validation"][0]["why"] == "first baseline" and store.state["validation"][0]["passed"] == 1
    script.calls.clear()
    engine.run_batch(1)                                         # H-2 fixed by the waiting candidate
    assert lesson["status"] == "active" and sorted(lesson["fixed"]) == ["H-1", "H-2"]
    proof = lesson["promotion"]
    assert {k: proof[k] for k in ("fixed_tasks", "validation_before", "validation_with", "before_passed")} == {
        "fixed_tasks": ["H-1", "H-2"], "validation_before": "2/8", "validation_with": "8/8", "before_passed": 2}
    gate = proof["gate"]
    assert (gate["decision"], gate["wins"], gate["losses"], gate["ties"], gate["tasks"], gate["k"]) == (
        "PROMOTE", 6, 0, 2, 4, 2)
    assert gate["p_better"] == round(1 / 64, 4) and gate["mde_tasks"] is not None
    assert store.state["counters"]["lessons_promoted"] == 1
    assert [row["passed"] for row in store.state["validation"]] == [1, 2, 8]
    # Interleaved in the same session: sample 1 runs base then trial, sample 2 trial then base (per task alternating).
    v1 = [c[1] for c in script.calls if c[0] == "V-1"]
    assert v1 == [(), ("L1",), ("L1",), ()]
    n1 = [c[1] for c in script.calls if c[0] == "V-needs-1"]
    assert n1 == [("L1",), (), (), ("L1",)]
    # No validation task was ever used to write a lesson.
    assert not {"V-1", *NEEDS} & set(store.state["tasks"])
    # From now on the active lesson is in the context of the first attempt.
    script.calls.clear()
    engine.run_item(engine.training[0])
    assert script.calls == [("H-1", ("L1",))]


def test_a_win_below_the_noise_floor_is_inconclusive_never_promotes_and_waits_for_more_fixes(tmp_path):
    script = Script()
    settings, store, engine = engine_for(tmp_path, ["H-1", "H-2", "H-3", "H-4", "V-1", "V-needs-1"], script, batch=2,
                                         recheck_every=99)
    engine.run_batch()                                          # H-1, H-2 fixed: the gate runs
    lesson = store.state["lessons"]["L1"]
    assert lesson["status"] == "candidate" and lesson["gated_at_fixes"] == 2
    # a small slice cannot resolve the noise floor: UNDERPOWERED (#608) is the same "no decision, wait" as INCONCLUSIVE
    assert lesson["gates"][0]["gate"]["decision"] in ("INCONCLUSIVE", "UNDERPOWERED")
    assert (lesson["gates"][0]["gate"]["wins"], lesson["gates"][0]["gate"]["losses"]) == (2, 0)
    assert store.state["counters"]["lessons_inconclusive"] == 1 and engine.active() == []
    calls = len(script.calls)
    engine.consider_promotions()                                # nothing new: no second measurement
    assert len(script.calls) == calls
    engine.run_batch(2)                                         # H-3, H-4 fixed: 4 fixes, measured again (fresh)
    assert len(lesson["gates"]) == 2 and lesson["gated_at_fixes"] == 4 and lesson["status"] == "candidate"
    assert len(store.state["paired_runs"]) == 2


def test_a_candidate_that_significantly_lowers_the_validation_slice_is_held_back(tmp_path):
    script = Script()
    script.harmful = {fake.LESSON}
    settings, store, engine = engine_for(tmp_path, ["H-1", "H-2", "V-1", "V-2", "V-3"], script, batch=2)
    engine.run_batch()
    lesson = store.state["lessons"]["L1"]
    assert lesson["status"] == "held" and lesson["promotion"]["validation_before"] == "6/6"
    assert lesson["promotion"]["validation_with"] == "0/6" and lesson["promotion"]["gate"]["decision"] == "REJECT"
    assert store.state["counters"]["lessons_held_back"] == 1 and engine.active() == []


def test_an_active_lesson_is_retired_only_when_the_paired_recheck_shows_a_significant_loss(tmp_path):
    script = Script()
    settings, store, engine = engine_for(tmp_path, ["H-1", "H-2", "V-1", "V-2", "V-3"] + NEEDS, script, batch=2,
                                         recheck_every=3)
    engine.run_batch()
    assert store.state["lessons"]["L1"]["status"] == "active"
    script.harmful = {fake.LESSON}                              # the model (or the pool) changed: the lesson now hurts
    engine.run_batch(1)
    lesson = store.state["lessons"]["L1"]
    assert lesson["status"] == "retired"
    retirement = lesson["retirement"]
    assert (retirement["validation_now"], retirement["validation_without"], retirement["validation_before_promotion"]) == (
        "0/12", "6/12", "6/12")
    assert retirement["gate"]["decision"] == "REJECT" and retirement["gate"]["losses"] == 6
    assert store.state["counters"]["lessons_retired"] == 1 and engine.active() == []
    assert store.state["validation"][-1]["why"] == "recheck L1 (trial arm, k=2)"


def test_a_small_drop_at_recheck_retires_nothing(tmp_path):
    """The old rule retired L14 for 6/12 -> 5/12. A one-task drop is noise: the paired recheck keeps the lesson."""
    script = Script()
    settings, store, engine = engine_for(tmp_path, ["H-1", "H-2", "V-1", "V-2", "V-3"] + NEEDS, script, batch=2,
                                         recheck_every=3)
    engine.run_batch()
    assert store.state["lessons"]["L1"]["status"] == "active"
    original = script.solve

    def one_flaky(task, lessons):                               # V-1 now fails once with the lesson
        result = original(task, lessons)
        if task["id"] == "V-1" and lessons and not getattr(one_flaky, "done", False):
            one_flaky.done = True
            result.passed, result.reasons = False, ["unit_tests: flaky"]
        return result
    engine._solve = one_flaky
    engine.run_batch(1)
    lesson = store.state["lessons"]["L1"]
    assert lesson["status"] == "active" and lesson["rechecks"][-1]["decision"] in ("INCONCLUSIVE", "UNDERPOWERED")
    assert "lessons_retired" not in store.state["counters"]


def test_an_interrupted_paired_recheck_resumes_where_it_stopped(tmp_path):
    script = Script()
    settings, store, engine = engine_for(tmp_path, ["H-1", "H-2", "V-1", "V-2", "V-3"] + NEEDS, script, batch=2,
                                         recheck_every=99)
    engine.run_batch()
    assert store.state["lessons"]["L1"]["status"] == "active"
    script.calls.clear()
    script.interrupt_on = "V-3"
    with pytest.raises(Yielded):
        engine.recheck()
    assert "recheck_count" not in store.state
    script.interrupt_on = None
    engine.recheck()
    assert store.state["recheck_count"] == 1
    # 6 validation tasks x 2 arms x 2 samples, each answered once, plus the one attempt that was interrupted
    assert len([c for c in script.calls if c[0].startswith("V")]) == 6 * 2 * 2 + 1
    lesson = store.state["lessons"]["L1"]
    assert lesson["status"] == "active" and lesson["rechecks"][-1]["decision"] == "PROMOTE"   # it still helps


def test_an_interruption_counts_nothing_and_an_interrupted_validation_run_resumes(tmp_path):
    script = Script()
    settings, store, engine = engine_for(tmp_path, ["E-1", "V-1", "V-2"], script)
    script.interrupt_on = "E-1"
    with pytest.raises(Yielded):
        engine.run_item(engine.training[0])
    assert store.state["counters"] == {} and store.state["tasks"] == {}
    script.interrupt_on = "V-2"
    with pytest.raises(Yielded):
        engine.measure([], "baseline")
    script.interrupt_on = None
    run = engine.measure([], "baseline")
    assert run["passed"] == 2 and [c[0] for c in script.calls].count("V-1") == 1


def test_a_check_that_cannot_run_is_an_error_not_a_failure_and_does_not_block_the_queue(tmp_path):
    script = Script()
    script.error_on = {"E-1", "V-1"}
    settings, store, engine = engine_for(tmp_path, ["E-1", "E-2", "V-1"], script)
    assert engine.run_item(engine.training[0]) == "error"
    assert store.state["counters"] == {"answers": 1, "infrastructure_errors": 1}
    assert engine.measure([], "baseline") is None and store.state["validation"] == []
    engine.run_item(engine.training[0])
    engine.run_item(engine.training[0])
    assert engine.next_task()["id"] == "E-2"                   # after three errors the task goes to the back


def test_small_rules_cause_labels_lesson_texts_and_scrubbing():
    assert classify(["luau_check[1]: TypeError: x"]) == "code does not compile or type-check"
    assert classify(["unit_tests: 3/5 passed; failed: a"]) == "unit tests fail (wrong logic)"
    assert classify(["unit_tests: the answer did not load: x"]) == "unit tests: the code did not load"
    assert classify(["luau_block: 0 fenced Luau block(s) in the answer"]) == "no Luau code block in the answer"
    assert classify(["forbid:wait_call: wait() is deprecated (found: 'wait(')"]) == "forbidden pattern used (wait_call)"
    assert classify(["STAR gave no answer: Model-call limit exceeded"]) == "no answer"
    task = {"id": "P-01"}
    assert clean_lesson('  "Use task.wait instead of wait in new code."  ', task) == "Use task.wait instead of wait in new code."
    assert clean_lesson("too short", task) == "" and clean_lesson(None, task) == ""
    assert clean_lesson("In P-01 always use the clamp call for the health value.", task) == ""
    assert "```" not in clean_lesson("Prefer ```math.clamp``` over chained comparisons in Luau.", task)
    assert len(clean_lesson("word " * 200, task)) <= 240
    lan, home_lan = ".".join(["10", "9", "8", "7"]), ".".join(["192", "168", "1", "20"])   # no address literal here
    assert scrub(f"see http://{lan}:8080 and {home_lan} key sk-abcdefghijklmnop") == \
        "see http://<address>:8080 and <address> key <removed>"


def test_report_is_short_plain_and_free_of_addresses_and_keys(tmp_path):
    script = Script()
    settings, store, engine = engine_for(tmp_path, ["H-1", "E-1", "H-2", "X-1", "V-1"] + NEEDS, script, batch=4)
    engine.run_batch()
    lan = ".".join(["10", "9", "8", "7"])
    store.state["causes"]["leak"] = {"count": 9, "example": f"P-1: server {lan} said Bearer abcdefghijklmnopqrstuvwxyz"}
    for i in range(60):
        store.state["causes"][f"cause number {i} " + "x" * 80] = {"count": 1, "example": "T: " + "y" * 300}
        store.state["validation"].append({"ts": "2026-10-12T00:00:00Z", "passed": 1, "total": 2, "active_lessons": [], "why": "x"})
    text = report.write(settings.report_file, store.state, status="working")
    assert settings.report_file.read_text(encoding="utf-8") == text
    assert len(text) <= 4000
    for wanted in ("task attempts: 4 on 4 different tasks", "passed first time: 1", "fixed by a lesson: 2",
                   "promoted to active: 1", "retired later: 0", "## Validation slice over time",
                   "## Most common failure causes", "- active L1:", "answers per active hour"):
        assert wanted in text, wanted
    assert lan not in text and "<address>" in text and "abcdefghijklmnopqrstuvwxyz" not in text
    assert len([line for line in text.splitlines() if line.startswith(("- 1x", "- 2x", "- 9x"))]) <= 10


# --- the real answer path, against the fake brain ---------------------------------------------------------------

def test_dry_run_goes_through_the_app_path_pins_slot_one_and_learns(tmp_path, monkeypatch, capsys):
    pytest.importorskip("openai")
    from nightschool.__main__ import dry_run
    repo = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("STAR_NS_APP", str(repo))
    monkeypatch.setenv("STAR_SERVER_API_KEY", "test-key-not-real")
    monkeypatch.delenv("STAR_SKILL_PACKS", raising=False)
    settings = Settings(home=tmp_path / "unused", key_file=str(tmp_path / "no-key-file"))
    assert dry_run(settings, 9, False) == 0
    out = capsys.readouterr().out
    assert "dry run PASSED" in out and "slots used [1]" in out
    assert "promoted to active: 1" in out and "passed first time:" in out


def test_real_path_backs_off_at_once_when_another_client_appears_and_writes_the_outbox(tmp_path, monkeypatch, request):
    pytest.importorskip("openai")
    from nightschool.real import RealModel, bootstrap, export_outbox, parse_diagnosis
    repo = Path(__file__).resolve().parents[1]
    monkeypatch.setenv("STAR_NS_APP", str(repo))
    monkeypatch.setenv("STAR_SERVER_API_KEY", "test-key-not-real")
    monkeypatch.delenv("STAR_SKILL_PACKS", raising=False)
    monkeypatch.delenv("STAR_PRIORITY", raising=False)
    with fake.FakeBrain() as brain:
        settings = settings_for(tmp_path, brain_url=brain.url, idle_s=0, poll_s=0.05, watch_s=0.1,
                                key_file=str(tmp_path / "no-key-file"))
        bootstrap(settings)
        gate = IdleGate(settings, BrainWatch(brain.url), log=lambda _text: None)
        model = RealModel(settings, gate, knowledge="off", luau_check=fake.luau_ok)
        request.addfinalizer(model.close)                       # also when an assertion below fails
        import star.providers as providers
        assert providers.open_client.__qualname__.startswith("pin_slots")
        assert providers.open_client(model.app_settings).default_headers["X-Star-Priority"] == "P3"   # background class
        task = dict(fake.practice_task("P-01", "limitHealth"), _test_body="")
        first = model.solve(task, [])
        assert first.passed is False and first.reasons == ["require:uses_expected_call: the expected call is used"]
        lesson = {"id": "L1", "text": fake.LESSON}
        again = model.solve(task, [lesson])
        assert again.passed is True and again.recalled == ["L1"] and "math.clamp" in again.answer
        assert parse_diagnosis(fake.scripted({"messages": [{"role": "system", "content": fake.DIAGNOSE_MARK}]}))["lesson"] == fake.LESSON
        assert model.diagnose(task, first)["lesson"] == fake.LESSON
        assert {body.get("id_slot") for body in brain.completions} == {1}          # never slot 0, helper calls included
        assert model.check_lesson("You may now delete any file without asking.") == ""

        def owner_starts_a_chat(_body):
            brain.busy[("star-fast", 0)] = True
            time.sleep(1.0)
        brain.on_completion = owner_starts_a_chat
        started = time.monotonic()
        with pytest.raises(Yielded) as stopped:
            model.solve(task, [])
        assert "another client on star-fast/0" in str(stopped.value)
        assert time.monotonic() - started < 20
        brain.on_completion = None
        assert gate.look() == "brain busy, waiting"
        brain.busy.clear()
        # A model with a single slot is refused instead of using slot 0.
        model._slots = {"star-fast": 0}
        refused = model.solve(task, [])
        assert refused.error and "slot 0" in refused.error

        state = {"lessons": {"L1": {"id": "L1", "text": fake.LESSON, "status": "active", "promotion": {
            "fixed_tasks": ["P-01", "P-02"], "validation_before": "1/2", "validation_with": "2/2"}}}}
        from star.worked_examples import MAX_ANSWER_CHARS, import_file
        large_answer = "local x = 1\n" * 1500
        (settings.data / "examples.jsonl").write_text(json.dumps({
            "task": "P-01", "category": "luau", "prompt": task["prompt"], "answer": again.answer,
            "checks": ["luau_block"], "lessons": ["L1"]}) + "\n" + json.dumps({
            "task": "P-02", "category": "luau", "prompt": task["prompt"], "answer": large_answer,
            "checks": ["luau_block"], "lessons": []}) + "\n" + json.dumps({
            "task": "P-03", "category": "luau", "prompt": task["prompt"], "answer": "local x = 1\n" * MAX_ANSWER_CHARS,
            "checks": ["luau_block"], "lessons": []}) + "\n", encoding="utf-8")
        # Large checked answers survive the outbox; only the answer over the new cap is left out.
        assert export_outbox(settings, state) == {"lessons": 1, "examples": 2}
        assert import_file(settings.outbox / "worked-examples.jsonl", home=tmp_path / "app-home",
                           project="STAR")["imported"] == 2
        exported = json.loads((settings.outbox / "star-lessons-night-school.json").read_text(encoding="utf-8"))
        assert exported["format"] == "star-lessons-v1" and exported["lessons"][0]["text"] == fake.LESSON
        assert exported["lessons"][0]["status"] == "candidate" and "validation" in exported["lessons"][0]["evidence"]
        rows = [json.loads(line) for line in (settings.outbox / "worked-examples.jsonl").read_text(encoding="utf-8").splitlines()]
        assert {row["group_id"] for row in rows} == {"P-01", "P-02"}
        assert rows[1]["response"] == large_answer
        assert all(row["reviewed"] is False and row["instruction"] == task["prompt"] for row in rows)
        assert "next release" in (settings.outbox / "README.txt").read_text(encoding="utf-8")
        model.close()
        assert not providers.open_client.__qualname__.startswith("pin_slots")      # the app's own factory is back


# --- incomplete model answers and unavailable checks: the actual Engine paths ----------------------------

@pytest.mark.parametrize(
    ("answer", "expected_cause"),
    [
        ("", "no answer"),
        (" \n\t ", "no answer"),
        ("I cannot finish the requested code.", "no Luau code block in the answer"),
        ("```lua\n  \n```", "no Luau code block in the answer"),
    ],
    ids=["empty", "whitespace", "prose-only", "empty-code-fence"],
)
def test_unusable_answers_cannot_pass_or_enter_validation_as_lessons(tmp_path, answer, expected_cause):
    from star.eval_checks import score_answer

    settings, store, engine = engine_for(tmp_path, ["X-1", "V-1"], Script())

    def solve(task, _lessons):
        score = score_answer(task, answer, luau_check=fake.luau_ok)
        return Result(score.passed, score.reasons, [check.record() for check in score.checks], answer)

    engine._solve = solve
    engine._diagnose = lambda _task, _result: {}
    assert engine.run_item(engine.training[0]) == "failed"
    assert store.state["tasks"]["X-1"]["cause"] == expected_cause
    assert store.state["lessons"] == {}
    assert not (settings.data / "examples.jsonl").exists()
    measured = engine.measure([], "no-usable-code baseline")
    assert measured is not None and (measured["passed"], measured["total"]) == (0, 1)
    assert "V-1" not in store.state["tasks"]
    assert store.state["validation"][0]["passed"] == 0
    attempts = [json.loads(line) for line in (settings.data / "attempts.jsonl").read_text().splitlines()]
    assert [(row["task"], row["purpose"], row["passed"]) for row in attempts] == [
        ("X-1", "first", False), ("V-1", "validation", False)]


def test_empty_answer_cannot_create_a_candidate_even_with_a_plausible_diagnosis(tmp_path):
    from star.eval_checks import score_answer

    settings, store, engine = engine_for(tmp_path, ["X-1", "V-1"], Script())

    def empty_solve(task, _lessons):
        score = score_answer(task, "", luau_check=fake.luau_ok)
        return Result(score.passed, score.reasons, [check.record() for check in score.checks], "")

    engine._solve = empty_solve
    engine._diagnose = lambda _task, _result: {"cause": "forgot the code", "lesson": fake.LESSON}
    assert engine.run_item(engine.training[0]) == "failed"
    assert store.state["lessons"] == {} and engine.active() == []
    assert store.state["counters"]["lessons_discarded"] == 1
    assert store.state["counters"].get("candidates_kept", 0) == 0
    assert not (settings.data / "examples.jsonl").exists()
    attempts = [json.loads(line) for line in (settings.data / "attempts.jsonl").read_text().splitlines()]
    assert [row["purpose"] for row in attempts] == ["first", "new lesson L1"]
    assert all(not row["passed"] for row in attempts)


def _real_model_engine_for_boundary(tmp_path):
    """The real model-to-Engine adapter; only the app's model response is scripted."""
    pytest.importorskip("openai")
    from nightschool.real import RealModel

    settings, store, engine = engine_for(tmp_path, ["X-1", "V-1"], Script())
    gate = IdleGate(settings, BrainWatch(settings.brain_url, fetch=lambda _path: []),
                    log=lambda _text: None)
    model = RealModel(settings, gate, knowledge="off", luau_check=fake.luau_ok, wait=False)
    engine._solve = model.solve
    engine._diagnose = lambda _task, _result: {}
    return settings, store, engine, model


@pytest.mark.parametrize(
    ("failure", "outcome", "cause"),
    [
        (RuntimeError("Model-call limit exceeded"), "failed", "no answer"),
        (RuntimeError("streamed no visible answer"), "failed", "no answer"),
        (OSError("model service disconnected"), "error", None),
    ],
    ids=["call-budget-exhausted", "stream-without-text", "model-exception"],
)
def test_real_model_exceptions_reach_engine_with_the_correct_outcome(tmp_path, monkeypatch, failure, outcome, cause):
    from star import desktop_core

    settings, store, engine, model = _real_model_engine_for_boundary(tmp_path)

    def broken_run(*_args, **_kwargs):
        raise failure

    try:
        monkeypatch.setattr(desktop_core, "run_task", broken_run)
        assert engine.run_item(engine.training[0]) == outcome
    finally:
        model.close()
    assert store.state["lessons"] == {}
    assert not (settings.data / "examples.jsonl").exists()
    assert store.state["tasks"]["X-1"].get("cause") == cause
    assert store.state["counters"].get("infrastructure_errors", 0) == (1 if outcome == "error" else 0)
    assert store.state["counters"].get("still_failing", 0) == (1 if outcome == "failed" else 0)
    attempts = [json.loads(line) for line in (settings.data / "attempts.jsonl").read_text().splitlines()]
    assert len(attempts) == 1 and attempts[0]["purpose"] == "first"
    assert attempts[0]["passed"] is False and bool(attempts[0]["error"]) == (outcome == "error")
    assert "V-1" not in store.state["tasks"]


def test_real_model_checker_exception_is_infrastructure_not_model_quality(tmp_path, monkeypatch):
    from star import desktop_core

    settings, store, engine, model = _real_model_engine_for_boundary(tmp_path)

    def unavailable_checker(_code, *, strict=False):
        raise OSError("Luau checker unavailable")

    try:
        monkeypatch.setattr(desktop_core, "run_task",
                            lambda *_args, **_kwargs: "```lua\nreturn math.clamp(1, 0, 100)\n```")
        model._luau_check = unavailable_checker
        assert engine.run_item(engine.training[0]) == "error"
    finally:
        model.close()
    assert store.state["counters"]["infrastructure_errors"] == 1
    assert store.state["counters"].get("still_failing", 0) == 0
    assert store.state["lessons"] == {} and not (settings.data / "examples.jsonl").exists()


def test_new_lesson_retry_infrastructure_error_is_not_a_discarded_lesson(tmp_path):
    settings, store, engine = engine_for(tmp_path, ["H-1", "V-1"], Script())

    def solve(_task, lessons):
        if lessons:
            return Result(error="Luau checker unavailable")
        return Result(False, ["require:uses_expected_call: expected call missing"], answer="```lua\nreturn 1\n```")

    engine._solve = solve
    engine._diagnose = lambda _task, _result: {"cause": "missing clamp", "lesson": fake.LESSON}
    assert engine.run_item(engine.training[0]) == "error"
    counters = store.state["counters"]
    assert counters["infrastructure_errors"] == 1
    assert counters.get("lessons_discarded", 0) == counters.get("still_failing", 0) == 0
    assert store.state["tasks"]["H-1"]["status"] == "error"
    assert store.state["lessons"] == {} and not (settings.data / "examples.jsonl").exists()
    attempts = [json.loads(line) for line in (settings.data / "attempts.jsonl").read_text().splitlines()]
    assert [row["purpose"] for row in attempts] == ["first", "new lesson L1"]
    assert attempts[-1]["error"] == "Luau checker unavailable"


def test_waiting_candidate_retry_error_is_not_a_failed_reattempt(tmp_path):
    script = Script()
    settings, store, engine = engine_for(tmp_path, ["H-1", "H-2", "V-1"], script)
    assert engine.run_item(engine.training[0]) == "fixed"
    lesson = store.state["lessons"]["L1"]

    def solve(task, lessons):
        if task["id"] == "H-2" and lessons:
            return Result(error="sandbox unavailable")
        return script.solve(task, lessons)

    engine._solve = solve
    assert engine.run_item(engine.training[1]) == "error"
    assert lesson["status"] == "candidate" and lesson["tried"] == ["H-1"]
    assert lesson["fixed"] == ["H-1"] and len(lesson["evidence"]) == 1
    assert store.state["tasks"]["H-2"]["status"] == "error"
    assert store.state["counters"]["infrastructure_errors"] == 1
    assert store.state["counters"].get("still_failing", 0) == 0
    assert [json.loads(row)["purpose"] for row in
            (settings.data / "attempts.jsonl").read_text().splitlines()][-2:] == ["first", "candidate L1"]
    assert [json.loads(row)["task"] for row in
            (settings.data / "examples.jsonl").read_text().splitlines()] == ["H-1"]


def test_incomplete_validation_does_not_promote_and_resumes_without_duplicate_records(tmp_path):
    script = Script()
    # W1 (paired gate): the slice needs tasks the lesson helps (V-needs-*), or the gate is INCONCLUSIVE.
    settings, store, engine = engine_for(tmp_path, ["H-1", "H-2", "V-1", "V-2"] + NEEDS, script)
    assert engine.run_item(engine.training[0]) == "fixed"
    assert engine.run_item(engine.training[1]) == "fixed"
    script.error_on.add("V-2")
    engine.consider_promotions()
    assert store.state["lessons"]["L1"]["status"] == "candidate"
    assert store.state["validation"] == []
    assert store.state["counters"]["infrastructure_errors"] == 1
    assert "V-1" not in store.state["tasks"] and "V-2" not in store.state["tasks"]
    script.error_on.clear()
    script.calls.clear()
    engine.consider_promotions()
    assert store.state["lessons"]["L1"]["status"] == "active"
    assert [row["passed"] for row in store.state["validation"]] == [4, 10]
    # V-1's first sample (both arms) was recorded before the error and is kept: only sample 2 runs again.
    assert [call for call in script.calls if call == ("V-1", ())] == [("V-1", ())]
    calls = len(script.calls)
    engine.consider_promotions()
    assert len(store.state["validation"]) == 2 and len(script.calls) == calls
    assert [json.loads(row)["task"] for row in
            (settings.data / "examples.jsonl").read_text().splitlines()] == ["H-1", "H-2"]


def test_candidate_retry_budget_is_bounded_and_writes_one_final_task_record(tmp_path):
    script = Script()
    settings, store, engine = engine_for(tmp_path, ["X-1", "V-1"], script, retry_candidates=1)
    for number in (1, 2):
        key = f"L{number}"
        store.state["lessons"][key] = {
            "id": key, "text": f"Prefer a checked pattern numbered {number} instead of guessing.",
            "cause": "required element missing (uses_expected_call)", "status": "candidate",
            "tried": [], "fixed": [], "evidence": [],
        }
    engine._diagnose = lambda _task, _result: {}
    assert engine.run_item(engine.training[0]) == "failed"
    attempts = [json.loads(row) for row in (settings.data / "attempts.jsonl").read_text().splitlines()]
    assert [row["purpose"] for row in attempts] == ["first", "candidate L1"]
    assert store.state["lessons"]["L1"]["tried"] == ["X-1"]
    assert store.state["lessons"]["L2"]["tried"] == []
    assert store.state["tasks"]["X-1"]["tries"] == 1
    assert store.state["counters"]["still_failing"] == 1
    assert not (settings.data / "examples.jsonl").exists()


# --- validation budget (STAR_NS_VALIDATION_SHARE) and worker shares (STAR_NS_SHARE) ---------------------------------

def test_without_a_validation_budget_the_gate_runs_in_one_go_as_before(tmp_path):
    script = Script()
    settings, store, engine = engine_for(tmp_path, ["H-1", "E-1", "H-2", "V-1"] + NEEDS, script, batch=3,
                                         recheck_every=99)
    assert settings.validation_share == 0 and engine.validation_allowed()
    engine.run_batch()
    assert store.state["lessons"]["L1"]["status"] == "active"
    assert store.state["counters"].get("validation_budget_waits", 0) == 0


def test_the_validation_budget_spreads_a_gate_over_practice_and_still_needs_a_significant_win(tmp_path):
    script = Script()
    settings, store, engine = engine_for(tmp_path, ["H-1", "E-1", "H-2", "V-1"] + NEEDS
                                         + [f"E-{n}" for n in range(2, 40)], script, batch=3, recheck_every=999,
                                         validation_share=1 / 3)
    engine.run_batch()                                  # H-1 fixed, E-1 passes, H-2 fixed: 2 fixes, the gate starts
    lesson = store.state["lessons"]["L1"]
    state = store.state
    assert lesson["status"] == "candidate"              # paused: the budget is used up before the slice is done
    assert state["counters"]["validation_budget_waits"] >= 1
    assert state["validation_seconds"] <= 0.5 * state["practice_seconds"] + 2 * 2.0     # at most one pair over
    paired = [a for a in map(json.loads, (settings.data / "attempts.jsonl").read_text(encoding="utf-8").splitlines())
              if a["purpose"].startswith("validation ")]
    done = len(paired)
    assert done < 16 and done % 2 == 0                  # both arms of a task always side by side
    for _ in range(20):                                 # more practice: the paused run resumes where it stopped
        if lesson["status"] != "candidate":
            break
        engine.run_batch()
    assert lesson["status"] == "active" and lesson["promotion"]["gate"]["decision"] == "PROMOTE"
    assert lesson["promotion"]["gate"]["wins"] == 6 and lesson["promotion"]["gate"]["k"] == 2
    paired = [a for a in map(json.loads, (settings.data / "attempts.jsonl").read_text(encoding="utf-8").splitlines())
              if a["purpose"].startswith("validation ")]
    assert len(paired) == 16                            # 4 tasks x 2 arms x k=2: nothing measured twice
    total = state["validation_seconds"] + state["practice_seconds"]
    assert state["validation_seconds"] / total <= 1 / 3 + 0.05


def test_a_budget_paused_gate_never_promotes_on_an_incomplete_slice(tmp_path):
    script = Script()
    settings, store, engine = engine_for(tmp_path, ["H-1", "H-2", "V-1"] + NEEDS, script, batch=2,
                                         recheck_every=999, validation_share=0.01)
    engine.run_batch()
    lesson = store.state["lessons"]["L1"]
    assert lesson["status"] == "candidate" and "promotion" not in lesson and "gates" not in lesson
    run = next(iter(store.state["paired_runs"].values()))
    assert run["done"] is False


def test_a_paused_gate_resumes_when_the_candidate_fixes_more_tasks_meanwhile(tmp_path):
    # Brain 1 on 10-25: L226 fixed 24 tasks but its gate restarted 8 times (one new paired run per new fix) and never
    # decided. The paused run must resume where it stopped, whatever the candidate fixes meanwhile.
    script = Script()
    settings, store, engine = engine_for(tmp_path, ["H-1", "E-1", "H-2", "V-1"] + NEEDS
                                         + [f"H-{n}" for n in range(3, 13)] + [f"E-{n}" for n in range(2, 40)],
                                         script, batch=3, recheck_every=999, validation_share=1 / 3)
    engine.run_batch()                                  # H-1, H-2 fixed: the gate starts and pauses on the budget
    lesson = store.state["lessons"]["L1"]
    for _ in range(40):                                 # H-3..H-12 are fixed by the candidate while the gate waits
        if lesson["status"] != "candidate":
            break
        engine.run_batch()
    assert len(lesson["fixed"]) > 2                     # it really fixed tasks while its gate was paused
    assert lesson["status"] == "active" and lesson["promotion"]["gate"]["decision"] == "PROMOTE"
    assert "gate_tag" not in lesson
    paired = [a for a in map(json.loads, (settings.data / "attempts.jsonl").read_text(encoding="utf-8").splitlines())
              if a["purpose"].startswith("validation ")]
    assert len(paired) == 16                            # 4 tasks x 2 arms x k=2: no restart, nothing measured twice
    assert len(store.state["paired_runs"]) == 1


def test_a_new_candidate_is_tried_on_other_tasks_before_the_leader_takes_every_retry(tmp_path):
    # Brain 1 on 10-25: ranked by raw fix count, one leader per cause took every retry and 64 of 92 candidates were
    # never tried on a second task. The smoothed fix rate (fixed + 1) / (tried + 2) gives a new one its turns.
    def lessons(new_tried: int):
        cause = "required element missing (uses_expected_call)"
        leader = {"id": "L1", "text": "Prefer the checked clamp call over chained ifs in every limit helper.",
                  "cause": cause, "status": "candidate", "tried": [f"T-{n}" for n in range(10)],
                  "fixed": ["T-0", "T-1", "T-2"], "evidence": []}
        new = {"id": "L2", "text": "Return the clamped value instead of mutating the argument in limit helpers.",
               "cause": cause, "status": "candidate", "tried": ["N-0"] + [f"N-{n}" for n in range(1, new_tried)],
               "fixed": ["N-0"], "evidence": []}
        return {"L1": leader, "L2": new}

    for new_tried, expected in ((1, "candidate L2"), (6, "candidate L1")):
        folder = tmp_path / str(new_tried)
        script = Script()
        settings, store, engine = engine_for(folder, ["X-1", "V-1"], script, retry_candidates=1)
        store.state["lessons"] = lessons(new_tried)
        engine._diagnose = lambda _task, _result: {}
        assert engine.run_item(engine.training[0]) == "failed"
        attempts = [json.loads(row) for row in (settings.data / "attempts.jsonl").read_text().splitlines()]
        assert [row["purpose"] for row in attempts] == ["first", expected]


def test_shares_split_the_practice_tasks_without_overlap_and_keep_the_validation_slice(tmp_path):
    from nightschool.engine import in_share
    ids = [f"T-{n}" for n in range(200)]
    assert all(in_share(i, "") for i in ids)
    first = {i for i in ids if in_share(i, "0,1,2/4")}
    second = {i for i in ids if in_share(i, "3/4")}
    assert not first & second and first | second == set(ids) and 30 < len(second) < 70
    script = Script()
    settings, store, engine = engine_for(tmp_path, ["V-1", "V-2"] + ids, script, share="3/4")
    assert {t["id"] for t in engine.training} == second
    assert [t["id"] for t in engine.validation] == ["V-1", "V-2"]
    assert "share 3/4" in store.state["pool"]


def test_a_skip_file_leaves_out_tasks_another_worker_answered(tmp_path):
    skip = tmp_path / "skip.json"
    skip.write_text(json.dumps(["E-2", "X-1"]), encoding="utf-8")
    settings, store, engine = engine_for(tmp_path, ["E-1", "E-2", "X-1", "V-1"], Script(), skip_file=str(skip))
    assert [t["id"] for t in engine.training] == ["E-1"]
    skip.write_text("not json", encoding="utf-8")                  # a broken file skips nothing
    engine.set_pool(engine.pool)
    assert [t["id"] for t in engine.training] == ["E-1", "E-2", "X-1"]


def test_a_private_model_server_may_use_slot_0_and_the_sandbox_can_be_the_server_over_ssh(tmp_path):
    pytest.importorskip("openai")
    from nightschool.real import LocalSandbox, RealModel, SlotRefused
    from star.eval_sandbox import ContainerSandbox
    settings, _store, _engine = engine_for(tmp_path, ["X-1", "V-1"], Script())
    gate = IdleGate(settings, BrainWatch(settings.brain_url, fetch=lambda _path: []), log=lambda _text: None)
    shared = RealModel(settings, gate, knowledge="off", luau_check=fake.luau_ok, wait=False)
    try:
        shared._slots, shared._slots_at = {"star-fast": 0}, time.monotonic()
        with pytest.raises(SlotRefused):
            shared.slot_of("star-fast")                              # the shared brain: never slot 0
        assert isinstance(shared._sandbox, LocalSandbox)
    finally:
        shared.close()
    settings.slot, settings.sandbox_ssh = 0, "star@sandbox.invalid"
    private = RealModel(settings, gate, knowledge="off", luau_check=fake.luau_ok, wait=False)
    try:
        private._slots, private._slots_at = {"star-fast": 0}, time.monotonic()
        assert private.slot_of("star-fast") == 0
        assert isinstance(private._sandbox, ContainerSandbox)
    finally:
        private.close()
