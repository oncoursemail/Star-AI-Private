import json

import pytest

from launcher.rc.backend import http_fetch
from launcher.rc.errors import RcError

from conftest import finish


def status(world):
    return world.module().backend.status()


def test_running_backend_reports_honest_capabilities(world):
    world.backend.up = True
    st = status(world)
    assert st["state"] == "running" and st["instanceId"] == "abc123" and st["ready"] is True
    assert st["nativeClientReady"] is False and st["actualGameClientVerified"] is False
    assert st["native"] == {"nativeLogin": False, "nativeRoomJoin": False, "nativeGameplay": False, "nativeVoice": False}
    assert "has not logged into it" in st["honesty"]
    json.dumps(st)


def test_status_never_claims_the_game_works_unless_rc_says_so(world):
    world.backend.up, world.backend.verified = True, True
    assert status(world)["actualGameClientVerified"] is True  # only because the backend itself reported it


@pytest.mark.parametrize("task,state", [("Ready", "stopped"), ("Disabled", "disabled"), ("absent", "not_installed"), ("Running", "unhealthy")])
def test_down_backend_state_comes_from_the_windows_task(world, task, state):
    world.backend.task = task
    st = status(world)
    assert st["state"] == state and st["task"] == task


def test_another_service_on_the_port_is_a_conflict_and_is_left_alone(world):
    world.backend.other_service = True
    mod = world.module()
    st = mod.backend.status()
    assert st["state"] == "conflict"
    assert mod.backend.error_for(st).code == "backend_conflict"
    done = finish(mod, mod.call("backend.start"))
    assert done["state"] == "failed" and done["error"]["code"] == "backend_conflict" and world.backend.start_calls == 0


def test_start_runs_the_task_and_waits_for_health(world):
    mod = world.module()
    done = finish(mod, mod.call("backend.start"))
    assert done["state"] == "done" and done["result"]["state"] == "running" and done["result"]["changed"] is True
    assert world.backend.start_calls == 1
    assert [s["state"] for s in done["stages"]] == ["done", "done", "done"]


def test_start_when_already_running_does_nothing(world):
    world.backend.up = True
    mod = world.module()
    done = finish(mod, mod.call("backend.start"))
    assert done["result"] == {"state": "running", "changed": False} and world.backend.start_calls == 0


def test_start_on_a_disabled_task_asks_first_then_enables(world):
    world.backend.task = "Disabled"
    mod = world.module()
    refused = finish(mod, mod.call("backend.start"))
    assert refused["error"]["code"] == "backend_disabled"
    assert [a["id"] for a in refused["error"]["actions"]] == ["enable_and_start"]
    assert world.backend.start_calls == 0
    done = finish(mod, mod.call("repair.run", {"action": "enable_and_start"}))
    assert done["state"] == "done" and world.backend.start_calls == 1


def test_start_with_no_task_is_a_plain_error(world):
    world.backend.task = "absent"
    mod = world.module()
    assert finish(mod, mod.call("backend.start"))["error"]["code"] == "backend_task_missing"


def test_start_times_out_with_a_readable_error(world):
    world.backend.polls_until_up = 10_000
    mod = world.module()
    ticks = iter(range(0, 10_000))
    mod.backend._clock = lambda: next(ticks) * 1.0  # a fake clock: every look takes one "second"
    done = finish(mod, mod.call("backend.start"))
    assert done["error"]["code"] == "backend_start_timeout"


def test_unhealthy_running_task_is_not_started_twice(world):
    world.backend.task = "Running"
    mod = world.module()
    world.backend._starting = 2  # it is slow to come up
    done = finish(mod, mod.call("backend.start"))
    assert done["state"] == "done" and world.backend.start_calls == 0


def test_stop_uses_the_rc_script_and_waits(world):
    world.backend.up = True
    mod = world.module()
    (world.paths.backend_dir / "ops").mkdir(parents=True)
    (world.paths.backend_dir / "ops" / "Stop-LocalBackend.ps1").write_text("x")
    done = finish(mod, mod.call("backend.stop"))
    assert done["state"] == "done" and done["result"]["state"] == "stopped" and world.backend.stop_calls == 1
    cmd = [c for c in world.runner.calls if c[0] == "powershell" and any("Stop-LocalBackend" in a for a in c)][0]
    assert "-ExecutionPolicy" in cmd and "RemoteSigned" in cmd and "-DisableAutoStart" not in cmd
    again = finish(mod, mod.call("backend.stop", {"disableAutoStart": True}))
    assert again["result"]["changed"] is False  # already stopped: the script is not run again


def test_stop_failure_leaves_it_running_and_says_so(world):
    world.backend.up, world.backend.stop_fails = True, True
    mod = world.module()
    (world.paths.backend_dir / "ops").mkdir(parents=True)
    (world.paths.backend_dir / "ops" / "Stop-LocalBackend.ps1").write_text("x")
    done = finish(mod, mod.call("backend.stop"))
    assert done["error"]["code"] == "backend_unhealthy" and "left running" in done["error"]["message"]


def test_stop_without_the_script_is_a_plain_error(world):
    world.backend.up = True
    mod = world.module()
    assert finish(mod, mod.call("backend.stop"))["error"]["code"] == "backend_task_missing"


def test_restart_stops_then_starts(world):
    world.backend.up = True
    mod = world.module()
    (world.paths.backend_dir / "ops").mkdir(parents=True)
    (world.paths.backend_dir / "ops" / "Stop-LocalBackend.ps1").write_text("x")
    done = finish(mod, mod.call("repair.run", {"action": "restart_backend"}))
    assert done["state"] == "done" and world.backend.stop_calls == 1 and world.backend.start_calls == 1


def test_deployment_manifest_cannot_redirect_the_port_or_task(world):
    (world.paths.backend_dir).mkdir(parents=True)
    (world.paths.backend_dir / "deployment.json").write_text(json.dumps({"port": 80, "taskName": "Evil; calc"}))
    dep = world.module().backend.deployment()
    assert dep["port"] == 4187 and dep["task"] == "Metallic-RC-Backend"
    (world.paths.backend_dir / "deployment.json").write_text(json.dumps({"port": 4200, "taskName": "Metallic-RC-Backend"}))
    assert world.module().backend.deployment()["port"] == 4200


def test_http_fetch_is_loopback_only():
    for url in ("http://example.com/healthz", "http://localhost:4187/healthz", "https://127.0.0.1:4187/", "file:///c:/x"):
        with pytest.raises(OSError):
            http_fetch(url, 1)


def test_backend_logs_are_read_only_tail(world):
    log = world.paths.backend_dir / "logs" / "backend.log"
    log.parent.mkdir(parents=True)
    log.write_text("\n".join(f"line {i}" for i in range(500)))
    assert world.module().backend.logs(3) == ["line 497", "line 498", "line 499"]
    assert world.module().call("backend.logs", {"lines": 2})["lines"][-1] == "line 499"
