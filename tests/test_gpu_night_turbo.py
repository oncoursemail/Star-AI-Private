"""GPU night turbo (server/night_school/pc/turbo.py): when a session starts and stops, what night school is given,
and the merged outbox. Everything here is a fake: no model, no GPU, no SSH, no scheduled task."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server" / "night_school" / "pc"))

import turbo  # noqa: E402

MIN = 60.0


class Probe:
    def __init__(self):
        self.idle, self.full, self.gpu = 30 * MIN, False, {}
        self.procs = {4: "System", 100: "dwm.exe", 200: "brave.exe"}
        self.gpu_looks = 0

    def idle_seconds(self):
        return self.idle

    def fullscreen(self):
        return self.full

    def processes(self):
        return dict(self.procs)

    def gpu_users(self):
        self.gpu_looks += 1
        return dict(self.gpu)


class Proc:
    def __init__(self, pid):
        self.pid, self.returncode = pid, None

    def poll(self):
        return self.returncode


class Helper:
    """The GPU switch's launcher, as far as the supervisor uses it."""

    def __init__(self):
        self.state, self.process, self.configured, self.leased = "off", None, None, 0

    def configure(self, settings, home, *, start=False):
        self.configured, self.state, self.process = (settings, home, start), "starting", Proc(900)

    def status(self):
        return {"state": self.state, "text": self.state}

    def lease(self):
        self.leased += 1
        return "http://127.0.0.1:5555/v1" if self.state == "ready" else None

    def shutdown(self):
        self.state, self.process = "off", None


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        self.now += 0.5                       # every look moves time on, so the polite-stop wait ends
        return self.now


@pytest.fixture
def rig(tmp_path, monkeypatch):
    killed = []
    monkeypatch.setattr(turbo, "kill_tree", lambda proc: (killed.append(proc.pid), setattr(proc, "returncode", 1)))
    monkeypatch.setattr(turbo.time, "sleep", lambda _s: None)
    (tmp_path / "settings.json").write_text('{"use_my_gpu": true}', encoding="utf-8")   # the app's switch, on
    config = dict(turbo.DEFAULTS, app=str(tmp_path / "app"), app_settings=str(tmp_path / "settings.json"), python="py.exe", llama_server="ls.exe", model="m.gguf",
                  knowledge_url="http://knowledge.invalid:8091", server_ssh="star@host.invalid")
    spawned, synced, merged = [], [], []

    def popen(argv, **kwargs):
        spawned.append((argv, kwargs))
        return Proc(700)

    def sync():
        synced.append(1)
        (tmp_path / "home" / "ns" / "pool").mkdir(parents=True, exist_ok=True)
        return "pool copied"
    hour, lock = {"now": 14}, {"held": False}
    (tmp_path / "home").mkdir()
    t = turbo.Turbo(tmp_path / "home", config, probe=Probe(), helper=Helper(), popen=popen, sync=sync,
                    merge=lambda: merged.append(1) or "merged", server_lock=lambda: lock["held"], clock=Clock(),
                    hour=lambda: hour["now"])
    t.spawned, t.synced, t.merged, t.killed, t.hour, t.lock = spawned, synced, merged, killed, hour, lock
    return t


def test_day_needs_20_idle_minutes_and_night_5(rig):
    rig.probe.idle = 19 * MIN
    assert "owner is active" in rig.start_blocker()
    rig.probe.idle = 21 * MIN
    assert rig.start_blocker() == ""
    rig.hour["now"] = 3
    rig.probe.idle = 6 * MIN
    assert rig.start_blocker() == ""
    rig.probe.idle = 4 * MIN
    assert "night" in rig.start_blocker()
    rig.hour["now"] = 8                       # 08:00 is day again
    rig.probe.idle = 6 * MIN
    assert "owner is active" in rig.start_blocker()


