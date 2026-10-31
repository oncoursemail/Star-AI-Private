"""The Studio build loop against a stand-in connector that carries the real tool schemas."""
import asyncio
import json

import pytest

from star import policy, studio_loop as sl
from star.policy import allowed_registry, classify, enforce
from star.roblox_cloud import DENIED_PLACE_IDS
from star.studio import list_tools
from tests.studio_fake import TOOLS, FakeStudio

SID = "studio-1"
DENIED = next(iter(DENIED_PLACE_IDS))


def run(coroutine):
    return asyncio.run(coroutine)


async def opened(fake, **settings):
    settings.setdefault("opted_in", True)
    return await sl.open_guarded(fake, await list_tools(fake), studio_id=fake.studio_id, **settings)


# ------------------------------------------------------------------ the tool list is discovered, then sorted

def test_every_tool_the_connector_offers_today_is_classified():
    groups = classify(TOOLS)
    assert len(TOOLS) == 30 and groups["unknown"] == []
    assert groups["edit"] == ["multi_edit", "start_stop_play"] and groups["luau"] == ["execute_luau"]
    assert groups["playtest"] == ["character_navigation", "user_keyboard_input", "user_mouse_input"]
    assert set(groups["blocked"]) == policy.BLOCKED_TOOLS
    assert not policy.BLOCKED_TOOLS & (policy.READ_TOOLS | policy.WRITE_TOOLS)


def test_what_a_model_is_offered_depends_on_the_mode():
    discovered = run(list_tools(FakeStudio()))
    assert [tool["name"] for tool in discovered] == [tool["name"] for tool in TOOLS]      # read at runtime
    reading = set(allowed_registry(discovered, False))
    assert reading == policy.READ_TOOLS and not reading & policy.WRITE_TOOLS
    editing = set(allowed_registry(discovered, True))
    assert editing == policy.READ_TOOLS | policy.EDIT_TOOLS | policy.PLAYTEST_TOOLS
    assert set(allowed_registry(discovered, True, allow_luau=True)) == editing | {"execute_luau"}
    with pytest.raises(ValueError):
        allowed_registry(discovered, False, allow_luau=True)


def test_a_tool_star_does_not_know_is_reported_and_never_offered():
    newer = [*TOOLS, {"name": "publish_to_roblox", "description": "new in some later connector",
                      "inputSchema": {"type": "object", "properties": {"studio_id": {"type": "string"}}}}]
    assert classify(newer)["unknown"] == ["publish_to_roblox"]
    assert "publish_to_roblox" not in allowed_registry(newer, True, allow_luau=True)


def test_read_only_screenshots_work_with_the_real_schema():
    registry = allowed_registry(TOOLS, False)
    enforce("screen_capture", {"studio_id": SID, "capture_id": "ScreenCapture_1"}, registry, SID, False)
    with pytest.raises(ValueError, match="Camera"):
        enforce("screen_capture", {"studio_id": SID, "capture_id": "c", "camera_position": [0, 9, 0]}, registry, SID, False)
    with pytest.raises(Exception):
        enforce("screen_capture", {"studio_id": SID}, registry, SID, False)          # the connector requires capture_id


def test_edits_playtest_input_and_luau_are_enforced_in_code():
    edit = {"studio_id": SID, "datamodel_type": "Edit", "file_path": "ServerScriptService.A",
            "edits": [{"old_string": "", "new_string": "print(1)"}], "className": "Script"}
    walk = {"studio_id": SID, "datamodel_type": "Client", "x": 1, "y": 2, "z": 3}
    luau = {"studio_id": SID, "datamodel_type": "Edit", "code": "return 1"}
    full = allowed_registry(TOOLS, True, allow_luau=True)
    for name, arguments in (("multi_edit", edit), ("character_navigation", walk), ("execute_luau", luau)):
        enforce(name, arguments, full, SID, True, allow_luau=True)
        with pytest.raises(ValueError):
            enforce(name, arguments, full, SID, False)                               # edits switched off
        with pytest.raises(ValueError):
            enforce(name, {**arguments, "studio_id": "other"}, full, SID, True, allow_luau=True)
    with pytest.raises(ValueError):
        enforce("execute_luau", luau, full, SID, True)                               # Luau not allowed
    with pytest.raises(ValueError):
        enforce("execute_luau", {**luau, "datamodel_type": "Server"}, full, SID, True, allow_luau=True)
    with pytest.raises(ValueError):
        enforce("insert_asset", {"studio_id": SID, "assetId": "1"}, full, SID, True, allow_luau=True)


