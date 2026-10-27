import json
import threading

import pytest

from launcher.rc.errors import ACTIONS, RcError
from launcher.rc.module import RcModule, _validate_settings
from launcher.rc.paths import Paths

from conftest import finish


def test_overview_is_json_and_complete(world):
    world.full_pc()
    world.backend.up = True
    ov = world.module().call("overview")
    json.dumps(ov)
    assert set(ov) >= {"settings", "tools", "tasks", "clients", "backend", "vr", "steamUrl"}
    assert ov["tools"]["kind"] == "adopted" and ov["backend"]["state"] == "running"
    assert [c["key"] for c in ov["clients"]][:4] == ["steam", "campus", "nexanet", "meownet"]


def test_overview_still_draws_when_tools_are_missing(world):
    world.legacy = False
    ov = world.module().call("overview")
    assert ov["tools"]["installed"] is False and ov["clientsError"]["code"] == "tools_missing"
    assert ov["clientsError"]["actions"][0]["id"] == "install_tools"
    assert len(ov["clients"]) == 4 and all(c["state"] == "not_found" for c in ov["clients"])


def test_unknown_method_and_bad_params(world):
    mod = world.module()
    with pytest.raises(RcError) as e:
        mod.call("nope.nothing")
    assert e.value.code == "bad_request"
    with pytest.raises(RcError):
        mod.call("clients.verify", {})
    with pytest.raises(RcError):
        mod.call("clients.register", {"client": "steam", "launcher": 5})
    assert mod.call("settings.get")["mode"] == "screen"  # non-dict params are treated as empty
    assert mod.call("settings.get", "garbage")["mode"] == "screen"


def test_call_json_for_string_only_bridges(world):
    mod = world.module()
    ok = json.loads(mod.call_json("settings.get"))
    assert ok["ok"] is True and ok["result"]["mode"] == "screen"
    bad = json.loads(mod.call_json("nope"))
    assert bad["ok"] is False and bad["error"]["code"] == "bad_request"
    assert json.loads(mod.call_json("settings.get", "{not json"))["error"]["code"] == "bad_request"


def test_call_async_replies_on_the_bus_with_success_and_problem(world):
    mod = world.module()
    got, done = [], threading.Event()
    mod.subscribe(lambda ev: (got.append(ev), done.set()) if ev["type"] == "reply" else None)
    mod.call_async("r1", "settings.get")
    assert done.wait(5)
    assert got[0]["id"] == "r1" and got[0]["ok"] and got[0]["result"]["mode"] == "screen"
    done.clear()
    mod.call_async("r2", "clients.verify", {})
    assert done.wait(5)
    assert got[1]["id"] == "r2" and got[1]["ok"] is False and got[1]["error"]["code"] == "bad_request"
    mod.close()


def test_settings_are_validated_and_persisted(world):
    mod = world.module()
    out = mod.call("settings.set", {"mode": "vr", "startBackendWithClient": True, "bogus": 1,
                                    "source": {"kind": "url", "url": "https://forge.example/rc/latest.json"}})
    assert out["mode"] == "vr" and out["startBackendWithClient"] is True and "bogus" not in out
    again = RcModule(world.paths, runner=world.runner, procs=world.procs)
    assert again.settings == out
    assert mod.call("settings.set", {"mode": "teleport"})["mode"] == "screen"  # bad values fall back, they do not stick
    assert _validate_settings({"source": {"kind": "url", "url": "file:///c:/x"}})["source"] == {}
    assert _validate_settings({"source": {"kind": "folder", "path": ""}})["source"] == {}
    assert _validate_settings("garbage") == _validate_settings(None)


def test_damaged_settings_file_falls_back_to_defaults(world):
    world.paths.module_dir.mkdir(parents=True)
    world.paths.settings_file.write_text("{ not json")
    assert world.module().settings["mode"] == "screen"


def test_every_repair_action_in_the_catalog_is_handled(world):
    mod = world.module()
    handled = {"retry", "install_tools", "repair_tools", "rollback_tools", "start_backend", "enable_and_start", "restart_backend",
               "register_client", "rebaseline", "locate_client", "register_launcher", "install_from_steam", "use_screen",
               "view_log", "open_vr_help"}
    assert handled == set(ACTIONS)
    out = {a: None for a in ("retry", "use_screen", "install_from_steam", "view_log", "open_vr_help", "locate_client", "register_launcher")}
    for action in out:
        out[action] = mod.call("repair.run", {"action": action})
    assert out["retry"] == {"retry": True}
    assert out["locate_client"] == {"needsInput": "folder"} and out["register_launcher"] == {"needsInput": "launcher"}
    assert out["use_screen"]["settings"]["mode"] == "screen"
    with pytest.raises(RcError):
        mod.call("repair.run", {"action": "format_c"})


def test_rollback_refuses_while_a_task_runs(world):
    mod = world.module(spawn=lambda fn: None)  # a task that is queued and never finishes
    mod.call("backend.start")
    mod.call("tools.verify")  # does not exclude backend
    with pytest.raises(RcError) as e:
        mod.call("tools.rollback")
    assert e.value.code == "busy"


def test_task_log_lines_are_written_without_secrets_or_paths_to_keys(world):
    mod = world.module()
    mod.call("launch.start", {"client": "steam"})
    text = "\n".join(mod.log_tail())
    assert "launch" in text and "done" in text
    assert "admin.key" not in text and "X-Metallic-Admin" not in text


def test_failed_task_log_has_the_code_and_detail(world):
    world.set_clients({})
    mod = world.module()
    mod.call("launch.start", {"client": "steam"})
    assert "client_missing" in "\n".join(mod.log_tail())


def test_module_never_runs_a_shell_string(world):
    mod = world.module()
    mod.call("launch.start", {"client": "steam"})
    mod.call("backend.status")
    assert all(isinstance(c, list) for c in world.runner.calls)


def test_default_paths_follow_the_environment(tmp_path):
    p = Paths.from_env({"LOCALAPPDATA": str(tmp_path), "METALLIC_LAUNCHER_HOME": str(tmp_path / "x")})
    assert p.module_dir == tmp_path / "x" / "rc" and p.rc_home == tmp_path / "Metallic-RC"
    assert p.state_dir == tmp_path / "Metallic-RC" / "launcher"
    p2 = Paths.from_env({"LOCALAPPDATA": str(tmp_path), "METALLIC_RC_HOME": str(tmp_path / "rc2")})
    assert p2.backend_dir == tmp_path / "rc2" / "backend" and p2.launcher_home == tmp_path / "Metallic" / "Launcher"
