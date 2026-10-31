"""Eval farm (server/night_school/pc/eval_farm.py): the paired queue, the worker's interleaving and result files (read by
the real gate), the runner wiring to the card's server, and the supervisor's start/yield rules. All fakes: no model,
no GPU, no SSH."""
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server" / "night_school" / "pc"))

import eval_farm  # noqa: E402

from star import eval_checks as ec  # noqa: E402
from star import eval_gate  # noqa: E402
from star import eval_runner as er  # noqa: E402

MIN = 60.0
BASE = "http://127.0.0.1:5555/v1"


def mini_suite(tmp_path, ids=("A-1", "A-2", "A-3")):
    tasks = [{"id": t, "category": "c", "goal": "g", "required_evidence": ["e"], "pass_conditions": ["p"],
              "run_mode": "automated", "prompt": "Write " + t, "auto": {"code": False, "compile": False}} for t in ids]
    tasks.append({"id": "S-1", "category": "c", "goal": "g", "required_evidence": ["e"], "pass_conditions": ["p"],
                  "run_mode": "studio", "prompt": "Build it", "studio_check": "look"})
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(tasks), encoding="utf-8")
    return path


def batch(tmp_path, **kw):
    options = {"baseline": [], "candidate": ["api_hints_enabled=true"], "tasks": [], **kw}
    return eval_farm.make_batch("qab", mini_suite(tmp_path), **options)


# ---- queue ------------------------------------------------------------------------------------------------------------
def test_queue_writes_a_checked_batch_and_refuses_bad_ones(tmp_path):
    spec = batch(tmp_path)
    assert spec["tasks"] == ["A-1", "A-2", "A-3"]                 # every automated task, never the Studio one
    assert spec["arms"] == {"baseline": [], "candidate": ["api_hints_enabled=true"]}
    home = tmp_path / "home"
    eval_farm.add_batch(home, spec)
    assert [s["name"] for s in eval_farm.pending(home)] == ["qab"]
    with pytest.raises(SystemExit, match="already queued"):
        eval_farm.add_batch(home, spec)
    with pytest.raises(SystemExit, match="same settings"):
        batch(tmp_path, candidate=[])
    with pytest.raises(SystemExit, match="not automated"):
        batch(tmp_path, tasks=["A-1", "S-1"])
    with pytest.raises(SystemExit, match="expected NAME=VALUE"):
        batch(tmp_path, candidate=["server_endpoint=http://x"])    # only answer-path switches, as eval_runner --set
    with pytest.raises(SystemExit, match="--k"):
        batch(tmp_path, k=9)


def test_queue_command_prints_the_power_of_the_batch(tmp_path, capsys):
    home = tmp_path / "home"
    code = eval_farm.main(["--home", str(home), "queue", "--name", "qab", "--suite", str(mini_suite(tmp_path)),
                           "--candidate-set", "api_hints_enabled=true", "--tasks", "A-1,A-2"])
    assert code == 0
    out = capsys.readouterr().out
    assert "2 tasks x 1 x 2 arms" in out and "MDE" in out
    assert json.loads((home / "queue" / "qab.json").read_text(encoding="utf-8"))["tasks"] == ["A-1", "A-2"]


# ---- worker -----------------------------------------------------------------------------------------------------------
def fake_build(order, passing):
    """build_arm's shape: (run_info, ask, scorer, secrets) per arm; asks are recorded in order."""
    def build(spec, arm, base, config, suite, log=print):
        def ask(task, cancel=None):
            order.append((arm, task["id"]))
            return er.Asked("answer " + task["id"], [], 2.0)

        def scorer(task, answer):
            score = ec.TaskScore()
            score.checks.append(ec.Check("x", (arm, task["id"]) in passing, ""))
            return score
        info = {"model": "star-fast" + eval_farm.FARM_TAG, "mode": "auto", "fingerprint": "fp-" + arm, "app_commit": "c1"}
        return info, ask, scorer, []
    return build