# ------------------------------------------------------------------ the sandbox rule

def identity(**changes):
    facts = dict(place_id=0, game_id=0, creator_id=0, creator_type="User", name="Baseplate", scripts=0, marker=False)
    return sl.PlaceIdentity(**{**facts, **changes})


@pytest.mark.parametrize("facts, settings, kind, editable", [
    (dict(), dict(opted_in=True), "blank", True),
    (dict(), dict(opted_in=False), "blank", False),
    (dict(scripts=3), dict(opted_in=True), "not_blank", False),                 # someone's unsaved work
    (dict(scripts=3, marker=True), dict(opted_in=True), "blank", True),         # STAR's own earlier build
    (dict(place_id=55, game_id=5, creator_id=4242), dict(opted_in=True), "published", False),
    (dict(place_id=55, game_id=5, creator_id=4242), dict(opted_in=True, own_account_id=4242), "own", False),
    (dict(place_id=55, game_id=5, creator_id=4242), dict(opted_in=True, own_places=True, own_account_id=4242), "own", True),
    (dict(place_id=55, game_id=5, creator_id=4242), dict(opted_in=False, own_places=True, own_account_id=4242), "own", False),
    (dict(place_id=55, game_id=5, creator_id=7), dict(opted_in=True, own_places=True, own_account_id=4242), "published", False),
    (dict(place_id=55, game_id=5, creator_id=4242, creator_type="Group"),
     dict(opted_in=True, own_places=True, own_account_id=4242), "published", False),
    (dict(place_id=DENIED, game_id=5, creator_id=4242), dict(opted_in=True, own_places=True, own_account_id=4242), "denied", False),
])
def test_the_sandbox_rule(facts, settings, kind, editable):
    verdict = sl.judge(identity(**facts), **settings)
    assert (verdict.kind, verdict.editable) == (kind, editable) and verdict.reason


def test_an_unidentified_place_is_read_only():
    assert sl.judge(None, opted_in=True, own_places=True, own_account_id=1).editable is False
    assert sl.judge(identity(), opted_in=True, studio_name=f"Paintball ({DENIED})").kind == "denied"


def test_a_blank_baseplate_is_identified_and_may_be_edited():
    for quoted in (False, True):                       # whichever way the connector quotes a returned string
        fake = FakeStudio(quote_results=quoted)
        studio = run(opened(fake))
        assert studio.verdict.editable and studio.verdict.kind == "blank"
        assert studio.verdict.identity == identity(session=fake.identity["session"])
        assert fake.names() == ["list_roblox_studios", "execute_luau"]
        assert fake.calls[1][1]["code"] == sl.IDENTITY_PROBE and fake.calls[1][1]["datamodel_type"] == "Edit"


def test_the_denied_place_is_never_asked_anything_and_never_edited():
    fake = FakeStudio(name=f"Paintball [{DENIED}]", place_id=DENIED, game_id=9, creator_id=1)
    studio = run(opened(fake, own_places=True, own_account_id=1))
    assert studio.verdict.kind == "denied" and not studio.verdict.editable
    assert fake.names() == ["list_roblox_studios"]                              # not even the identity question
    refused = run(studio.call_tool("multi_edit", {"studio_id": SID, "datamodel_type": "Edit",
                                                  "file_path": "ServerScriptService.X", "className": "Script",
                                                  "edits": [{"old_string": "", "new_string": "x"}]}))
    assert refused.model_dump()["isError"] and "deny-list" in sl.result_text(refused)
    report = run(sl.run_build_loop(studio, scripts=[{"path": "ServerScriptService.X", "source": "print(1)"}]))
    assert report["stopped"].startswith("read only") and not set(fake.names()) & policy.WRITE_TOOLS
    assert fake.scripts == {}


