"""Minecraft tools through STAR's real agent loop, desktop routing and Settings boundary."""
from __future__ import annotations

import asyncio
import json
import re
import zipfile
from pathlib import Path

import pytest

from star import agent, desktop_core as core, minecraft_assets, skill_packs
from star.minecraft_tools import MinecraftTools, READ_TOOLS, TOOL_NAMES, WRITE_TOOLS, wants_minecraft
from star.react_shell import apply_setting_changes
from star.turn_memory import TurnMemory
from star.workspace import Workspace
from tests.test_debug_tools_integration import Client, Models, call, offered, reply, tool_payloads

ROOT = Path(__file__).resolve().parents[1]
PROMPT = "Check my Minecraft resource pack"


def _pack_files(root: Path):
    pack = root / "pack"
    pack.mkdir()
    (pack / "pack.mcmeta").write_text(json.dumps(
        {"pack": {"description": "t", "min_format": [97, 1], "max_format": [97, 1]}}), encoding="utf-8")
    return pack


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    _pack_files(root)
    plugins = root / "server" / "plugins"
    plugins.mkdir(parents=True)
    with zipfile.ZipFile(plugins / "Nexo.jar", "w") as jar:
        jar.writestr("plugin.yml", "name: Nexo\nversion: '1.2'\n")
    return Workspace(root)


def run_agent(responses, *, workspace=None, tools=None, prompt=PROMPT, **kwargs):
    models = Models(responses)
    result = asyncio.run(agent.execute(client=Client(models), model="offline", prompt=prompt,
                                      image_paths=[], workspace=workspace, minecraft_tools=tools,
                                      now="", **kwargs))
    return result, models.requests


def test_agent_audits_a_pack_through_the_registry(workspace):
    tools = MinecraftTools(workspace, enabled=True)
    result, requests = run_agent([
        reply(calls=[call("workspace_minecraft_audit", {"path": "pack"})]), reply(text="pack is fine"),
    ], workspace=workspace, tools=tools)
    assert result[0] == "pack is fine"
    assert offered(requests[0]) >= READ_TOOLS
    payload = tool_payloads(requests[1])[0]
    assert payload["isError"] is False
    report = json.loads(payload["output"])
    assert report["kind"] == "resource-pack" and report["valid"] is True and report["tested_in_game"] is False


def test_agent_inspects_only_the_named_server_folder(workspace):
    _, requests = run_agent([
        reply(calls=[call("workspace_minecraft_inspect", {"path": "server"})]), reply(text="done"),
    ], workspace=workspace, tools=MinecraftTools(workspace, enabled=True), prompt="Inspect my Paper server plugin folder")
    report = json.loads(tool_payloads(requests[1])[0]["output"])
    assert report["jars"][0]["name"] == "Nexo" and report["jar_executed"] is False
    # No path means no inspection: the tool never defaults to the workspace root or a scan.
    _, requests = run_agent([
        reply(calls=[call("workspace_minecraft_inspect", {})]), reply(text="done"),
    ], workspace=workspace, tools=MinecraftTools(workspace, enabled=True), prompt="Inspect my Paper server plugin folder")
    assert tool_payloads(requests[1])[0]["isError"] is True


@pytest.mark.parametrize("enabled", [None, False])
def test_disabled_minecraft_tools_are_neither_offered_nor_dispatched(workspace, enabled):
    tools = None if enabled is None else MinecraftTools(workspace, enabled=enabled)
    _, requests = run_agent([
        reply(calls=[call("workspace_minecraft_audit", {"path": "pack"})]), reply(text="done"),
    ], workspace=workspace, tools=tools)
    assert not TOOL_NAMES & offered(requests[0])
    assert "rejected" in json.dumps(tool_payloads(requests[-1]))


def test_unrelated_prompt_does_not_offer_or_dispatch_minecraft_tools(workspace):
    _, requests = run_agent([
        reply(calls=[call("workspace_minecraft_audit", {"path": "pack"})]), reply(text="done"),
    ], workspace=workspace, tools=MinecraftTools(workspace, enabled=True), prompt="Hello there")
    assert not TOOL_NAMES & offered(requests[0])
    assert "rejected" in json.dumps(tool_payloads(requests[-1]))


def test_write_tools_need_workspace_editing(workspace):
    args = {"path": "pack", "output": "pack.zip", "target_version": "26.3"}
    _, requests = run_agent([
        reply(calls=[call("workspace_minecraft_package", args)]), reply(text="done"),
    ], workspace=workspace, tools=MinecraftTools(workspace, enabled=True))
    assert not WRITE_TOOLS & offered(requests[0]) and READ_TOOLS <= offered(requests[0])
    assert "rejected" in json.dumps(tool_payloads(requests[-1]))
    assert not (workspace.root / "pack.zip").exists()
    _, requests = run_agent([
        reply(calls=[call("workspace_minecraft_package", args)]), reply(text="done"),
    ], workspace=workspace, tools=MinecraftTools(workspace, enabled=True, allow_write=True))
    assert TOOL_NAMES <= offered(requests[0])
    assert tool_payloads(requests[-1])[0]["isError"] is False
    assert (workspace.root / "pack.zip").is_file()


def test_unknown_argument_and_escape_are_refused(workspace):
    tools = MinecraftTools(workspace, enabled=True)
    _, requests = run_agent([
        reply(calls=[call("workspace_minecraft_audit", {"path": "pack", "command": "java -jar x.jar"})]),
        reply(calls=[call("workspace_minecraft_inspect", {"path": "../"}, "call_2")]), reply(text="done"),
    ], workspace=workspace, tools=tools)
    outputs = tool_payloads(requests[-1])
    assert [o["isError"] for o in outputs] == [True, True]