def test_off_file_games_the_gpu_switch_and_other_gpu_users_block_a_start(rig):
    (rig.home / "OFF").write_text("off")
    assert "OFF" in rig.start_blocker()
    (rig.home / "OFF").unlink()
    rig.probe.full = True
    assert "full-screen" in rig.start_blocker()
    rig.probe.full, rig.next_look = False, -1e18
    rig.probe.procs[300] = "llama-server.exe"         # the STAR app's "Use my GPU" (or anything else) on the card
    assert "another llama-server" in rig.start_blocker()
    del rig.probe.procs[300]
    rig.next_look = -1e18
    rig.config["block_processes"] = ["RobloxPlayerBeta.exe"]
    rig.probe.procs[301] = "RobloxPlayerBeta.exe"
    assert "RobloxPlayerBeta.exe is running" == rig.start_blocker()
    del rig.probe.procs[301]
    rig.next_look = -1e18
    rig.probe.gpu = {200: 40.0, 100: 90.0}            # a browser game at 40 %; dwm (the desktop) is ignored
    assert rig.start_blocker() == "checking the graphics card again"
    assert rig.start_blocker() == "brave.exe is using the graphics card (40%)"
    looks = rig.probe.gpu_looks
    assert rig.start_blocker() == "brave.exe is using the graphics card (40%)"    # not looked at again for a minute
    assert rig.probe.gpu_looks == looks
    rig.probe.gpu, rig.next_look = {200: 3.0}, -1e18
    assert rig.start_blocker() == ""


def test_the_apps_use_my_pc_switch_gates_every_session(rig):
    settings = rig.home.parent / "settings.json"
    for text in ('{"use_my_gpu": false}', "{}", '{"use_my_gpu": "yes"}', "not json", None):
        if text is None:
            settings.unlink()                                      # no settings file: off, never "on by default"
        else:
            settings.write_text(text, encoding="utf-8")
        assert "Use my PC switch is off" in rig.start_blocker()
        rig.tick()
        assert rig.state == "waiting" and rig.helper.configured is None and not rig.spawned
    settings.write_text('{"use_my_gpu": true}', encoding="utf-8")
    assert rig.start_blocker() == ""
    rig.tick()
    assert rig.state == "loading"
    assert settings.read_text(encoding="utf-8") == '{"use_my_gpu": true}'      # read only


def test_automatic_night_use_runs_in_the_night_window_with_the_switch_off(rig):
    settings = rig.home.parent / "settings.json"
    rig.hour["now"] = 3
    rig.probe.idle = 6 * MIN
    settings.write_text('{"use_my_gpu": false}', encoding="utf-8")            # auto night is on by default
    assert rig.start_blocker() == ""
    settings.write_text('{"use_my_gpu": false, "use_my_pc_auto_night": false}', encoding="utf-8")
    assert "Use my PC switch is off" in rig.start_blocker()                   # auto off: does not run
    settings.write_text("not json", encoding="utf-8")
    assert "could not be read" in rig.start_blocker()                         # unreadable: fails closed at night too
    settings.write_text('{"use_my_gpu": false}', encoding="utf-8")
    rig.hour["now"] = 14                                                      # day: follows the switch
    rig.probe.idle = 30 * MIN
    assert "Use my PC switch is off" in rig.start_blocker()
    rig.hour["now"] = 3
    rig.tick()
    assert rig.state == "loading"
    rig.helper.state = "ready"
    rig.tick()
    assert rig.state == "running"
    rig.hour["now"] = 8                                                       # night_end: back to the switch (off)
    rig.tick()
    assert rig.state == "waiting" and "Use my PC switch was turned off" in rig.reason


def test_a_session_runs_night_school_on_the_switch_launcher_and_stops_when_the_owner_returns(rig):
    rig.tick()
    assert rig.state == "loading" and rig.synced == [1]
    settings, home, start = rig.helper.configured
    assert (settings.use_my_gpu, settings.gpu_helper_server, settings.gpu_helper_model, start) == (True, "ls.exe", "m.gguf", True)
    rig.tick()
    assert rig.state == "loading" and rig.spawned == []           # the model is still loading
    rig.helper.state = "ready"
    rig.tick()
    assert rig.state == "running" and rig.helper.leased == 1
    argv, kwargs = rig.spawned[0]
    assert argv == ["py.exe", "-m", "nightschool", "run"]
    assert kwargs["cwd"].endswith(str(Path("app") / "server" / "night_school"))
    env = kwargs["env"]
    assert env["STAR_NS_BRAIN_URL"] == "http://127.0.0.1:5555" and env["STAR_NS_SLOT"] == "0"
    assert env["STAR_NS_SHARE"] == "2/4" and env["STAR_NS_SANDBOX_SSH"] == "star@host.invalid"
    assert env["STAR_NS_SKIP_FILE"].endswith("skip.json") and env["STAR_NS_PLANNER_URL"] == "off"
    assert env["STAR_NS_KNOWLEDGE_URL"] == "http://knowledge.invalid:8091" and env["STAR_NS_IDLE_S"] == "0"
    assert str(rig.home) in env["APPDATA"]                         # never the owner's STAR profile
    rig.tick()
    assert rig.state == "running"
    # Two answers were written during the session.
    attempts = rig.ns / "data" / "attempts.jsonl"
    attempts.parent.mkdir(parents=True, exist_ok=True)
    attempts.write_text(json.dumps({"purpose": "first", "passed": True}) + "\n"
                        + json.dumps({"purpose": "first", "passed": False}) + "\n", encoding="utf-8")
    rig.probe.idle = 1.0                                           # the owner moved the mouse
    rig.tick()
    assert rig.state == "waiting" and "owner is back" in rig.reason
    assert (rig.ns / "data" / "HOLD").is_file() and rig.killed == [700]
    assert rig.helper.state == "off" and rig.merged == [1]
    log = (rig.home / "turbo.log").read_text(encoding="utf-8")
    assert "2 answers (2 first tries, 1 passed first" in log
    rig.probe.idle = 30 * MIN                                      # the next session clears HOLD before night school
    rig.tick()
    rig.helper.state = "ready"
    rig.tick()
    assert rig.state == "running" and not (rig.ns / "data" / "HOLD").exists()