def test_a_published_place_of_another_account_is_read_only_and_readable():
    fake = FakeStudio(name="Someone's game", place_id=777, game_id=77, creator_id=5)
    fake.scripts["ServerScriptService.Main"] = {"class": "Script", "source": "local function f() end"}
    studio = run(opened(fake, own_places=True, own_account_id=4242))
    assert studio.verdict.kind == "published"
    report = run(sl.run_build_loop(studio, scripts=[{"path": "ServerScriptService.Main", "source": "broken"}]))
    assert [step["step"] for step in report["steps"]] == ["connect", "read tree", "read scripts", "screenshot before"]
    assert all(step["ok"] for step in report["steps"])
    assert fake.scripts["ServerScriptService.Main"]["source"] == "local function f() end"
    assert not [name for name in fake.names() if name in ("multi_edit", "start_stop_play")]
    assert fake.names().count("execute_luau") == 1                              # only STAR's identity question


def test_other_reasons_to_stay_read_only():
    assert run(opened(FakeStudio(), opted_in=False)).verdict.editable is False
    crowded = FakeStudio()
    crowded.scripts["ServerScriptService.Old"] = {"class": "Script", "source": "print('mine')"}
    assert run(opened(crowded)).verdict.kind == "not_blank"
    no_luau = FakeStudio(tools=[tool for tool in TOOLS if tool["name"] != "execute_luau"])
    assert run(opened(no_luau)).verdict.kind == "unknown"
    gone = FakeStudio()
    studio = run(sl.open_guarded(gone, TOOLS, studio_id="closed-instance", opted_in=True))
    assert studio.verdict.kind == "unknown" and "not open" in studio.verdict.reason


def test_a_place_of_stars_own_account_needs_both_switches():
    fake = FakeStudio(name="STAR Test Place", place_id=9001, game_id=7001, creator_id=4242)
    assert run(opened(fake, own_account_id=4242)).verdict.editable is False
    assert run(opened(fake, own_places=True, own_account_id=4242)).verdict.editable is True
    assert run(opened(fake, own_places=True, own_account_id=None)).verdict.editable is False


# ------------------------------------------------------------------ guarded edits, journal, undo

def test_the_guard_refuses_the_wrong_instance_and_blocked_tools():
    fake = FakeStudio()
    studio = run(opened(fake))
    before = len(fake.calls)
    wrong = run(studio.call_tool("start_stop_play", {"studio_id": "studio-2", "is_start": True}))
    blocked = run(studio.call_tool("insert_asset", {"studio_id": SID, "assetId": "1"}))
    server = run(studio.call_tool("execute_luau", {"studio_id": SID, "datamodel_type": "Server", "code": "x"}))
    assert all(result.model_dump()["isError"] for result in (wrong, blocked, server))
    assert len(fake.calls) == before and fake.playing is False


def test_a_luau_edit_is_wrapped_tagged_and_listed():
    fake = FakeStudio()
    fake.luau_effects = lambda code: [("Model", "Workspace.Lobby"), ("Part", "Workspace.Lobby.Floor")]
    studio = run(opened(fake))
    code = "local lobby = Instance.new('Model')\nlobby.Name = 'Lobby' -- last line is a comment"
    result = run(studio.call_tool("execute_luau", {"studio_id": SID, "datamodel_type": "Edit", "code": code}))
    sent = fake.calls[-1][1]["code"]
    assert sent.startswith("-- STAR:bound ")
    assert json.loads(sent.split("\n", 1)[0].removeprefix("-- STAR:bound "))["session"] == fake.identity["session"]
    assert "\nlobby.Name = 'Lobby' -- last line is a comment\nend)" in sent
    assert "TryBeginRecording" in sent and "FinishRecording" in sent and "StarSandbox" in sent
    assert not result.model_dump()["isError"]
    entry = studio.journal.entries[-1]
    assert entry["known"] and entry["ok"] and entry["added_count"] == 2
    assert entry["added"] == ["Model Workspace.Lobby", "Part Workspace.Lobby.Floor"]
    assert "2 instance(s) added" in studio.journal.report()["changes"][0]["what"]
    assert run(studio.undo())["undone"] == ["undid recorded Luau edit"]
    assert "Workspace.Lobby" not in fake.instances and "Workspace.Baseplate" in fake.instances