def test_plugin_metadata_cannot_reenable_full_luau_execution(workspace):
    from tests.test_luau_after_untrusted import LUAU_ARGS, LUAU_TOOL, Studio
    studio = Studio()
    _, requests = run_agent([
        reply(calls=[call("workspace_minecraft_inspect", {"path": "server"})]),
        reply(calls=[call("execute_luau", LUAU_ARGS, "call_2")]), reply(text="done"),
    ], workspace=workspace, tools=MinecraftTools(workspace, enabled=True),
        studio=studio, discovered=[LUAU_TOOL], studio_id="s1", may_edit=True, allow_luau=True,
        prompt="Inspect my Paper server plugin folder")
    assert studio.calls == []
    assert "rejected" in json.dumps(tool_payloads(requests[-1])[-1])


def test_sticky_tools_drop_immediately_when_owner_switches_off(workspace):
    memory = TurnMemory(sticky=True)
    tools = MinecraftTools(workspace, enabled=True)
    _, first = run_agent([reply(text="done")], workspace=workspace, tools=tools, tool_memory=memory)
    assert READ_TOOLS <= offered(first[0])
    tools.enabled = False
    _, off = run_agent([reply(text="done")], workspace=workspace, tools=tools,
                      prompt="Continue", tool_memory=memory)
    assert not TOOL_NAMES & offered(off[0])


def test_prompt_gate_matches_minecraft_work_only():
    for text in ("Make a Minecraft texture pack", "open my .bbmodel", "my Paper server plugin crashes",
                 "Is Nexo or Oraxen better", "fix pack.mcmeta"):
        assert wants_minecraft(text), text
    for text in ("Fix this Roblox script", "write a research paper", "What is a mod in Python?", ""):
        assert not wants_minecraft(text), text


def test_setting_defaults_false_round_trips_and_rejects_non_boolean(tmp_path):
    file = tmp_path / "settings.json"
    assert core.Settings.load(file).minecraft_tools_enabled is False
    settings = apply_setting_changes(core.Settings(), {"minecraft_tools_enabled": True})
    assert settings.minecraft_tools_enabled is True
    settings.save(file)
    assert core.Settings.load(file).minecraft_tools_enabled is True
    for invalid in (1, "true", None):
        with pytest.raises(ValueError):
            apply_setting_changes(core.Settings(), {"minecraft_tools_enabled": invalid}).save(file)


@pytest.mark.parametrize(("enabled", "has_workspace", "edit", "expected"), [
    (False, True, True, set()), (True, False, True, set()),
    (True, True, False, READ_TOOLS), (True, True, True, TOOL_NAMES),
])
def test_desktop_route_wires_only_owner_enabled_workspace_tools(
        tmp_path, monkeypatch, workspace, enabled, has_workspace, edit, expected):
    from star import server_roles, turn_memory
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "appdata"))
    server_roles.forget()
    turn_memory.forget()
    models = Models([reply(text="done")])
    monkeypatch.setattr(core, "open_client", lambda settings, **_: Client(models))
    settings = core.Settings(provider="local", model="offline", knowledge_endpoint="off",
                             web_auto_search=False, skills_enabled=False, graphify_enabled=False,
                             minecraft_tools_enabled=enabled, workspace_edit=edit,
                             workspace=str(workspace.root) if has_workspace else "")
    assert core.run_task(settings, PROMPT, mode="agent") == "done"
    assert TOOL_NAMES & offered(models.requests[0]) == set(expected)
    server_roles.forget()
    turn_memory.forget()


def test_package_zips_the_bytes_that_were_validated(workspace, monkeypatch):
    pack = workspace.root / "pack"
    (pack / "assets" / "ns" / "models").mkdir(parents=True)
    good = json.dumps({"parent": "minecraft:item/generated"}).encode()
    (pack / "assets" / "ns" / "models" / "a.json").write_bytes(good)
    real = minecraft_assets._files_from_folder
    calls = []

    def snapshot_then_edit(root):
        result = real(root)
        calls.append(root)
        # An editor save after validation must not reach the archive unchecked.
        (root / "assets" / "ns" / "models" / "a.json").write_bytes(b"{ not json")
        return result

    monkeypatch.setattr(minecraft_assets, "_files_from_folder", snapshot_then_edit)
    minecraft_assets.package(workspace, "pack", "out.zip", target_version="26.3")
    assert len(calls) == 1
    with zipfile.ZipFile(workspace.root / "out.zip") as archive:
        assert archive.read("assets/ns/models/a.json") == good


def test_engine_minecraft_pack_names_only_real_tools_and_fits_the_budget():
    pack = {p.name: p for p in skill_packs.available()}["engine-minecraft"]
    assert len(pack.body) <= 4600
    reference = (pack.file.parent / "references" / "server-assets.md").read_text(encoding="utf-8")
    assert "references/server-assets.md" in pack.body
    assert set(re.findall(r"workspace_minecraft_\w+", reference)) == set(TOOL_NAMES)
    assert "minecraft_tools_enabled" in reference


def test_blockbench_installer_never_downloads_silently():
    text = (ROOT / "scripts" / "install-blockbench-windows.ps1").read_text(encoding="utf-8")
    for banned in ("Invoke-WebRequest", "Invoke-RestMethod", "iwr ", "curl", "wget", "DownloadFile",
                   "DownloadString", "Start-BitsTransfer", "Invoke-Expression", "iex ", "-Force",
                   "--accept-package-agreements", "--accept-source-agreements", "--silent"):
        assert banned not in text, banned
    code = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    body = "\n".join(code)
    assert "[switch]$Install" in body
    assert body.index("if (-not $Install)") < body.index("winget install")
    assert "$packageId = 'JannisX11.Blockbench'" in body
    assert "winget install --exact --id $packageId --source winget" in body