@pytest.mark.parametrize("change, words", [
    (lambda r: (r.home / "OFF").write_text("off"), "off switch"),
    (lambda r: (r.home.parent / "settings.json").write_text('{"use_my_gpu": false}'), "Use my PC switch was turned off"),
    (lambda r: setattr(r.probe, "full", True), "full-screen"),
    (lambda r: r.probe.procs.update({301: "llama-server.exe"}), "another llama-server"),
    (lambda r: setattr(r.worker, "returncode", 3), "night school exited (code 3)"),
    (lambda r: setattr(r.helper, "state", "failed"), "model server is failed"),
    (lambda r: r.lock.update(held=True), "quiet lock"),
])
def test_a_running_session_stops_for_each_reason(rig, change, words):
    rig.tick()
    rig.helper.state = "ready"
    rig.tick()
    assert rig.state == "running"
    rig.gpu_at = -1e18                                             # the program look is due
    change(rig)
    rig.tick()
    assert rig.state == "waiting" and words in rig.reason
    assert rig.helper.state == "off"


def test_another_program_busy_on_the_card_stops_a_session_but_our_own_server_does_not(rig):
    rig.tick()
    rig.helper.state = "ready"
    rig.tick()
    rig.probe.gpu = {900: 95.0, 700: 1.0}                          # our llama-server (pid 900) and night school
    for _ in range(3):
        rig.gpu_at = -1e18
        rig.tick()
    assert rig.state == "running"
    rig.probe.gpu[200] = 60.0
    for _ in range(2):
        rig.gpu_at = -1e18
        rig.tick()
    assert rig.state == "waiting" and "brave.exe is using the graphics card" in rig.reason


def test_a_model_that_does_not_start_cools_down(rig):
    rig.tick()
    rig.helper.state = "busy"                                      # the switch's own start rules said no
    rig.tick()
    assert rig.state == "waiting" and "did not start" in rig.reason
    rig.helper.state = "off"
    assert rig.state == "waiting" and rig.merged == []             # nothing ran, nothing to merge


def test_server_state_gives_the_skip_list_and_seeds_the_validation_slice_once(tmp_path):
    ns = tmp_path / "ns"
    state = {"tasks": {"T-2": {}, "T-1": {}}, "validation_ids": ["V-1", "V-2"]}
    assert "2 tasks answered on server 1" in turbo.apply_server_state(ns, state)
    assert json.loads((ns / "skip.json").read_text()) == ["T-1", "T-2"]
    assert json.loads((ns / "data" / "state.json").read_text()) == {"validation_ids": ["V-1", "V-2"]}
    (ns / "data" / "state.json").write_text(json.dumps({"validation_ids": ["V-1", "V-2"], "tasks": {"T-9": {}}}))
    turbo.apply_server_state(ns, {"tasks": {}, "validation_ids": ["V-7"]})
    assert json.loads((ns / "data" / "state.json").read_text())["tasks"] == {"T-9": {}}     # own state kept