def test_the_whole_loop_builds_playtests_fixes_and_reports_with_undo():
    fake = FakeStudio()
    fake.luau_effects = lambda code: [("ScreenGui", "StarterGui.Shop"), ("TextButton", "StarterGui.Shop.Buy")]

    def play(studio):                                   # what Studio's output shows for the current scripts
        source = studio.scripts["ServerScriptService.Shop"]["source"]
        studio.console = (["ServerScriptService.Shop:2: attempt to index nil with 'Coins'", "Stack Begin"]
                          if "leaderstats.Coins" in source and "WaitForChild" not in source else ["Shop ready"])
    fake.on_play = play
    broken = "local Players = game:GetService('Players')\nprint(Players.LocalPlayer.leaderstats.Coins)"
    fixed = "local Players = game:GetService('Players')\nprint('Shop ready') -- WaitForChild added"
    seen_errors = []

    def fix(errors):
        seen_errors.extend(errors)
        return [{"path": "ServerScriptService.Shop", "class_name": "Script", "source": fixed}]

    studio = run(opened(fake))
    report = run(sl.run_build_loop(
        studio, scripts=[{"path": "ServerScriptService.Shop", "class_name": "Script", "source": broken}],
        luau_edits=["local gui = Instance.new('ScreenGui') gui.Name = 'Shop' gui.Parent = game.StarterGui"], fix=fix))
    assert [step["step"] for step in report["steps"]] == [
        "connect", "read tree", "read scripts", "screenshot before", "write ServerScriptService.Shop",
        "build instances", "playtest first", "screenshot after first playtest",
        "write ServerScriptService.Shop", "playtest after the fix", "screenshot after the fix"]
    assert report["ok"] and all(step["ok"] for step in report["steps"])
    assert "attempt to index nil" in seen_errors[0]
    assert report["steps"][6]["errors"] and report["steps"][9]["errors"] == []
    assert fake.scripts["ServerScriptService.Shop"]["source"] == fixed and fake.marker and not fake.playing
    changes = report["changes"]
    assert changes["edits"] == 3 and changes["undo"]["available"]
    assert [item["what"].split(":")[0] for item in changes["changes"]] == [
        "created script ServerScriptService.Shop", "ran an edit", "started a playtest", "stopped the playtest",
        "edited script ServerScriptService.Shop", "started a playtest", "stopped the playtest"]
    assert "Studio changes in this turn (3)" in studio.journal.text() and "Ctrl+Z" in studio.journal.text()

    undone = run(studio.undo())
    assert undone["left"] == [] and len(undone["undone"]) == 3
    assert fake.scripts == {} and "StarterGui.Shop" not in fake.instances
    assert set(fake.instances) == {"Workspace.Baseplate", "Workspace.SpawnLocation"}
    assert studio.journal.report()["edits"] == 0


def test_an_existing_script_is_restored_exactly(tmp_path):
    fake = FakeStudio()
    fake.marker = True                                   # an earlier STAR session built here
    original = "local a = 1\nprint(a)"
    fake.scripts["ReplicatedStorage.Config"] = {"class": "ModuleScript", "source": original}
    studio = run(opened(fake))
    run(studio.call_tool("multi_edit", {"studio_id": SID, "datamodel_type": "Edit", "file_path": "game.ReplicatedStorage.Config",
                                        "edits": [{"old_string": "local a = 1", "new_string": "local a = 2"}]}))
    assert fake.scripts["ReplicatedStorage.Config"]["source"] == "local a = 2\nprint(a)"
    entry = studio.journal.entries[0]
    assert entry == {"kind": "script", "path": "game.ReplicatedStorage.Config", "created": False,
                     "target_inspected": True,
                     "before": original, "after": "local a = 2\nprint(a)", "restorable": True,
                     "tag": entry["tag"], "instance_id": fake.scripts["ReplicatedStorage.Config"]["_id"],
                     "known": True, "ok": True, "undo_can": False, "undo_name": None,
                     "recorded": True, "connector_recorded": False}
    assert run(studio.undo())["undone"] == ["restored script game.ReplicatedStorage.Config"]
    assert fake.scripts["ReplicatedStorage.Config"]["source"] == original