def test_worker_interleaves_the_arms_and_the_gate_reads_its_files(tmp_path):
    home = tmp_path / "home"
    spec = batch(tmp_path)
    eval_farm.add_batch(home, spec)
    order = []
    wins = {("candidate", "A-1"), ("candidate", "A-2"), ("baseline", "A-3"), ("candidate", "A-3")}
    assert eval_farm.work(home, BASE, {}, build=fake_build(order, wins), log=lambda m: None) == 0
    # back to back per task, first arm alternating, so a night that ends early leaves whole pairs
    assert order == [("baseline", "A-1"), ("candidate", "A-1"), ("candidate", "A-2"), ("baseline", "A-2"),
                     ("baseline", "A-3"), ("candidate", "A-3")]
    assert eval_farm.pending(home) == []                                   # marked done
    assert eval_farm.progress(home, spec)["baseline"]["pass"] == 1
    assert eval_farm.progress(home, spec)["candidate"]["pass"] == 3
    verdict = eval_gate.evaluate_paired(eval_farm.arm_files(home, spec, "baseline"),
                                        eval_farm.arm_files(home, spec, "candidate"))
    assert verdict.code != eval_gate.UNUSABLE, verdict.text()
    assert (verdict.compared, verdict.baseline_pass, verdict.candidate_pass) == (3, 1, 3)


def test_a_stopped_worker_resumes_with_the_task_in_flight_and_keeps_pairs(tmp_path):
    home = tmp_path / "home"
    spec = batch(tmp_path)
    eval_farm.add_batch(home, spec)
    order = []
    build = fake_build(order, set())

    def dies_on_a2(spec, arm, base, config, suite, log=print):
        info, ask, scorer, secrets = build(spec, arm, base, config, suite, log)

        def ask_or_die(task, cancel=None):
            if task["id"] == "A-2" and arm == "baseline":
                raise KeyboardInterrupt                   # the supervisor ended the session mid-answer
            return ask(task, cancel)
        return info, ask_or_die, scorer, secrets
    assert eval_farm.work(home, BASE, {}, build=dies_on_a2, log=lambda m: None) == 2
    assert eval_farm.progress(home, spec)["pairs"] == 1                    # A-1 whole; A-2 half
    order.clear()
    assert eval_farm.work(home, BASE, {}, build=build, log=lambda m: None) == 0
    assert order == [("baseline", "A-2"), ("baseline", "A-3"), ("candidate", "A-3")]   # nothing answered twice
    assert eval_farm.progress(home, spec)["pairs"] == 3


def test_a_farm_arm_never_pairs_with_a_brain_arm(tmp_path):
    home = tmp_path / "home"
    spec = batch(tmp_path)
    eval_farm.add_batch(home, spec)
    eval_farm.work(home, BASE, {}, build=fake_build([], set()), log=lambda m: None)
    brain = tmp_path / "brain.json"
    er.run_suite(er.load_suite(Path(spec["suite"])), out=brain, ask=lambda t, cancel=None: er.Asked("a", [], 1.0),
                 scorer=lambda t, a: ec.TaskScore([ec.Check("x", True, "")]),
                 run_info={"model": "star-fast", "mode": "auto", "fingerprint": "b", "app_commit": "c1"}, log=lambda m: None)
    verdict = eval_gate.evaluate_paired([brain], eval_farm.arm_files(home, spec, "candidate"))
    assert verdict.code == eval_gate.UNUSABLE and "model differs" in verdict.text()


def test_build_arm_points_the_real_runner_at_the_card_and_the_given_knowledge(tmp_path, monkeypatch):
    from star import desktop_core
    calls, seen = [], {}

    def recorder(settings, prompt, **kwargs):
        calls.append(settings.knowledge_endpoint)
        return "answer"
    monkeypatch.setattr(desktop_core, "run_task", recorder)

    def build_real(args, log=print):
        from star.desktop_core import Settings, run_task        # as eval_runner.build_real binds them
        seen.update(server=args.server, pin=args.pin_model, ssh=args.ssh, sandbox=args.sandbox_ssh, sets=args.set)
        os.environ["STAR_BACKGROUND_WORK"] = "1"
        settings = Settings(provider="star_server", server_endpoint=args.server, model=args.model)
        return ({"model": args.model, "mode": args.mode, "fingerprint": "f"},
                lambda task, cancel=None: run_task(settings, task["prompt"]), None, None, ["k"])
    monkeypatch.setattr(er, "build_real", build_real)
    spec = batch(tmp_path)
    config = dict(eval_farm.DEFAULTS, knowledge_url="http://127.0.0.1:8094", sandbox_ssh="star@box.invalid")
    info, ask, _scorer, secrets = eval_farm.build_arm(spec, "candidate", BASE, config, None, log=lambda m: None)
    assert seen == {"server": BASE, "pin": True, "ssh": "", "sandbox": "star@box.invalid",
                    "sets": ["api_hints_enabled=true"]}
    assert desktop_core.run_task is recorder                               # the patch does not outlive the wiring
    ask({"prompt": "p"})
    assert calls == ["http://127.0.0.1:8094"]                               # every task asks the given knowledge
    assert "STAR_BACKGROUND_WORK" not in os.environ                         # the card's single slot is the farm's
    assert info["model"] == "star-fast@pc-gpu" and info["farm"]["arm"] == "candidate"
    assert "star@box.invalid" in secrets


