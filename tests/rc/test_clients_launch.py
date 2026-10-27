import json

import pytest

from launcher.rc.clients import Clients, key_for

from conftest import CAMPUS_LAUNCHER, CAMPUS_ROOT, NEXA_ROOT, STEAM_ROOT, finish


def entries(mod):
    return {e["key"]: e for e in mod.call("clients.list")["clients"]}


def launch(mod, key="steam", **kw):
    return finish(mod, mod.call("launch.start", {"client": key, **kw}))


# -- detection and states ---------------------------------------------------------------------------------------------
def test_name_to_key():
    assert key_for("Rec Room \u00b7 Steam installation") == "steam"
    assert key_for("Campus \u00b7 existing installation") == "campus"
    assert key_for("NexaNet \u00b7 existing installation") == "nexanet"
    assert key_for("Meow.Net \u00b7 existing installation") == "meownet"
    assert key_for("Something else") is None


def test_every_known_client_is_listed_even_when_absent(world):
    e = entries(world.module())
    assert list(e) == ["steam", "campus", "nexanet", "meownet"]
    assert e["steam"]["state"] == "found" and e["campus"]["state"] == "not_found" and e["meownet"]["state"] == "not_found"
    assert [a["id"] for a in e["steam"]["actions"]] == ["register_client"]
    assert [a["id"] for a in e["campus"]["actions"]] == ["locate_client"]


def test_missing_steam_offers_the_steam_page_not_a_download(world):
    world.set_clients({})
    mod = world.module()
    e = entries(mod)["steam"]
    assert e["state"] == "not_found" and [a["id"] for a in e["actions"]] == ["install_from_steam"]
    out = mod.call("repair.run", {"action": "install_from_steam"})
    assert out["openUrl"].startswith("https://store.steampowered.com/app/")


def test_partner_revivals_are_detected_with_honest_states(world):
    world.full_pc()
    e = entries(world.module())
    assert e["campus"]["state"] == "found" and e["campus"]["launcherPath"] == CAMPUS_LAUNCHER and e["campus"]["usesOwnLauncher"]
    assert e["nexanet"]["state"] == "found" and e["nexanet"]["usesOwnLauncher"] and e["nexanet"]["launcherPath"] is None
    assert [a["id"] for a in e["nexanet"]["actions"]] == ["register_launcher"]  # modified client: asks for its launcher first
    assert e["meownet"]["state"] == "not_found"
    for p in ("campus", "nexanet", "meownet"):
        assert e[p]["kind"] == "partner"


def test_register_then_verify_walks_through_states(world):
    mod = world.module()
    assert entries(mod)["steam"]["state"] == "found"
    done = finish(mod, mod.call("clients.register", {"client": "steam"}))
    assert done["state"] == "done" and done["result"]["installationId"]
    assert entries(mod)["steam"]["state"] == "registered"
    ver = finish(mod, mod.call("clients.verify", {"client": "steam"}))
    assert ver["result"]["isValid"] is True
    assert entries(mod)["steam"]["state"] == "verified"


def test_changed_client_files_show_changed_and_offer_rebaseline_only_with_confirmation(world):
    mod = world.module()
    finish(mod, mod.call("clients.register", {"client": "steam"}))
    world.tamper(STEAM_ROOT)
    ver = finish(mod, mod.call("clients.verify", {"client": "steam"}))
    assert ver["result"]["isValid"] is False and ver["result"]["problems"][0]["path"] == "GameAssembly.dll"
    e = entries(mod)["steam"]
    assert e["state"] == "changed" and [a["id"] for a in e["actions"]] == ["rebaseline"]
    from launcher.rc.errors import RcError
    with pytest.raises(RcError) as err:
        mod.call("clients.rebaseline", {"client": "steam"})
    assert err.value.code == "bad_request"
    with pytest.raises(RcError):
        mod.call("repair.run", {"action": "rebaseline", "params": {"client": "steam"}})
    done = finish(mod, mod.call("clients.rebaseline", {"client": "steam", "confirm": True}))
    assert done["state"] == "done" and done["result"]["replaced"] is True
    assert finish(mod, mod.call("clients.verify", {"client": "steam"}))["result"]["isValid"] is True


def test_modified_client_must_get_its_launcher_before_it_can_be_added(world):
    world.full_pc()
    mod = world.module()
    refused = finish(mod, mod.call("clients.register", {"client": "nexanet"}))
    assert refused["error"]["code"] == "external_launcher_required"
    ok = finish(mod, mod.call("clients.register", {"client": "nexanet", "launcher": r"C:\Games\Nexa\Nexa.exe"}))
    assert ok["state"] == "done"
    assert entries(mod)["nexanet"]["launcherRegistered"] is True


def test_a_folder_the_owner_picks_is_inspected_first(world):
    world.set_clients({STEAM_ROOT: {"name": "Rec Room \u00b7 Steam installation"}, r"D:\Games\RecRoomCopy": {"name": "Copy"}})
    mod = world.module()
    bad = finish(mod, mod.call("clients.register", {"client": "custom", "folder": r"D:\Nope"}))
    assert bad["error"]["code"] == "client_missing" and "complete Rec Room client" in bad["error"]["message"]
    good = finish(mod, mod.call("clients.register", {"client": "custom", "folder": r"D:\Games\RecRoomCopy", "name": "My copy"}))
    assert good["state"] == "done"
    custom = [e for e in mod.call("clients.list")["clients"] if e["kind"] == "custom"]
    assert custom and custom[0]["name"] == "My copy" and custom[0]["state"] == "registered"