def test_a_failed_edit_is_not_journaled_and_a_failed_luau_edit_is_reported():
    fake = FakeStudio()
    studio = run(opened(fake))
    bad = run(studio.call_tool("multi_edit", {"studio_id": SID, "datamodel_type": "Edit", "file_path": "Workspace.X",
                                              "edits": [{"old_string": "nope", "new_string": "y"}]}))
    assert bad.model_dump()["isError"] and studio.journal.entries == []
    run(studio.call_tool("execute_luau", {"studio_id": SID, "datamodel_type": "Edit", "code": "error('boom')"}))
    assert studio.journal.entries[-1]["ok"] is False
    assert "stopped with an error" in studio.journal.report()["changes"][0]["what"]


def test_stars_fixed_snippets_are_fixed_text():
    wrapped, tag = sl.wrap_edit("return 1", "StarEdit_0123abcd")
    assert tag == "StarEdit_0123abcd" and wrapped.count(tag) == 4
    with pytest.raises(ValueError):
        sl.wrap_edit("return 1", 'x") game:Destroy() --')
    assert "Destroy" not in sl.IDENTITY_PROBE and "SetAttribute" not in sl.IDENTITY_PROBE     # the question only reads
    assert sl._SCRIPT_PATH.fullmatch("game.ServerScriptService.Shop.Main")
    assert not sl._SCRIPT_PATH.fullmatch('ServerScriptService.X") game:Destroy() --')
    assert sl.console_errors("Shop ready\nWorkspace.A:3: attempt to call a nil value\nInfinite yield possible on x") == [
        "Workspace.A:3: attempt to call a nil value", "Infinite yield possible on x"]
    assert json.loads(json.dumps(sl.judge(None, opted_in=True).public()))["editable"] is False


# ------------------------------------------------------------------ a model drives the loop through the agent