# ---- supervisor -------------------------------------------------------------------------------------------------------
class Probe:
    def __init__(self):
        self.idle, self.procs = 30 * MIN, {4: "System", 100: "dwm.exe"}

    def idle_seconds(self):
        return self.idle

    def fullscreen(self):
        return False

    def processes(self):
        return dict(self.procs)

    def gpu_users(self):
        return {}


class Proc:
    def __init__(self, pid):
        self.pid, self.returncode = pid, None

    def poll(self):
        return self.returncode


class Helper:
    def __init__(self):
        self.state, self.process, self.configured = "off", None, None

    def configure(self, settings, home, *, start=False):
        self.configured, self.state, self.process = settings, "starting", Proc(900)

    def status(self):
        return {"state": self.state, "text": self.state}

    def lease(self):
        return BASE if self.state == "ready" else None

    def shutdown(self):
        self.state, self.process = "off", None


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        self.now += 0.5
        return self.now


@pytest.fixture
def farm(tmp_path, monkeypatch):
    killed, spawned = [], []
    monkeypatch.setattr(eval_farm.turbo, "kill_tree", lambda p: (killed.append(p.pid), setattr(p, "returncode", 1)))
    home = tmp_path / "home"
    home.mkdir()
    config = dict(eval_farm.DEFAULTS, python="py.exe", llama_server="ls.exe", model="m.gguf",
                  knowledge_url="http://127.0.0.1:8094", sandbox_ssh="star@box.invalid",
                  app_settings=str(tmp_path / "missing-settings.json"))   # the app switch cannot be read: not needed
    hour = {"now": 14}

    def popen(argv, **kwargs):
        spawned.append(argv)
        return Proc(700)
    f = eval_farm.Farm(home, config, probe=Probe(), helper=Helper(), popen=popen, server_lock=lambda: False,
                       clock=Clock(), hour=lambda: hour["now"])
    f.killed, f.spawned, f.hour = killed, spawned, hour
    eval_farm.add_batch(home, batch(tmp_path))
    return f


def test_farm_starts_on_pc_guard_idle_and_needs_no_app_switch(farm):
    farm.probe.idle = 4 * MIN
    assert "owner is active" in farm.start_blocker()
    farm.probe.idle = 6 * MIN                                     # pc_guard: idle after 5 minutes
    assert farm.start_blocker() == ""
    farm.hour["now"], farm.probe.idle = 0, 3 * MIN               # 00:00-08:00 is night: 2 minutes
    assert farm.start_blocker() == ""
    (farm.home / "queue" / "qab.done").write_text("{}")
    assert farm.start_blocker() == "nothing queued"


def test_session_loads_star_fast_spawns_the_worker_and_yields_when_the_owner_returns(farm):
    farm.tick()
    assert farm.state == "loading"
    assert (farm.helper.configured.gpu_helper_server, farm.helper.configured.gpu_helper_model) == ("ls.exe", "m.gguf")
    farm.helper.state = "ready"
    farm.tick()
    assert farm.state == "running"
    argv = farm.spawned[-1]
    assert argv[0] == "py.exe" and argv[-3:] == ["work", "--base", BASE]
    farm.probe.idle = 2.0                                         # the owner touched the mouse
    farm.tick()
    assert farm.state == "waiting" and "owner is back" in farm.reason
    assert farm.killed == [700] and farm.helper.state == "off"   # worker and model gone, the card is free
    farm.probe.idle = 6 * MIN
    assert farm.start_blocker() == ""                             # no cool-down: yielding is not a failure


def test_a_failed_worker_cools_down_and_a_finished_one_does_not(farm):
    for code, cools in ((2, True), (0, False)):
        farm.cool_until = -1e18
        farm.tick()
        farm.helper.state = "ready"
        farm.tick()
        farm.worker.returncode = code
        farm.tick()
        assert farm.state == "waiting" and f"exited (code {code})" in farm.reason
        assert (farm.start_blocker() == "cooling down after a failure") is cools


def test_missing_config_never_loads_a_model(farm):
    farm.config["knowledge_url"] = ""
    farm.tick()
    assert farm.state == "waiting" and "lacks knowledge_url" in farm.reason and farm.helper.configured is None