def test_gpu_counters_are_summed_per_process_without_video_and_copy():
    text = ("pid_12_luid_0x1_phys_0_eng_0_engtype_3D|10.5\npid_12_luid_0x1_phys_0_eng_1_engtype_Compute_0|5\n"
            "pid_13_luid_0x1_phys_0_eng_3_engtype_VideoDecode|50\npid_14_luid_0x1_phys_0_eng_2_engtype_Copy|30\n"
            "garbage\n")
    assert turbo.parse_gpu_counters(text) == {12: 15.5}


def test_merged_outbox_keeps_both_workers_results_in_the_app_formats(tmp_path):
    from star.learned_week import build_bundle

    from star.lessons import LessonStore

    def outbox(name, lessons, rows):
        folder = tmp_path / name
        (folder / "outbox").mkdir(parents=True)
        (folder / "report").mkdir()
        (folder / "report" / "latest.md").write_text(f"# report {name}\n")
        store = LessonStore(tmp_path / ("lessons-" + name))     # night school's own export path (real.export_outbox)
        try:
            for ident, text in lessons:
                store.capture_inferred(project="night-school", kind="correction", text=text,
                                       source_type="verified-fix", source="night-school:" + ident,
                                       evidence="night school: fixed practice tasks T-1, T-2; paired gate PROMOTE")
            data = store.export("night-school")
        finally:
            store.close()
        (folder / "outbox" / "star-lessons-night-school.json").write_text(json.dumps(data))
        (folder / "outbox" / "worked-examples.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        return folder

    def row(task, text):
        return {"id": "night-school-" + task, "group_id": task, "task_category": "luau", "instruction": "Write " + task,
                "response": "```lua\nreturn " + text + "\n```", "evidence": ["night-school automated checks: luau_block"],
                "source": "night-school-verified", "reviewed": False, "rights_confirmed": False, "lessons_in_context": []}
    server = outbox("server", [("L1", "Always wrap Luau code in a fenced luau block.")], [row("T-1", "1"), row("T-2", "2")])
    pc = outbox("pc", [("L1", "Clamp counts with math.clamp before using them.")], [row("T-2", "22"), row("T-3", "3")])
    done = turbo.merge_outboxes([("server1", server), ("pc-gpu", pc)], tmp_path / "merged")
    assert done == {"lessons": 2, "examples": 3}
    merged = [json.loads(l) for l in (tmp_path / "merged" / "worked-examples.jsonl").read_text().splitlines()]
    assert [r["group_id"] for r in merged] == ["T-1", "T-2", "T-3"] and merged[1]["response"].count("2") == 1
    assert (tmp_path / "merged" / "report-server1.md").is_file() and (tmp_path / "merged" / "report-pc-gpu.md").is_file()
    lessons = json.loads((tmp_path / "merged" / "star-lessons-night-school.json").read_text())
    assert lessons["format"] == "star-lessons-v1" and "server1, pc-gpu" in lessons["note"]
    bundle = build_bundle(tmp_path / "merged")                     # the app's own packaging accepts it
    assert len(bundle["examples"]) == 3
    assert sorted(l["id"] for l in bundle["lessons"]) == ["L1", "pc-gpu:L1"]      # both kept, no id clash


def test_server_1s_quiet_lock_blocks_a_start(rig):
    rig.lock["held"] = True
    assert rig.start_blocker() == "server 1's quiet lock is held"
    rig.lock["held"], rig.next_look = False, -1e18
    assert rig.start_blocker() == ""


def test_pc_conductor_tasks_are_pushed_to_server_1s_pool(tmp_path, monkeypatch):
    pool = tmp_path / "ns" / "pool"
    pool.mkdir(parents=True)
    (pool / "conductor-pc-20261017.json").write_text("[]", encoding="utf-8")
    (pool / "conductor-20261017.json").write_text("[]", encoding="utf-8")      # server 1's own file: never sent back
    (pool / "conductor-pc-x.json").write_text("[]", encoding="utf-8")          # odd name: refused
    calls = []
    monkeypatch.setattr(turbo.subprocess, "run", lambda argv, **kw: calls.append((argv, kw)) or turbo.SimpleNamespace(returncode=0))
    config = dict(turbo.DEFAULTS, server_ssh="star@host.invalid")
    assert turbo.push_conductor_tasks(config, tmp_path / "ns") == 1
    assert "pool/conductor-pc-20261017.json" in calls[0][0][-1] and calls[0][1]["input"] == b"[]"
    assert turbo.push_conductor_tasks(dict(config, server_ssh=""), tmp_path / "ns") == 0