# -- launch -----------------------------------------------------------------------------------------------------------
def test_play_steam_screen_end_to_end(world):
    mod = world.module()
    done = launch(mod, "steam", mode="screen")
    assert done["state"] == "done", done["error"]
    r = done["result"]
    assert r["command"] == "RecRoom.exe +forcemode:screen" and r["running"] is True and r["mode"] == "screen" and r["target"] == "client"
    assert [s["id"] for s in done["stages"] if s["state"] == "done"] == [s["id"] for s in done["stages"]]
    # the first Play registered the client (read-only) and verified it
    assert entries(mod)["steam"]["state"] == "verified"
    assert any(w for w in r["warnings"] if "backend is not running" in w)
    assert mod.settings["mode"] == "screen" and mod.settings["lastClient"] == "steam"


def test_vr_mode_passes_vr_and_warns_without_a_runtime(world):
    world.vr = {"available": False, "runtimes": [], "steamvrRunning": False, "note": "No VR runtime found (SteamVR or an OpenXR runtime). VR mode may not start."}
    done = launch(world.module(), "steam", mode="vr")
    assert done["state"] == "done" and done["result"]["command"] == "RecRoom.exe +forcemode:vr"
    assert any("No VR runtime" in w for w in done["result"]["warnings"])
    assert mod_mode(world) == "vr"


def mod_mode(world):
    return json.loads(world.paths.settings_file.read_text())["mode"]


def test_changed_files_stop_the_launch_before_anything_starts(world):
    mod = world.module()
    finish(mod, mod.call("clients.register", {"client": "steam"}))
    world.tamper(STEAM_ROOT)
    done = launch(mod)
    assert done["state"] == "failed" and done["error"]["code"] == "files_changed"
    assert "GameAssembly.dll" in done["error"]["message"]
    assert [a["id"] for a in done["error"]["actions"]] == ["rebaseline", "locate_client", "view_log"]
    assert not (world.pc / "procs.json").exists()  # nothing was started
    assert [s["state"] for s in done["stages"]][:3] == ["done", "done", "failed"]


def test_client_missing(world):
    world.set_clients({})
    done = launch(world.module())
    assert done["error"]["code"] == "client_missing" and "never downloads the game" in done["error"]["message"]


def test_tools_missing_is_reported_by_play_with_the_install_action(world):
    world.legacy = False  # no RC tools anywhere on this PC
    mod = world.module()
    done = launch(mod)
    assert done["error"]["code"] == "tools_missing" and done["error"]["actions"][0]["id"] == "install_tools"


def test_process_start_failure_maps_to_launch_failed(world):
    (world.pc / "launch.fail").write_text("1")
    done = launch(world.module())
    assert done["error"]["code"] == "launch_failed"


def test_client_that_never_appears_is_exited_early_not_running(world):
    (world.pc / "launch.nopid").write_text("1")
    done = launch(world.module())
    assert done["state"] == "failed" and done["error"]["code"] == "exited_early"
    assert done["stages"][-1]["state"] == "failed"


def test_client_found_by_name_counts_even_if_the_pid_differs(world):
    (world.pc / "launch.nopid").write_text("1")
    world.procs.extra[999] = "recroom.exe"
    assert launch(world.module())["state"] == "done"


def test_campus_goes_through_its_own_launcher_only_after_confirmation(world):
    world.full_pc()
    mod = world.module()
    unconfirmed = launch(mod, "campus")
    assert unconfirmed["error"]["code"] == "external_launcher_unconfirmed"
    assert "Campus.exe" in unconfirmed["error"]["message"]
    assert not (world.pc / "procs.json").exists()
    done = launch(mod, "campus", confirmExternal=True, mode="vr")
    assert done["state"] == "done", done["error"]
    assert done["result"]["target"] == "external" and done["result"]["command"] == "Campus.exe"
    assert any("chooses screen or VR itself" in w for w in done["result"]["warnings"])
    launches = [c for c in world.runner.calls if len(c) > 2 and c[1] == "launch"]
    assert len(launches) == 1 and "--approved-launcher" in launches[0] and CAMPUS_LAUNCHER in launches[0]


def test_modified_client_without_launcher_cannot_be_played(world):
    world.full_pc()
    done = launch(world.module(), "nexanet", confirmExternal=True)
    assert done["error"]["code"] == "external_launcher_required"


def test_backend_is_started_with_the_client_only_when_the_owner_turned_that_on(world):
    mod = world.module()
    assert world.backend.start_calls == 0
    launch(mod)
    assert world.backend.start_calls == 0
    mod.call("settings.set", {"startBackendWithClient": True})
    done = launch(mod)
    assert done["state"] == "done" and world.backend.start_calls == 1
    assert done["result"]["backend"] == "running" and not any("backend" in w for w in done["result"]["warnings"])


def test_launch_with_the_backend_running_has_no_warning(world):
    world.backend.up = True
    done = launch(world.module())
    assert done["result"]["warnings"] == [] and done["result"]["backend"] == "running"


def test_a_second_play_while_one_runs_is_refused(world):
    import threading
    from launcher.rc.errors import RcError
    mod = world.module(spawn=None)
    gate = threading.Event()
    mod.flows.cli.list = lambda: gate.wait(5) and []
    first = mod.call("launch.start", {"client": "steam"})
    with pytest.raises(RcError) as e:
        mod.call("launch.start", {"client": "steam"})
    assert e.value.code == "busy"
    mod.call("task.cancel", {"id": first["task"]["id"]})
    gate.set()
    assert mod.tasks.wait(first["task"]["id"])["state"] in ("cancelled", "failed")
