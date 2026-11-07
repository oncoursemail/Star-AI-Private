"""STAR Home (star/home): executor guards, owner stop, action log, her loop, plug-ins. Fake backends only."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import random
import sys
import types

import pytest

from star import curiosity
from star.home import activities, brain, control
from star.home.host import Executor
from star.home.life import Life
from star.home.loop import cycle


class FakeBackend:
    def __init__(self):
        self.calls = []

    def run(self, argv, timeout):
        self.calls.append(("run", argv))
        return 0, "ok"

    def launch(self, target, args):
        self.calls.append(("launch", target, args))

    def screenshot(self, path):
        self.calls.append(("screenshot", path))
        Path(path).write_bytes(b"\x89PNG fake")

    def click(self, x, y, button, clicks):
        self.calls.append(("click", x, y, button, clicks))

    def move(self, x, y):
        self.calls.append(("move", x, y))

    def type_text(self, text):
        self.calls.append(("type", text))

    def key(self, keys):
        self.calls.append(("key", keys))


@pytest.fixture
def home(tmp_path):
    return tmp_path / "STAR" / "home"


def _log(home):
    return [json.loads(line) for line in (home / control.LOG_NAME).read_text(encoding="utf-8").splitlines()]


def test_action_runs_through_backend_and_is_logged_before_and_after(home):
    backend = FakeBackend()
    result = Executor(home, backend).do("shell", {"command": "Get-Date"})
    assert result.ok and "exit 0" in result.text
    assert backend.calls[0][1][:2] == ["powershell", "-NoProfile"]
    assert [(r["action"], r["phase"]) for r in _log(home)] == [("shell", "start"), ("shell", "done")]


def test_owner_stop_refuses_every_action_and_nothing_runs(home):
    backend = FakeBackend()
    control.stop(home)
    result = Executor(home, backend).do("click", {"x": 1, "y": 2})
    assert not result.ok and "stop" in result.text
    assert backend.calls == []
    assert _log(home)[-1]["phase"] == "refused"
    assert control.resume(home) and Executor(home, backend).do("click", {"x": 1, "y": 2}).ok


def test_her_actions_cannot_touch_the_control_folder(home):
    backend = FakeBackend()
    ex = Executor(home, backend)
    control.stop(home)
    control.resume(home)
    assert not ex.do("write_file", {"path": str(home / "STOP"), "text": ""}).ok
    assert not ex.do("write_file", {"path": str(home / "actions.jsonl"), "text": "x"}).ok
    assert not ex.do("shell", {"command": f"Remove-Item '{home / 'STOP'}'"}).ok
    assert not ex.do("shell", {"command": r"del C:\ProgramData\STAR\home\STOP", "shell": "cmd"}).ok
    assert backend.calls == []


@pytest.mark.parametrize("command", ["ssh owner@pc", "scp a b:", "Enter-PSSession -ComputerName x",
                                     "Invoke-Command -ComputerName pc -ScriptBlock {}", r"net use Z: \\pc\c$",
                                     "mstsc /v:pc"])
def test_remote_control_of_other_machines_is_refused(home, command):
    backend = FakeBackend()
    assert "remote-control" in Executor(home, backend).do("shell", {"command": command}).text
    assert backend.calls == []


def test_ordinary_commands_with_similar_words_still_run(home):
    backend = FakeBackend()
    assert Executor(home, backend).do("shell", {"command": "Get-Service sshd-helper; echo scope"}).ok


def test_dry_run_logs_and_runs_nothing(home, tmp_path):
    backend = FakeBackend()
    ex = Executor(home, backend, dry_run=True)
    target = tmp_path / "art" / "a.txt"
    for action, args in [("shell", {"command": "winget list"}), ("write_file", {"path": str(target), "text": "x"}),
                         ("click", {"x": 5, "y": 5}), ("type_text", {"text": "hi"}), ("screenshot", {})]:
        assert "dry run" in ex.do(action, args).text
    assert backend.calls == [] and not target.exists()
    assert all(r["dry_run"] for r in _log(home) if r["phase"] == "start")


def test_winget_install_validates_the_id(home):
    backend = FakeBackend()
    ex = Executor(home, backend)
    assert ex.do("winget_install", {"package_id": "Blender.Blender"}).ok
    assert backend.calls[0][1][:4] == ["winget", "install", "--id", "Blender.Blender"]
    assert not ex.do("winget_install", {"package_id": "x; rm -rf /"}).ok


def test_ask_owner_records_and_does_not_act(home):
    backend = FakeBackend()
    Executor(home, backend).do("ask_owner", {"action": "buy a drawing tablet", "reason": "drawing"})
    row = json.loads((home / "approvals.jsonl").read_text(encoding="utf-8"))
    assert row["status"] == "waiting" and backend.calls == []


def test_life_seeds_and_her_weights_are_clamped(home):
    life = Life(home)
    assert {"game_making", "drawing", "music", "research", "practice"} <= set(life.interests())
    assert life.goals()
    assert life.set_interest("drawing", 99)["weight"] == 5.0
    assert life.set_interest("Pixel Art", 0)["weight"] == 0.1
    assert "pixel_art" in life.interests()


def test_pick_only_from_interests_with_an_activity(home):
    life = Life(home, rng=random.Random(1))
    assert {life.pick({"music"}) for _ in range(20)} == {"music"}
    assert life.pick(set()) is None


def test_variety_lowers_an_interest_done_recently(home):
    life = Life(home)
    before = life.scores({"music", "research"})
    life.record("music", "music", {"ok": True, "verified": True})
    after = life.scores({"music", "research"})
    assert after["music"] < before["music"] * 0.5 * 1.1 + 1e-9
    assert after["research"] == before["research"]


def test_budget_bounds_sessions_and_pauses(home):
    now = [datetime(2026, 10, 26, 12, tzinfo=timezone.utc)]
    life = Life(home, clock=lambda: now[0])
    config = {"sessions_per_day": 2, "pause_minutes": 30}
    assert life.budget_ok(config)[0]
    life.record("music", "music", {})
    assert not life.budget_ok(config)[0]
    now[0] += timedelta(minutes=31)
    assert life.budget_ok(config)[0]
    life.record("music", "music", {})
    now[0] += timedelta(minutes=31)
    assert "sessions" in life.budget_ok(config)[1]


def _scripted(*replies):
    queue = list(replies)

    def chat(messages, tools):
        assert {t["function"]["name"] for t in tools} >= {"shell", "finish", "set_interest"}
        return queue.pop(0)
    return chat


def _call(tool, **args):
    return {"tool_calls": [{"id": f"c-{tool}", "function": {"name": tool, "arguments": json.dumps(args)}}]}


def test_session_is_verified_only_when_the_claimed_files_exist(home, tmp_path):
    backend = FakeBackend()
    ex = Executor(home, backend)
    art = tmp_path / "gallery" / "cat.svg"
    good = brain.run_session(_scripted(_call("write_file", path=str(art), text="<svg/>"),
                                       _call("finish", summary="drew a cat", success=True, artifacts=[str(art)])),
                             ex, Life(home), interest="drawing", brief="draw", goal=None)
    assert good["ok"] and good["verified"] and good["evidence"] == [str(art)]
    bad = brain.run_session(_scripted(_call("write_file", path=str(art), text="<svg/>"),
                                      _call("finish", summary="made a song", success=True,
                                            artifacts=[str(tmp_path / "missing.wav")])),
                            ex, Life(home), interest="music", brief="music", goal=None)
    assert bad["ok"] and not bad["verified"]


def test_session_stops_at_the_step_bound(home):
    chat = _scripted(*[_call("shell", command="echo hi") for _ in range(10)])
    out = brain.run_session(chat, Executor(home, FakeBackend()), Life(home), interest="research", brief="r",
                            goal=None, max_steps=3)
    assert out["steps"] == 3 and not out["ok"] and not out["verified"]


def test_she_changes_her_own_weights_in_a_session(home):
    life = Life(home)
    brain.run_session(_scripted(_call("set_interest", name="music", weight=4.0),
                                _call("finish", summary="decided", success=False)),
                      Executor(home, FakeBackend()), life, interest="music", brief="m", goal=None)
    assert life.interests()["music"]["weight"] == 4.0


def test_cycle_records_history_and_feeds_failures_to_curiosity(home, monkeypatch):
    monkeypatch.setenv("STAR_CURIOSITY", "on")
    registry = activities.Registry()
    registry.register("music", "music", lambda ctx: {"ok": True, "verified": False, "summary": "no audio file",
                                                     "failures": ["shell: exit 1"]})
    life = Life(home, rng=random.Random(0))
    weight = life.interests()["music"]["weight"]
    out = cycle(home, {"sessions_per_day": 5, "pause_minutes": 0}, registry, life, Executor(home, FakeBackend()),
                None)
    assert out["state"] == "worked" and out["interest"] == "music" and not out["verified"]
    assert life.history()[-1]["claimed"] and not life.history()[-1]["verified"]
    assert life.interests()["music"]["weight"] < weight
    kinds = {i.kind for i in curiosity.load(home / "curiosity.jsonl").values()}
    assert kinds == {"failed_verification", "tool_failure"}


def test_practice_resolves_the_curiosity_item_it_studied(home, monkeypatch):
    monkeypatch.setenv("STAR_CURIOSITY", "on")
    queue = home / "curiosity.jsonl"
    home.mkdir(parents=True)
    curiosity.record("failed_verification", "luau tween easing rung", "x", path=queue)
    seen = {}

    def practise(ctx):
        seen["topic"] = ctx.practice_topic
        return {"ok": True, "verified": True, "summary": "ok"}
    registry = activities.Registry()
    registry.register("practice", "practice", practise)
    cycle(home, {"pause_minutes": 0}, registry, Life(home), Executor(home, FakeBackend()), None)
    assert seen["topic"] == "luau tween easing rung"
    assert curiosity.ranked(5, paths=(queue,)) == []


def test_cycle_does_nothing_while_stopped(home):
    control.stop(home)
    registry = activities.Registry()
    registry.register("music", "music", lambda ctx: pytest.fail("ran while stopped"))
    assert cycle(home, {}, registry, Life(home), Executor(home, FakeBackend()), None) == {"state": "stopped"}


def test_plugins_add_activities_and_a_broken_one_is_contained(monkeypatch):
    good = types.ModuleType("fake_games")
    good.register_home_activities = lambda reg: reg.register("play roblox", "play_games",
                                                             lambda ctx: {"ok": True}, "play")
    bad = types.ModuleType("fake_social")

    def broken(reg):
        raise RuntimeError("no token")
    bad.register_home_activities = broken
    monkeypatch.setitem(sys.modules, "fake_games", good)
    monkeypatch.setitem(sys.modules, "fake_social", bad)
    registry = activities.default_registry(("fake_games", "fake_social", "not_installed_module_xyz"))
    assert "play_games" in registry.interests() and "play roblox" in registry.items
    assert "fake_social" in registry.plugin_errors
    assert {"game_making", "drawing", "music", "research", "practice"} <= registry.interests()


def test_http_chat_sends_the_key_only_in_the_header(tmp_path, home):
    key_file = tmp_path / "server_api_key"
    key_file.write_text("sekrit-value-123\n", encoding="utf-8")
    sent = {}

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def opener(request, timeout):
        sent["url"], sent["auth"], sent["body"] = request.full_url, request.get_header("Authorization"), request.data
        return Response(json.dumps({"choices": [{"message": {"content": "ready"}}]}).encode())

    chat = brain.http_chat({"brain_url": "http://brain.test:8080", "key_file": str(key_file), "model": "star-fast"},
                           opener=opener)
    assert chat([{"role": "user", "content": "hi"}], [])["content"] == "ready"
    assert sent["url"] == "http://brain.test:8080/v1/chat/completions"
    assert sent["auth"] == "Bearer sekrit-value-123"
    assert b"sekrit" not in sent["body"] and b'"tools"' not in sent["body"]


class FakeGpu:
    def __init__(self, free, game=""):
        self.free, self.game = free, game

    def free_mb(self):
        return self.free

    def game_running(self, names):
        return self.game


def _gpu_registry():
    registry = activities.Registry()
    registry.register("research", "research", lambda ctx: {"ok": True, "verified": True, "summary": "notes"})
    registry.register("local voice music", "music", lambda ctx: {"ok": True, "verified": True, "summary": "song"},
                      gpu_mb=4000)
    return registry


def test_game_mode_keeps_video_memory_for_her_game():
    registry = _gpu_registry()
    config = {"game_reserve_mb": 5000}
    names = lambda pair: sorted(a.name for a in pair[0])  # noqa: E731
    assert names(registry.eligible(FakeGpu(7500), config)) == ["local voice music", "research"]
    in_game = registry.eligible(FakeGpu(7500, "RobloxPlayerBeta.exe"), config)
    assert names(in_game) == ["research"] and "game mode" in in_game[1]
    assert names(registry.eligible(FakeGpu(9500, "javaw.exe"), config)) == ["local voice music", "research"]
    assert names(registry.eligible(FakeGpu(None), config)) == ["research"]


def test_cycle_skips_gpu_activities_during_a_game(home):
    life = Life(home, rng=random.Random(3))
    seen = set()
    for _ in range(6):
        out = cycle(home, {"pause_minutes": 0, "game_reserve_mb": 5000}, _gpu_registry(), life,
                    Executor(home, FakeBackend()), None, FakeGpu(6000, "RobloxPlayerBeta.exe"))
        seen.add(out["activity"])
    assert seen == {"research"}


def test_without_a_brain_brain_sessions_wait_instead_of_failing(home):
    out = cycle(home, {"pause_minutes": 0}, activities.default_registry(()), Life(home),
                Executor(home, FakeBackend()), None, FakeGpu(8000))
    assert out == {"state": "idle", "why": "no brain configured (config.json brain_url)"}
    assert Life(home).history() == []