class ScriptedModel:
    """Answers with the next prepared tool call, then with text; keeps what it was sent."""

    def __init__(self, steps):
        self.steps, self.requests = list(steps), []

    async def create(self, **kwargs):
        from types import SimpleNamespace
        self.requests.append(kwargs)
        step = self.steps.pop(0)
        if isinstance(step, str):
            message = SimpleNamespace(content=step, tool_calls=None)
        else:
            name, arguments = step
            message = SimpleNamespace(content=None, tool_calls=[SimpleNamespace(
                id=f"call{len(self.requests)}", function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


LOOP_STEPS = [
    ("search_game_tree", {"studio_id": SID, "datamodel_type": "Edit"}),
    ("screen_capture", {"studio_id": SID, "capture_id": "ScreenCapture_1"}),
    ("multi_edit", {"studio_id": SID, "datamodel_type": "Edit", "file_path": "ServerScriptService.Door", "className": "Script",
                    "edits": [{"old_string": "", "new_string": "print('door ready')"}]}),
    ("execute_luau", {"studio_id": SID, "datamodel_type": "Edit", "code": "local p = Instance.new('Part') p.Name = 'Door' p.Parent = workspace"}),
    ("start_stop_play", {"studio_id": SID, "is_start": True}),
    ("get_console_output", {"studio_id": SID}),
    ("start_stop_play", {"studio_id": SID, "is_start": False}),
    ("insert_asset", {"studio_id": SID, "assetId": "123"}),            # a tool STAR never offers
    "The door is built and the playtest printed 'door ready'.",
]


def drive(fake, *, luau=True, **settings):
    """One agent turn with a scripted model, wired the way star/desktop_core.py wires a Studio turn."""
    from types import SimpleNamespace
    from star.agent import execute
    settings.setdefault("opted_in", True)

    async def turn():
        discovered = await list_tools(fake)
        studio = await sl.open_guarded(fake, discovered, studio_id=SID, **settings)
        model = ScriptedModel(LOOP_STEPS)
        events = []
        outcome = await execute(
            client=SimpleNamespace(chat=SimpleNamespace(completions=model)), model="local", image_paths=[],
            prompt="Build a door in Studio and playtest it", studio=studio, discovered=discovered, studio_id=SID,
            may_edit=studio.verdict.editable, allow_luau=studio.verdict.editable and luau,
            on_event=events.append, max_calls=12)
        return sl.with_report(outcome, studio), studio, model, events
    return run(turn())


def test_a_model_runs_the_whole_loop_in_a_blank_place_and_the_answer_lists_the_changes():
    fake = FakeStudio()
    fake.luau_effects = lambda code: [("Part", "Workspace.Door")]
    fake.on_play = lambda studio: studio.console.append("door ready")
    (answer, _messages, _archive), studio, model, events = drive(fake)
    offered = {tool["function"]["name"] for tool in model.requests[0]["tools"]}
    assert {"multi_edit", "execute_luau", "start_stop_play", "screen_capture", "get_console_output"} <= offered
    assert not offered & policy.BLOCKED_TOOLS
    assert fake.scripts["ServerScriptService.Door"]["source"] == "print('door ready')"
    assert "Workspace.Door" in fake.instances and fake.playing is False and fake.console == ["door ready"]
    assert [event["tool"] for event in events if event["event"] == "tool_rejected"] == ["insert_asset"]
    assert "insert_asset" not in fake.names()
    assert answer.startswith("The door is built and the playtest printed 'door ready'.\n\nStudio changes in this turn (2):")
    assert "- created script ServerScriptService.Door" in answer and "Part Workspace.Door" in answer and "Undo:" in answer
    assert run(studio.undo())["left"] == [] and fake.scripts == {} and "Workspace.Door" not in fake.instances


def test_the_same_model_can_only_read_a_published_place():
    fake = FakeStudio(name="A live game", place_id=4321, game_id=432, creator_id=9)
    (answer, _messages, _archive), studio, model, events = drive(fake)
    offered = {tool["function"]["name"] for tool in model.requests[0]["tools"]}
    assert offered == policy.READ_TOOLS
    rejected = [event["tool"] for event in events if event["event"] == "tool_rejected"]
    assert rejected == ["multi_edit", "execute_luau", "start_stop_play", "start_stop_play", "insert_asset"]
    assert fake.scripts == {} and fake.playing is False and "Workspace.Door" not in fake.instances
    assert fake.names().count("execute_luau") == 1 and "Studio changes" not in answer      # only STAR's own question ran


def test_without_the_luau_switch_a_model_edits_scripts_but_cannot_run_code():
    fake = FakeStudio()
    (answer, _messages, _archive), studio, model, events = drive(fake, luau=False)
    offered = {tool["function"]["name"] for tool in model.requests[0]["tools"]}
    assert "multi_edit" in offered and "execute_luau" not in offered
    assert "execute_luau" in [event["tool"] for event in events if event["event"] == "tool_rejected"]
    assert "ServerScriptService.Door" in fake.scripts and "Workspace.Door" not in fake.instances
    assert "Studio changes in this turn (1):" in answer


# ------------------------------------------------------------------ a Studio on another machine

def test_the_owner_can_name_a_launcher_for_a_studio_elsewhere(monkeypatch):
    from star import studio
    monkeypatch.delenv(studio.COMMAND_ENV, raising=False)
    assert studio.custom_launcher() is None
    monkeypatch.setenv(studio.COMMAND_ENV, json.dumps(["ssh", "-o", "BatchMode=yes", "studio-host", "studio-mcp.sh"]))
    assert studio.launcher() == ("ssh", ["-o", "BatchMode=yes", "studio-host", "studio-mcp.sh"], None)
    for bad in ("ssh studio-host", "[]", '["ssh", 7]', '{"program": "ssh"}', '[""]', json.dumps(["x"] * 41)):
        monkeypatch.setenv(studio.COMMAND_ENV, bad)
        with pytest.raises(RuntimeError, match="JSON list"):
            studio.launcher()


def test_without_it_only_the_local_windows_launcher_is_used(monkeypatch, tmp_path):
    from star import studio
    monkeypatch.delenv(studio.COMMAND_ENV, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(studio.sys, "platform", "win32")
    assert studio.launcher() == ("cmd.exe", ["/d", "/c", str(tmp_path / "Roblox" / "mcp.bat")], tmp_path / "Roblox" / "mcp.bat")
    monkeypatch.setattr(studio.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match=studio.COMMAND_ENV):
        studio.launcher()
